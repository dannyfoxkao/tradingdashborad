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


def classify_long_term(df):
    """
    ① 均線 / 趨勢濾網（判斷「現在是不是順風」）。
    取最長且已成形的均線（優先 MA200，其次 MA120、MA60）：
      🌤️ 順風＝收盤站上該長均線 且 長均線上彎（中長期趨勢健康）
      ⛈️ 逆風＝跌破長均線 且 長均線下彎
      🌥️ 中性/轉折＝站上但下彎，或跌破但上彎（易假突破、來回打臉）
    回傳 dict：{label, icon, bg, ma_used, days, slope}；資料不足回 None。
    """
    if df is None or len(df) < 6:
        return None
    latest = df.iloc[-1]
    ma_col = None
    for col in ('MA200', 'MA120', 'MA60'):
        if col in df.columns and pd.notna(latest[col]):
            ma_col = col
            break
    if ma_col is None:
        return None

    ma = latest[ma_col]
    close = latest['Close']
    lb = 20  # 長均線斜率以 20 根回看
    slope = 0.0
    if len(df) > lb:
        ref = df[ma_col].iloc[-1 - lb]
        if pd.notna(ref) and ref > 0:
            slope = (ma - ref) / ref * 100

    up = slope > 0
    above = close >= ma
    days = ma_col.replace('MA', '')
    if above and up:
        return {"label": "順風", "icon": "🌤️", "bg": "#2e7d32",
                "ma_used": ma_col, "days": days, "slope": slope}
    if (not above) and (not up):
        return {"label": "逆風", "icon": "⛈️", "bg": "#b71c1c",
                "ma_used": ma_col, "days": days, "slope": slope}
    return {"label": "中性轉折", "icon": "🌥️", "bg": "#546e7a",
            "ma_used": ma_col, "days": days, "slope": slope}


def compute_momentum(df):
    """
    ② 動能 / Momentum（時間序列動能 + RSI）。
    參考 time-series momentum：過去 1/3/6/12 個月報酬對下一期有一定預測力，
    強者續強、弱者續弱。以多數區間是否為正 + 3 個月方向綜合評分。
    回傳 dict：{r1, r3, r6, r12, rsi, score, n, label, icon, bg}；資料不足回 None。
    """
    if df is None or len(df) < 21:
        return None
    latest = df.iloc[-1]

    def g(col):
        v = latest.get(col)
        return round(float(v), 1) if (v is not None and pd.notna(v)) else None

    r1, r3, r6, r12 = g('Ret_20'), g('Ret_60'), g('Ret_120'), g('Ret_240')
    rsi = g('RSI14')
    vals = [x for x in (r1, r3, r6, r12) if x is not None]
    if not vals:
        return None
    pos = sum(1 for x in vals if x > 0)
    ratio = pos / len(vals)

    if ratio >= 0.75 and (r3 is None or r3 > 0):
        label, icon, bg = "強動能", "🚀", "#2e7d32"
    elif ratio <= 0.25 and (r3 is None or r3 < 0):
        label, icon, bg = "弱動能", "🐢", "#b71c1c"
    else:
        label, icon, bg = "中性動能", "⚖️", "#546e7a"

    return {"r1": r1, "r3": r3, "r6": r6, "r12": r12, "rsi": rsi,
            "score": pos, "n": len(vals), "label": label, "icon": icon, "bg": bg}


def compute_atr_stop(df, mult=2.0):
    """
    ⑤ 波動度 / ATR 風控。ATR 不預測方向，但可避免停損被正常波動掃掉：
    停損建議放在 1.5～3 倍 ATR 之外。回傳建議停損價與波動幅度；資料不足回 None。
    回傳 dict：{atr, atr_pct, stop, stop_tight, stop_loose, mult}。
    """
    if df is None or len(df) < 15 or 'ATR14' not in df.columns:
        return None
    latest = df.iloc[-1]
    atr = latest.get('ATR14')
    close = latest['Close']
    if pd.isna(atr) or atr <= 0 or close <= 0:
        return None
    return {
        "atr": round(float(atr), 2),
        "atr_pct": round(atr / close * 100, 1),
        "stop": round(close - mult * atr, 2),        # 主要建議(2×ATR)
        "stop_tight": round(close - 1.5 * atr, 2),   # 較緊(1.5×ATR)
        "stop_loose": round(close - 3.0 * atr, 2),   # 較鬆(3×ATR)
        "mult": mult,
    }


def compute_support_resistance(df, window=60):
    """
    ④ 支撐壓力 / 前高前低 + 風險報酬比(R:R)。
    前高＝壓力(潛在報酬空間)、前低＝支撐(潛在風險/停損參考)。
    broken=True 代表已突破前高(強勢)。回傳 None 表示資料不足。
    回傳 dict：{resistance, support, rr, upside_pct, downside_pct, window, broken}。
    """
    if df is None or len(df) < 2:
        return None
    latest = df.iloc[-1]
    close = latest['Close']
    res = latest.get(f'PriorHigh{window}')
    sup = latest.get(f'PriorLow{window}')
    if res is None or sup is None or pd.isna(res) or pd.isna(sup) or close <= 0:
        return None

    upside = res - close      # 到壓力(潛在報酬)
    downside = close - sup     # 到支撐(潛在風險)
    broken = upside <= 0        # 已站上前高
    rr = round(upside / downside, 2) if (downside > 0 and upside > 0) else None
    return {
        "resistance": round(float(res), 2),
        "support": round(float(sup), 2),
        "rr": rr,
        "upside_pct": round(upside / close * 100, 1),
        "downside_pct": round(downside / close * 100, 1),
        "window": window,
        "broken": bool(broken),
    }


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
    # B6 帶量突破前高：價漲量增 + 站上 20 日前高（成交量要搭配價格結構才可靠）
    ph20 = last.get('PriorHigh20')
    ph20_prev = prev.get('PriorHigh20')
    if not in_disp and ph20 is not None and ph20_prev is not None \
            and pd.notna(ph20) and pd.notna(ph20_prev) \
            and last['Close'] > ph20 and prev['Close'] <= ph20_prev and vr >= 1.5:
        buys.append("帶量破前高")
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


def red_k_tailwind_signals(df, chg_thr=6.5, vol_mult=1.5, atr_trail_mult=2.0,
                           reentry_on_new_high=False, limit_up_thr=9.5,
                           require_close_high=True):
    """
    策略「紅K順風車」買賣點標記（狀態機：進場→出場成對；依 volatility_framework.md）。
    回傳 dict：{buys, sells, warns, accel_mask, trail, latest}；資料不足回 None。

    進場（flat 時）—— 第一根紅K（前一根未觸發才算第一根），兩條任一成立：
      Ⓐ 出量突破：漲≥chg_thr% 且 量≥vol_mult×20日均量 且 收紅實體(收>開)
      Ⓑ 鎖漲停：漲≥limit_up_thr%(預設9.5) 且 收盤=當日最高 —— 量不論、不要求實體收紅
         （台股鎖漲停量被機械性壓縮，涵蓋一字/跳空鎖死；收=高確認鎖在漲停而非觸頂回落）
      ※ 無量再進場補丁：收盤創 20 日新高 —— 預設【關閉】(reentry_on_new_high=False)，
         依使用者要求移除此再進場邏輯
    出場（持倉時，先觸發者）
      交易倉：收盤跌破「進場後最高收盤 − atr_trail_mult×ATR14」→ 2×ATR 移動停利
      核心倉：20日SNR 由正轉負(跌破0) 且 RetStd20 位於高檔 → 性質切換SNR<0
    警示層（不直接觸發，另存 warns）
      波動降溫：ATR5% 下穿 ATR14% 且連續走低（近三日遞減）
      性質切換警示：SNR5日均 由>0.15 掉到<0.05 且 ATR14% ≥ 120日P80
    背景：波動加速＝ATR5%>ATR14% 且 ATR14% ≥ 一年P80 → accel_mask
    """
    if df is None or len(df) < 25:
        return None

    o = df['Open'].to_numpy(float)
    h = df['High'].to_numpy(float)
    low = df['Low'].to_numpy(float)
    c = df['Close'].to_numpy(float)
    v = df['Volume'].to_numpy(float)
    n = len(df)
    idx = df.index

    def _arr(name, fallback=None):
        if name in df.columns:
            return df[name].to_numpy(float)
        return fallback

    ret1 = _arr('Ret1')
    if ret1 is None:
        ret1 = np.concatenate([[np.nan], (c[1:] / c[:-1] - 1) * 100])
    # 出量基準用「處置剔除後」的 20 日均量（處置期量能失真不可比）
    volma20 = _arr('Vol_MA20_clean')
    if volma20 is None:
        volma20 = _arr('Vol_MA20')
    if volma20 is None:
        volma20 = pd.Series(v).rolling(20).mean().to_numpy()
    atr14 = _arr('ATR14_clean')                        # 絕對值(元)，處置剔除後，供 trail
    if atr14 is None:
        atr14 = _arr('ATR14', np.full(n, np.nan))
    dispday = df['DispDay'].to_numpy(bool) if 'DispDay' in df.columns else np.zeros(n, bool)
    atr5p = _arr('ATR5_pct', np.full(n, np.nan))
    atr14p = _arr('ATR14_pct', np.full(n, np.nan))
    atr14p80 = _arr('ATR14_pct_p80', np.full(n, np.nan))
    atr14p80_120 = _arr('ATR14_pct_p80_120', np.full(n, np.nan))
    snr = _arr('SNR_t', np.full(n, np.nan))
    snr5 = _arr('SNR_t5', np.full(n, np.nan))
    retstd = _arr('RetStd20', np.full(n, np.nan))
    retstd_p60 = _arr('RetStd20_p60', np.full(n, np.nan))
    flip = _arr('FlipRate10', np.full(n, np.nan))
    if 'Close20High' in df.columns:
        c20high = df['Close20High'].to_numpy(bool)
    else:
        c20high = c >= pd.Series(c).rolling(20).max().to_numpy()

    def _fin(x):
        return x is not None and np.isfinite(x)

    def _ignite(i):
        if not (_fin(ret1[i]) and c[i] > 0):
            return False
        # Ⓑ 鎖漲停：漲≥limit_up_thr%（可選 收在最高）→ 量不論、不要求實體收紅（一字/跳空鎖死）
        locked_limit = ret1[i] >= limit_up_thr and (
            (not require_close_high) or c[i] >= h[i] - 1e-6)
        # Ⓐ 出量突破：漲≥chg_thr% 且 量≥vol_mult×20日均量 且 收紅實體
        vol_breakout = (_fin(volma20[i]) and ret1[i] >= chg_thr
                        and v[i] >= vol_mult * volma20[i] and c[i] > o[i])
        return locked_limit or vol_breakout

    buys, sells = [], []
    trail = np.full(n, np.nan)
    in_pos = False
    peak = np.nan

    for i in range(n):
        if dispday[i]:
            continue                          # 處置日不進不出、不更新峰值(trail 留 NaN)
        if not in_pos:
            reason = None
            if _ignite(i) and not (i > 0 and _ignite(i - 1)):
                reason = "第一根紅K"
            elif reentry_on_new_high and c20high[i]:
                reason = "20日新高再進場"
            if reason and _fin(atr14[i]):
                in_pos = True
                peak = c[i]
                trail[i] = peak - atr_trail_mult * atr14[i]
                buys.append({"date": idx[i], "price": float(low[i]), "reason": reason})
        else:
            if c[i] > peak:
                peak = c[i]
            tr = peak - atr_trail_mult * atr14[i] if _fin(atr14[i]) else np.nan
            trail[i] = tr
            exit_trail = _fin(tr) and c[i] < tr
            exit_regime = (_fin(snr[i]) and _fin(snr[i - 1]) and snr[i] < 0 and snr[i - 1] >= 0
                           and _fin(retstd[i]) and _fin(retstd_p60[i]) and retstd[i] >= retstd_p60[i])
            if exit_trail or exit_regime:
                rs = []
                if exit_regime:
                    rs.append("性質切換SNR<0")
                if exit_trail:
                    rs.append("2×ATR移動停利")
                sells.append({"date": idx[i], "price": float(h[i]), "reason": "／".join(rs)})
                in_pos = False
                peak = np.nan

    # ── 警示層 ──
    warns_map = {}
    for i in range(2, n):
        if _fin(atr5p[i]) and _fin(atr14p[i]) and _fin(atr5p[i - 1]) and _fin(atr14p[i - 1]) and _fin(atr5p[i - 2]):
            if (atr5p[i] < atr14p[i] and atr5p[i - 1] >= atr14p[i - 1]
                    and atr5p[i] < atr5p[i - 1] < atr5p[i - 2]):
                warns_map.setdefault(idx[i], []).append("波動降溫")
    for i in range(1, n):
        if (_fin(snr5[i]) and _fin(snr5[i - 1]) and _fin(atr14p[i]) and _fin(atr14p80_120[i])
                and snr5[i - 1] > 0.15 and snr5[i] < 0.05 and atr14p[i] >= atr14p80_120[i]):
            warns_map.setdefault(idx[i], []).append("性質切換警示")
    warns = [{"date": t, "price": float(df['High'].loc[t]), "reason": "／".join(rs)}
             for t, rs in sorted(warns_map.items())]

    accel = pd.Series((atr5p > atr14p) & (atr14p >= atr14p80), index=idx).fillna(False)

    # ── 最新狀態 / 象限 ──
    snr_last = snr[-1]
    energy_high = _fin(atr14p[-1]) and _fin(atr14p80[-1]) and atr14p[-1] >= atr14p80[-1]
    if _fin(snr_last):
        if snr_last >= 0.15 and energy_high:
            quad = "單邊行情（抱緊+雷達）"
        elif snr_last >= 0.15:
            quad = "緩漲趨勢（沿5日線）"
        elif energy_high:
            quad = "雙向絞殺（縮部位/離場）"
        else:
            quad = "休眠盤整（觀察）"
    else:
        quad = "—"

    def _round(x):
        return round(float(x), 2) if _fin(x) else None

    latest = {
        "atr5_pct": _round(atr5p[-1]), "atr14_pct": _round(atr14p[-1]),
        "snr": _round(snr_last), "flip_pct": round(float(flip[-1]) * 100) if _fin(flip[-1]) else None,
        "accel": bool(accel.iloc[-1]), "in_pos": in_pos, "quad": quad,
    }
    return {"buys": buys, "sells": sells, "warns": warns,
            "accel_mask": accel, "trail": pd.Series(trail, index=idx), "latest": latest}
