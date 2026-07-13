"""FinMind 個股 / 大盤日線資料抓取。"""

from __future__ import annotations

import logging
import os
import time

import numpy as np
import pandas as pd
import streamlit as st
from FinMind.data import DataLoader

from .. import indicators
from ..config import (
    BENCHMARK_TTL,
    FINMIND_RETRY_ATTEMPTS,
    FINMIND_RETRY_BACKOFF,
    FINMIND_TTL,
    parse_stock_id,
)

logger = logging.getLogger(__name__)


@st.cache_resource
def init_finmind() -> DataLoader:
    """建立 FinMind DataLoader（單例）。若提供 FINMIND_TOKEN 則登入以提高速率上限。"""
    api = DataLoader()
    token = os.environ.get("FINMIND_TOKEN")
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


@st.cache_data(ttl=FINMIND_TTL)
def fetch_finmind_data(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    """抓取個股日線並加上技術指標欄位；失敗或無資料回傳 None。"""
    stock_id = parse_stock_id(ticker)
    df = _fetch_daily_with_retry(stock_id, start, end)
    if df is None or df.empty:
        return None

    df = df.rename(
        columns={
            "open": "Open",
            "max": "High",
            "min": "Low",
            "close": "Close",
            "Trading_Volume": "Volume",
            "Trading_money": "Turnover",
        }
    )

    # 量 / 額互補；皆缺時以 NaN 表示（不再偽造固定 1,000,000 量能）
    if "Turnover" not in df.columns:
        df["Turnover"] = df["Close"] * df["Volume"] if "Volume" in df.columns else np.nan
    if "Volume" not in df.columns:
        if "Turnover" in df.columns and df["Turnover"].sum() > 0:
            df["Volume"] = df["Turnover"] / df["Close"]
        else:
            df["Volume"] = np.nan

    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    return indicators.enrich(df)


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
