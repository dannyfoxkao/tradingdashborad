import re
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import requests
import streamlit as st
from FinMind.data import DataLoader


# 初始化 FinMind
@st.cache_resource
def init_finmind():
    return DataLoader()


api = init_finmind()


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


# 🌦️ 大盤天氣濾鏡用：抓上市(加權 TAIEX)與上櫃(櫃買 TPEx)指數
# 固定 150 天回看，確保 MACD(12,26,9) 與月線(20MA) 一定算得出來，不受觀測天數影響
@st.cache_data(ttl=600)
def fetch_index_close(stock_id, start, end):
    try:
        df = api.taiwan_stock_daily(stock_id=stock_id, start_date=start, end_date=end)
        if df is None or df.empty:
            return None
        df = df.rename(columns={'close': 'Close'})
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        return df[['Close']]
    except Exception:
        return None


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
