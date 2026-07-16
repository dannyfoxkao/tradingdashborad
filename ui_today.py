import os

import numpy as np
import pandas as pd
import streamlit as st

from data import fetch_finmind_data
from analysis import red_k_tailwind_signals


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
    """回傳 (點火資訊, 持倉/出場資訊, 最新交易日)。
       點火＝近 lookback 個交易日內最近一次第一根紅K；無則 None。
       持倉/出場＝狀態機口徑：今日觸發出場 或 目前持倉中(含出場價/緩衝)。
       last_dt=None 代表這檔沒抓到資料(限流/停牌)。"""
    if df is None or len(df) < 25:
        return None, None, None
    c, o, h, v, ret, vm, disp = _series(df)
    n = len(df)
    last_dt = df.index[-1].normalize()

    ign = None
    lo = max(1, n - lookback)                 # 需要 i-1，故 i>=1
    for pos in range(n - 1, lo - 1, -1):      # 由最新往回，取視窗內最近一次「第一根」點火
        if disp[pos]:
            continue
        if _ignite(c, o, h, v, ret, vm, pos) and not _ignite(c, o, h, v, ret, vm, pos - 1):
            ret_v, tag = _tag_at(c, o, h, v, ret, vm, pos)
            ign = {"ret": ret_v, "tag": tag, "date": df.index[pos],
                   "days_ago": (n - 1) - pos}
            break

    # ── 出場雷達（狀態機：實際進出場配對）──
    pos_info = None
    res = red_k_tailwind_signals(df)
    if res:
        close = float(c[-1])
        if res["sells"] and res["sells"][-1]["date"].normalize() == last_dt:
            pos_info = {"status": "exit", "close": close,
                        "trail": float(res["trail"].iloc[-1]) if pd.notna(res["trail"].iloc[-1]) else None,
                        "reason": res["sells"][-1]["reason"]}
        elif res["latest"]["in_pos"]:
            tv = res["trail"].iloc[-1]
            if pd.notna(tv) and close > 0:
                buf = (close - float(tv)) / close * 100      # 距出場線緩衝(%)
                pos_info = {"status": "hold", "close": close,
                            "trail": float(tv), "buffer": buf,
                            "entry": res["buys"][-1]["date"] if res["buys"] else None}
    return ign, pos_info, last_dt


SCAN_KEY = "tw_scan_result"          # session_state：掃描結果（跨 rerun/切換族群保留）
SHARES_CSV = os.path.join("backtest_cache", "shares_issued.csv")   # 發行股數（sweep_mktcap 產出）
CAP_THR = 900e8                      # 大型股門檻：市值≥900億 ≈ 全市場前150大


def _load_shares():
    """發行股數 {股號: 股數}；檔案不存在回空 dict（等級標記自動略過）。"""
    try:
        if os.path.exists(SHARES_CSV):
            sh = pd.read_csv(SHARES_CSV, dtype={"sid": str})
            return dict(zip(sh.sid, sh.shares))
    except Exception:
        pass
    return {}


def _run_scan(stocks_pool, start_str, end_str, lookback):
    """實際掃描全池，回傳可存進 session_state 的結果 payload。"""
    seen, rows, scan_date, missed = {}, [], None, []
    pos_rows, pos_seen = [], set()              # 出場雷達列（每檔只列一次）
    shares = _load_shares()                     # 發行股數 → 市值分級（大型股≥900億）
    prog = st.progress(0.0, text="掃描中…")
    all_items = [(g, tk, nm) for g, d in stocks_pool.items() for tk, nm in d.items()]
    total = len(all_items) or 1

    with st.spinner("逐檔研判紅K順風車訊號中…"):
        for k, (group, ticker, name) in enumerate(all_items):
            prog.progress((k + 1) / total, text=f"掃描中… {k + 1}/{total}　{name}")
            clean_id = ticker.split(".")[0].strip()
            if clean_id not in seen:
                df = fetch_finmind_data(clean_id, start_str, end_str)
                info, pos_info, last_dt = _scan_stock(df, lookback)
                big = None
                if df is not None and len(df) and clean_id in shares:
                    big = shares[clean_id] * float(df["Close"].iloc[-1]) >= CAP_THR
                seen[clean_id] = (info, pos_info, last_dt, big)
                if last_dt is None:
                    missed.append(f"{name}({clean_id})")
            info, pos_info, last_dt, big = seen[clean_id]
            if last_dt is not None and (scan_date is None or last_dt > scan_date):
                scan_date = last_dt
            if info is not None:
                rows.append({"族群": group, "代號": clean_id, "名稱": name,
                             "漲幅%": info["ret"], "點火類型": info["tag"],
                             "點火日": info["date"].strftime("%m/%d"),
                             "_days": info["days_ago"], "_big": bool(big) if big is not None else False})
            if pos_info is not None and clean_id not in pos_seen:
                pos_seen.add(clean_id)
                pos_rows.append({"族群": group, "代號": clean_id, "名稱": name, **pos_info})
    prog.empty()
    return {"rows": rows, "missed": missed, "lookback": lookback, "pos_rows": pos_rows,
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
        _render_exit_radar(payload.get("pos_rows", []), date_txt)
        return

    df_fire = pd.DataFrame(rows)
    n_stock = df_fire["代號"].nunique()
    n_group = df_fire["族群"].nunique()
    n_today = df_fire.loc[df_fire["_days"] == 0, "代號"].nunique()

    # 族群齊發：同族群在視窗內 ≥3 檔點火（對應回測 ±N 日同步；跨多空最穩濾網）
    grp_cnt = df_fire.groupby("族群")["代號"].nunique()
    rally = sorted(grp_cnt[grp_cnt >= 3].index.tolist())

    # 等級：🅰️ 大型股(市值≥900億)×族群齊發｜🅱️ 只中一個｜— 都沒中
    #（回測：A級 多頭勝率58.8%/空頭56.5%，中位數皆轉正；中小型孤軍為最弱桶，建議不做）
    if "_big" not in df_fire.columns:
        df_fire["_big"] = False                  # 舊掃描結果相容
    df_fire["_齊發"] = df_fire["族群"].isin(rally)
    df_fire["等級"] = np.select(
        [df_fire["_big"] & df_fire["_齊發"], df_fire["_big"] | df_fire["_齊發"]],
        ["🅰️", "🅱️"], default="—")
    n_a = df_fire.loc[df_fire["等級"] == "🅰️", "代號"].nunique()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"{rng_txt}點火", f"{n_stock} 檔", f"其中今日 {n_today} 檔")
    c2.metric("涉及族群", f"{n_group} 個", f"最新交易日 {date_txt}")
    c3.metric("族群齊發(≥3檔)", f"{len(rally)} 群",
              "跨多空最穩濾網" if rally else "無")
    c4.metric("🅰️ A級(大型×齊發)", f"{n_a} 檔",
              "多空勝率皆57%±" if n_a else "無")

    if rally:
        st.success(f"🔥 **族群齊發（{rng_txt}視窗內 ≥3 檔點火，優先關注）**：" + "、".join(
            f"{g}（{int(grp_cnt[g])}檔）" for g in rally))

    # 距今日數 → 中文；今日以綠點標示
    df_fire["距今"] = np.where(df_fire["_days"] == 0, "🟢今日",
                               df_fire["_days"].astype(str) + "日前")
    # 排序：A級 → B級 → 其他，再依 齊發族群/群檔數/越近/漲幅
    df_fire["_grade"] = df_fire["等級"].map({"🅰️": 0, "🅱️": 1}).fillna(2)
    df_fire["_群檔數"] = df_fire["族群"].map(grp_cnt)
    df_fire = df_fire.sort_values(
        ["_grade", "_齊發", "_群檔數", "族群", "_days", "漲幅%"],
        ascending=[True, False, False, True, True, False]).reset_index(drop=True)
    df_fire.insert(0, "齊發", np.where(df_fire["_齊發"], "🔥", ""))
    df_fire["大型股"] = np.where(df_fire["_big"], "💎", "")

    st.dataframe(
        df_fire[["等級", "齊發", "大型股", "族群", "代號", "名稱", "點火日", "距今", "漲幅%", "點火類型"]],
        width="stretch", hide_index=True)
    st.caption("**等級**：🅰️ 大型股(市值≥900億≈前150大)×族群齊發＝多空勝率皆57%±、中位數正，正常倉位｜"
               "🅱️ 只中一個濾網＝減碼觀察｜— 中小型孤軍＝回測最弱桶(多頭勝率40%/空頭34%)，建議不做。"
               "🔒鎖漲停(免量)：漲停鎖死、量被壓縮仍算數｜🚀爆量突破：漲≥6.5% 且量≥1.5×20日均量。"
               "⚠️ 一字/鎖死漲停當天實務多半買不到；同一檔視窗內多次點火只列最近一次。")

    _render_exit_radar(payload.get("pos_rows", []), date_txt)


def _render_exit_radar(pos_rows, date_txt):
    """🚪 出場雷達：今日觸發出場的標的 + 持倉中依緩衝排序。"""
    st.markdown("---")
    st.markdown("#### 🚪 順風車出場雷達（狀態機持倉）")
    if not pos_rows:
        st.info("目前策略沒有任何持倉、也沒有今日出場訊號。")
        return

    exits = [r for r in pos_rows if r["status"] == "exit"]
    holds = sorted([r for r in pos_rows if r["status"] == "hold"],
                   key=lambda r: r.get("buffer", 1e9))
    n_danger = sum(1 for r in holds if r.get("buffer", 99) < 3)

    c1, c2, c3 = st.columns(3)
    c1.metric("🔴 今日觸發出場", f"{len(exits)} 檔", f"最新交易日 {date_txt}")
    c2.metric("⚠️ 接近出場(緩衝<3%)", f"{n_danger} 檔")
    c3.metric("🟢 持倉中", f"{len(holds)} 檔")

    if exits:
        st.error("🔴 **今日觸發出場（收盤已跌破出場線／性質切換），依紀律隔天出場**：" + "、".join(
            f"{r['名稱']}({r['代號']}) {r['reason']}" for r in exits))

    disp = []
    for r in exits:
        disp.append({"狀態": "🔴出場", "族群": r["族群"], "代號": r["代號"], "名稱": r["名稱"],
                     "收盤": r["close"], "出場價": r.get("trail"),
                     "緩衝%": None, "備註": r.get("reason", "")})
    for r in holds:
        buf = r.get("buffer")
        mark = "⚠️危險" if (buf is not None and buf < 3) else "🟢持倉"
        disp.append({"狀態": mark, "族群": r["族群"], "代號": r["代號"], "名稱": r["名稱"],
                     "收盤": r["close"], "出場價": round(r["trail"], 2),
                     "緩衝%": round(buf, 1) if buf is not None else None,
                     "備註": f"進場 {r['entry'].strftime('%m/%d')}" if r.get("entry") is not None else ""})
    st.dataframe(pd.DataFrame(disp), width="stretch", hide_index=True)
    st.caption("出場價＝進場後最高收盤 − 2×ATR14(處置剔除)，逐日上移；**收盤 < 出場價 → 隔日出場**。"
               "緩衝%＝(收盤−出場價)/收盤，越小越接近出場。持倉為策略狀態機口徑，非你的實際庫存。")


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
