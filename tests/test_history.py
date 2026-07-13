"""history（排行榜每日快照、雷達訊號歷史、前瞻報酬）的單元測試。"""

import pandas as pd

from trading_dashboard.history import (
    HISTORY_COLUMNS,
    SIGNAL_COLUMNS,
    append_leaderboard_snapshot,
    append_signal_snapshot,
    build_history_matrix,
    forward_return,
    load_history,
)


def _rows(turnovers=(100.0, 80.0)):
    return [
        {"stock_id": "2330", "name": "台積電", "market": "上市", "turnover_billion": turnovers[0]},
        {"stock_id": "6488", "name": "環球晶", "market": "上櫃", "turnover_billion": turnovers[1]},
    ]


def test_first_snapshot_creates_file_with_columns(tmp_path):
    path = tmp_path / "history.csv"

    df = append_leaderboard_snapshot(_rows(), "20260710", path)

    assert path.exists()
    assert list(df.columns) == HISTORY_COLUMNS
    assert len(df) == 2
    back = load_history(path)
    assert back["stock_id"].tolist() == ["2330", "6488"]


def test_same_day_snapshot_overwrites_not_duplicates(tmp_path):
    path = tmp_path / "history.csv"
    append_leaderboard_snapshot(_rows((100.0, 80.0)), "20260710", path)

    df = append_leaderboard_snapshot(_rows((150.0, 90.0)), "20260710", path)

    assert len(df) == 2  # 同日重刷 → 不重複
    assert df[df["stock_id"] == "2330"]["turnover_billion"].iloc[0] == 150.0  # 以新蓋舊


def test_cross_day_snapshots_accumulate(tmp_path):
    path = tmp_path / "history.csv"
    append_leaderboard_snapshot(_rows(), "20260709", path)

    df = append_leaderboard_snapshot(_rows(), "20260710", path)

    assert len(df) == 4
    assert set(df["date"].astype(str)) == {"20260709", "20260710"}


def test_rank_is_per_market(tmp_path):
    path = tmp_path / "history.csv"
    rows = [
        {"stock_id": "2330", "name": "台積電", "market": "上市", "turnover_billion": 100.0},
        {"stock_id": "2454", "name": "聯發科", "market": "上市", "turnover_billion": 90.0},
        {"stock_id": "6488", "name": "環球晶", "market": "上櫃", "turnover_billion": 80.0},
    ]

    df = append_leaderboard_snapshot(rows, "20260710", path)

    by_id = df.set_index("stock_id")["rank"]
    assert by_id["2330"] == 1
    assert by_id["2454"] == 2
    assert by_id["6488"] == 1  # 上櫃自成一列名次


def test_build_history_matrix_pivot(tmp_path):
    path = tmp_path / "history.csv"
    append_leaderboard_snapshot(_rows(), "20260709", path)
    append_leaderboard_snapshot(
        [{"stock_id": "2330", "name": "台積電", "market": "上市", "turnover_billion": 120.0}], "20260710", path
    )

    matrix = build_history_matrix(load_history(path))

    assert matrix.shape == (2, 2)  # 2 檔 × 2 日
    assert "2330 台積電" in matrix.index
    assert matrix.loc["2330 台積電"].notna().sum() == 2  # 兩天都在榜
    assert matrix.index[0] == "2330 台積電"  # 上榜次數多者排前


def test_build_history_matrix_empty():
    assert build_history_matrix(pd.DataFrame()).empty
    assert build_history_matrix(None).empty


# ── 雷達訊號歷史 ──


def _sig(sid="2330", name="台積電", signal="🟢 強多", close=1000.0, alpha=5.0):
    return {"stock_id": sid, "name": name, "signal": signal, "close": close, "alpha": alpha}


def test_signal_snapshot_creates_file(tmp_path):
    path = tmp_path / "signals.csv"

    df = append_signal_snapshot([_sig()], "2026-07-10", path)

    assert list(df.columns) == SIGNAL_COLUMNS
    assert len(df) == 1


def test_signal_same_day_partial_scans_union(tmp_path):
    """同日先掃「全部族群」再掃「本族群」→ 不得抹除其他訊號（聯集）。"""
    path = tmp_path / "signals.csv"
    append_signal_snapshot([_sig("2330"), _sig("6488", "環球晶")], "2026-07-10", path)

    df = append_signal_snapshot([_sig("2330", close=1010.0)], "2026-07-10", path)

    assert len(df) == 2  # 6488 保留、2330 只一筆
    assert df[df["stock_id"] == "2330"]["close"].iloc[0] == 1010.0  # (date,sid) 以新蓋舊


def test_signal_cross_day_accumulates(tmp_path):
    path = tmp_path / "signals.csv"
    append_signal_snapshot([_sig()], "2026-07-09", path)

    df = append_signal_snapshot([_sig()], "2026-07-10", path)

    assert len(df) == 2


# ── forward_return ──


def _price_df(n=30, start="2026-07-01"):
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame({"Close": [100.0 + i for i in range(n)]}, index=idx)


def test_forward_return_basic():
    df = _price_df()
    # 基準 = 2026-07-01（Close=100），5 根後 Close=105 → +5%
    assert forward_return(df, "2026-07-01", 5) == 5.0


def test_forward_return_signal_on_non_trading_day_uses_next_bar():
    df = _price_df()
    # 2026-07-04 是週六 → 基準取次一交易日 7/6（Close=103）
    r = forward_return(df, "2026-07-04", 5)
    expected = (108.0 - 103.0) / 103.0 * 100
    assert abs(r - expected) < 1e-9


def test_forward_return_insufficient_bars_returns_none():
    df = _price_df(n=5)
    assert forward_return(df, "2026-07-01", 10) is None
    assert forward_return(None, "2026-07-01", 5) is None
    assert forward_return(df, "2026-12-31", 5) is None  # 訊號日在資料之後
