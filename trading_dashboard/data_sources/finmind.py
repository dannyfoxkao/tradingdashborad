"""FinMind 個股 / 大盤日線資料抓取。"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from FinMind.data import DataLoader

from .. import indicators
from ..config import (
    BENCHMARK_TTL,
    FINMIND_RETRY_ATTEMPTS,
    FINMIND_RETRY_BACKOFF,
    FINMIND_TOKEN_FILE,
    FINMIND_TTL,
    FINMIND_WARMUP_DAYS,
    parse_stock_id,
)
from ..vol_framework import apply_vol_framework, back_adjust
from .disposition import fetch_disposition_map

logger = logging.getLogger(__name__)


def _load_finmind_token(path: Path | str = FINMIND_TOKEN_FILE) -> str:
    """讀取 FinMind API token：優先本地 finmind_token.json（api_token 鍵），其次環境變數。"""
    path = Path(path)
    try:
        if path.exists():
            token = (json.loads(path.read_text(encoding="utf-8")).get("api_token") or "").strip()
            if token:
                return token
    except (OSError, json.JSONDecodeError, AttributeError) as e:
        logger.warning("finmind_token.json 讀取失敗，改用環境變數：%s", e)
    return (os.environ.get("FINMIND_TOKEN") or "").strip()


@st.cache_resource
def init_finmind() -> DataLoader:
    """建立 FinMind DataLoader（單例）。有 token 則登入以提高速率上限。"""
    api = DataLoader()
    token = _load_finmind_token()
    if token:
        try:
            api.login_by_token(api_token=token)
            logger.info("FinMind 已以 API token 登入。")
        except Exception as e:  # FinMind 內部例外型別不一，僅記錄不中斷
            logger.warning("FinMind 登入失敗，改用匿名模式：%s", e)
    return api


def _fetch_daily_with_retry(stock_id: str, start: str, end: str) -> pd.DataFrame | None:
    """FinMind 日線抓取＋輕量重試（線性退避）；全部失敗回 None。"""
    for attempt in range(FINMIND_RETRY_ATTEMPTS):
        try:
            return init_finmind().taiwan_stock_daily(stock_id=stock_id, start_date=start, end_date=end)
        except Exception as e:  # FinMind 可能拋出多種錯誤；記錄後重試/降級
            logger.warning("FinMind %s 第 %d 次抓取失敗：%s", stock_id, attempt + 1, e)
            if attempt < FINMIND_RETRY_ATTEMPTS - 1:
                time.sleep(FINMIND_RETRY_BACKOFF * (attempt + 1))
    return None


def _normalise_columns(raw: pd.DataFrame) -> pd.DataFrame:
    """FinMind 原始欄位 → OHLCV/Turnover，date 設為排序後索引。"""
    df = raw.rename(
        columns={
            "open": "Open",
            "max": "High",
            "min": "Low",
            "close": "Close",
            "Trading_Volume": "Volume",
            "Trading_money": "Turnover",
        }
    )

    # 量 / 額互補；皆缺時以 NaN 表示（不偽造量能——點火等量能條件將保守地不觸發）
    if "Turnover" not in df.columns:
        df["Turnover"] = df["Close"] * df["Volume"] if "Volume" in df.columns else np.nan
    if "Volume" not in df.columns:
        if "Turnover" in df.columns and df["Turnover"].sum() > 0:
            df["Volume"] = df["Turnover"] / df["Close"]
        else:
            df["Volume"] = np.nan

    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def _compute_indicators(df: pd.DataFrame, stock_id: str) -> pd.DataFrame:
    """還原股價 → 基礎/重型指標 → 波動率框架策略欄位（處置剔除法）。"""
    df = back_adjust(df)
    df = indicators.enrich(df)
    df = indicators.enrich_heavy(df)
    windows = fetch_disposition_map().get(stock_id, [])
    return apply_vol_framework(df, windows)


@st.cache_data(ttl=FINMIND_TTL)
def fetch_finmind_data(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    """抓取個股日線並計算全套研判/策略指標欄位；失敗或無資料回傳 None。

    為讓 MA200 / 12 個月動能等長週期指標在顯示區左緣就成形，實際多抓
    FINMIND_WARMUP_DAYS 天暖身資料，指標算完後切回 [start, end]。
    """
    stock_id = parse_stock_id(ticker)
    fetch_start = (pd.to_datetime(start) - timedelta(days=FINMIND_WARMUP_DAYS)).strftime("%Y-%m-%d")
    raw = _fetch_daily_with_retry(stock_id, fetch_start, end)
    if raw is None or raw.empty:
        return None

    df = _compute_indicators(_normalise_columns(raw), stock_id)
    df = df[df.index >= pd.to_datetime(start)]
    return None if df.empty else df


@st.cache_data(ttl=BENCHMARK_TTL)
def fetch_index_close(stock_id: str, start: str, end: str) -> pd.DataFrame | None:
    """抓取指數（TAIEX 加權 / TPEx 櫃買）收盤序列；失敗回傳 None。"""
    df = _fetch_daily_with_retry(stock_id, start, end)
    if df is None or df.empty:
        return None

    df = df.rename(columns={"close": "Close"})
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    return df[["Close"]]


def fetch_benchmark_data(start: str, end: str) -> pd.DataFrame | None:
    """抓取大盤（TAIEX）作為 Alpha 計算基準；失敗回傳 None。"""
    return fetch_index_close("TAIEX", start, end)
