"""處置股清單（上市 TWSE + 上櫃 TPEx）。

處置期間改分盤集合競價(5分/20分撮合)、常預收款券/暫停當沖 → 量能被機械性壓縮、
不可比，故用於：① 標記處置中 ② 量能基準排除處置日 ③ K 線標出處置區間。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from ..config import DISPOSITION_CALENDAR_FILE, DISPOSITION_TTL
from ..persistence import atomic_write_csv
from .http import get_session

logger = logging.getLogger(__name__)

CALENDAR_COLUMNS = ["stock_id", "start", "end", "measure", "market"]

TWSE_PUNISH_URL = "https://openapi.twse.com.tw/v1/announcement/punish"
TPEX_DISPOSAL_URL = "https://www.tpex.org.tw/openapi/v1/tpex_disposal_information"

_PERIOD_SLASH_RE = re.compile(r"(\d{2,3})/(\d{1,2})/(\d{1,2})")  # 帶斜線 (TWSE)
_PERIOD_COMPACT_RE = re.compile(r"(\d{7})")  # 緊湊 7 碼 (TPEx)


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
    result.setdefault(sid, []).append({"start": start, "end": end, "measure": measure_text, "market": market})


def _fetch_live_disposition() -> dict:
    """向證交所/櫃買抓「當前有效」的處置清單（API 不含已解除的歷史處置）。"""
    result: dict = {}

    # ── 上市 TWSE ──
    try:
        r = get_session().get(TWSE_PUNISH_URL, timeout=12)
        for it in r.json():
            sid = str(it.get("Code", "")).strip()
            start, end = parse_period(it.get("DispositionPeriod", ""))
            _add(
                result,
                sid,
                start,
                end,
                measure(str(it.get("DispositionMeasures", "")) + str(it.get("Detail", ""))),
                "上市",
            )
    except (requests.RequestException, ValueError) as e:
        logger.warning("處置股(上市) 抓取失敗：%s", e)

    # ── 上櫃 TPEx ──
    try:
        r = get_session().get(TPEX_DISPOSAL_URL, timeout=12)
        for it in r.json():
            sid = str(it.get("SecuritiesCompanyCode", "")).strip()
            start, end = parse_period(it.get("DispositionPeriod", ""))
            _add(result, sid, start, end, measure(it.get("DisposalCondition", "")), "上櫃")
    except (requests.RequestException, ValueError) as e:
        logger.warning("處置股(上櫃) 抓取失敗：%s", e)

    return result


def load_disposition_calendar(path: Path | str = DISPOSITION_CALENDAR_FILE) -> dict:
    """讀本地處置日曆 CSV → {stock_id: [window,...]}；不存在或壞檔回 {}。"""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        cdf = pd.read_csv(path, dtype={"stock_id": str})
    except Exception as e:
        logger.warning("處置日曆讀取失敗（忽略，視為空）：%s", e)
        return {}
    result: dict = {}
    for row in cdf.to_dict("records"):
        sid = str(row.get("stock_id", "")).strip()
        try:
            start, end = pd.Timestamp(row["start"]), pd.Timestamp(row["end"])
        except (ValueError, KeyError, TypeError):
            continue
        if not sid or pd.isna(start) or pd.isna(end):
            continue
        _add(result, sid, start, end, str(row.get("measure", "")), str(row.get("market", "")))
    return result


def save_disposition_calendar(cal: dict, path: Path | str = DISPOSITION_CALENDAR_FILE) -> None:
    """把合併後的處置日曆原子性寫回 CSV（供下次啟動累積使用）。"""
    rows = [
        {
            "stock_id": sid,
            "start": pd.Timestamp(w["start"]).strftime("%Y-%m-%d"),
            "end": pd.Timestamp(w["end"]).strftime("%Y-%m-%d"),
            "measure": w.get("measure", ""),
            "market": w.get("market", ""),
        }
        for sid, wins in cal.items()
        for w in wins
    ]
    df = pd.DataFrame(rows, columns=CALENDAR_COLUMNS).sort_values(["stock_id", "start"])
    atomic_write_csv(df, path)


def merge_disposition(base: dict, extra: dict) -> dict:
    """合併兩份 {sid:[window]}，以 (start, end) 去重；不修改輸入。"""
    out = {sid: list(wins) for sid, wins in base.items()}
    for sid, wins in extra.items():
        seen = {(pd.Timestamp(w["start"]), pd.Timestamp(w["end"])) for w in out.get(sid, [])}
        for w in wins:
            key = (pd.Timestamp(w["start"]), pd.Timestamp(w["end"]))
            if key not in seen:
                out.setdefault(sid, []).append(w)
                seen.add(key)
    return out


def disposition_mask(index: pd.DatetimeIndex, windows: list[dict]) -> pd.Series:
    """回傳 index 上每一天是否落在任一處置窗內的布林序列。"""
    mask = pd.Series(False, index=index)
    norm = index.normalize()
    for w in windows:
        mask |= (norm >= w["start"]) & (norm <= w["end"])
    return mask


@st.cache_data(ttl=DISPOSITION_TTL)
def fetch_disposition_map() -> dict:
    """回傳 本地累積日曆 ∪ 今日 live 快照，並把合併結果寫回本地日曆。

    live API 只列「當前有效」的處置；本地累積讓已解除的歷史處置保留，
    供回測的處置剔除法使用。寫回失敗僅記錄、不中斷。
    """
    merged = merge_disposition(load_disposition_calendar(DISPOSITION_CALENDAR_FILE), _fetch_live_disposition())
    try:
        save_disposition_calendar(merged, DISPOSITION_CALENDAR_FILE)
    except Exception as e:
        logger.warning("處置日曆寫回失敗（不影響本次結果）：%s", e)
    return merged
