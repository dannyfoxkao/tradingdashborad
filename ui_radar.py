import pandas as pd
import streamlit as st

from data import fetch_finmind_data
from analysis import (
    classify_trend, compute_alpha, evaluate_signals, is_in_disposition,
    classify_long_term, compute_momentum, compute_support_resistance,
)


# =====================================================================
# 📈 選股雷達：整理「強多 / 震盪偏多」清單
# =====================================================================
def render_stock_radar(group_choice, selected_stocks, stocks_pool,
                       start_str, end_str, benchmark_df, disposition_map):
    with st.expander("📈 強多／底部翻揚／震盪偏多 選股雷達", expanded=False):
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

            rows = []
            prog = st.progress(0.0, text="掃描中...")
            total = max(len(scope_items), 1)
            for k, (g, tk, nm) in enumerate(scope_items):
                cid = tk.split('.')[0].strip()
                d = fetch_finmind_data(cid, start_str, end_str)
                ti = classify_trend(d)
                if ti and ti["label"] in ("強多", "底部翻揚", "震盪(偏多)"):
                    latest = d.iloc[-1]
                    prev = d.iloc[-2]
                    chg = ((latest['Close'] - prev['Close']) / prev['Close'] * 100) if prev['Close'] else 0.0
                    av, _ = compute_alpha(d, benchmark_df)
                    in_disp = is_in_disposition(cid, d.index[-1], disposition_map)
                    sg = evaluate_signals(d, in_disp)
                    n_buy = len(sg["buys"]) if sg else 0
                    n_sell = len(sg["sells"]) if sg else 0
                    # 長線濾網／動能／R:R 欄位暫不顯示（classify_long_term / compute_momentum /
                    # compute_support_resistance 保留於 analysis.py，日後要顯示再接回）。
                    rows.append({
                        "族群": g,
                        "代號": cid,
                        "名稱": nm,
                        "趨勢": f'{ti["icon"]} {ti["label"]}',
                        "收盤": round(float(latest['Close']), 2),
                        "今日%": round(chg, 2),
                        "📥買訊": n_buy,
                        "📤賣警": n_sell,
                        "α%": round(av, 1) if av is not None else None,
                        "MA20斜率%": round(ti["slope"], 2),
                        "處置": "⛔" if in_disp else "",
                        "_rank": ti["rank"],
                    })
                prog.progress((k + 1) / total, text=f"掃描中... {k+1}/{total}")
            prog.empty()

            if rows:
                res = (pd.DataFrame(rows)
                       .sort_values(["_rank", "α%"], ascending=[True, False], na_position="last")
                       .drop(columns="_rank")
                       .reset_index(drop=True))
                n_strong = sum(1 for r in rows if "強多" in r["趨勢"])
                n_bottom = sum(1 for r in rows if "底部翻揚" in r["趨勢"])
                n_mid = len(rows) - n_strong - n_bottom
                st.success(f"掃描完成：共 {len(res)} 檔（🟢 強多 {n_strong}／🌱 底部翻揚 {n_bottom}／🟡 震盪偏多 {n_mid}）｜由強至弱排序")
                st.dataframe(res, width='stretch', hide_index=True)
            else:
                st.info("本次掃描沒有符合『強多／震盪偏多』的標的。")
        else:
            st.caption("選擇範圍後按「開始掃描」，將篩出趨勢為 🟢強多 / 🌱底部翻揚 / 🟡震盪偏多 的個股並依強度排序。")
