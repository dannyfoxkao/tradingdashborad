import csv
import io
import os
import random
import time
from datetime import datetime, timedelta

import pandas as pd
import requests

from config import LEADERBOARD_FILE


# =====================================================================
# 🛠️ 核心功能一：全市場 (上市 + 上櫃) 混合成交值排行
# =====================================================================
def _col(fields: list, *keywords, default: int) -> int:
    """從 fields 陣列動態找欄位 index，找不到回傳 default"""
    for i, f in enumerate(fields):
        for kw in keywords:
            if kw in str(f):
                return i
    return default


def _is_common_stock(sid: str) -> bool:
    """只保留 4 碼純數字（普通股），排除 ETF / 槓桿反向 / 權證"""
    return len(sid) == 4 and sid.isdigit()


# ─── 引擎 A：上市 (TWSE) ────────────────────────────────
def _fetch_twse_top20(headers: dict, date_str: str):
    """
    以「成交金額(turnover value)」排序取上市前 20。
    註：MI_INDEX20 是依「成交股數(量)」排名且不含成交金額欄位，故不適用本目標；
        唯一含全市場成交金額的來源是 STOCK_DAY_ALL（現已改為 CSV 輸出）。
    """
    errors = []
    try:
        url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL?response=json&date={date_str}"
        time.sleep(random.uniform(0.3, 0.8))
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            raise Exception(f"HTTP {r.status_code}")

        r.encoding = "utf-8"
        rows = list(csv.reader(io.StringIO(r.text)))
        if len(rows) < 2:
            raise Exception("CSV 無資料列")

        header = rows[0]
        # 以表頭動態定位欄位，避免日後欄位位移
        id_col     = _col(header, "證券代號", "代號", default=1)
        name_col   = _col(header, "證券名稱", "名稱", default=2)
        amount_col = _col(header, "成交金額", "金額", default=4)

        pool = []
        for row in rows[1:]:
            if len(row) <= amount_col:
                continue
            sid = str(row[id_col]).strip()
            if not _is_common_stock(sid):   # 排除 ETF / 權證 / 槓桿反向
                continue
            try:
                amount = float(str(row[amount_col]).replace(",", ""))
                if amount > 0:
                    pool.append({
                        "stock_id": sid,
                        "name": str(row[name_col]).strip(),
                        "turnover_billion": round(amount / 1e8, 2),
                        "market": "上市"
                    })
            except:
                pass

        if not pool:
            raise Exception("pool 為空")

        pool.sort(key=lambda x: x["turnover_billion"], reverse=True)
        return pool[:20], errors

    except Exception as e:
        errors.append(f"上市-STOCK_DAY_ALL: {e}")

    return None, errors


# ─── 引擎 B：上櫃 (TPEx) ────────────────────────────────
def _fetch_tpex_top20(headers: dict, tpex_date_str: str):
    errors = []
    try:
        url = (
            "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/"
            f"stk_quote_result.php?l=zh-tw&o=json&d={tpex_date_str}"
        )
        time.sleep(random.uniform(0.5, 1.0))
        r = requests.get(url, headers=headers, timeout=10)

        if r.status_code != 200 or "application/json" not in r.headers.get("Content-Type", ""):
            raise Exception(f"HTTP {r.status_code} 或非 JSON")

        jd = r.json()
        # 新版櫃買回傳格式為 {"tables":[{"fields":[...], "data":[...]}, ...]}
        tables = jd.get("tables", [])
        table = next((t for t in tables if t.get("data")), None)
        if table is None:
            raise Exception("tables 無資料")

        data   = table.get("data", [])
        fields = table.get("fields", [])
        # 動態定位成交金額欄位（新版於 index 9：成交金額(元)）
        amount_col = _col(fields, "成交金額", "金額", default=9)

        pool = []
        for row in data:
            sid = str(row[0]).strip()
            if not _is_common_stock(sid):
                continue
            try:
                amount = float(str(row[amount_col]).replace(",", ""))
                if amount > 0:
                    pool.append({
                        "stock_id": sid,
                        "name": str(row[1]).strip(),
                        "turnover_billion": round(amount / 1e8, 2),
                        "market": "上櫃"
                    })
            except:
                pass

        if not pool:
            raise Exception("pool 為空")

        pool.sort(key=lambda x: x["turnover_billion"], reverse=True)
        return pool[:20], errors

    except Exception as e:
        errors.append(f"上櫃-TPEx: {e}")
        return None, errors


# ─── 主函式：上市上櫃分開回傳 ────────────────────────────
def fetch_market_top20_raw():
    """
    回傳:
      twse_top20  : list[dict] | None  → 上市前20
      tpex_top20  : list[dict] | None  → 上櫃前20
      date_str    : str                → 實際資料日期 YYYYMMDD
      error_logs  : list[str]
    """
    now = datetime.today()
    if now.hour < 14 or (now.hour == 14 and now.minute < 30):
        base_date = now - timedelta(days=1)
    else:
        base_date = now

    while base_date.weekday() >= 5:
        base_date -= timedelta(days=1)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://www.twse.com.tw/",
        "X-Requested-With": "XMLHttpRequest",
    }

    check_date    = base_date
    current_delay = 2.0
    all_errors    = []

    for attempt in range(4):
        date_str      = check_date.strftime("%Y%m%d")
        roc_year      = check_date.year - 1911
        tpex_date_str = f"{roc_year}/{check_date.strftime('%m/%d')}"

        twse_top20, twse_err = _fetch_twse_top20(headers, date_str)
        tpex_top20, tpex_err = _fetch_tpex_top20(headers, tpex_date_str)
        all_errors.extend(twse_err + tpex_err)

        if twse_top20 or tpex_top20:
            return twse_top20, tpex_top20, date_str, all_errors

        # 全失敗 → 退回前一個交易日
        current_delay *= 1.5
        time.sleep(current_delay + random.uniform(0.5, 1.5))
        check_date -= timedelta(days=1)
        while check_date.weekday() >= 5:
            check_date -= timedelta(days=1)

    return None, None, None, all_errors


def update_leaderboard_data(today_list, current_date_str):
    if not today_list:
        return None

    if os.path.exists(LEADERBOARD_FILE):
        df_old = pd.read_csv(LEADERBOARD_FILE, dtype={"stock_id": str})
        if "market" not in df_old.columns:
            df_old["market"] = "上市"  # 舊數據兼容補丁
    else:
        df_old = pd.DataFrame(columns=["stock_id", "name", "cumulative_days", "last_seen_date", "buffer_days", "market"])

    today_df = pd.DataFrame(today_list)
    updated_rows = []
    today_ids = today_df["stock_id"].tolist()

    for _, row in df_old.iterrows():
        sid = row["stock_id"]
        name = row["name"]
        cum_days = int(row["cumulative_days"])
        last_date = str(row["last_seen_date"])
        buf_days = int(row["buffer_days"])
        market_val = str(row.get("market", "上市"))

        if sid in today_ids:
            t_row = today_df[today_df["stock_id"] == sid].iloc[0]
            updated_rows.append({
                "stock_id": sid, "name": name,
                "cumulative_days": cum_days + 1,
                "last_seen_date": current_date_str,
                "buffer_days": 0,
                "market": t_row["market"],
                "turnover_billion": t_row["turnover_billion"]
            })
        else:
            if last_date != current_date_str:
                buf_days += 1
            if buf_days <= 2:
                updated_rows.append({
                    "stock_id": sid, "name": name,
                    "cumulative_days": cum_days,
                    "last_seen_date": last_date,
                    "buffer_days": buf_days,
                    "market": market_val,
                    "turnover_billion": 0.0
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
                "turnover_billion": row["turnover_billion"]
            })

    df_new = pd.DataFrame(updated_rows)
    df_new.to_csv(LEADERBOARD_FILE, index=False, encoding="utf-8")
    return df_new
