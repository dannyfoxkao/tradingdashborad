"""技術指標計算與研判。

網格牆與選股雷達共用同一套研判邏輯，確保不分歧。皆為純函式，可單元測試。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import (
    ALPHA_BETA_MAX,
    ALPHA_BETA_MIN,
    ALPHA_WINDOW,
    MA_WINDOWS,
    MIN_TREND_ROWS,
    TREND_FLAT_SLOPE,
    TREND_SLOPE_LOOKBACK,
    TURN_MA_WINDOWS,
    VOL_BASE_WINDOW,
    VOL_MA_WINDOWS,
    VOL_SHRINK_RATIO,
    VOL_SHRINK_Z,
    VOL_STD_WINDOW,
    VOL_SURGE_RATIO,
    VOL_SURGE_Z,
    VOL_UP_RATIO,
)

INSUFFICIENT_TREND = {"label": "資料不足", "bg": "#37474f", "icon": "⏳", "rank": 5, "slope": 0.0}


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """加上價格均線、量能/金額均線與量能標準差欄位。"""
    df = df.copy()
    for w in MA_WINDOWS:
        df[f"MA{w}"] = df["Close"].rolling(w).mean()
    for w in VOL_MA_WINDOWS:
        df[f"Vol_MA{w}"] = df["Volume"].rolling(w).mean()
    for w in TURN_MA_WINDOWS:
        df[f"Turn_MA{w}"] = df["Turnover"].rolling(w).mean()
    df["Vol_Std20"] = df["Volume"].rolling(VOL_STD_WINDOW).std()
    return df


def classify_trend(df: pd.DataFrame | None) -> dict | None:
    """回傳趨勢分類 dict：{label, bg, icon, rank, slope}；rank 越小越強(0=強多)。

    df 為 None 回傳 None；列數不足（MA20 尚未成形）回傳「資料不足」標籤，
    避免新上市股因 NaN 比較被誤判為「震盪(中性)」。
    """
    if df is None:
        return None
    if len(df) < MIN_TREND_ROWS:
        return dict(INSUFFICIENT_TREND)

    latest = df.iloc[-1]
    c, m5, m20, m60 = latest["Close"], latest["MA5"], latest["MA20"], latest["MA60"]
    if pd.isna(m5) or pd.isna(m20):
        return dict(INSUFFICIENT_TREND)

    # 排列分 0~3（MA60 未成形時該比較為 False，自動只計短中期）
    align = int(c > m5) + int(m5 > m20) + int(m20 > m60)
    ma20_ref = df["MA20"].iloc[-TREND_SLOPE_LOOKBACK]
    slope = ((m20 - ma20_ref) / ma20_ref * 100) if (pd.notna(ma20_ref) and ma20_ref > 0) else 0.0

    if align == 3 and slope > 0:
        return {"label": "強多", "bg": "#2e7d32", "icon": "🟢", "rank": 0, "slope": slope}
    if align >= 2 and slope >= TREND_FLAT_SLOPE:
        return {"label": "震盪(偏多)", "bg": "#f57c00", "icon": "🟡", "rank": 1, "slope": slope}
    if align <= 1 and slope < 0:
        return {"label": "弱勢", "bg": "#b71c1c", "icon": "🔴", "rank": 4, "slope": slope}
    if slope >= 0:
        return {"label": "震盪(中性)", "bg": "#546e7a", "icon": "⚪", "rank": 3, "slope": slope}
    return {"label": "震盪(偏空)", "bg": "#455a64", "icon": "🟠", "rank": 2, "slope": slope}


def compute_alpha(df: pd.DataFrame | None, bench: pd.DataFrame | None) -> tuple[float | None, float | None]:
    """Beta 調整後 20 日超額報酬，回傳 (alpha_val, beta)；資料不足回傳 (None, None)。"""
    if bench is None or df is None or len(bench) < ALPHA_WINDOW:
        return None, None
    joined = df[["Close"]].join(bench[["Close"]].rename(columns={"Close": "Bench"}), how="inner").dropna()
    if len(joined) < ALPHA_WINDOW:
        return None, None
    win = joined.iloc[-ALPHA_WINDOW:]
    s_ret = win["Close"].pct_change().dropna()
    b_ret = win["Bench"].pct_change().dropna()
    var_b = b_ret.var()
    beta = (np.cov(s_ret, b_ret)[0, 1] / var_b) if var_b > 0 else 1.0
    beta = float(np.clip(beta, ALPHA_BETA_MIN, ALPHA_BETA_MAX))
    s_cum = win["Close"].iloc[-1] / win["Close"].iloc[0] - 1
    b_cum = win["Bench"].iloc[-1] / win["Bench"].iloc[0] - 1
    return (s_cum - beta * b_cum) * 100, beta


def classify_volume(latest_vol: float, base_vol: float, vol_ma20: float, vol_std20: float) -> dict:
    """量能研判：量比(倍數)為主、Z-Score 為輔。回傳 {label, bg, icon, vr, z}。"""
    if pd.isna(latest_vol) or pd.isna(base_vol):
        return {"label": "量能不明", "bg": "#424242", "icon": "❔", "vr": float("nan"), "z": 0.0}

    vr = (latest_vol / base_vol) if base_vol > 0 else 1.0
    z = (latest_vol - vol_ma20) / vol_std20 if pd.notna(vol_std20) and vol_std20 > 0 else 0.0

    if vr >= VOL_SURGE_RATIO or z >= VOL_SURGE_Z:
        label, bg, icon = f"爆量 x{vr:.1f}", "#c62828", "💥"
    elif vr >= VOL_UP_RATIO:
        label, bg, icon = f"放量 x{vr:.1f}", "#ef6c00", "🔆"
    elif vr < VOL_SHRINK_RATIO or z <= VOL_SHRINK_Z:
        label, bg, icon = f"縮量 x{vr:.1f}", "#0277bd", "🧊"
    else:
        label, bg, icon = f"常態 x{vr:.1f}", "#424242", "💧"
    return {"label": label, "bg": bg, "icon": icon, "vr": vr, "z": z}


def volume_base(volume: pd.Series, disp_mask: pd.Series, window: int = VOL_BASE_WINDOW) -> float:
    """量能基準：近 window 個「非處置」交易日(不含今日)均量。"""
    nondisp = volume[~disp_mask].iloc[:-1]
    return nondisp.tail(window).mean() if len(nondisp) >= 1 else np.nan
