"""🚗『紅K順風車』點火掃描：列出近 N 個交易日內出訊號的個股與族群。

點火 = 每一次「第一根紅K」（出量突破 或 鎖漲停；與持倉無關，刻意採用與
回測報告2 ignition_events 相同口徑，才不會被「還抱著」吃掉）。
族群齊發 = 同族群在近 N 日視窗內 ≥GROUP_RALLY_MIN 檔點火（回測中跨多空
最穩的濾網，對應回測『同族群 ±N 日一起點火』同步概念）。
點火判定走 strategy.is_ignition（唯一事實來源）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from ..config import GROUP_RALLY_MIN, TODAY_LOOKBACK_OPTIONS, TW_MIN_ROWS, parse_stock_id
from ..data_sources.prefetch import prefetch_many
from ..strategy import ignition_tag, is_ignition, prepare_series

SCAN_KEY = "tw_scan_result"  # session_state：掃描結果（跨 rerun/切換族群保留）


def _scan_stock(df: pd.DataFrame | None, lookback: int) -> tuple[dict | None, pd.Timestamp | None]:
    """近 lookback 個交易日內『最近一次』第一根紅K點火資訊；無則 None。

    另回傳最新交易日(normalize)；last_dt=None 代表這檔沒抓到資料(限流/停牌)。
    """
    if df is None or len(df) < TW_MIN_ROWS:
        return None, None
    s = prepare_series(df)
    n = len(df)
    last_dt = df.index[-1].normalize()
    lo = max(1, n - lookback)  # 需要 i-1，故 i>=1
    for pos in range(n - 1, lo - 1, -1):  # 由最新往回，取視窗內最近一次「第一根」
        if s.dispday[pos]:
            continue
        if is_ignition(s, pos) and not is_ignition(s, pos - 1):
            ret_v, tag = ignition_tag(s, pos)
            return {"ret": ret_v, "tag": tag, "date": df.index[pos], "days_ago": (n - 1) - pos}, last_dt
    return None, last_dt


def _run_scan(stocks_pool: dict, start_str: str, end_str: str, lookback: int) -> dict:
    """平行預抓全池後逐檔研判，回傳可存進 session_state 的結果 payload。"""
    all_items = [(g, tk, nm) for g, d in stocks_pool.items() for tk, nm in d.items()]
    prog = st.progress(0.0, text="掃描中…")
    data = prefetch_many([tk for _, tk, _ in all_items], start_str, end_str, progress=prog)
    prog.empty()

    seen: dict[str, tuple[dict | None, pd.Timestamp | None]] = {}
    rows: list[dict] = []
    missed: list[str] = []
    scan_date: pd.Timestamp | None = None
    for group, ticker, name in all_items:
        clean_id = parse_stock_id(ticker)
        if clean_id not in seen:
            seen[clean_id] = _scan_stock(data.get(clean_id), lookback)
            if seen[clean_id][1] is None:
                missed.append(f"{name}({clean_id})")
        info, last_dt = seen[clean_id]
        if last_dt is not None and (scan_date is None or last_dt > scan_date):
            scan_date = last_dt
        if info is not None:
            rows.append(
                {
                    "族群": group,
                    "代號": clean_id,
                    "名稱": name,
                    "漲幅%": info["ret"],
                    "點火類型": info["tag"],
                    "點火日": info["date"].strftime("%m/%d"),
                    "_days": info["days_ago"],
                }
            )
    return {
        "rows": rows,
        "missed": missed,
        "lookback": lookback,
        "scan_date": scan_date.strftime("%Y-%m-%d") if scan_date is not None else "—",
    }


def _analyse_rows(rows: list[dict]) -> dict:
    """齊發判定與排序（純函式，供渲染與測試共用）。"""
    df_fire = pd.DataFrame(rows)
    grp_cnt = df_fire.groupby("族群")["代號"].nunique()
    rally = sorted(grp_cnt[grp_cnt >= GROUP_RALLY_MIN].index.tolist())

    df_fire["距今"] = np.where(df_fire["_days"] == 0, "🟢今日", df_fire["_days"].astype(str) + "日前")
    df_fire["_齊發"] = df_fire["族群"].isin(rally)
    df_fire["_群檔數"] = df_fire["族群"].map(grp_cnt)
    # 排序：齊發族群優先 → 同族群檔數多 → 越近越前 → 漲幅大
    df_fire = df_fire.sort_values(
        ["_齊發", "_群檔數", "族群", "_days", "漲幅%"], ascending=[False, False, True, True, False]
    ).reset_index(drop=True)
    df_fire.insert(0, "齊發", np.where(df_fire["_齊發"], "🔥", ""))

    return {
        "frame": df_fire,
        "grp_cnt": grp_cnt,
        "rally": rally,
        "n_stock": int(df_fire["代號"].nunique()),
        "n_group": int(df_fire["族群"].nunique()),
        "n_today": int(df_fire.loc[df_fire["_days"] == 0, "代號"].nunique()),
    }


def _render_result(payload: dict) -> None:
    """從 payload 重畫結果（每次 rerun 都會呼叫，切換族群不會清掉）。"""
    rows, missed = payload["rows"], payload["missed"]
    lookback, date_txt = payload["lookback"], payload["scan_date"]
    rng_txt = "今日" if lookback == 1 else f"近{lookback}日"

    if missed:
        st.warning(
            f"⚠️ {len(missed)} 檔未取得資料（FinMind 限流/停牌），可能遺漏其點火——重新掃描可補齊："
            + "、".join(missed[:20])
            + ("…" if len(missed) > 20 else "")
        )
    if not rows:
        st.warning(f"📅 最新交易日 {date_txt}：全池{rng_txt}沒有任何個股觸發紅K順風車進場訊號。")
        return

    result = _analyse_rows(rows)
    c1, c2, c3 = st.columns(3)
    c1.metric(f"{rng_txt}點火", f"{result['n_stock']} 檔", f"其中今日 {result['n_today']} 檔")
    c2.metric("涉及族群", f"{result['n_group']} 個", f"最新交易日 {date_txt}")
    c3.metric(
        f"族群齊發(≥{GROUP_RALLY_MIN}檔)", f"{len(result['rally'])} 群", "跨多空最穩濾網" if result["rally"] else "無"
    )

    if result["rally"]:
        st.success(
            f"🔥 **族群齊發（{rng_txt}視窗內 ≥{GROUP_RALLY_MIN} 檔點火，優先關注）**："
            + "、".join(f"{g}（{int(result['grp_cnt'][g])}檔）" for g in result["rally"])
        )

    st.dataframe(
        result["frame"][["齊發", "族群", "代號", "名稱", "點火日", "距今", "漲幅%", "點火類型"]],
        width="stretch",
        hide_index=True,
    )
    st.caption(
        "🔒鎖漲停(免量)：漲停鎖死、量被壓縮仍算數（台股特性）｜🚀爆量突破：漲≥6.5% 且量≥1.5×20日均量。"
        "⚠️ 一字/鎖死漲停當天實務多半買不到，訊號常需靠隔天成交。"
        "同一檔若視窗內多次點火，只列最近一次。"
    )


def render(stocks_pool: dict, start_str: str, end_str: str) -> None:
    with st.expander("🚗『紅K順風車』點火掃描（近幾日 · 全池）", expanded=False):
        st.caption(
            "掃描設定檔全部族群，列出**近 N 個交易日內**出現第一根紅K進場訊號的個股，"
            f"並以『同族群視窗內 ≥{GROUP_RALLY_MIN} 檔一起點火』標出**族群齊發**。"
            "掃過一次結果會保留在頁面上，切換族群不會清掉；要更新按『重新掃描』即可。"
        )

        lookback = st.radio(
            "回看範圍",
            list(TODAY_LOOKBACK_OPTIONS),
            index=1,
            horizontal=True,
            format_func=lambda d: "僅今日" if d == 1 else f"近{d}日",
            key="tw_lookback",
        )

        saved = st.session_state.get(SCAN_KEY)
        btn_label = "🔄 重新掃描" if saved else "🔍 掃描點火個股"
        if st.button(btn_label, key="tw_scan"):
            st.session_state[SCAN_KEY] = _run_scan(stocks_pool, start_str, end_str, int(lookback))
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
