import numpy as np
import pandas as pd
import streamlit as st

from data import fetch_finmind_data


# =====================================================================
# 🚗 『紅K順風車』點火掃描：列出近 N 個交易日內出訊號的個股與族群
#   點火 = 每一次「第一根紅K」（出量突破 或 鎖漲停；與持倉無關，
#   刻意採用與回測報告2 ignition_events 相同口徑，才不會被「還抱著」吃掉）。
#   族群齊發 = 同族群在近 N 日視窗內 ≥3 檔點火（回測中跨多空最穩的濾網，
#   對應回測『同族群 ±N 日一起點火』同步概念）。
# =====================================================================
def _series(df):
    """一次備好判斷點火要用的所有陣列。"""
    c = df["Close"].to_numpy(float)
    o = df["Open"].to_numpy(float)
    h = df["High"].to_numpy(float)
    v = df["Volume"].to_numpy(float)
    if "Ret1" in df.columns:
        ret = df["Ret1"].to_numpy(float)
    else:
        ret = np.concatenate([[np.nan], (c[1:] / c[:-1] - 1) * 100]) if len(c) > 1 else np.array([np.nan])
    volma_col = "Vol_MA20_clean" if "Vol_MA20_clean" in df.columns else (
        "Vol_MA20" if "Vol_MA20" in df.columns else None)
    vm = df[volma_col].to_numpy(float) if volma_col else pd.Series(v).rolling(20).mean().to_numpy()
    disp = df["DispDay"].to_numpy(bool) if "DispDay" in df.columns else np.zeros(len(df), bool)
    return c, o, h, v, ret, vm, disp


def _ignite(c, o, h, v, ret, vm, i):
    """第 i 根是否點火（鎖漲停免量 或 出量突破）。"""
    if not (np.isfinite(ret[i]) and c[i] > 0):
        return False
    locked = ret[i] >= 9.5 and c[i] >= h[i] - 1e-6
    vol_ok = (np.isfinite(vm[i]) and ret[i] >= 6.5 and vm[i] > 0
              and v[i] >= 1.5 * vm[i] and c[i] > o[i])
    return bool(locked or vol_ok)


def _tag_at(c, o, h, v, ret, vm, i):
    """第 i 根的 (漲幅%, 類型標籤)。"""
    locked = np.isfinite(ret[i]) and ret[i] >= 9.5 and c[i] >= h[i] - 1e-6
    vol_ok = (np.isfinite(ret[i]) and np.isfinite(vm[i]) and ret[i] >= 6.5
              and vm[i] > 0 and v[i] >= 1.5 * vm[i] and c[i] > o[i])
    tag = "🔒鎖漲停+爆量" if (locked and vol_ok) else ("🔒鎖漲停(免量)" if locked else "🚀爆量突破")
    return (round(float(ret[i]), 2) if np.isfinite(ret[i]) else None), tag


def _scan_stock(df, lookback):
    """回傳該檔在近 lookback 個交易日內『最近一次』第一根紅K點火資訊；無則 None。
       另回傳最新交易日(normalize)；last_dt=None 代表這檔沒抓到資料(限流/停牌)。"""
    if df is None or len(df) < 25:
        return None, None
    c, o, h, v, ret, vm, disp = _series(df)
    n = len(df)
    last_dt = df.index[-1].normalize()
    lo = max(1, n - lookback)                 # 需要 i-1，故 i>=1
    for pos in range(n - 1, lo - 1, -1):      # 由最新往回，取視窗內最近一次「第一根」點火
        if disp[pos]:
            continue
        if _ignite(c, o, h, v, ret, vm, pos) and not _ignite(c, o, h, v, ret, vm, pos - 1):
            ret_v, tag = _tag_at(c, o, h, v, ret, vm, pos)
            return {"ret": ret_v, "tag": tag, "date": df.index[pos],
                    "days_ago": (n - 1) - pos}, last_dt
    return None, last_dt


SCAN_KEY = "tw_scan_result"          # session_state：掃描結果（跨 rerun/切換族群保留）


def _run_scan(stocks_pool, start_str, end_str, lookback):
    """實際掃描全池，回傳可存進 session_state 的結果 payload。"""
    seen, rows, scan_date, missed = {}, [], None, []
    prog = st.progress(0.0, text="掃描中…")
    all_items = [(g, tk, nm) for g, d in stocks_pool.items() for tk, nm in d.items()]
    total = len(all_items) or 1

    with st.spinner("逐檔研判紅K順風車訊號中…"):
        for k, (group, ticker, name) in enumerate(all_items):
            prog.progress((k + 1) / total, text=f"掃描中… {k + 1}/{total}　{name}")
            clean_id = ticker.split(".")[0].strip()
            if clean_id not in seen:
                df = fetch_finmind_data(clean_id, start_str, end_str)
                info, last_dt = _scan_stock(df, lookback)
                seen[clean_id] = (info, last_dt)
                if last_dt is None:
                    missed.append(f"{name}({clean_id})")
            info, last_dt = seen[clean_id]
            if last_dt is not None and (scan_date is None or last_dt > scan_date):
                scan_date = last_dt
            if info is not None:
                rows.append({"族群": group, "代號": clean_id, "名稱": name,
                             "漲幅%": info["ret"], "點火類型": info["tag"],
                             "點火日": info["date"].strftime("%m/%d"),
                             "_days": info["days_ago"]})
    prog.empty()
    return {"rows": rows, "missed": missed, "lookback": lookback,
            "scan_date": scan_date.strftime("%Y-%m-%d") if scan_date is not None else "—"}


def _render_result(payload):
    """從 payload 重畫結果（每次 rerun 都會呼叫，故切換族群不會清掉）。"""
    rows, missed = payload["rows"], payload["missed"]
    lookback, date_txt = payload["lookback"], payload["scan_date"]
    rng_txt = "今日" if lookback == 1 else f"近{lookback}日"

    if missed:
        st.warning(f"⚠️ {len(missed)} 檔未取得資料（FinMind 限流/停牌），可能遺漏其點火——重新掃描可補齊："
                   + "、".join(missed[:20]) + ("…" if len(missed) > 20 else ""))
    if not rows:
        st.warning(f"📅 最新交易日 {date_txt}：全池{rng_txt}沒有任何個股觸發紅K順風車進場訊號。")
        return

    df_fire = pd.DataFrame(rows)
    n_stock = df_fire["代號"].nunique()
    n_group = df_fire["族群"].nunique()
    n_today = df_fire.loc[df_fire["_days"] == 0, "代號"].nunique()

    # 族群齊發：同族群在視窗內 ≥3 檔點火（對應回測 ±N 日同步；跨多空最穩濾網）
    grp_cnt = df_fire.groupby("族群")["代號"].nunique()
    rally = sorted(grp_cnt[grp_cnt >= 3].index.tolist())

    c1, c2, c3 = st.columns(3)
    c1.metric(f"{rng_txt}點火", f"{n_stock} 檔", f"其中今日 {n_today} 檔")
    c2.metric("涉及族群", f"{n_group} 個", f"最新交易日 {date_txt}")
    c3.metric("族群齊發(≥3檔)", f"{len(rally)} 群",
              "跨多空最穩濾網" if rally else "無")

    if rally:
        st.success(f"🔥 **族群齊發（{rng_txt}視窗內 ≥3 檔點火，優先關注）**：" + "、".join(
            f"{g}（{int(grp_cnt[g])}檔）" for g in rally))

    # 距今日數 → 中文；今日以綠點標示
    df_fire["距今"] = np.where(df_fire["_days"] == 0, "🟢今日",
                               df_fire["_days"].astype(str) + "日前")
    # 排序：齊發族群優先 → 同族群檔數多 → 越近越前 → 漲幅大
    df_fire["_齊發"] = df_fire["族群"].isin(rally)
    df_fire["_群檔數"] = df_fire["族群"].map(grp_cnt)
    df_fire = df_fire.sort_values(
        ["_齊發", "_群檔數", "族群", "_days", "漲幅%"],
        ascending=[False, False, True, True, False]).reset_index(drop=True)
    df_fire.insert(0, "齊發", np.where(df_fire["_齊發"], "🔥", ""))

    st.dataframe(
        df_fire[["齊發", "族群", "代號", "名稱", "點火日", "距今", "漲幅%", "點火類型"]],
        width="stretch", hide_index=True)
    st.caption("🔒鎖漲停(免量)：漲停鎖死、量被壓縮仍算數（台股特性）｜🚀爆量突破：漲≥6.5% 且量≥1.5×20日均量。"
               "⚠️ 一字/鎖死漲停當天實務多半買不到，訊號常需靠隔天成交。"
               "同一檔若視窗內多次點火，只列最近一次。")


def render_today_tailwind(stocks_pool, start_str, end_str):
    with st.expander("🚗『紅K順風車』點火掃描（近幾日 · 全池）", expanded=False):
        st.caption("掃描設定檔全部族群，列出**近 N 個交易日內**出現第一根紅K進場訊號的個股，"
                   "並以『同族群視窗內 ≥3 檔一起點火』標出**族群齊發**。"
                   "掃過一次結果會保留在頁面上，切換族群不會清掉；要更新按『重新掃描』即可。")

        lookback = st.radio(
            "回看範圍", [1, 3, 5], index=1, horizontal=True,
            format_func=lambda d: ("僅今日" if d == 1 else f"近{d}日"),
            key="tw_lookback")

        saved = st.session_state.get(SCAN_KEY)
        btn_label = "🔄 重新掃描" if saved else "🔍 掃描點火個股"
        if st.button(btn_label, key="tw_scan"):
            st.session_state[SCAN_KEY] = _run_scan(stocks_pool, start_str, end_str, lookback)
            saved = st.session_state[SCAN_KEY]

        if not saved:
            st.info("選好回看範圍後，點上方按鈕開始掃描。")
            return

        # 若回看範圍改了但還沒重掃，提醒目前顯示的是舊視窗結果
        if saved["lookback"] != lookback:
            cur = "今日" if lookback == 1 else f"近{lookback}日"
            old = "今日" if saved["lookback"] == 1 else f"近{saved['lookback']}日"
            st.info(f"目前顯示上次掃描（{old}）的結果；已把回看範圍改為「{cur}」，按『重新掃描』以更新。")

        _render_result(saved)
