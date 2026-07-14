# 全球自訂族群看盤系統 Pro

一套以 [Streamlit](https://streamlit.io/) 打造的台股**族群監控看盤儀表板**。針對自訂的產業族群（PCB、光通、散熱、記憶體、軍工……）批次繪製 K 線網格牆，疊加多項量化研判指標，並提供全市場（上市＋上櫃）**熱錢成交值排行**的長期累積帳本與**強多／震盪偏多選股雷達**。

資料來源為 [FinMind](https://finmindtrade.com/)（個股／大盤日線）、[證交所 TWSE](https://www.twse.com.tw/) 與 [櫃買中心 TPEx](https://www.tpex.org.tw/) 公開 API。

---

## 功能特色

| 面板 | 說明 |
|------|------|
| 🔥 **熱錢 Top 20 排行** | 上市＋上櫃成交值前 20 寫入本地帳本，累積「連續進榜天數」；📈 歷史趨勢分頁以每日快照畫上榜熱圖；一鍵匯出 CSV。 |
| 🚗 **今日點火掃描** | 全池掃描近 1/3/5 個交易日內的「第一根紅K」點火（出量突破／鎖漲停免量），標出**族群齊發（≥3 檔）**；結果跨 rerun 保留。 |
| 🌦️ **大盤氣象台** | 上市／上櫃指數的天氣濾鏡：收盤對月線判安全/危險區 × MACD 柱方向判風力，附操作心法。 |
| 📈 **選股雷達** | 「本族群／全部族群」批次掃描 🟢強多 / 🌱底部翻揚 / 🟡震盪偏多，依強度與 Alpha 排序；🕘 訊號歷史分頁可回算 N 日前瞻報酬驗證準度；匯出 CSV。 |
| 🧭 **族群動能** | 目前族群的多空陣營占比；空方過半警示「族群轉弱」、多方過六成提示「族群一起動」。 |
| 🖥️ **K 線網格牆** | 自訂欄數網格：K 線＋均線（含 MA200 長線濾網）、量能／金額副圖、戰情徽章、交易一致性訊號燈（6 買訊＋5 賣警），並可疊加**紅K順風車覆蓋層**（▲買/▼賣/★警示、2×ATR 移動停利線、壓/撐/停損水平線、波動加速背景）。 |
| 🛠️ **族群管理** | 側欄直接增刪族群與代號（格式驗證＋一次性備份＋原子寫入），免手改 JSON。 |

### 指標研判

- **趨勢分類 v2**：均線排列＋MA20/短均斜率，分為 強多 / 🌱底部翻揚 / 震盪(偏多) / 中性 / 🥀頭部鈍化 / 震盪(偏空) / 弱勢；資料不足標示「資料不足」而非誤判。
- **紅K順風車策略**（規範：`docs/volatility_framework.md`）：第一根紅K 點火進場（漲≥6.5%＋量≥1.5×剔除後均量收紅，或 漲≥9.5% 鎖漲停免量）、2×ATR14 移動停利＋SNR 性質切換出場、波動降溫／性質切換警示層、ATR%×SNR 四象限研判。
- **波動率框架資料管線**：還原股價（修除權/分割假跳空）、處置期【剔除法】（整段移除處置日、接縫 TR 只用高低價、跨縫報酬 NaN）、SNR／ATR%／翻轉率／年度 P80 分位等 16 個策略欄位、400 天暖身讓 MA200／12 個月動能於顯示區左緣成形。
- **量能研判**：量比（vs 近 20 個非處置日均量）為主、Z-Score 為輔；**相對大盤 Alpha**：Beta 調整後 20 日超額報酬。
- **處置股**：live 清單 ∪ 本地累積日曆（`disposition_calendar.csv`，已解除的歷史處置保留供回測剔除）；K 線標出處置區間並停用該期間量能結論。

### 離線工具（`tools/`）

```bash
python tools/backtest_tailwind.py --start 2025-06-01 --end 2026-07-09   # 三份回測報告（磁碟快取續傳）
python tools/sweep_limitup.py     # 鎖漲停門檻敏感度掃描（重用回測快取）
python tools/sweep_mabull.py      # 多頭排列進場濾網掃描
```

回測快取存於 `backtest_cache/{start}_{end}/`，FinMind 限流中斷後**再跑一次即補齊**；輸出 `backtest_trades.csv` / `backtest_ignitions.csv` / `backtest_summary.json`（皆已 gitignore）。

---

## 專案架構

由單體腳本重構為分層套件，資料層／指標／UI 各自獨立、可單元測試：

```
app.py                          # Streamlit 入口（set_page_config、側邊欄、串接面板）
stock_config.json               # 族群設定（UI 可增刪，亦可手改）
trading_dashboard/
├── config.py                   # 常數、門檻、路徑、設定檔載入/驗證/存檔、logging
├── indicators.py               # enrich(_heavy) / 趨勢 / Alpha / 量能 / RSI / ATR / 長線 / 動能
├── vol_framework.py            # 還原股價 + 處置剔除法策略欄位（docs/volatility_framework.md）
├── strategy.py                 # 紅K順風車狀態機；點火判定唯一事實來源
├── signals.py                  # 交易一致性訊號（6 買訊 + 5 賣警）
├── backtest.py                 # 回測引擎純函式（三份報告的計算核心）
├── market.py                   # 交易日推算、全市場成交值排行（上市/上櫃並行）
├── leaderboard.py              # 熱錢排行帳本讀寫 + 舊版相容遷移
├── history.py                  # 排行榜每日快照、雷達訊號歷史、前瞻報酬
├── persistence.py              # 原子寫入、CSV 匯出 bytes
├── data_sources/
│   ├── finmind.py              # 個股/指數日線（400 天暖身 + 全套策略欄位管線）
│   ├── twse.py  tpex.py        # 上市 / 上櫃成交值排行
│   ├── turnover.py  http.py    # 共用工具 / 共用 Session（傳輸層重試）
│   ├── disposition.py          # 處置股清單 + 本地日曆累積
│   └── prefetch.py             # 多檔平行預抓（執行緒池 + 去重）
└── ui/
    ├── components.py           # 徽章、漲跌標籤、rangebreaks 快取
    ├── leaderboard_panel.py    # 熱錢排行（目前排行 / 歷史熱圖）
    ├── today_panel.py          # 今日『紅K順風車』點火掃描
    ├── weather_panel.py        # 大盤氣象台
    ├── radar_panel.py          # 選股雷達（掃描 / 訊號歷史）
    ├── momentum_panel.py       # 族群動能
    ├── chart_grid.py           # K 線網格牆（含順風車覆蓋層）
    └── config_editor.py        # 側欄族群管理
tools/                          # 離線 CLI：回測 + 兩支門檻掃描
docs/volatility_framework.md    # 波動率框架規範文件（策略門檻的單一事實來源）
tests/                          # pytest 單元測試（239+）
```

---

## 環境需求

- **Python 3.10 – 3.13**（使用標準庫 `zoneinfo`；Windows 需 `tzdata`，已列於 `requirements.txt`）。
  > ⚠️ **請勿使用 Python 3.14**：Streamlit 1.58 的伺服器以 Starlette/Uvicorn/anyio 提供前端靜態檔，在 3.14 下會因 async 偵測不相容而對所有 `/static/*.js` 回 500（畫面變成 `Internal Server Error` 或 `Failed to fetch dynamically imported module`）。請改用 3.12（建議）。
- 可連線至 FinMind / 證交所 / 櫃買中心的網路環境。

## 安裝

```bash
# 用受支援的 Python 版本建立虛擬環境（Windows 可用 py 啟動器指定 3.12）
py -3.12 -m venv .venv          # Windows
# python3.12 -m venv .venv       # macOS / Linux

.venv\Scripts\activate          # Windows
# source .venv/bin/activate       # macOS / Linux

pip install -r requirements.txt
```

## 啟動

啟用虛擬環境後，直接啟動（預設開在 http://localhost:8501）：

```bash
streamlit run app.py
```

若未啟用 venv，可直接用 venv 內的 Python 執行——這也是 `.claude/launch.json` 實際使用的完整指令：

```bash
# Windows
.venv\Scripts\python -m streamlit run app.py --server.port 8501 --server.headless true

# macOS / Linux
.venv/bin/python -m streamlit run app.py --server.port 8501 --server.headless true
```

> 若提示 `Port 8501 is in use`，表示已有舊的 Streamlit 行程占用該埠；先結束它（Windows：`taskkill /F /PID <PID>`）或改用 `--server.port 8502` 即可。

瀏覽器開啟後：於左側側邊欄選擇觀測族群、網格欄數、觀測天數與副圖內容；展開上方面板可刷新熱錢排行或執行選股雷達。

---

## 設定檔 `stock_config.json`

結構為 **族群名稱 → { 代號: 顯示名稱 }**。代號後綴 `.TW` 為上市、`.TWO` 為上櫃；大盤指數用 `TAIEX`：

```json
{
  "PCB": {
    "2383.TW": "台光電",
    "8358.TWO": "金居"
  },
  "散熱": {
    "3017.TW": "奇鋐",
    "3324.TWO": "雙鴻"
  }
}
```

啟動時會驗證結構：頂層須為非空物件、每個族群須為非空的「字串→字串」對應，否則以清楚訊息中止（fail fast）。

## 產出檔 `turnover_leaderboard.csv`

執行「刷新最新熱錢排行」後於專案根目錄產生／更新的本地帳本（已列入 `.gitignore`，不應提交）。欄位：

| 欄位 | 意義 |
|------|------|
| `stock_id` / `name` | 代號 / 名稱 |
| `cumulative_days` | 累計進入全市場成交值前 20 的天數 |
| `last_seen_date` | 最後一次進榜日期 |
| `buffer_days` | 連續掉榜緩衝計數（> 2 天即移除） |
| `market` | 上市 / 上櫃 |
| `turnover_billion` | 當日成交額（億） |

## 選用：FinMind API Token

未登入的匿名額度有速率限制，可能造成資料不全。有 FinMind 帳號時，兩種設定方式擇一（**本地檔優先**）：

1. 專案根目錄放 `finmind_token.json`（已列入 `.gitignore`，勿提交）：

   ```json
   {"api_token": "你的_token"}
   ```

2. 環境變數：

   ```bash
   # Windows (PowerShell)
   $env:FINMIND_TOKEN = "你的_token"
   # macOS / Linux
   export FINMIND_TOKEN="你的_token"
   ```

程式啟動時自動登入；都未設定則維持匿名模式。

## 本地累積資料檔

以下皆為執行期產物、已列入 `.gitignore`：`turnover_leaderboard.csv`（排行帳本）、`leaderboard_history.csv`（排行每日快照）、`signals_history.csv`（雷達訊號歷史）、`disposition_calendar.csv`（處置日曆累積——已解除的歷史處置保留供回測剔除）、`backtest_cache/` 與 `backtest_*.csv/json`（回測快取與輸出）。

---

## 測試

```bash
pip install -r requirements-dev.txt
pytest --cov=trading_dashboard --cov-report=term-missing
```

測試聚焦於純邏輯：設定檔驗證、欄位定位、民國日期解析、趨勢／量能／Alpha 研判、交易日推算、排行帳本（含舊版 CSV 遷移）。

---

## 已知限制

- 資料為**收盤後日線**，非即時報價；交易日對齊以台灣 14:30 收盤為界。
- 指標僅供研究參考，**不構成投資建議**。
- FinMind 匿名額度有限，大量掃描建議設定 `FINMIND_TOKEN`。

## 備註：目錄名稱

repo 目錄名 `tradingdashborad` 為早期拼字（board → borad），如需更正可手動 `git mv`；入口檔已更名為 `app.py`，啟動指令統一為 `streamlit run app.py`。
