"""回測引擎（trading_dashboard/backtest.py）純函式的單元測試。"""

import json

import numpy as np
import pandas as pd

from trading_dashboard import backtest


def _df(n=40, ignite_at=(), disp_at=()):
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
            "ATR14_clean": np.full(n, 2.0),
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


def _set(df, col, i, value):
    df.iloc[i, df.columns.get_loc(col)] = value


# ── 配對與報酬 ──


def test_trades_from_signals_pairs_and_filters():
    df = _df()
    result = {
        "buys": [
            {"date": df.index[5], "price": 99.0, "reason": "第一根紅K"},
            {"date": pd.Timestamp("2030-01-01"), "price": 99.0, "reason": "第一根紅K"},  # 不在 index → 跳過
        ],
        "sells": [
            {"date": df.index[8], "price": 101.0, "reason": "2×ATR移動停利"},
            {"date": df.index[9], "price": 101.0, "reason": "2×ATR移動停利"},
        ],
    }
    _set(df, "Close", 5, 100.0)
    _set(df, "Close", 8, 110.0)

    trades = backtest.trades_from_signals(df, result, "2330", "台積電")

    assert len(trades) == 1
    assert trades[0]["ret"] == 10.0
    assert trades[0]["entry_reason"] == "第一根紅K"
    assert backtest.trades_from_signals(df, None, "2330", "台積電") == []


def test_trade_returns_matches_engine_pairing():
    df = _df(ignite_at=(25,))
    _set(df, "Close", 28, 96.0)  # trail 出場

    rets = backtest.trade_returns(df)

    assert len(rets) == 1
    assert abs(rets[0] - (96.0 / 101.0 - 1) * 100) < 0.01  # 進出皆取收盤


def test_summarize_returns_empty_guard():
    out = backtest.summarize_returns([])

    assert out["n"] == 0  # 平面 sweep_limitup 的除零缺陷已修
    assert np.isnan(out["win"])


def test_summarize_returns_stats():
    out = backtest.summarize_returns([10.0, -5.0, 20.0, -5.0])

    assert out["n"] == 4
    assert out["win"] == 50.0
    assert out["exp"] == 5.0
    assert out["pf"] == 3.0  # 30 / 10


def test_summarize_overall_buckets():
    trades = pd.DataFrame(
        [
            {"stock": "2330", "days": 5, "ret": 10.0, "exit_reason": "2×ATR移動停利"},
            {"stock": "2330", "days": 30, "ret": -3.0, "exit_reason": "性質切換SNR<0"},
            {"stock": "2454", "days": 15, "ret": 6.0, "exit_reason": "2×ATR移動停利"},
        ]
    )

    out = backtest.summarize_overall(trades)

    assert out["total"] == 3
    assert out["stocks"] == 2
    assert out["win_rate"] == 66.7
    assert out["by_exit"]["2×ATR移動停利"]["n"] == 2
    assert backtest.summarize_overall(pd.DataFrame()) == {"total": 0}


# ── 點火事件回測 ──


def test_ignition_events_trail_exit_and_disposition_skip():
    df = _df(ignite_at=(10,), disp_at=(12,))
    _set(df, "Close", 13, 96.0)  # 處置日(12)跳過 → 13 觸發 trail

    events = backtest.ignition_events(df, "2330", "台積電")

    assert len(events) == 1
    assert events[0]["date"] == df.index[10].strftime("%Y-%m-%d")
    assert abs(events[0]["ret"] - (96.0 / 101.0 - 1) * 100) < 0.01


def test_ignition_events_max_hold_cap():
    df = _df(n=40, ignite_at=(10,))  # 永不跌破 trail → 以 max_hold 或資料尾端出場

    events = backtest.ignition_events(df, "2330", "台積電", max_hold=5)

    assert len(events) == 1
    assert events[0]["date"] == df.index[10].strftime("%Y-%m-%d")
    # 出場在 i+max_hold=15
    assert events[0]["days"] == int((df.index[15] - df.index[10]).days)


def test_ignition_events_no_fire_when_volma_zero():
    df = _df(ignite_at=(10,))
    _set(df, "Vol_MA20_clean", 10, 0.0)

    assert backtest.ignition_events(df, "2330", "台積電") == []


# ── 族群同步 ──


def test_synchrony_buckets():
    groups = {"PCB": {"A", "B", "C"}, "MEM": {"Z"}}
    ig = pd.DataFrame(
        [
            {"stock": "A", "date": "2026-07-01", "ret": 5.0},
            {"stock": "B", "date": "2026-07-01", "ret": 3.0},
            {"stock": "C", "date": "2026-07-02", "ret": -2.0},
            {"stock": "Z", "date": "2026-07-01", "ret": 1.0},
        ]
    )

    res = backtest.synchrony(ig, groups, windows=(0, 3))

    assert res["total"] == 4
    assert res["w0"]["小同步(2)"]["n"] == 2  # A、B 同日
    assert res["w0"]["孤軍(1)"]["n"] == 2  # C（隔日）、Z（族群僅一檔）
    assert res["w3"]["族群齊發(>=3)"]["n"] == 3  # ±3 日 → A/B/C 齊發


# ── 大盤 regime ──


def _index_df(closes, start="2026-01-05"):
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({"Close": closes}, index=idx)


def test_market_weather_with_injected_fetch():
    def fake_fetch(sid, start, end):
        if sid == "TAIEX":
            return _index_df([100.0 + i for i in range(60)])  # 一路走高 → safe
        return None  # TPEx 無資料

    weather = backtest.market_weather("2026-03-01", "2026-07-01", fake_fetch)

    assert weather["上市"] is not None
    assert bool(weather["上市"]["safe"].iloc[-1])
    assert weather["上櫃"] is None


def test_regime_split_asof_entry_day():
    idx = pd.bdate_range("2026-06-01", periods=10)
    frame = pd.DataFrame({"safe": [True] * 5 + [False] * 5, "strong": [True] * 5 + [False] * 5}, index=idx)
    weather = {"上市": frame}
    trades = pd.DataFrame(
        [
            {"stock": "2330", "entry": idx[2].strftime("%Y-%m-%d"), "ret": 10.0},  # 安全區
            {"stock": "2330", "entry": idx[8].strftime("%Y-%m-%d"), "ret": -5.0},  # 危險區
        ]
    )

    res = backtest.regime_split(trades, {"2330": "上市"}, weather)

    assert res["全部"]["n"] == 2
    assert res["安全區(收盤≥大盤月線)"]["n"] == 1
    assert res["危險區(<大盤月線)"]["n"] == 1
    assert res["強風(安全+MACD↑)"]["n"] == 1


# ── 股池與快取 ──


def test_build_universe_excludes_groups_and_indexes(tmp_path):
    cfg = {
        "大盤": {"TAIEX": "加權指數", "2330.TW": "台積電"},
        "PCB": {"3037.TW": "欣興", "8155.TWO": "博智"},
    }
    path = tmp_path / "stock_config.json"
    path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    uniq, groups, market = backtest.build_universe({"大盤"}, path)

    assert "2330" not in uniq  # 整個族群被排除
    assert "TAIEX" not in uniq
    assert set(uniq) == {"3037", "8155"}
    assert market["8155"] == "上櫃"
    assert market["3037"] == "上市"
    assert groups["PCB"] == {"3037", "8155"}

    uniq2, _, _ = backtest.build_universe(set(), path)
    assert "TAIEX" not in uniq2  # 指數恆排除
    assert "2330" in uniq2


def test_load_cached_frames_reads_existing_pickles(tmp_path):
    df = _df(n=10)
    df.to_pickle(tmp_path / "2330.pkl")

    frames = backtest.load_cached_frames(tmp_path, ["2330", "9999"])

    assert set(frames) == {"2330"}
    assert len(frames["2330"]) == 10
