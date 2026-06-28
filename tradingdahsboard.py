import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import json
import os
import requests
import time
import random
import csv
import io
import re
import numpy as np
from FinMind.data import DataLoader



# 1. 網頁基礎配置（純淨黑魂風）
st.set_page_config(layout="wide", page_title="全球自訂族群看盤系統 Pro")
st.markdown("""
    <style>
    .stApp { background-color: #121212; color: #FFFFFF; }
    iframe { background-color: #121212 !important; }
    </style>
    """, unsafe_allow_html=True)

# 2. 初始化 FinMind
@st.cache_resource
def init_finmind():
    return DataLoader()

api = init_finmind()

# 3. 讀取外部設定檔
CONFIG_PATH = "stock_config.json"
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        STOCKS_POOL = json.load(f)
else:
    st.error(f"找不到設定檔 {CONFIG_PATH}，請確認檔案是否存在。")
    st.stop()

# =====================================================================
# 🛠️ 核心功能一：全市場 (上市 + 上櫃) 混合成交值排行
# =====================================================================
LEADERBOARD_FILE = "turnover_leaderboard.csv"

def _col(fields: list, *keywords, default: int) -> int:
    """從 fields 陣列動態找欄位 index，找不到回傳 default"""
    for i, f in enumerate(fields):
        for kw in keywords:
            if kw in str(f):
                return i
    return default

def _is_common_stock(sid: str) -> bool:
    """只保留 4 碼純數字（普通股），排除 ETF / 槓桿反向 / 權證"""
    return len(sid) == 4 and sid.isdigit()


# ─── 引擎 A：上市 (TWSE) ────────────────────────────────
def _fetch_twse_top20(headers: dict, date_str: str):
    """
    以「成交金額(turnover value)」排序取上市前 20。
    註：MI_INDEX20 是依「成交股數(量)」排名且不含成交金額欄位，故不適用本目標；
        唯一含全市場成交金額的來源是 STOCK_DAY_ALL（現已改為 CSV 輸出）。
    """
    errors = []
    try:
        url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL?response=json&date={date_str}"
        time.sleep(random.uniform(0.3, 0.8))
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            raise Exception(f"HTTP {r.status_code}")

        r.encoding = "utf-8"
        rows = list(csv.reader(io.StringIO(r.text)))
        if len(rows) < 2:
            raise Exception("CSV 無資料列")

        header = rows[0]
        # 以表頭動態定位欄位，避免日後欄位位移
        id_col     = _col(header, "證券代號", "代號", default=1)
        name_col   = _col(header, "證券名稱", "名稱", default=2)
        amount_col = _col(header, "成交金額", "金額", default=4)

        pool = []
        for row in rows[1:]:
            if len(row) <= amount_col:
                continue
            sid = str(row[id_col]).strip()
            if not _is_common_stock(sid):   # 排除 ETF / 權證 / 槓桿反向
                continue
            try:
                amount = float(str(row[amount_col]).replace(",", ""))
                if amount > 0:
                    pool.append({
                        "stock_id": sid,
                        "name": str(row[name_col]).strip(),
                        "turnover_billion": round(amount / 1e8, 2),
                        "market": "上市"
                    })
            except:
                pass

        if not pool:
            raise Exception("pool 為空")

        pool.sort(key=lambda x: x["turnover_billion"], reverse=True)
        return pool[:20], errors

    except Exception as e:
        errors.append(f"上市-STOCK_DAY_ALL: {e}")

    return None, errors


# ─── 引擎 B：上櫃 (TPEx) ────────────────────────────────
def _fetch_tpex_top20(headers: dict, tpex_date_str: str):
    errors = []
    try:
        url = (
            "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/"
            f"stk_quote_result.php?l=zh-tw&o=json&d={tpex_date_str}"
        )
        time.sleep(random.uniform(0.5, 1.0))
        r = requests.get(url, headers=headers, timeout=10)

        if r.status_code != 200 or "application/json" not in r.headers.get("Content-Type", ""):
            raise Exception(f"HTTP {r.status_code} 或非 JSON")

        jd = r.json()
        # 新版櫃買回傳格式為 {"tables":[{"fields":[...], "data":[...]}, ...]}
        tables = jd.get("tables", [])
        table = next((t for t in tables if t.get("data")), None)
        if table is None:
            raise Exception("tables 無資料")

        data   = table.get("data", [])
        fields = table.get("fields", [])
        # 動態定位成交金額欄位（新版於 index 9：成交金額(元)）
        amount_col = _col(fields, "成交金額", "金額", default=9)

        pool = []
        for row in data:
            sid = str(row[0]).strip()
            if not _is_common_stock(sid):
                continue
            try:
                amount = float(str(row[amount_col]).replace(",", ""))
                if amount > 0:
                    pool.append({
                        "stock_id": sid,
                        "name": str(row[1]).strip(),
                        "turnover_billion": round(amount / 1e8, 2),
                        "market": "上櫃"
                    })
            except:
                pass

        if not pool:
            raise Exception("pool 為空")

        pool.sort(key=lambda x: x["turnover_billion"], reverse=True)
        return pool[:20], errors

    except Exception as e:
        errors.append(f"上櫃-TPEx: {e}")
        return None, errors


# ─── 主函式：上市上櫃分開回傳 ────────────────────────────
def fetch_market_top20_raw():
    """
    回傳:
      twse_top20  : list[dict] | None  → 上市前20
      tpex_top20  : list[dict] | None  → 上櫃前20
      date_str    : str                → 實際資料日期 YYYYMMDD
      error_logs  : list[str]
    """
    now = datetime.today()
    if now.hour < 14 or (now.hour == 14 and now.minute < 30):
        base_date = now - timedelta(days=1)
    else:
        base_date = now

    while base_date.weekday() >= 5:
        base_date -= timedelta(days=1)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://www.twse.com.tw/",
        "X-Requested-With": "XMLHttpRequest",
    }

    check_date    = base_date
    current_delay = 2.0
    all_errors    = []

    for attempt in range(4):
        date_str      = check_date.strftime("%Y%m%d")
        roc_year      = check_date.year - 1911
        tpex_date_str = f"{roc_year}/{check_date.strftime('%m/%d')}"

        twse_top20, twse_err = _fetch_twse_top20(headers, date_str)
        tpex_top20, tpex_err = _fetch_tpex_top20(headers, tpex_date_str)
        all_errors.extend(twse_err + tpex_err)

        if twse_top20 or tpex_top20:
            return twse_top20, tpex_top20, date_str, all_errors

        # 全失敗 → 退回前一個交易日
        current_delay *= 1.5
        time.sleep(current_delay + random.uniform(0.5, 1.5))
        check_date -= timedelta(days=1)
        while check_date.weekday() >= 5:
            check_date -= timedelta(days=1)

    return None, None, None, all_errors

def update_leaderboard_data(today_list, current_date_str):
    if not today_list:
        return None
        
    if os.path.exists(LEADERBOARD_FILE):
        df_old = pd.read_csv(LEADERBOARD_FILE, dtype={"stock_id": str})
        if "market" not in df_old.columns:
            df_old["market"] = "上市"  # 舊數據兼容補丁
    else:
        df_old = pd.DataFrame(columns=["stock_id", "name", "cumulative_days", "last_seen_date", "buffer_days", "market"])

    today_df = pd.DataFrame(today_list)
    updated_rows = []
    today_ids = today_df["stock_id"].tolist()

    for _, row in df_old.iterrows():
        sid = row["stock_id"]
        name = row["name"]
        cum_days = int(row["cumulative_days"])
        last_date = str(row["last_seen_date"])
        buf_days = int(row["buffer_days"])
        market_val = str(row.get("market", "上市"))

        if sid in today_ids:
            t_row = today_df[today_df["stock_id"] == sid].iloc[0]
            updated_rows.append({
                "stock_id": sid, "name": name, 
                "cumulative_days": cum_days + 1, 
                "last_seen_date": current_date_str, 
                "buffer_days": 0,
                "market": t_row["market"],
                "turnover_billion": t_row["turnover_billion"]
            })
        else:
            if last_date != current_date_str:
                buf_days += 1
            if buf_days <= 2:
                updated_rows.append({
                    "stock_id": sid, "name": name, 
                    "cumulative_days": cum_days, 
                    "last_seen_date": last_date, 
                    "buffer_days": buf_days,
                    "market": market_val,
                    "turnover_billion": 0.0
                })

    old_ids = df_old["stock_id"].tolist() if not df_old.empty else []
    for _, row in today_df.iterrows():
        sid = row["stock_id"]
        if sid not in old_ids:
            updated_rows.append({
                "stock_id": sid, "name": row["name"], 
                "cumulative_days": 1, 
                "last_seen_date": current_date_str, 
                "buffer_days": 0,
                "market": row["market"],
                "turnover_billion": row["turnover_billion"]
            })

    df_new = pd.DataFrame(updated_rows)
    df_new.to_csv(LEADERBOARD_FILE, index=False, encoding="utf-8")
    return df_new

# =====================================================================
# 🖥️ UI：熱錢霸榜排行看板 (雙拼版)
# =====================================================================
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
            st.dataframe(df_disp, use_container_width=True)
        else:
            st.info("本地帳本目前為空，請於下個交易日收盤後再次刷新嘗試對齊。")
    else:
        st.info("本地尚無資料庫紀錄。")

st.markdown("---")

# =====================================================================
# 🖥️ UI：自訂板塊 K 線網格牆 (Pro 級量化指標升級版)
# =====================================================================
st.sidebar.header("⚙️ 專業級看盤監控")
group_choice = st.sidebar.selectbox("選擇觀測族群", list(STOCKS_POOL.keys()))

st.title(f"🖥️ 監控板塊：{group_choice}")

grid_cols = st.sidebar.slider("每行顯示圖表數 (網格欄數)", min_value=1, max_value=4, value=3)
time_window = st.sidebar.slider("觀測天數", min_value=30, max_value=365, value=120)

st.sidebar.markdown("---")
st.sidebar.header("📊 指標配置")
sub_chart_type = st.sidebar.selectbox(
    "副圖顯示內容", 
    ["成交量", "成交金額 (估算)", "量 + 金額雙對比"]
)

end_date = datetime.today()
start_date = end_date - timedelta(days=time_window)
start_str = start_date.strftime("%Y-%m-%d")
end_str = end_date.strftime("%Y-%m-%d")

# 👑 全局抓取大盤作為 Alpha 計算基準
@st.cache_data(ttl=600)
def fetch_benchmark_data(start, end):
    try:
        df = api.taiwan_stock_daily(stock_id="TAIEX", start_date=start, end_date=end)
        if df is not None and not df.empty:
            df = df.rename(columns={'close': 'Close'})
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            return df[['Close']]
        return None
    except:
        return None

benchmark_df = fetch_benchmark_data(start_str, end_str)

# 👮 抓取「處置股」清單（上市 TWSE + 上櫃 TPEx）
# 處置期間改分盤集合競價(5分/20分撮合)、常預收款券/暫停當沖 → 量能被機械性壓縮、不可比，
# 故用於：① 標記處置中 ② 量能基準排除處置日 ③ K 線標出處置區間
@st.cache_data(ttl=3600)
def fetch_disposition_map():
    """
    回傳 {stock_id: [{'start':Timestamp, 'end':Timestamp, 'measure':str, 'market':str}, ...]}
    """
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    result = {}

    def _add(sid, start, end, measure, market):
        if not sid or start is None or end is None:
            return
        result.setdefault(sid, []).append(
            {"start": start, "end": end, "measure": measure, "market": market}
        )

    def _parse_period(s):
        """處置起訖日期：支援 '115/06/29～115/07/10' 與 '1150629~1150710' 兩種民國格式"""
        s = str(s)
        m = re.findall(r'(\d{2,3})/(\d{1,2})/(\d{1,2})', s)      # 帶斜線 (TWSE)
        if len(m) >= 2:
            (y1, mo1, d1), (y2, mo2, d2) = m[0], m[1]
            return (pd.Timestamp(int(y1) + 1911, int(mo1), int(d1)),
                    pd.Timestamp(int(y2) + 1911, int(mo2), int(d2)))
        m = re.findall(r'(\d{7})', s)                            # 緊湊 7 碼 (TPEx)
        if len(m) >= 2:
            c = lambda x: pd.Timestamp(int(x[:3]) + 1911, int(x[3:5]), int(x[5:7]))
            return c(m[0]), c(m[1])
        return None, None

    def _measure(text):
        text = str(text)
        if "20分" in text or "二十分" in text:
            return "20分撮合"
        if "5分" in text or "五分" in text:
            return "5分撮合"
        return "分盤撮合"

    # ── 上市 TWSE ──
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/announcement/punish",
                         headers=headers, timeout=12)
        for it in r.json():
            sid = str(it.get("Code", "")).strip()
            s, e = _parse_period(it.get("DispositionPeriod", ""))
            _add(sid, s, e,
                 _measure(str(it.get("DispositionMeasures", "")) + str(it.get("Detail", ""))),
                 "上市")
    except Exception:
        pass

    # ── 上櫃 TPEx ──
    try:
        r = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_disposal_information",
                         headers=headers, timeout=12)
        for it in r.json():
            sid = str(it.get("SecuritiesCompanyCode", "")).strip()
            s, e = _parse_period(it.get("DispositionPeriod", ""))
            _add(sid, s, e, _measure(it.get("DisposalCondition", "")), "上櫃")
    except Exception:
        pass

    return result

disposition_map = fetch_disposition_map()

@st.cache_data(ttl=600)
def fetch_finmind_data(ticker, start, end):
    try:
        stock_id = ticker.split('.')[0].strip()
        df = api.taiwan_stock_daily(stock_id=stock_id, start_date=start, end_date=end)
        
        if df is None or df.empty:
            return None
            
        df = df.rename(columns={
            'open': 'Open', 'max': 'High', 'min': 'Low', 'close': 'Close',
            'Trading_Volume': 'Volume', 'Trading_money': 'Turnover'
        })
        
        if 'Turnover' not in df.columns:
            df['Turnover'] = df['Close'] * df['Volume'] if 'Volume' in df.columns else 0
        if 'Volume' not in df.columns:
            if 'Turnover' in df.columns and df['Turnover'].sum() > 0:
                df['Volume'] = df['Turnover'] / df['Close']
            else:
                df['Volume'] = 1000000 
                
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        
        # 價格均線
        df['MA5'] = df['Close'].rolling(5).mean()
        df['MA10'] = df['Close'].rolling(10).mean()
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA60'] = df['Close'].rolling(60).mean()
        # 量能/金額均線
        df['Vol_MA5'] = df['Volume'].rolling(5).mean()
        df['Vol_MA20'] = df['Volume'].rolling(20).mean()
        df['Turn_MA5'] = df['Turnover'].rolling(5).mean()
        df['Turn_MA20'] = df['Turnover'].rolling(20).mean()
        df['Turn_MA60'] = df['Turnover'].rolling(60).mean()
        
        # 👑 核心升級：計算量能標準差 (Z-Score)
        df['Vol_Std20'] = df['Volume'].rolling(20).std()
        
        return df
    except Exception as e:
        return None

# =====================================================================
# 🧠 共用研判函式（網格牆與選股雷達共用同一套邏輯，確保不分歧）
# =====================================================================
def classify_trend(df):
    """
    回傳趨勢分類 dict：{label, bg, icon, rank, slope}；rank 越小越強(0=強多)。
    資料不足回傳 None。
    """
    if df is None or len(df) < 6:
        return None
    latest = df.iloc[-1]
    c, m5, m20, m60 = latest['Close'], latest['MA5'], latest['MA20'], latest['MA60']
    # 排列分 0~3（MA60 未成形時該比較為 False，自動只計短中期）
    align = int(c > m5) + int(m5 > m20) + int(m20 > m60)
    ma20_ref = df['MA20'].iloc[-6]
    slope = ((m20 - ma20_ref) / ma20_ref * 100) if (pd.notna(ma20_ref) and ma20_ref > 0) else 0.0

    if align == 3 and slope > 0:
        return {"label": "強多",      "bg": "#2e7d32", "icon": "🟢", "rank": 0, "slope": slope}
    elif align >= 2 and slope >= -0.1:
        return {"label": "震盪(偏多)", "bg": "#f57c00", "icon": "🟡", "rank": 1, "slope": slope}
    elif align <= 1 and slope < 0:
        return {"label": "弱勢",      "bg": "#b71c1c", "icon": "🔴", "rank": 4, "slope": slope}
    elif slope >= 0:
        return {"label": "震盪(中性)", "bg": "#546e7a", "icon": "⚪", "rank": 3, "slope": slope}
    else:
        return {"label": "震盪(偏空)", "bg": "#455a64", "icon": "🟠", "rank": 2, "slope": slope}

def compute_alpha(df, bench):
    """Beta 調整後 20 日超額報酬，回傳 (alpha_val, beta)；資料不足回傳 (None, None)。"""
    if bench is None or df is None or len(bench) < 21:
        return None, None
    joined = df[['Close']].join(
        bench[['Close']].rename(columns={'Close': 'Bench'}), how='inner'
    ).dropna()
    if len(joined) < 21:
        return None, None
    win = joined.iloc[-21:]
    s_ret = win['Close'].pct_change().dropna()
    b_ret = win['Bench'].pct_change().dropna()
    var_b = b_ret.var()
    beta = (np.cov(s_ret, b_ret)[0, 1] / var_b) if var_b > 0 else 1.0
    beta = float(np.clip(beta, 0.0, 3.0))
    s_cum = win['Close'].iloc[-1] / win['Close'].iloc[0] - 1
    b_cum = win['Bench'].iloc[-1] / win['Bench'].iloc[0] - 1
    return (s_cum - beta * b_cum) * 100, beta

def _is_in_disposition(stock_id, ref_date):
    """該股在 ref_date 是否仍處於處置期"""
    ref = pd.Timestamp(ref_date).normalize()
    return any(w["start"] <= ref <= w["end"] for w in disposition_map.get(stock_id, []))

# --- 嚴格橫向二維排版渲染 ---
selected_stocks = STOCKS_POOL[group_choice]
tickers = list(selected_stocks.keys())

# =====================================================================
# 📈 選股雷達：整理「強多 / 震盪偏多」清單
# =====================================================================
with st.expander("📈 強多／震盪偏多 選股雷達", expanded=False):
    c1, c2 = st.columns([3, 1])
    with c1:
        scan_scope = st.radio("掃描範圍", ["本族群", "全部族群"], horizontal=True, key="scan_scope")
    with c2:
        run_scan = st.button("🛰️ 開始掃描")

    if run_scan:
        if scan_scope == "本族群":
            scope_items = [(group_choice, t, n) for t, n in selected_stocks.items()]
        else:
            scope_items = [(g, t, n) for g, d in STOCKS_POOL.items() for t, n in d.items()]

        rows = []
        prog = st.progress(0.0, text="掃描中...")
        total = max(len(scope_items), 1)
        for k, (g, tk, nm) in enumerate(scope_items):
            cid = tk.split('.')[0].strip()
            d = fetch_finmind_data(cid, start_str, end_str)
            ti = classify_trend(d)
            if ti and ti["label"] in ("強多", "震盪(偏多)"):
                latest = d.iloc[-1]
                prev = d.iloc[-2]
                chg = ((latest['Close'] - prev['Close']) / prev['Close'] * 100) if prev['Close'] else 0.0
                av, _ = compute_alpha(d, benchmark_df)
                in_disp = _is_in_disposition(cid, d.index[-1])
                rows.append({
                    "族群": g,
                    "代號": cid,
                    "名稱": nm,
                    "趨勢": f'{ti["icon"]} {ti["label"]}',
                    "收盤": round(float(latest['Close']), 2),
                    "今日%": round(chg, 2),
                    "α%": round(av, 1) if av is not None else None,
                    "MA20斜率%": round(ti["slope"], 2),
                    "處置": "⛔" if in_disp else "",
                    "_rank": ti["rank"],
                })
            prog.progress((k + 1) / total, text=f"掃描中... {k+1}/{total}")
        prog.empty()

        if rows:
            res = (pd.DataFrame(rows)
                   .sort_values(["_rank", "α%"], ascending=[True, False], na_position="last")
                   .drop(columns="_rank")
                   .reset_index(drop=True))
            n_strong = sum(1 for r in rows if r["趨勢"].startswith("🟢"))
            n_mid = len(rows) - n_strong
            st.success(f"掃描完成：共 {len(res)} 檔（🟢 強多 {n_strong}／🟡 震盪偏多 {n_mid}）｜由強至弱排序")
            st.dataframe(res, use_container_width=True, hide_index=True)
        else:
            st.info("本次掃描沒有符合『強多／震盪偏多』的標的。")
    else:
        st.caption("選擇範圍後按「開始掃描」，將篩出趨勢為 🟢強多 / 🟡震盪偏多 的個股並依強度排序。")

for i in range(0, len(tickers), grid_cols):
    row_tickers = tickers[i:i+grid_cols]
    cols = st.columns(grid_cols)  
    
    for idx, ticker in enumerate(row_tickers):
        name = selected_stocks[ticker]
        clean_id = ticker.split('.')[0].strip()
        df = fetch_finmind_data(clean_id, start_str, end_str)
        
        if df is None or len(df) < 5:
            continue
            
        with cols[idx]:
            # === 處置股研判（影響量能可信度）===
            disp_windows = disposition_map.get(clean_id, [])
            last_date = df.index[-1].normalize()
            # 標記 df 中落在任一處置區間內的交易日
            disp_mask = pd.Series(False, index=df.index)
            for w in disp_windows:
                disp_mask |= (df.index.normalize() >= w["start"]) & (df.index.normalize() <= w["end"])
            in_disp = bool(disp_mask.iloc[-1])   # 最新交易日是否仍在處置中
            active_w = next((w for w in disp_windows if w["start"] <= last_date <= w["end"]), None)
            disp_html = ""
            if active_w is not None:
                disp_html = (
                    f'<span style="background:#6a1b9a; color:#fff; padding:2px 6px; '
                    f'border-radius:4px; font-size:11px; margin-left:4px;">'
                    f'⛔處置 {active_w["measure"]}·至{active_w["end"].strftime("%m/%d")}</span>'
                )

            # === 計算 Pro 級即時戰情指標 ===
            try:
                latest = df.iloc[-1]
                prev = df.iloc[-2]

                # 計算漲跌
                price_diff = latest['Close'] - prev['Close']
                price_pct = (price_diff / prev['Close']) * 100
                
                if price_diff > 0:
                    price_html = f'<span style="color:#ff5252; font-weight:bold; font-size:14px; margin-left:8px;">{latest["Close"]:.2f} (+{price_diff:.2f}  +{price_pct:.2f}%)</span>'
                elif price_diff < 0:
                    price_html = f'<span style="color:#4caf50; font-weight:bold; font-size:14px; margin-left:8px;">{latest["Close"]:.2f} ({price_diff:.2f}  {price_pct:.2f}%)</span>'
                else:
                    price_html = f'<span style="color:#9e9e9e; font-weight:bold; font-size:14px; margin-left:8px;">{latest["Close"]:.2f} (0.00  0.00%)</span>'

                
                # ── 1. 趨勢研判（共用 classify_trend，與選股雷達同邏輯）──
                ti = classify_trend(df)
                if ti:
                    trend_html = f'<span style="background:{ti["bg"]}; color:#fff; padding:2px 6px; border-radius:4px; font-size:11px; margin-left:4px;">{ti["icon"]} {ti["label"]}</span>'
                else:
                    trend_html = ""

                # ── 2. 量能研判：量比(倍數)為主、Z-Score 為輔 ──
                if in_disp:
                    # 處置中改分盤撮合(5分/20分)、常預收款券/暫停當沖 → 量被機械性壓縮、不可比，
                    # 停用爆量/縮量結論，避免假訊號（解除後自動恢復）
                    vol_html = (
                        '<span style="background:#6a1b9a; color:#fff; padding:2px 6px; '
                        'border-radius:4px; font-size:11px; margin-left:4px;">⛔ 分盤·量能失真</span>'
                    )
                else:
                    # 基準＝最近 20 個「非處置」交易日(不含今日)均量；
                    # 排除處置日可避免基準污染，以及處置解除當天的假性爆量
                    nondisp_vol = df['Volume'][~disp_mask].iloc[:-1]
                    base_vol = nondisp_vol.tail(20).mean() if len(nondisp_vol) >= 1 else np.nan
                    vr = (latest['Volume'] / base_vol) if (pd.notna(base_vol) and base_vol > 0) else 1.0
                    if pd.notna(latest['Vol_Std20']) and latest['Vol_Std20'] > 0:
                        z_score = (latest['Volume'] - latest['Vol_MA20']) / latest['Vol_Std20']
                    else:
                        z_score = 0.0

                    if vr >= 2.5 or z_score >= 2.0:
                        vol_label, vol_bg, vol_icon = f"爆量 x{vr:.1f}", "#c62828", "💥"
                    elif vr >= 1.5:
                        vol_label, vol_bg, vol_icon = f"放量 x{vr:.1f}", "#ef6c00", "🔆"
                    elif vr < 0.7 or z_score <= -1.0:
                        vol_label, vol_bg, vol_icon = f"縮量 x{vr:.1f}", "#0277bd", "🧊"
                    else:
                        vol_label, vol_bg, vol_icon = f"常態 x{vr:.1f}", "#424242", "💧"
                    vol_html = f'<span style="background:{vol_bg}; color:#fff; padding:2px 6px; border-radius:4px; font-size:11px; margin-left:4px;">{vol_icon} {vol_label}</span>'

                # ── 3. 相對大盤 Alpha：Beta 調整後的 20 日超額報酬(共用 compute_alpha) ──
                alpha_html = ""
                alpha_val, beta = compute_alpha(df, benchmark_df)
                if alpha_val is not None:
                    if alpha_val >= 5:
                        a_bg, a_icon = "#558b2f", "🚀"            # 顯著領先
                    elif alpha_val > 0:
                        a_bg, a_icon = "#827717", "🌟"            # 領先
                    elif alpha_val > -5:
                        a_bg, a_icon = "#37474f", "⚠️"            # 略落後
                    else:
                        a_bg, a_icon = "#b71c1c", "🐢"            # 顯著落後
                    sign = "+" if alpha_val >= 0 else ""
                    alpha_html = f'<span style="background:{a_bg}; color:#fff; padding:2px 6px; border-radius:4px; font-size:11px; margin-left:4px;">{a_icon} α {sign}{alpha_val:.1f}% (β{beta:.1f})</span>'
            except:
                price_html, trend_html, vol_html, alpha_html = "", "", "", ""

            # 頂部戰情儀表板 HTML
            sub_label = "額MA" if sub_chart_type == "成交金額 (估算)" else "量MA"
            st.markdown(f"""
            <div style="padding: 8px 10px; background-color: #1e1e1e; border-radius: 6px; border-left: 4px solid #4fc3f7; margin-bottom: 5px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                    <div>
                        <b style="color: #FFFFFF; font-size: 14px;">{clean_id} {name}</b>
                        {price_html}
                    </div>
                    <div>{disp_html}{trend_html}{vol_html}{alpha_html}</div>
                </div>
                <div style="font-size: 11px; color: #888888; font-family: monospace;">
                    價MA: <span style="color:#ffa726; margin-right:5px;">●5</span><span style="color:#ec407a; margin-right:5px;">●10</span><span style="color:#29b6f6; margin-right:5px;">●20</span><span style="color:#ab47bc; margin-right:12px;">●60</span>
                    {sub_label}: <span style="color:#ffa726; margin-right:5px;">●5</span><span style="color:#29b6f6; margin-right:5px;">●20</span><span style="color:#ab47bc; margin-right:5px;">●60</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # === Plotly 圖表渲染 ===
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.70, 0.30])
            div_factor = 100000000
            display_vol = df['Volume'] / 1000
            vol_colors = ['#ef5350' if c >= o else '#26a69a' for o, c in zip(df['Open'], df['Close'])]
            
            # K 線與均線
            fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], increasing_line_color='#ef5350', decreasing_line_color='#26a69a', increasing_fillcolor='#ef5350', decreasing_fillcolor='#26a69a'), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['MA5'], mode='lines', line=dict(color='#ffa726', width=1.2)), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['MA10'], mode='lines', line=dict(color='#ec407a', width=1.2)), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], mode='lines', line=dict(color='#29b6f6', width=1.2)), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['MA60'], mode='lines', line=dict(color='#ab47bc', width=1.2)), row=1, col=1)
            
            # 副圖
            if sub_chart_type == "成交量" or sub_chart_type == "量 + 金額雙對比":
                fig.add_trace(go.Bar(x=df.index, y=display_vol, marker_color=vol_colors, opacity=0.4), row=2, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['Vol_MA5']/1000 if 'Vol_MA5' in df else df['Vol_MA20']/1000, mode='lines', line=dict(color='#ffa726', width=1.0)), row=2, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['Vol_MA20']/1000, mode='lines', line=dict(color='#29b6f6', width=1.0)), row=2, col=1)
                
            if sub_chart_type == "成交金額 (估算)":
                fig.add_trace(go.Bar(x=df.index, y=df['Turnover'] / div_factor, marker_color='#455a64', opacity=0.5), row=2, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['Turn_MA5'] / div_factor, mode='lines', line=dict(color='#ffa726', width=1.0)), row=2, col=1)
                fig.add_trace(go.Scatter(x=df.index, y=df['Turn_MA20'] / div_factor, mode='lines', line=dict(color='#29b6f6', width=1.0)), row=2, col=1)
                
            if sub_chart_type == "量 + 金額雙對比":
                fig.add_trace(go.Scatter(x=df.index, y=df['Turnover'] / div_factor, mode='lines', line=dict(color='#cfd8dc', width=1.2), yaxis="y3"), row=2, col=1)
                fig.update_layout(yaxis3=dict(overlaying="y2", side="right", showgrid=False))

            fig.update_layout(
                height=380, 
                margin=dict(l=35, r=35, t=30, b=15), 
                template="plotly_dark", 
                xaxis_rangeslider_visible=False, 
                showlegend=False, 
                hovermode="x unified"
            )
            
            # 動態去空白斷層
            missing_dates = pd.date_range(start=df.index.min(), end=df.index.max()).difference(df.index)
            missing_dates_str = missing_dates.strftime('%Y-%m-%d').tolist()
            fig.update_xaxes(rangebreaks=[dict(values=missing_dates_str)])

            # ⛔ 處置期間：紫色陰影標出(量縮為分盤所致，非真實冷卻)
            for w in disp_windows:
                x0 = max(w["start"], df.index.min())
                x1 = min(w["end"], df.index.max())
                if x0 <= x1:
                    fig.add_vrect(x0=x0, x1=x1, fillcolor="#7e57c2", opacity=0.13,
                                  line_width=0, layer="below", row="all", col=1)

            st.plotly_chart(fig, width='stretch')