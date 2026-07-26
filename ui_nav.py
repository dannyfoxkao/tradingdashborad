import streamlit as st
import streamlit.components.v1 as components


# =====================================================================
# ⏮️⏭️ 族群導覽：上一個/下一個 按鈕 + 鍵盤快捷鍵（← → 或 [ ]）
#   快捷鍵以 JS 監聽父文件 keydown，再點擊對應按鈕（Streamlit 無原生熱鍵）。
#   焦點在輸入框/下拉選單時不攔截，避免干擾選單本身的方向鍵操作。
# =====================================================================
GROUP_KEY = "group_choice"


def _shift(groups, delta):
    """on_click callback：在 widget 重繪前改 session_state，故可直接改選單值。"""
    cur = st.session_state.get(GROUP_KEY, groups[0])
    if cur not in groups:
        cur = groups[0]
    st.session_state[GROUP_KEY] = groups[(groups.index(cur) + delta) % len(groups)]


def _inject_hotkeys():
    """綁定父文件 keydown。每次 rerun 重綁（舊 iframe 銷毀後其 handler 會失效）。"""
    components.html(
        """
<script>
(function () {
  try {
    var doc = window.parent.document;
    if (doc.__grpNavHandler) doc.removeEventListener('keydown', doc.__grpNavHandler);
    var handler = function (e) {
      if (e.ctrlKey || e.altKey || e.metaKey) return;
      var t = e.target, tag = ((t && t.tagName) || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select' ||
          (t && t.isContentEditable) ||
          (t && t.closest && t.closest('[data-baseweb="select"], [role="listbox"]'))) return;
      var key = null;
      if (e.key === 'ArrowLeft' || e.key === '[') key = 'grp_prev';
      if (e.key === 'ArrowRight' || e.key === ']') key = 'grp_next';
      if (!key) return;
      var btn = doc.querySelector('.st-key-' + key + ' button');
      if (btn) { e.preventDefault(); btn.click(); }
    };
    doc.__grpNavHandler = handler;
    doc.addEventListener('keydown', handler);
  } catch (err) { /* 跨來源受限時降級為純按鈕操作 */ }
})();
</script>
""",
        height=0,
    )


def render_group_nav(stocks_pool):
    """側邊欄族群選擇（選單＋前後切換＋快捷鍵），回傳目前族群名稱。"""
    groups = list(stocks_pool.keys())
    if st.session_state.get(GROUP_KEY) not in groups:
        st.session_state[GROUP_KEY] = groups[0]

    choice = st.sidebar.selectbox("選擇觀測族群", groups, key=GROUP_KEY)
    c1, c2 = st.sidebar.columns(2)
    c1.button("◀ 上一個", key="grp_prev", on_click=_shift, args=(groups, -1),
              width="stretch")
    c2.button("下一個 ▶", key="grp_next", on_click=_shift, args=(groups, 1),
              width="stretch")
    st.sidebar.caption(
        f"第 {groups.index(choice) + 1}/{len(groups)} 個族群　快捷鍵：← → 或 [ ]")
    _inject_hotkeys()
    return choice
