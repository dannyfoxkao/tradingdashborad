import pandas as pd
import pytest

import trading_dashboard.data_sources.disposition as disposition
from trading_dashboard.data_sources.disposition import (
    disposition_mask,
    is_in_disposition,
    load_disposition_calendar,
    measure,
    merge_disposition,
    parse_period,
    save_disposition_calendar,
)


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


@pytest.mark.parametrize(
    "text, expected",
    [
        ("處置：每20分鐘撮合一次", "20分撮合"),
        ("改為5分鐘分盤", "5分撮合"),
        ("分盤集合競價", "分盤撮合"),
    ],
)
def test_measure(text, expected):
    assert measure(text) == expected


def test_is_in_disposition():
    dmap = {
        "2330": [
            {
                "start": pd.Timestamp(2026, 6, 1),
                "end": pd.Timestamp(2026, 6, 30),
                "measure": "5分撮合",
                "market": "上市",
            }
        ]
    }
    assert is_in_disposition(dmap, "2330", "2026-06-15") is True
    assert is_in_disposition(dmap, "2330", "2026-07-01") is False
    assert is_in_disposition(dmap, "9999", "2026-06-15") is False


# ── 處置日曆本地累積 ──


def _win(start, end, measure_text="分盤撮合", market="上市"):
    return {"start": pd.Timestamp(start), "end": pd.Timestamp(end), "measure": measure_text, "market": market}


def test_load_calendar_missing_file_returns_empty(tmp_path):
    assert load_disposition_calendar(tmp_path / "nope.csv") == {}


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "cal.csv"
    cal = {"2330": [_win("2026-01-05", "2026-01-16", "5分撮合")]}

    save_disposition_calendar(cal, path)
    back = load_disposition_calendar(path)

    assert back["2330"][0]["start"] == pd.Timestamp("2026-01-05")
    assert back["2330"][0]["end"] == pd.Timestamp("2026-01-16")
    assert back["2330"][0]["measure"] == "5分撮合"
    assert back["2330"][0]["market"] == "上市"


def test_load_calendar_skips_bad_rows(tmp_path):
    path = tmp_path / "cal.csv"
    path.write_text(
        "stock_id,start,end,measure,market\n2330,not-a-date,2026-01-16,x,上市\n2454,2026-01-05,2026-01-16,y,上市\n",
        encoding="utf-8",
    )

    back = load_disposition_calendar(path)

    assert "2330" not in back
    assert "2454" in back


def test_merge_dedupes_by_start_end():
    a = {"2330": [_win("2026-01-05", "2026-01-16")]}
    b = {"2330": [_win("2026-01-05", "2026-01-16"), _win("2026-03-02", "2026-03-13")]}

    merged = merge_disposition(a, b)

    assert len(merged["2330"]) == 2


def test_merge_keeps_released_windows():
    local = {"1234": [_win("2025-06-02", "2025-06-13")]}  # 已解除的歷史處置
    live = {"2330": [_win("2026-07-01", "2026-07-14")]}

    merged = merge_disposition(local, live)

    assert "1234" in merged
    assert "2330" in merged


def test_fetch_disposition_map_unions_live_and_local(tmp_path, monkeypatch):
    path = tmp_path / "cal.csv"
    save_disposition_calendar({"1234": [_win("2025-06-02", "2025-06-13")]}, path)
    monkeypatch.setattr(disposition, "DISPOSITION_CALENDAR_FILE", path)
    monkeypatch.setattr(disposition, "_fetch_live_disposition", lambda: {"2330": [_win("2026-07-01", "2026-07-14")]})
    disposition.fetch_disposition_map.clear()

    result = disposition.fetch_disposition_map()

    assert "1234" in result and "2330" in result
    back = load_disposition_calendar(path)  # live 結果已累積寫回本地日曆
    assert "2330" in back
    disposition.fetch_disposition_map.clear()


def test_disposition_mask_marks_window_days():
    idx = pd.date_range("2026-01-05", periods=10, freq="B")
    wins = [_win("2026-01-07", "2026-01-09")]

    mask = disposition_mask(idx, wins)

    assert int(mask.sum()) == 3
    assert bool(mask.loc["2026-01-08"])
    assert not bool(mask.loc["2026-01-05"])
