"""交易一致性訊號：純日線可自動化的買訊/賣警子集。

盤中/題材/情緒類條件屬人工 checklist，不在此。純函式，可單元測試。
  買訊：突破首根 / 出量 / 三日沒破低 / 多頭回測買點 / 糾結放量
  賣警：高位大黑K / 飆股破5日未站回 / 緩漲破月線未站回 / 連兩日收弱 / 短線過熱
"""

from __future__ import annotations

import pandas as pd

from .config import (
    SIGNAL_BAND_MAX_PCT,
    SIGNAL_DARK_BIAS20,
    SIGNAL_DARK_BODY_PCT,
    SIGNAL_MIN_ROWS,
    SIGNAL_OVERHEAT_BIAS5,
    SIGNAL_RETEST_BIAS5,
    SIGNAL_SLOW_SLOPE20,
    SIGNAL_STEEP_SLOPE20,
    SIGNAL_VOL_RATIO,
    SIGNAL_WEAK_CLOSE_POS,
    TREND_SHORT_SLOPE_LOOKBACK,
    TREND_SLOPE_LOOKBACK,
)
from .indicators import ma_slope


def _bias(close: float, ma: float) -> float:
    return (close - ma) / ma * 100 if (pd.notna(ma) and ma > 0) else 0.0


def _weak_close(row: pd.Series) -> bool:
    """收黑且收盤落在當日區間下緣（疑出貨）。"""
    rng = row["High"] - row["Low"]
    return row["Close"] < row["Open"] and rng > 0 and (row["Close"] - row["Low"]) / rng < SIGNAL_WEAK_CLOSE_POS


def _collect_buys(df, last, prev, slope5, slope10, slope20, bias5, vr, in_disp) -> list[str]:
    buys: list[str] = []
    # B3 突破首根：今日站上月線、昨日尚未（一個波段的第一根）
    if (
        pd.notna(last["MA20"])
        and pd.notna(prev["MA20"])
        and last["Close"] > last["MA20"]
        and prev["Close"] <= prev["MA20"]
    ):
        buys.append("突破首根")
    # B4 出量（處置中量價失真 → 不計）
    if not in_disp and vr >= SIGNAL_VOL_RATIO:
        buys.append(f"出量x{vr:.1f}")
    # B5 拉回三天沒破低：近三日低點逐日不破前低
    low = df["Low"]
    if low.iloc[-1] >= low.iloc[-2] >= low.iloc[-3]:
        buys.append("三日沒破低")
    # H2 均線多頭回測：三線同步向上 + 收盤貼近五日線(輕拉回)
    lo, hi = SIGNAL_RETEST_BIAS5
    if slope5 > 0 and slope10 > 0 and slope20 > 0 and lo <= bias5 <= hi:
        buys.append("多頭回測買點")
    # H3 糾結放量：均線收斂帶寬 < 上限 + 出量
    mas = (last["MA5"], last["MA10"], last["MA20"])
    if not in_disp and all(pd.notna(m) for m in mas) and last["Close"] > 0:
        band = (max(mas) - min(mas)) / last["Close"] * 100
        if band < SIGNAL_BAND_MAX_PCT and vr >= SIGNAL_VOL_RATIO:
            buys.append("糾結放量")
    return buys


def _collect_sells(last, prev, slope20, bias5, bias20) -> list[str]:
    sells: list[str] = []
    # S5 高位大黑K：高乖離 + 長黑實體
    body = (last["Open"] - last["Close"]) / last["Open"] * 100 if last["Open"] > 0 else 0.0
    if last["Close"] < last["Open"] and body >= SIGNAL_DARK_BODY_PCT and bias20 >= SIGNAL_DARK_BIAS20:
        sells.append("高位大黑K")
    # S7 飆股破5日未站回：強漲(月線斜率陡) + 連兩日收在5日下
    if (
        pd.notna(last["MA5"])
        and pd.notna(prev["MA5"])
        and slope20 >= SIGNAL_STEEP_SLOPE20
        and prev["Close"] < prev["MA5"]
        and last["Close"] < last["MA5"]
    ):
        sells.append("飆股破5日未站回")
    # S8 緩漲破月線未站回：緩多(月線未明顯下彎且非飆) + 連兩日收在月線下
    lo, hi = SIGNAL_SLOW_SLOPE20
    if (
        pd.notna(last["MA20"])
        and pd.notna(prev["MA20"])
        and lo < slope20 < hi
        and prev["Close"] < prev["MA20"]
        and last["Close"] < last["MA20"]
    ):
        sells.append("緩漲破月線未站回")
    # S4 連兩日收弱(疑出貨)
    if _weak_close(last) and _weak_close(prev):
        sells.append("連兩日收弱")
    # 過熱提醒：短線乖離過大
    if bias5 >= SIGNAL_OVERHEAT_BIAS5:
        sells.append("短線過熱")
    return sells


def evaluate_signals(df: pd.DataFrame | None, in_disp: bool = False) -> dict | None:
    """回傳 {buys:[...], sells:[...], bias5, bias20}；資料不足回 None。"""
    if df is None or len(df) < SIGNAL_MIN_ROWS:
        return None
    last, prev = df.iloc[-1], df.iloc[-2]
    slope20 = ma_slope(df, "MA20", TREND_SLOPE_LOOKBACK)
    slope5 = ma_slope(df, "MA5", TREND_SHORT_SLOPE_LOOKBACK)
    slope10 = ma_slope(df, "MA10", TREND_SHORT_SLOPE_LOOKBACK)
    bias5 = _bias(last["Close"], last["MA5"])
    bias20 = _bias(last["Close"], last["MA20"])
    vr = last["Volume"] / last["Vol_MA20"] if (pd.notna(last["Vol_MA20"]) and last["Vol_MA20"] > 0) else 1.0

    return {
        "buys": _collect_buys(df, last, prev, slope5, slope10, slope20, bias5, vr, in_disp),
        "sells": _collect_sells(last, prev, slope20, bias5, bias20),
        "bias5": round(bias5, 1),
        "bias20": round(bias20, 1),
    }
