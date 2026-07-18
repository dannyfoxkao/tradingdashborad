# -*- coding: utf-8 -*-
"""五分K實測：「盤中跌破昨日已知 trail 價 → 當下出場」 vs 原版「收盤跌破才出」。

trail_known(第j日) = 進場後至 j-1 日的最高收盤 − 2×ATR14(j-1)   ← 只用昨天資訊，無偷看
變體：ride 任一持倉日，第一根 5分K收盤 < trail_known → 以該根收盤出場
基準：原版日線口徑（收盤 < 當日trail → 收盤出場）
樣本：進場日在 5分K 可得範圍(約60天)內的 ride。含還原價不一致防呆。"""
import sys, time
import numpy as np
import pandas as pd

import data
from backtest_tailwind import build_universe, ATR_TRAIL
from sweep_gapfade import rides, _arrays

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

START_5M = pd.Timestamp("2026-05-22")


def main():
    import yfinance as yf
    uniq, groups, market = build_universe({"大盤"})
    base_r, var_r, early, saved_on_exitday, rows = [], [], 0, [], 0
    m5_cache = {}

    for sid, name in uniq.items():
        df = data.fetch_finmind_data(sid, "2026-03-01", "2026-07-18")
        if df is None or len(df) < 40:
            continue
        o, h, c, v, volma, atr, disp, ret1 = _arrays(df)
        rd = [(i, e) for i, e in rides(df) if df.index[i] >= START_5M and e > i]
        if not rd:
            continue
        if sid not in m5_cache:
            tkr = f"{sid}.TWO" if market[sid] == "上櫃" else f"{sid}.TW"
            try:
                m = yf.download(tkr, period="60d", interval="5m", progress=False, auto_adjust=False)
                time.sleep(0.25)
            except Exception:
                m = None
            if m is not None and len(m):
                m.columns = [x[0] if isinstance(x, tuple) else x for x in m.columns]
                m = m.tz_convert("Asia/Taipei").tz_localize(None) if m.index.tz is not None else m
            m5_cache[sid] = m
        m = m5_cache[sid]
        if m is None or len(m) == 0:
            continue

        for i, e in rd:
            base_ret = (c[e] / c[i] - 1) * 100
            exit_px, exit_j = None, None
            for j in range(i + 1, e + 1):
                if disp[j] or not np.isfinite(atr[j - 1]):
                    continue
                trail_known = np.nanmax(c[i:j]) - ATR_TRAIL * atr[j - 1]
                if not np.isfinite(trail_known):
                    continue
                d0 = df.index[j].normalize()
                day = m[(m.index >= d0) & (m.index < d0 + pd.Timedelta(days=1))]
                if len(day) < 10:
                    continue
                # 還原價防呆：5分K收盤 vs 日K收盤差>3% ⇒ 該股價序不一致，跳過整段
                if abs(float(day["Close"].iloc[-1]) / c[j] - 1) > 0.03:
                    exit_px = None
                    break
                cl = day["Close"].astype(float)
                hit = cl[cl < trail_known]
                if len(hit):
                    exit_px, exit_j = float(hit.iloc[0]), j
                    break
            if exit_px is None and exit_j is None:
                var_ret = base_ret                    # 全程未盤中破線（或資料防呆跳過）
            else:
                var_ret = (exit_px / c[i] - 1) * 100
                if exit_j < e:
                    early += 1                        # 提早下車（日線其實還沒出）
                elif exit_j == e:
                    saved_on_exitday.append((exit_px / c[e] - 1) * 100)
            base_r.append(base_ret)
            var_r.append(var_ret)
            rows += 1

    def stat(lab, arr):
        a = np.array(arr, float)
        w, l = a[a > 0], a[a <= 0]
        pf = w.sum() / abs(l.sum()) if l.sum() != 0 else float("inf")
        print(f"    {lab:<22} n={len(a):>4}  win {100*(a>0).mean():5.1f}%  "
              f"avg {a.mean():+6.2f}%  中位 {np.median(a):+6.2f}%  PF {pf:4.2f}")

    print("=" * 80)
    print(f"  樣本：進場於 {START_5M.date()} 之後的 ride 共 {rows} 段")
    print("=" * 80)
    stat("基準：收盤破trail才出", base_r)
    stat("變體：盤中破trail即出", var_r)
    print(f"    提早下車（盤中破線但當日收盤沒破，日線本不出場）：{early} 段")
    if saved_on_exitday:
        s = np.array(saved_on_exitday)
        print(f"    出場日當天盤中先出：{len(s)} 段  出場價比收盤 平均 {s.mean():+5.2f}%  中位 {np.median(s):+5.2f}%")


if __name__ == "__main__":
    main()
