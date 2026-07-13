"""共用 HTTP Session：連線重用（免每次 TLS 握手）＋傳輸層重試（僅冪等 GET）。

requests.Session 非執行緒安全，故以 threading.local 每執行緒一個
（prefetch 執行緒池與市場並行抓取皆安全）。
"""

from __future__ import annotations

import threading

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import DEFAULT_HEADERS, HTTP_RETRY_BACKOFF, HTTP_RETRY_STATUS, HTTP_RETRY_TOTAL

_local = threading.local()


def get_session() -> requests.Session:
    """回傳目前執行緒的共用 Session（延遲建立）。"""
    session = getattr(_local, "session", None)
    if session is None:
        session = _build_session()
        _local.session = session
    return session


def _build_session() -> requests.Session:
    retry = Retry(
        total=HTTP_RETRY_TOTAL,
        backoff_factor=HTTP_RETRY_BACKOFF,
        status_forcelist=HTTP_RETRY_STATUS,
        allowed_methods=frozenset({"GET"}),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(DEFAULT_HEADERS)
    return session
