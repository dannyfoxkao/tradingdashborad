"""TWSE / TPEx 成交值排行的共用工具（DRY）。"""

from __future__ import annotations

from ..config import HUNDRED_MILLION, TOP_N


def find_column(fields: list, *keywords: str) -> int | None:
    """依表頭關鍵字動態定位欄位 index；找不到回傳 ``None``（不再靜默用預設值）。"""
    for i, field in enumerate(fields):
        text = str(field)
        for kw in keywords:
            if kw in text:
                return i
    return None


def is_common_stock(stock_id: str) -> bool:
    """只保留 4 碼純數字（普通股），排除 ETF / 槓桿反向 / 權證。"""
    return len(stock_id) == 4 and stock_id.isdigit()


def build_record(stock_id: str, name: str, amount: float, market: str) -> dict:
    """組成單筆排行紀錄，成交金額換算為「億」。"""
    return {
        "stock_id": stock_id,
        "name": name,
        "turnover_billion": round(amount / HUNDRED_MILLION, 2),
        "market": market,
    }


def finalize_pool(pool: list[dict], top_n: int = TOP_N) -> list[dict]:
    """依成交值由大到小排序並取前 ``top_n`` 檔。"""
    pool.sort(key=lambda x: x["turnover_billion"], reverse=True)
    return pool[:top_n]
