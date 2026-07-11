"""append-only 歷史快照。

現行帳本（leaderboard.py）只保存每檔的「當前連續在榜狀態」，掉榜逾
緩衝即整列刪除——沒有任何日級歷史可供畫圖。本模組補上：每個交易日
寫入一份 Top-N 快照（同日重刷以新蓋舊，取盤後最終數字），供趨勢
視覺化使用。歷史自部署日起累積，無法回溯部署前。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import LEADERBOARD_HISTORY_FILE
from .persistence import atomic_write_csv

HISTORY_COLUMNS = ["date", "stock_id", "name", "market", "turnover_billion", "rank"]


def load_history(path: Path | str) -> pd.DataFrame | None:
    """讀取歷史快照 CSV；不存在回傳 None。"""
    path = Path(path)
    if not path.exists():
        return None
    return pd.read_csv(path, dtype={"stock_id": str, "date": str})


def append_leaderboard_snapshot(
    rows: list[dict],
    date_str: str,
    path: Path | str = LEADERBOARD_HISTORY_FILE,
) -> pd.DataFrame:
    """把當日 Top-N 合併名單寫入快照；rank 為各自市場內名次（1 起算）。"""
    snap_rows: list[dict] = []
    per_market_rank: dict[str, int] = {}
    for r in sorted(rows, key=lambda x: -float(x["turnover_billion"])):
        market = r["market"]
        per_market_rank[market] = per_market_rank.get(market, 0) + 1
        snap_rows.append(
            {
                "date": date_str,
                "stock_id": r["stock_id"],
                "name": r["name"],
                "market": market,
                "turnover_billion": r["turnover_billion"],
                "rank": per_market_rank[market],
            }
        )
    new_df = pd.DataFrame(snap_rows, columns=HISTORY_COLUMNS)

    old = load_history(path)
    if old is not None and not old.empty:
        old = old[old["date"].astype(str) != str(date_str)]  # 同日重刷 → 以新蓋舊
        new_df = pd.concat([old, new_df], ignore_index=True)

    atomic_write_csv(new_df, path)
    return new_df


def build_history_matrix(history_df: pd.DataFrame | None, top_n: int = 20) -> pd.DataFrame:
    """pivot 成熱圖矩陣：index=個股（取上榜次數前 top_n）、columns=日期、values=成交額(億)。"""
    if history_df is None or history_df.empty:
        return pd.DataFrame()
    df = history_df.copy()
    df["label"] = df["stock_id"].astype(str) + " " + df["name"].astype(str)
    counts = df["label"].value_counts()
    top_labels = counts.head(top_n).index
    sub = df[df["label"].isin(top_labels)]
    matrix = sub.pivot_table(index="label", columns="date", values="turnover_billion", aggfunc="last")
    return matrix.reindex(counts.loc[counts.index.isin(top_labels)].index)  # 上榜次數多者在前
