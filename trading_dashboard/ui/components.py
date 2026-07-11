"""共用 UI 元件與小工具（徽章、漲跌標籤、rangebreaks 快取）。"""
from __future__ import annotations

import html

import pandas as pd

# 收盤漲跌色（台股慣例：紅漲綠跌）
PRICE_UP = "#ff5252"
PRICE_DOWN = "#4caf50"
PRICE_FLAT = "#9e9e9e"

# 快取「補空白斷層」用的缺漏日期，避免每次重繪都重算
_RANGEBREAKS_CACHE: dict[tuple, list[str]] = {}


def badge_html(text: str, bg: str, icon: str = "") -> str:
    """產生統一風格的色塊徽章；對文字做 HTML 跳脫以防注入。"""
    safe = html.escape(str(text))
    prefix = f"{icon} " if icon else ""
    return (
        f'<span style="background:{bg}; color:#fff; padding:2px 6px; '
        f'border-radius:4px; font-size:11px; margin-left:4px;">{prefix}{safe}</span>'
    )


def price_badge(close: float, prev_close: float) -> str:
    """收盤價與漲跌幅標籤。"""
    diff = close - prev_close
    pct = (diff / prev_close * 100) if prev_close else 0.0
    if diff > 0:
        color, body = PRICE_UP, f"{close:.2f} (+{diff:.2f}  +{pct:.2f}%)"
    elif diff < 0:
        color, body = PRICE_DOWN, f"{close:.2f} ({diff:.2f}  {pct:.2f}%)"
    else:
        color, body = PRICE_FLAT, f"{close:.2f} (0.00  0.00%)"
    return (
        f'<span style="color:{color}; font-weight:bold; font-size:14px; '
        f'margin-left:8px;">{body}</span>'
    )


def get_rangebreaks(index: pd.DatetimeIndex) -> list[str]:
    """回傳交易日之間缺漏的日曆日字串（供 Plotly rangebreaks 去空白）。

    以 (min, max, len) 為 key 快取，避免每張圖、每次 rerun 重算集合差。
    """
    key = (index.min(), index.max(), len(index))
    cached = _RANGEBREAKS_CACHE.get(key)
    if cached is None:
        missing = pd.date_range(start=index.min(), end=index.max()).difference(index)
        cached = missing.strftime("%Y-%m-%d").tolist()
        _RANGEBREAKS_CACHE[key] = cached
    return cached
