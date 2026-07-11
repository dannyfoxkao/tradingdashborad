"""FinMind 個股 / 大盤日線資料抓取。"""
from __future__ import annotations

import logging
import os

import numpy as np
import pandas as pd
import streamlit as st
from FinMind.data import DataLoader

from ..config import BENCHMARK_TTL, FINMIND_TTL, parse_stock_id
from .. import indicators

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


@st.cache_data(ttl=FINMIND_TTL)
def fetch_finmind_data(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    """抓取個股日線並加上技術指標欄位；失敗或無資料回傳 None。"""
    stock_id = parse_stock_id(ticker)
    try:
        df = init_finmind().taiwan_stock_daily(stock_id=stock_id, start_date=start, end_date=end)
    except Exception as e:  # FinMind 可能拋出多種錯誤；記錄後優雅降級
        logger.warning("FinMind 個股 %s 抓取失敗：%s", stock_id, e)
        return None

    if df is None or df.empty:
        return None

    df = df.rename(columns={
        "open": "Open", "max": "High", "min": "Low", "close": "Close",
        "Trading_Volume": "Volume", "Trading_money": "Turnover",
    })

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
def fetch_benchmark_data(start: str, end: str) -> pd.DataFrame | None:
    """抓取大盤（TAIEX）作為 Alpha 計算基準；失敗回傳 None。"""
    try:
        df = init_finmind().taiwan_stock_daily(stock_id="TAIEX", start_date=start, end_date=end)
    except Exception as e:
        logger.warning("FinMind 大盤(TAIEX) 抓取失敗：%s", e)
        return None

    if df is None or df.empty:
        return None

    df = df.rename(columns={"close": "Close"})
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    return df[["Close"]]
