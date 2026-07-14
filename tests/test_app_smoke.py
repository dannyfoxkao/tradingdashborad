"""端到端冒煙測試：以 Streamlit AppTest 在無頭模式執行 app.py。

模擬資料層（不連網），驗證三大面板可完整渲染且不丟出例外，
同時涵蓋 UI 渲染路徑（圖卡、徽章、Plotly 圖）。
"""

from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

import trading_dashboard.data_sources.disposition as disp_mod
import trading_dashboard.data_sources.finmind as finmind_mod
import trading_dashboard.indicators as indicators
import trading_dashboard.ui.chart_grid as chart_grid_mod
import trading_dashboard.ui.momentum_panel as momentum_mod
import trading_dashboard.ui.radar_panel as radar_mod
import trading_dashboard.ui.today_panel as today_mod
from trading_dashboard.config import parse_stock_id

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


def _fake_df():
    n = 70
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    closes = [100.0 + i for i in range(n)]
    vols = [1000.0 + i for i in range(n)]
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": [c + 1 for c in closes],
            "Low": [c - 1 for c in closes],
            "Close": closes,
            "Volume": vols,
            "Turnover": [c * v for c, v in zip(closes, vols, strict=False)],
        },
        index=idx,
    )
    return indicators.enrich(df)


def test_app_renders_without_exception(monkeypatch):
    df = _fake_df()
    bench = pd.DataFrame({"Close": [50.0 + i for i in range(70)]}, index=df.index)

    def fake_prefetch(tickers, start, end, **kwargs):
        return {parse_stock_id(t): df for t in tickers}

    monkeypatch.setattr(finmind_mod, "fetch_benchmark_data", lambda s, e: bench)
    monkeypatch.setattr(finmind_mod, "fetch_index_close", lambda sid, s, e: bench)
    monkeypatch.setattr(disp_mod, "fetch_disposition_map", lambda: {})
    monkeypatch.setattr(chart_grid_mod, "prefetch_many", fake_prefetch)
    monkeypatch.setattr(radar_mod, "prefetch_many", fake_prefetch)
    monkeypatch.setattr(momentum_mod, "prefetch_many", fake_prefetch)
    monkeypatch.setattr(today_mod, "prefetch_many", fake_prefetch)

    at = AppTest.from_file(APP_PATH).run(timeout=60)

    assert not at.exception
    assert at.title  # 有渲染出「監控板塊」標題
    assert any("大盤氣象台" in str(m.value) for m in at.markdown)  # 氣象台已渲染
    assert any("紅K順風車" in str(m.value) for m in at.markdown)  # 順風車狀態列已渲染


def test_app_shows_placeholder_card_when_data_missing(monkeypatch):
    """個股抓不到資料時應顯示「無資料」占位卡，而非默默留白。"""
    df = _fake_df()
    bench = pd.DataFrame({"Close": [50.0 + i for i in range(70)]}, index=df.index)

    def fake_prefetch(tickers, start, end, **kwargs):
        # 第一檔回 None（模擬抓取失敗／無效代號），其餘正常
        out = {}
        for i, t in enumerate(tickers):
            out[parse_stock_id(t)] = None if i == 0 else df
        return out

    monkeypatch.setattr(finmind_mod, "fetch_benchmark_data", lambda s, e: bench)
    monkeypatch.setattr(finmind_mod, "fetch_index_close", lambda sid, s, e: bench)
    monkeypatch.setattr(disp_mod, "fetch_disposition_map", lambda: {})
    monkeypatch.setattr(chart_grid_mod, "prefetch_many", fake_prefetch)
    monkeypatch.setattr(radar_mod, "prefetch_many", fake_prefetch)
    monkeypatch.setattr(momentum_mod, "prefetch_many", fake_prefetch)
    monkeypatch.setattr(today_mod, "prefetch_many", fake_prefetch)

    at = AppTest.from_file(APP_PATH).run(timeout=60)

    assert not at.exception
    assert any("無資料" in str(m.value) for m in at.markdown)
