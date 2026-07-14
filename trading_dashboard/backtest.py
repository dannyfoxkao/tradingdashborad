"""紅K順風車回測引擎（純函式；CLI 殼在 tools/backtest_tailwind.py）。

三份報告的計算核心：
  報告1 · 整體績效：狀態機每筆進場→出場交易（strategy_trades / summarize_overall）
  報告2 · 族群同步：每個點火訊號獨立以 2×ATR 移動停利回測（ignition_events / synchrony）
  報告3 · 大盤氣象台閘門：交易依進場當日大盤 regime 拆解（market_weather / regime_split）
等權、以「訊號當日收盤」進出、未計費用/滑價——是訊號回測，非部位管理。
點火判定走 strategy.is_ignition（唯一事實來源）。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (
    BACKTEST_INDEX_WARMUP_DAYS,
    BACKTEST_MAX_HOLD,
    BACKTEST_RET_FLOOR,
    CONFIG_PATH,
    KNOWN_INDEX_IDS,
    SYNC_WINDOWS,
    TW_ATR_TRAIL_MULT,
    load_stock_config,
    parse_stock_id,
)
from .strategy import is_ignition, prepare_series, red_k_tailwind_signals


def build_universe(
    exclude_groups: set[str], config_path: Path | str = CONFIG_PATH
) -> tuple[dict[str, str], dict[str, set[str]], dict[str, str]]:
    """回傳 (uniq: sid→名稱, groups: 族群→sid集合, market: sid→上市/上櫃)；排除指數與指定族群。"""
    cfg = load_stock_config(config_path)
    uniq: dict[str, str] = {}
    groups: dict[str, set[str]] = {}
    market: dict[str, str] = {}
    for group, members in cfg.items():
        if group in exclude_groups:
            continue
        for ticker, name in members.items():
            sid = parse_stock_id(ticker)
            if sid in KNOWN_INDEX_IDS:
                continue
            uniq.setdefault(sid, name)
            market[sid] = "上櫃" if ticker.strip().upper().endswith(".TWO") else "上市"
            groups.setdefault(group, set()).add(sid)
    return uniq, groups, market


def trades_from_signals(
    df: pd.DataFrame, result: dict | None, sid: str, name: str, *, ret_floor: float = BACKTEST_RET_FLOOR
) -> list[dict]:
    """buys/sells 依序配對成交易；日期不在 index、價格<=0、報酬<=floor 皆剔除。"""
    if not result:
        return []
    out: list[dict] = []
    buys, sells = result["buys"], result["sells"]
    for i in range(min(len(buys), len(sells))):
        entry_date, exit_date = buys[i]["date"], sells[i]["date"]
        if entry_date not in df.index or exit_date not in df.index:
            continue
        entry_px = float(df.loc[entry_date, "Close"])
        exit_px = float(df.loc[exit_date, "Close"])
        if entry_px <= 0 or exit_px <= 0:
            continue
        ret = (exit_px / entry_px - 1) * 100
        if not np.isfinite(ret) or ret <= ret_floor:
            continue
        out.append(
            {
                "stock": sid,
                "name": name,
                "entry": entry_date.strftime("%Y-%m-%d"),
                "exit": exit_date.strftime("%Y-%m-%d"),
                "days": int((exit_date - entry_date).days),
                "ret": round(ret, 2),
                "entry_reason": buys[i]["reason"],
                "exit_reason": sells[i]["reason"],
            }
        )
    return out


def strategy_trades(df: pd.DataFrame, sid: str, name: str, **strategy_kwargs) -> list[dict]:
    """報告1：狀態機的完整進場→出場交易（預設純第一根紅K、reentry 關閉）。"""
    return trades_from_signals(df, red_k_tailwind_signals(df, **strategy_kwargs), sid, name)


def trade_returns(df: pd.DataFrame, **strategy_kwargs) -> list[float]:
    """門檻掃描共用：只取每筆交易報酬 %（供 tools/sweep_*）。"""
    return [t["ret"] for t in strategy_trades(df, "", "", **strategy_kwargs)]


def summarize_returns(rets: list[float]) -> dict:
    """n/win/exp/med/pf；空清單回 n=0＋NaN（修平面 sweep_limitup 的除零缺陷）。"""
    if len(rets) == 0:
        return {"n": 0, "win": float("nan"), "exp": float("nan"), "med": float("nan"), "pf": float("nan")}
    arr = np.array(rets, dtype=float)
    wins, losses = arr[arr > 0], arr[arr <= 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {
        "n": len(arr),
        "win": 100 * len(wins) / len(arr),
        "exp": float(arr.mean()),
        "med": float(np.median(arr)),
        "pf": float(pf),
    }


def ignition_events(
    df: pd.DataFrame,
    sid: str,
    name: str,
    *,
    max_hold: int = BACKTEST_MAX_HOLD,
    atr_trail_mult: float = TW_ATR_TRAIL_MULT,
    ret_floor: float = BACKTEST_RET_FLOOR,
) -> list[dict]:
    """報告2：每個「第一根紅K」進攻訊號，獨立以 2×ATR 移動停利事件回測。"""
    s = prepare_series(df)
    n = len(df)
    out: list[dict] = []
    for i in range(1, n):
        if not (is_ignition(s, i) and not s.dispday[i] and not is_ignition(s, i - 1)):
            continue
        entry, peak, exit_i = s.close[i], s.close[i], None
        for j in range(i + 1, min(i + max_hold + 1, n)):
            if s.dispday[j]:
                continue
            peak = max(peak, s.close[j])
            trail = peak - atr_trail_mult * s.atr14[j] if np.isfinite(s.atr14[j]) else np.nan
            if np.isfinite(trail) and s.close[j] < trail:
                exit_i = j
                break
        if exit_i is None:
            exit_i = min(i + max_hold, n - 1)
        exit_px = s.close[exit_i]
        if entry <= 0 or exit_px <= 0:
            continue
        ret = (exit_px / entry - 1) * 100
        if not np.isfinite(ret) or ret <= ret_floor:
            continue
        out.append(
            {
                "stock": sid,
                "name": name,
                "date": s.index[i].strftime("%Y-%m-%d"),
                "days": int((s.index[exit_i] - s.index[i]).days),
                "ret": round(ret, 2),
            }
        )
    return out


def _grp(frame: pd.DataFrame, col: str) -> dict:
    out = {}
    for key, grp in frame.groupby(col, observed=True):
        out[str(key)] = {"n": len(grp), "win": round((grp.ret > 0).mean() * 100, 1), "avg": round(grp.ret.mean(), 2)}
    return out


def summarize_overall(trades: pd.DataFrame) -> dict:
    """報告1 統計：勝率/期望值/賺賠比/獲利因子＋持有期與出場理由分桶。"""
    if trades.empty:
        return {"total": 0}
    wins, losses = trades[trades.ret > 0], trades[trades.ret <= 0]
    trades = trades.copy()
    trades["hb"] = pd.cut(trades.days, [0, 10, 20, 40, 80, 400])
    return {
        "stocks": int(trades.stock.nunique()),
        "total": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "avg_win": round(wins.ret.mean(), 2) if len(wins) else None,
        "avg_loss": round(losses.ret.mean(), 2) if len(losses) else None,
        "payoff": round(wins.ret.mean() / abs(losses.ret.mean()), 2) if len(wins) and len(losses) else None,
        "expectancy": round(trades.ret.mean(), 2),
        "median": round(trades.ret.median(), 2),
        "profit_factor": round(wins.ret.sum() / abs(losses.ret.sum()), 2) if losses.ret.sum() != 0 else None,
        "max_win": round(trades.ret.max(), 1),
        "max_loss": round(trades.ret.min(), 1),
        "avg_days": round(trades.days.mean(), 1),
        "by_hold": _grp(trades, "hb"),
        "by_exit": _grp(trades, "exit_reason"),
    }


def synchrony(ig: pd.DataFrame, groups: dict[str, set[str]], windows: tuple[int, ...] = SYNC_WINDOWS) -> dict:
    """報告2 統計：每個點火依「同族群 ±N 日內一起點火的檔數」分桶比較。"""
    stock_to_groups: dict[str, list[str]] = defaultdict(list)
    for group, sids in groups.items():
        for sid in sids:
            stock_to_groups[sid].append(group)
    ig = ig.copy()
    ig["d"] = pd.to_datetime(ig["date"])
    group_day: dict[str, dict[pd.Timestamp, set[str]]] = defaultdict(lambda: defaultdict(set))
    for _, row in ig.iterrows():
        for group in stock_to_groups.get(row.stock, []):
            group_day[group][row.d].add(row.stock)

    def cofire(stock: str, day: pd.Timestamp, win: int) -> int:
        best = 1
        for group in stock_to_groups.get(stock, []):
            got: set[str] = set()
            for other_day, sids in group_day[group].items():
                if abs((other_day - day).days) <= win:
                    got |= sids
            best = max(best, len(got))
        return best

    res: dict = {"total": len(ig)}
    for win in windows:
        ig["co"] = [cofire(row.stock, row.d, win) for _, row in ig.iterrows()]
        ig["bk"] = pd.cut(ig.co, [0, 1, 2, 1e9], labels=["孤軍(1)", "小同步(2)", "族群齊發(>=3)"])
        res[f"w{win}"] = {
            str(key): {
                "n": len(grp),
                "win": round((grp.ret > 0).mean() * 100, 1),
                "avg": round(grp.ret.mean(), 2),
                "med": round(grp.ret.median(), 2),
            }
            for key, grp in ig.groupby("bk", observed=True)
        }
    return res


def market_weather(
    start: str, end: str, fetch_index: Callable[[str, str, str], pd.DataFrame | None]
) -> dict[str, pd.DataFrame | None]:
    """報告3 前置：{'上市'/'上櫃': DataFrame(index=date, cols=[safe, strong])}。

    safe = 收盤 ≥ 20MA；strong = safe 且 MACD 柱狀上彎。fetch_index 以參數注入
    （CLI 傳 finmind.fetch_index_close），多抓暖身天數讓月線/MACD 期初成形。
    """
    buf = (pd.to_datetime(start) - pd.tseries.offsets.Day(BACKTEST_INDEX_WARMUP_DAYS)).strftime("%Y-%m-%d")
    out: dict[str, pd.DataFrame | None] = {}
    for market, sid in (("上市", "TAIEX"), ("上櫃", "TPEx")):
        idf = fetch_index(sid, buf, end)
        if idf is None or len(idf) < 30:
            out[market] = None
            continue
        close = idf["Close"].astype(float)
        ma20 = close.rolling(20).mean()
        ema_fast = close.ewm(span=12, adjust=False).mean()
        ema_slow = close.ewm(span=26, adjust=False).mean()
        hist = (ema_fast - ema_slow) - (ema_fast - ema_slow).ewm(span=9, adjust=False).mean()
        safe = close >= ma20
        out[market] = pd.DataFrame({"safe": safe, "strong": safe & (hist > hist.shift(1))}).dropna()
    return out


def regime_split(trades: pd.DataFrame, sid_market: dict[str, str], weather: dict) -> dict:
    """報告3：把交易依進場當日（或之前最近交易日，asof）的大盤 regime 拆解。"""
    recs = []
    for _, trade in trades.iterrows():
        frame = weather.get(sid_market.get(trade.stock))
        if frame is None or len(frame) == 0:
            continue
        sub = frame.loc[: pd.Timestamp(trade.entry)]
        if len(sub) == 0:
            continue
        row = sub.iloc[-1]
        recs.append((bool(row["safe"]), bool(row["strong"]), trade.ret))
    df = pd.DataFrame(recs, columns=["safe", "strong", "ret"])

    def agg(sub: pd.DataFrame) -> dict | None:
        if len(sub) == 0:
            return None
        return {
            "n": len(sub),
            "win": round((sub.ret > 0).mean() * 100, 1),
            "avg": round(sub.ret.mean(), 2),
            "med": round(sub.ret.median(), 2),
            "exp": round(sub.ret.mean(), 2),
        }

    return {
        "全部": agg(df),
        "安全區(收盤≥大盤月線)": agg(df[df.safe]),
        "危險區(<大盤月線)": agg(df[~df.safe]),
        "強風(安全+MACD↑)": agg(df[df.strong]),
    }


def load_cached_frames(cache_dir: Path | str, sids: list[str]) -> dict[str, pd.DataFrame]:
    """讀取期間快取目錄下既有的 pickle；只回傳存在者。"""
    cache_dir = Path(cache_dir)
    out: dict[str, pd.DataFrame] = {}
    for sid in sids:
        path = cache_dir / f"{sid}.pkl"
        if path.exists():
            out[sid] = pd.read_pickle(path)
    return out
