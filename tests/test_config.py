import json

import pytest

from trading_dashboard.config import (
    ConfigError,
    find_malformed_ids,
    load_stock_config,
    parse_stock_id,
)


@pytest.mark.parametrize(
    "ticker, expected",
    [
        ("2330.TW", "2330"),
        ("5347.TWO", "5347"),
        ("TAIEX", "TAIEX"),
        (" 2330.TW ", "2330"),
    ],
)
def test_parse_stock_id(ticker, expected):
    assert parse_stock_id(ticker) == expected


def _write(tmp_path, payload):
    p = tmp_path / "stock_config.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def test_load_stock_config_valid(tmp_path):
    p = _write(tmp_path, {"大盤": {"2330.TW": "台積電", "2454.TW": "聯發科"}})
    cfg = load_stock_config(p)
    assert cfg["大盤"]["2330.TW"] == "台積電"


def test_load_stock_config_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        load_stock_config(tmp_path / "nope.json")


def test_load_stock_config_bad_json(tmp_path):
    p = tmp_path / "stock_config.json"
    p.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_stock_config(p)


@pytest.mark.parametrize(
    "payload",
    [
        {},  # 空 dict
        [],  # 非 dict 頂層
        {"A": []},  # 族群值非 dict
        {"A": {}},  # 族群為空
        {"A": {"2330.TW": 123}},  # 名稱非字串
    ],
)
def test_load_stock_config_invalid_structure(tmp_path, payload):
    p = _write(tmp_path, payload)
    with pytest.raises(ConfigError):
        load_stock_config(p)


def test_find_malformed_ids_flags_only_invalid():
    pool = {
        "大盤": {"TAIEX": "加權指數", "TPEx": "櫃檯加權", "2330.TW": "台積電"},
        "ETF": {"00981A.TW": "主動增長", "0050.TW": "元大台灣50"},
        "打錯": {"233O.TW": "字母O打錯", "ABC": "亂填"},
    }

    assert find_malformed_ids(pool) == ["233O.TW", "ABC"]


def test_find_malformed_ids_empty_when_all_valid():
    pool = {"g": {"2330.TW": "台積電", "5347.TWO": "世界", "TAIEX": "指數"}}

    assert find_malformed_ids(pool) == []


def test_find_malformed_ids_dedupes_repeated_ticker():
    pool = {"a": {"XXX.TW": "壞"}, "b": {"XXX.TW": "壞"}}

    assert find_malformed_ids(pool) == ["XXX.TW"]
