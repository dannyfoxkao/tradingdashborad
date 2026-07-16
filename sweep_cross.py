# -*- coding: utf-8 -*-
"""「大型股(市值≥900億) × 族群齊發(±3日同族群≥3檔)」雙濾網交叉回測。
事件口徑：ignition_events（每次第一根紅K，獨立 2×ATR 移動停利）。
齊發計算與 backtest_tailwind.synchrony 完全同口徑（±3 曆日、跨族群取最大）。
市值 = shares_issued.csv(發行股數) × 多頭段最後收盤。重用磁碟快取。"""
import os, sys
from collections import defaultdict
import numpy as np
import pandas as pd

from backtest_tailwind import CACHE_ROOT, build_universe, ignition_events

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PERIODS = [
    ("多頭", "2025-06-01", "2026-07-09"),
    ("空頭", "2021-12-01", "2023-03-31"),
]
CAP_THR = 900e8          # 前150大 proxy
SHARES_CSV = os.path.join(CACHE_ROOT, "shares_issued.csv")
BULL_DIR = os.path.join(CACHE_ROOT, "2025-06-01_2026-07-09")


def load_caps(uniq):
    sh = pd.read_csv(SHARES_CSV, dtype={"sid": str})
    shares = dict(zip(sh.sid, sh.shares))
    caps = {}
    for sid in uniq:
        p = os.path.join(BULL_DIR, f"{sid}.pkl")
        if sid in shares and os.path.exists(p):
            caps[sid] = shares[sid] * float(pd.read_pickle(p)["Close"].iloc[-1])
    return caps


def add_cofire(ig, groups, win=3):
    s2g = defaultdict(list)
    for g, ss in groups.items():
        for s in ss:
            s2g[s].append(g)
    ig = ig.copy()
    ig["d"] = pd.to_datetime(ig["date"])
    gday = defaultdict(lambda: defaultdict(set))
    for _, r in ig.iterrows():
        for g in s2g.get(r.stock, []):
            gday[g][r.d].add(r.stock)

    def cofire(stock, d):
        best = 1
        for g in s2g.get(stock, []):
            got = set()
            for dd, ss in gday[g].items():
                if abs((dd - d).days) <= win:
                    got |= ss
            best = max(best, len(got))
        return best

    ig["co"] = [cofire(r.stock, r.d) for _, r in ig.iterrows()]
    return ig


def line(lab, sub):
    if len(sub) == 0:
        print(f"    {lab:<26} n=   0")
        return
    a = sub.ret.to_numpy(float)
    w, l = a[a > 0], a[a <= 0]
    pf = w.sum() / abs(l.sum()) if l.sum() != 0 else float("inf")
    pf = "inf" if pf == float("inf") else f"{pf:4.2f}"
    print(f"    {lab:<26} n={len(a):>4}  win {100*(a>0).mean():5.1f}%  "
          f"avg {a.mean():+6.2f}%  中位 {np.median(a):+6.2f}%  PF {pf}")


def main():
    uniq, groups, market = build_universe({"大盤"})
    caps = load_caps(uniq)

    for pname, start, end in PERIODS:
        cache_dir = os.path.join(CACHE_ROOT, f"{start}_{end}")
        if not os.path.isdir(cache_dir):
            continue
        ev = []
        for sid in uniq:
            p = os.path.join(cache_dir, f"{sid}.pkl")
            if sid in caps and os.path.exists(p):
                ev += ignition_events(pd.read_pickle(p), sid, uniq[sid])
        ig = add_cofire(pd.DataFrame(ev), groups)
        ig["big"] = ig.stock.map(caps) >= CAP_THR
        ig["rally"] = ig.co >= 3

        print("\n" + "=" * 84)
        print(f"  {pname}  {start} ~ {end}   點火事件 {len(ig)} 筆")
        print("=" * 84)
        line("全部（無濾網）", ig)
        print("  ── 單濾網 ──")
        line("大型股(≥900億)", ig[ig.big])
        line("族群齊發(≥3)", ig[ig.rally])
        print("  ── 2×2 交叉 ──")
        line("★ 大型股 × 齊發", ig[ig.big & ig.rally])
        line("大型股 × 孤軍/小同步", ig[ig.big & ~ig.rally])
        line("中小型 × 齊發", ig[~ig.big & ig.rally])
        line("中小型 × 孤軍/小同步", ig[~ig.big & ~ig.rally])
        print("  ── 加碼：齊發門檻拉高 ──")
        line("★ 大型股 × 齊發≥4", ig[ig.big & (ig.co >= 4)])
        line("★ 大型股 × 齊發≥5", ig[ig.big & (ig.co >= 5)])


if __name__ == "__main__":
    main()
