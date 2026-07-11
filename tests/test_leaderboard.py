import pandas as pd

from trading_dashboard.leaderboard import load_leaderboard, update_leaderboard_data


def _rec(sid, name="名稱", tb=100.0, market="上市"):
    return {"stock_id": sid, "name": name, "turnover_billion": tb, "market": market}


def _cum(df, sid):
    return int(df.loc[df["stock_id"] == sid, "cumulative_days"].iloc[0])


def test_new_stock_starts_at_one(tmp_path):
    p = tmp_path / "lb.csv"
    df = update_leaderboard_data([_rec("2330")], "20260626", p)
    assert _cum(df, "2330") == 1
    assert p.exists()


def test_cumulative_increments_when_seen_again(tmp_path):
    p = tmp_path / "lb.csv"
    update_leaderboard_data([_rec("2330")], "20260626", p)
    df = update_leaderboard_data([_rec("2330")], "20260627", p)
    assert _cum(df, "2330") == 2


def test_buffer_expiry_removes_after_grace(tmp_path):
    p = tmp_path / "lb.csv"
    update_leaderboard_data([_rec("2330")], "20260626", p)   # 2330 進榜
    update_leaderboard_data([_rec("9999")], "20260627", p)   # 缺席 buf=1
    update_leaderboard_data([_rec("9999")], "20260630", p)   # 缺席 buf=2
    df = update_leaderboard_data([_rec("9999")], "20260701", p)  # 缺席 buf=3 → 移除
    assert "2330" not in df["stock_id"].tolist()


def test_legacy_csv_missing_columns_is_migrated(tmp_path):
    p = tmp_path / "lb.csv"
    legacy = pd.DataFrame([{
        "stock_id": "2330", "name": "台積電",
        "cumulative_days": 5, "last_seen_date": "20260620", "buffer_days": 0,
    }])
    legacy.to_csv(p, index=False, encoding="utf-8")

    loaded = load_leaderboard(p)
    assert "turnover_billion" in loaded.columns
    assert "market" in loaded.columns

    # 不應崩潰，且累計天數正確銜接
    df = update_leaderboard_data([_rec("2330")], "20260626", p)
    assert _cum(df, "2330") == 6


def test_load_leaderboard_missing_file_returns_none(tmp_path):
    assert load_leaderboard(tmp_path / "nope.csv") is None
