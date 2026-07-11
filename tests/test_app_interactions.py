"""互動冒煙：點擊「刷新熱錢排行」與「開始掃描」按鈕，覆蓋面板互動路徑。"""
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

import trading_dashboard.data_sources.disposition as disp_mod
import trading_dashboard.data_sources.finmind as finmind_mod
import trading_dashboard.indicators as indicators
import trading_dashboard.ui.chart_grid as chart_grid_mod
import trading_dashboard.ui.leaderboard_panel as lb_mod
import trading_dashboard.ui.radar_panel as radar_mod
from trading_dashboard.config import parse_stock_id

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


def _rising_df():
    n = 70
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    closes = [100.0 + i for i in range(n)]
    vols = [1000.0 + i for i in range(n)]
    df = pd.DataFrame({
        "Open": closes, "High": [c + 1 for c in closes], "Low": [c - 1 for c in closes],
        "Close": closes, "Volume": vols, "Turnover": [c * v for c, v in zip(closes, vols)],
    }, index=idx)
    return indicators.enrich(df)


def _ledger_df():
    return pd.DataFrame([{
        "stock_id": "2330", "name": "台積電", "cumulative_days": 3,
        "last_seen_date": "20260626", "buffer_days": 0,
        "market": "上市", "turnover_billion": 100.0,
    }])


def test_buttons_drive_panels(monkeypatch):
    df = _rising_df()
    bench = pd.DataFrame({"Close": [50.0 + i for i in range(70)]}, index=df.index)

    def fake_prefetch(tickers, start, end, **kwargs):
        return {parse_stock_id(t): df for t in tickers}

    monkeypatch.setattr(finmind_mod, "fetch_benchmark_data", lambda s, e: bench)
    monkeypatch.setattr(disp_mod, "fetch_disposition_map", lambda: {})
    monkeypatch.setattr(chart_grid_mod, "prefetch_many", fake_prefetch)
    monkeypatch.setattr(radar_mod, "prefetch_many", fake_prefetch)

    # 熱錢排行：避免真的連網 / 寫入磁碟
    monkeypatch.setattr(lb_mod, "fetch_market_top20_raw",
                        lambda: ([{"stock_id": "2330", "name": "台積電",
                                   "turnover_billion": 100.0, "market": "上市"}], [], "20260626", []))
    monkeypatch.setattr(lb_mod, "update_leaderboard_data", lambda combined, date: _ledger_df())
    monkeypatch.setattr(lb_mod, "load_leaderboard", lambda *a, **k: _ledger_df())

    at = AppTest.from_file(APP_PATH).run(timeout=60)
    assert not at.exception

    # 點擊所有按鈕（刷新排行 + 開始掃描）
    for btn in at.button:
        btn.set_value(True)
    at.run(timeout=60)

    assert not at.exception
    assert len(at.dataframe) >= 1  # 排行或雷達表格已渲染
