# =====================================================================
# 全球自訂族群看盤系統 Pro — 主入口
# 各功能模組：
#   config.py         → 頁面設定 / 設定檔讀取 / 常數
#   data.py           → FinMind API 與各項資料抓取（快取）
#   leaderboard.py    → 全市場熱錢成交值排行的資料處理
#   analysis.py       → 趨勢/量能/大盤天氣/交易訊號等純研判函式
#   ui_leaderboard.py → 熱錢排行看板 UI
#   ui_weather.py     → 大盤氣象台 UI
#   ui_radar.py       → 選股雷達 UI
#   ui_grid.py        → 族群動能 + K 線網格牆 UI
# =====================================================================
from config import setup_page, load_stock_pool

# ⚠️ set_page_config 必須是第一個 Streamlit 指令，故先於其他 import 執行
setup_page()

from datetime import datetime, timedelta

import streamlit as st

from data import fetch_benchmark_data, fetch_index_close, fetch_disposition_map
from ui_leaderboard import render_leaderboard
from ui_today import render_today_tailwind
from ui_intraday import render_intraday_prescan
from ui_nav import render_group_nav
from ui_weather import render_market_weather
from ui_radar import render_stock_radar
from ui_grid import render_group_momentum, render_grid_wall

# 讀取外部設定檔
STOCKS_POOL = load_stock_pool()

# 🔥 熱錢霸榜排行看板
render_leaderboard()

st.markdown("---")

# 🚗 今日『紅K順風車』點火掃描（全池；按鈕觸發）
_today_end = datetime.today().strftime("%Y-%m-%d")
_today_start = (datetime.today() - timedelta(days=120)).strftime("%Y-%m-%d")
render_today_tailwind(STOCKS_POOL, _today_start, _today_end)

# 📡 盤中預掃（即時報價；按鈕觸發）
render_intraday_prescan(STOCKS_POOL, _today_start, _today_end)

st.markdown("---")

# ⚙️ 側邊欄：專業級看盤監控
st.sidebar.header("⚙️ 專業級看盤監控")
group_choice = render_group_nav(STOCKS_POOL)

st.title(f"🖥️ 監控板塊：{group_choice}")

grid_cols = st.sidebar.slider("每行顯示圖表數 (網格欄數)", min_value=1, max_value=4, value=3)
time_window = st.sidebar.slider("觀測天數", min_value=30, max_value=365, value=120)

st.sidebar.markdown("---")
st.sidebar.header("📊 指標配置")
sub_chart_type = st.sidebar.selectbox(
    "副圖顯示內容",
    ["成交量", "成交金額 (估算)", "量 + 金額雙對比"]
)
show_tailwind = st.sidebar.checkbox("🚗 標記『紅K順風車』買賣點", value=True)

end_date = datetime.today()
start_date = end_date - timedelta(days=time_window)
start_str = start_date.strftime("%Y-%m-%d")
end_str = end_date.strftime("%Y-%m-%d")

# 大盤 Alpha 計算基準
benchmark_df = fetch_benchmark_data(start_str, end_str)

# 大盤天氣濾鏡用指數（固定 150 天回看確保 MACD/月線算得出來）
_mkt_start = (datetime.today() - timedelta(days=150)).strftime('%Y-%m-%d')
twse_index_df = fetch_index_close("TAIEX", _mkt_start, end_str)
tpex_index_df = fetch_index_close("TPEx", _mkt_start, end_str)

# 處置股清單
disposition_map = fetch_disposition_map()

# --- 嚴格橫向二維排版渲染 ---
selected_stocks = STOCKS_POOL[group_choice]
tickers = list(selected_stocks.keys())

# 🌦️ 大盤氣象台
render_market_weather(twse_index_df, tpex_index_df)

# 📈 選股雷達
render_stock_radar(group_choice, selected_stocks, STOCKS_POOL,
                   start_str, end_str, benchmark_df, disposition_map)

# 🧭 族群動能
render_group_momentum(tickers, start_str, end_str)

# 🖥️ K 線網格牆
render_grid_wall(tickers, selected_stocks, grid_cols, sub_chart_type,
                 start_str, end_str, disposition_map, benchmark_df, show_tailwind)
