import os

import pandas as pd
import streamlit as st

from config import LEADERBOARD_FILE
from leaderboard import fetch_market_top20_raw, update_leaderboard_data


# =====================================================================
# 🖥️ UI：熱錢霸榜排行看板 (雙拼版)
# =====================================================================
def render_leaderboard():
    with st.expander("🔥 全市場(上市+上櫃) 熱錢 Top 20 觀測站", expanded=False):
        if st.button("🔄 刷新最新熱錢排行"):
            with st.spinner("正在向 證交所 與 櫃買中心 安全調取雙拼數據..."):
                twse_top20, tpex_top20, trading_date, error_logs = fetch_market_top20_raw()

                # ★ 合併上市 + 上櫃（各取前 20）成單一名單再寫入帳本
                combined = (twse_top20 or []) + (tpex_top20 or [])

                if combined:
                    df_leaderboard = update_leaderboard_data(combined, trading_date)
                    n_twse = len(twse_top20) if twse_top20 else 0
                    n_tpex = len(tpex_top20) if tpex_top20 else 0
                    st.success(f"上市櫃數據混合成功！對齊交易日：{trading_date}（上市 {n_twse} 檔 + 上櫃 {n_tpex} 檔）")
                    if not twse_top20:
                        st.warning("⚠️ 上市資料抓取失敗，本次僅含上櫃。")
                    if not tpex_top20:
                        st.warning("⚠️ 上櫃資料抓取失敗，本次僅含上市。")
                else:
                    st.error("❌ 無法從交易所獲取雙拼排行 (可能正處於深夜伺服器清算維護期)")
                    st.info("💡 系統已自動啟動【本地備援機制】，維持顯示歷史累積的強勢股名單。")
                    st.warning("狀態明細：")
                    for log in error_logs:
                        st.code(log)

        if os.path.exists(LEADERBOARD_FILE):
            df_disp = pd.read_csv(LEADERBOARD_FILE, dtype={"stock_id": str})
            if not df_disp.empty:
                df_disp = df_disp.sort_values(by="cumulative_days", ascending=False).reset_index(drop=True)
                if "market" not in df_disp.columns:
                    df_disp["market"] = "上市"

                # 重整顯示欄位
                df_disp = df_disp[["market", "stock_id", "name", "cumulative_days", "turnover_billion", "last_seen_date"]]
                df_disp.columns = ["所屬市場", "股票代號", "股票名稱", "🔥 累計進榜(天)", "今日成交額(億)", "最後進榜日"]

                # 使用自訂 Style 顏色高亮上櫃股 (此處以單純的 dataframe 呈現，Streamlit 會自動排版)
                st.dataframe(df_disp, width='stretch')
            else:
                st.info("本地帳本目前為空，請於下個交易日收盤後再次刷新嘗試對齊。")
        else:
            st.info("本地尚無資料庫紀錄。")
