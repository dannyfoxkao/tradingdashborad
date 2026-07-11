import pandas as pd

from trading_dashboard.ui import components


def test_badge_html_escapes_text():
    out = components.badge_html("<script>alert(1)</script>", "#000000", "🔥")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "🔥" in out
    assert "#000000" in out


def test_price_badge_up_is_red():
    out = components.price_badge(110.0, 100.0)
    assert components.PRICE_UP in out
    assert "+10.00" in out


def test_price_badge_down_is_green():
    out = components.price_badge(90.0, 100.0)
    assert components.PRICE_DOWN in out


def test_price_badge_flat():
    out = components.price_badge(100.0, 100.0)
    assert components.PRICE_FLAT in out
    assert "0.00%" in out


def test_get_rangebreaks_is_cached_and_nonempty():
    idx = pd.date_range("2026-06-01", periods=10, freq="B")  # 含週末缺漏
    first = components.get_rangebreaks(idx)
    second = components.get_rangebreaks(idx)
    assert first is second  # 命中快取，回傳同一物件
    assert len(first) > 0  # 週末確實被列為缺漏日
