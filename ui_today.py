import numpy as np
import pandas as pd
import streamlit as st

from data import fetch_finmind_data
from analysis import red_k_tailwind_signals


# =====================================================================
# 🚗 今日『紅K順風車』點火掃描：列出當日出訊號的個股與族群
#   點火 = 狀態機當日出現「第一根紅K」進場（出量突破 或 鎖漲停）。
#   依回測結論高亮「族群齊發(同日≥3檔)」——跨多空最穩的濾網。
# =====================================================================
def _ignition_label(df):
    """判斷最新一根是哪種點火，回傳 (漲幅%, 類型標籤)。"""
    c = df["Close"].to_numpy(float)
    o = df["Open"].to_numpy(float)
    h = df["High"].to_numpy(float)
    v = df["Volume"].to_numpy(float)
    if "Ret1" in df.columns and np.isfinite(df["Ret1"].iloc[-1]):
        ret = float(df["Ret1"].iloc[-1])
    else:
        ret = (c[-1] / c[-2] - 1) * 100 if len(c) > 1 and c[-2] > 0 else np.nan
    volma_col = "Vol_MA20_clean" if "Vol_MA20_clean" in df.columns else (
        "Vol_MA20" if "Vol_MA20" in df.columns else None)
    volma = float(df[volma_col].iloc[-1]) if volma_col else float(pd.Series(v).rolling(20).mean().iloc[-1])

    locked = np.isfinite(ret) and ret >= 9.5 and c[-1] >= h[-1] - 1e-6
    vol_ok = (np.isfinite(ret) and np.isfinite(volma) and ret >= 6.5
              and volma > 0 and v[-1] >= 1.5 * volma and c[-1] > o[-1])
    if locked and vol_ok:
        tag = "🔒鎖漲停+爆量"
    elif locked:
        tag = "🔒鎖漲停(免量)"
    else:
        tag = "🚀爆量突破"
    return round(ret, 2) if np.isfinite(ret) else None, tag


def render_today_tailwind(stocks_pool, start_str, end_str):
    with st.expander("🚗 今日『紅K順風車』點火掃描（全池）", expanded=False):
        st.caption("掃描設定檔全部族群，列出**最新交易日**當天出現第一根紅K進場訊號的個股。"
                   "會逐檔向 FinMind 取資料，首次掃描較慢；受免費層限流影響可稍後重掃。")
        if not st.button("🔍 掃描今日點火個股"):
            st.info("點上方按鈕開始掃描。")
            return

        # clean_id → (fired?, name, group, ret, tag, date)；跨族群同一檔只算一次資料
        seen, rows, scan_date = {}, [], None
        prog = st.progress(0.0, text="掃描中…")
        all_items = [(g, tk, nm) for g, d in stocks_pool.items() for tk, nm in d.items()]
        total = len(all_items) or 1

        with st.spinner("逐檔研判紅K順風車訊號中…"):
            for k, (group, ticker, name) in enumerate(all_items):
                prog.progress((k + 1) / total, text=f"掃描中… {k + 1}/{total}　{name}")
                clean_id = ticker.split(".")[0].strip()
                if clean_id not in seen:
                    df = fetch_finmind_data(clean_id, start_str, end_str)
                    fired = ret = tag = None
                    last_dt = None
                    if df is not None and len(df) >= 25:
                        res = red_k_tailwind_signals(df)
                        last_dt = df.index[-1].normalize()
                        if res and res["buys"]:
                            b_last = res["buys"][-1]["date"].normalize()
                            if b_last == last_dt:            # 進場日 = 最新交易日 → 今日點火
                                fired = True
                                ret, tag = _ignition_label(df)
                    seen[clean_id] = (fired, ret, tag, last_dt)
                fired, ret, tag, last_dt = seen[clean_id]
                if last_dt is not None and (scan_date is None or last_dt > scan_date):
                    scan_date = last_dt
                if fired:
                    rows.append({"族群": group, "代號": clean_id, "名稱": name,
                                 "漲幅%": ret, "點火類型": tag})
        prog.empty()

        date_txt = scan_date.strftime("%Y-%m-%d") if scan_date is not None else "—"
        if not rows:
            st.warning(f"📅 最新交易日 {date_txt}：全池今日沒有任何個股觸發紅K順風車進場訊號。")
            return

        df_fire = pd.DataFrame(rows)
        n_stock = df_fire["代號"].nunique()
        n_group = df_fire["族群"].nunique()

        # 族群齊發：同一族群當日 ≥3 檔一起點火（回測中跨多空最穩的濾網）
        grp_cnt = df_fire.groupby("族群")["代號"].nunique()
        rally = sorted(grp_cnt[grp_cnt >= 3].index.tolist())

        c1, c2, c3 = st.columns(3)
        c1.metric("今日點火", f"{n_stock} 檔", f"最新交易日 {date_txt}")
        c2.metric("涉及族群", f"{n_group} 個")
        c3.metric("族群齊發(≥3檔)", f"{len(rally)} 群",
                  "跨多空最穩濾網" if rally else "今日無")

        if rally:
            st.success("🔥 **族群齊發（同日≥3檔點火，優先關注）**：" + "、".join(
                f"{g}（{int(grp_cnt[g])}檔）" for g in rally))

        # 齊發族群排前面，其次同族群檔數多者，再依漲幅
        df_fire["_齊發"] = df_fire["族群"].isin(rally)
        df_fire["_群檔數"] = df_fire["族群"].map(grp_cnt)
        df_fire = df_fire.sort_values(
            ["_齊發", "_群檔數", "族群", "漲幅%"],
            ascending=[False, False, True, False]).reset_index(drop=True)
        df_fire.insert(0, "齊發", np.where(df_fire["_齊發"], "🔥", ""))
        st.dataframe(df_fire[["齊發", "族群", "代號", "名稱", "漲幅%", "點火類型"]],
                     width="stretch", hide_index=True)
        st.caption("🔒鎖漲停(免量)：漲停鎖死、量被壓縮仍算數（台股特性）｜🚀爆量突破：漲≥6.5% 且量≥1.5×20日均量。"
                   "⚠️ 一字/鎖死漲停當天實務多半買不到，訊號常需靠隔天成交。")
