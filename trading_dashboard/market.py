"""交易日推算與全市場(上市+上櫃)成交值排行抓取。"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from .config import (
    DEFAULT_HEADERS,
    MARKET_CLOSE_HOUR,
    MARKET_CLOSE_MINUTE,
    MARKET_FETCH_MAX_RETRY,
    MARKET_RETRY_JITTER,
    TZ_TAIPEI,
)
from .data_sources.tpex import fetch_tpex_top20
from .data_sources.twse import fetch_twse_top20

logger = logging.getLogger(__name__)


def resolve_trading_base_date(now: datetime) -> datetime:
    """由台灣當下時間推算對齊的交易基準日。

    收盤(14:30)前以前一日為基準，並回溯至最近的工作日。為純函式，
    傳入 tz-aware 的 now 即可單元測試（不依賴實機時鐘）。
    """
    before_close = now.hour < MARKET_CLOSE_HOUR or (now.hour == MARKET_CLOSE_HOUR and now.minute < MARKET_CLOSE_MINUTE)
    base = now - timedelta(days=1) if before_close else now
    while base.weekday() >= 5:  # 週六/日往前
        base -= timedelta(days=1)
    return base


def fetch_market_top20_raw(
    on_stage: Callable[[str], None] | None = None,
) -> tuple[list[dict] | None, list[dict] | None, str | None, list[str]]:
    """回傳 (twse_top20|None, tpex_top20|None, date_str|None, error_logs)。

    上市/上櫃同輪「並行」抓取；該日雙雙無資料時回走前一交易日，
    僅留小抖動（交易日回走不是伺服器過載重試，長 backoff 無意義；
    瞬斷 5xx 已由傳輸層 Retry adapter 處理）。``on_stage`` 供 UI
    顯示分段進度——本模組刻意不依賴 Streamlit 以保可測性。
    """
    check_date = resolve_trading_base_date(datetime.now(TZ_TAIPEI))
    all_errors: list[str] = []

    for attempt in range(MARKET_FETCH_MAX_RETRY):
        date_str = check_date.strftime("%Y%m%d")
        roc_year = check_date.year - 1911
        tpex_date_str = f"{roc_year}/{check_date.strftime('%m/%d')}"
        if on_stage:
            on_stage(f"查詢交易日 {date_str} 排行（上市＋上櫃並行）…")

        with ThreadPoolExecutor(max_workers=2) as ex:
            twse_future = ex.submit(fetch_twse_top20, DEFAULT_HEADERS, date_str)
            tpex_future = ex.submit(fetch_tpex_top20, DEFAULT_HEADERS, tpex_date_str)
            twse_top20, twse_err = twse_future.result()
            tpex_top20, tpex_err = tpex_future.result()
        all_errors.extend(twse_err + tpex_err)

        if twse_top20 or tpex_top20:
            return twse_top20, tpex_top20, date_str, all_errors

        # 全失敗 → 退回前一個交易日
        if on_stage:
            on_stage(f"{date_str} 無資料，回走前一交易日…")
        if attempt < MARKET_FETCH_MAX_RETRY - 1:
            time.sleep(random.uniform(*MARKET_RETRY_JITTER))
        check_date -= timedelta(days=1)
        while check_date.weekday() >= 5:
            check_date -= timedelta(days=1)

    return None, None, None, all_errors
