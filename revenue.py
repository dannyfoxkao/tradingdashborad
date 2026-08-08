# -*- coding: utf-8 -*-
"""月營收 YoY 動能（FinMind taiwan_stock_month_revenue，免費層可用）。

名詞：
  YoY(y,m) = 該月營收 / 去年同月營收 - 1
  創高      = 最新月 YoY 為近 12 個月最高
  連增      = 最近連續幾個月 YoY 逐月墊高（含最新月）
注意：月營收於次月 10 日前後公布，故最新月份通常落後當下 1 個月。
"""
import numpy as np
import pandas as pd
import streamlit as st

from data import api

SKIP_IDS = {"TAIEX", "TPEx"}          # 指數無營收


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_month_revenue(stock_id, start="2023-01-01"):
    """回傳 DataFrame[year, month, revenue]（依時間排序）；無資料回 None。"""
    if stock_id in SKIP_IDS:
        return None
    try:
        df = api.taiwan_stock_month_revenue(
            stock_id=stock_id, start_date=start,
            end_date=pd.Timestamp.today().strftime("%Y-%m-%d"))
    except Exception:
        return None
    if df is None or df.empty:
        return None
    df = df.rename(columns={"revenue_year": "year", "revenue_month": "month"})
    df = df[["year", "month", "revenue"]].astype({"year": int, "month": int, "revenue": float})
    return df.sort_values(["year", "month"]).reset_index(drop=True)


def yoy_metrics(rev):
    """由月營收算 YoY 動能。回傳 dict；資料不足回 None。
       {yoy, yoy_prev, streak, is_high, high_of, month_label, rev_high}"""
    if rev is None or len(rev) < 13:
        return None
    lut = {(int(r.year), int(r.month)): float(r.revenue) for r in rev.itertuples()}
    yoys = []                                     # [(y, m, yoy%)]
    for r in rev.itertuples():
        y, m, v = int(r.year), int(r.month), float(r.revenue)
        base = lut.get((y - 1, m))
        if base and base > 0 and np.isfinite(v):
            yoys.append((y, m, (v / base - 1) * 100))
    if len(yoys) < 4:
        return None

    ys = [x[2] for x in yoys]
    last_y, last_m, last = yoys[-1]
    win = ys[-12:]                                # 近 12 個月（不足則全取）
    is_high = last >= max(win) - 1e-9

    streak = 1                                    # 最近連續墊高的月數（含最新月）
    for k in range(len(ys) - 1, 0, -1):
        if ys[k] > ys[k - 1]:
            streak += 1
        else:
            break

    # 營收金額本身是否為近 12 個月新高
    revs = [float(r.revenue) for r in rev.itertuples()][-12:]
    rev_high = bool(revs and revs[-1] >= max(revs) - 1e-9)

    return {
        "yoy": round(last, 1),
        "yoy_prev": round(ys[-2], 1) if len(ys) >= 2 else None,
        "streak": int(streak),
        "is_high": bool(is_high),
        "high_of": len(win),
        "month_label": f"{last_y}/{last_m:02d}",
        "rev_high": rev_high,
    }


def pullback_state(df):
    """由日K判斷「拉回」狀態。回傳 dict；資料不足回 None。
       淺回：收盤<MA5 但仍站上 MA20（趨勢未壞，框架偏好的買點）
       深回：跌破 MA20 但仍在 MA60 之上
       破線：跌破 MA60"""
    if df is None or len(df) < 60:
        return None
    last = df.iloc[-1]
    c = float(last["Close"])
    ma5, ma20, ma60 = (float(last.get(k, np.nan)) for k in ("MA5", "MA20", "MA60"))
    if not np.isfinite(c) or not np.isfinite(ma20):
        return None
    hi20 = float(df["Close"].tail(20).max())
    from_high = (c / hi20 - 1) * 100 if hi20 > 0 else np.nan

    if np.isfinite(ma60) and c < ma60:
        state = "❌破季線"
    elif c < ma20:
        state = "🟠深回(破月線)"
    elif np.isfinite(ma5) and c < ma5:
        state = "🟢淺回(月線上)"
    else:
        state = "🔺強勢(未回)"
    return {"close": round(c, 2), "state": state,
            "from_high": round(from_high, 1) if np.isfinite(from_high) else None,
            "above_ma20": bool(c >= ma20)}
