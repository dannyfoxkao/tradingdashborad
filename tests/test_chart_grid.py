"""chart_grid 純函式（HTML 面板、Plotly 圖、順風車覆蓋層）的單元測試。"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from trading_dashboard import indicators
from trading_dashboard.signals import MAX_BUY_SIGNALS
from trading_dashboard.ui import chart_grid


def _make_df(n: int = 70) -> pd.DataFrame:
    idx = pd.bdate_range("2026-01-01", periods=n)
    close = np.linspace(100.0, 130.0, n)
    df = pd.DataFrame(
        {
            "Open": close - 1,
            "High": close + 2,
            "Low": close - 2,
            "Close": close,
            "Volume": np.full(n, 1_000_000.0),
            "Turnover": close * 1_000_000.0,
        },
        index=idx,
    )
    return indicators.enrich(df)


def _sub_legend_part(html_out: str, sub_label: str) -> str:
    assert sub_label in html_out
    return html_out.split(sub_label)[1]


def test_panel_html_sub_legend_matches_plotted_windows():
    df = _make_df()
    mask = chart_grid._disposition_mask(df.index, [])

    html_out = chart_grid._panel_html("2330", "台積電", df, [], mask, "成交量", None)

    sub_part = _sub_legend_part(html_out, "量MA:")
    assert "●60" not in sub_part
    for w in chart_grid._SUB_MA_COLORS:
        assert f"●{w}" in sub_part


def test_panel_html_turnover_mode_legend_matches_plotted_windows():
    df = _make_df()
    mask = chart_grid._disposition_mask(df.index, [])

    html_out = chart_grid._panel_html("2330", "台積電", df, [], mask, "成交金額 (估算)", None)

    sub_part = _sub_legend_part(html_out, "額MA:")
    assert "●60" not in sub_part


def test_empty_card_html_shows_id_reason_and_escapes():
    out = chart_grid._empty_card_html("2330", "<b>台積電</b>", "抓取失敗或代號無資料")

    assert "2330" in out
    assert "&lt;b&gt;台積電&lt;/b&gt;" in out
    assert "<b>台積電</b>" not in out
    assert "無資料" in out
    assert "抓取失敗或代號無資料" in out


def _row2_traces(fig: go.Figure) -> list:
    return [t for t in fig.data if getattr(t, "yaxis", "y") not in (None, "y")]


def test_build_figure_volume_mode_traces():
    fig = chart_grid._build_figure(_make_df(), "成交量", [])

    row2 = _row2_traces(fig)
    assert len([t for t in row2 if isinstance(t, go.Bar)]) == 1
    assert len([t for t in row2 if isinstance(t, go.Scatter)]) == len(chart_grid._SUB_MA_COLORS)


def test_build_figure_turnover_mode_traces():
    fig = chart_grid._build_figure(_make_df(), "成交金額 (估算)", [])

    row2 = _row2_traces(fig)
    assert len([t for t in row2 if isinstance(t, go.Bar)]) == 1
    assert len([t for t in row2 if isinstance(t, go.Scatter)]) == len(chart_grid._SUB_MA_COLORS)


def _fake_tw(df):
    idx = df.index
    accel = pd.Series(False, index=idx)
    accel.iloc[30:33] = True
    accel.iloc[40:42] = True  # 兩段波動加速
    trail = pd.Series(np.nan, index=idx)
    trail.iloc[25:29] = 100.0
    return {
        "buys": [{"date": idx[25], "price": 99.0, "reason": "第一根紅K"}],
        "sells": [{"date": idx[28], "price": 105.0, "reason": "2×ATR移動停利"}],
        "warns": [{"date": idx[27], "price": 104.0, "reason": "波動降溫"}],
        "accel_mask": accel,
        "trail": trail,
        "latest": {
            "atr5_pct": 1.0,
            "atr14_pct": 2.0,
            "snr": 0.1,
            "flip_pct": 40,
            "accel": True,
            "in_pos": True,
            "quad": "單邊行情（抱緊+雷達）",
        },
    }


def test_signals_html_badge_cap_is_max_buy_signals():
    out = chart_grid._signals_html("2330", _make_df(), False)

    assert f"/{MAX_BUY_SIGNALS}" in out
    assert "進場 0/5<" not in out  # 舊分母已淘汰


def test_panel_html_legend_includes_ma200():
    df = _make_df()
    mask = chart_grid._disposition_mask(df.index, [])

    html_out = chart_grid._panel_html("2330", "台積電", df, [], mask, "成交量", None)

    assert "┈200" in html_out


def test_build_figure_plots_ma200_dashed_when_formed():
    df = indicators.enrich_heavy(_make_df(220))

    fig = chart_grid._build_figure(df, "成交量", [])

    ma200 = [t for t in fig.data if isinstance(t, go.Scatter) and getattr(t.line, "color", None) == "#90a4ae"]
    assert len(ma200) == 1
    assert ma200[0].line.dash == "dot"


def test_ma200_absent_when_column_missing():
    fig = chart_grid._build_figure(_make_df(), "成交量", [])

    assert not any(isinstance(t, go.Scatter) and getattr(t.line, "color", None) == "#90a4ae" for t in fig.data)


def test_volume_bar_opacity_full():
    fig = chart_grid._build_figure(_make_df(), "成交量", [])

    bar = next(t for t in fig.data if isinstance(t, go.Bar))
    assert bar.opacity == 1.0


def test_tailwind_traces_markers_and_trail():
    df = _make_df()

    fig = chart_grid._build_figure(df, "成交量", [], tw=_fake_tw(df))

    symbols = {t.marker.symbol for t in fig.data if isinstance(t, go.Scatter) and t.mode == "markers"}
    assert {"triangle-up", "triangle-down", "star"} <= symbols
    assert any(  # 2×ATR trail 虛線
        isinstance(t, go.Scatter) and getattr(t.line, "dash", None) == "dot" and t.line.color == "#ffa726"
        for t in fig.data
    )


def test_accel_vrect_segments():
    df = _make_df()

    fig = chart_grid._build_figure(df, "成交量", [], tw=_fake_tw(df))

    vrects = [s for s in fig.layout.shapes if s.type == "rect" and s.fillcolor == "#fbc02d"]
    assert len(vrects) == 2  # 兩段波動加速背景


def test_level_hlines_resistance_support_stop():
    df = _make_df()
    sr = {
        "resistance": 130.0,
        "support": 100.0,
        "rr": 2.0,
        "upside_pct": 5.0,
        "downside_pct": 3.0,
        "window": 60,
        "broken": False,
    }
    atr_stop = {"atr": 2.0, "atr_pct": 1.5, "stop": 120.0, "stop_tight": 122.0, "stop_loose": 116.0, "mult": 2.0}

    fig = chart_grid._build_figure(df, "成交量", [], sr=sr, atr_stop=atr_stop)

    hline_ys = {s.y0 for s in fig.layout.shapes if s.type == "line"}
    assert {130.0, 100.0, 120.0} <= hline_ys


def test_tailwind_html_states():
    tw = _fake_tw(_make_df())

    out = chart_grid._tailwind_html(tw)
    assert "紅K順風車" in out
    assert "波動加速" in out
    assert "持倉中" in out
    assert "▲買1" in out

    tw["latest"]["accel"] = False
    tw["latest"]["in_pos"] = False
    out2 = chart_grid._tailwind_html(tw)
    assert "波動中性" in out2
    assert "空手" in out2


def test_build_figure_dual_mode_has_extra_axis_line():
    fig = chart_grid._build_figure(_make_df(), "量 + 金額雙對比", [])

    row2 = _row2_traces(fig)
    dual_lines = [t for t in row2 if getattr(t, "yaxis", "") == "y3"]
    assert len(dual_lines) == 1
    ma_lines = [t for t in row2 if isinstance(t, go.Scatter) and t.yaxis != "y3"]
    assert len(ma_lines) == len(chart_grid._SUB_MA_COLORS)
