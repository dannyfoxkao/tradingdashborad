# -*- coding: utf-8 -*-
"""市場寬度(breadth)對紅K順風車點火品質的影響。
驗證假設：「大盤沒動、但個股一直往下（寬度退潮）」的環境，點火容易被停損。

特徵（皆取進場當日）：
  B      = 全池站上月線比例(%)   （寬度位階）
  dB10   = B 較 10 個交易日前的變化(百分點)（寬度動能：退潮/擴張）
  idx10  = 加權指數近 10 日報酬(%)
  背離    = idx10 > -2%（指數撐著）且 dB10 < -5pp（個股退潮）→ 使用者描述的盤況
事件口徑：ignition_events（每次第一根紅K獨立 2×ATR 移動停利）。重用磁碟快取。"""
import os, sys
from datetime import timedelta
import numpy as np
import pandas as pd

import data
from backtest_tailwind import CACHE_ROOT, build_universe, ignition_events

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PERIODS = [
    ("多頭", "2025-06-01", "2026-07-09"),
    ("空頭", "2021-12-01", "2023-03-31"),
]


def load_dfs(uniq, cache_dir):
    dfs = {}
    for sid in uniq:
        p = os.path.join(cache_dir, f"{sid}.pkl")
        if os.path.exists(p):
            dfs[sid] = pd.read_pickle(p)
    return dfs


def breadth_series(dfs, min_n=30):
    """每日『收盤 > 月線』的個股比例(%)。"""
    cols = []
    for sid, df in dfs.items():
        if "MA20" in df.columns:
            ma = df["MA20"]
        else:
            ma = df["Close"].rolling(20).mean()
        cols.append((df["Close"] > ma).where(ma.notna()).rename(sid))
    m = pd.concat(cols, axis=1).sort_index()
    b = m.mean(axis=1) * 100
    b[m.notna().sum(axis=1) < min_n] = np.nan
    return b


def stats(sub):
    if len(sub) == 0:
        return "     n=   0      —"
    a = sub["ret"].to_numpy(float)
    w = (a > 0).mean() * 100
    return f"n={len(a):>5}  win {w:5.1f}%  avg {a.mean():+6.2f}%  中位 {np.median(a):+6.2f}%"


def main():
    uniq, groups, market = build_universe({"大盤"})
    for pname, start, end in PERIODS:
        cache_dir = os.path.join(CACHE_ROOT, f"{start}_{end}")
        if not os.path.isdir(cache_dir):
            print(f"[{pname}] 無快取，跳過")
            continue
        dfs = load_dfs(uniq, cache_dir)

        # 寬度與指數
        B = breadth_series(dfs)
        buf = (pd.to_datetime(start) - timedelta(days=40)).strftime("%Y-%m-%d")
        idxdf = data.fetch_index_close("TAIEX", buf, end)
        idx10 = idxdf["Close"].pct_change(10) * 100 if idxdf is not None else None

        # 點火事件 + 進場日特徵
        ev = []
        for sid, df in dfs.items():
            ev += ignition_events(df, sid, uniq[sid])
        ev = pd.DataFrame(ev)
        ev["d"] = pd.to_datetime(ev["date"])
        dB10 = B - B.shift(10)
        ev["B"] = ev["d"].map(B)
        ev["dB10"] = ev["d"].map(dB10)
        ev["idx10"] = ev["d"].map(idx10) if idx10 is not None else np.nan
        ev = ev.dropna(subset=["B", "dB10"])

        print("\n" + "=" * 84)
        print(f"  {pname}  {start} ~ {end}   事件 {len(ev)} 筆   全池寬度中位 {B.median():.0f}%")
        print("=" * 84)

        print("  ── 寬度位階 B（進場日全池站上月線比例）──")
        for lab, lo, hi in [("<40%（弱）", -1, 40), ("40–55%", 40, 55),
                            ("55–70%", 55, 70), (">70%（強）", 70, 999)]:
            print(f"    {lab:<12}", stats(ev[(ev.B > lo) & (ev.B <= hi)]))

        print("  ── 寬度動能 dB10（10日變化）──")
        for lab, lo, hi in [("退潮 <-5pp", -999, -5), ("平 -5~+5", -5, 5), ("擴張 >+5pp", 5, 999)]:
            print(f"    {lab:<12}", stats(ev[(ev.dB10 > lo) & (ev.dB10 <= hi)]))

        if ev["idx10"].notna().any():
            div = (ev.idx10 > -2) & (ev.dB10 < -5)
            print("  ── 背離：指數撐著(idx10>-2%) 但 個股退潮(dB10<-5pp) ──")
            print(f"    {'背離期進場':<12}", stats(ev[div]))
            print(f"    {'其餘':<12}", stats(ev[~div]))


if __name__ == "__main__":
    main()
