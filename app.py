"""全球自訂族群看盤系統 Pro — Streamlit 入口。

啟動方式：``streamlit run app.py``
"""

from __future__ import annotations

from datetime import datetime, timedelta

import streamlit as st

from trading_dashboard.config import (
    TZ_TAIPEI,
    ConfigError,
    configure_logging,
    find_malformed_ids,
    load_stock_config,
)
from trading_dashboard.data_sources.disposition import fetch_disposition_map
from trading_dashboard.data_sources.finmind import fetch_benchmark_data
from trading_dashboard.ui import chart_grid, leaderboard_panel, radar_panel

_SUB_CHART_OPTIONS = ["成交量", "成交金額 (估算)", "量 + 金額雙對比"]
_PAGE_CSS = """
    <style>
    .stApp { background-color: #121212; color: #FFFFFF; }
    iframe { background-color: #121212 !important; }
    </style>
"""


def _setup_page() -> None:
    st.set_page_config(layout="wide", page_title="全球自訂族群看盤系統 Pro")
    st.markdown(_PAGE_CSS, unsafe_allow_html=True)


def _load_config() -> dict:
    try:
        return load_stock_config()
    except ConfigError as e:
        st.error(f"設定檔載入失敗：{e}")
        st.stop()


def main() -> None:
    configure_logging()
    _setup_page()
    stocks_pool = _load_config()
    malformed = find_malformed_ids(stocks_pool)
    if malformed:
        st.sidebar.warning("以下代號格式異常，將無法取得資料：" + "、".join(malformed))

    # 1) 熱錢霸榜排行
    leaderboard_panel.render()
    st.markdown("---")

    # 2) 側邊欄監控設定
    st.sidebar.header("⚙️ 專業級看盤監控")
    group_choice = st.sidebar.selectbox("選擇觀測族群", list(stocks_pool.keys()))
    st.title(f"🖥️ 監控板塊：{group_choice}")
    grid_cols = st.sidebar.slider("每行顯示圖表數 (網格欄數)", min_value=1, max_value=4, value=3)
    time_window = st.sidebar.slider("觀測天數", min_value=30, max_value=365, value=120)
    st.sidebar.markdown("---")
    st.sidebar.header("📊 指標配置")
    sub_chart_type = st.sidebar.selectbox("副圖顯示內容", _SUB_CHART_OPTIONS)

    # 3) 計算觀測區間（台灣時區）並抓取共用資料
    end_date = datetime.now(TZ_TAIPEI)
    start_date = end_date - timedelta(days=time_window)
    start_str, end_str = start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")

    benchmark_df = fetch_benchmark_data(start_str, end_str)
    disposition_map = fetch_disposition_map()
    selected_stocks = stocks_pool[group_choice]

    # 4) 選股雷達 + K 線網格牆
    radar_panel.render(group_choice, selected_stocks, stocks_pool, start_str, end_str, benchmark_df, disposition_map)
    chart_grid.render(
        group_choice, selected_stocks, grid_cols, sub_chart_type, start_str, end_str, benchmark_df, disposition_map
    )


if __name__ == "__main__":
    main()
