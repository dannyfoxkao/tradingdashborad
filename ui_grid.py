import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from data import fetch_finmind_data
from analysis import classify_trend, compute_alpha, evaluate_signals


# =====================================================================
# 🧭 族群動能：多空陣營占比（族群一起動 / 族群轉弱）
# =====================================================================
def render_group_momentum(tickers, start_str, end_str):
    _bull_set = {"強多", "底部翻揚", "震盪(偏多)"}
    _bear_set = {"弱勢", "震盪(偏空)", "頭部鈍化"}
    _g_bull = _g_bear = _g_total = 0
    for _tk in tickers:
        _d = fetch_finmind_data(_tk.split('.')[0].strip(), start_str, end_str)
        _ti = classify_trend(_d)
        if _ti:
            _g_total += 1
            if _ti["label"] in _bull_set:
                _g_bull += 1
            elif _ti["label"] in _bear_set:
                _g_bear += 1
    if _g_total:
        _bull_pct = _g_bull / _g_total * 100
        _bear_pct = _g_bear / _g_total * 100
        _m1, _m2, _m3 = st.columns(3)
        _m1.metric("族群多方占比", f"{_bull_pct:.0f}%", f"{_g_bull}/{_g_total} 檔")
        _m2.metric("族群空方占比", f"{_bear_pct:.0f}%", f"{_g_bear}/{_g_total} 檔", delta_color="inverse")
        _m3.metric("中性", f"{max(100 - _bull_pct - _bear_pct, 0):.0f}%",
                   f"{_g_total - _g_bull - _g_bear}/{_g_total} 檔")
        st.progress(_bull_pct / 100, text=f"族群同步偏多 {_bull_pct:.0f}%")
        if _bear_pct >= 50:
            st.warning("⚠️ 族群轉弱：空方陣營過半，符合『族群轉弱』出場條件，持股留意減碼。")
        elif _bull_pct >= 60:
            st.success("🚀 族群一起動：多方陣營過六成，順風環境，回檔偏買點。")
    st.markdown("---")


# =====================================================================
# 🖥️ UI：自訂板塊 K 線網格牆 (Pro 級量化指標升級版)
# =====================================================================
def render_grid_wall(tickers, selected_stocks, grid_cols, sub_chart_type,
                     start_str, end_str, disposition_map, benchmark_df):
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

                # ── 交易一致性訊號燈：進場(B/H) / 出場(S)，純日線自動子集 ──
                try:
                    sig = evaluate_signals(df, in_disp)
                except Exception:
                    sig = None
                if sig:
                    buy_chips = "".join(
                        f'<span style="background:#1b5e20;color:#fff;padding:1px 5px;border-radius:3px;'
                        f'font-size:10px;margin:0 3px 2px 0;display:inline-block;">{b}</span>'
                        for b in sig["buys"])
                    sell_chips = "".join(
                        f'<span style="background:#b71c1c;color:#fff;padding:1px 5px;border-radius:3px;'
                        f'font-size:10px;margin:0 3px 2px 0;display:inline-block;">{s}</span>'
                        for s in sig["sells"])
                    nb, ns = len(sig["buys"]), len(sig["sells"])
                    buy_badge = f'<span style="color:#66bb6a;font-weight:bold;">📥 進場 {nb}/5</span>'
                    sell_badge = (f'<span style="color:#ef5350;font-weight:bold;margin-left:10px;">📤 出場警示 {ns}</span>'
                                  if ns else '<span style="color:#9e9e9e;margin-left:10px;">📤 無警示</span>')
                    bias_txt = (f'<span style="color:#888;margin-left:10px;">乖離 5d {sig["bias5"]}% ｜ '
                                f'20d {sig["bias20"]}%</span>')
                    chips = (buy_chips + sell_chips) or '<span style="color:#666;font-size:10px;">—</span>'
                    st.markdown(f"""
                    <div style="padding:5px 10px; background:#181818; border-radius:6px; margin-bottom:5px; font-size:11px;">
                        <div style="margin-bottom:3px;">{buy_badge}{sell_badge}{bias_txt}</div>
                        <div>{chips}</div>
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
