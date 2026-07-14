"""紅K順風車 策略回測（離線 CLI；引擎在 trading_dashboard.backtest）。

對 stock_config.json 的股池跑三份分析：
  報告1 · 整體績效：狀態機每筆進場→出場交易（純第一根紅K 進場）
  報告2 · 族群同步：每個進攻訊號依「同族群 ±N 日內一起點火的檔數」分組比較
  報告3 · 大盤氣象台閘門：交易依「進場當日大盤安全/危險區」拆解

特性
  • 還原股價＋處置期剔除：沿用套件 fetch_finmind_data（已內建重型管線）
  • 期間感知磁碟快取續傳：每檔存 backtest_cache/{start}_{end}/{sid}.pkl；
    FinMind 限流中斷後直接再跑即補完，不同期間互不污染
  • 舊快取（平面版產出）欄位相容可續用；點火口徑如有差異用 --refresh 重建
  • 等權、以「訊號當日收盤」進出，未計費用/滑價——是訊號回測，非部位管理

用法
  python tools/backtest_tailwind.py
  python tools/backtest_tailwind.py --start 2021-11-01 --end 2023-01-31
  python tools/backtest_tailwind.py --exclude 大盤,金控 --refresh
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 允許 python tools/xxx.py 直跑

import pandas as pd

from trading_dashboard import backtest
from trading_dashboard.config import BACKTEST_CACHE_DIR, BACKTEST_MIN_ROWS, BASE_DIR
from trading_dashboard.data_sources.finmind import fetch_finmind_data, fetch_index_close

OUT_TRADES = BASE_DIR / "backtest_trades.csv"
OUT_IGNITE = BASE_DIR / "backtest_ignitions.csv"
OUT_JSON = BASE_DIR / "backtest_summary.json"


def ensure_cache(uniq, start, end, cache_dir: Path, sleep: float, refresh: bool):
    """快取續傳：逐檔補抓缺漏 pickle；回傳 (已快取 sid 清單, 本次新抓數, 未抓到清單)。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    newly, miss = 0, []
    for sid in uniq:
        path = cache_dir / f"{sid}.pkl"
        if path.exists() and not refresh:
            continue
        df = fetch_finmind_data(sid, start, end)
        time.sleep(sleep)
        if df is not None and len(df) >= BACKTEST_MIN_ROWS:
            df.to_pickle(path)
            newly += 1
        else:
            miss.append(sid)
    cached = [s for s in uniq if (cache_dir / f"{s}.pkl").exists()]
    return cached, newly, miss


def _line(width: int = 66) -> None:
    print("-" * width)


def print_report(overall, sync, regime, period, coverage, missing) -> None:
    print()
    _line()
    print(f"  紅K順風車 回測  期間 {period}  覆蓋 {coverage}")
    if missing:
        print(f"  ! 尚有 {len(missing)} 檔未抓到（FinMind 限流）→ 再跑一次即補齊")
    _line()
    print("  報告1 · 整體績效")
    print(f"    交易 {overall['total']} 筆／{overall['stocks']} 檔  勝率 {overall['win_rate']}%"
          f"（{overall['wins']}勝 {overall['losses']}敗）")
    print(f"    期望值 {overall['expectancy']:+}%／筆  中位 {overall['median']:+}%  "
          f"賺賠比 {overall['payoff']}:1  獲利因子 {overall['profit_factor']}")
    print(f"    均賺 {overall['avg_win']:+}%／均賠 {overall['avg_loss']:+}%  "
          f"最大 {overall['max_win']:+}% / {overall['max_loss']:+}%  均持 {overall['avg_days']} 天")
    for key, grp in overall["by_hold"].items():
        print(f"      持有 {key:>9}  n={grp['n']:>4}  win {grp['win']:>5}%  avg {grp['avg']:+.1f}%")
    _line()
    print("  報告3 · 大盤氣象台進場閘門（依進場當日大盤 regime）")
    for key, grp in regime.items():
        if grp is None:
            print(f"    {key:<22}  無資料")
            continue
        print(f"    {key:<22}  n={grp['n']:>4}  win {grp['win']:>5}%  期望 {grp['exp']:+6.2f}%  中位 {grp['med']:+.2f}%")
    _line()
    print("  報告2 · 族群同步進攻（±3 日）")
    for key, grp in sync.get("w3", {}).items():
        print(f"    {key:<12}  n={grp['n']:>4}  win {grp['win']:>5}%  avg {grp['avg']:+6.2f}%  中位 {grp['med']:+.2f}%")
    _line()
    print(f"  明細：{OUT_TRADES.name} / {OUT_IGNITE.name} / {OUT_JSON.name}")
    _line()


def main() -> None:
    with contextlib.suppress(Exception):  # Windows CJK console
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="紅K順風車 策略回測（磁碟快取續傳）")
    parser.add_argument("--start", default="2025-06-01")
    parser.add_argument("--end", default="2026-07-09")
    parser.add_argument("--exclude", default="大盤", help="排除的族群，逗號分隔")
    parser.add_argument("--sleep", type=float, default=0.12)
    parser.add_argument("--refresh", action="store_true", help="忽略快取重抓")
    args = parser.parse_args()
    exclude = {x.strip() for x in args.exclude.split(",") if x.strip()}
    cache_dir = BACKTEST_CACHE_DIR / f"{args.start}_{args.end}"

    uniq, groups, market = backtest.build_universe(exclude)
    print(f"股池 {len(uniq)} 檔（排除：{'、'.join(sorted(exclude)) or '無'}）  期間 {args.start}~{args.end}  快取續傳中…")
    cached, newly, miss = ensure_cache(uniq, args.start, args.end, cache_dir, args.sleep, args.refresh)
    print(f"本次新抓 {newly} 檔，快取覆蓋 {len(cached)}/{len(uniq)}")
    if not cached:
        print("沒有可用資料（可能整批限流）——稍後再跑一次。")
        return

    frames = backtest.load_cached_frames(cache_dir, cached)
    overall_rows, ignite_rows = [], []
    for sid, df in frames.items():
        overall_rows += backtest.strategy_trades(df, sid, uniq[sid])
        ignite_rows += backtest.ignition_events(df, sid, uniq[sid])
    trades = pd.DataFrame(overall_rows)
    ignites = pd.DataFrame(ignite_rows)
    trades.to_csv(OUT_TRADES, index=False, encoding="utf-8")
    ignites.to_csv(OUT_IGNITE, index=False, encoding="utf-8")

    overall = backtest.summarize_overall(trades)
    sync = backtest.synchrony(ignites, groups)
    weather = backtest.market_weather(args.start, args.end, fetch_index_close)
    regime = backtest.regime_split(trades, market, weather)
    OUT_JSON.write_text(
        json.dumps(
            {
                "period": f"{args.start} ~ {args.end}",
                "coverage": f"{len(cached)}/{len(uniq)}",
                "overall": overall,
                "regime": regime,
                "synchrony": sync,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print_report(overall, sync, regime, f"{args.start} ~ {args.end}", f"{len(cached)}/{len(uniq)}", miss)


if __name__ == "__main__":
    main()
