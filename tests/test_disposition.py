import pandas as pd
import pytest

from trading_dashboard.data_sources.disposition import is_in_disposition, measure, parse_period


def test_parse_period_slash_format():
    start, end = parse_period("115/06/29～115/07/10")
    assert start == pd.Timestamp(2026, 6, 29)
    assert end == pd.Timestamp(2026, 7, 10)


def test_parse_period_compact_format():
    start, end = parse_period("1150629~1150710")
    assert start == pd.Timestamp(2026, 6, 29)
    assert end == pd.Timestamp(2026, 7, 10)


def test_parse_period_unparseable():
    assert parse_period("無資料") == (None, None)


@pytest.mark.parametrize("text, expected", [
    ("處置：每20分鐘撮合一次", "20分撮合"),
    ("改為5分鐘分盤", "5分撮合"),
    ("分盤集合競價", "分盤撮合"),
])
def test_measure(text, expected):
    assert measure(text) == expected


def test_is_in_disposition():
    dmap = {"2330": [{"start": pd.Timestamp(2026, 6, 1), "end": pd.Timestamp(2026, 6, 30),
                      "measure": "5分撮合", "market": "上市"}]}
    assert is_in_disposition(dmap, "2330", "2026-06-15") is True
    assert is_in_disposition(dmap, "2330", "2026-07-01") is False
    assert is_in_disposition(dmap, "9999", "2026-06-15") is False
