"""處置股清單（上市 TWSE + 上櫃 TPEx）。

處置期間改分盤集合競價(5分/20分撮合)、常預收款券/暫停當沖 → 量能被機械性壓縮、
不可比，故用於：① 標記處置中 ② 量能基準排除處置日 ③ K 線標出處置區間。
"""
from __future__ import annotations

import logging
import re

import pandas as pd
import requests
import streamlit as st

from ..config import DISPOSITION_TTL

logger = logging.getLogger(__name__)

TWSE_PUNISH_URL = "https://openapi.twse.com.tw/v1/announcement/punish"
TPEX_DISPOSAL_URL = "https://www.tpex.org.tw/openapi/v1/tpex_disposal_information"

_PERIOD_SLASH_RE = re.compile(r"(\d{2,3})/(\d{1,2})/(\d{1,2})")  # 帶斜線 (TWSE)
_PERIOD_COMPACT_RE = re.compile(r"(\d{7})")                       # 緊湊 7 碼 (TPEx)


def parse_period(s: object) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """處置起訖日期：支援 '115/06/29～115/07/10' 與 '1150629~1150710' 兩種民國格式。"""
    text = str(s)
    slash = _PERIOD_SLASH_RE.findall(text)
    if len(slash) >= 2:
        (y1, mo1, d1), (y2, mo2, d2) = slash[0], slash[1]
        return (
            pd.Timestamp(int(y1) + 1911, int(mo1), int(d1)),
            pd.Timestamp(int(y2) + 1911, int(mo2), int(d2)),
        )
    compact = _PERIOD_COMPACT_RE.findall(text)
    if len(compact) >= 2:
        def _c(x: str) -> pd.Timestamp:
            return pd.Timestamp(int(x[:3]) + 1911, int(x[3:5]), int(x[5:7]))
        return _c(compact[0]), _c(compact[1])
    return None, None


def measure(text: object) -> str:
    """由處置條件文字判斷撮合方式。"""
    t = str(text)
    if "20分" in t or "二十分" in t:
        return "20分撮合"
    if "5分" in t or "五分" in t:
        return "5分撮合"
    return "分盤撮合"


def is_in_disposition(disposition_map: dict, stock_id: str, ref_date) -> bool:
    """該股在 ref_date 是否仍處於處置期。"""
    ref = pd.Timestamp(ref_date).normalize()
    return any(w["start"] <= ref <= w["end"] for w in disposition_map.get(stock_id, []))


def _add(result: dict, sid: str, start, end, measure_text: str, market: str) -> None:
    if not sid or start is None or end is None:
        return
    result.setdefault(sid, []).append(
        {"start": start, "end": end, "measure": measure_text, "market": market}
    )


@st.cache_data(ttl=DISPOSITION_TTL)
def fetch_disposition_map() -> dict:
    """回傳 {stock_id: [{'start','end','measure','market'}, ...]}。"""
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    result: dict = {}

    # ── 上市 TWSE ──
    try:
        r = requests.get(TWSE_PUNISH_URL, headers=headers, timeout=12)
        for it in r.json():
            sid = str(it.get("Code", "")).strip()
            start, end = parse_period(it.get("DispositionPeriod", ""))
            _add(
                result, sid, start, end,
                measure(str(it.get("DispositionMeasures", "")) + str(it.get("Detail", ""))),
                "上市",
            )
    except (requests.RequestException, ValueError) as e:
        logger.warning("處置股(上市) 抓取失敗：%s", e)

    # ── 上櫃 TPEx ──
    try:
        r = requests.get(TPEX_DISPOSAL_URL, headers=headers, timeout=12)
        for it in r.json():
            sid = str(it.get("SecuritiesCompanyCode", "")).strip()
            start, end = parse_period(it.get("DispositionPeriod", ""))
            _add(result, sid, start, end, measure(it.get("DisposalCondition", "")), "上櫃")
    except (requests.RequestException, ValueError) as e:
        logger.warning("處置股(上櫃) 抓取失敗：%s", e)

    return result
