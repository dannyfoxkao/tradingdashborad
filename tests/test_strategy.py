"""紅K順風車策略引擎（strategy.py）的單元測試。

以手工鋪策略欄位的合成資料精準命中每個分支；語義以平面版
analysis.red_k_tailwind_signals 為準（含實碼勘誤：買 Low 賣 High、
處置日凍結、同日雙出場理由順序、volma>0 統一防護）。
"""

import numpy as np
import pandas as pd

from trading_dashboard import strategy


def _df(n=30):
    """基準：完全不點火、無警示、休眠盤整。"""
    idx = pd.bdate_range("2026-01-05", periods=n)
    return pd.DataFrame(
        {
            "Open": np.full(n, 100.0),
            "High": np.full(n, 101.0),
            "Low": np.full(n, 99.0),
            "Close": np.full(n, 100.0),
            "Volume": np.full(n, 1000.0),
            "Ret1": np.zeros(n),
            "Vol_MA20_clean": np.full(n, 1000.0),
            "ATR14_clean": np.full(n, 2.0),
            "DispDay": np.zeros(n, dtype=bool),
            "ATR5_pct": np.full(n, 1.0),
            "ATR14_pct": np.full(n, 2.0),
            "ATR14_pct_p80": np.full(n, 3.0),
            "ATR14_pct_p80_120": np.full(n, 3.0),
            "SNR_t": np.full(n, 0.1),
            "SNR_t5": np.full(n, 0.1),
            "RetStd20": np.full(n, 1.0),
            "RetStd20_p60": np.full(n, 1.5),
            "FlipRate10": np.full(n, 0.4),
            "Close20High": np.zeros(n, dtype=bool),
        },
        index=idx,
    )


def _set(df, col, i, value):
    df.iloc[i, df.columns.get_loc(col)] = value


def _ignite_volume(df, i):
    """在第 i 根鋪出 Ⓐ 出量突破：漲 7%、量 2 倍、收紅。"""
    _set(df, "Ret1", i, 7.0)
    _set(df, "Volume", i, 2000.0)
    _set(df, "Close", i, 101.0)  # 收紅（Open=100）且不超過 High


def _ignite_limit(df, i):
    """在第 i 根鋪出 Ⓑ 鎖漲停：漲 9.8%、收=最高、量不論。"""
    _set(df, "Ret1", i, 9.8)
    _set(df, "High", i, 105.0)
    _set(df, "Close", i, 105.0)


# ── prepare_series 回退階梯 ──


def test_prepare_series_fallback_ladder():
    n = 30
    idx = pd.bdate_range("2026-01-05", periods=n)
    closes = [100.0 + i for i in range(n)]
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": [c + 1 for c in closes],
            "Low": [c - 1 for c in closes],
            "Close": closes,
            "Volume": [1000.0] * n,
        },
        index=idx,
    )

    s = strategy.prepare_series(df)

    assert abs(s.ret1[1] - 1.0) < 0.01  # Ret1 缺 → 由收盤補算
    assert np.isfinite(s.volma20[-1])  # Vol_MA20_clean 缺 → rolling(20)
    assert not s.dispday.any()  # DispDay 缺 → 全 False
    assert np.isnan(s.atr14).all()  # ATR14_clean/ATR14 皆缺 → NaN


# ── is_ignition / ignition_tag ──


def test_is_ignition_volume_breakout_path():
    df = _df()
    _ignite_volume(df, 25)
    s = strategy.prepare_series(df)
    assert strategy.is_ignition(s, 25)
    assert not strategy.is_ignition(s, 24)


def test_is_ignition_limit_up_ignores_volume():
    df = _df()
    _ignite_limit(df, 25)
    _set(df, "Volume", 25, np.nan)  # 鎖漲停量被壓縮 → 量不論
    s = strategy.prepare_series(df)
    assert strategy.is_ignition(s, 25)


def test_is_ignition_require_close_high_toggle():
    df = _df()
    _set(df, "Ret1", 25, 9.8)
    _set(df, "High", 25, 105.0)
    _set(df, "Close", 25, 104.0)  # 觸頂回落、未收在最高
    s = strategy.prepare_series(df)
    assert not strategy.is_ignition(s, 25)
    assert strategy.is_ignition(s, 25, require_close_high=False)


def test_no_volume_ignition_when_volma_zero_or_nan():
    for bad in (0.0, np.nan):
        df = _df()
        _ignite_volume(df, 25)
        _set(df, "Vol_MA20_clean", 25, bad)
        s = strategy.prepare_series(df)
        assert not strategy.is_ignition(s, 25)  # volma>0 防護（統一三副本）


def test_volume_ignition_requires_red_body():
    df = _df()
    _set(df, "Ret1", 25, 7.0)
    _set(df, "Volume", 25, 2000.0)  # 量夠但收黑（Close=100=Open）
    s = strategy.prepare_series(df)
    assert not strategy.is_ignition(s, 25)


def test_ignition_tag_three_branches():
    df = _df()
    _ignite_limit(df, 25)
    _set(df, "Volume", 25, 2000.0)  # 鎖漲停 + 爆量
    _ignite_limit(df, 26)
    _set(df, "Volume", 26, 100.0)  # 鎖漲停免量
    _ignite_volume(df, 27)
    s = strategy.prepare_series(df)

    assert strategy.ignition_tag(s, 25) == (9.8, "🔒鎖漲停+爆量")
    assert strategy.ignition_tag(s, 26) == (9.8, "🔒鎖漲停(免量)")
    assert strategy.ignition_tag(s, 27) == (7.0, "🚀爆量突破")


# ── red_k_tailwind_signals 狀態機 ──


def test_min_rows_returns_none():
    assert strategy.red_k_tailwind_signals(None) is None
    assert strategy.red_k_tailwind_signals(_df(20)) is None  # < TW_MIN_ROWS(25)


def test_first_bar_only_consecutive_ignitions():
    df = _df(32)
    _ignite_volume(df, 25)
    _ignite_volume(df, 26)  # 連兩日點火 → 只取第一根

    result = strategy.red_k_tailwind_signals(df)

    assert len(result["buys"]) == 1
    assert result["buys"][0]["date"] == df.index[25]
    assert result["buys"][0]["reason"] == "第一根紅K"


def test_buy_price_low_and_trail_exit_price_high():
    df = _df(32)
    _ignite_volume(df, 25)  # 進場：peak=101、trail=101-2×2=97
    _set(df, "Close", 28, 96.0)  # 跌破 trail

    result = strategy.red_k_tailwind_signals(df)

    assert result["buys"][0]["price"] == 99.0  # 買點取當日 Low
    assert result["sells"][0]["date"] == df.index[28]
    assert result["sells"][0]["price"] == 101.0  # 賣點取當日 High
    assert result["sells"][0]["reason"] == "2×ATR移動停利"
    assert result["latest"]["in_pos"] is False
    assert abs(result["trail"].iloc[25] - 97.0) < 1e-9


def test_entry_skipped_when_atr_nan():
    df = _df(32)
    _ignite_volume(df, 25)
    _set(df, "ATR14_clean", 25, np.nan)

    assert strategy.red_k_tailwind_signals(df)["buys"] == []


def test_disposition_day_frozen():
    df = _df(34)
    _ignite_volume(df, 25)
    _set(df, "DispDay", 27, True)
    _set(df, "Close", 27, 50.0)  # 處置日暴跌也不出場、不更新峰值
    _set(df, "Close", 28, 96.0)  # 次日仍在 trail(97) 之下

    result = strategy.red_k_tailwind_signals(df)

    sell_dates = [s["date"] for s in result["sells"]]
    assert df.index[27] not in sell_dates
    assert np.isnan(result["trail"].iloc[27])
    assert df.index[28] in sell_dates  # 次日恢復判定 → 觸發 trail 出場


def test_disposition_day_no_entry():
    df = _df(32)
    _ignite_volume(df, 25)
    _set(df, "DispDay", 25, True)

    assert strategy.red_k_tailwind_signals(df)["buys"] == []


def test_regime_exit_snr_cross_zero_with_high_retstd():
    df = _df(34)
    _ignite_volume(df, 25)
    _set(df, "SNR_t", 27, 0.05)
    _set(df, "SNR_t", 28, -0.1)  # 由正轉負
    _set(df, "RetStd20", 28, 2.0)  # ≥ p60(1.5) 高檔

    result = strategy.red_k_tailwind_signals(df)

    assert result["sells"][0]["date"] == df.index[28]
    assert result["sells"][0]["reason"] == "性質切換SNR<0"


def test_same_day_double_exit_reason_order():
    df = _df(34)
    _ignite_volume(df, 25)
    _set(df, "SNR_t", 27, 0.05)
    _set(df, "SNR_t", 28, -0.1)
    _set(df, "RetStd20", 28, 2.0)
    _set(df, "Close", 28, 96.0)  # 同日也跌破 trail

    result = strategy.red_k_tailwind_signals(df)

    assert result["sells"][0]["reason"] == "性質切換SNR<0／2×ATR移動停利"


def test_entry_filter_vetoes():
    df = _df(32)
    _ignite_volume(df, 25)

    result = strategy.red_k_tailwind_signals(df, entry_filter=lambda i: False)

    assert result["buys"] == []


def test_reentry_on_new_high_path():
    df = _df(32)
    _set(df, "Close20High", 25, True)  # 無點火，僅創 20 日新高

    assert strategy.red_k_tailwind_signals(df)["buys"] == []  # 預設關閉
    result = strategy.red_k_tailwind_signals(df, reentry_on_new_high=True)
    assert result["buys"][0]["reason"] == "20日新高再進場"


def test_warn_cooling_cross_and_three_day_decline():
    df = _df(32)
    _set(df, "ATR5_pct", 23, 3.0)
    _set(df, "ATR5_pct", 24, 2.5)  # 昨日仍 ≥ ATR14%(2.0)
    _set(df, "ATR5_pct", 25, 1.5)  # 今日下穿且連三日遞減
    _set(df, "ATR14_pct", 25, 2.0)

    result = strategy.red_k_tailwind_signals(df)

    warn = next(w for w in result["warns"] if w["date"] == df.index[25])
    assert "波動降溫" in warn["reason"]


def test_warn_regime_shift_snr5():
    df = _df(32)
    _set(df, "SNR_t5", 24, 0.2)  # > 0.15
    _set(df, "SNR_t5", 25, 0.04)  # < 0.05
    _set(df, "ATR14_pct", 25, 3.5)  # ≥ 120日P80(3.0)

    result = strategy.red_k_tailwind_signals(df)

    warn = next(w for w in result["warns"] if w["date"] == df.index[25])
    assert "性質切換警示" in warn["reason"]


def test_accel_mask():
    df = _df(32)
    _set(df, "ATR5_pct", 25, 4.0)  # > ATR14%
    _set(df, "ATR14_pct", 25, 3.5)  # ≥ 一年P80(3.0)

    result = strategy.red_k_tailwind_signals(df)

    assert bool(result["accel_mask"].iloc[25])
    assert not bool(result["accel_mask"].iloc[24])


def test_quadrant_four_states_and_dash():
    cases = [
        ({"SNR_t": 0.2, "ATR14_pct": 3.5}, "單邊行情（抱緊+雷達）"),
        ({"SNR_t": 0.2, "ATR14_pct": 2.0}, "緩漲趨勢（沿5日線）"),
        ({"SNR_t": 0.05, "ATR14_pct": 3.5}, "雙向絞殺（縮部位/離場）"),
        ({"SNR_t": 0.05, "ATR14_pct": 2.0}, "休眠盤整（觀察）"),
    ]
    for overrides, expected in cases:
        df = _df(32)
        for col, val in overrides.items():
            _set(df, col, -1, val)
        assert strategy.red_k_tailwind_signals(df)["latest"]["quad"] == expected, expected

    df = _df(32)
    df["SNR_t"] = np.nan
    assert strategy.red_k_tailwind_signals(df)["latest"]["quad"] == "—"


def test_latest_payload_fields():
    df = _df(32)

    latest = strategy.red_k_tailwind_signals(df)["latest"]

    assert latest["atr5_pct"] == 1.0
    assert latest["atr14_pct"] == 2.0
    assert latest["snr"] == 0.1
    assert latest["flip_pct"] == 40  # 0.4 → 40%
    assert latest["accel"] is False
    assert latest["in_pos"] is False


def test_graceful_on_enrich_only_df():
    n = 30
    idx = pd.bdate_range("2026-01-05", periods=n)
    closes = [100.0 + 0.1 * i for i in range(n)]
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": [c + 1 for c in closes],
            "Low": [c - 1 for c in closes],
            "Close": closes,
            "Volume": [1000.0] * n,
        },
        index=idx,
    )

    result = strategy.red_k_tailwind_signals(df)  # 無策略欄位也不炸

    assert result is not None
    assert result["latest"]["quad"] == "—"
