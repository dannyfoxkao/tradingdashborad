"""交易日推算與全市場(上市+上櫃)成交值排行抓取。"""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta

from .config import DEFAULT_HEADERS, MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE, TZ_TAIPEI
from .data_sources.twse import fetch_twse_top20
from .data_sources.tpex import fetch_tpex_top20

logger = logging.getLogger(__name__)

_MAX_RETRY = 4


def resolve_trading_base_date(now: datetime) -> datetime:
    """由台灣當下時間推算對齊的交易基準日。

    收盤(14:30)前以前一日為基準，並回溯至最近的工作日。為純函式，
    傳入 tz-aware 的 now 即可單元測試（不依賴實機時鐘）。
    """
    before_close = now.hour < MARKET_CLOSE_HOUR or (
        now.hour == MARKET_CLOSE_HOUR and now.minute < MARKET_CLOSE_MINUTE
    )
    base = now - timedelta(days=1) if before_close else now
    while base.weekday() >= 5:  # 週六/日往前
        base -= timedelta(days=1)
    return base


def fetch_market_top20_raw():
    """回傳 (twse_top20|None, tpex_top20|None, date_str|None, error_logs)。"""
    base_date = resolve_trading_base_date(datetime.now(TZ_TAIPEI))

    check_date = base_date
    current_delay = 2.0
    all_errors: list[str] = []

    for _ in range(_MAX_RETRY):
        date_str = check_date.strftime("%Y%m%d")
        roc_year = check_date.year - 1911
        tpex_date_str = f"{roc_year}/{check_date.strftime('%m/%d')}"

        twse_top20, twse_err = fetch_twse_top20(DEFAULT_HEADERS, date_str)
        tpex_top20, tpex_err = fetch_tpex_top20(DEFAULT_HEADERS, tpex_date_str)
        all_errors.extend(twse_err + tpex_err)

        if twse_top20 or tpex_top20:
            return twse_top20, tpex_top20, date_str, all_errors

        # 全失敗 → 退回前一個交易日
        current_delay *= 1.5
        time.sleep(current_delay + random.uniform(0.5, 1.5))
        check_date -= timedelta(days=1)
        while check_date.weekday() >= 5:
            check_date -= timedelta(days=1)

    return None, None, None, all_errors
