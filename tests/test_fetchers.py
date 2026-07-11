from datetime import datetime

import trading_dashboard.data_sources.tpex as tpex_mod
import trading_dashboard.data_sources.twse as twse_mod
import trading_dashboard.market as market_mod
from trading_dashboard.config import MARKET_FETCH_MAX_RETRY


class FakeResp:
    def __init__(self, text="", status=200, json_data=None, content_type="application/json"):
        self.status_code = status
        self.text = text
        self.encoding = "utf-8"
        self._json = json_data
        self.headers = {"Content-Type": content_type}

    def json(self):
        return self._json


class FakeSession:
    def __init__(self, resp):
        self._resp = resp

    def get(self, *args, **kwargs):
        return self._resp


def _patch_session(monkeypatch, module, resp):
    monkeypatch.setattr(module, "get_session", lambda: FakeSession(resp))


# ── TWSE ──


def test_fetch_twse_top20_parses_and_filters(monkeypatch):
    csv_text = "\r\n".join(
        [
            "日期,證券代號,證券名稱,成交股數,成交金額",
            "20260626,2330,台積電,1000,10000000000",
            "20260626,2454,聯發科,500,5000000000",
            "20260626,00981A,主動統一,100,9999999999",  # 非 4 碼純數字 → 排除
        ]
    )
    _patch_session(monkeypatch, twse_mod, FakeResp(text=csv_text))

    pool, errors = twse_mod.fetch_twse_top20({}, "20260626")
    assert errors == []
    assert [r["stock_id"] for r in pool] == ["2330", "2454"]
    assert pool[0]["turnover_billion"] == 100.0


def test_fetch_twse_top20_http_error(monkeypatch):
    _patch_session(monkeypatch, twse_mod, FakeResp(status=500))
    pool, errors = twse_mod.fetch_twse_top20({}, "20260626")
    assert pool is None
    assert errors  # 有記錄錯誤


# ── TPEx ──


def test_fetch_tpex_top20_parses(monkeypatch):
    payload = {
        "tables": [
            {
                "fields": ["代號", "名稱", "成交金額"],
                "data": [
                    ["6488", "環球晶", "8000000000"],
                    ["5483", "中美晶", "3000000000"],
                ],
            }
        ]
    }
    _patch_session(monkeypatch, tpex_mod, FakeResp(json_data=payload))

    pool, errors = tpex_mod.fetch_tpex_top20({}, "115/06/26")
    assert errors == []
    assert [r["stock_id"] for r in pool] == ["6488", "5483"]
    assert pool[0]["turnover_billion"] == 80.0


def test_fetch_tpex_top20_non_json_content_type(monkeypatch):
    _patch_session(monkeypatch, tpex_mod, FakeResp(text="<html>維護中</html>", content_type="text/html"))
    pool, errors = tpex_mod.fetch_tpex_top20({}, "115/06/26")
    assert pool is None
    assert errors


def test_fetch_tpex_top20_empty_tables(monkeypatch):
    _patch_session(monkeypatch, tpex_mod, FakeResp(json_data={"tables": []}))
    pool, errors = tpex_mod.fetch_tpex_top20({}, "115/06/26")
    assert pool is None
    assert errors


# ── market.fetch_market_top20_raw（並行 + 交易日回走）──

_TWSE_ROW = [{"stock_id": "2330", "name": "台積電", "turnover_billion": 100.0, "market": "上市"}]
_TPEX_ROW = [{"stock_id": "6488", "name": "環球晶", "turnover_billion": 80.0, "market": "上櫃"}]


def test_fetch_market_top20_raw_combines(monkeypatch):
    monkeypatch.setattr(market_mod, "fetch_twse_top20", lambda h, d: (_TWSE_ROW, []))
    monkeypatch.setattr(market_mod, "fetch_tpex_top20", lambda h, d: (_TPEX_ROW, []))

    twse, tpex, date_str, errors = market_mod.fetch_market_top20_raw()
    assert twse and tpex
    assert date_str is not None
    assert errors == []


def test_fetch_market_single_side_success_returns_immediately(monkeypatch):
    calls = {"n": 0}

    def twse_fail(h, d):
        calls["n"] += 1
        return None, [f"err-{d}"]

    monkeypatch.setattr(market_mod, "fetch_twse_top20", twse_fail)
    monkeypatch.setattr(market_mod, "fetch_tpex_top20", lambda h, d: (_TPEX_ROW, []))

    twse, tpex, _date_str, _errors = market_mod.fetch_market_top20_raw()
    assert twse is None
    assert tpex == _TPEX_ROW
    assert calls["n"] == 1  # 單邊成功即返回，不再回走


def test_fetch_market_retries_previous_day_then_succeeds(monkeypatch):
    seen_dates: list[str] = []
    sleeps: list[float] = []

    def twse(h, d):
        seen_dates.append(d)
        if len(seen_dates) == 1:
            return None, ["第一天無資料"]
        return _TWSE_ROW, []

    monkeypatch.setattr(market_mod, "fetch_twse_top20", twse)
    monkeypatch.setattr(market_mod, "fetch_tpex_top20", lambda h, d: (None, []))
    monkeypatch.setattr(market_mod.time, "sleep", lambda s: sleeps.append(s))

    twse_r, _tpex_r, date_str, errors = market_mod.fetch_market_top20_raw()
    assert twse_r == _TWSE_ROW
    assert date_str == seen_dates[1]  # 回傳的是第二輪（前一交易日）
    assert len(sleeps) == 1  # 回走一次只 sleep 一次
    assert "第一天無資料" in errors


def test_fetch_market_walks_back_over_weekend(monkeypatch):
    # 假設今天是週一（2026-07-06）收盤後 → 第一輪查週一，失敗後應跳過週末查上週五
    class _FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 7, 6, 15, 0, tzinfo=tz)

    seen_dates: list[str] = []

    def twse(h, d):
        seen_dates.append(d)
        return None, []

    monkeypatch.setattr(market_mod, "datetime", _FakeDT)
    monkeypatch.setattr(market_mod, "fetch_twse_top20", twse)
    monkeypatch.setattr(market_mod, "fetch_tpex_top20", lambda h, d: (None, []))
    monkeypatch.setattr(market_mod.time, "sleep", lambda s: None)

    result = market_mod.fetch_market_top20_raw()
    assert result[:3] == (None, None, None)
    assert len(seen_dates) == MARKET_FETCH_MAX_RETRY
    assert seen_dates[0] == "20260706"  # 週一
    assert seen_dates[1] == "20260703"  # 跳過週末 → 上週五


def test_fetch_market_reports_stages(monkeypatch):
    monkeypatch.setattr(market_mod, "fetch_twse_top20", lambda h, d: (_TWSE_ROW, []))
    monkeypatch.setattr(market_mod, "fetch_tpex_top20", lambda h, d: (_TPEX_ROW, []))
    stages: list[str] = []

    market_mod.fetch_market_top20_raw(on_stage=stages.append)
    assert stages
    assert "查詢交易日" in stages[0]
