import os
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
def _fetch_live_disposition():
    """
    向證交所/櫃買抓「當前有效」的處置清單（API 不含已解除的歷史處置）。
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


# ── 處置日曆：live API（僅列當前）＋ 本地累積快照，讓歷史回測也能剔除處置日 ──
DISPOSITION_CALENDAR = "disposition_calendar.csv"


def _load_disposition_calendar():
    """讀本地處置日曆 CSV → {stock_id: [window,...]}；不存在或壞檔回 {}。"""
    if not os.path.exists(DISPOSITION_CALENDAR):
        return {}
    try:
        cdf = pd.read_csv(DISPOSITION_CALENDAR, dtype={"stock_id": str})
    except Exception:
        return {}
    result = {}
    for _, r in cdf.iterrows():
        sid = str(r["stock_id"]).strip()
        try:
            start, end = pd.Timestamp(r["start"]), pd.Timestamp(r["end"])
        except Exception:
            continue
        if pd.isna(start) or pd.isna(end):
            continue
        result.setdefault(sid, []).append({
            "start": start, "end": end,
            "measure": str(r.get("measure", "")), "market": str(r.get("market", "")),
        })
    return result


def _save_disposition_calendar(cal):
    """把合併後的處置日曆寫回 CSV（供下次啟動累積使用）。"""
    rows = []
    for sid, wins in cal.items():
        for w in wins:
            rows.append({
                "stock_id": sid,
                "start": pd.Timestamp(w["start"]).strftime("%Y-%m-%d"),
                "end": pd.Timestamp(w["end"]).strftime("%Y-%m-%d"),
                "measure": w.get("measure", ""), "market": w.get("market", ""),
            })
    (pd.DataFrame(rows, columns=["stock_id", "start", "end", "measure", "market"])
       .sort_values(["stock_id", "start"])
       .to_csv(DISPOSITION_CALENDAR, index=False, encoding="utf-8"))


def _merge_disposition(base, extra):
    """合併兩份 {sid:[win]}，以 (start,end) 去重。"""
    out = {sid: list(wins) for sid, wins in base.items()}
    for sid, wins in extra.items():
        seen = {(pd.Timestamp(w["start"]), pd.Timestamp(w["end"])) for w in out.get(sid, [])}
        for w in wins:
            key = (pd.Timestamp(w["start"]), pd.Timestamp(w["end"]))
            if key not in seen:
                out.setdefault(sid, []).append(w)
                seen.add(key)
    return out


@st.cache_data(ttl=3600)
def fetch_disposition_map():
    """
    回傳合併後的處置日曆 {stock_id: [window,...]}＝本地累積日曆 ∪ 今日 live 快照，
    並把最新結果寫回本地日曆（每次 cache miss 累積一次），讓已解除的歷史處置也保留。
    """
    live = _fetch_live_disposition()
    merged = _merge_disposition(_load_disposition_calendar(), live)
    try:
        _save_disposition_calendar(merged)
    except Exception:
        pass
    return merged


def _rsi(close, period=14):
    """Wilder RSI(14)：0~100，>70 過熱、<30 過冷。"""
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    roll_up = up.ewm(alpha=1 / period, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / period, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _atr(df, period=14):
    """ATR(14)：平均真實區間，衡量波動度（不預測方向，用於風控/停損距離）。"""
    high, low, close = df['High'], df['Low'], df['Close']
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _back_adjust(df):
    """
    自製還原股價：台股 ±10% 日限，收盤對收盤 |漲跌| > ~12% 必為除權/分割/資料異常，
    視為公司行為 → 將該事件日「之前」的 OHLC 乘上跳空比例 g（成交量除以 g）使序列連續。
    小額現金股息(日限內)不調整，影響甚微；可修掉分割造成的假暴跌（如國巨、0050）。
    """
    if df is None or len(df) < 2 or 'Close' not in df.columns:
        return df
    close = df['Close'].to_numpy(float)
    n = len(close)
    adj = np.ones(n)
    for i in range(1, n):
        c0, c1 = close[i - 1], close[i]
        if c0 > 0 and np.isfinite(c1) and np.isfinite(c0):
            g = c1 / c0
            if g < 0.88 or g > 1.13:          # 超出日限 → 公司行為/分割
                adj[:i] *= g
    if (adj != 1).any():
        for c in ('Open', 'High', 'Low', 'Close'):
            if c in df.columns:
                df[c] = df[c].to_numpy(float) * adj
        if 'Volume' in df.columns:            # 分割使股數放大 → 還原前期量以可比
            df['Volume'] = df['Volume'].to_numpy(float) / np.where(adj == 0, 1.0, adj)
    return df


def _apply_vol_framework(df, stock_id):
    """
    計算「波動率框架」策略欄位，並套用處置期【剔除法】(volatility_framework.md §5)：
      ① 整段移除處置交易日、時間軸縫合
      ② 接縫日 TR 只用當日高低價（不用前收，避免假跳空）
      ③ 跨縫日報酬設 NaN、rolling 以 min_periods 跳過
    於暖身資料上計算（滾動一年百分位才成形），再對齊回完整索引（處置日為 NaN）。
    """
    idx = df.index
    windows = fetch_disposition_map().get(str(stock_id), [])
    disp_mask = pd.Series(False, index=idx)
    for w in windows:
        disp_mask |= (idx.normalize() >= w["start"]) & (idx.normalize() <= w["end"])

    keep = ~disp_mask
    if int(keep.sum()) < 20:          # 剔除後資料過少 → 不剔除，避免全空
        keep = pd.Series(True, index=idx)
        disp_mask = pd.Series(False, index=idx)
    clean = df[keep]

    # 接縫偵測：clean 相鄰列在「原始序列」是否跳號（跳號=中間被剔除=接縫；第一列亦視為接縫）
    pos = np.where(keep.to_numpy())[0]
    is_seam = np.ones(len(pos), dtype=bool)
    is_seam[1:] = pos[1:] != pos[:-1] + 1
    seam = pd.Series(is_seam, index=clean.index)

    H, L, C, V = clean['High'], clean['Low'], clean['Close'], clean['Volume']
    prev_c = C.shift(1)
    tr = pd.concat([(H - L), (H - prev_c).abs(), (L - prev_c).abs()], axis=1).max(axis=1)
    tr[seam] = (H - L)[seam]                        # ② 接縫日 TR 只用當日高低價

    atr5 = tr.rolling(5, min_periods=3).mean()
    atr14 = tr.rolling(14, min_periods=8).mean()
    atr5_pct = atr5 / C * 100
    atr14_pct = atr14 / C * 100

    ret1 = C.pct_change() * 100
    ret1[seam] = np.nan                             # ③ 跨縫報酬設 NaN
    ret_mean20 = ret1.rolling(20, min_periods=15).mean()
    ret_std20 = ret1.rolling(20, min_periods=15).std()
    snr_t = ret_mean20 / ret_std20.replace(0, np.nan)     # SNR＝方向純度 mean/std
    sgn = np.sign(ret1)
    flip = (sgn != sgn.shift(1)).where(ret1.notna() & ret1.shift(1).notna())
    _ern = 10
    snr_er = (C - C.shift(_ern)).abs() / \
        C.diff().abs().rolling(_ern, min_periods=6).sum().replace(0, np.nan)   # Kaufman 效率比

    out = {
        'ATR5_pct': atr5_pct, 'ATR14_pct': atr14_pct, 'ATR14_clean': atr14,
        'ATR14_pct_p80': atr14_pct.rolling(252, min_periods=60).quantile(0.80),      # 一年 P80
        'ATR14_pct_p80_120': atr14_pct.rolling(120, min_periods=40).quantile(0.80),  # 120日 P80(警示)
        'Ret1': ret1, 'RetMean20': ret_mean20, 'RetStd20': ret_std20,
        'RetStd20_p60': ret_std20.rolling(252, min_periods=60).quantile(0.60),
        'SNR_t': snr_t, 'SNR_t5': snr_t.rolling(5, min_periods=3).mean(),
        'SNR_ER': snr_er, 'FlipRate10': flip.rolling(10, min_periods=6).mean(),
        'Vol_MA20_clean': V.rolling(20, min_periods=10).mean(),
        'Close20High': (C >= C.rolling(20, min_periods=10).max()),
    }
    for k, s in out.items():
        if k == 'Close20High':                       # bool 欄位：reindex 直接補 False，避免 object 降型警告
            df[k] = s.reindex(idx, fill_value=False).astype(bool)
        else:
            df[k] = s.reindex(idx)
    df['DispDay'] = disp_mask
    return df


@st.cache_data(ttl=600)
def fetch_finmind_data(ticker, start, end, warmup_days=400):
    """
    抓日線並計算全套研判所需指標。
    為了讓 MA200 / 12 個月動能 等長週期指標在「顯示區間的第一根」就成形，
    實際多抓 warmup_days 天暖身資料，算完指標後再切回使用者要求的 [start, end] 區間顯示。
    """
    try:
        stock_id = ticker.split('.')[0].strip()
        # 往前多抓暖身資料（長均線/長動能需要足夠回看）
        fetch_start = (pd.to_datetime(start) - timedelta(days=warmup_days)).strftime('%Y-%m-%d')
        df = api.taiwan_stock_daily(stock_id=stock_id, start_date=fetch_start, end_date=end)

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
        df.sort_index(inplace=True)

        # ── 0. 還原股價：修掉除權/分割造成的假跳空（未還原資料源的必要前處理）──
        df = _back_adjust(df)

        # ── 1. 價格均線（含長線趨勢濾網 120/200）──
        for w in (5, 10, 20, 60, 120, 200):
            df[f'MA{w}'] = df['Close'].rolling(w).mean()
        # 量能/金額均線
        df['Vol_MA5'] = df['Volume'].rolling(5).mean()
        df['Vol_MA20'] = df['Volume'].rolling(20).mean()
        df['Turn_MA5'] = df['Turnover'].rolling(5).mean()
        df['Turn_MA20'] = df['Turnover'].rolling(20).mean()
        df['Turn_MA60'] = df['Turnover'].rolling(60).mean()
        # 👑 量能標準差 (Z-Score)
        df['Vol_Std20'] = df['Volume'].rolling(20).std()

        # ── 2. 動能 / Momentum：RSI + 時間序列報酬(約 1/3/6/12 個月) ──
        df['RSI14'] = _rsi(df['Close'], 14)
        df['Ret_20'] = df['Close'].pct_change(20) * 100     # ~1 個月
        df['Ret_60'] = df['Close'].pct_change(60) * 100     # ~3 個月
        df['Ret_120'] = df['Close'].pct_change(120) * 100   # ~6 個月
        df['Ret_240'] = df['Close'].pct_change(240) * 100   # ~12 個月

        # ── 3. 波動度 / ATR：風控停損距離 ──
        df['ATR14'] = _atr(df, 14)

        # ── 3b. 策略「紅K順風車」波動框架欄位（含處置期剔除法，見 volatility_framework.md §5）──
        df = _apply_vol_framework(df, stock_id)

        # ── 4. 支撐壓力 / 前高前低：用「到前一日為止」的 N 日極值(shift(1) 避免看到未來) ──
        for w in (20, 60):
            df[f'PriorHigh{w}'] = df['High'].rolling(w).max().shift(1)
            df[f'PriorLow{w}'] = df['Low'].rolling(w).min().shift(1)

        # 指標算完後切回顯示區間（長均線/長動能已於暖身期成形）
        df = df[df.index >= pd.to_datetime(start)]
        if df.empty:
            return None

        return df
    except Exception as e:
        return None
