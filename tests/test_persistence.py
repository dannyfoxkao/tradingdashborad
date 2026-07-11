"""persistence 原子寫入與匯出的單元測試。"""

import io

import pandas as pd
import pytest

from trading_dashboard.persistence import atomic_write_csv, atomic_write_text, to_csv_bytes


def test_to_csv_bytes_has_bom_and_roundtrips():
    df = pd.DataFrame({"代號": ["2330"], "名稱": ["台積電"], "收盤": [1000.0]})

    data = to_csv_bytes(df)

    assert data.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM → Excel 直接開不亂碼
    back = pd.read_csv(io.BytesIO(data), encoding="utf-8-sig", dtype={"代號": str})
    assert back["代號"].tolist() == ["2330"]
    assert back["名稱"].tolist() == ["台積電"]


def test_atomic_write_csv_roundtrip(tmp_path):
    df = pd.DataFrame({"stock_id": ["2330", "0050"], "value": [1.5, 2.0]})
    target = tmp_path / "out.csv"

    atomic_write_csv(df, target)

    back = pd.read_csv(target, dtype={"stock_id": str})
    assert back["stock_id"].tolist() == ["2330", "0050"]
    assert back["value"].tolist() == [1.5, 2.0]
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_write_csv_overwrites_existing(tmp_path):
    target = tmp_path / "out.csv"
    atomic_write_csv(pd.DataFrame({"a": [1]}), target)

    atomic_write_csv(pd.DataFrame({"a": [2]}), target)

    assert pd.read_csv(target)["a"].tolist() == [2]


def test_atomic_write_csv_failure_keeps_original_and_no_tmp(tmp_path, monkeypatch):
    target = tmp_path / "out.csv"
    target.write_text("original", encoding="utf-8")

    def boom(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_csv", boom)
    with pytest.raises(OSError):
        atomic_write_csv(pd.DataFrame({"a": [1]}), target)

    assert target.read_text(encoding="utf-8") == "original"
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_write_text_roundtrip(tmp_path):
    target = tmp_path / "out.json"

    atomic_write_text(target, '{"族群": {}}')

    assert target.read_text(encoding="utf-8") == '{"族群": {}}'
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_write_text_failure_keeps_original_and_no_tmp(tmp_path, monkeypatch):
    import os

    target = tmp_path / "out.json"
    target.write_text("original", encoding="utf-8")

    def boom(src, dst):
        raise OSError("locked")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_text(target, "new content")

    assert target.read_text(encoding="utf-8") == "original"
    assert not list(tmp_path.glob("*.tmp"))
