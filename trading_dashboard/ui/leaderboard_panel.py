"""熱錢霸榜排行看板（上市 + 上櫃 雙拼版）。"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from ..config import LEADERBOARD_HISTORY_FILE
from ..history import append_leaderboard_snapshot, build_history_matrix, load_history
from ..leaderboard import load_leaderboard, update_leaderboard_data
from ..market import fetch_market_top20_raw
from ..persistence import to_csv_bytes

_DISPLAY_COLUMNS = ["market", "stock_id", "name", "cumulative_days", "turnover_billion", "last_seen_date"]
_DISPLAY_HEADERS = ["所屬市場", "股票代號", "股票名稱", "🔥 累計進榜(天)", "今日成交額(億)", "最後進榜日"]


def render() -> None:
    with st.expander("🔥 全市場(上市+上櫃) 熱錢 Top 20 觀測站", expanded=False):
        if st.button("🔄 刷新最新熱錢排行"):
            _refresh()
        tab_now, tab_history = st.tabs(["📋 目前排行", "📈 歷史趨勢"])
        with tab_now:
            _show_table()
        with tab_history:
            _show_history()


def _refresh() -> None:
    with st.status("向 證交所 與 櫃買中心 調取排行…", expanded=True) as status:
        twse_top20, tpex_top20, trading_date, error_logs = fetch_market_top20_raw(on_stage=st.write)
        combined = (twse_top20 or []) + (tpex_top20 or [])

        if combined and trading_date is not None:
            update_leaderboard_data(combined, trading_date)
            append_leaderboard_snapshot(combined, trading_date)
            n_twse = len(twse_top20) if twse_top20 else 0
            n_tpex = len(tpex_top20) if tpex_top20 else 0
            status.update(
                label=f"完成！對齊交易日：{trading_date}（上市 {n_twse} 檔 + 上櫃 {n_tpex} 檔）",
                state="complete",
                expanded=False,
            )
            if not twse_top20:
                st.warning("⚠️ 上市資料抓取失敗，本次僅含上櫃。")
            if not tpex_top20:
                st.warning("⚠️ 上櫃資料抓取失敗，本次僅含上市。")
        else:
            status.update(label="無法取得排行資料", state="error")
            st.error("❌ 無法從交易所獲取雙拼排行 (可能正處於深夜伺服器清算維護期)")
            st.info("💡 系統已自動啟動【本地備援機制】，維持顯示歷史累積的強勢股名單。")
            st.warning("狀態明細：")
            for log in error_logs:
                st.code(log)


def _show_table() -> None:
    df = load_leaderboard()
    if df is None:
        st.info("本地尚無資料庫紀錄。")
        return
    if df.empty:
        st.info("本地帳本目前為空，請於下個交易日收盤後再次刷新嘗試對齊。")
        return

    df = df.sort_values(by="cumulative_days", ascending=False).reset_index(drop=True)
    latest_date = str(df["last_seen_date"].max())
    display = df[_DISPLAY_COLUMNS].copy()
    display.columns = _DISPLAY_HEADERS
    st.dataframe(display, width="stretch")
    st.download_button(
        "⬇️ 匯出 CSV",
        data=to_csv_bytes(display),
        file_name=f"leaderboard_{latest_date}.csv",
        mime="text/csv",
        key="leaderboard_export",
    )


def _show_history() -> None:
    matrix = build_history_matrix(load_history(LEADERBOARD_HISTORY_FILE))
    if matrix.empty:
        st.info("歷史自部署日起累積，尚無資料。連續幾個交易日刷新後，這裡會出現上榜熱圖。")
        return
    fig = go.Figure(
        go.Heatmap(
            z=matrix.values,
            x=[str(c) for c in matrix.columns],
            y=list(matrix.index),
            colorscale="YlOrRd",
            colorbar={"title": "成交額(億)"},
            hovertemplate="%{y}<br>%{x}：%{z:.1f} 億<extra></extra>",
        )
    )
    fig.update_layout(
        template="plotly_dark",
        height=max(320, 28 * len(matrix.index) + 120),
        margin={"l": 10, "r": 10, "t": 20, "b": 10},
        yaxis={"autorange": "reversed"},  # 上榜次數最多者在最上方
    )
    st.plotly_chart(fig, width="stretch", key="leaderboard_history_heatmap")
    st.caption("顏色 = 當日成交額(億)；只顯示累計上榜次數前 20 的個股。歷史自部署日起累積。")
