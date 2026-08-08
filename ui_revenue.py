import numpy as np
import pandas as pd
import streamlit as st

from data import fetch_finmind_data
from revenue import fetch_month_revenue, yoy_metrics, pullback_state, SKIP_IDS
from ui_today import _load_shares, CAP_THR

REV_KEY = "rev_scan_result"


# =====================================================================
# 📈 營收動能雷達：月營收 YoY 持續創高 × 股價拉回
#   🎯 買拉回：YoY創高/連增 且 股價「淺回」(跌破5日線但仍站月線) — 基本面加速、
#      技術面剛好回檔的交集，即使用者要的進場區。
#   📊 強勢未回：動能有、但價未回檔（追高風險，列入觀察）
#   ⚠️ 價背離：營收創高但股價已破季線（基本面與價格背離，別接刀）
# =====================================================================
def _scan_revenue(stocks_pool, start_str, end_str):
    items, seen = [], set()
    for g, d in stocks_pool.items():
        for tk, nm in d.items():
            cid = tk.split(".")[0].strip()
            if cid in SKIP_IDS or cid.startswith("00"):      # 指數/ETF 無月營收
                continue
            items.append((g, cid, nm))
            seen.add(cid)
    shares = _load_shares()

    # ① 先掃營收（每檔一次 API，結果快取一天）
    rev_map = {}
    prog = st.progress(0.0, text="讀取月營收…")
    uniq_ids = list(dict.fromkeys(cid for _, cid, _ in items))
    for k, cid in enumerate(uniq_ids):
        prog.progress((k + 1) / len(uniq_ids), text=f"讀取月營收… {k + 1}/{len(uniq_ids)}")
        rev_map[cid] = yoy_metrics(fetch_month_revenue(cid))
    prog.empty()

    # ② 只對「有動能」的個股抓股價算拉回，省 API
    hot = {cid for cid, m in rev_map.items()
           if m and (m["is_high"] or m["streak"] >= 3) and m["yoy"] > 0}
    px_map = {}
    prog = st.progress(0.0, text="比對股價位階…")
    for k, cid in enumerate(sorted(hot)):
        prog.progress((k + 1) / max(len(hot), 1), text=f"比對股價位階… {k + 1}/{len(hot)}")
        df = fetch_finmind_data(cid, start_str, end_str)
        p = pullback_state(df)
        if p and cid in shares and df is not None and len(df):
            p["big"] = shares[cid] * float(df["Close"].iloc[-1]) >= CAP_THR
        px_map[cid] = p
    prog.empty()

    rows = []
    for g, cid, nm in items:
        m, p = rev_map.get(cid), px_map.get(cid)
        if not m or cid not in hot or not p:
            continue
        rows.append({
            "族群": g, "代號": cid, "名稱": nm,
            "營收月": m["month_label"], "YoY%": m["yoy"], "上月YoY%": m["yoy_prev"],
            "連增月": m["streak"], "創高": "🔺" if m["is_high"] else "",
            "營收新高": "💰" if m["rev_high"] else "",
            "收盤": p["close"], "股價位階": p["state"], "距20日高%": p["from_high"],
            "_big": bool(p.get("big", False)), "_pull": p["state"].startswith("🟢"),
            "_broken": p["state"].startswith("❌"),
        })
    return {"rows": rows, "scan_at": pd.Timestamp.now().strftime("%m/%d %H:%M"),
            "n_scanned": len(uniq_ids)}


def _render(payload):
    rows = payload["rows"]
    st.caption(f"掃描於 {payload['scan_at']}｜檢視 {payload['n_scanned']} 檔｜"
               "月營收於次月 10 日前後公布，故最新月份通常落後 1 個月。")
    if not rows:
        st.info("目前沒有『YoY 創高或連增 ≥3 個月』的標的。")
        return

    df = pd.DataFrame(rows)
    df["標記"] = np.select(
        [df["_pull"], df["_broken"]], ["🎯買拉回", "⚠️價背離"], default="📊強勢未回")
    n_target = (df["標記"] == "🎯買拉回").sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🎯 買拉回候選", f"{n_target} 檔", "營收加速×淺回月線上")
    c2.metric("📊 強勢未回", f"{(df['標記'] == '📊強勢未回').sum()} 檔")
    c3.metric("⚠️ 價背離(破季線)", f"{(df['標記'] == '⚠️價背離').sum()} 檔")
    c4.metric("動能股合計", f"{df['代號'].nunique()} 檔")

    if n_target:
        tgt = df[df["標記"] == "🎯買拉回"].sort_values("YoY%", ascending=False)
        st.success("🎯 **營收加速 × 股價拉回（跌破5日線但仍站月線）**：" + "、".join(
            f"{r['名稱']}({r['代號']}) YoY{r['YoY%']:+.0f}%" for _, r in tgt.head(12).iterrows()))

    df["大型股"] = np.where(df["_big"], "💎", "")
    df["_ord"] = df["標記"].map({"🎯買拉回": 0, "📊強勢未回": 1, "⚠️價背離": 2})
    df = df.sort_values(["_ord", "連增月", "YoY%"], ascending=[True, False, False])
    st.dataframe(df[["標記", "大型股", "族群", "代號", "名稱", "營收月", "YoY%", "上月YoY%",
                     "連增月", "創高", "營收新高", "收盤", "股價位階", "距20日高%"]],
                 width="stretch", hide_index=True)
    st.caption("**創高🔺**＝最新月 YoY 為近12個月最高｜**連增月**＝YoY 逐月墊高的連續月數（含最新月）｜"
               "**營收新高💰**＝營收金額本身為近12個月最高。"
               "股價位階：🔺強勢(未回)｜🟢淺回(跌破5日線、仍站月線)｜🟠深回(破月線、季線上)｜❌破季線。"
               "⚠️ 營收是落後指標且逐月公布，追高前留意是否已反映；破季線者屬基本面與價格背離，勿接刀。")


def render_revenue_radar(stocks_pool, start_str, end_str):
    with st.expander("📈 營收動能雷達（YoY 創高 × 買拉回）", expanded=False):
        st.caption("掃全池月營收，找出 **YoY 持續創高／連增** 的個股，"
                   "並標出目前正在**拉回**（跌破5日線但月線未失守）的買點候選。"
                   "月營收每月只更新一次，結果快取一天。")
        saved = st.session_state.get(REV_KEY)
        if st.button("📈 " + ("重新掃描" if saved else "掃描營收動能"), key="rev_scan"):
            st.session_state[REV_KEY] = _scan_revenue(stocks_pool, start_str, end_str)
            saved = st.session_state[REV_KEY]
        if saved:
            _render(saved)
        else:
            st.info("點上方按鈕開始掃描（首次較慢，之後走快取）。")
