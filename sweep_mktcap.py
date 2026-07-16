# -*- coding: utf-8 -*-
"""市值分層 × 紅K順風車勝率。
市值 = 發行股數(taiwan_stock_shareholding, 免費) × 最新收盤(回測快取)。
發行股數逐檔抓、存 CSV 可續傳（FinMind 限流安全）。
交易口徑：狀態機 strategy_trades（與主回測報告1一致）。"""
import os, sys, time
import numpy as np
import pandas as pd

import data
from backtest_tailwind import CACHE_ROOT, build_universe, strategy_trades

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SHARES_CSV = os.path.join(CACHE_ROOT, "shares_issued.csv")
PERIODS = [
    ("多頭", "2025-06-01", "2026-07-09"),
    ("空頭", "2021-12-01", "2023-03-31"),
]
TIERS = [("≥3000億", 3000e8, np.inf), ("1000–3000億", 1000e8, 3000e8),
         ("500–1000億", 500e8, 1000e8), ("200–500億", 200e8, 500e8),
         ("<200億", 0, 200e8)]


def load_shares(uniq, sleep=0.15):
    """發行股數（可續傳）。回傳 {sid: shares}。"""
    done = {}
    if os.path.exists(SHARES_CSV):
        old = pd.read_csv(SHARES_CSV, dtype={"sid": str})
        done = dict(zip(old.sid, old.shares))
    todo = [s for s in uniq if s not in done]
    print(f"發行股數：已快取 {len(done)}，待抓 {len(todo)}")
    for k, sid in enumerate(todo):
        try:
            d = data.api.taiwan_stock_shareholding(
                stock_id=sid, start_date="2026-07-01", end_date="2026-07-10")
            if d is not None and len(d):
                done[sid] = float(d["NumberOfSharesIssued"].iloc[-1])
        except Exception as e:
            if "402" in str(e) or "level" in str(e):
                print(f"  ...限流於 {sid}（{k}/{len(todo)}），已存進度，稍後重跑續傳")
                break
        time.sleep(sleep)
    pd.DataFrame({"sid": list(done), "shares": list(done.values())}).to_csv(SHARES_CSV, index=False)
    return done


def main():
    uniq, groups, market = build_universe({"大盤"})
    shares = load_shares(uniq)

    # 市值（用多頭段最後收盤；空頭段沿用同一分層，附註偏誤）
    caps = {}
    bull_dir = os.path.join(CACHE_ROOT, "2025-06-01_2026-07-09")
    for sid in uniq:
        p = os.path.join(bull_dir, f"{sid}.pkl")
        if sid in shares and os.path.exists(p):
            df = pd.read_pickle(p)
            caps[sid] = shares[sid] * float(df["Close"].iloc[-1])
    print(f"市值可算 {len(caps)}/{len(uniq)} 檔")
    rank = pd.Series(caps).sort_values(ascending=False)
    print("池內市值前5：", [(uniq[s], f"{v/1e12:.2f}兆") for s, v in rank.head(5).items()])
    n150 = (rank >= 900e8).sum()
    print(f"池內 ≥900億(≈全市場前150門檻) 共 {n150} 檔")

    for pname, start, end in PERIODS:
        cache_dir = os.path.join(CACHE_ROOT, f"{start}_{end}")
        if not os.path.isdir(cache_dir):
            continue
        trades = []
        for sid in uniq:
            p = os.path.join(cache_dir, f"{sid}.pkl")
            if sid not in caps or not os.path.exists(p):
                continue
            for t in strategy_trades(pd.read_pickle(p), sid, uniq[sid]):
                t["cap"] = caps[sid]
                trades.append(t)
        tr = pd.DataFrame(trades)
        print("\n" + "=" * 80)
        print(f"  {pname}  {start} ~ {end}   交易 {len(tr)} 筆")
        print("=" * 80)

        def show(lab, sub):
            if len(sub) == 0:
                print(f"    {lab:<14} n=   0")
                return
            a = sub.ret.to_numpy(float)
            w = a[a > 0]; l = a[a <= 0]
            pf = w.sum() / abs(l.sum()) if l.sum() != 0 else float("inf")
            print(f"    {lab:<14} n={len(a):>4}  win {100*(a>0).mean():5.1f}%  "
                  f"avg {a.mean():+6.2f}%  中位 {np.median(a):+6.2f}%  PF {pf:4.2f}")

        print("  ── 市值分層 ──")
        for lab, lo, hi in TIERS:
            show(lab, tr[(tr.cap >= lo) & (tr.cap < hi)])
        print("  ── 前150大 proxy（市值≥900億）──")
        show("大型股(≥900億)", tr[tr.cap >= 900e8])
        show("中小型(<900億)", tr[tr.cap < 900e8])


if __name__ == "__main__":
    main()
