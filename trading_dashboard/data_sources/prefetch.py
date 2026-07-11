"""平行預抓 FinMind 個股資料。

修正原本「序列阻塞抓取」：選股雷達與 K 線網格牆原為單執行緒逐檔抓取，
全族群掃描可達數百檔、冷快取耗時上百秒且 UI 凍結。此處以執行緒池併發、
並先以代號去重（同一檔在多族群重複出現只抓一次）。
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

try:  # 將主執行緒的 Streamlit 執行情境附加到工作執行緒，避免快取失效與警告
    from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
except Exception:  # pragma: no cover - 不同 Streamlit 版本的保護
    add_script_run_ctx = None
    get_script_run_ctx = None

from ..config import PREFETCH_MAX_WORKERS, parse_stock_id
from .finmind import fetch_finmind_data

logger = logging.getLogger(__name__)


def prefetch_many(
    tickers: Iterable[str],
    start: str,
    end: str,
    *,
    fetch_fn: Callable[[str, str, str], pd.DataFrame | None] = fetch_finmind_data,
    max_workers: int = PREFETCH_MAX_WORKERS,
    progress=None,
) -> dict[str, pd.DataFrame | None]:
    """併發抓取多檔，回傳 {純代號: DataFrame|None}。

    ``progress`` 可傳入 Streamlit progress bar，會依完成數更新。
    """
    unique_ids = list(dict.fromkeys(parse_stock_id(t) for t in tickers))
    if not unique_ids:
        return {}

    ctx = get_script_run_ctx() if get_script_run_ctx else None

    def _worker(cid: str) -> tuple[str, pd.DataFrame | None]:
        if ctx is not None and add_script_run_ctx is not None:
            add_script_run_ctx(threading.current_thread(), ctx)
        try:
            return cid, fetch_fn(cid, start, end)
        except Exception as e:  # 單檔失敗不應拖垮整批
            logger.warning("預抓 %s 失敗：%s", cid, e)
            return cid, None

    results: dict[str, pd.DataFrame | None] = {}
    total = len(unique_ids)
    with ThreadPoolExecutor(max_workers=min(max_workers, total)) as ex:
        for done, (cid, df) in enumerate(ex.map(_worker, unique_ids), start=1):
            results[cid] = df
            if progress is not None:
                progress.progress(done / total, text=f"抓取中... {done}/{total}")
    return results
