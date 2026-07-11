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


def test_enrich_adds_indicator_columns():
    df = _make_df(list(range(1, 71)))
    for col in ["MA5", "MA10", "MA20", "MA60", "Vol_MA5", "Vol_MA20", "Turn_MA20", "Vol_Std20"]:
        assert col in df.columns


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
    assert result["rank"] == 4


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
