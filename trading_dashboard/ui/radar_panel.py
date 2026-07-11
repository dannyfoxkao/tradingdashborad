"""選股雷達：整理「強多 / 底部翻揚 / 震盪偏多」清單（平行抓取版）。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..config import BULL_LABELS, parse_stock_id
from ..data_sources.disposition import is_in_disposition
from ..data_sources.prefetch import prefetch_many
from ..indicators import classify_trend, compute_alpha
from ..signals import evaluate_signals


def render(group_choice, selected_stocks, stocks_pool, start_str, end_str, benchmark_df, disposition_map) -> None:
    with st.expander("📈 強多／底部翻揚／震盪偏多 選股雷達", expanded=False):
        c1, c2 = st.columns([3, 1])
        with c1:
            scan_scope = st.radio("掃描範圍", ["本族群", "全部族群"], horizontal=True, key="scan_scope")
        with c2:
            run_scan = st.button("🛰️ 開始掃描")

        if not run_scan:
            st.caption("選擇範圍後按「開始掃描」，將篩出趨勢為 🟢強多 / 🌱底部翻揚 / 🟡震盪偏多 的個股並依強度排序。")
            return

        if scan_scope == "本族群":
            scope_items = [(group_choice, t, n) for t, n in selected_stocks.items()]
        else:
            scope_items = [(g, t, n) for g, d in stocks_pool.items() for t, n in d.items()]

        # 先平行預抓（同代號去重，只抓一次）
        prog = st.progress(0.0, text="抓取中...")
        data = prefetch_many([t for _, t, _ in scope_items], start_str, end_str, progress=prog)
        prog.empty()

        rows = _scan_rows(scope_items, data, benchmark_df, disposition_map)
        _show_results(rows)


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


def _show_results(rows: list[dict]) -> None:
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
    st.dataframe(res, use_container_width=True, hide_index=True)
