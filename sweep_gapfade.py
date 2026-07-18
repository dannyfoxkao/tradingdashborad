# -*- coding: utf-8 -*-
"""驗證使用者觀察：「波段高點大概率發生在開高日，之後日內緩坡下滑（開高走低）」。
並回測對應的出場改良：『持倉中遇到大開高 → 開盤價直接出』 vs 原版 2×ATR 收盤 trail。

日K可測的代理（無需五分K）：
  峰值日 = 進場後至出場日之間 High 最高的那天
    gap_pk    = 峰值日開盤 / 前一日收盤 - 1（峰值日是不是開高日）
    fade_pk   = 峰值日 收盤 < 開盤（開高走低）
    open≈high = (High-Open)/Open ≤ 1%（當日高點就在開盤附近 ⇒ 開盤即最高）
出場變體：
  ride 中任一天 開盤 ≥ 前收 ×(1+g) → 以「開盤價」出場（搶在緩坡下滑前）
  其餘照舊：收盤 < 峰值-2×ATR14 → 收盤出場
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


def _arrays(df):
    o = df["Open"].to_numpy(float)
    h = df["High"].to_numpy(float)
    c = df["Close"].to_numpy(float)
    v = df["Volume"].to_numpy(float)
    volma_col = "Vol_MA20_clean" if "Vol_MA20_clean" in df.columns else (
        "Vol_MA20" if "Vol_MA20" in df.columns else None)
    volma = (df[volma_col] if volma_col else df["Volume"].rolling(20).mean()).to_numpy(float)
    atr = (df["ATR14_clean"] if "ATR14_clean" in df.columns else df["ATR14"]).to_numpy(float)
    disp = df["DispDay"].to_numpy(bool) if "DispDay" in df.columns else np.zeros(len(df), bool)
    with np.errstate(divide="ignore", invalid="ignore"):
        ret1 = np.concatenate([[np.nan], (c[1:] / c[:-1] - 1) * 100])
    return o, h, c, v, volma, atr, disp, ret1


def rides(df):
    """回傳每段 ride 的 (i_entry, i_exit_baseline)（原版 trail 出場）。"""
    o, h, c, v, volma, atr, disp, ret1 = _arrays(df)
    n = len(df)

    def _fire(i):
        if not (np.isfinite(ret1[i]) and c[i] > 0):
            return False
        locked = (ret1[i] >= LIMIT_UP) and (c[i] >= h[i] - 1e-6)
        volbrk = (ret1[i] >= CHG_THR) and (volma[i] > 0) and (v[i] >= VOL_MULT * volma[i]) and (c[i] > o[i])
        return locked or volbrk

    out = []
    for i in range(1, n):
        if not (_fire(i) and not disp[i] and not _fire(i - 1)):
            continue
        peak, exit_i = c[i], None
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
        if exit_i > i and c[i] > 0 and c[exit_i] > 0:
            out.append((i, exit_i))
    return out


def gap_exit_ret(df, i, e_base, g):
    """出場變體：ride 中開盤跳空 ≥ g → 開盤價出；否則走原版到 e_base 收盤。"""
    o, h, c, v, volma, atr, disp, ret1 = _arrays(df)
    for j in range(i + 1, e_base + 1):
        if disp[j] or not (np.isfinite(o[j]) and c[j - 1] > 0):
            continue
        if o[j] / c[j - 1] - 1 >= g:
            return (o[j] / c[i] - 1) * 100
    return (c[e_base] / c[i] - 1) * 100


def main():
    uniq, groups, market = build_universe({"大盤"})
    for pname, start, end in PERIODS:
        cache_dir = os.path.join(CACHE_ROOT, f"{start}_{end}")
        if not os.path.isdir(cache_dir):
            continue

        pk_rows, base_r, g3_r, g5_r = [], [], [], []
        for sid in uniq:
            p = os.path.join(cache_dir, f"{sid}.pkl")
            if not os.path.exists(p):
                continue
            df = pd.read_pickle(p)
            o, h, c, v, volma, atr, disp, ret1 = _arrays(df)
            for i, e in rides(df):
                seg = slice(i + 1, e + 1)
                hs = h[seg]
                if len(hs) == 0 or not np.isfinite(hs).any():
                    continue
                j = (i + 1) + int(np.nanargmax(hs))          # 峰值日
                gap_pk = o[j] / c[j - 1] - 1 if c[j - 1] > 0 else np.nan
                pk_rows.append(dict(
                    gap_pk=gap_pk * 100,
                    fade=bool(c[j] < o[j]),
                    open_is_high=bool((h[j] - o[j]) / o[j] <= 0.01 if o[j] > 0 else False),
                ))
                base_r.append((c[e] / c[i] - 1) * 100)
                g3_r.append(gap_exit_ret(df, i, e, 0.03))
                g5_r.append(gap_exit_ret(df, i, e, 0.05))

        pk = pd.DataFrame(pk_rows)
        print("\n" + "=" * 80)
        print(f"  {pname}  {start} ~ {end}   有效 ride {len(pk)} 段")
        print("=" * 80)
        print("  ── 你的觀察：波段峰值日長什麼樣 ──")
        print(f"    峰值日開高(gap≥+2%) 比例      {100*(pk.gap_pk>=2).mean():5.1f}%")
        print(f"    峰值日開高(gap≥+3%) 比例      {100*(pk.gap_pk>=3).mean():5.1f}%")
        print(f"    峰值日『開高走低』(收<開) 比例    {100*(pk.fade).mean():5.1f}%")
        print(f"    峰值日『開盤即最高』(H-O≤1%) 比例 {100*(pk.open_is_high).mean():5.1f}%")
        print(f"    開高≥2% 且 走低 比例          {100*((pk.gap_pk>=2)&pk.fade).mean():5.1f}%")
        print("  ── 出場變體：開高即出(開盤價) vs 原版收盤 trail ──")
        for lab, arr in [("原版 2×ATR trail", base_r), ("gap≥3% 開盤出", g3_r), ("gap≥5% 開盤出", g5_r)]:
            a = np.array(arr)
            w, l = a[a > 0], a[a <= 0]
            pf = w.sum() / abs(l.sum()) if l.sum() != 0 else float("inf")
            print(f"    {lab:<18} n={len(a):>4}  win {100*(a>0).mean():5.1f}%  "
                  f"avg {a.mean():+6.2f}%  中位 {np.median(a):+6.2f}%  PF {pf:4.2f}")


if __name__ == "__main__":
    main()
