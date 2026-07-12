"""
紅K順風車 策略回測（離線工具）
=================================
對 stock_config.json 的股池跑三份分析：
  報告1 · 整體績效：red_k_tailwind_signals 狀態機的每筆進場→出場交易（純第一根紅K 進場）
  報告2 · 族群同步：每個進攻訊號依「同族群 ±N 日內一起點火的檔數」分組比較
  報告3 · 大盤氣象台閘門：把交易依「進場當日大盤安全/危險區」拆解，看 regime 濾網有沒有加分

特性
  • 還原股價 + 處置期剔除：沿用 data.fetch_finmind_data（已內建）
  • 期間感知磁碟快取續傳：每檔存 backtest_cache/{start}_{end}/{sid}.pkl；FinMind 限流中斷後
    直接再跑即補完，不同期間互不污染（見記憶 finmind-ratelimit-backtest）
  • 等權、以「訊號當日收盤」進出，未計費用/滑價——是訊號回測，非部位管理

用法
  python backtest_tailwind.py                                   # 預設期間、排除大盤
  python backtest_tailwind.py --start 2021-11-01 --end 2023-01-31   # 空頭段重測
  python backtest_tailwind.py --exclude 大盤,金控
再跑一次即可把上次限流沒抓到的補齊。
"""
import os
import sys
import json
import time
import argparse
from datetime import timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data          # noqa: E402  (fetch_finmind_data：還原股價+處置剔除)
import analysis      # noqa: E402  (red_k_tailwind_signals)

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "stock_config.json")
CACHE_ROOT = os.path.join(HERE, "backtest_cache")
OUT_TRADES = os.path.join(HERE, "backtest_trades.csv")
OUT_IGNITE = os.path.join(HERE, "backtest_ignitions.csv")
OUT_JSON = os.path.join(HERE, "backtest_summary.json")

CHG_THR = 6.5
VOL_MULT = 1.5
LIMIT_UP = 9.5          # 鎖漲停代理門檻(%)：涵蓋一字/跳空鎖死，量不論
ATR_TRAIL = 2.0
MAX_HOLD = 120
INDEX_IDS = {"TAIEX", "TPEx"}


# ---------------------------------------------------------------- 股池
def build_universe(exclude_groups):
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    uniq, groups, market = {}, {}, {}
    for g, d in cfg.items():
        if g in exclude_groups:
            continue
        for t, name in d.items():
            sid = t.split(".")[0].strip()
            if sid in INDEX_IDS:
                continue
            uniq.setdefault(sid, name)
            market[sid] = "上櫃" if t.strip().upper().endswith(".TWO") else "上市"
            groups.setdefault(g, set()).add(sid)
    return uniq, groups, market


# ------------------------------------------------------------ 快取續傳
def ensure_cache(uniq, start, end, cache_dir, sleep, refresh):
    os.makedirs(cache_dir, exist_ok=True)
    newly, miss = 0, []
    for sid in uniq:
        p = os.path.join(cache_dir, f"{sid}.pkl")
        if os.path.exists(p) and not refresh:
            continue
        df = data.fetch_finmind_data(sid, start, end)
        time.sleep(sleep)
        if df is not None and len(df) >= 40:
            df.to_pickle(p)
            newly += 1
        else:
            miss.append(sid)
    cached = [s for s in uniq if os.path.exists(os.path.join(cache_dir, f"{s}.pkl"))]
    return cached, newly, miss


# ------------------------------------------------------------ 交易產生
def strategy_trades(df, sid, name):
    """報告1：狀態機的完整進場→出場交易（純第一根紅K，reentry_on_new_high=False）。"""
    res = analysis.red_k_tailwind_signals(df)
    if not res:
        return []
    out = []
    b, s = res["buys"], res["sells"]
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
        out.append(dict(stock=sid, name=name, entry=ed.strftime("%Y-%m-%d"),
                        exit=xd.strftime("%Y-%m-%d"), days=int((xd - ed).days),
                        ret=round(r, 2), entry_reason=b[i]["reason"], exit_reason=s[i]["reason"]))
    return out


def ignition_events(df, sid, name):
    """報告2：每個「第一根紅K」進攻訊號，獨立以 2×ATR 移動停利事件回測。"""
    o = df["Open"].to_numpy(float)
    h = df["High"].to_numpy(float)
    c = df["Close"].to_numpy(float)
    v = df["Volume"].to_numpy(float)
    volma = (df["Vol_MA20"] if "Vol_MA20" in df.columns else df["Volume"].rolling(20).mean()).to_numpy(float)
    atr = (df["ATR14_clean"] if "ATR14_clean" in df.columns else df["ATR14"]).to_numpy(float)
    disp = df["DispDay"].to_numpy(bool) if "DispDay" in df.columns else np.zeros(len(df), bool)
    with np.errstate(divide="ignore", invalid="ignore"):
        ret1 = np.concatenate([[np.nan], (c[1:] / c[:-1] - 1) * 100])
    idx, n, out = df.index, len(df), []

    def _fire(i):
        if not (np.isfinite(ret1[i]) and c[i] > 0):
            return False
        locked_limit = (ret1[i] >= LIMIT_UP) and (c[i] >= h[i] - 1e-6)      # 鎖漲停：量不論、不要求收紅
        vol_breakout = (ret1[i] >= CHG_THR) and (volma[i] > 0) and (v[i] >= VOL_MULT * volma[i]) and (c[i] > o[i])
        return locked_limit or vol_breakout

    for i in range(1, n):
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
        xp = c[exit_i]
        if entry <= 0 or xp <= 0:
            continue
        r = (xp / entry - 1) * 100
        if not np.isfinite(r) or r <= -95:
            continue
        out.append(dict(stock=sid, name=name, date=idx[i].strftime("%Y-%m-%d"),
                        days=int((idx[exit_i] - idx[i]).days), ret=round(r, 2)))
    return out


# ------------------------------------------------------ 大盤氣象台閘門
def market_weather(start, end):
    """
    回傳 {'上市': DataFrame(index=date, cols=[safe, strong]), '上櫃': ...}。
    safe = 收盤 ≥ 20MA（安全區）；strong = safe 且 MACD 柱狀上彎（強風）。
    多抓 90 天暖身讓月線/MACD 於期初就成形。
    """
    buf = (pd.to_datetime(start) - timedelta(days=90)).strftime("%Y-%m-%d")
    out = {}
    for market, sid in (("上市", "TAIEX"), ("上櫃", "TPEx")):
        idf = data.fetch_index_close(sid, buf, end)
        if idf is None or len(idf) < 30:
            out[market] = None
            continue
        c = idf["Close"].astype(float)
        ma20 = c.rolling(20).mean()
        ef = c.ewm(span=12, adjust=False).mean()
        es = c.ewm(span=26, adjust=False).mean()
        hist = (ef - es) - (ef - es).ewm(span=9, adjust=False).mean()
        safe = c >= ma20
        out[market] = pd.DataFrame({"safe": safe, "strong": safe & (hist > hist.shift(1))}).dropna()
    return out


def regime_split(tr, sid_market, weather):
    """報告3：把交易依進場當日大盤 regime 拆解。"""
    recs = []
    for _, t in tr.iterrows():
        wm = weather.get(sid_market.get(t.stock))
        if wm is None or len(wm) == 0:
            continue
        d = pd.Timestamp(t.entry)
        sub = wm.loc[:d]
        if len(sub) == 0:
            continue
        row = sub.iloc[-1]                     # asof：進場日(或之前最近交易日)的 regime
        recs.append((bool(row["safe"]), bool(row["strong"]), t.ret))
    df = pd.DataFrame(recs, columns=["safe", "strong", "ret"])

    def agg(sub):
        if len(sub) == 0:
            return None
        w = sub[sub.ret > 0]
        return dict(n=len(sub), win=round((sub.ret > 0).mean() * 100, 1),
                    avg=round(sub.ret.mean(), 2), med=round(sub.ret.median(), 2),
                    exp=round(sub.ret.mean(), 2))
    return {
        "全部": agg(df),
        "安全區(收盤≥大盤月線)": agg(df[df.safe]),
        "危險區(<大盤月線)": agg(df[~df.safe]),
        "強風(安全+MACD↑)": agg(df[df.strong]),
    }


# -------------------------------------------------------------- 統計
def _grp(frame, col):
    o = {}
    for k, g in frame.groupby(col, observed=True):
        o[str(k)] = dict(n=len(g), win=round((g.ret > 0).mean() * 100, 1), avg=round(g.ret.mean(), 2))
    return o


def summarize_overall(tr):
    w, l = tr[tr.ret > 0], tr[tr.ret <= 0]
    tr = tr.copy()
    tr["hb"] = pd.cut(tr.days, [0, 10, 20, 40, 80, 400])
    return dict(
        stocks=int(tr.stock.nunique()), total=len(tr), wins=len(w), losses=len(l),
        win_rate=round(len(w) / len(tr) * 100, 1),
        avg_win=round(w.ret.mean(), 2), avg_loss=round(l.ret.mean(), 2),
        payoff=round(w.ret.mean() / abs(l.ret.mean()), 2) if len(l) else None,
        expectancy=round(tr.ret.mean(), 2), median=round(tr.ret.median(), 2),
        profit_factor=round(w.ret.sum() / abs(l.ret.sum()), 2) if l.ret.sum() != 0 else None,
        max_win=round(tr.ret.max(), 1), max_loss=round(tr.ret.min(), 1),
        avg_days=round(tr.days.mean(), 1),
        by_hold=_grp(tr, "hb"), by_exit=_grp(tr, "exit_reason"),
    )


def synchrony(ig, groups, windows=(0, 3)):
    from collections import defaultdict
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

    def cofire(stock, d, win):
        best = 1
        for g in s2g.get(stock, []):
            got = set()
            for dd, ss in gday[g].items():
                if abs((dd - d).days) <= win:
                    got |= ss
            best = max(best, len(got))
        return best

    res = {"total": len(ig)}
    for win in windows:
        ig["co"] = [cofire(r.stock, r.d, win) for _, r in ig.iterrows()]
        ig["bk"] = pd.cut(ig.co, [0, 1, 2, 1e9], labels=["孤軍(1)", "小同步(2)", "族群齊發(>=3)"])
        res[f"w{win}"] = {
            str(k): dict(n=len(g), win=round((g.ret > 0).mean() * 100, 1),
                         avg=round(g.ret.mean(), 2), med=round(g.ret.median(), 2))
            for k, g in ig.groupby("bk", observed=True)}
    return res


# -------------------------------------------------------------- 輸出
def _line(w=66):
    print("-" * w)


def print_report(o, sync, regime, period, coverage, missing):
    print()
    _line()
    print(f"  紅K順風車 回測  期間 {period}  覆蓋 {coverage}")
    if missing:
        print(f"  ! 尚有 {len(missing)} 檔未抓到（FinMind 限流）→ 再跑一次即補齊")
    _line()
    print("  報告1 · 整體績效")
    print(f"    交易 {o['total']} 筆／{o['stocks']} 檔  勝率 {o['win_rate']}%（{o['wins']}勝 {o['losses']}敗）")
    print(f"    期望值 {o['expectancy']:+}%／筆  中位 {o['median']:+}%  賺賠比 {o['payoff']}:1  獲利因子 {o['profit_factor']}")
    print(f"    均賺 {o['avg_win']:+}%／均賠 {o['avg_loss']:+}%  最大 {o['max_win']:+}% / {o['max_loss']:+}%  均持 {o['avg_days']} 天")
    for k, g in o["by_hold"].items():
        print(f"      持有 {k:>9}  n={g['n']:>4}  win {g['win']:>5}%  avg {g['avg']:+.1f}%")
    _line()
    print("  報告3 · 大盤氣象台進場閘門（依進場當日大盤 regime）")
    for k, g in regime.items():
        if g is None:
            print(f"    {k:<22}  無資料")
            continue
        print(f"    {k:<22}  n={g['n']:>4}  win {g['win']:>5}%  期望 {g['exp']:+6.2f}%  中位 {g['med']:+.2f}%")
    _line()
    print("  報告2 · 族群同步進攻（±3 日）")
    for k, g in sync.get("w3", {}).items():
        print(f"    {k:<12}  n={g['n']:>4}  win {g['win']:>5}%  avg {g['avg']:+6.2f}%  中位 {g['med']:+.2f}%")
    _line()
    print(f"  明細：{os.path.basename(OUT_TRADES)} / {os.path.basename(OUT_IGNITE)} / {os.path.basename(OUT_JSON)}")
    _line()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="紅K順風車 策略回測（磁碟快取續傳）")
    ap.add_argument("--start", default="2025-06-01")
    ap.add_argument("--end", default="2026-07-09")
    ap.add_argument("--exclude", default="大盤", help="排除的族群，逗號分隔")
    ap.add_argument("--sleep", type=float, default=0.12)
    ap.add_argument("--refresh", action="store_true", help="忽略快取重抓")
    args = ap.parse_args()
    exclude = {x.strip() for x in args.exclude.split(",") if x.strip()}
    cache_dir = os.path.join(CACHE_ROOT, f"{args.start}_{args.end}")

    uniq, groups, market = build_universe(exclude)
    print(f"股池 {len(uniq)} 檔（排除：{'、'.join(sorted(exclude)) or '無'}）  期間 {args.start}~{args.end}  快取續傳中…")
    cached, newly, miss = ensure_cache(uniq, args.start, args.end, cache_dir, args.sleep, args.refresh)
    print(f"本次新抓 {newly} 檔，快取覆蓋 {len(cached)}/{len(uniq)}")
    if not cached:
        print("沒有可用資料（可能整批限流）——稍後再跑一次。")
        return

    overall, ignites = [], []
    for sid in cached:
        df = pd.read_pickle(os.path.join(cache_dir, f"{sid}.pkl"))
        overall += strategy_trades(df, sid, uniq[sid])
        ignites += ignition_events(df, sid, uniq[sid])
    tr = pd.DataFrame(overall)
    ig = pd.DataFrame(ignites)
    tr.to_csv(OUT_TRADES, index=False, encoding="utf-8")
    ig.to_csv(OUT_IGNITE, index=False, encoding="utf-8")

    o = summarize_overall(tr)
    sync = synchrony(ig, groups)
    weather = market_weather(args.start, args.end)
    regime = regime_split(tr, market, weather)
    json.dump({"period": f"{args.start} ~ {args.end}", "coverage": f"{len(cached)}/{len(uniq)}",
               "overall": o, "regime": regime, "synchrony": sync},
              open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print_report(o, sync, regime, f"{args.start} ~ {args.end}", f"{len(cached)}/{len(uniq)}", miss)


if __name__ == "__main__":
    main()
