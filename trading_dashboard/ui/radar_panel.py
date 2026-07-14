"""選股雷達：整理「強多 / 底部翻揚 / 震盪偏多」清單（平行抓取版）。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..config import BULL_LABELS, FORWARD_RETURN_DAYS, SIGNALS_HISTORY_FILE, parse_stock_id
from ..data_sources.disposition import is_in_disposition
from ..data_sources.prefetch import prefetch_many
from ..history import append_signal_snapshot, forward_return, load_history
from ..indicators import classify_trend, compute_alpha
from ..persistence import to_csv_bytes
from ..signals import evaluate_signals


def render(group_choice, selected_stocks, stocks_pool, start_str, end_str, benchmark_df, disposition_map) -> None:
    with st.expander("📈 強多／底部翻揚／震盪偏多 選股雷達", expanded=False):
        tab_scan, tab_history = st.tabs(["🛰️ 掃描", "🕘 訊號歷史"])
        with tab_scan:
            _render_scan(group_choice, selected_stocks, stocks_pool, start_str, end_str, benchmark_df, disposition_map)
        with tab_history:
            _render_signal_history(start_str, end_str)


def _render_scan(group_choice, selected_stocks, stocks_pool, start_str, end_str, benchmark_df, disposition_map) -> None:
    c1, c2 = st.columns([3, 1])
    with c1:
        scan_scope = st.radio("掃描範圍", ["本族群", "全部族群"], horizontal=True, key="scan_scope")
    with c2:
        run_scan = st.button("🛰️ 開始掃描")

    if run_scan:
        if scan_scope == "本族群":
            scope_items = [(group_choice, t, n) for t, n in selected_stocks.items()]
        else:
            scope_items = [(g, t, n) for g, d in stocks_pool.items() for t, n in d.items()]

        # 先平行預抓（同代號去重，只抓一次）
        prog = st.progress(0.0, text="抓取中...")
        data = prefetch_many([t for _, t, _ in scope_items], start_str, end_str, progress=prog)
        prog.empty()

        # 結果進 session_state：download_button 等互動觸發 rerun 後結果不消失
        rows = _scan_rows(scope_items, data, benchmark_df, disposition_map)
        st.session_state["radar_rows"] = rows
        st.session_state["radar_scan_date"] = end_str
        _record_signals(rows, end_str)

    stored_rows = st.session_state.get("radar_rows")
    if stored_rows is None:
        st.caption("選擇範圍後按「開始掃描」，將篩出趨勢為 🟢強多 / 🌱底部翻揚 / 🟡震盪偏多 的個股並依強度排序。")
        return
    _show_results(stored_rows, st.session_state.get("radar_scan_date", ""))


def _record_signals(rows: list[dict], scan_date: str) -> None:
    """把本次掃描命中的訊號寫入歷史檔（供事後驗證雷達準確度）。"""
    if not rows:
        return
    sig_rows = [
        {"stock_id": r["代號"], "name": r["名稱"], "signal": r["趨勢"], "close": r["收盤"], "alpha": r["α%"]}
        for r in rows
    ]
    append_signal_snapshot(sig_rows, scan_date)


def _render_signal_history(start_str: str, end_str: str) -> None:
    hist = load_history(SIGNALS_HISTORY_FILE)
    if hist is None or hist.empty:
        st.info("尚無訊號歷史。掃描後符合條件的個股會自動記錄於此，累積後可回頭驗證雷達準確度。")
        return

    c1, c2 = st.columns([1, 3])
    with c1:
        n_days = st.selectbox("N 日後報酬", FORWARD_RETURN_DAYS, key="signal_fwd_days")
    with c2:
        calc = st.button("🧮 計算報酬", key="signal_calc_returns")

    if calc:
        hist = _with_forward_returns(hist, int(n_days), end_str)
    st.dataframe(hist.sort_values("date", ascending=False), width="stretch", hide_index=True)
    st.caption("⚠️ 「計算報酬」會對歷史中每檔個股抓取價格（FinMind 額度），已以快取＋去重降低用量。")


def _with_forward_returns(hist: pd.DataFrame, n_days: int, end_str: str) -> pd.DataFrame:
    start = str(hist["date"].min())
    prog = st.progress(0.0, text="抓取價格資料...")
    data = prefetch_many(hist["stock_id"].astype(str).unique().tolist(), start, end_str, progress=prog)
    prog.empty()

    hist = hist.copy()
    returns = []
    for sid, d in zip(hist["stock_id"].astype(str), hist["date"], strict=False):
        r = forward_return(data.get(sid), d, n_days)
        returns.append(round(r, 2) if r is not None else None)
    hist[f"{n_days}日後%"] = returns
    return hist


def _scan_rows(scope_items, data, benchmark_df, disposition_map) -> list[dict]:
    rows: list[dict] = []
    for g, tk, nm in scope_items:
        cid = parse_stock_id(tk)
        d = data.get(cid)
        ti = classify_trend(d)
        if not (ti and ti["label"] in BULL_LABELS):
            continue
        latest, prev = d.iloc[-1], d.iloc[-2]
        chg = ((latest["Close"] - prev["Close"]) / prev["Close"] * 100) if prev["Close"] else 0.0
        alpha_val, _ = compute_alpha(d, benchmark_df)
        in_disp = is_in_disposition(disposition_map, cid, d.index[-1])
        sig = evaluate_signals(d, in_disp)
        rows.append(
            {
                "族群": g,
                "代號": cid,
                "名稱": nm,
                "趨勢": f"{ti['icon']} {ti['label']}",
                "收盤": round(float(latest["Close"]), 2),
                "今日%": round(chg, 2),
                "📥買訊": len(sig["buys"]) if sig else 0,
                "📤賣警": len(sig["sells"]) if sig else 0,
                "α%": round(alpha_val, 1) if alpha_val is not None else None,
                "MA20斜率%": round(ti["slope"], 2),
                "處置": "⛔" if in_disp else "",
                "_rank": ti["rank"],
            }
        )
    return rows


def _show_results(rows: list[dict], scan_date: str) -> None:
    if not rows:
        st.info("本次掃描沒有符合『強多／底部翻揚／震盪偏多』的標的。")
        return
    res = (
        pd.DataFrame(rows)
        .sort_values(["_rank", "α%"], ascending=[True, False], na_position="last")
        .drop(columns="_rank")
        .reset_index(drop=True)
    )
    n_strong = sum(1 for r in rows if r["趨勢"].startswith("🟢"))
    n_bottom = sum(1 for r in rows if r["趨勢"].startswith("🌱"))
    n_mid = len(rows) - n_strong - n_bottom
    st.success(
        f"掃描完成：共 {len(res)} 檔（🟢 強多 {n_strong}／🌱 底部翻揚 {n_bottom}／🟡 震盪偏多 {n_mid}）｜由強至弱排序"
    )
    st.dataframe(res, width="stretch", hide_index=True)
    st.download_button(
        "⬇️ 匯出 CSV",
        data=to_csv_bytes(res),
        file_name=f"radar_{scan_date}.csv",
        mime="text/csv",
        key="radar_export",
    )
