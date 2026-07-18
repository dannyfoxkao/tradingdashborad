import numpy as np
import pandas as pd
import streamlit as st

from data import fetch_finmind_data
from data_intraday import fetch_realtime_quotes, session_elapsed_fraction
from ui_today import _load_shares, CAP_THR, SCAN_KEY


# =====================================================================
# 📡 盤中預掃：即時報價（TWSE MIS，免費）× 順風車點火條件的「暫定」版本
#   🔥準點火 = 現在漲≥6.5% 且 量能投影≥1.5×20日均量 且 現價>開盤；或 鎖漲停
#   🌡️醞釀   = 漲≥5% 但條件未齊
#   ⚠️ 盤中訊號未收盤不作數（尾盤可能翻黑/量能不足）；量能為時間投影估算。
# =====================================================================
INTRA_KEY = "tw_intraday_result"


def _scan_intraday(stocks_pool, start_str, end_str):
    tick_map = {}                                    # clean_id → (full_ticker, name)
    for g, d in stocks_pool.items():
        for tk, nm in d.items():
            cid = tk.split(".")[0].strip()
            tick_map.setdefault(cid, (tk, nm))
    quotes = fetch_realtime_quotes([tk for tk, _ in tick_map.values()])
    if not quotes:
        return None
    shares = _load_shares()
    # 時段比例：取最新揭示時間（收盤後=1 → 量能不投影）
    t_latest = max((q.get("t", "") for q in quotes.values()), default="")
    frac = session_elapsed_fraction(t_latest)

    per_stock = {}
    prog = st.progress(0.0, text="比對日K量能基準…")
    for k, (cid, (tk, nm)) in enumerate(tick_map.items()):
        prog.progress((k + 1) / len(tick_map), text=f"比對日K量能基準… {nm}")
        q = quotes.get(cid)
        if not q or not q.get("z") or not q.get("y"):
            continue
        z, y, o, h, v, u = q["z"], q["y"], q.get("o"), q.get("h"), q.get("v") or 0, q.get("u")
        chg = (z / y - 1) * 100
        if chg < 5.0:                                # 只關心醞釀以上，省日K比對
            continue
        df = fetch_finmind_data(cid, start_str, end_str)
        volma = None
        if df is not None and len(df):
            col = "Vol_MA20_clean" if "Vol_MA20_clean" in df.columns else (
                "Vol_MA20" if "Vol_MA20" in df.columns else None)
            if col and pd.notna(df[col].iloc[-1]) and df[col].iloc[-1] > 0:
                volma = float(df[col].iloc[-1])      # 股
        vol_shares = v * 1000.0                      # 張 → 股
        ratio_now = vol_shares / volma if volma else np.nan
        ratio_proj = ratio_now / frac if np.isfinite(ratio_now) else np.nan
        locked = u is not None and z >= u - 1e-6
        red = o is not None and z > o
        fire = locked or (chg >= 6.5 and np.isfinite(ratio_proj) and ratio_proj >= 1.5 and red)
        big = None
        if cid in shares:
            big = shares[cid] * z >= CAP_THR
        from_high = (h - z) / h * 100 if h else np.nan
        per_stock[cid] = {
            "名稱": nm, "現價": z, "漲幅%": round(chg, 2),
            "量能投影x": round(ratio_proj, 2) if np.isfinite(ratio_proj) else None,
            "距高回落%": round(from_high, 1) if np.isfinite(from_high) else None,
            "鎖漲停": "🔒" if locked else ("觸停回落" if (u and h and h >= u - 1e-6) else ""),
            "_fire": bool(fire), "_big": bool(big) if big is not None else False,
        }
    prog.empty()

    rows = []
    for g, d in stocks_pool.items():
        for tk, nm in d.items():
            cid = tk.split(".")[0].strip()
            if cid in per_stock:
                rows.append({"族群": g, "代號": cid, **per_stock[cid]})

    # ── 持倉盤中破線警戒：出場雷達的持倉 trail(昨日已知) × 即時價 ──
    pos_alerts = []
    pos_rows = (st.session_state.get(SCAN_KEY) or {}).get("pos_rows", [])
    for r in pos_rows:
        if r.get("status") != "hold" or r.get("trail") is None:
            continue
        q = quotes.get(r["代號"])
        if not q or not q.get("z"):
            continue
        z, trail = q["z"], float(r["trail"])
        margin = (z - trail) / z * 100 if z > 0 else np.nan
        state = "🔴已破線" if z < trail else ("⚠️近線" if margin < 1.5 else "🟢安全")
        pos_alerts.append({"狀態": state, "代號": r["代號"], "名稱": r["名稱"],
                           "現價": z, "出場價(trail)": round(trail, 2),
                           "緩衝%": round(margin, 1) if np.isfinite(margin) else None})
    pos_alerts.sort(key=lambda x: x.get("緩衝%") if x.get("緩衝%") is not None else 99)

    return {"rows": rows, "frac": frac, "t": t_latest, "pos_alerts": pos_alerts,
            "scan_at": pd.Timestamp.now().strftime("%H:%M:%S")}


def _render_intraday(payload):
    rows, frac = payload["rows"], payload["frac"]
    st.caption(f"報價揭示時間 {payload['t'] or '—'}｜掃描於 {payload['scan_at']}｜"
               f"時段進度 {frac*100:.0f}%（量能投影 = 目前量 ÷ 進度）")

    # ── 🚨 持倉盤中破線警戒 ──
    alerts = payload.get("pos_alerts", [])
    if alerts:
        broken = [a for a in alerts if a["狀態"] == "🔴已破線"]
        near = [a for a in alerts if a["狀態"] == "⚠️近線"]
        st.markdown("##### 🚨 持倉盤中警戒（昨日 trail × 即時價）")
        if broken:
            st.error("🔴 **盤中已破出場線**（回測：出場日盤中先出比等收盤多保住約+1.3%，建議先出一半）：" +
                     "、".join(f"{a['名稱']}({a['代號']}) {a['現價']}＜{a['出場價(trail)']}" for a in broken))
        if near:
            st.warning("⚠️ 距出場線不到 1.5%：" + "、".join(
                f"{a['名稱']}({a['代號']}) 緩衝{a['緩衝%']}%" for a in near))
        st.dataframe(pd.DataFrame(alerts), width="stretch", hide_index=True)
        st.caption("trail 為前一交易日收盤後已知的 2×ATR 出場價；盤中假破線在多頭可能被甩轎——"
                   "破線先出一半、收盤真破再出另一半是風險折衷。")
    elif not (st.session_state.get(SCAN_KEY) or {}).get("pos_rows"):
        st.info("💡 想看持倉破線警戒：先跑一次上方『點火掃描』取得持倉與出場價，再盤中掃描。")

    if not rows:
        st.info("目前全池沒有漲幅 ≥5% 的標的。")
        return
    df = pd.DataFrame(rows)
    df["狀態"] = np.where(df["_fire"], "🔥準點火", "🌡️醞釀")

    fire_df = df[df["_fire"]]
    grp_cnt = fire_df.groupby("族群")["代號"].nunique() if len(fire_df) else pd.Series(dtype=int)
    rally = sorted(grp_cnt[grp_cnt >= 3].index.tolist())
    df["_rally"] = df["族群"].isin(rally)
    df["等級"] = np.select([df["_fire"] & df["_big"] & df["_rally"],
                           df["_fire"] & (df["_big"] | df["_rally"])],
                          ["🅰️", "🅱️"], default="—")
    n_fire = fire_df["代號"].nunique()
    n_a = df.loc[df["等級"] == "🅰️", "代號"].nunique()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔥 準點火", f"{n_fire} 檔")
    c2.metric("🌡️ 醞釀(≥5%)", f"{df['代號'].nunique() - n_fire} 檔")
    c3.metric("醞釀齊發(≥3)", f"{len(rally)} 群")
    c4.metric("🅰️ A級候選", f"{n_a} 檔")

    if rally:
        st.success("🔥 **盤中族群齊發醞釀中**：" + "、".join(
            f"{g}（{int(grp_cnt[g])}檔）" for g in rally))

    df["大型股"] = np.where(df["_big"], "💎", "")
    df["_grade"] = df["等級"].map({"🅰️": 0, "🅱️": 1}).fillna(2)
    df = df.sort_values(["_grade", "_fire", "漲幅%"], ascending=[True, False, False])
    st.dataframe(df[["等級", "狀態", "大型股", "族群", "代號", "名稱", "現價",
                     "漲幅%", "量能投影x", "距高回落%", "鎖漲停"]],
                 width="stretch", hide_index=True)
    st.caption("⚠️ **盤中訊號未收盤不作數**：尾盤翻黑/量縮就會失效，正式訊號以收盤掃描為準。"
               "「距高回落%」大＝開高走低緩坡中（回測：波段峰值日 68% 開高走低），追價留意。"
               "量能投影以時段進度線性估算，早盤會高估爆量股。")


def render_intraday_prescan(stocks_pool, start_str, end_str):
    with st.expander("📡 盤中預掃（即時報價 · 暫定訊號）", expanded=False):
        st.caption("盤中即時抓證交所報價，預判今天收盤「可能」成為紅K順風車點火的標的與醞釀中的族群。"
                   "首次掃描需比對日K量能基準（較慢）；重掃只更新報價。")
        saved = st.session_state.get(INTRA_KEY)
        if st.button("📡 " + ("重新掃描" if saved else "盤中掃描"), key="intra_scan"):
            res = _scan_intraday(stocks_pool, start_str, end_str)
            if res is None:
                st.error("即時報價取得失敗（MIS API 無回應），稍後再試。")
            else:
                st.session_state[INTRA_KEY] = res
                saved = res
        if saved:
            _render_intraday(saved)
        else:
            st.info("點上方按鈕開始盤中掃描。")
