"""vol_framework（還原股價＋處置剔除法策略欄位）的單元測試。

規範文件：docs/volatility_framework.md §2/§5。
"""

import numpy as np
import pandas as pd

from trading_dashboard.vol_framework import STRATEGY_COLUMNS, apply_vol_framework, back_adjust


def _ohlcv(closes, highs=None, lows=None, vols=None, start="2026-01-05"):
    n = len(closes)
    idx = pd.bdate_range(start, periods=n)
    closes = [float(c) for c in closes]
    return pd.DataFrame(
        {
            "Open": closes,
            "High": highs if highs is not None else [c + 1 for c in closes],
            "Low": lows if lows is not None else [c - 1 for c in closes],
            "Close": closes,
            "Volume": vols if vols is not None else [1000.0] * n,
        },
        index=idx,
    )


def _win(start, end):
    return {"start": pd.Timestamp(start), "end": pd.Timestamp(end), "measure": "分盤撮合", "market": "上市"}


# ── back_adjust 還原股價 ──


def test_back_adjust_split_backmultiplies_prior_ohlc_and_divides_volume():
    df = _ohlcv([100.0, 100.0, 50.0, 50.0])  # 1拆2：跳空比例 0.5

    out = back_adjust(df)

    assert out["Close"].tolist() == [50.0, 50.0, 50.0, 50.0]
    assert out["Open"].iloc[0] == 50.0
    assert out["Volume"].iloc[0] == 2000.0  # 前期量 ÷0.5（股數放大 → 還原可比）
    assert out["Volume"].iloc[2] == 1000.0  # 事件日之後不動


def test_back_adjust_within_daily_limit_untouched():
    df = _ohlcv([100.0, 109.0, 100.0, 91.0])  # ±10% 內

    out = back_adjust(df)

    assert out["Close"].tolist() == [100.0, 109.0, 100.0, 91.0]


def test_back_adjust_boundary_not_triggered():
    df = _ohlcv([100.0, 88.0])  # g=0.88 恰好在邊界 → 不視為公司行為

    out = back_adjust(df)

    assert out["Close"].iloc[0] == 100.0


def test_back_adjust_short_df_noop_and_input_not_mutated():
    df = _ohlcv([100.0])
    assert back_adjust(df)["Close"].iloc[0] == 100.0

    df2 = _ohlcv([100.0, 100.0, 50.0])
    original = df2["Close"].copy()
    back_adjust(df2)
    assert df2["Close"].equals(original)  # 不可變：不就地修改輸入


# ── apply_vol_framework 處置剔除法 ──


def test_all_strategy_columns_present():
    df = _ohlcv([100.0 + i * 0.1 for i in range(70)])

    out = apply_vol_framework(df, [])

    for col in STRATEGY_COLUMNS:
        assert col in out.columns, col
    assert "DispDay" in out.columns


def test_disposition_days_flagged_and_nan():
    n = 40
    df = _ohlcv([100.0] * n)
    idx = df.index
    wins = [_win(idx[10], idx[14])]

    out = apply_vol_framework(df, wins)

    assert bool(out["DispDay"].iloc[12])
    assert not bool(out["DispDay"].iloc[5])
    assert np.isnan(out["Ret1"].iloc[12])  # 處置日策略欄位為 NaN
    assert np.isnan(out["ATR14_clean"].iloc[12])


def test_seam_day_tr_uses_high_low_only():
    # 處置窗後首日大幅跳空：若 TR 誤用前收會被灌爆，剔除法規定接縫日 TR=H−L
    closes = [100.0] * 20 + [200.0] * 20  # 窗內「假跳空」到 200
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    df = _ohlcv(closes, highs, lows)
    idx = df.index
    wins = [_win(idx[15], idx[19])]  # 剔除跳空前的過渡段

    out = apply_vol_framework(df, wins)

    # 接縫日之後 ATR5（min_periods=3）應維持 H−L=2 的量級，而非被 +100 跳空污染
    atr5_pct = out["ATR5_pct"].iloc[25]
    assert abs(atr5_pct - (2.0 / 200.0 * 100)) < 0.2
    # 跨縫日報酬設 NaN
    assert np.isnan(out["Ret1"].iloc[20])


def test_close20high_bool_dtype_and_false_on_disp():
    n = 40
    df = _ohlcv([100.0 + i for i in range(n)])  # 一路創高
    idx = df.index
    wins = [_win(idx[30], idx[32])]

    out = apply_vol_framework(df, wins)

    assert out["Close20High"].dtype == bool
    assert bool(out["Close20High"].iloc[-1])
    assert not bool(out["Close20High"].iloc[31])  # 處置日補 False


def test_fallback_when_clean_rows_below_min():
    n = 15
    df = _ohlcv([100.0] * n)
    wins = [_win(df.index[0], df.index[-1])]  # 全期處置 → 剔除後 0 列

    out = apply_vol_framework(df, wins)

    assert not out["DispDay"].any()  # fallback：不剔除、DispDay 全 False


def test_vol_ma20_clean_excludes_disposition_volume():
    n = 40
    vols = [1000.0] * n
    for i in range(10, 15):
        vols[i] = 99999.0  # 處置期異常量
    df = _ohlcv([100.0] * n, vols=vols)
    idx = df.index
    wins = [_win(idx[10], idx[14])]

    out = apply_vol_framework(df, wins)

    assert abs(out["Vol_MA20_clean"].iloc[-1] - 1000.0) < 1e-9


def test_p80_forms_after_min_periods():
    df = _ohlcv([100.0 + (i % 7) for i in range(80)])

    out = apply_vol_framework(df, [])

    assert np.isnan(out["ATR14_pct_p80"].iloc[40])  # min_periods=60 未滿
    assert np.isfinite(out["ATR14_pct_p80"].iloc[-1])
