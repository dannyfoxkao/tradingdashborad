# -*- coding: utf-8 -*-
"""大盤季線(60MA)閘門回測：進場當日所屬市場指數收盤 < 季線 → 不做多。
上市股看 TAIEX、上櫃股看 TPEx。交易口徑：狀態機 strategy_trades（報告1一致）。
對照組：之前測過的月線(20MA)閘門一併重列，方便比較。重用磁碟快取。"""
import os, sys
from datetime import timedelta
import numpy as np
import pandas as pd

import data
from backtest_tailwind import CACHE_ROOT, build_universe, strategy_trades

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PERIODS = [
    ("多頭", "2025-06-01", "2026-07-09"),
    ("空頭", "2021-12-01", "2023-03-31"),
]


def index_flags(start, end):
    """{市場: DataFrame(index=date, above20, above60)}；多抓 150 天暖身讓 60MA 期初成形。"""
    buf = (pd.to_datetime(start) - timedelta(days=150)).strftime("%Y-%m-%d")
    out = {}
    for mkt, sid in (("上市", "TAIEX"), ("上櫃", "TPEx")):
        idf = data.fetch_index_close(sid, buf, end)
        if idf is None or len(idf) < 70:
            out[mkt] = None
            continue
        c = idf["Close"].astype(float)
        out[mkt] = pd.DataFrame({
            "above20": c >= c.rolling(20).mean(),
            "above60": c >= c.rolling(60).mean(),
        })
    return out


def stat(lab, sub):
    if len(sub) == 0:
        print(f"    {lab:<26} n=   0")
        return
    a = sub.ret.to_numpy(float)
    w, l = a[a > 0], a[a <= 0]
    pf = w.sum() / abs(l.sum()) if l.sum() != 0 else float("inf")
    pf = "inf" if pf == float("inf") else f"{pf:4.2f}"
    tot = a.sum()
    print(f"    {lab:<26} n={len(a):>4}  win {100*(a>0).mean():5.1f}%  "
          f"avg {a.mean():+6.2f}%  中位 {np.median(a):+6.2f}%  PF {pf}  Σ{tot:+8.0f}%")


def main():
    uniq, groups, market = build_universe({"大盤"})
    for pname, start, end in PERIODS:
        cache_dir = os.path.join(CACHE_ROOT, f"{start}_{end}")
        if not os.path.isdir(cache_dir):
            continue
        flags = index_flags(start, end)
        trades = []
        for sid in uniq:
            p = os.path.join(cache_dir, f"{sid}.pkl")
            if not os.path.exists(p):
                continue
            for t in strategy_trades(pd.read_pickle(p), sid, uniq[sid]):
                f = flags.get(market[sid])
                if f is None:
                    continue
                d = pd.to_datetime(t["entry"])
                pos = f.index.searchsorted(d, side="right") - 1   # 進場日(或其前一個交易日)的指數狀態
                if pos < 0:
                    continue
                t["above20"] = bool(f["above20"].iloc[pos])
                t["above60"] = bool(f["above60"].iloc[pos])
                trades.append(t)
        tr = pd.DataFrame(trades)
        print("\n" + "=" * 88)
        print(f"  {pname}  {start} ~ {end}   交易 {len(tr)} 筆"
              f"（指數在季線上的交易佔 {100*tr.above60.mean():.0f}%）")
        print("=" * 88)
        stat("全部（無閘門）", tr)
        print("  ── 季線(60MA)閘門 ──")
        stat("指數 ≥ 季線（保留）", tr[tr.above60])
        stat("指數 < 季線（被濾掉）", tr[~tr.above60])
        print("  ── 對照：月線(20MA)閘門 ──")
        stat("指數 ≥ 月線（保留）", tr[tr.above20])
        stat("指數 < 月線（被濾掉）", tr[~tr.above20])


if __name__ == "__main__":
    main()
