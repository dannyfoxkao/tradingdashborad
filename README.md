# 全球自訂族群看盤系統 Pro

一套以 [Streamlit](https://streamlit.io/) 打造的台股**族群監控看盤儀表板**。針對自訂的產業族群（PCB、光通、散熱、記憶體、軍工……）批次繪製 K 線網格牆，疊加多項量化研判指標，並提供全市場（上市＋上櫃）**熱錢成交值排行**的長期累積帳本與**強多／震盪偏多選股雷達**。

資料來源為 [FinMind](https://finmindtrade.com/)（個股／大盤日線）、[證交所 TWSE](https://www.twse.com.tw/) 與 [櫃買中心 TPEx](https://www.tpex.org.tw/) 公開 API。

---

## 功能特色

| 面板 | 說明 |
|------|------|
| 🔥 **熱錢 Top 20 排行** | 抓取上市＋上櫃當日成交值前 20，寫入本地帳本 `turnover_leaderboard.csv`，累積每檔的「連續進榜天數」，並以 buffer 緩衝短暫掉榜。 |
| 📈 **選股雷達** | 對「本族群」或「全部族群」批次掃描，篩出趨勢為 🟢強多 / 🟡震盪偏多 的個股，依強度與 Alpha 排序。 |
| 🖥️ **K 線網格牆** | 自訂欄數的二維網格，每檔顯示 K 線 + 4 條均線、量能／成交金額副圖，與即時戰情徽章。 |

### 指標研判

- **趨勢分類**：依均線排列（收盤 vs MA5 / MA20 / MA60）與 MA20 斜率分為 強多 / 震盪(偏多) / 震盪(中性) / 震盪(偏空) / 弱勢；資料不足（< 21 個交易日）標示「資料不足」而非誤判。
- **量能研判**：以「量比（vs 近 20 個非處置日均量）」為主、Z-Score 為輔，分類爆量 / 放量 / 常態 / 縮量。
- **相對大盤 Alpha**：以加權指數（TAIEX）為基準，計算 **Beta 調整後的 20 日超額報酬**。
- **處置股標記**：抓取上市／上櫃處置清單，於 K 線標出處置區間（紫色陰影），並停用處置期間的量能結論（分盤撮合使量能不可比）。

---

## 專案架構

由單體腳本重構為分層套件，資料層／指標／UI 各自獨立、可單元測試：

```
app.py                          # Streamlit 入口（set_page_config、側邊欄、串接面板）
stock_config.json               # 族群設定（可自行增刪）
trading_dashboard/
├── config.py                   # 常數、門檻、路徑、設定檔載入/驗證、logging
├── indicators.py               # enrich / classify_trend / compute_alpha / classify_volume（純函式）
├── market.py                   # 交易日推算、全市場成交值排行抓取
├── leaderboard.py              # 熱錢排行帳本讀寫 + 舊版相容遷移
├── data_sources/
│   ├── finmind.py              # 個股 / 大盤日線
│   ├── twse.py  tpex.py        # 上市 / 上櫃成交值排行
│   ├── turnover.py             # TWSE/TPEx 共用工具
│   ├── disposition.py          # 處置股清單
│   └── prefetch.py             # 多檔平行預抓（執行緒池 + 去重）
└── ui/
    ├── components.py           # 徽章、漲跌標籤、rangebreaks 快取
    ├── leaderboard_panel.py    # 熱錢排行面板
    ├── radar_panel.py          # 選股雷達面板
    └── chart_grid.py           # K 線網格牆
tests/                          # pytest 單元測試
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

未登入的匿名額度有速率限制，可能造成資料不全。若有 FinMind 帳號，可設定環境變數以提高額度：

```bash
# Windows (PowerShell)
$env:FINMIND_TOKEN = "你的_token"
# macOS / Linux
export FINMIND_TOKEN="你的_token"
```

程式啟動時會自動以該 token 登入；未設定則維持匿名模式。

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
