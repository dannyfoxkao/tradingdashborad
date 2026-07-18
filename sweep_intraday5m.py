# -*- coding: utf-8 -*-
"""五分K實測「開高後沿5MA緩降」出場規則（yfinance 5m，僅最近約60天可得）。

樣本：紅K順風車 ride 中「開高 ≥3%」的持倉日。
規則（使用者觀察）：09:30 後第一次出現
    5分K收盤 < 當日開盤價  且  5分K收盤 < 日內5MA  且  5MA 下彎
  → 以該根收盤出場；否則抱到收盤（原版日線口徑）。
對照亦測 R1：10:00 檢查點——現價 < 開盤 → 出場。
評估：規則出場價 vs 當日收盤（正=比等收盤多保住）；並統計誤殺（出場後尾盤反而收更高）。"""
import sys, time
import numpy as np
import pandas as pd

import data
from backtest_tailwind import build_universe
from sweep_gapfade import rides, _arrays

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

GAP_THR = 0.03
START_5M = pd.Timestamp("2026-05-22")     # yfinance 5m 約可回看 60 天


def collect_gap_days():
    uniq, groups, market = build_universe({"大盤"})
    out = []
    for sid, name in uniq.items():
        df = data.fetch_finmind_data(sid, "2026-03-01", "2026-07-18")
        if df is None or len(df) < 40:
            continue
        o, h, c, v, volma, atr, disp, ret1 = _arrays(df)
        for i, e in rides(df):
            hi_max = np.nanmax(h[i + 1:e + 1]) if e > i else np.nan
            for j in range(i + 1, e + 1):
                if df.index[j] < START_5M or c[j - 1] <= 0:
                    continue
                gap = o[j] / c[j - 1] - 1
                if gap >= GAP_THR:
                    out.append(dict(sid=sid, name=name, mkt=market[sid],
                                    d=df.index[j].normalize(), gap=gap * 100,
                                    day_open=o[j], day_close=c[j], day_high=h[j],
                                    peak_day=bool(np.isfinite(hi_max) and h[j] >= hi_max - 1e-9)))
    return pd.DataFrame(out)


def eval_rules(gd):
    import yfinance as yf
    res = []
    for sid, sub in gd.groupby("sid"):
        tkr = f"{sid}.TWO" if sub.mkt.iloc[0] == "上櫃" else f"{sid}.TW"
        try:
            m = yf.download(tkr, period="60d", interval="5m", progress=False, auto_adjust=False)
        except Exception:
            continue
        time.sleep(0.25)
        if m is None or len(m) == 0:
            continue
        m.columns = [c[0] if isinstance(c, tuple) else c for c in m.columns]
        m = m.tz_localize(None) if m.index.tz is None else m.tz_convert("Asia/Taipei").tz_localize(None)
        for _, r in sub.iterrows():
            day = m[(m.index >= r.d) & (m.index < r.d + pd.Timedelta(days=1))]
            if len(day) < 20:
                continue
            cl = day["Close"].astype(float)
            ma5 = cl.rolling(5).mean()
            slope = ma5.diff()
            exit_r3 = None
            for k in range(6, len(day)):                       # ≥09:30
                if (np.isfinite(ma5.iloc[k]) and cl.iloc[k] < r.day_open
                        and cl.iloc[k] < ma5.iloc[k] and slope.iloc[k] < 0):
                    exit_r3 = float(cl.iloc[k])
                    break
            t10 = day[day.index.time >= pd.Timestamp("10:00").time()]
            exit_r1 = float(t10["Close"].iloc[0]) if len(t10) and float(t10["Close"].iloc[0]) < r.day_open else None
            res.append(dict(sid=sid, name=r["name"], d=r.d.date(), gap=r.gap, peak_day=r.peak_day,
                            day_open=r.day_open, day_close=r.day_close, day_high=r.day_high,
                            r3=exit_r3, r1=exit_r1))
    return pd.DataFrame(res)


def report(ev, col, lab):
    trig = ev[ev[col].notna()]
    hold = ev[ev[col].isna()]
    print(f"  ── {lab} ──")
    print(f"    觸發 {len(trig)}/{len(ev)} 天（{100*len(trig)/len(ev):.0f}%）")
    if len(trig):
        edge = (trig[col] - trig.day_close) / trig.day_close * 100
        bad = (edge < 0).mean() * 100
        print(f"    觸發日：出場價 vs 收盤  平均 {edge.mean():+5.2f}%  中位 {edge.median():+5.2f}%"
              f"（誤殺-出場後收更高：{bad:.0f}%）")
        pk = trig[trig.peak_day]
        if len(pk):
            e2 = (pk[col] - pk.day_close) / pk.day_close * 100
            print(f"    其中『峰值日』{len(pk)} 天：平均多保住 {e2.mean():+5.2f}%")
    if len(hold):
        oc = (hold.day_close - hold.day_open) / hold.day_open * 100
        print(f"    未觸發日 {len(hold)} 天：開盤→收盤 平均 {oc.mean():+5.2f}%（沒訊號＝讓它跑，正值代表對）")


def main():
    print("蒐集 ride 中的開高日（日K）…")
    gd = collect_gap_days()
    print(f"開高≥3% 持倉日 {len(gd)} 天／{gd.sid.nunique()} 檔（{START_5M.date()} 之後）")
    print("下載 5分K 並評估規則…")
    ev = eval_rules(gd)
    print(f"5分K可得 {len(ev)} 天\n")
    print("=" * 80)
    report(ev, "r3", "R3 你的規則：跌破開盤 且 跌破5MA 且 5MA下彎（09:30後首次）")
    report(ev, "r1", "R1 簡化對照：10:00 仍低於開盤 → 出")
    print("=" * 80)
    n_pk = ev.peak_day.sum()
    print(f"  參考：這 {len(ev)} 個開高日中 {n_pk} 天（{100*n_pk/len(ev):.0f}%）正是該段 ride 的峰值日")


if __name__ == "__main__":
    main()
