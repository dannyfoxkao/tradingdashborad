import trading_dashboard.data_sources.tpex as tpex_mod
import trading_dashboard.data_sources.twse as twse_mod
import trading_dashboard.market as market_mod


class FakeResp:
    def __init__(self, text="", status=200, json_data=None, content_type="application/json"):
        self.status_code = status
        self.text = text
        self.encoding = "utf-8"
        self._json = json_data
        self.headers = {"Content-Type": content_type}

    def json(self):
        return self._json


def test_fetch_twse_top20_parses_and_filters(monkeypatch):
    csv_text = "\r\n".join(
        [
            "日期,證券代號,證券名稱,成交股數,成交金額",
            "20260626,2330,台積電,1000,10000000000",
            "20260626,2454,聯發科,500,5000000000",
            "20260626,00981A,主動統一,100,9999999999",  # 非 4 碼純數字 → 排除
        ]
    )
    monkeypatch.setattr(twse_mod.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(twse_mod.requests, "get", lambda *a, **k: FakeResp(text=csv_text))

    pool, errors = twse_mod.fetch_twse_top20({}, "20260626")
    assert errors == []
    assert [r["stock_id"] for r in pool] == ["2330", "2454"]
    assert pool[0]["turnover_billion"] == 100.0


def test_fetch_twse_top20_http_error(monkeypatch):
    monkeypatch.setattr(twse_mod.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(twse_mod.requests, "get", lambda *a, **k: FakeResp(status=500))
    pool, errors = twse_mod.fetch_twse_top20({}, "20260626")
    assert pool is None
    assert errors  # 有記錄錯誤


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
    monkeypatch.setattr(tpex_mod.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(tpex_mod.requests, "get", lambda *a, **k: FakeResp(json_data=payload))

    pool, errors = tpex_mod.fetch_tpex_top20({}, "115/06/26")
    assert errors == []
    assert [r["stock_id"] for r in pool] == ["6488", "5483"]
    assert pool[0]["turnover_billion"] == 80.0


def test_fetch_market_top20_raw_combines(monkeypatch):
    monkeypatch.setattr(
        market_mod,
        "fetch_twse_top20",
        lambda h, d: ([{"stock_id": "2330", "name": "台積電", "turnover_billion": 100.0, "market": "上市"}], []),
    )
    monkeypatch.setattr(
        market_mod,
        "fetch_tpex_top20",
        lambda h, d: ([{"stock_id": "6488", "name": "環球晶", "turnover_billion": 80.0, "market": "上櫃"}], []),
    )

    twse, tpex, date_str, errors = market_mod.fetch_market_top20_raw()
    assert twse and tpex
    assert date_str is not None
    assert errors == []
