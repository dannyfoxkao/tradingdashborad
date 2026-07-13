import json
import os
import streamlit as st

# 外部設定檔與本地帳本路徑
CONFIG_PATH = "stock_config.json"
LEADERBOARD_FILE = "turnover_leaderboard.csv"


def setup_page():
    """網頁基礎配置（純淨黑魂風）。必須是第一個被呼叫的 Streamlit 指令。"""
    st.set_page_config(layout="wide", page_title="全球自訂族群看盤系統 Pro")
    st.markdown("""
        <style>
        .stApp { background-color: #121212; color: #FFFFFF; }
        iframe { background-color: #121212 !important; }
        </style>
        """, unsafe_allow_html=True)


def load_stock_pool():
    """讀取外部設定檔，回傳 STOCKS_POOL；找不到則報錯並停止。"""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    st.error(f"找不到設定檔 {CONFIG_PATH}，請確認檔案是否存在。")
    st.stop()
