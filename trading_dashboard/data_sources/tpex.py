"""上櫃（TPEx）成交值排行抓取。

新版櫃買回傳格式為 ``{"tables":[{"fields":[...], "data":[...]}, ...]}``。
"""

from __future__ import annotations

import logging
import random
import time

import requests

from ..config import DEFAULT_HEADERS
from .turnover import build_record, finalize_pool, find_column, is_common_stock

logger = logging.getLogger(__name__)

DAILY_CLOSE_URL = "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php"

_DEFAULT_AMOUNT_COL = 9  # 新版於 index 9：成交金額(元)


def fetch_tpex_top20(headers: dict | None = None, tpex_date_str: str = "") -> tuple[list[dict] | None, list[str]]:
    """回傳 (上櫃前 N 名 list 或 None, 錯誤訊息 list)。"""
    headers = headers or DEFAULT_HEADERS
    errors: list[str] = []
    try:
        url = f"{DAILY_CLOSE_URL}?l=zh-tw&o=json&d={tpex_date_str}"
        time.sleep(random.uniform(0.5, 1.0))
        r = requests.get(url, headers=headers, timeout=10)

        if r.status_code != 200 or "application/json" not in r.headers.get("Content-Type", ""):
            raise requests.HTTPError(f"HTTP {r.status_code} 或非 JSON")

        jd = r.json()
        tables = jd.get("tables", [])
        table = next((t for t in tables if t.get("data")), None)
        if table is None:
            raise ValueError("tables 無資料")

        data = table.get("data", [])
        fields = table.get("fields", [])
        found = find_column(fields, "成交金額", "金額")
        if found is None:
            logger.warning("TPEx：找不到「成交金額」欄位，改用預設 index %d；fields=%s", _DEFAULT_AMOUNT_COL, fields)
            amount_col = _DEFAULT_AMOUNT_COL
        else:
            amount_col = found

        pool: list[dict] = []
        skipped = 0
        for row in data:
            if len(row) <= max(amount_col, 1):  # 先確保可安全存取 row[0]/row[1]
                skipped += 1
                continue
            sid = str(row[0]).strip()
            if not is_common_stock(sid):
                continue
            try:
                amount = float(str(row[amount_col]).replace(",", ""))
            except (ValueError, IndexError):
                skipped += 1
                continue
            if amount > 0:
                pool.append(build_record(sid, str(row[1]).strip(), amount, "上櫃"))

        if skipped:
            logger.debug("TPEx：略過 %d 筆無法解析的資料列", skipped)
        if not pool:
            raise ValueError("pool 為空")

        return finalize_pool(pool), errors

    except (requests.RequestException, ValueError) as e:
        logger.warning("上櫃 TPEx 抓取失敗：%s", e)
        errors.append(f"上櫃-TPEx: {e}")
        return None, errors
