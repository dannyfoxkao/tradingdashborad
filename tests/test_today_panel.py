"""今日『紅K順風車』點火掃描面板（純函式部分）的單元測試。"""

import numpy as np
import pandas as pd

import trading_dashboard.ui.today_panel as today_mod
from trading_dashboard.ui.today_panel import _analyse_rows, _run_scan, _scan_stock


def _df(n=30, ignite_at=(), disp_at=()):
    """合成策略欄位資料；ignite_at 位置鋪出量突破。"""
    idx = pd.bdate_range("2026-01-05", periods=n)
    df = pd.DataFrame(
        {
            "Open": np.full(n, 100.0),
            "High": np.full(n, 101.0),
            "Low": np.full(n, 99.0),
            "Close": np.full(n, 100.0),
            "Volume": np.full(n, 1000.0),
            "Ret1": np.zeros(n),
            "Vol_MA20_clean": np.full(n, 1000.0),
            "DispDay": np.zeros(n, dtype=bool),
        },
        index=idx,
    )
    for i in ignite_at:
        df.iloc[i, df.columns.get_loc("Ret1")] = 7.0
        df.iloc[i, df.columns.get_loc("Volume")] = 2000.0
        df.iloc[i, df.columns.get_loc("Close")] = 101.0
    for i in disp_at:
        df.iloc[i, df.columns.get_loc("DispDay")] = True
    return df


def test_scan_stock_finds_latest_first_bar_within_lookback():
    df = _df(ignite_at=(25, 28))  # 兩次點火，取視窗內最近一次

    info, last_dt = _scan_stock(df, lookback=5)

    assert info is not None
    assert info["date"] == df.index[28]
    assert info["days_ago"] == 1  # n-1=29
    assert info["tag"] == "🚀爆量突破"
    assert last_dt == df.index[-1].normalize()


def test_scan_stock_ignores_ignition_outside_lookback():
    df = _df(ignite_at=(20,))

    info, last_dt = _scan_stock(df, lookback=3)

    assert info is None
    assert last_dt is not None


def test_scan_stock_skips_disposition_day():
    df = _df(ignite_at=(28,), disp_at=(28,))

    info, _ = _scan_stock(df, lookback=5)

    assert info is None


def test_scan_stock_short_df_returns_none_none():
    assert _scan_stock(None, 3) == (None, None)
    assert _scan_stock(_df(10), 3) == (None, None)


def test_run_scan_dedupes_and_collects_missed(monkeypatch):
    pool = {
        "族群A": {"2330.TW": "台積電", "2454.TW": "聯發科"},
        "族群B": {"2330.TW": "台積電"},  # 跨族群同一檔 → 只掃一次、兩列都出
    }
    fired = _df(ignite_at=(29,))

    def fake_prefetch(tickers, start, end, **kwargs):
        return {"2330": fired, "2454": None}  # 2454 抓不到（限流/停牌）

    monkeypatch.setattr(today_mod, "prefetch_many", fake_prefetch)

    payload = _run_scan(pool, "2026-01-01", "2026-02-28", lookback=3)

    assert len(payload["rows"]) == 2  # 兩個族群各一列（同檔）
    assert all(r["代號"] == "2330" for r in payload["rows"])
    assert any("2454" in m for m in payload["missed"])
    assert payload["lookback"] == 3
    assert payload["scan_date"] != "—"


def test_analyse_rows_rally_requires_min_and_sorting():
    rows = [
        {
            "族群": "PCB",
            "代號": str(1000 + i),
            "名稱": f"股{i}",
            "漲幅%": 7.0,
            "點火類型": "🚀爆量突破",
            "點火日": "07/10",
            "_days": 1,
        }
        for i in range(3)  # PCB 三檔 → 齊發
    ] + [
        {
            "族群": "記憶體",
            "代號": "2408",
            "名稱": "南亞科",
            "漲幅%": 9.9,
            "點火類型": "🔒鎖漲停(免量)",
            "點火日": "07/11",
            "_days": 0,
        }
    ]

    result = _analyse_rows(rows)

    assert result["rally"] == ["PCB"]  # ≥3 檔才算齊發
    assert result["n_stock"] == 4
    assert result["n_today"] == 1
    assert result["frame"].iloc[0]["族群"] == "PCB"  # 齊發族群排最前
    assert result["frame"].iloc[0]["齊發"] == "🔥"


def test_analyse_rows_no_rally_below_min():
    rows = [
        {
            "族群": "PCB",
            "代號": "3037",
            "名稱": "欣興",
            "漲幅%": 7.0,
            "點火類型": "🚀爆量突破",
            "點火日": "07/10",
            "_days": 0,
        },
        {
            "族群": "PCB",
            "代號": "8046",
            "名稱": "南電",
            "漲幅%": 8.0,
            "點火類型": "🚀爆量突破",
            "點火日": "07/10",
            "_days": 0,
        },
    ]

    assert _analyse_rows(rows)["rally"] == []  # 2 檔 < GROUP_RALLY_MIN(3)
