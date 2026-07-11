"""http.get_session（每執行緒 Session + 傳輸層重試）的單元測試。"""

import threading

from trading_dashboard.config import HTTP_RETRY_TOTAL
from trading_dashboard.data_sources.http import get_session


def test_same_thread_reuses_session():
    assert get_session() is get_session()


def test_different_threads_get_different_sessions():
    main_session = get_session()
    other: list = []

    t = threading.Thread(target=lambda: other.append(get_session()))
    t.start()
    t.join()

    assert other[0] is not main_session


def test_adapter_mounted_with_retry():
    session = get_session()
    adapter = session.get_adapter("https://www.twse.com.tw/")
    assert adapter.max_retries.total == HTTP_RETRY_TOTAL
    assert "GET" in adapter.max_retries.allowed_methods


def test_default_headers_applied():
    session = get_session()
    assert "Mozilla" in session.headers["User-Agent"]
