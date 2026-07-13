"""波動率框架資料前處理（規範：docs/volatility_framework.md）。

- ``back_adjust``：還原股價——台股 ±10% 日限外的收盤跳動視為除權/分割等
  公司行為，將事件日之前的 OHLC 乘上跳空比例（量除以比例）使序列連續。
- ``apply_vol_framework``：處置期【剔除法】（§5）＋策略欄位（§2）：
    ① 整段移除處置交易日、時間軸縫合
    ② 接縫日 TR 只用當日高低價（不用前收，避免假跳空）
    ③ 跨縫日報酬設 NaN、rolling 以 min_periods 跳過
  於暖身資料上計算後對齊回完整索引（處置日為 NaN）。

皆為純函式：處置窗以參數注入、不就地修改輸入，無網路/Streamlit 依賴。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import (
    BACK_ADJUST_DOWN,
    BACK_ADJUST_UP,
    VF_ATR_FAST,
    VF_ATR_SLOW,
    VF_C20HIGH,
    VF_ER,
    VF_FLIP,
    VF_MIN_CLEAN_ROWS,
    VF_P80_Q,
    VF_P80_WARN,
    VF_P80_YEAR,
    VF_RET_ROLL,
    VF_RETSTD_Q60,
    VF_SNR5,
    VF_VOLMA,
)

STRATEGY_COLUMNS: tuple[str, ...] = (
    "ATR5_pct",
    "ATR14_pct",
    "ATR14_clean",
    "ATR14_pct_p80",
    "ATR14_pct_p80_120",
    "Ret1",
    "RetMean20",
    "RetStd20",
    "RetStd20_p60",
    "SNR_t",
    "SNR_t5",
    "SNR_ER",
    "FlipRate10",
    "Vol_MA20_clean",
    "Close20High",
)


def back_adjust(df: pd.DataFrame) -> pd.DataFrame:
    """還原股價；回傳新 DataFrame（小額股息在日限內、不調整，影響甚微）。"""
    if df is None or len(df) < 2 or "Close" not in df.columns:
        return df
    close = df["Close"].to_numpy(float)
    adj = np.ones(len(close))
    for i in range(1, len(close)):
        c0, c1 = close[i - 1], close[i]
        if c0 > 0 and np.isfinite(c1) and np.isfinite(c0):
            gap = c1 / c0
            if gap < BACK_ADJUST_DOWN or gap > BACK_ADJUST_UP:  # 超出日限 → 公司行為/分割
                adj[:i] *= gap
    if not (adj != 1).any():
        return df
    df = df.copy()
    for col in ("Open", "High", "Low", "Close"):
        if col in df.columns:
            df[col] = df[col].to_numpy(float) * adj
    if "Volume" in df.columns:  # 分割使股數放大 → 還原前期量以可比
        df["Volume"] = df["Volume"].to_numpy(float) / np.where(adj == 0, 1.0, adj)
    return df


def _mask_from_windows(index: pd.DatetimeIndex, windows: list[dict]) -> pd.Series:
    mask = pd.Series(False, index=index)
    norm = index.normalize()
    for w in windows:
        mask |= (norm >= w["start"]) & (norm <= w["end"])
    return mask


def _clean_true_range(clean: pd.DataFrame, seam: pd.Series) -> pd.Series:
    """剔除後序列的 TR；接縫日只用當日高低價（§5 ②）。"""
    high, low, close = clean["High"], clean["Low"], clean["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    tr[seam] = (high - low)[seam]
    return tr


def _strategy_series(clean: pd.DataFrame, seam: pd.Series) -> dict[str, pd.Series]:
    """在剔除後的乾淨序列上計算全部策略欄位（§2）。"""
    close, volume = clean["Close"], clean["Volume"]
    tr = _clean_true_range(clean, seam)
    atr5 = tr.rolling(*VF_ATR_FAST).mean()
    atr14 = tr.rolling(*VF_ATR_SLOW).mean()
    atr5_pct = atr5 / close * 100
    atr14_pct = atr14 / close * 100

    ret1 = close.pct_change() * 100
    ret1[seam] = np.nan  # ③ 跨縫報酬設 NaN
    ret_mean20 = ret1.rolling(*VF_RET_ROLL).mean()
    ret_std20 = ret1.rolling(*VF_RET_ROLL).std()
    snr_t = ret_mean20 / ret_std20.replace(0, np.nan)  # SNR＝方向純度 mean/std

    sign = np.sign(ret1)
    flip = (sign != sign.shift(1)).where(ret1.notna() & ret1.shift(1).notna())
    er_window = VF_ER[0]
    snr_er = (close - close.shift(er_window)).abs() / close.diff().abs().rolling(
        er_window, min_periods=VF_ER[1]
    ).sum().replace(0, np.nan)  # Kaufman 效率比

    return {
        "ATR5_pct": atr5_pct,
        "ATR14_pct": atr14_pct,
        "ATR14_clean": atr14,
        "ATR14_pct_p80": atr14_pct.rolling(*VF_P80_YEAR).quantile(VF_P80_Q),
        "ATR14_pct_p80_120": atr14_pct.rolling(*VF_P80_WARN).quantile(VF_P80_Q),
        "Ret1": ret1,
        "RetMean20": ret_mean20,
        "RetStd20": ret_std20,
        "RetStd20_p60": ret_std20.rolling(*VF_P80_YEAR).quantile(VF_RETSTD_Q60),
        "SNR_t": snr_t,
        "SNR_t5": snr_t.rolling(*VF_SNR5).mean(),
        "SNR_ER": snr_er,
        "FlipRate10": flip.rolling(*VF_FLIP).mean(),
        "Vol_MA20_clean": volume.rolling(*VF_VOLMA).mean(),
        "Close20High": close >= close.rolling(*VF_C20HIGH).max(),
    }


def apply_vol_framework(df: pd.DataFrame, windows: list[dict]) -> pd.DataFrame:
    """加上策略欄位（處置剔除法）；回傳新 DataFrame，處置日欄位為 NaN、DispDay=True。"""
    df = df.copy()
    idx = df.index
    disp_mask = _mask_from_windows(idx, windows)

    keep = ~disp_mask
    if int(keep.sum()) < VF_MIN_CLEAN_ROWS:  # 剔除後資料過少 → 不剔除，避免全空
        keep = pd.Series(True, index=idx)
        disp_mask = pd.Series(False, index=idx)
    clean = df[keep]

    # 接縫偵測：clean 相鄰列在原始序列是否跳號（跳號＝中間被剔除＝接縫；第一列亦視為接縫）
    pos = np.where(keep.to_numpy())[0]
    is_seam = np.ones(len(pos), dtype=bool)
    is_seam[1:] = pos[1:] != pos[:-1] + 1
    seam = pd.Series(is_seam, index=clean.index)

    for name, series in _strategy_series(clean, seam).items():
        if name == "Close20High":  # bool 欄位：reindex 直接補 False，避免 object 降型警告
            df[name] = series.reindex(idx, fill_value=False).astype(bool)
        else:
            df[name] = series.reindex(idx)
    df["DispDay"] = disp_mask
    return df
