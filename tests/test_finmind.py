"""finmind 資料層（欄位轉換、重試、降級）的單元測試。

以假 DataLoader 取代 init_finmind，不連網。@st.cache_data 在裸 pytest
下仍會快取，故每個測試前清空快取避免互相污染。
"""

import pandas as pd
import pytest

import trading_dashboard.data_sources.finmind as finmind_mod
from trading_dashboard.data_sources.finmind import (
    fetch_benchmark_data,
    fetch_finmind_data,
    fetch_index_close,
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """清快取 + 關掉重試間的 sleep。"""
    fetch_finmind_data.clear()
    fetch_index_close.clear()
    monkeypatch.setattr(finmind_mod.time, "sleep", lambda s: None)


class FakeLoader:
    """依序回放 frames；元素為 Exception 時拋出。"""

    def __init__(self, frames):
        self.frames = list(frames)
        self.calls = 0

    def taiwan_stock_daily(self, stock_id, start_date, end_date):
        self.calls += 1
        item = self.frames.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _raw_df(n=30, with_money=True):
    data = {
        "date": pd.date_range("2026-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
        "open": [100.0 + i for i in range(n)],
        "max": [101.0 + i for i in range(n)],
        "min": [99.0 + i for i in range(n)],
        "close": [100.5 + i for i in range(n)],
        "Trading_Volume": [1000.0] * n,
    }
    if with_money:
        data["Trading_money"] = [100_000.0] * n
    return pd.DataFrame(data)


def _use(monkeypatch, loader):
    monkeypatch.setattr(finmind_mod, "init_finmind", lambda: loader)
    return loader


def test_fetch_finmind_data_renames_and_enriches(monkeypatch):
    _use(monkeypatch, FakeLoader([_raw_df()]))

    df = fetch_finmind_data("2330.TW", "2026-01-01", "2026-02-28")

    for col in ["Open", "High", "Low", "Close", "Volume", "Turnover", "MA5", "Vol_MA20"]:
        assert col in df.columns
    assert isinstance(df.index, pd.DatetimeIndex)


def test_fetch_finmind_data_empty_returns_none(monkeypatch):
    _use(monkeypatch, FakeLoader([pd.DataFrame()]))
    assert fetch_finmind_data("1101.TW", "2026-01-01", "2026-02-28") is None


def test_fetch_finmind_data_retries_then_succeeds(monkeypatch):
    loader = _use(monkeypatch, FakeLoader([RuntimeError("rate limited"), _raw_df()]))

    df = fetch_finmind_data("2454.TW", "2026-01-01", "2026-02-28")

    assert df is not None
    assert loader.calls == 2


def test_fetch_finmind_data_all_attempts_fail_returns_none(monkeypatch):
    loader = _use(monkeypatch, FakeLoader([RuntimeError("boom"), RuntimeError("boom")]))

    assert fetch_finmind_data("2317.TW", "2026-01-01", "2026-02-28") is None
    assert loader.calls == 2  # FINMIND_RETRY_ATTEMPTS


def test_fetch_finmind_data_backfills_turnover(monkeypatch):
    _use(monkeypatch, FakeLoader([_raw_df(with_money=False)]))

    df = fetch_finmind_data("3231.TW", "2026-01-01", "2026-02-28")

    assert "Turnover" in df.columns
    expected = df["Close"].iloc[-1] * df["Volume"].iloc[-1]
    assert df["Turnover"].iloc[-1] == pytest.approx(expected)


def test_fetch_index_close_returns_close_only(monkeypatch):
    _use(monkeypatch, FakeLoader([_raw_df()]))

    df = fetch_index_close("TPEx", "2026-01-01", "2026-02-28")

    assert list(df.columns) == ["Close"]
    assert isinstance(df.index, pd.DatetimeIndex)


def test_load_token_prefers_file_over_env(tmp_path, monkeypatch):
    p = tmp_path / "finmind_token.json"
    p.write_text('{"api_token": " file-tok "}', encoding="utf-8")
    monkeypatch.setenv("FINMIND_TOKEN", "env-tok")

    assert finmind_mod._load_finmind_token(p) == "file-tok"


def test_load_token_falls_back_to_env(tmp_path, monkeypatch):
    monkeypatch.setenv("FINMIND_TOKEN", "env-tok")

    assert finmind_mod._load_finmind_token(tmp_path / "nope.json") == "env-tok"


def test_load_token_bad_json_falls_back_to_env(tmp_path, monkeypatch):
    p = tmp_path / "finmind_token.json"
    p.write_text("{broken", encoding="utf-8")
    monkeypatch.setenv("FINMIND_TOKEN", "env-tok")

    assert finmind_mod._load_finmind_token(p) == "env-tok"


def test_fetch_benchmark_data_delegates_to_index_close(monkeypatch):
    seen = {}

    def fake_index_close(stock_id, start, end):
        seen["stock_id"] = stock_id
        return pd.DataFrame({"Close": [1.0]})

    monkeypatch.setattr(finmind_mod, "fetch_index_close", fake_index_close)

    df = fetch_benchmark_data("2026-01-01", "2026-02-28")
    assert seen["stock_id"] == "TAIEX"
    assert df is not None
