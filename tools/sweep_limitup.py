"""掃描『鎖漲停點火』兩個門檻：limit_up_thr(%) × 收盤=最高(on/off)。

重用 backtest_cache 的 pkl，不重抓 FinMind。對每組算報告1狀態機交易的整體績效。
用法：python tools/sweep_limitup.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools._sweep_common import run_sweep
from trading_dashboard.backtest import trade_returns

# (標籤, limit_up_thr, require_close_high)；thr=100 等於關閉漲停路徑=純出量突破基準
CONFIGS = [
    ("純出量(關漲停)", 100.0, True),
    ("9.8% 收=高", 9.8, True),
    ("9.5% 收=高(現行)", 9.5, True),
    ("9.0% 收=高", 9.0, True),
    ("9.5% 不管收盤位置", 9.5, False),
    ("9.0% 不管收盤位置", 9.0, False),
]


def _rets_for(df, config):
    _label, thr, rch = config
    return trade_returns(df, limit_up_thr=thr, require_close_high=rch)


if __name__ == "__main__":
    run_sweep(CONFIGS, _rets_for, label_width=20)
