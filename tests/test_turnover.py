import pytest

from trading_dashboard.data_sources.turnover import (
    build_record,
    finalize_pool,
    find_column,
    is_common_stock,
)


def test_find_column_hit():
    assert find_column(["證券代號", "證券名稱", "成交金額"], "成交金額", "金額") == 2


def test_find_column_miss_returns_none():
    assert find_column(["a", "b", "c"], "成交金額", "金額") is None


@pytest.mark.parametrize(
    "sid, expected",
    [
        ("2330", True),
        ("0050", True),  # 4 碼純數字即視為普通股（與原邏輯一致）
        ("00981A", False),  # 含英文字母
        ("233", False),  # 少於 4 碼
        ("23300", False),  # 多於 4 碼
    ],
)
def test_is_common_stock(sid, expected):
    assert is_common_stock(sid) is expected


def test_build_record_converts_to_billion():
    rec = build_record("2330", "台積電", 1e10, "上市")
    assert rec == {"stock_id": "2330", "name": "台積電", "turnover_billion": 100.0, "market": "上市"}


def test_finalize_pool_sorts_desc_and_truncates():
    pool = [
        {"stock_id": "A", "turnover_billion": 1.0},
        {"stock_id": "B", "turnover_billion": 3.0},
        {"stock_id": "C", "turnover_billion": 2.0},
    ]
    top2 = finalize_pool(pool, top_n=2)
    assert [r["stock_id"] for r in top2] == ["B", "C"]
