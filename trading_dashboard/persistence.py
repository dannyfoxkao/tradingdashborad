"""原子檔案寫入：先寫同目錄暫存檔，成功後以 os.replace 取代目標。

os.replace 僅在同一磁碟區為原子操作（Windows/POSIX 皆然），
因此暫存檔必須與目標檔同目錄。失敗時保留原檔並清除暫存檔。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def atomic_write_csv(df: pd.DataFrame, path: Path | str, *, encoding: str = "utf-8") -> None:
    """將 DataFrame 原子性寫入 CSV（index 不輸出）。"""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        df.to_csv(tmp, index=False, encoding=encoding)
        os.replace(tmp, path)
    except Exception:
        logger.exception("原子寫入 CSV 失敗：%s", path)
        tmp.unlink(missing_ok=True)
        raise


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """DataFrame → CSV bytes（utf-8-sig 含 BOM，Excel 直接開啟不亂碼）。"""
    return df.to_csv(index=False).encode("utf-8-sig")


def atomic_write_text(path: Path | str, text: str, *, encoding: str = "utf-8") -> None:
    """將文字原子性寫入檔案。"""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, path)
    except Exception:
        logger.exception("原子寫入文字失敗：%s", path)
        tmp.unlink(missing_ok=True)
        raise
