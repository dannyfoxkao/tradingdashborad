"""自訂板塊 K 線網格牆（Pro 級量化指標）。"""

from __future__ import annotations

import html
import logging

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from ..config import (
    ALPHA_LAG,
    ALPHA_STRONG,
    HUNDRED_MILLION,
    parse_stock_id,
)
from ..data_sources.disposition import disposition_mask
from ..data_sources.prefetch import prefetch_many
from ..indicators import (
    classify_trend,
    classify_volume,
    compute_alpha,
    compute_atr_stop,
    compute_support_resistance,
    volume_base,
)
from ..signals import MAX_BUY_SIGNALS, evaluate_signals
from ..strategy import red_k_tailwind_signals
from .components import badge_html, get_rangebreaks, price_badge

logger = logging.getLogger(__name__)

_MIN_ROWS = 5
_CANDLE_UP, _CANDLE_DOWN = "#ef5350", "#26a69a"
_MA_COLORS = {"MA5": "#ffa726", "MA10": "#ec407a", "MA20": "#29b6f6", "MA60": "#ab47bc"}
_MA200_COLOR = "#90a4ae"  # 長線趨勢濾網（灰虛線，成形才畫）
# 副圖均線的單一事實來源：圖例與繪線皆由此導出，保證兩者一致
_SUB_MA_COLORS: dict[int, str] = {5: "#ffa726", 20: "#29b6f6"}
_TURN_BAR, _DUAL_LINE, _DISP_FILL = "#455a64", "#cfd8dc", "#7e57c2"
_ACCEL_FILL = "#fbc02d"  # 波動加速背景
_TURN_TYPE, _DUAL_TYPE = "成交金額 (估算)", "量 + 金額雙對比"


def render(
    group_choice,
    selected_stocks,
    grid_cols,
    sub_chart_type,
    start_str,
    end_str,
    benchmark_df,
    disposition_map,
    show_tailwind: bool = True,
) -> None:
    tickers = list(selected_stocks.keys())
    # 先平行預抓整個族群，迴圈內只做 dict 查找（修序列阻塞）
    data = prefetch_many(tickers, start_str, end_str)

    for i in range(0, len(tickers), grid_cols):
        row_tickers = tickers[i : i + grid_cols]
        cols = st.columns(grid_cols)
        for idx, ticker in enumerate(row_tickers):
            clean_id = parse_stock_id(ticker)
            df = data.get(clean_id)
            with cols[idx]:
                if df is None:
                    st.markdown(
                        _empty_card_html(clean_id, selected_stocks[ticker], "抓取失敗或代號無資料"),
                        unsafe_allow_html=True,
                    )
                elif len(df) < _MIN_ROWS:
                    st.markdown(
                        _empty_card_html(
                            clean_id, selected_stocks[ticker], f"僅 {len(df)} 筆，未達最低 {_MIN_ROWS} 筆"
                        ),
                        unsafe_allow_html=True,
                    )
                else:
                    _render_card(
                        clean_id,
                        selected_stocks[ticker],
                        df,
                        sub_chart_type,
                        benchmark_df,
                        disposition_map,
                        key=f"{ticker}_{i + idx}",
                        show_tailwind=show_tailwind,
                    )


def _render_card(
    clean_id, name, df, sub_chart_type, benchmark_df, disposition_map, key="", show_tailwind: bool = True
) -> None:
    disp_windows = disposition_map.get(clean_id, [])
    disp_mask = _disposition_mask(df.index, disp_windows)
    st.markdown(
        _panel_html(clean_id, name, df, disp_windows, disp_mask, sub_chart_type, benchmark_df),
        unsafe_allow_html=True,
    )
    sig_html = _signals_html(clean_id, df, bool(disp_mask.iloc[-1]))
    if sig_html:
        st.markdown(sig_html, unsafe_allow_html=True)

    tw = _tailwind_result(clean_id, df) if show_tailwind else None
    if tw:
        st.markdown(_tailwind_html(tw), unsafe_allow_html=True)
    sr = compute_support_resistance(df)
    atr_stop = compute_atr_stop(df)

    st.plotly_chart(
        _build_figure(df, sub_chart_type, disp_windows, tw=tw, sr=sr, atr_stop=atr_stop),
        width="stretch",
        key=f"chart_{key}",
    )


def _tailwind_result(clean_id: str, df: pd.DataFrame) -> dict | None:
    try:
        return red_k_tailwind_signals(df)
    except Exception as e:  # 策略評估失敗不應讓卡片崩潰
        logger.warning("紅K順風車評估失敗 %s：%s", clean_id, e)
        return None


def _tailwind_html(tw: dict) -> str:
    """🚗 紅K順風車狀態列：象限／波動狀態／持倉／關鍵指標／訊號計數。"""
    latest = tw["latest"]
    if latest["accel"]:
        vstate = f'<span style="color:{_ACCEL_FILL};">🔥波動加速</span>'
    else:
        vstate = '<span style="color:#9e9e9e;">波動中性</span>'
    pos_txt = (
        '<span style="color:#ff8a80;">持倉中</span>' if latest["in_pos"] else '<span style="color:#888;">空手</span>'
    )
    return (
        f'<div style="padding:4px 10px;background:#161616;border-radius:6px;'
        f'margin-bottom:5px;font-size:10px;color:#aaa;">'
        f"🚗 紅K順風車｜{latest['quad']}｜{vstate}｜{pos_txt}　"
        f"ATR5% {latest['atr5_pct']}／ATR14% {latest['atr14_pct']}　"
        f"SNR {latest['snr']}｜翻轉 {latest['flip_pct']}%　"
        f'<span style="color:#ff8a80;">▲買{len(tw["buys"])}</span> '
        f'<span style="color:#80cbc4;">▼賣{len(tw["sells"])}</span> '
        f'<span style="color:#ffb74d;">⚠{len(tw["warns"])}</span></div>'
    )


def _chip(text: str, bg: str) -> str:
    return (
        f'<span style="background:{bg};color:#fff;padding:1px 5px;border-radius:3px;'
        f'font-size:10px;margin:0 3px 2px 0;display:inline-block;">{html.escape(text)}</span>'
    )


def _signals_html(clean_id: str, df: pd.DataFrame, in_disp: bool) -> str:
    """交易一致性訊號燈列（進場/出場/乖離）；無法評估時回空字串。"""
    try:
        sig = evaluate_signals(df, in_disp)
    except Exception as e:  # 訊號失敗不應讓卡片崩潰
        logger.warning("訊號評估失敗 %s：%s", clean_id, e)
        sig = None
    if not sig:
        return ""
    buy_chips = "".join(_chip(b, "#1b5e20") for b in sig["buys"])
    sell_chips = "".join(_chip(s, "#b71c1c") for s in sig["sells"])
    nb, ns = len(sig["buys"]), len(sig["sells"])
    buy_badge = f'<span style="color:#66bb6a;font-weight:bold;">📥 進場 {nb}/{MAX_BUY_SIGNALS}</span>'
    sell_badge = (
        f'<span style="color:#ef5350;font-weight:bold;margin-left:10px;">📤 出場警示 {ns}</span>'
        if ns
        else '<span style="color:#9e9e9e;margin-left:10px;">📤 無警示</span>'
    )
    bias_txt = f'<span style="color:#888;margin-left:10px;">乖離 5d {sig["bias5"]}% ｜ 20d {sig["bias20"]}%</span>'
    chips = (buy_chips + sell_chips) or '<span style="color:#666;font-size:10px;">—</span>'
    return f"""
    <div style="padding:5px 10px; background:#181818; border-radius:6px; margin-bottom:5px; font-size:11px;">
        <div style="margin-bottom:3px;">{buy_badge}{sell_badge}{bias_txt}</div>
        <div>{chips}</div>
    </div>
    """


def _empty_card_html(clean_id: str, name: str, reason: str) -> str:
    """個股無資料時的占位卡（取代原本的默默留白）。"""
    safe_name = html.escape(str(name))
    safe_reason = html.escape(reason)
    return f"""
    <div style="padding: 8px 10px; background-color: #1e1e1e; border-radius: 6px; border-left: 4px solid #616161; margin-bottom: 5px;">
        <b style="color: #9e9e9e; font-size: 14px;">{clean_id} {safe_name}</b>
        <div style="font-size: 12px; color: #757575;">⚠️ 無資料：{safe_reason}</div>
    </div>
    """


def _disposition_mask(index: pd.DatetimeIndex, windows: list[dict]) -> pd.Series:
    return disposition_mask(index, windows)


def _panel_html(clean_id, name, df, disp_windows, disp_mask, sub_chart_type, benchmark_df) -> str:
    last_date = df.index[-1].normalize()
    in_disp = bool(disp_mask.iloc[-1])
    active_w = next((w for w in disp_windows if w["start"] <= last_date <= w["end"]), None)
    disp_html = (
        badge_html(f"處置 {active_w['measure']}·至{active_w['end'].strftime('%m/%d')}", "#6a1b9a", "⛔")
        if active_w
        else ""
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
        if alpha_val is not None and beta is not None:
            alpha_html = _alpha_badge(alpha_val, beta)
    except Exception as e:  # 指標計算失敗不應讓整張卡片崩潰
        logger.warning("圖卡指標計算失敗 %s：%s", clean_id, e)

    sub_label = "額MA" if sub_chart_type == _TURN_TYPE else "量MA"
    sub_legend = "".join(
        f'<span style="color:{color}; margin-right:5px;">●{w}</span>' for w, color in _SUB_MA_COLORS.items()
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
            價MA: <span style="color:#ffa726; margin-right:5px;">●5</span><span style="color:#ec407a; margin-right:5px;">●10</span><span style="color:#29b6f6; margin-right:5px;">●20</span><span style="color:#ab47bc; margin-right:5px;">●60</span><span style="color:{_MA200_COLOR}; margin-right:12px;">┈200</span>
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


def _build_figure(
    df: pd.DataFrame,
    sub_chart_type: str,
    disp_windows: list[dict],
    tw: dict | None = None,
    sr: dict | None = None,
    atr_stop: dict | None = None,
) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.70, 0.30])
    display_vol = df["Volume"] / 1000
    vol_colors = [_CANDLE_UP if c >= o else _CANDLE_DOWN for o, c in zip(df["Open"], df["Close"], strict=False)]

    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            increasing_line_color=_CANDLE_UP,
            decreasing_line_color=_CANDLE_DOWN,
            increasing_fillcolor=_CANDLE_UP,
            decreasing_fillcolor=_CANDLE_DOWN,
        ),
        row=1,
        col=1,
    )
    for ma, color in _MA_COLORS.items():
        fig.add_trace(go.Scatter(x=df.index, y=df[ma], mode="lines", line={"color": color, "width": 1.2}), row=1, col=1)
    # 長線趨勢濾網 MA200（灰虛線，僅在成形時繪製）
    if "MA200" in df.columns and df["MA200"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=df.index, y=df["MA200"], mode="lines", line={"color": _MA200_COLOR, "width": 1.0, "dash": "dot"}
            ),
            row=1,
            col=1,
        )

    if tw:
        _add_tailwind_traces(fig, df, tw)
    _add_level_lines(fig, sr, atr_stop)
    _add_subchart(fig, df, sub_chart_type, display_vol, vol_colors)

    fig.update_layout(
        height=380,
        margin={"l": 35, "r": 35, "t": 30, "b": 15},
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        showlegend=False,
        hovermode="x unified",
    )
    fig.update_xaxes(rangebreaks=[{"values": get_rangebreaks(df.index)}])

    for w in disp_windows:  # ⛔ 處置期間：紫色陰影（量縮為分盤所致，非真實冷卻）
        x0 = max(w["start"], df.index.min())
        x1 = min(w["end"], df.index.max())
        if x0 <= x1:
            fig.add_vrect(
                x0=x0, x1=x1, fillcolor=_DISP_FILL, opacity=0.13, line_width=0, layer="below", row="all", col=1
            )
    return fig


def _add_tailwind_traces(fig: go.Figure, df: pd.DataFrame, tw: dict) -> None:
    """紅K順風車覆蓋層：波動加速背景、2×ATR trail、▲買/▼賣/★警示標記。"""
    accel = tw.get("accel_mask")
    if accel is not None and accel.any():  # 波動加速：淡黃背景區段
        groups = (accel != accel.shift()).cumsum()
        for _, seg in accel[accel].groupby(groups[accel]):
            fig.add_vrect(
                x0=seg.index.min(),
                x1=seg.index.max(),
                fillcolor=_ACCEL_FILL,
                opacity=0.06,
                line_width=0,
                layer="below",
                row=1,
                col=1,
            )
    trail = tw.get("trail")
    if trail is not None and trail.notna().any():  # 持倉段才有值，空手為 NaN 自動斷線
        fig.add_trace(
            go.Scatter(x=df.index, y=trail, mode="lines", line={"color": "#ffa726", "width": 1.0, "dash": "dot"}),
            row=1,
            col=1,
        )
    marker_specs = (
        (tw["buys"], 0.985, "triangle-up", 12, "#ff5252", "買"),
        (tw["sells"], 1.015, "triangle-down", 12, "#26a69a", "賣"),
        (tw["warns"], 1.03, "star", 9, "#ffb74d", "警示"),
    )
    for events, y_mult, symbol, size, color, label in marker_specs:
        if not events:
            continue
        fig.add_trace(
            go.Scatter(
                x=[e["date"] for e in events],
                y=[e["price"] * y_mult for e in events],
                mode="markers",
                marker={"symbol": symbol, "size": size, "color": color, "line": {"width": 1, "color": "#fff"}},
                text=[e["reason"] for e in events],
                hovertemplate=label + "：%{text}<br>%{x|%Y-%m-%d}<extra></extra>",
            ),
            row=1,
            col=1,
        )


def _add_level_lines(fig: go.Figure, sr: dict | None, atr_stop: dict | None) -> None:
    """支撐壓力（前高前低）＋ ATR 停損：主圖水平參考線。"""
    if sr:
        fig.add_hline(
            y=sr["resistance"],
            line={"color": _CANDLE_UP, "width": 0.8, "dash": "dash"},
            annotation_text="壓",
            annotation_position="top left",
            annotation_font_size=9,
            annotation_font_color=_CANDLE_UP,
            row=1,
            col=1,
        )
        fig.add_hline(
            y=sr["support"],
            line={"color": _CANDLE_DOWN, "width": 0.8, "dash": "dash"},
            annotation_text="撐",
            annotation_position="bottom left",
            annotation_font_size=9,
            annotation_font_color=_CANDLE_DOWN,
            row=1,
            col=1,
        )
    if atr_stop:
        fig.add_hline(
            y=atr_stop["stop"],
            line={"color": "#ffa726", "width": 0.8, "dash": "dot"},
            annotation_text="停損2×ATR",
            annotation_position="bottom right",
            annotation_font_size=9,
            annotation_font_color="#ffa726",
            row=1,
            col=1,
        )


def _add_subchart(fig, df, sub_chart_type, display_vol, vol_colors) -> None:
    div = HUNDRED_MILLION
    if sub_chart_type in ("成交量", _DUAL_TYPE):
        fig.add_trace(go.Bar(x=df.index, y=display_vol, marker_color=vol_colors, opacity=1.0), row=2, col=1)
        for w, color in _SUB_MA_COLORS.items():
            fig.add_trace(
                go.Scatter(x=df.index, y=df[f"Vol_MA{w}"] / 1000, mode="lines", line={"color": color, "width": 1.0}),
                row=2,
                col=1,
            )
    if sub_chart_type == _TURN_TYPE:
        fig.add_trace(go.Bar(x=df.index, y=df["Turnover"] / div, marker_color=_TURN_BAR, opacity=0.5), row=2, col=1)
        for w, color in _SUB_MA_COLORS.items():
            fig.add_trace(
                go.Scatter(x=df.index, y=df[f"Turn_MA{w}"] / div, mode="lines", line={"color": color, "width": 1.0}),
                row=2,
                col=1,
            )
    if sub_chart_type == _DUAL_TYPE:
        fig.add_trace(
            go.Scatter(x=df.index, y=df["Turnover"] / div, mode="lines", line={"color": _DUAL_LINE, "width": 1.2}),
            row=2,
            col=1,
        )
        # add_trace(row=2) 會把 yaxis 覆寫為 y2，須事後改指到疊加軸 y3
        fig.data[-1].update(yaxis="y3")
        fig.update_layout(yaxis3={"overlaying": "y2", "side": "right", "showgrid": False})
