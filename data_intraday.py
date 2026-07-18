# -*- coding: utf-8 -*-
"""盤中即時報價：證交所 MIS API（免費、免登入；上市 tse_ / 上櫃 otc_ 同一端點）。
回傳欄位（每檔）：
  z 現價  y 昨收  o 開盤  h 最高  l 最低  v 累積量(張)  u 漲停價  w 跌停價  t 揭示時間
資料為約 5 秒快照；收盤後回傳當日最終值。"""
from datetime import datetime, time as dtime

import requests
import streamlit as st

_MIS = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
       "Referer": "https://mis.twse.com.tw/stock/index.jsp"}
_BATCH = 100          # 一次查詢檔數上限（URL 長度保守值）


def _fnum(x):
    try:
        f = float(x)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def fetch_realtime_quotes(tickers):
    """tickers: ['2330.TW', '5347.TWO', ...] → {股號: dict}。失敗的檔直接缺席。"""
    chs = []
    for tk in tickers:
        sid = tk.split(".")[0].strip()
        mkt = "otc" if tk.upper().endswith(".TWO") else "tse"
        chs.append(f"{mkt}_{sid}.tw")
    out = {}
    try:
        s = requests.Session()
        s.headers.update(_UA)
        s.get("https://mis.twse.com.tw/stock/index.jsp", timeout=10)   # 取 cookie
        for k in range(0, len(chs), _BATCH):
            r = s.get(_MIS, params={"ex_ch": "|".join(chs[k:k + _BATCH]),
                                    "json": "1", "delay": "0"}, timeout=15)
            for m in (r.json().get("msgArray") or []):
                sid = m.get("c")
                if not sid:
                    continue
                z = _fnum(m.get("z"))
                if z is None:                          # 尚無成交：退而用最佳買價
                    b = (m.get("b") or "").split("_")[0]
                    z = _fnum(b)
                out[sid] = {
                    "z": z, "y": _fnum(m.get("y")), "o": _fnum(m.get("o")),
                    "h": _fnum(m.get("h")), "l": _fnum(m.get("l")),
                    "v": _fnum(m.get("v")),            # 累積成交量(張)
                    "u": _fnum(m.get("u")), "w": _fnum(m.get("w")),
                    "t": m.get("t", ""), "name": m.get("n", ""),
                }
    except Exception:
        pass
    return out


def session_elapsed_fraction(quote_time=""):
    """台股 09:00–13:30 共 270 分鐘；回傳已走時段比例 (0, 1]。
    以「報價揭示時間 t」(HH:MM:SS) 為準——收盤後/假日快照 t=13:30 → 1（不投影）；
    解析失敗退回牆上時鐘。"""
    hh = mm = None
    try:
        parts = str(quote_time).split(":")
        hh, mm = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        now = datetime.now().time()
        hh, mm = now.hour, now.minute
    mins = (hh - 9) * 60 + mm
    if mins <= 0:
        return 1.0                      # 盤前（尚無當日資料）→ 不投影
    return max(0.02, min(1.0, mins / 270.0))
