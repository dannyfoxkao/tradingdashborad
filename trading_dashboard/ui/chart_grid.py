"""自訂板塊 K 線網格牆（Pro 級量化指標）。"""
from __future__ import annotations

import html
import logging

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from ..config import (
    ALPHA_LAG, ALPHA_STRONG, HUNDRED_MILLION, parse_stock_id,
)
from ..data_sources.prefetch import prefetch_many
from ..indicators import classify_trend, classify_volume, compute_alpha, volume_base
from .components import badge_html, get_rangebreaks, price_badge

logger = logging.getLogger(__name__)

_MIN_ROWS = 5
_CANDLE_UP, _CANDLE_DOWN = "#ef5350", "#26a69a"
_MA_COLORS = {"MA5": "#ffa726", "MA10": "#ec407a", "MA20": "#29b6f6", "MA60": "#ab47bc"}
# 副圖均線的單一事實來源：圖例與繪線皆由此導出，保證兩者一致
_SUB_MA_COLORS: dict[int, str] = {5: "#ffa726", 20: "#29b6f6"}
_TURN_BAR, _DUAL_LINE, _DISP_FILL = "#455a64", "#cfd8dc", "#7e57c2"
_TURN_TYPE, _DUAL_TYPE = "成交金額 (估算)", "量 + 金額雙對比"


def render(group_choice, selected_stocks, grid_cols, sub_chart_type, start_str, end_str,
           benchmark_df, disposition_map) -> None:
    tickers = list(selected_stocks.keys())
    # 先平行預抓整個族群，迴圈內只做 dict 查找（修序列阻塞）
    data = prefetch_many(tickers, start_str, end_str)

    for i in range(0, len(tickers), grid_cols):
        row_tickers = tickers[i:i + grid_cols]
        cols = st.columns(grid_cols)
        for idx, ticker in enumerate(row_tickers):
            clean_id = parse_stock_id(ticker)
            df = data.get(clean_id)
            if df is None or len(df) < _MIN_ROWS:
                continue
            with cols[idx]:
                _render_card(clean_id, selected_stocks[ticker], df, sub_chart_type,
                             benchmark_df, disposition_map, key=f"{ticker}_{i + idx}")


def _render_card(clean_id, name, df, sub_chart_type, benchmark_df, disposition_map, key="") -> None:
    disp_windows = disposition_map.get(clean_id, [])
    disp_mask = _disposition_mask(df.index, disp_windows)
    st.markdown(
        _panel_html(clean_id, name, df, disp_windows, disp_mask, sub_chart_type, benchmark_df),
        unsafe_allow_html=True,
    )
    st.plotly_chart(_build_figure(df, sub_chart_type, disp_windows), width="stretch", key=f"chart_{key}")


def _disposition_mask(index: pd.DatetimeIndex, windows: list[dict]) -> pd.Series:
    mask = pd.Series(False, index=index)
    norm = index.normalize()
    for w in windows:
        mask |= (norm >= w["start"]) & (norm <= w["end"])
    return mask


def _panel_html(clean_id, name, df, disp_windows, disp_mask, sub_chart_type, benchmark_df) -> str:
    last_date = df.index[-1].normalize()
    in_disp = bool(disp_mask.iloc[-1])
    active_w = next((w for w in disp_windows if w["start"] <= last_date <= w["end"]), None)
    disp_html = (
        badge_html(f'處置 {active_w["measure"]}·至{active_w["end"].strftime("%m/%d")}', "#6a1b9a", "⛔")
        if active_w else ""
    )

    price_html = trend_html = vol_html = alpha_html = ""
    try:
        latest, prev = df.iloc[-1], df.iloc[-2]
        price_html = price_badge(latest["Close"], prev["Close"])

        ti = classify_trend(df)
        if ti:
            trend_html = badge_html(ti["label"], ti["bg"], ti["icon"])

        if in_disp:
            # 處置改分盤撮合 → 量被機械性壓縮、不可比，停用爆量/縮量結論避免假訊號
            vol_html = badge_html("分盤·量能失真", "#6a1b9a", "⛔")
        else:
            base_vol = volume_base(df["Volume"], disp_mask)
            vi = classify_volume(latest["Volume"], base_vol, latest["Vol_MA20"], latest["Vol_Std20"])
            vol_html = badge_html(vi["label"], vi["bg"], vi["icon"])

        alpha_val, beta = compute_alpha(df, benchmark_df)
        if alpha_val is not None:
            alpha_html = _alpha_badge(alpha_val, beta)
    except Exception as e:  # 指標計算失敗不應讓整張卡片崩潰
        logger.warning("圖卡指標計算失敗 %s：%s", clean_id, e)

    sub_label = "額MA" if sub_chart_type == _TURN_TYPE else "量MA"
    sub_legend = "".join(
        f'<span style="color:{color}; margin-right:5px;">●{w}</span>'
        for w, color in _SUB_MA_COLORS.items()
    )
    safe_name = html.escape(str(name))
    return f"""
    <div style="padding: 8px 10px; background-color: #1e1e1e; border-radius: 6px; border-left: 4px solid #4fc3f7; margin-bottom: 5px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
            <div>
                <b style="color: #FFFFFF; font-size: 14px;">{clean_id} {safe_name}</b>
                {price_html}
            </div>
            <div>{disp_html}{trend_html}{vol_html}{alpha_html}</div>
        </div>
        <div style="font-size: 11px; color: #888888; font-family: monospace;">
            價MA: <span style="color:#ffa726; margin-right:5px;">●5</span><span style="color:#ec407a; margin-right:5px;">●10</span><span style="color:#29b6f6; margin-right:5px;">●20</span><span style="color:#ab47bc; margin-right:12px;">●60</span>
            {sub_label}: {sub_legend}
        </div>
    </div>
    """


def _alpha_badge(alpha_val: float, beta: float) -> str:
    if alpha_val >= ALPHA_STRONG:
        bg, icon = "#558b2f", "🚀"
    elif alpha_val > 0:
        bg, icon = "#827717", "🌟"
    elif alpha_val > ALPHA_LAG:
        bg, icon = "#37474f", "⚠️"
    else:
        bg, icon = "#b71c1c", "🐢"
    sign = "+" if alpha_val >= 0 else ""
    return badge_html(f"α {sign}{alpha_val:.1f}% (β{beta:.1f})", bg, icon)


def _build_figure(df: pd.DataFrame, sub_chart_type: str, disp_windows: list[dict]) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05,
                        row_heights=[0.70, 0.30])
    display_vol = df["Volume"] / 1000
    vol_colors = [_CANDLE_UP if c >= o else _CANDLE_DOWN for o, c in zip(df["Open"], df["Close"])]

    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        increasing_line_color=_CANDLE_UP, decreasing_line_color=_CANDLE_DOWN,
        increasing_fillcolor=_CANDLE_UP, decreasing_fillcolor=_CANDLE_DOWN,
    ), row=1, col=1)
    for ma, color in _MA_COLORS.items():
        fig.add_trace(go.Scatter(x=df.index, y=df[ma], mode="lines",
                                 line=dict(color=color, width=1.2)), row=1, col=1)

    _add_subchart(fig, df, sub_chart_type, display_vol, vol_colors)

    fig.update_layout(height=380, margin=dict(l=35, r=35, t=30, b=15), template="plotly_dark",
                      xaxis_rangeslider_visible=False, showlegend=False, hovermode="x unified")
    fig.update_xaxes(rangebreaks=[dict(values=get_rangebreaks(df.index))])

    for w in disp_windows:  # ⛔ 處置期間：紫色陰影（量縮為分盤所致，非真實冷卻）
        x0 = max(w["start"], df.index.min())
        x1 = min(w["end"], df.index.max())
        if x0 <= x1:
            fig.add_vrect(x0=x0, x1=x1, fillcolor=_DISP_FILL, opacity=0.13,
                          line_width=0, layer="below", row="all", col=1)
    return fig


def _add_subchart(fig, df, sub_chart_type, display_vol, vol_colors) -> None:
    div = HUNDRED_MILLION
    if sub_chart_type in ("成交量", _DUAL_TYPE):
        fig.add_trace(go.Bar(x=df.index, y=display_vol, marker_color=vol_colors, opacity=0.4), row=2, col=1)
        for w, color in _SUB_MA_COLORS.items():
            fig.add_trace(go.Scatter(x=df.index, y=df[f"Vol_MA{w}"] / 1000, mode="lines",
                                     line=dict(color=color, width=1.0)), row=2, col=1)
    if sub_chart_type == _TURN_TYPE:
        fig.add_trace(go.Bar(x=df.index, y=df["Turnover"] / div, marker_color=_TURN_BAR, opacity=0.5), row=2, col=1)
        for w, color in _SUB_MA_COLORS.items():
            fig.add_trace(go.Scatter(x=df.index, y=df[f"Turn_MA{w}"] / div, mode="lines",
                                     line=dict(color=color, width=1.0)), row=2, col=1)
    if sub_chart_type == _DUAL_TYPE:
        fig.add_trace(go.Scatter(x=df.index, y=df["Turnover"] / div, mode="lines",
                                 line=dict(color=_DUAL_LINE, width=1.2)), row=2, col=1)
        # add_trace(row=2) 會把 yaxis 覆寫為 y2，須事後改指到疊加軸 y3
        fig.data[-1].update(yaxis="y3")
        fig.update_layout(yaxis3=dict(overlaying="y2", side="right", showgrid=False))
