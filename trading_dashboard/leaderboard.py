"""熱錢排行帳本（CSV）讀寫與向後相容遷移。

帳本累積每檔股票進入全市場成交值前 N 的天數，並以 buffer 緩衝短暫掉榜。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import LEADERBOARD_BUFFER_DAYS, LEADERBOARD_FILE
from .persistence import atomic_write_csv

LEDGER_COLUMNS = [
    "stock_id", "name", "cumulative_days", "last_seen_date",
    "buffer_days", "market", "turnover_billion",
]


def load_leaderboard(path: Path | str = LEADERBOARD_FILE) -> pd.DataFrame | None:
    """讀取帳本 CSV；不存在回傳 None。對舊版缺欄位做遷移補丁。"""
    path = Path(path)
    if not path.exists():
        return None
    df = pd.read_csv(path, dtype={"stock_id": str})
    if "market" not in df.columns:
        df["market"] = "上市"
    if "turnover_billion" not in df.columns:
        df["turnover_billion"] = 0.0
    return df


def update_leaderboard_data(
    today_list: list[dict],
    current_date_str: str,
    path: Path | str = LEADERBOARD_FILE,
) -> pd.DataFrame | None:
    """以今日名單更新帳本並寫回 CSV，回傳更新後的 DataFrame。"""
    if not today_list:
        return None

    df_old = load_leaderboard(path)
    if df_old is None:
        df_old = pd.DataFrame(columns=LEDGER_COLUMNS)

    today_df = pd.DataFrame(today_list)
    today_ids = today_df["stock_id"].tolist()
    updated_rows: list[dict] = []

    for _, row in df_old.iterrows():
        sid = row["stock_id"]
        if sid in today_ids:
            t_row = today_df[today_df["stock_id"] == sid].iloc[0]
            updated_rows.append({
                "stock_id": sid, "name": row["name"],
                "cumulative_days": int(row["cumulative_days"]) + 1,
                "last_seen_date": current_date_str,
                "buffer_days": 0,
                "market": t_row["market"],
                "turnover_billion": t_row["turnover_billion"],
            })
        else:
            buf_days = int(row["buffer_days"])
            last_date = str(row["last_seen_date"])
            if last_date != current_date_str:
                buf_days += 1
            if buf_days <= LEADERBOARD_BUFFER_DAYS:
                updated_rows.append({
                    "stock_id": sid, "name": row["name"],
                    "cumulative_days": int(row["cumulative_days"]),
                    "last_seen_date": last_date,
                    "buffer_days": buf_days,
                    "market": str(row.get("market", "上市")),
                    "turnover_billion": 0.0,
                })

    old_ids = df_old["stock_id"].tolist() if not df_old.empty else []
    for _, row in today_df.iterrows():
        sid = row["stock_id"]
        if sid not in old_ids:
            updated_rows.append({
                "stock_id": sid, "name": row["name"],
                "cumulative_days": 1,
                "last_seen_date": current_date_str,
                "buffer_days": 0,
                "market": row["market"],
                "turnover_billion": row["turnover_billion"],
            })

    df_new = pd.DataFrame(updated_rows, columns=LEDGER_COLUMNS)
    atomic_write_csv(df_new, path)
    return df_new
