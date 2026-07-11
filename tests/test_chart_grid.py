"""chart_grid 純函式（HTML 面板、Plotly 圖）的單元測試。"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from trading_dashboard import indicators
from trading_dashboard.ui import chart_grid


def _make_df(n: int = 70) -> pd.DataFrame:
    idx = pd.bdate_range("2026-01-01", periods=n)
    close = np.linspace(100.0, 130.0, n)
    df = pd.DataFrame({
        "Open": close - 1, "High": close + 2, "Low": close - 2, "Close": close,
        "Volume": np.full(n, 1_000_000.0),
        "Turnover": close * 1_000_000.0,
    }, index=idx)
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


def test_build_figure_dual_mode_has_extra_axis_line():
    fig = chart_grid._build_figure(_make_df(), "量 + 金額雙對比", [])

    row2 = _row2_traces(fig)
    dual_lines = [t for t in row2 if getattr(t, "yaxis", "") == "y3"]
    assert len(dual_lines) == 1
    ma_lines = [t for t in row2 if isinstance(t, go.Scatter) and t.yaxis != "y3"]
    assert len(ma_lines) == len(chart_grid._SUB_MA_COLORS)
