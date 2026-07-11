"""🧭 族群動能：多空陣營占比（族群一起動 / 族群轉弱）。"""

from __future__ import annotations

import streamlit as st

from ..config import MOMENTUM_BEAR_ALERT, MOMENTUM_BULL_ALERT
from ..data_sources.prefetch import prefetch_many
from ..indicators import classify_trend, compute_momentum


def render(tickers: list[str], start_str: str, end_str: str) -> None:
    """計算並顯示目前族群的多空占比；資料不足時安靜略過。"""
    data = prefetch_many(tickers, start_str, end_str)
    trends = (classify_trend(df) for df in data.values())
    labels = [ti["label"] for ti in trends if ti]
    m = compute_momentum(labels)
    if not m["total"]:
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("族群多方占比", f"{m['bull_pct']:.0f}%", f"{m['bull']}/{m['total']} 檔")
    c2.metric("族群空方占比", f"{m['bear_pct']:.0f}%", f"{m['bear']}/{m['total']} 檔", delta_color="inverse")
    neutral = m["total"] - m["bull"] - m["bear"]
    c3.metric("中性", f"{max(100 - m['bull_pct'] - m['bear_pct'], 0):.0f}%", f"{neutral}/{m['total']} 檔")
    st.progress(m["bull_pct"] / 100, text=f"族群同步偏多 {m['bull_pct']:.0f}%")

    if m["bear_pct"] >= MOMENTUM_BEAR_ALERT:
        st.warning("⚠️ 族群轉弱：空方陣營過半，符合『族群轉弱』出場條件，持股留意減碼。")
    elif m["bull_pct"] >= MOMENTUM_BULL_ALERT:
        st.success("🚀 族群一起動：多方陣營過六成，順風環境，回檔偏買點。")
    st.markdown("---")
