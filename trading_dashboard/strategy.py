"""紅K順風車策略引擎（規範：docs/volatility_framework.md §3 進場 / §4 出場）。

點火判定（is_ignition / ignition_tag）是唯一事實來源，供本引擎、
回測（backtest.ignition_events）與今日點火面板共用。皆為純函式。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

import numpy as np
import pandas as pd

from .config import (
    TW_ATR_TRAIL_MULT,
    TW_CHG_THR,
    TW_CLOSE_HIGH_EPS,
    TW_LIMIT_UP_THR,
    TW_MIN_ROWS,
    TW_SNR_TREND,
    TW_SNR_WARN_FLOOR,
    TW_VOL_MULT,
)


class TailwindSeries(NamedTuple):
    """引擎所需全部陣列（欄位回退階梯已於 prepare_series 處理）。"""

    index: pd.DatetimeIndex
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    ret1: np.ndarray
    volma20: np.ndarray
    atr14: np.ndarray
    dispday: np.ndarray
    atr5_pct: np.ndarray
    atr14_pct: np.ndarray
    atr14_pct_p80: np.ndarray
    atr14_pct_p80_120: np.ndarray
    snr: np.ndarray
    snr5: np.ndarray
    retstd: np.ndarray
    retstd_p60: np.ndarray
    flip: np.ndarray
    close20high: np.ndarray


def _fin(x: float | None) -> bool:
    return x is not None and bool(np.isfinite(x))


def _column_or_none(df: pd.DataFrame, name: str) -> np.ndarray | None:
    return df[name].to_numpy(float) if name in df.columns else None


def _column(df: pd.DataFrame, name: str, fallback: np.ndarray) -> np.ndarray:
    arr = _column_or_none(df, name)
    return arr if arr is not None else fallback


def prepare_series(df: pd.DataFrame) -> TailwindSeries:
    """欄位回退階梯的唯一實作：策略欄位缺席時退回可用近似值。

    Ret1 缺 → 由收盤補算；量基準 Vol_MA20_clean → Vol_MA20 → rolling(20)；
    ATR14_clean → ATR14 → NaN；DispDay 缺 → 全 False。
    """
    n = len(df)
    close = df["Close"].to_numpy(float)
    volume = df["Volume"].to_numpy(float)
    nan = np.full(n, np.nan)

    ret1 = _column_or_none(df, "Ret1")
    if ret1 is None:
        ret1 = np.concatenate([[np.nan], (close[1:] / close[:-1] - 1) * 100]) if n > 1 else np.array([np.nan])
    volma20 = _column_or_none(df, "Vol_MA20_clean")
    if volma20 is None:
        volma20 = _column_or_none(df, "Vol_MA20")
    if volma20 is None:
        volma20 = pd.Series(volume).rolling(20).mean().to_numpy()
    atr14 = _column_or_none(df, "ATR14_clean")
    if atr14 is None:
        atr14 = _column(df, "ATR14", nan)
    dispday = df["DispDay"].to_numpy(bool) if "DispDay" in df.columns else np.zeros(n, bool)
    if "Close20High" in df.columns:
        close20high = df["Close20High"].to_numpy(bool)
    else:
        close20high = close >= pd.Series(close).rolling(20).max().to_numpy()

    return TailwindSeries(
        index=df.index,
        open=df["Open"].to_numpy(float),
        high=df["High"].to_numpy(float),
        low=df["Low"].to_numpy(float),
        close=close,
        volume=volume,
        ret1=ret1,
        volma20=volma20,
        atr14=atr14,
        dispday=dispday,
        atr5_pct=_column(df, "ATR5_pct", nan),
        atr14_pct=_column(df, "ATR14_pct", nan),
        atr14_pct_p80=_column(df, "ATR14_pct_p80", nan),
        atr14_pct_p80_120=_column(df, "ATR14_pct_p80_120", nan),
        snr=_column(df, "SNR_t", nan),
        snr5=_column(df, "SNR_t5", nan),
        retstd=_column(df, "RetStd20", nan),
        retstd_p60=_column(df, "RetStd20_p60", nan),
        flip=_column(df, "FlipRate10", nan),
        close20high=close20high,
    )


def is_ignition(
    s: TailwindSeries,
    i: int,
    *,
    chg_thr: float = TW_CHG_THR,
    vol_mult: float = TW_VOL_MULT,
    limit_up_thr: float = TW_LIMIT_UP_THR,
    require_close_high: bool = True,
) -> bool:
    """點火判定唯一事實來源（§3）：

    Ⓑ 鎖漲停：漲 ≥ limit_up_thr%（可選 收=最高）→ 量不論、不要求收紅
       （台股鎖漲停量被機械性壓縮，涵蓋一字/跳空鎖死）
    Ⓐ 出量突破：漲 ≥ chg_thr% 且 量 ≥ vol_mult×20日均量 且 收紅實體。
       volma>0 防護為三份平面副本的有意識統一（volma=0 時恆真會誤點火）。
    """
    if not (_fin(s.ret1[i]) and s.close[i] > 0):
        return False
    locked_limit = s.ret1[i] >= limit_up_thr and (
        (not require_close_high) or s.close[i] >= s.high[i] - TW_CLOSE_HIGH_EPS
    )
    vol_breakout = (
        _fin(s.volma20[i])
        and s.volma20[i] > 0
        and s.ret1[i] >= chg_thr
        and _fin(s.volume[i])
        and s.volume[i] >= vol_mult * s.volma20[i]
        and s.close[i] > s.open[i]
    )
    return bool(locked_limit or vol_breakout)


def ignition_tag(
    s: TailwindSeries,
    i: int,
    *,
    chg_thr: float = TW_CHG_THR,
    vol_mult: float = TW_VOL_MULT,
    limit_up_thr: float = TW_LIMIT_UP_THR,
) -> tuple[float | None, str]:
    """第 i 根的 (漲幅%, 點火型態標籤)。"""
    locked = _fin(s.ret1[i]) and s.ret1[i] >= limit_up_thr and s.close[i] >= s.high[i] - TW_CLOSE_HIGH_EPS
    vol_ok = (
        _fin(s.ret1[i])
        and _fin(s.volma20[i])
        and s.volma20[i] > 0
        and s.ret1[i] >= chg_thr
        and _fin(s.volume[i])
        and s.volume[i] >= vol_mult * s.volma20[i]
        and s.close[i] > s.open[i]
    )
    tag = "🔒鎖漲停+爆量" if (locked and vol_ok) else ("🔒鎖漲停(免量)" if locked else "🚀爆量突破")
    return (round(float(s.ret1[i]), 2) if _fin(s.ret1[i]) else None), tag


def _run_state_machine(
    s: TailwindSeries,
    *,
    chg_thr: float,
    vol_mult: float,
    atr_trail_mult: float,
    reentry_on_new_high: bool,
    limit_up_thr: float,
    require_close_high: bool,
    entry_filter: Callable[[int], bool] | None,
) -> tuple[list[dict], list[dict], np.ndarray, bool]:
    """進出場狀態機：買點取當日 Low、賣點取當日 High（圖表標記位置）。"""

    def _fire(i: int) -> bool:
        return is_ignition(
            s, i, chg_thr=chg_thr, vol_mult=vol_mult, limit_up_thr=limit_up_thr, require_close_high=require_close_high
        )

    n = len(s.close)
    buys: list[dict] = []
    sells: list[dict] = []
    trail = np.full(n, np.nan)
    in_pos, peak = False, np.nan

    for i in range(n):
        if s.dispday[i]:
            continue  # 處置日不進不出、不更新峰值（trail 留 NaN）
        if not in_pos:
            reason = None
            if _fire(i) and not (i > 0 and _fire(i - 1)):
                reason = "第一根紅K"
            elif reentry_on_new_high and s.close20high[i]:
                reason = "20日新高再進場"
            if reason and entry_filter is not None and not entry_filter(i):
                reason = None  # 額外進場濾網（研究/回測用；預設 None 不影響）
            if reason and _fin(s.atr14[i]):
                in_pos, peak = True, s.close[i]
                trail[i] = peak - atr_trail_mult * s.atr14[i]
                buys.append({"date": s.index[i], "price": float(s.low[i]), "reason": reason})
        else:
            peak = max(peak, s.close[i])
            tr = peak - atr_trail_mult * s.atr14[i] if _fin(s.atr14[i]) else np.nan
            trail[i] = tr
            exit_trail = _fin(tr) and s.close[i] < tr
            exit_regime = (
                _fin(s.snr[i])
                and _fin(s.snr[i - 1])
                and s.snr[i] < 0
                and s.snr[i - 1] >= 0
                and _fin(s.retstd[i])
                and _fin(s.retstd_p60[i])
                and s.retstd[i] >= s.retstd_p60[i]
            )
            if exit_trail or exit_regime:
                reasons = (["性質切換SNR<0"] if exit_regime else []) + (["2×ATR移動停利"] if exit_trail else [])
                sells.append({"date": s.index[i], "price": float(s.high[i]), "reason": "／".join(reasons)})
                in_pos, peak = False, np.nan

    return buys, sells, trail, in_pos


def _collect_warns(s: TailwindSeries) -> list[dict]:
    """警示層（§4，不觸發出場）：波動降溫、性質切換警示。"""
    warns_map: dict = {}
    n = len(s.close)
    for i in range(2, n):
        values = (s.atr5_pct[i], s.atr14_pct[i], s.atr5_pct[i - 1], s.atr14_pct[i - 1], s.atr5_pct[i - 2])
        if all(_fin(x) for x in values) and (
            s.atr5_pct[i] < s.atr14_pct[i]
            and s.atr5_pct[i - 1] >= s.atr14_pct[i - 1]
            and s.atr5_pct[i] < s.atr5_pct[i - 1] < s.atr5_pct[i - 2]
        ):
            warns_map.setdefault(s.index[i], []).append("波動降溫")
    for i in range(1, n):
        shift_values = (s.snr5[i], s.snr5[i - 1], s.atr14_pct[i], s.atr14_pct_p80_120[i])
        if (
            all(_fin(x) for x in shift_values)
            and s.snr5[i - 1] > TW_SNR_TREND
            and s.snr5[i] < TW_SNR_WARN_FLOOR
            and s.atr14_pct[i] >= s.atr14_pct_p80_120[i]
        ):
            warns_map.setdefault(s.index[i], []).append("性質切換警示")
    high = pd.Series(s.high, index=s.index)
    return [{"date": t, "price": float(high.loc[t]), "reason": "／".join(rs)} for t, rs in sorted(warns_map.items())]


def _quadrant(snr_last: float, energy_high: bool) -> str:
    """§2 象限：SNR 方向純度 × ATR 能量位階。"""
    if not _fin(snr_last):
        return "—"
    if snr_last >= TW_SNR_TREND and energy_high:
        return "單邊行情（抱緊+雷達）"
    if snr_last >= TW_SNR_TREND:
        return "緩漲趨勢（沿5日線）"
    if energy_high:
        return "雙向絞殺（縮部位/離場）"
    return "休眠盤整（觀察）"


def _round2(x: float) -> float | None:
    return round(float(x), 2) if _fin(x) else None


def _latest_status(s: TailwindSeries, accel: pd.Series, in_pos: bool) -> dict:
    energy_high = _fin(s.atr14_pct[-1]) and _fin(s.atr14_pct_p80[-1]) and s.atr14_pct[-1] >= s.atr14_pct_p80[-1]
    return {
        "atr5_pct": _round2(s.atr5_pct[-1]),
        "atr14_pct": _round2(s.atr14_pct[-1]),
        "snr": _round2(s.snr[-1]),
        "flip_pct": round(float(s.flip[-1]) * 100) if _fin(s.flip[-1]) else None,
        "accel": bool(accel.iloc[-1]),
        "in_pos": in_pos,
        "quad": _quadrant(s.snr[-1], energy_high),
    }


def red_k_tailwind_signals(
    df: pd.DataFrame | None,
    chg_thr: float = TW_CHG_THR,
    vol_mult: float = TW_VOL_MULT,
    atr_trail_mult: float = TW_ATR_TRAIL_MULT,
    reentry_on_new_high: bool = False,
    limit_up_thr: float = TW_LIMIT_UP_THR,
    require_close_high: bool = True,
    entry_filter: Callable[[int], bool] | None = None,
) -> dict | None:
    """策略「紅K順風車」買賣點標記（狀態機：進場→出場成對）。

    進場（flat 時）——第一根紅K（前一根未觸發才算第一根）：見 is_ignition。
    出場（持倉時，先觸發者）：
      交易倉：收盤跌破「進場後最高收盤 − atr_trail_mult×ATR14」→ 2×ATR 移動停利
      核心倉：20日SNR 由正轉負(跌破0) 且 RetStd20 位於高檔 → 性質切換SNR<0
    警示層（不觸發出場，另存 warns）：波動降溫／性質切換警示。
    背景：波動加速＝ATR5%>ATR14% 且 ATR14% ≥ 一年P80 → accel_mask。

    回傳 {buys, sells, warns, accel_mask, trail, latest}；資料不足回 None。
    """
    if df is None or len(df) < TW_MIN_ROWS:
        return None
    s = prepare_series(df)
    buys, sells, trail, in_pos = _run_state_machine(
        s,
        chg_thr=chg_thr,
        vol_mult=vol_mult,
        atr_trail_mult=atr_trail_mult,
        reentry_on_new_high=reentry_on_new_high,
        limit_up_thr=limit_up_thr,
        require_close_high=require_close_high,
        entry_filter=entry_filter,
    )
    accel = pd.Series((s.atr5_pct > s.atr14_pct) & (s.atr14_pct >= s.atr14_pct_p80), index=s.index).fillna(False)
    return {
        "buys": buys,
        "sells": sells,
        "warns": _collect_warns(s),
        "accel_mask": accel,
        "trail": pd.Series(trail, index=s.index),
        "latest": _latest_status(s, accel, in_pos),
    }
