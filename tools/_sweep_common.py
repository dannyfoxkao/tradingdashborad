"""兩支門檻掃描 CLI 的共用骨架：讀期間快取 → 逐組跑 → 印固定寬度表。"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trading_dashboard import backtest
from trading_dashboard.config import BACKTEST_CACHE_DIR

PERIODS = [
    ("多頭", "2025-06-01", "2026-07-09"),
    ("空頭", "2021-12-01", "2023-03-31"),
]


def run_sweep(
    configs: Sequence[tuple],
    rets_for: Callable[[pd.DataFrame, tuple], list[float]],
    label_width: int = 20,
) -> None:
    """對每個 PERIOD × config 印整體績效表（重用 backtest_cache，不重抓 FinMind）。"""
    with contextlib.suppress(Exception):  # Windows CJK console
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    uniq, _groups, _market = backtest.build_universe({"大盤"})
    for pname, start, end in PERIODS:
        cache_dir = BACKTEST_CACHE_DIR / f"{start}_{end}"
        if not cache_dir.is_dir():
            print(f"[{pname}] 無快取 {cache_dir}，跳過（先跑 tools/backtest_tailwind.py 建快取）")
            continue
        frames = list(backtest.load_cached_frames(cache_dir, list(uniq)).values())
        print("\n" + "=" * 78)
        print(f"  {pname}  {start} ~ {end}   快取 {len(frames)} 檔")
        print("=" * 78)
        print(f"  {'設定':<{label_width}}{'筆數':>6}{'勝率':>8}{'期望值':>9}{'中位':>8}{'獲利因子':>9}")
        base_n = None
        for config in configs:
            label = config[0]
            rets: list[float] = []
            for df in frames:
                rets += rets_for(df, config)
            stats = backtest.summarize_returns(rets)
            if base_n is None:
                base_n = stats["n"]
            pf = "inf" if stats["pf"] == float("inf") else f"{stats['pf']:.2f}"
            print(
                f"  {label:<{label_width}}{stats['n']:>6}{stats['win']:>7.1f}%{stats['exp']:>+8.2f}%"
                f"{stats['med']:>+7.1f}%{pf:>9}   ({stats['n'] - base_n:+d} 筆)"
            )
