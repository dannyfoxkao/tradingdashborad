# -*- coding: utf-8 -*-
"""掃描『鎖漲停點火』兩個門檻：limit_up_thr(%) × 收盤=最高(on/off)。
重用 backtest_cache 的 pkl，不重抓 FinMind。對每組算報告1狀態機交易的整體績效。"""
import os, sys, itertools
import numpy as np
import pandas as pd

import analysis
from backtest_tailwind import CACHE_ROOT, build_universe

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PERIODS = [
    ("多頭", "2025-06-01", "2026-07-09"),
    ("空頭", "2021-12-01", "2023-03-31"),
]
# (標籤, limit_up_thr, require_close_high)；thr=100 等於關閉漲停路徑=純出量突破基準
CONFIGS = [
    ("純出量(關漲停)",        100.0, True),
    ("9.8% 收=高",            9.8,   True),
    ("9.5% 收=高(現行)",      9.5,   True),
    ("9.0% 收=高",            9.0,   True),
    ("9.5% 不管收盤位置",      9.5,   False),
    ("9.0% 不管收盤位置",      9.0,   False),
]


def trades_for(df, thr, rch):
    res = analysis.red_k_tailwind_signals(df, limit_up_thr=thr, require_close_high=rch)
    if not res:
        return []
    out, b, s = [], res["buys"], res["sells"]
    for i in range(min(len(b), len(s))):
        ed, xd = b[i]["date"], s[i]["date"]
        if ed not in df.index or xd not in df.index:
            continue
        ep, xp = float(df.loc[ed, "Close"]), float(df.loc[xd, "Close"])
        if ep <= 0 or xp <= 0:
            continue
        r = (xp / ep - 1) * 100
        if not np.isfinite(r) or r <= -95:
            continue
        out.append(r)
    return out


def summarize(rets):
    a = np.array(rets, float)
    w, l = a[a > 0], a[a <= 0]
    pf = (w.sum() / abs(l.sum())) if l.sum() != 0 else float("inf")
    return dict(n=len(a), win=100 * len(w) / len(a), exp=a.mean(),
                med=np.median(a), pf=pf)


def main():
    exclude = {"大盤"}
    uniq, groups, market = build_universe(exclude)
    for pname, start, end in PERIODS:
        cache_dir = os.path.join(CACHE_ROOT, f"{start}_{end}")
        if not os.path.isdir(cache_dir):
            print(f"[{pname}] 無快取 {cache_dir}，跳過")
            continue
        dfs = []
        for sid in uniq:
            p = os.path.join(cache_dir, f"{sid}.pkl")
            if os.path.exists(p):
                dfs.append(pd.read_pickle(p))
        print("\n" + "=" * 78)
        print(f"  {pname}  {start} ~ {end}   快取 {len(dfs)} 檔")
        print("=" * 78)
        print(f"  {'設定':<20}{'筆數':>6}{'勝率':>8}{'期望值':>9}{'中位':>8}{'獲利因子':>9}")
        base_n = None
        for label, thr, rch in CONFIGS:
            rets = []
            for df in dfs:
                rets += trades_for(df, thr, rch)
            r = summarize(rets)
            if base_n is None:
                base_n = r["n"]
            d = r["n"] - base_n
            pf = "inf" if r["pf"] == float("inf") else f"{r['pf']:.2f}"
            print(f"  {label:<20}{r['n']:>6}{r['win']:>7.1f}%{r['exp']:>+8.2f}%"
                  f"{r['med']:>+7.1f}%{pf:>9}   ({d:+d} 筆)")


if __name__ == "__main__":
    main()
