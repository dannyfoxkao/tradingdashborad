"""上市（TWSE）成交值排行抓取。

以「成交金額(turnover value)」排序取上市前 N。
唯一含全市場成交金額的來源是 STOCK_DAY_ALL（CSV 輸出）。
"""
from __future__ import annotations

import csv
import io
import logging
import random
import time

import requests

from ..config import DEFAULT_HEADERS
from .turnover import build_record, finalize_pool, find_column, is_common_stock

logger = logging.getLogger(__name__)

STOCK_DAY_ALL_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL"

# 表頭定位失敗時的後備欄位 index（對應現行版面；失敗會記錄 warning 而非靜默）
_DEFAULT_ID_COL = 1
_DEFAULT_NAME_COL = 2
_DEFAULT_AMOUNT_COL = 4


def fetch_twse_top20(headers: dict | None = None, date_str: str = "") -> tuple[list[dict] | None, list[str]]:
    """回傳 (上市前 N 名 list 或 None, 錯誤訊息 list)。"""
    headers = headers or DEFAULT_HEADERS
    errors: list[str] = []
    try:
        url = f"{STOCK_DAY_ALL_URL}?response=json&date={date_str}"
        time.sleep(random.uniform(0.3, 0.8))
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            raise requests.HTTPError(f"HTTP {r.status_code}")

        r.encoding = "utf-8"
        rows = list(csv.reader(io.StringIO(r.text)))
        if len(rows) < 2:
            raise ValueError("CSV 無資料列")

        header = rows[0]
        id_col = _resolve_col(find_column(header, "證券代號", "代號"), _DEFAULT_ID_COL, "證券代號", header)
        name_col = _resolve_col(find_column(header, "證券名稱", "名稱"), _DEFAULT_NAME_COL, "證券名稱", header)
        amount_col = _resolve_col(find_column(header, "成交金額", "金額"), _DEFAULT_AMOUNT_COL, "成交金額", header)

        pool: list[dict] = []
        skipped = 0
        for row in rows[1:]:
            if len(row) <= amount_col:
                continue
            sid = str(row[id_col]).strip()
            if not is_common_stock(sid):  # 排除 ETF / 權證 / 槓桿反向
                continue
            try:
                amount = float(str(row[amount_col]).replace(",", ""))
            except (ValueError, IndexError):
                skipped += 1
                continue
            if amount > 0:
                pool.append(build_record(sid, str(row[name_col]).strip(), amount, "上市"))

        if skipped:
            logger.debug("TWSE：略過 %d 筆無法解析的資料列", skipped)
        if not pool:
            raise ValueError("pool 為空")

        return finalize_pool(pool), errors

    except (requests.RequestException, ValueError) as e:
        logger.warning("上市 STOCK_DAY_ALL 抓取失敗：%s", e)
        errors.append(f"上市-STOCK_DAY_ALL: {e}")

    return None, errors


def _resolve_col(found: int | None, default: int, label: str, header: list) -> int:
    if found is None:
        logger.warning("TWSE：找不到「%s」欄位，改用預設 index %d；表頭=%s", label, default, header)
        return default
    return found
