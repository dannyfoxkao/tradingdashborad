# 紅K順風車／波動率框架移植計畫（移植完成後移除根目錄平面模組）

## Context

PR #1 的遺留 TODO：平面版（根目錄 13 個 .py）承載著另一線開發的「紅K順風車」策略——點火掃描、回測、門檻掃描與 `volatility_framework.md` 規範文件。兩套架構目前共存（ruff 排除平面模組）。本計畫把策略線完整移植進 `trading_dashboard/` 套件（TDD），最後刪除全部平面模組，回到單一架構。

**探索結論（兩個 Explore agent + 人工複核）**：移植面遠大於「三個具名工具」——真正的核心是平面 `data.py` 的重型指標管線（還原股價、處置剔除法、SNR/ATR%/翻轉率等 16 個策略欄位、400 天 warmup、MA120/200/RSI14/ATR14/四段動能/前高前低）與 `analysis.red_k_tailwind_signals` 引擎（158 行進出場狀態機）。**套件版資料層完全沒有這些**。另外平面版 `evaluate_signals` 多了第 6 買訊「帶量破前高」（套件版漏了）、點火規則在三處重複實作（語義還不一致）、`compute_momentum` 同名不同義（個股動能 vs 族群占比）。

**使用者決策**：① 繼續堆在 `feat/package-architecture`（push 後 PR #1 自動更新）；② 休眠函式（classify_long_term、個股動能）一併移植（個股版改名 `stock_momentum`）。

**技術決策（設計定案）**：統一重型 fetch 管線（FinMind call 數不變、快取共用、所有面板受益）；量能缺值統一 NaN（棄平面版偽造 1,000,000；NaN 使點火條件保守地不觸發）；點火判定收斂為單一事實來源（採 `volma>0` 防護——三副本中兩份有、且保守正確）；回測引擎純函式進套件（計覆蓋率）、CLI 殼進 `tools/`；`volatility_framework.md` → `docs/`。

## 實碼勘誤（測試須以此為準，已人工驗證 analysis.py:340-497）

1. `red_k_tailwind_signals(df, chg_thr=6.5, vol_mult=1.5, atr_trail_mult=2.0, reentry_on_new_high=False, limit_up_thr=9.5, require_close_high=True, entry_filter=None)`——**沒有** `exit_regime` 參數，性質切換出場恆開。
2. 買點 price 取當日 **Low**、賣點/警示取當日 **High**（圖表標記位置用）；回測配對則用 Close。
3. 處置日 `continue`：不進不出、不更新峰值、trail 留 NaN。
4. 同日雙出場 reason join 順序：「性質切換SNR<0／2×ATR移動停利」。
5. 進場需 `ATR14_clean` 有限值；「第一根」= `_ignite(i) and not (i>0 and _ignite(i-1))`。
6. 平面 `_ignite` 缺 `volma>0` 防護（volma=0 時恆真誤點火）→ 統一版加上（commit 說明記為有意識統一）。
7. B6（analysis.py:296-302）：`not in_disp AND Close>PriorHigh20 AND prev_Close≤prev_PriorHigh20 AND vr≥1.5`（vr 用 Vol_MA20 非 clean）。
8. 平面 grid 徽章寫死「進場 {nb}/5」但實有 6 買訊 → 套件以 `signals.MAX_BUY_SIGNALS = 6` 導出。
9. `sweep_limitup.summarize` 空清單 ZeroDivision + dead `import itertools` → 合併時採 sweep_mabull 的有防護版。
10. 平面處置日曆存檔非原子 → 套件版改用 `persistence.atomic_write_csv`。

## 模組佈局

| 模組 | 內容 |
|---|---|
| `trading_dashboard/vol_framework.py`（新 ~150L） | `back_adjust`（還原股價：close 跳動 <0.88/>1.13 回溯調整）、`apply_vol_framework(df, windows)`（處置剔除法 §5 + 16 個策略欄位；處置窗**參數注入**、純函式） |
| `trading_dashboard/strategy.py`（新 ~220L） | `TailwindSeries(NamedTuple)`＋`prepare_series(df)`（欄位回退階梯唯一實作）、`is_ignition(s,i,...)`／`ignition_tag(s,i,...)`（點火唯一事實來源）、`red_k_tailwind_signals`（拆 `_run_state_machine`/`_collect_warns`/`_latest_status`，每函式 <50 行；回傳結構與平面逐鍵相同） |
| `trading_dashboard/backtest.py`（新 ~230L） | `trades_from_signals`、`trade_returns`、`summarize_returns`（含空防護）、`summarize_overall`、`ignition_events`（用 strategy 判定）、`synchrony`、`market_weather(start,end,fetch_index)`（注入）、`regime_split`、`build_universe`（重用 `config.load_stock_config`）、`load_cached_frames` |
| `trading_dashboard/indicators.py`（238→~430L） | 加 `rsi`、`atr`、`enrich_heavy`（MA120/200、RSI14、Ret_20/60/120/240、ATR14、PriorHigh/Low{20,60}——PriorHigh 用 shift(1) 不看未來）、`compute_atr_stop`、`compute_support_resistance`、`classify_long_term`、`stock_momentum`（**改名**自平面 per-stock compute_momentum） |
| `trading_dashboard/signals.py` | B6 帶量破前高（`last.get("PriorHigh20")` 防缺欄）、`MAX_BUY_SIGNALS = 6` |
| `data_sources/disposition.py`（+~55L） | `load/save/merge_disposition_calendar`（原子寫入、失敗僅 log）、`disposition_mask(index, windows)`（chart_grid 委派去重）、`fetch_disposition_map` 升級＝live ∪ 本地累積並寫回（已解除的處置保留供回測剔除） |
| `data_sources/finmind.py`（+~35L） | `_load_finmind_token(path=FINMIND_TOKEN_FILE)`（json 檔優先→env）、重型管線（見 P1c） |
| `trading_dashboard/ui/today_panel.py`（新 ~140L） | 今日點火掃描（自 ui_today 移植，改用 strategy 共用判定＋prefetch_many） |
| `trading_dashboard/ui/chart_grid.py`（→~380L） | 順風車覆蓋層（見 P3b） |
| `tools/backtest_tailwind.py`、`tools/sweep_limitup.py`、`tools/sweep_mabull.py` | CLI 殼：argparse、pickle 快取續傳、print 報表（CLI 允許 print）、`sys.path` bootstrap＋utf-8 reconfigure；實驗定義（PERIODS/CONFIGS/make_filter）留在工具 |
| `docs/volatility_framework.md` | `git mv`；程式 docstring 引用 § 條款號 |

**處置日曆接線**：`finmind.fetch_finmind_data` 內部呼叫已快取的 `fetch_disposition_map()`（不當參數注入——st.cache_data 會雜湊大 dict 且日曆累積時整批失效）；無循環匯入（disposition→config/http；vol_framework→config/numpy/pandas；finmind→indicators+vol_framework+disposition 單向）。

**新常數**：全部進 `trading_dashboard/config.py`——FINMIND_TOKEN_FILE、FINMIND_WARMUP_DAYS=400、BACK_ADJUST_DOWN/UP=0.88/1.13、DISPOSITION_CALENDAR_FILE、LONG_MA_WINDOWS=(120,200)、RSI_PERIOD=14、ATR_PERIOD=14、MOMENTUM_RET_WINDOWS=(20,60,120,240)、PRIOR_LEVEL_WINDOWS=(20,60)、VF_*（各 rolling (window,min_periods) 與分位數，註明 §2/§5）、TW_MIN_ROWS=25、TW_CHG_THR=6.5、TW_VOL_MULT=1.5、TW_LIMIT_UP_THR=9.5、TW_ATR_TRAIL_MULT=2.0、TW_SNR_TREND=0.15、TW_SNR_WARN_FLOOR=0.05、ATR_STOP_MULT=2.0、SR_WINDOW=60、BACKTEST_*（CACHE_DIR、MAX_HOLD=120、MIN_ROWS=40、RET_FLOOR=-95.0）、SYNC_WINDOWS=(0,3)、GROUP_RALLY_MIN=3、TODAY_LOOKBACK_OPTIONS=(1,3,5)、TODAY_PANEL_WINDOW_DAYS=120。

## 分階段（皆於 feat/package-architecture；每 commit 前 pytest+ruff+format+mypy 全綠）

### P1 資料層（3 commits）
- **P1a Token＋處置日曆**：測試先行——test_finmind 加 token 檔優先/壞檔回退 env ×3；test_disposition 加 calendar roundtrip/壞列跳過/merge 去重/保留已解除窗/live∪local/disposition_mask ×7。實作 finmind._load_finmind_token＋init_finmind；disposition 日曆三函式＋mask＋fetch 升級；chart_grid._disposition_mask 委派。→ `feat(data): FinMind token 檔案載入與處置日曆本地累積`
- **P1b 還原股價＋波動率框架**：新檔 tests/test_vol_framework.py——back_adjust（除權回溯×2/±10%內不動/邊界0.88·1.13/短資料 noop）；apply_vol_framework（處置日剔除+NaN 回填、縫合日 TR=H−L 手算驗證、跨縫 Ret1=NaN、Close20High dtype、<20 乾淨列 fallback、16 欄齊、Vol_MA20_clean 排除處置日、P80 min_periods）；test_indicators 加 rsi/atr/enrich_heavy（PriorHigh20 shift(1)）。實作 vol_framework.py＋indicators.rsi/atr/enrich_heavy。→ `feat(indicators): 還原股價與波動率框架欄位（處置剔除法）`
- **P1c 統一重型管線**：測試先行（FakeLoader 記錄 start_date）——warmup start=start−400d、切回後首列≥start 且 MA20 已成形、策略欄位齊、**Volume 缺值維持 NaN**、切回後空→None；既有測項維持綠。實作 fetch_finmind_data 拆 `_normalise_columns`＋`_compute_indicators`：rename→量額互補(NaN)→sort→back_adjust→enrich→enrich_heavy→apply_vol_framework(disposition)→切回 [start,end]。**簽名不變**（warmup 內部化，面板全免改）。test_finmind 的 `_isolate` fixture 加 patch `fetch_disposition_map`（裸 pytest 防連網）。→ `feat(data): fetch_finmind_data 統一重量級管線（暖身400日＋策略欄位）`

### P2 純邏輯（3 commits）
- **P2a B6**：test_signals 加 5 案例（觸發/處置抑制/量比不足/缺欄相容/昨已在上不觸發）；實作 _collect_buys＋MAX_BUY_SIGNALS=6。→ `feat(signals): B6 帶量破前高買訊`
- **P2b 策略引擎**（核心 TDD 檔 tests/test_strategy.py，~17 案例）：prepare_series 回退階梯/Ret1 補算/DispDay 預設；is_ignition Ⓐ路徑/Ⓑ免量路徑/require_close_high 開關/**volma≤0 或 NaN 不點火**/收紅必要；ignition_tag 三分支；引擎——首根限定/買 Low 賣 High/ATR NaN 不進場/處置日凍結/2×ATR trail 出場/SNR 制度出場/同日 reason 順序/entry_filter 否決/reentry 路徑/警示兩型/accel_mask/象限四態＋"—"/latest 欄位/最少 25 列/enrich-only df 優雅降級。實作 strategy.py。→ `feat(strategy): 紅K順風車狀態機與共用點火判定`
- **P2c 休眠四函式**：test_indicators 加 atr_stop/support_resistance/classify_long_term（MA200→120→60 遞補）/stock_momentum 案例。→ `feat(indicators): ATR停損／支撐壓力／長線濾網／個股動能`

### P3 UI（3 commits）
- **P3a 棄用修正**：`use_container_width=True→width="stretch"`——[leaderboard_panel.py:70](trading_dashboard/ui/leaderboard_panel.py:70)、[radar_panel.py:82](trading_dashboard/ui/radar_panel.py:82)、radar_panel.py:149。→ `fix(ui): st.dataframe 棄用參數改 width="stretch"`
- **P3b 網格牆覆蓋層**：test_chart_grid 加——徽章「/6」、MA200 虛線（成形才畫/全 NaN 不畫）＋圖例 ┈200、量柱 opacity 1.0、▲▼★ markers＋hovertext、trail 線、accel vrect 段數、壓/撐/停損 hlines、tailwind html 狀態、show_tailwind=False 全關。實作：`_render_card` 算 `tw/sr/atr_stop`；新增 `_tailwind_html`、`_add_tailwind_traces`、`_add_level_lines`；`render(..., show_tailwind=True)`；app.py 側欄 checkbox「🚗 標記『紅K順風車』買賣點」。smoke 加「紅K順風車」斷言。→ `feat(ui): 網格牆紅K順風車覆蓋層（買賣點／trail／壓撐停損／MA200）`
- **P3c 今日點火面板**：新檔 tests/test_today_panel.py（掃描 lookback 命中/處置日跳過/短資料/缺資料 missed/去重/齊發≥3/排序）；smoke＋interactions 都加 patch `today_mod.prefetch_many`，interactions 點全按鈕後斷言 `tw_scan_result` 留存 session_state。實作 ui/today_panel.py（radio (1,3,5) 預設 3、掃描鈕、3 metrics、齊發 banner、排序表、lookback 變更提示；判定走 strategy 共用；抓取改 prefetch_many）；app.py 排行之後渲染（視窗 today−120d）。→ `feat(ui): 今日『紅K順風車』點火掃描面板`

### P4 工具（2 commits）
- **P4a 回測引擎**：新檔 tests/test_backtest.py（配對/floor 過濾/空防護/summarize buckets/ignition_events trail+max_hold+處置跳過+volma=0 不點火/synchrony 玩具案例/market_weather 注入 fetch/regime_split asof/build_universe 排除+市場對映/load_cached_frames）。實作 trading_dashboard/backtest.py。→ `feat(backtest): 紅K順風車回測引擎純函式模組`
- **P4b CLI 殼＋文件**：`git mv volatility_framework.md docs/`；tools/ 三支 CLI（sys.path bootstrap、argparse --start/--end/--exclude/--sleep/--refresh、ensure_cache pickle 續傳、print_report；sweeps 只剩 PERIODS/CONFIGS/make_filter）；pyproject 加 `[tool.ruff.lint.per-file-ignores] "tools/*"=["E402"]`；CI mypy 改 `mypy trading_dashboard app.py tools`；驗證 `tools\backtest_tailwind.py --help` 不觸網。舊 backtest_cache pickle 相容（欄位為平面版產出、語義差異用 --refresh 重建，docstring 註明）。→ `feat(tools): 回測與門檻掃描 CLI 移入 tools/，共用套件引擎`

### P5 移除＋清理（2 commits）
- **P5a 刪平面模組**：移除前檢查——①`rg "^(from|import) (analysis|data|config|leaderboard|tradingdahsboard|backtest_tailwind|sweep_limitup|sweep_mabull|ui_grid|ui_leaderboard|ui_radar|ui_today|ui_weather)\b"` 命中僅限平面檔內部；②volatility_framework.md 引用只剩 docs/；③無殘留呼叫端。`git rm` 13 個平面 .py；pyproject 刪 extend-exclude 平面清單（僅留 .venv）；`ruff check .` 全 repo 收斂。→ `refactor: 移除根目錄平面模組，lint/型別全面納管`
- **P5b 文件**：README 更新（今日點火/覆蓋層功能列、架構樹、finmind_token.json 說明、tools/ 用法、disposition_calendar.csv 說明）；設計文件存 `docs/superpowers/specs/2026-07-13-tailwind-port-design.md`（本計畫內容）。→ `docs(readme): 紅K順風車策略線、今日點火面板與離線工具說明`

## 既有測試更動（意識性）
test_finmind（_isolate 加 disposition patch、FakeLoader 記 start_date）；test_app_smoke／test_app_interactions（加 today_panel.prefetch_many patch＋新斷言）；test_chart_grid（_build_figure 新參數預設 None、僅加測項）；其餘 13 檔不動。

## 風險
- **st.cache 失效**：fetch_finmind_data 改寫使記憶體快取重建（一次冷啟，預期行為）。
- **AppTest 點全按鈕**：today 掃描鈕會真跑 → 已規定 patch prefetch_many；config_editor 已有既有 patch。
- **mypy**：prepare_series 用 NamedTuple 固定 ndarray 型別消滅聯集；`_fin` 明確回 bool；預估少量顯式轉型即過。
- **覆蓋率**：新增 ~1000 行；純邏輯 90%+、UI 直測 70-80%，估 86.7%→84-86%，80 門檻有餘裕。最大破口 today_panel 渲染與 _tailwind_html 分支——已排直測。
- **FinMind 額度**：手動驗證用小族群；warmup 不增加 call 數（rows 變多而已）。

## 驗證
每階段：`pytest -q`＋`ruff check .`＋`ruff format --check .`＋`mypy trading_dashboard app.py`（P4b 起加 tools）。
最終：`pytest --cov=trading_dashboard`（≥80）；手動 `streamlit run app.py`——今日點火掃描（小族群）、網格牆覆蓋層開/關、壓撐停損線、MA200；`python tools/backtest_tailwind.py --help`；`git push`（PR #1 自動更新）。

## 關鍵檔案
- 移植來源：[analysis.py](analysis.py)（引擎 :340-497、B6 :296-302、休眠四函式）、[data.py](data.py)（token/back_adjust/vol_framework/日曆/warmup）、[ui_today.py](ui_today.py)、[ui_grid.py](ui_grid.py)（覆蓋層 :162-308）、[backtest_tailwind.py](backtest_tailwind.py)、[volatility_framework.md](volatility_framework.md)
- 落點：[trading_dashboard/config.py](trading_dashboard/config.py)（常數）、[data_sources/finmind.py](trading_dashboard/data_sources/finmind.py)、[data_sources/disposition.py](trading_dashboard/data_sources/disposition.py)、[indicators.py](trading_dashboard/indicators.py)、[signals.py](trading_dashboard/signals.py)、[ui/chart_grid.py](trading_dashboard/ui/chart_grid.py)、新檔 `vol_framework.py`/`strategy.py`/`backtest.py`/`ui/today_panel.py`/`tools/*`
