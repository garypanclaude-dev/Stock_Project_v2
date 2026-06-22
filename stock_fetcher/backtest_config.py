"""
Backtest configuration constants.

All tuneable parameters for the forward-return backtester are defined here
so they can be adjusted without modifying engine logic.
"""

# ── 前瞻報酬天數 ──────────────────────────────────────────────────────────────
FORWARD_DAYS = [1, 3, 5, 10, 20]   # 買進後第 N 個交易日的收盤價報酬率

# ── 篩選器參數 ──────────────────────────────────────────────────────────────
TOP_N = 20                          # 每日取篩選器前 N 名

# ── 回測區間 ──────────────────────────────────────────────────────────────────
WARM_UP_DAYS = 120                  # 篩選器暖機天數（BB 120 日回溯；MA200 為前置過濾，資料不足時自動跳過）
BENCHMARK_SYMBOL = "0050.TW"        # 基準指標（元大台灣50 ETF）
