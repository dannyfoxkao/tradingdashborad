import numpy as np
import pandas as pd

from trading_dashboard import indicators


def _make_df(closes, volumes=None, turnovers=None):
    n = len(closes)
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    vol = volumes if volumes is not None else [1000.0] * n
    turn = turnovers if turnovers is not None else [c * v for c, v in zip(closes, vol, strict=False)]
    df = pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": vol, "Turnover": turn}, index=idx
    )
    return indicators.enrich(df)


def _make_ma_df(*, close, ma5, ma10, ma20, ma60, ma5_prev3=None, ma10_prev3=None, ma20_prev5=None, n=25):
    """手工指定均線欄位的合成資料，精準命中 classify_trend 的分支條件。

    prev 參數對應 _slope 的回看格：MA5/MA10 回看 3 根（iloc[-4]）、MA20 回看 5 根（iloc[-6]）。
    """
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    df = pd.DataFrame({"Close": close, "MA5": ma5, "MA10": ma10, "MA20": ma20, "MA60": ma60}, index=idx, dtype=float)
    if ma5_prev3 is not None:
        df.iloc[-4, df.columns.get_loc("MA5")] = ma5_prev3
    if ma10_prev3 is not None:
        df.iloc[-4, df.columns.get_loc("MA10")] = ma10_prev3
    if ma20_prev5 is not None:
        df.iloc[-6, df.columns.get_loc("MA20")] = ma20_prev5
    return df


def test_enrich_adds_indicator_columns():
    df = _make_df(list(range(1, 71)))
    for col in ["MA5", "MA10", "MA20", "MA60", "Vol_MA5", "Vol_MA20", "Turn_MA20", "Vol_Std20"]:
        assert col in df.columns


# ── classify_trend v2：7 狀態、rank 單調（0 最強 → 6 最弱）──


def test_classify_trend_none():
    assert indicators.classify_trend(None) is None


def test_classify_trend_insufficient_history():
    df = _make_df(list(range(1, 11)))  # 10 列 < 21
    assert indicators.classify_trend(df)["label"] == "資料不足"


def test_classify_trend_strong_uptrend():
    df = _make_df([float(i) for i in range(1, 71)])  # 穩定上升
    result = indicators.classify_trend(df)
    assert result["label"] == "強多"
    assert result["rank"] == 0


def test_classify_trend_weak_downtrend():
    df = _make_df([float(i) for i in range(70, 0, -1)])  # 穩定下降
    result = indicators.classify_trend(df)
    assert result["label"] == "弱勢"
    assert result["rank"] == 6


def test_classify_trend_bottom_reversal():
    # 空頭結構（月線<季線）但短均同步上彎、站回 5 日、月線止跌
    df = _make_ma_df(
        close=105,
        ma5=100,
        ma10=95,
        ma20=90,
        ma60=120,
        ma5_prev3=97,
        ma10_prev3=93,
        ma20_prev5=90,
    )
    result = indicators.classify_trend(df)
    assert result["label"] == "底部翻揚"
    assert result["rank"] == 1
    assert result["icon"] == "🌱"


def test_classify_trend_head_dulling():
    # 多頭結構（月線>季線、align>=2）但短均同步下彎、月線動能熄火
    df = _make_ma_df(
        close=98,
        ma5=100,
        ma10=101,
        ma20=95,
        ma60=90,
        ma5_prev3=103,
        ma10_prev3=104,
        ma20_prev5=95,
    )
    result = indicators.classify_trend(df)
    assert result["label"] == "頭部鈍化"
    assert result["rank"] == 4
    assert result["icon"] == "🥀"


def test_classify_trend_oscillating_bullish_rank():
    # align=3 但月線走平（slope=0 不滿足強多的 slope>0），短均上彎（非頭部鈍化）
    df = _make_ma_df(
        close=101,
        ma5=100,
        ma10=99,
        ma20=98,
        ma60=97,
        ma5_prev3=99,
        ma10_prev3=98,
        ma20_prev5=98,
    )
    result = indicators.classify_trend(df)
    assert result["label"] == "震盪(偏多)"
    assert result["rank"] == 2


def test_classify_trend_neutral_rank():
    # align=0、slope=0 → 震盪(中性)
    df = _make_ma_df(
        close=99,
        ma5=100,
        ma10=100,
        ma20=101,
        ma60=102,
        ma5_prev3=99,
        ma10_prev3=99,
        ma20_prev5=101,
    )
    result = indicators.classify_trend(df)
    assert result["label"] == "震盪(中性)"
    assert result["rank"] == 3


def test_classify_trend_oscillating_bearish_rank():
    # align=3 但月線明顯下彎（slope=-1%）、短均仍上 → 震盪(偏空)
    df = _make_ma_df(
        close=101,
        ma5=100,
        ma10=99.5,
        ma20=99,
        ma60=98,
        ma5_prev3=99,
        ma10_prev3=99,
        ma20_prev5=100,
    )
    result = indicators.classify_trend(df)
    assert result["label"] == "震盪(偏空)"
    assert result["rank"] == 5


# ── rsi / atr / enrich_heavy（重型指標）──


def test_rsi_bounds_and_direction():
    # 鋸齒趨勢（漲多跌少 / 跌多漲少）；純單調序列分母為 0 → NaN（與平面版一致）
    up_steps = [2.0 if i % 2 == 0 else -0.5 for i in range(40)]
    down_steps = [-2.0 if i % 2 == 0 else 0.5 for i in range(40)]
    rising = pd.Series(100.0 + np.cumsum(up_steps))
    falling = pd.Series(100.0 + np.cumsum(down_steps))

    assert indicators.rsi(rising).iloc[-1] > 70
    assert indicators.rsi(falling).iloc[-1] < 30


def test_atr_known_values():
    n = 30
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    df = pd.DataFrame({"High": [101.0] * n, "Low": [99.0] * n, "Close": [100.0] * n}, index=idx)

    out = indicators.atr(df)

    assert abs(out.iloc[-1] - 2.0) < 1e-9  # 恆定區間 H−L=2 → ATR=2


def test_enrich_heavy_adds_long_indicators():
    n = 260
    df = _make_df([100.0 + 0.1 * i for i in range(n)])

    out = indicators.enrich_heavy(df)

    for col in [
        "MA120",
        "MA200",
        "RSI14",
        "Ret_20",
        "Ret_60",
        "Ret_120",
        "Ret_240",
        "ATR14",
        "PriorHigh20",
        "PriorLow20",
        "PriorHigh60",
        "PriorLow60",
    ]:
        assert col in out.columns, col
    assert np.isfinite(out["MA200"].iloc[-1])
    assert np.isfinite(out["Ret_240"].iloc[-1])


def test_enrich_heavy_prior_high_excludes_today():
    n = 60
    closes = [100.0] * n
    df = _make_df(closes)
    df.loc[df.index[-1], "High"] = 150.0  # 今日暴衝新高

    out = indicators.enrich_heavy(df)

    assert out["PriorHigh20"].iloc[-1] < 150.0  # shift(1)：前高不含今日，不看未來


# ── compute_atr_stop / compute_support_resistance / classify_long_term / stock_momentum ──


def _flat_df(n=30, close=100.0):
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1000.0}, index=idx
    )


def test_compute_atr_stop_levels_and_none_paths():
    df = _flat_df()
    df["ATR14"] = 2.0

    stop = indicators.compute_atr_stop(df)

    assert stop["stop"] == 96.0  # 100 − 2×2
    assert stop["stop_tight"] == 97.0
    assert stop["stop_loose"] == 94.0
    assert stop["atr_pct"] == 2.0

    assert indicators.compute_atr_stop(_flat_df()) is None  # 無 ATR14 欄
    df.iloc[-1, df.columns.get_loc("ATR14")] = np.nan
    assert indicators.compute_atr_stop(df) is None


def test_compute_support_resistance_rr_and_broken():
    df = _flat_df()
    df["PriorHigh60"] = 110.0
    df["PriorLow60"] = 95.0

    sr = indicators.compute_support_resistance(df)

    assert sr["resistance"] == 110.0
    assert sr["support"] == 95.0
    assert sr["rr"] == 2.0  # 上檔10 / 下檔5
    assert sr["broken"] is False

    df["PriorHigh60"] = 99.0  # 已站上前高
    assert indicators.compute_support_resistance(df)["broken"] is True
    assert indicators.compute_support_resistance(_flat_df()) is None  # 缺欄 → None


def test_classify_long_term_ma_priority_and_labels():
    df = _flat_df(n=30)
    df["MA200"] = 90.0
    df.iloc[-21, df.columns.get_loc("MA200")] = 85.0  # 20 根回看 → 上彎

    result = indicators.classify_long_term(df)
    assert result["label"] == "順風"  # 收盤(100) ≥ MA200 且上彎
    assert result["ma_used"] == "MA200"

    df2 = _flat_df(n=30)
    df2["MA120"] = 110.0  # 無 MA200 → 遞補 MA120；跌破且下彎
    df2.iloc[-21, df2.columns.get_loc("MA120")] = 115.0
    result2 = indicators.classify_long_term(df2)
    assert result2["label"] == "逆風"
    assert result2["ma_used"] == "MA120"

    df3 = _flat_df(n=30)
    df3["MA200"] = 90.0
    df3.iloc[-21, df3.columns.get_loc("MA200")] = 95.0  # 站上但下彎 → 中性轉折
    assert indicators.classify_long_term(df3)["label"] == "中性轉折"

    assert indicators.classify_long_term(_flat_df()) is None  # 無任何長均線


def test_stock_momentum_strong_weak_neutral():
    df = _flat_df()
    for col, val in {"Ret_20": 5.0, "Ret_60": 8.0, "Ret_120": 12.0, "Ret_240": 20.0, "RSI14": 65.0}.items():
        df[col] = val
    strong = indicators.stock_momentum(df)
    assert strong["label"] == "強動能"
    assert strong["score"] == 4
    assert strong["rsi"] == 65.0

    for col in ("Ret_20", "Ret_60", "Ret_120", "Ret_240"):
        df[col] = -5.0
    assert indicators.stock_momentum(df)["label"] == "弱動能"

    df["Ret_20"] = 5.0
    df["Ret_60"] = 5.0  # 2正2負 → 中性
    assert indicators.stock_momentum(df)["label"] == "中性動能"

    assert indicators.stock_momentum(_flat_df(n=10)) is None  # 資料不足
    assert indicators.stock_momentum(_flat_df()) is None  # 無動能欄位


# ── compute_alpha ──


def test_compute_alpha_no_benchmark():
    df = _make_df([float(i) for i in range(1, 30)])
    assert indicators.compute_alpha(df, None) == (None, None)


def test_compute_alpha_zero_variance_benchmark():
    closes = [float(i) for i in range(1, 30)]
    df = _make_df(closes)
    bench = pd.DataFrame({"Close": [100.0] * len(closes)}, index=df.index)  # 常數 → var=0
    alpha, beta = indicators.compute_alpha(df, bench)
    assert beta == 1.0
    assert alpha is not None


# ── classify_volume ──


def test_classify_volume_surge():
    info = indicators.classify_volume(300.0, 100.0, 100.0, 10.0)
    assert info["label"].startswith("爆量")


def test_classify_volume_normal():
    info = indicators.classify_volume(100.0, 100.0, 100.0, 0.0)
    assert info["label"].startswith("常態")


def test_classify_volume_shrink():
    info = indicators.classify_volume(50.0, 100.0, 100.0, 0.0)
    assert info["label"].startswith("縮量")


def test_classify_volume_unknown_when_nan():
    info = indicators.classify_volume(np.nan, 100.0, 100.0, 1.0)
    assert info["label"] == "量能不明"


# ── MACD ──


def test_macd_constant_close_is_flat():
    close = pd.Series([100.0] * 60)
    dif, _dea, hist = indicators.macd(close)
    assert abs(dif.iloc[-1]) < 1e-9
    assert abs(hist.iloc[-1]) < 1e-9


def test_macd_rising_close_positive_dif():
    close = pd.Series([100.0 + i for i in range(60)])
    dif, _, _ = indicators.macd(close)
    assert dif.iloc[-1] > 0


# ── classify_market_weather：安危區 × 風力 → 四狀態 ──


def _index_df(closes):
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="B")
    return pd.DataFrame({"Close": closes}, index=idx)


def test_weather_insufficient_data():
    assert indicators.classify_market_weather(None) is None
    assert indicators.classify_market_weather(_index_df([100.0] * 10)) is None


def test_weather_strong_wind():
    # 加速上漲：站上月線 + MACD 柱往上 → 強風
    closes = [100.0 + 0.05 * i * i for i in range(60)]
    w = indicators.classify_market_weather(_index_df(closes))
    assert w["weather"] == "強風"


def test_weather_turbulence():
    # 長升後走平：仍在月線上，但動能熄火（柱往下）→ 亂流
    closes = [100.0 + i for i in range(55)] + [154.0] * 5
    w = indicators.classify_market_weather(_index_df(closes))
    assert w["weather"] == "亂流"


def test_weather_gust():
    # 長跌後小反彈：仍在月線下，但柱回升 → 陣風
    closes = [200.0 - 2 * i for i in range(55)] + [92.0, 94.0, 96.0, 98.0, 100.0]
    w = indicators.classify_market_weather(_index_df(closes))
    assert w["weather"] == "陣風"


def test_weather_windless():
    # 加速下跌：跌破月線 + 柱往下 → 無風
    closes = [200.0 - 0.05 * i * i for i in range(60)]
    w = indicators.classify_market_weather(_index_df(closes))
    assert w["weather"] == "無風"


# ── compute_momentum：族群多空占比 ──


def test_compute_momentum_counts_bull_bear():
    labels = ["強多", "底部翻揚", "弱勢", "震盪(中性)"]
    m = indicators.compute_momentum(labels)
    assert m["bull"] == 2
    assert m["bear"] == 1
    assert m["total"] == 4
    assert m["bull_pct"] == 50.0
    assert m["bear_pct"] == 25.0


def test_compute_momentum_skips_insufficient():
    m = indicators.compute_momentum(["強多", "資料不足"])
    assert m["total"] == 1
    assert m["bull_pct"] == 100.0


def test_compute_momentum_empty():
    m = indicators.compute_momentum([])
    assert m["total"] == 0
    assert m["bull_pct"] == 0.0
