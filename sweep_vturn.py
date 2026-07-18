# -*- coding: utf-8 -*-
"""「順達型」失敗點火的特徵回測：V轉救援 / 深水反彈 / 絞殺區點火。
事件口徑：每次第一根紅K獨立 2×ATR 移動停利（同 ignition_events），加進場日情境特徵。

特徵（皆取點火當日 i）：
  crash2  = 前 1~2 日最差單日報酬（≤-5% ⇒ 點火是暴跌後的 V轉救援）
  dist20h = 收盤距 20 日最高收盤 (%)（0=創高突破；越負越是深水反彈）
  grind   = 絞殺區旗標：ATR14_pct ≥ 其一年P80 且 SNR_t < 0（高波動+方向渾沌）
重用磁碟快取。"""
import os, sys
import numpy as np
import pandas as pd

from backtest_tailwind import (CACHE_ROOT, build_universe,
                               CHG_THR, VOL_MULT, LIMIT_UP, ATR_TRAIL, MAX_HOLD)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PERIODS = [
    ("多頭", "2025-06-01", "2026-07-09"),
    ("空頭", "2021-12-01", "2023-03-31"),
]


def events_with_features(df, sid, name):
    o = df["Open"].to_numpy(float)
    h = df["High"].to_numpy(float)
    c = df["Close"].to_numpy(float)
    v = df["Volume"].to_numpy(float)
    volma_col = "Vol_MA20_clean" if "Vol_MA20_clean" in df.columns else (
        "Vol_MA20" if "Vol_MA20" in df.columns else None)
    volma = (df[volma_col] if volma_col else df["Volume"].rolling(20).mean()).to_numpy(float)
    atr = (df["ATR14_clean"] if "ATR14_clean" in df.columns else df["ATR14"]).to_numpy(float)
    disp = df["DispDay"].to_numpy(bool) if "DispDay" in df.columns else np.zeros(len(df), bool)
    atrp = df["ATR14_pct"].to_numpy(float) if "ATR14_pct" in df.columns else np.full(len(df), np.nan)
    atrp80 = df["ATR14_pct_p80"].to_numpy(float) if "ATR14_pct_p80" in df.columns else np.full(len(df), np.nan)
    snr = df["SNR_t"].to_numpy(float) if "SNR_t" in df.columns else np.full(len(df), np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        ret1 = np.concatenate([[np.nan], (c[1:] / c[:-1] - 1) * 100])
    c20max = pd.Series(c).rolling(20, min_periods=10).max().to_numpy()
    idx, n, out = df.index, len(df), []

    def _fire(i):
        if not (np.isfinite(ret1[i]) and c[i] > 0):
            return False
        locked = (ret1[i] >= LIMIT_UP) and (c[i] >= h[i] - 1e-6)
        volbrk = (ret1[i] >= CHG_THR) and (volma[i] > 0) and (v[i] >= VOL_MULT * volma[i]) and (c[i] > o[i])
        return locked or volbrk

    for i in range(2, n):
        if not (_fire(i) and not disp[i] and not _fire(i - 1)):
            continue
        entry, peak, exit_i = c[i], c[i], None
        for j in range(i + 1, min(i + MAX_HOLD + 1, n)):
            if disp[j]:
                continue
            peak = max(peak, c[j])
            tr = peak - ATR_TRAIL * atr[j] if np.isfinite(atr[j]) else np.nan
            if np.isfinite(tr) and c[j] < tr:
                exit_i = j
                break
        if exit_i is None:
            exit_i = min(i + MAX_HOLD, n - 1)
        if entry <= 0 or c[exit_i] <= 0:
            continue
        r = (c[exit_i] / entry - 1) * 100
        if not np.isfinite(r) or r <= -95:
            continue
        crash2 = np.nanmin([ret1[i - 1], ret1[i - 2]])
        dist20h = (c[i] / c20max[i] - 1) * 100 if np.isfinite(c20max[i]) and c20max[i] > 0 else np.nan
        grind = (np.isfinite(atrp[i]) and np.isfinite(atrp80[i]) and atrp[i] >= atrp80[i]
                 and np.isfinite(snr[i]) and snr[i] < 0)
        out.append(dict(stock=sid, name=name, date=idx[i].strftime("%Y-%m-%d"), ret=r,
                        crash2=crash2, dist20h=dist20h, grind=bool(grind)))
    return out


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
    for pname, start, end in PERIODS:
        cache_dir = os.path.join(CACHE_ROOT, f"{start}_{end}")
        if not os.path.isdir(cache_dir):
            continue
        ev = []
        for sid in uniq:
            p = os.path.join(cache_dir, f"{sid}.pkl")
            if os.path.exists(p):
                ev += events_with_features(pd.read_pickle(p), sid, uniq[sid])
        ev = pd.DataFrame(ev).dropna(subset=["crash2", "dist20h"])
        print("\n" + "=" * 84)
        print(f"  {pname}  {start} ~ {end}   點火事件 {len(ev)} 筆")
        print("=" * 84)
        line("全部", ev)
        print("  ── ① V轉救援：點火前 1~2 日最差單日 ──")
        line("crash2 ≤ -5%（暴跌後救援）", ev[ev.crash2 <= -5])
        line("-5% < crash2 ≤ -3%", ev[(ev.crash2 > -5) & (ev.crash2 <= -3)])
        line("crash2 > -3%（前面安靜）", ev[ev.crash2 > -3])
        print("  ── ② 深水反彈：收盤距 20 日高 ──")
        line("dist20h ≥ -1%（貼著前高/創高）", ev[ev.dist20h >= -1])
        line("-8% ~ -1%", ev[(ev.dist20h >= -8) & (ev.dist20h < -1)])
        line("dist20h < -8%（深水區）", ev[ev.dist20h < -8])
        print("  ── ③ 絞殺區點火（高ATR × SNR<0）──")
        line("絞殺區", ev[ev.grind])
        line("非絞殺區", ev[~ev.grind])
        print("  ── 綜合：順達型 = 救援(≤-5%) 或 絞殺區 ──")
        bad = (ev.crash2 <= -5) | ev.grind
        line("順達型（剔除對象）", ev[bad])
        line("★ 過濾後保留", ev[~bad])


if __name__ == "__main__":
    main()
