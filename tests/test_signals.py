"""交易一致性訊號（signals.evaluate_signals）的單元測試。

以手工指定均線/量能欄位的合成資料，逐一命中每個買訊/賣警條件。
基準框架刻意設計為「不觸發任何訊號」（除了恆真的三日沒破低，
以遞減 Low 關閉），再依測項覆寫欄位。
"""

import pandas as pd
import pytest

from trading_dashboard.signals import evaluate_signals


def _base_df(n: int = 30) -> pd.DataFrame:
    """基準：緩跌均線（避免多頭回測）、量能常態、收盤在區間上緣、Low 遞減。"""
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    df = pd.DataFrame(
        {
            "Open": 100.0,
            "High": 102.0,
            "Low": [99.0 - 0.1 * i for i in range(n)],  # 遞減 → 不觸發「三日沒破低」
            "Close": 101.0,
            "Volume": 1000.0,
            "MA5": 101.5,
            "MA10": 101.0,
            "MA20": 98.0,  # 收盤(101)在月線上 → 不觸發 S8/B3
            "MA60": 100.0,
            "Vol_MA20": 1000.0,
        },
        index=idx,
    )
    # 均線微幅下彎：slope5/slope10/slope20 皆 < 0（關閉多頭回測）
    df.iloc[-4, df.columns.get_loc("MA5")] = 101.6
    df.iloc[-4, df.columns.get_loc("MA10")] = 101.1
    df.iloc[-6, df.columns.get_loc("MA20")] = 98.1
    return df


def _set(df, col, iloc, value):
    df.iloc[iloc, df.columns.get_loc(col)] = value


def test_insufficient_rows_returns_none():
    assert evaluate_signals(None) is None
    assert evaluate_signals(_base_df().head(5)) is None


def test_base_frame_triggers_nothing():
    sig = evaluate_signals(_base_df())
    assert sig["buys"] == []
    assert sig["sells"] == []


# ── 買訊 ──


def test_buy_breakout_first_bar():
    df = _base_df()
    _set(df, "Close", -2, 97.0)  # 昨收在月線(98)下
    _set(df, "Close", -1, 99.0)  # 今收站上月線
    sig = evaluate_signals(df)
    assert "突破首根" in sig["buys"]


def test_buy_volume_surge_and_disposition_suppression():
    df = _base_df()
    _set(df, "Volume", -1, 2000.0)  # vr = 2.0
    assert any(b.startswith("出量") for b in evaluate_signals(df)["buys"])
    assert not any(b.startswith("出量") for b in evaluate_signals(df, in_disp=True)["buys"])


def test_buy_three_days_holding_low():
    df = _base_df()
    _set(df, "Low", -3, 99.0)
    _set(df, "Low", -2, 99.0)
    _set(df, "Low", -1, 99.5)
    sig = evaluate_signals(df)
    assert "三日沒破低" in sig["buys"]


def test_buy_bullish_retest():
    df = _base_df()
    # 三線同步向上
    _set(df, "MA5", -4, 100.0)
    _set(df, "MA5", -1, 101.0)
    _set(df, "MA10", -4, 99.5)
    _set(df, "MA10", -1, 100.5)
    _set(df, "MA20", -6, 99.0)
    _set(df, "MA20", -1, 100.0)
    _set(df, "Close", -1, 102.0)  # bias5 = (102-101)/101 ≈ +1% ∈ [-3, 2]
    sig = evaluate_signals(df)
    assert "多頭回測買點" in sig["buys"]


def test_buy_congestion_breakout():
    df = _base_df()
    # 均線糾結（帶寬 < 2%）+ 出量
    _set(df, "MA5", -1, 100.5)
    _set(df, "MA10", -1, 100.0)
    _set(df, "MA20", -1, 101.0)
    _set(df, "Close", -1, 100.8)
    _set(df, "Volume", -1, 2000.0)
    sig = evaluate_signals(df)
    assert "糾結放量" in sig["buys"]


# ── 賣警 ──


def test_sell_high_dark_candle():
    df = _base_df()
    _set(df, "Open", -1, 120.0)
    _set(df, "Close", -1, 114.0)  # 實體 5% 長黑
    _set(df, "MA20", -1, 100.0)  # bias20 = +14%
    sig = evaluate_signals(df)
    assert "高位大黑K" in sig["sells"]


def test_sell_soaring_stock_breaks_ma5():
    df = _base_df()
    _set(df, "MA20", -6, 100.0)
    _set(df, "MA20", -1, 103.0)  # slope20 = 3% 飆股
    _set(df, "MA5", -2, 110.0)
    _set(df, "MA5", -1, 110.0)
    _set(df, "Close", -2, 108.0)  # 連兩日收在 5 日線下
    _set(df, "Close", -1, 107.0)
    sig = evaluate_signals(df)
    assert "飆股破5日未站回" in sig["sells"]


def test_sell_slow_rise_breaks_ma20():
    df = _base_df()
    _set(df, "MA20", -6, 100.0)
    _set(df, "MA20", -2, 100.5)
    _set(df, "MA20", -1, 100.5)  # slope20 = 0.5% 緩漲
    _set(df, "Close", -2, 99.0)  # 連兩日收在月線下
    _set(df, "Close", -1, 98.5)
    sig = evaluate_signals(df)
    assert "緩漲破月線未站回" in sig["sells"]


def test_sell_two_weak_closes():
    df = _base_df()
    for i in (-2, -1):
        _set(df, "Open", i, 102.0)
        _set(df, "High", i, 103.0)
        _set(df, "Low", i, 99.0)
        _set(df, "Close", i, 100.0)  # 收黑且收在區間下緣 25% < 40%
    sig = evaluate_signals(df)
    assert "連兩日收弱" in sig["sells"]


def test_sell_overheat():
    df = _base_df()
    _set(df, "MA5", -1, 100.0)
    _set(df, "Close", -1, 111.0)  # bias5 = +11% ≥ 10%
    sig = evaluate_signals(df)
    assert "短線過熱" in sig["sells"]


def test_bias_values_reported():
    df = _base_df()
    sig = evaluate_signals(df)
    assert sig["bias5"] == pytest.approx((101.0 - 101.5) / 101.5 * 100, abs=0.1)
    assert sig["bias20"] == pytest.approx((101.0 - 98.0) / 98.0 * 100, abs=0.1)
