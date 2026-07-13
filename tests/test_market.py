from datetime import datetime

from trading_dashboard.config import TZ_TAIPEI
from trading_dashboard.market import resolve_trading_base_date


def _at(y, m, d, h, mi):
    return datetime(y, m, d, h, mi, tzinfo=TZ_TAIPEI)


def test_before_close_uses_previous_trading_day():
    # 2026-06-29 為週一 09:00（盤中前）→ 退回上週五 06-26
    r = resolve_trading_base_date(_at(2026, 6, 29, 9, 0))
    assert (r.year, r.month, r.day) == (2026, 6, 26)


def test_after_close_uses_same_day():
    r = resolve_trading_base_date(_at(2026, 6, 29, 15, 0))
    assert (r.month, r.day) == (6, 29)


def test_exactly_at_close_minute_is_not_before():
    # 14:30 整不算盤中前（now.minute < 30 為 False）
    r = resolve_trading_base_date(_at(2026, 6, 29, 14, 30))
    assert (r.month, r.day) == (6, 29)


def test_one_minute_before_close_is_before():
    r = resolve_trading_base_date(_at(2026, 6, 29, 14, 29))
    assert (r.month, r.day) == (6, 26)


def test_weekend_skips_back_to_friday():
    # 週六盤後 → 仍回最近交易日（週五 06-26）
    r = resolve_trading_base_date(_at(2026, 6, 27, 15, 0))
    assert (r.month, r.day) == (6, 26)
