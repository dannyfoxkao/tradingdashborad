"""掃描『進場加 5日/10日 多頭排列濾網』對紅K順風車的影響。

重用 backtest_cache 的 pkl，不重抓 FinMind。對每組算報告1狀態機交易的整體績效。
濾網變體（皆在進場當日 i 評估）：
  基準       ：無濾網（現行策略）
  MA5>MA10   ：五日線在十日線上方（多頭排列）
  C>MA5>MA10 ：收盤也要站上五日線
  排列+上彎   ：MA5>MA10 且 MA5 較 3 日前上彎
用法：python tools/sweep_mabull.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools._sweep_common import run_sweep
from trading_dashboard.backtest import trade_returns

CONFIGS = [
    ("基準(無濾網)", "none"),
    ("MA5>MA10", "bull"),
    ("C>MA5>MA10", "c_bull"),
    ("排列+MA5上彎", "bull_up"),
]


def make_filter(df: pd.DataFrame, mode: str):
    if mode == "none":
        return None
    close = df["Close"].to_numpy(float)
    ma5 = df["MA5"].to_numpy(float) if "MA5" in df.columns else pd.Series(close).rolling(5).mean().to_numpy()
    ma10 = df["MA10"].to_numpy(float) if "MA10" in df.columns else pd.Series(close).rolling(10).mean().to_numpy()

    fin = np.isfinite
    if mode == "bull":  # MA5 > MA10
        return lambda i: bool(fin(ma5[i]) and fin(ma10[i]) and ma5[i] > ma10[i])
    if mode == "c_bull":  # C > MA5 > MA10
        return lambda i: bool(fin(ma5[i]) and fin(ma10[i]) and close[i] > ma5[i] > ma10[i])
    if mode == "bull_up":  # MA5 > MA10 且 MA5 上彎(比 3 日前高)
        return lambda i: bool(
            i >= 3 and fin(ma5[i]) and fin(ma10[i]) and fin(ma5[i - 3]) and ma5[i] > ma10[i] and ma5[i] > ma5[i - 3]
        )
    raise ValueError(mode)


def _rets_for(df, config):
    _label, mode = config
    return trade_returns(df, entry_filter=make_filter(df, mode))


if __name__ == "__main__":
    run_sweep(CONFIGS, _rets_for, label_width=16)
