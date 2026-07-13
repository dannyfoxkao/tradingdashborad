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
