from trading_dashboard.data_sources import prefetch as pf


def test_prefetch_dedupes_by_clean_id():
    calls: list[str] = []

    def fake_fetch(cid, start, end):
        calls.append(cid)
        return f"df-{cid}"

    out = pf.prefetch_many(["2330.TW", "2330.TW", "2454.TW"], "s", "e", fetch_fn=fake_fetch)

    assert set(out.keys()) == {"2330", "2454"}
    assert out["2330"] == "df-2330"
    assert sorted(calls) == ["2330", "2454"]  # 同代號只抓一次


def test_prefetch_empty_input():
    assert pf.prefetch_many([], "s", "e", fetch_fn=lambda *a: None) == {}


def test_prefetch_isolates_single_failure():
    def flaky(cid, start, end):
        if cid == "2330":
            raise RuntimeError("boom")
        return "ok"

    out = pf.prefetch_many(["2330.TW", "2454.TW"], "s", "e", fetch_fn=flaky)
    assert out["2330"] is None  # 單檔失敗轉為 None，不拖垮整批
    assert out["2454"] == "ok"
