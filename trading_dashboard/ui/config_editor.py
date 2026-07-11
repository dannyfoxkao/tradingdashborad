"""🛠️ 族群管理：側欄編輯 stock_config.json（免手動改 JSON）。

所有寫入都經過 config.save_stock_config（先驗證 → 一次性備份 →
原子寫入），保證編輯操作不可能產生載入不了的設定檔。
"""

from __future__ import annotations

import streamlit as st

from ..config import ConfigError, classify_ticker, save_stock_config


def render(stocks_pool: dict[str, dict[str, str]]) -> None:
    with st.sidebar.expander("🛠️ 族群管理", expanded=False):
        st.caption("新增族群（需同時提供第一檔成員）")
        _add_group_form(stocks_pool)
        st.markdown("---")
        _add_ticker_form(stocks_pool)
        _remove_ticker_form(stocks_pool)
        st.markdown("---")
        _delete_group_form(stocks_pool)


def _save_and_rerun(data: dict[str, dict[str, str]]) -> None:
    try:
        save_stock_config(data)
    except ConfigError as e:
        st.error(f"存檔失敗：{e}")
        return
    except OSError as e:
        st.error(f"寫入失敗（檔案可能被其他程式占用）：{e}")
        return
    st.rerun()


def _ticker_ok(ticker: str) -> bool:
    kind = classify_ticker(ticker)
    if kind == "invalid":
        st.error(f"代號「{ticker}」格式無效（台股為 4~6 位數字，可帶一碼大寫字母尾碼，如 2330.TW / 00981A.TW）。")
        return False
    if kind == "index":
        st.warning("指數代號僅供大盤參考，個股 K 線可能無資料。")
    return True


def _add_group_form(stocks_pool: dict[str, dict[str, str]]) -> None:
    group_in = st.text_input("族群名稱", key="editor_new_group")
    ticker_in = st.text_input("第一檔代號（如 2330.TW）", key="editor_new_group_ticker")
    name_in = st.text_input("第一檔名稱", key="editor_new_group_name")
    if st.button("➕ 新增族群", key="editor_add_group"):
        group, ticker, name = group_in.strip(), ticker_in.strip(), name_in.strip()
        if not group or not ticker or not name:
            st.error("族群名稱、代號與名稱皆不可為空。")
            return
        if group in stocks_pool:
            st.error(f"族群「{group}」已存在。")
            return
        if not _ticker_ok(ticker):
            return
        _save_and_rerun({**stocks_pool, group: {ticker: name}})


def _add_ticker_form(stocks_pool: dict[str, dict[str, str]]) -> None:
    group = st.selectbox("目標族群", list(stocks_pool.keys()), key="editor_ticker_group")
    ticker_in = st.text_input("代號（如 2330.TW / 5347.TWO）", key="editor_add_ticker")
    name_in = st.text_input("顯示名稱", key="editor_add_ticker_name")
    if st.button("➕ 加入代號", key="editor_add_ticker_btn"):
        ticker, name = ticker_in.strip(), name_in.strip()
        if not ticker or not name:
            st.error("代號與名稱皆不可為空。")
            return
        if ticker in stocks_pool[group]:
            st.error(f"「{ticker}」已在族群「{group}」中。")
            return
        if not _ticker_ok(ticker):
            return
        _save_and_rerun({**stocks_pool, group: {**stocks_pool[group], ticker: name}})


def _remove_ticker_form(stocks_pool: dict[str, dict[str, str]]) -> None:
    group = st.selectbox("從族群", list(stocks_pool.keys()), key="editor_rm_group")
    members = stocks_pool[group]
    target = st.selectbox(
        "移除代號",
        list(members.keys()),
        format_func=lambda t: f"{t} {members[t]}",
        key="editor_rm_ticker",
    )
    confirm = st.checkbox("我確認要移除此代號", key="editor_rm_ticker_confirm")
    if st.button("➖ 移除代號", key="editor_rm_ticker_btn"):
        if not confirm:
            st.error("請先勾選確認。")
            return
        if len(members) <= 1:
            st.error("族群至少須保留一檔（或直接刪除整個族群）。")
            return
        new_members = {t: n for t, n in members.items() if t != target}
        _save_and_rerun({**stocks_pool, group: new_members})


def _delete_group_form(stocks_pool: dict[str, dict[str, str]]) -> None:
    target = st.selectbox("刪除族群", list(stocks_pool.keys()), key="editor_del_group")
    confirm = st.checkbox("我確認要刪除整個族群", key="editor_del_group_confirm")
    if st.button("🗑️ 刪除族群", key="editor_del_group_btn"):
        if not confirm:
            st.error("請先勾選確認。")
            return
        if len(stocks_pool) <= 1:
            st.error("至少須保留一個族群。")
            return
        _save_and_rerun({k: v for k, v in stocks_pool.items() if k != target})
