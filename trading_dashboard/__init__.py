"""台股自訂族群看盤系統（分層套件）。

模組分層：
- config            ：常數、門檻、路徑、設定檔載入與驗證、logging
- data_sources.*    ：對外資料抓取（FinMind / TWSE / TPEx / 處置股 / 平行預抓）
- indicators        ：技術指標計算與研判（純函式，可單元測試）
- market            ：交易日推算與全市場成交值排行抓取
- leaderboard       ：熱錢排行帳本（CSV）讀寫與遷移
- ui.*              ：Streamlit 介面面板
"""

__all__ = ["config"]
