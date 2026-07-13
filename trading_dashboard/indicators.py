"""技術指標計算與研判。

網格牆與選股雷達共用同一套研判邏輯，確保不分歧。皆為純函式，可單元測試。
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from .config import (
    ALPHA_BETA_MAX,
    ALPHA_BETA_MIN,
    ALPHA_WINDOW,
    BEAR_LABELS,
    BULL_LABELS,
    MA_WINDOWS,
    MACD_FAST,
    MACD_SIGNAL,
    MACD_SLOW,
    MIN_TREND_ROWS,
    TREND_BOTTOM_SLOPE_MIN,
    TREND_FLAT_SLOPE,
    TREND_HEAD_SLOPE_MAX,
    TREND_SHORT_SLOPE_LOOKBACK,
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
    WEATHER_MIN_ROWS,
)

INSUFFICIENT_TREND = {"label": "資料不足", "bg": "#37474f", "icon": "⏳", "rank": 7, "slope": 0.0}


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


def ma_slope(df: pd.DataFrame, col: str, lookback: int) -> float:
    """col 均線從 lookback 根前至今的 % 變化；資料不足或無效回 0.0。"""
    if len(df) < lookback + 1:
        return 0.0
    ref = df[col].iloc[-1 - lookback]
    cur = df[col].iloc[-1]
    if pd.notna(ref) and ref > 0 and pd.notna(cur):
        return float((cur - ref) / ref * 100)
    return 0.0


def classify_trend(df: pd.DataFrame | None) -> dict | None:
    """回傳趨勢分類 dict：{label, bg, icon, rank, slope}；rank 越小越強(0=強多)。

    除月線(MA20)斜率外，另計短均(MA5/MA10)斜率，以「月線 vs 季線」結構位置
    把轉折點切成兩個獨立標籤：
      🌱 底部翻揚＝空頭結構(月線<季線)但短均同步上彎、站回 5 日、月線止跌
      🥀 頭部鈍化＝多頭結構(月線>季線)但短均同步下彎、月線動能熄火
    rank 為單調序：0強多/1底部翻揚/2震盪偏多/3中性/4頭部鈍化/5震盪偏空/6弱勢。
    df 為 None 回傳 None；列數不足回傳「資料不足」標籤（rank 7），
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
    slope = ma_slope(df, "MA20", TREND_SLOPE_LOOKBACK)
    slope5 = ma_slope(df, "MA5", TREND_SHORT_SLOPE_LOOKBACK)
    slope10 = ma_slope(df, "MA10", TREND_SHORT_SLOPE_LOOKBACK)
    short_up = slope5 > 0 and slope10 > 0  # 短均同步上彎
    short_down = slope5 < 0 and slope10 < 0  # 短均同步下彎
    above_season = pd.notna(m60) and m20 > m60  # 多頭結構：月線在季線上
    below_season = pd.notna(m60) and m20 < m60  # 空頭結構：月線在季線下

    if align == 3 and slope > 0:
        return {"label": "強多", "bg": "#2e7d32", "icon": "🟢", "rank": 0, "slope": slope}
    if below_season and short_up and c > m5 and slope >= TREND_BOTTOM_SLOPE_MIN:
        return {"label": "底部翻揚", "bg": "#00897b", "icon": "🌱", "rank": 1, "slope": slope}
    if above_season and align >= 2 and short_down and slope < TREND_HEAD_SLOPE_MAX:
        return {"label": "頭部鈍化", "bg": "#8d6e63", "icon": "🥀", "rank": 4, "slope": slope}
    if align >= 2 and slope >= TREND_FLAT_SLOPE:
        return {"label": "震盪(偏多)", "bg": "#f57c00", "icon": "🟡", "rank": 2, "slope": slope}
    if align <= 1 and slope < 0:
        return {"label": "弱勢", "bg": "#b71c1c", "icon": "🔴", "rank": 6, "slope": slope}
    if slope >= 0:
        return {"label": "震盪(中性)", "bg": "#546e7a", "icon": "⚪", "rank": 3, "slope": slope}
    return {"label": "震盪(偏空)", "bg": "#455a64", "icon": "🟠", "rank": 5, "slope": slope}


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
    z = (latest_vol - vol_ma20) / vol_std20 if (pd.notna(vol_std20) and vol_std20 > 0) else 0.0

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


def macd(
    close: pd.Series, fast: int = MACD_FAST, slow: int = MACD_SLOW, signal: int = MACD_SIGNAL
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """標準 MACD：回傳 (DIF, DEA, 柱狀OSC)。"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    return dif, dea, dif - dea


def classify_market_weather(df: pd.DataFrame | None) -> dict | None:
    """大盤天氣濾鏡：安全/危險區 ← 收盤 vs 月線(20MA)；風強弱 ← MACD 柱狀方向。

      安全區+風變強 → 💨強風 ｜ 安全區+風減弱 → 🌀亂流
      危險區+風變強 → 🌬️陣風 ｜ 危險區+風減弱 → 🌫️無風
    回傳 dict：{weather, icon, bg, zone, wind, action, mind}；資料不足回 None。
    """
    if df is None or len(df) < WEATHER_MIN_ROWS:
        return None
    close = df["Close"].astype(float)
    ma20 = close.rolling(20).mean()
    _, _, hist = macd(close)
    if pd.isna(ma20.iloc[-1]) or pd.isna(hist.iloc[-1]) or pd.isna(hist.iloc[-2]):
        return None
    safe = close.iloc[-1] >= ma20.iloc[-1]  # 安全區：站上月線
    macd_up = hist.iloc[-1] > hist.iloc[-2]  # 風變強：MACD 柱狀往上

    if safe and macd_up:
        return {
            "weather": "強風",
            "icon": "💨",
            "bg": "#2e7d32",
            "zone": "安全區 (站上月線20MA)",
            "wind": "風變強 (MACD往上)",
            "action": "積極追漲 or 積極布局",
            "mind": "股票漲勢容易延續！短線可積極",
        }
    if safe and not macd_up:
        return {
            "weather": "亂流",
            "icon": "🌀",
            "bg": "#f57c00",
            "zone": "安全區 (站上月線20MA)",
            "wind": "風減弱 (MACD往下)",
            "action": "短線嚴守紀律 or 波段佈局",
            "mind": "股票震盪變大，嚴守紀律",
        }
    if not safe and macd_up:
        return {
            "weather": "陣風",
            "icon": "🌬️",
            "bg": "#0277bd",
            "zone": "危險區 (跌破月線20MA)",
            "wind": "風變強 (MACD往上)",
            "action": "短線試單 or 波段佈局",
            "mind": "股票漲勢不易延續，容易回檔",
        }
    return {
        "weather": "無風",
        "icon": "🌫️",
        "bg": "#455a64",
        "zone": "危險區 (跌破月線20MA)",
        "wind": "沒風 (MACD往下)",
        "action": "短線休息 or 波段佈局",
        "mind": "股票易跌，休息至上",
    }


def compute_momentum(labels: Iterable[str]) -> dict:
    """族群多空占比（🧭 族群動能）；「資料不足」不列入分母。"""
    counted = [lb for lb in labels if lb != INSUFFICIENT_TREND["label"]]
    total = len(counted)
    bull = sum(1 for lb in counted if lb in BULL_LABELS)
    bear = sum(1 for lb in counted if lb in BEAR_LABELS)
    return {
        "bull": bull,
        "bear": bear,
        "total": total,
        "bull_pct": (bull / total * 100) if total else 0.0,
        "bear_pct": (bear / total * 100) if total else 0.0,
    }
