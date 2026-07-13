"""集中設定：路徑、常數、門檻、設定檔載入/驗證、logging。

本模組刻意不相依 Streamlit，方便單元測試。所有「魔術數字」皆於此命名集中。
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from zoneinfo import ZoneInfo

from .persistence import atomic_write_text

# ──────────────────────────────────────────────────────────────────
# 路徑：錨定於專案根目錄（本檔位於 <root>/trading_dashboard/config.py）
# 不依賴行程的當前工作目錄（CWD），避免換目錄啟動時找不到設定檔。
# ──────────────────────────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).resolve().parent.parent
CONFIG_PATH: Path = BASE_DIR / "stock_config.json"
LEADERBOARD_FILE: Path = BASE_DIR / "turnover_leaderboard.csv"
LEADERBOARD_HISTORY_FILE: Path = BASE_DIR / "leaderboard_history.csv"
SIGNALS_HISTORY_FILE: Path = BASE_DIR / "signals_history.csv"
DISPOSITION_CALENDAR_FILE: Path = BASE_DIR / "disposition_calendar.csv"  # 處置日曆本地累積（已 gitignore）
FINMIND_TOKEN_FILE: Path = BASE_DIR / "finmind_token.json"  # {"api_token": "..."}，已 gitignore

# ── 時區：台股以 Asia/Taipei（UTC+8）為準，避免主機時區造成抓錯交易日 ──
TZ_TAIPEI = ZoneInfo("Asia/Taipei")

# ── 一般數值常數 ──
HUNDRED_MILLION: float = 1e8  # 成交金額換算「億」
TOP_N: int = 20  # 上市/上櫃各取成交值前 N
LEADERBOARD_BUFFER_DAYS: int = 2  # 連續未進榜可緩衝保留的天數
MARKET_CLOSE_HOUR: int = 14  # 台股收盤 14:30
MARKET_CLOSE_MINUTE: int = 30

# ── 快取存活秒數（TTL）──
FINMIND_TTL: int = 600
BENCHMARK_TTL: int = 600
DISPOSITION_TTL: int = 3600

# ── 平行抓取 ──
PREFETCH_MAX_WORKERS: int = 8  # 同時對 FinMind 的最大併發數（兼顧速率限制）

# ── 均線視窗 ──
MA_WINDOWS: tuple[int, ...] = (5, 10, 20, 60)
VOL_MA_WINDOWS: tuple[int, ...] = (5, 20)
TURN_MA_WINDOWS: tuple[int, ...] = (5, 20)
VOL_STD_WINDOW: int = 20

# ── 趨勢研判門檻 ──
MIN_TREND_ROWS: int = 21  # 少於此列數視為資料不足（MA20 尚未成形）
TREND_SLOPE_LOOKBACK: int = 5  # MA20 斜率回看根數（從 5 根前到現在）
TREND_FLAT_SLOPE: float = -0.1  # 震盪(偏多) 容許的輕微負斜率下限
TREND_SHORT_SLOPE_LOOKBACK: int = 3  # 短均（MA5/MA10）斜率回看根數
TREND_BOTTOM_SLOPE_MIN: float = -0.3  # 底部翻揚容許的月線微跌下限 %
TREND_HEAD_SLOPE_MAX: float = 0.3  # 頭部鈍化的月線動能上限 %

# ── MACD / 大盤氣象台 ──
MACD_FAST: int = 12
MACD_SLOW: int = 26
MACD_SIGNAL: int = 9
WEATHER_MIN_ROWS: int = 35  # MACD(12,26,9)+月線可研判的最低列數
INDEX_LOOKBACK_DAYS: int = 150  # 指數固定回看天數（確保 MACD/月線成形，不受觀測天數影響）

# ── 交易一致性訊號門檻 ──
SIGNAL_MIN_ROWS: int = 6
SIGNAL_VOL_RATIO: float = 1.5  # 出量 / 糾結放量 的量比門檻
SIGNAL_BAND_MAX_PCT: float = 2.0  # 均線糾結帶寬上限 %
SIGNAL_RETEST_BIAS5: tuple[float, float] = (-3.0, 2.0)  # 多頭回測的 5 日乖離區間 %
SIGNAL_DARK_BODY_PCT: float = 3.0  # 高位大黑K 實體門檻 %
SIGNAL_DARK_BIAS20: float = 8.0  # 高位大黑K 的 20 日乖離門檻 %
SIGNAL_STEEP_SLOPE20: float = 2.0  # 飆股月線斜率門檻 %
SIGNAL_SLOW_SLOPE20: tuple[float, float] = (-0.5, 2.0)  # 緩漲月線斜率區間 %
SIGNAL_WEAK_CLOSE_POS: float = 0.4  # 收弱：收盤位於當日區間的位置比例
SIGNAL_OVERHEAT_BIAS5: float = 10.0  # 短線過熱乖離 %

# ── 訊號歷史前瞻報酬 ──
FORWARD_RETURN_DAYS: tuple[int, ...] = (5, 10, 20)  # 可選的 N 日後報酬

# ── 還原股價（台股 ±10% 日限外＝除權/分割等公司行為）──
BACK_ADJUST_DOWN: float = 0.88
BACK_ADJUST_UP: float = 1.13

# ── 重型指標（策略/長線研判）──
FINMIND_WARMUP_DAYS: int = 400  # 暖身天數：讓 MA200 / 12個月動能在顯示區左緣成形
LONG_MA_WINDOWS: tuple[int, ...] = (120, 200)
RSI_PERIOD: int = 14
ATR_PERIOD: int = 14
MOMENTUM_RET_WINDOWS: tuple[int, ...] = (20, 60, 120, 240)  # ~1/3/6/12 個月
PRIOR_LEVEL_WINDOWS: tuple[int, ...] = (20, 60)  # 前高前低視窗

# ── 波動率框架（docs/volatility_framework.md §2/§5；(window, min_periods)）──
VF_MIN_CLEAN_ROWS: int = 20  # 剔除後低於此列數 → 放棄剔除（避免全空）
VF_ATR_FAST: tuple[int, int] = (5, 3)
VF_ATR_SLOW: tuple[int, int] = (14, 8)
VF_RET_ROLL: tuple[int, int] = (20, 15)
VF_P80_YEAR: tuple[int, int] = (252, 60)  # 一年 P80
VF_P80_WARN: tuple[int, int] = (120, 40)  # 120日 P80（警示層）
VF_P80_Q: float = 0.80
VF_RETSTD_Q60: float = 0.60
VF_SNR5: tuple[int, int] = (5, 3)
VF_ER: tuple[int, int] = (10, 6)  # Kaufman 效率比
VF_FLIP: tuple[int, int] = (10, 6)  # 隔日翻轉率
VF_VOLMA: tuple[int, int] = (20, 10)  # 剔除後量能基準
VF_C20HIGH: tuple[int, int] = (20, 10)  # 收盤創 20 日新高

# ── 族群動能 ──
BULL_LABELS: frozenset[str] = frozenset({"強多", "底部翻揚", "震盪(偏多)"})
BEAR_LABELS: frozenset[str] = frozenset({"弱勢", "震盪(偏空)", "頭部鈍化"})
MOMENTUM_BEAR_ALERT: float = 50.0  # 空方占比 ≥ → 族群轉弱警示
MOMENTUM_BULL_ALERT: float = 60.0  # 多方占比 ≥ → 族群一起動

# ── 量能研判門檻（量比 vr 與 Z-Score）──
VOL_SURGE_RATIO: float = 2.5  # 爆量
VOL_SURGE_Z: float = 2.0
VOL_UP_RATIO: float = 1.5  # 放量
VOL_SHRINK_RATIO: float = 0.7  # 縮量
VOL_SHRINK_Z: float = -1.0
VOL_BASE_WINDOW: int = 20  # 量能基準：近 N 個非處置交易日均量

# ── 相對大盤 Alpha ──
ALPHA_WINDOW: int = 21  # 計算超額報酬的視窗（含起點，故 21 列得 20 日報酬）
ALPHA_BETA_MIN: float = 0.0
ALPHA_BETA_MAX: float = 3.0
ALPHA_STRONG: float = 5.0  # 顯著領先
ALPHA_LAG: float = -5.0  # 顯著落後

# ── HTTP 傳輸層（Session 重用 + 冪等 GET 重試）──
HTTP_RETRY_TOTAL: int = 2
HTTP_RETRY_BACKOFF: float = 0.3
HTTP_RETRY_STATUS: tuple[int, ...] = (500, 502, 503, 504)

# ── 市場排行抓取重試（交易日回走）──
MARKET_FETCH_MAX_RETRY: int = 4
MARKET_RETRY_JITTER: tuple[float, float] = (0.2, 0.8)  # 回走前的小抖動秒數

# ── FinMind 輕量重試 ──
FINMIND_RETRY_ATTEMPTS: int = 2
FINMIND_RETRY_BACKOFF: float = 0.5  # 秒，線性遞增

# ── UI 快取上限 ──
RANGEBREAKS_CACHE_MAX: int = 256  # rangebreaks 快取筆數上限（滿了整批清除）

# ── 對外請求預設標頭 ──
DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://www.twse.com.tw/",
    "X-Requested-With": "XMLHttpRequest",
}

logger = logging.getLogger("trading_dashboard")


class ConfigError(Exception):
    """設定檔不存在、格式錯誤或結構不符時拋出。"""


def configure_logging(level: int = logging.INFO) -> None:
    """設定根 logger（重複呼叫安全）。"""
    root = logging.getLogger("trading_dashboard")
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root.addHandler(handler)
    root.setLevel(level)


def parse_stock_id(ticker: str) -> str:
    """由 ticker（如 '2330.TW' / '5347.TWO'）取出純代號 '2330'。"""
    return ticker.split(".")[0].strip()


# 台股代號：4~6 位數字，ETF/特別股允許尾碼一個大寫字母（如 00981A）
TICKER_RE = re.compile(r"^\d{4,6}[A-Z]?$")
# 已知指數代號：非個股但屬合法設定（供大盤基準/氣象台使用）
KNOWN_INDEX_IDS: frozenset[str] = frozenset({"TAIEX", "TPEx"})


def classify_ticker(ticker: str) -> str:
    """ticker 三分類：'stock'（個股）/'index'（已知指數）/'invalid'（格式無效）。"""
    clean = parse_stock_id(ticker)
    if clean in KNOWN_INDEX_IDS:
        return "index"
    if TICKER_RE.match(clean):
        return "stock"
    return "invalid"


def save_stock_config(data: dict[str, dict[str, str]], path: Path | str = CONFIG_PATH) -> None:
    """驗證後原子性寫回設定檔；首次寫入前建立一次性 .bak 備份。

    驗證失敗直接拋出 :class:`ConfigError`，原檔分毫不動——保證任何
    編輯操作都不可能產生載入不了的設定檔。
    """
    _validate_stock_config(data)
    path = Path(path)
    bak = path.with_name(path.name + ".bak")
    if path.exists() and not bak.exists():
        shutil.copyfile(path, bak)  # 只保「最初」版本，之後不覆蓋
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def find_malformed_ids(stocks_pool: dict[str, dict[str, str]]) -> list[str]:
    """回傳格式異常（非股票代號、亦非已知指數）的 ticker 清單（去重、保序）。"""
    bad: list[str] = []
    for members in stocks_pool.values():
        for ticker in members:
            clean = parse_stock_id(ticker)
            if clean not in KNOWN_INDEX_IDS and not TICKER_RE.match(clean):
                bad.append(ticker)
    return list(dict.fromkeys(bad))


def load_stock_config(path: Path | str = CONFIG_PATH) -> dict[str, dict[str, str]]:
    """載入並驗證 stock_config.json。

    結構需為 ``{族群名稱: {代號: 顯示名稱}}``，且非空。
    任何不符之處皆拋出 :class:`ConfigError`，附帶清楚訊息（fail fast）。
    """
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"找不到設定檔：{path}")

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"設定檔 JSON 格式錯誤：{e}") from e
    except OSError as e:
        raise ConfigError(f"無法讀取設定檔 {path}：{e}") from e

    _validate_stock_config(data)
    return data


def _validate_stock_config(data: object) -> None:
    if not isinstance(data, dict) or not data:
        raise ConfigError("設定檔頂層必須是非空物件（族群 → {代號: 名稱}）。")
    for group, members in data.items():
        if not isinstance(members, dict) or not members:
            raise ConfigError(f"族群「{group}」的內容必須是非空物件 {{代號: 名稱}}。")
        for ticker, name in members.items():
            if not isinstance(ticker, str) or not isinstance(name, str):
                raise ConfigError(f"族群「{group}」中存在非字串的代號或名稱：{ticker!r} → {name!r}。")
