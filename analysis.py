import numpy as np
import pandas as pd


# =====================================================================
# 🧠 共用研判函式（網格牆與選股雷達共用同一套邏輯，確保不分歧）
# =====================================================================
def classify_trend(df):
    """
    回傳趨勢分類 dict：{label, bg, icon, rank, slope}；rank 越小越強(0=強多)。
    除月線(MA20)斜率外，另計短均(MA5/MA10)斜率，用「月線 vs 季線」的結構位置
    把轉折點切成兩個獨立標籤：
      🌱 底部翻揚＝空頭結構(月線<季線)但短均同步上彎、站回 5 日、月線止跌
      🥀 頭部鈍化＝多頭結構(月線>季線)但短均同步下彎、月線動能熄火
    資料不足回傳 None。
    """
    if df is None or len(df) < 6:
        return None
    latest = df.iloc[-1]
    c, m5, m20, m60 = latest['Close'], latest['MA5'], latest['MA20'], latest['MA60']
    # 排列分 0~3（MA60 未成形時該比較為 False，自動只計短中期）
    align = int(c > m5) + int(m5 > m20) + int(m20 > m60)

    def _slope(col, lookback):
        """col 均線從 lookback 根前到現在的 % 變化；資料不足或無效回 0.0"""
        if len(df) < lookback + 1:
            return 0.0
        ref = df[col].iloc[-1 - lookback]
        cur = df[col].iloc[-1]
        if pd.notna(ref) and ref > 0 and pd.notna(cur):
            return (cur - ref) / ref * 100
        return 0.0

    slope   = _slope('MA20', 5)   # 月線斜率（原邏輯，5 根回看）
    slope5  = _slope('MA5', 3)    # 五日線斜率（短均，3 根回看）
    slope10 = _slope('MA10', 3)   # 十日線斜率
    short_up   = slope5 > 0 and slope10 > 0   # 短均同步上彎
    short_down = slope5 < 0 and slope10 < 0   # 短均同步下彎
    above_season = pd.notna(m60) and m20 > m60  # 多頭結構：月線在季線上
    below_season = pd.notna(m60) and m20 < m60  # 空頭結構：月線在季線下

    # 1. 強多：完美多排 + 月線上彎
    if align == 3 and slope > 0:
        return {"label": "強多",      "bg": "#2e7d32", "icon": "🟢", "rank": 0, "slope": slope}
    # 2. 底部翻揚：空頭結構但短均同步上彎、站回 5 日、月線止跌走平
    if below_season and short_up and c > m5 and slope >= -0.3:
        return {"label": "底部翻揚",  "bg": "#00897b", "icon": "🌱", "rank": 1, "slope": slope}
    # 3. 頭部鈍化：多頭結構但短均同步下彎、月線動能熄火(走平到微下彎)
    if above_season and align >= 2 and short_down and slope < 0.3:
        return {"label": "頭部鈍化",  "bg": "#8d6e63", "icon": "🥀", "rank": 4, "slope": slope}
    # 4. 震盪(偏多)
    if align >= 2 and slope >= -0.1:
        return {"label": "震盪(偏多)", "bg": "#f57c00", "icon": "🟡", "rank": 2, "slope": slope}
    # 5. 弱勢
    if align <= 1 and slope < 0:
        return {"label": "弱勢",      "bg": "#b71c1c", "icon": "🔴", "rank": 6, "slope": slope}
    # 6. 震盪(中性)
    if slope >= 0:
        return {"label": "震盪(中性)", "bg": "#546e7a", "icon": "⚪", "rank": 3, "slope": slope}
    # 7. 震盪(偏空)
    return {"label": "震盪(偏空)", "bg": "#455a64", "icon": "🟠", "rank": 5, "slope": slope}


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


def is_in_disposition(stock_id, ref_date, disposition_map):
    """該股在 ref_date 是否仍處於處置期"""
    ref = pd.Timestamp(ref_date).normalize()
    return any(w["start"] <= ref <= w["end"] for w in disposition_map.get(stock_id, []))


def _macd(close, fast=12, slow=26, signal=9):
    """標準 MACD：回傳 (DIF, DEA, 柱狀OSC)"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    return dif, dea, (dif - dea)


def classify_market_weather(df):
    """
    大盤天氣濾鏡：
      安全/危險區 ← 收盤 vs 月線(20MA)；風強弱 ← MACD 柱狀(OSC)方向
        安全區+風變強 → 💨強風 ｜ 安全區+風減弱 → 🌀亂流
        危險區+風變強 → 🌬️陣風 ｜ 危險區+風減弱 → 🌫️無風
    回傳 dict：{weather, icon, bg, zone, wind, action, mind}；資料不足回 None。
    """
    if df is None or len(df) < 35:
        return None
    close = df['Close'].astype(float)
    ma20 = close.rolling(20).mean()
    _, _, hist = _macd(close)
    if pd.isna(ma20.iloc[-1]) or pd.isna(hist.iloc[-1]) or pd.isna(hist.iloc[-2]):
        return None
    safe = close.iloc[-1] >= ma20.iloc[-1]      # 安全區：站上月線
    macd_up = hist.iloc[-1] > hist.iloc[-2]      # 風變強：MACD 柱狀往上

    if safe and macd_up:
        return {"weather": "強風", "icon": "💨", "bg": "#2e7d32",
                "zone": "安全區 (站上月線20MA)", "wind": "風變強 (MACD往上)",
                "action": "積極追漲 or 積極布局", "mind": "股票漲勢容易延續！短線可積極"}
    if safe and not macd_up:
        return {"weather": "亂流", "icon": "🌀", "bg": "#f57c00",
                "zone": "安全區 (站上月線20MA)", "wind": "風減弱 (MACD往下)",
                "action": "短線嚴守紀律 or 波段佈局", "mind": "股票震盪變大，嚴守紀律"}
    if (not safe) and macd_up:
        return {"weather": "陣風", "icon": "🌬️", "bg": "#0277bd",
                "zone": "危險區 (跌破月線20MA)", "wind": "風變強 (MACD往上)",
                "action": "短線試單 or 波段佈局", "mind": "股票漲勢不易延續，容易回檔"}
    return {"weather": "無風", "icon": "🌫️", "bg": "#455a64",
            "zone": "危險區 (跌破月線20MA)", "wind": "沒風 (MACD往下)",
            "action": "短線休息 or 波段佈局", "mind": "股票易跌，休息至上"}


def evaluate_signals(df, in_disp=False):
    """
    交易一致性訊號（純日線可自動化的子集；盤中/題材/情緒類屬人工 checklist 不在此）。
    回傳 dict：{buys:[...], sells:[...], bias5, bias20}；資料不足回 None。
      買訊：突破首根 / 出量 / 三日沒破低 / 多頭回測買點 / 糾結放量
      賣訊：高位大黑K / 飆股破5日未站回 / 緩漲破月線未站回 / 連兩日收弱 / 短線過熱
    """
    if df is None or len(df) < 6:
        return None
    l = df['Low']
    last, prev = df.iloc[-1], df.iloc[-2]

    def _sl(col, lb):
        if len(df) < lb + 1:
            return 0.0
        ref, cur = df[col].iloc[-1 - lb], df[col].iloc[-1]
        return (cur - ref) / ref * 100 if (pd.notna(ref) and ref > 0 and pd.notna(cur)) else 0.0

    slope20, slope5, slope10 = _sl('MA20', 5), _sl('MA5', 3), _sl('MA10', 3)
    bias5  = (last['Close'] - last['MA5'])  / last['MA5']  * 100 if (pd.notna(last['MA5'])  and last['MA5']  > 0) else 0.0
    bias20 = (last['Close'] - last['MA20']) / last['MA20'] * 100 if (pd.notna(last['MA20']) and last['MA20'] > 0) else 0.0
    vr = last['Volume'] / last['Vol_MA20'] if (pd.notna(last['Vol_MA20']) and last['Vol_MA20'] > 0) else 1.0

    buys, sells = [], []

    # B3 突破首根：今日站上月線、昨日尚未（一個波段的第一根）
    if pd.notna(last['MA20']) and pd.notna(prev['MA20']) \
            and last['Close'] > last['MA20'] and prev['Close'] <= prev['MA20']:
        buys.append("突破首根")
    # B4 出量（處置中量價失真→不計）
    if not in_disp and vr >= 1.5:
        buys.append(f"出量x{vr:.1f}")
    # B5 拉回三天沒破低：近三日低點逐日不破前低
    if l.iloc[-1] >= l.iloc[-2] >= l.iloc[-3]:
        buys.append("三日沒破低")
    # H2 均線多頭回測：三線同步向上 + 收盤貼近五日線(輕拉回)
    if slope5 > 0 and slope10 > 0 and slope20 > 0 and -3 <= bias5 <= 2:
        buys.append("多頭回測買點")
    # H3 糾結放量：均線收斂帶寬<2% + 出量
    if not in_disp and pd.notna(last['MA5']) and pd.notna(last['MA10']) and pd.notna(last['MA20']) and last['Close'] > 0:
        band = (max(last['MA5'], last['MA10'], last['MA20']) - min(last['MA5'], last['MA10'], last['MA20'])) / last['Close'] * 100
        if band < 2 and vr >= 1.5:
            buys.append("糾結放量")

    # S5 高位大黑K：高乖離 + 長黑實體
    body = (last['Open'] - last['Close']) / last['Open'] * 100 if last['Open'] > 0 else 0.0
    if last['Close'] < last['Open'] and body >= 3 and bias20 >= 8:
        sells.append("高位大黑K")
    # S7 飆股破5日未站回：強漲(月線斜率陡) + 連兩日收在5日下
    if pd.notna(last['MA5']) and pd.notna(prev['MA5']) \
            and slope20 >= 2 and prev['Close'] < prev['MA5'] and last['Close'] < last['MA5']:
        sells.append("飆股破5日未站回")
    # S8 緩漲破月線未站回：緩多(月線未明顯下彎且非飆) + 連兩日收在月線下
    if pd.notna(last['MA20']) and pd.notna(prev['MA20']) \
            and -0.5 < slope20 < 2 and prev['Close'] < prev['MA20'] and last['Close'] < last['MA20']:
        sells.append("緩漲破月線未站回")
    # S4 連兩日收弱(疑出貨，日線近似盤中緩降)
    def _weak(r):
        rng = r['High'] - r['Low']
        return r['Close'] < r['Open'] and rng > 0 and (r['Close'] - r['Low']) / rng < 0.4
    if _weak(last) and _weak(prev):
        sells.append("連兩日收弱")
    # 過熱提醒：短線乖離過大
    if bias5 >= 10:
        sells.append("短線過熱")

    return {"buys": buys, "sells": sells, "bias5": round(bias5, 1), "bias20": round(bias20, 1)}
