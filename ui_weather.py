import streamlit as st

from analysis import classify_market_weather


# =====================================================================
# 🌦️ 大盤氣象台：上市(加權) + 上櫃(櫃買) 天氣濾鏡
# =====================================================================
def render_market_weather(twse_index_df, tpex_index_df):
    st.markdown("### 🌦️ 大盤氣象台")
    _mkt_cols = st.columns(2)
    for _col_box, _idx_df, _mkt_name in (
        (_mkt_cols[0], twse_index_df, "上市 · 加權指數"),
        (_mkt_cols[1], tpex_index_df, "上櫃 · 櫃買指數"),
    ):
        with _col_box:
            w = classify_market_weather(_idx_df)
            if w is None:
                st.warning(f"⚠️ {_mkt_name}：指數資料不足，暫無法研判天氣。")
                continue
            st.markdown(f"""
            <div style="padding:12px 14px; background:{w['bg']}; border-radius:8px; margin-bottom:6px;">
                <div style="font-size:15px; color:#fff; font-weight:bold; margin-bottom:4px;">
                    {_mkt_name}　{w['icon']} 天氣：{w['weather']}
                </div>
                <div style="font-size:12px; color:#e0e0e0; line-height:1.7;">
                    狀態：{w['zone']}　+　{w['wind']}<br>
                    動作：<b style="color:#fff;">{w['action']}</b><br>
                    心法：{w['mind']}
                </div>
            </div>
            """, unsafe_allow_html=True)
    st.caption("天氣 = 收盤對月線(20MA)判安全/危險區，MACD 柱狀方向判風強弱。對照下方個股訊號搭配操作。")
