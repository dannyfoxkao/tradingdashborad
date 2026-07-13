# -*- coding: utf-8 -*-
"""掃描『進場加 5日/10日 多頭排列濾網』對紅K順風車的影響。
重用 backtest_cache 的 pkl，不重抓 FinMind。對每組算報告1狀態機交易的整體績效。

濾網變體（皆在進場當日 i 評估）：
  基準       ：無濾網（現行策略）
  MA5>MA10   ：五日線在十日線上方（多頭排列）
  C>MA5>MA10 ：收盤也要站上五日線
  排列+上彎   ：MA5>MA10 且 MA5 較 3 日前上彎
"""
import os, sys
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


def make_filter(df, mode):
    if mode == "none":
        return None
    c = df["Close"].to_numpy(float)
    m5 = df["MA5"].to_numpy(float) if "MA5" in df.columns else pd.Series(c).rolling(5).mean().to_numpy()
    m10 = df["MA10"].to_numpy(float) if "MA10" in df.columns else pd.Series(c).rolling(10).mean().to_numpy()

    def _fin(x):
        return np.isfinite(x)

    if mode == "bull":                        # MA5 > MA10
        return lambda i: _fin(m5[i]) and _fin(m10[i]) and m5[i] > m10[i]
    if mode == "c_bull":                      # C > MA5 > MA10
        return lambda i: _fin(m5[i]) and _fin(m10[i]) and c[i] > m5[i] > m10[i]
    if mode == "bull_up":                     # MA5 > MA10 且 MA5 上彎(比 3 日前高)
        return lambda i: (i >= 3 and _fin(m5[i]) and _fin(m10[i]) and _fin(m5[i - 3])
                          and m5[i] > m10[i] and m5[i] > m5[i - 3])
    raise ValueError(mode)


CONFIGS = [
    ("基準(無濾網)", "none"),
    ("MA5>MA10", "bull"),
    ("C>MA5>MA10", "c_bull"),
    ("排列+MA5上彎", "bull_up"),
]


def trades_for(df, mode):
    res = analysis.red_k_tailwind_signals(df, entry_filter=make_filter(df, mode))
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
    if len(a) == 0:
        return dict(n=0, win=np.nan, exp=np.nan, med=np.nan, pf=np.nan)
    w, l = a[a > 0], a[a <= 0]
    pf = (w.sum() / abs(l.sum())) if l.sum() != 0 else float("inf")
    return dict(n=len(a), win=100 * len(w) / len(a), exp=a.mean(),
                med=np.median(a), pf=pf)


def main():
    uniq, groups, market = build_universe({"大盤"})
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
        print(f"  {'設定':<16}{'筆數':>6}{'勝率':>8}{'期望值':>9}{'中位':>8}{'獲利因子':>9}")
        base_n = None
        for label, mode in CONFIGS:
            rets = []
            for df in dfs:
                rets += trades_for(df, mode)
            r = summarize(rets)
            if base_n is None:
                base_n = r["n"]
            pf = "inf" if r["pf"] == float("inf") else f"{r['pf']:.2f}"
            print(f"  {label:<16}{r['n']:>6}{r['win']:>7.1f}%{r['exp']:>+8.2f}%"
                  f"{r['med']:>+7.1f}%{pf:>9}   ({r['n'] - base_n:+d} 筆)")


if __name__ == "__main__":
    main()
