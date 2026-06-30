"""
22 檔台股 ETF 元資料（人工維護的靜態欄位）。

欄位說明：
  symbol            : yfinance 代號（含 .TW 後綴）
  name_zh           : 中文名稱
  category          : 'core' / 'monthly' / 'factor' / 'active' / 'benchmark'
  tracking_index    : 追蹤指數中文名（主動式 ETF 此欄為 None）
  expense_ratio     : 經理費 + 保管費，年化（0.0046 = 0.46%）
  payout_frequency  : 1=月配 / 3=季配 / 6=半年配 / 12=年配
  is_active         : True = 主動式 ETF

動態欄位（AUM、NAV、yield、fund_family、inception_date）由 yfinance 抓，
寫入 etf_meta 表，本檔不處理。

新增 / 修改 ETF 時：
  1. 加一筆 dict 到 ETF_CONFIGS
  2. 重啟 service（會自動 upsert 到 etf_meta）
詳見 docs/dca-simulator.md §2。
"""
from __future__ import annotations

ETF_CONFIGS: list[dict] = [
    # ── A. 核心高股息（5 檔） ─────────────────────────────────────────────────
    {
        "symbol": "0056.TW",
        "name_zh": "元大高股息",
        "category": "core",
        "tracking_index": "臺灣高股息指數",
        "expense_ratio": 0.0046,
        "payout_frequency": 3,
        "is_active": False,
    },
    {
        "symbol": "00878.TW",
        "name_zh": "國泰永續高股息",
        "category": "core",
        "tracking_index": "MSCI 臺灣 ESG 永續高股息精選 30 指數",
        "expense_ratio": 0.0051,
        "payout_frequency": 3,
        "is_active": False,
    },
    {
        "symbol": "00919.TW",
        "name_zh": "群益台灣精選高息",
        "category": "core",
        "tracking_index": "臺灣精選高息指數",
        "expense_ratio": 0.0055,
        "payout_frequency": 3,
        "is_active": False,
    },
    {
        "symbol": "00713.TW",
        "name_zh": "元大台灣高息低波",
        "category": "core",
        "tracking_index": "臺灣指數公司特選高股息低波動指數",
        "expense_ratio": 0.0055,
        "payout_frequency": 3,
        "is_active": False,
    },
    {
        "symbol": "00915.TW",
        "name_zh": "凱基優選高股息 30",
        "category": "core",
        "tracking_index": "臺灣多因子優選高股息 30 指數",
        "expense_ratio": 0.0040,
        "payout_frequency": 3,
        "is_active": False,
    },

    # ── B. 月配息（5 檔） ─────────────────────────────────────────────────────
    {
        "symbol": "00929.TW",
        "name_zh": "復華台灣科技優息",
        "category": "monthly",
        "tracking_index": "特選臺灣科技優息指數",
        "expense_ratio": 0.0060,
        "payout_frequency": 1,
        "is_active": False,
    },
    {
        "symbol": "00939.TW",
        "name_zh": "統一台灣高息動能",
        "category": "monthly",
        "tracking_index": "特選臺灣高息動能指數",
        "expense_ratio": 0.0060,
        "payout_frequency": 1,
        "is_active": False,
    },
    {
        "symbol": "00940.TW",
        "name_zh": "元大台灣價值高息",
        "category": "monthly",
        "tracking_index": "臺灣價值高息指數",
        "expense_ratio": 0.0034,
        "payout_frequency": 1,
        "is_active": False,
    },
    {
        "symbol": "00943.TW",
        "name_zh": "兆豐台灣電子成長高息",
        "category": "monthly",
        "tracking_index": "特選臺灣電子高息成長指數",
        "expense_ratio": 0.0045,
        "payout_frequency": 1,
        "is_active": False,
    },
    {
        "symbol": "00946.TW",
        "name_zh": "群益台灣科技高息成長",
        "category": "monthly",
        "tracking_index": "特選臺灣科技高息成長指數",
        "expense_ratio": 0.0050,
        "payout_frequency": 1,
        "is_active": False,
    },

    # ── C. 高息成長 / 因子型（3 檔） ─────────────────────────────────────────
    {
        "symbol": "00731.TW",
        "name_zh": "FH 富時高息低波",
        "category": "factor",
        "tracking_index": "富時臺灣高股息低波動指數",
        "expense_ratio": 0.0050,
        "payout_frequency": 3,
        "is_active": False,
    },
    {
        "symbol": "00701.TW",
        "name_zh": "國泰股利精選 30",
        "category": "factor",
        "tracking_index": "臺灣指數公司低波動股利精選 30 指數",
        "expense_ratio": 0.0034,
        "payout_frequency": 6,
        "is_active": False,
    },
    {
        "symbol": "00692.TW",
        "name_zh": "富邦公司治理",
        "category": "factor",
        "tracking_index": "臺灣公司治理 100 指數",
        "expense_ratio": 0.0032,
        "payout_frequency": 6,
        "is_active": False,
    },

    # ── D. 主動式 ETF（5 檔，2025-06 起發行） ────────────────────────────────
    {
        "symbol": "00980A.TW",
        "name_zh": "野村臺灣 SMART 主動式 ETF",
        "category": "active",
        "tracking_index": None,
        "expense_ratio": 0.0099,
        "payout_frequency": 3,
        "is_active": True,
    },
    {
        "symbol": "00981A.TW",
        "name_zh": "統一台灣高息成長主動式 ETF",
        "category": "active",
        "tracking_index": None,
        "expense_ratio": 0.0099,
        "payout_frequency": 1,
        "is_active": True,
    },
    {
        "symbol": "00982A.TW",
        "name_zh": "群益台灣優選主動式 ETF",
        "category": "active",
        "tracking_index": None,
        "expense_ratio": 0.0099,
        "payout_frequency": 3,
        "is_active": True,
    },
    {
        "symbol": "00984A.TW",
        "name_zh": "安聯臺灣高息成長主動式 ETF",
        "category": "active",
        "tracking_index": None,
        "expense_ratio": 0.0120,
        "payout_frequency": 3,
        "is_active": True,
    },
    {
        "symbol": "00985A.TW",
        "name_zh": "野村臺灣 50 主動式 ETF",
        "category": "active",
        "tracking_index": None,
        "expense_ratio": 0.0099,
        "payout_frequency": 3,
        "is_active": True,
    },

    # ── E. 對照組（4 檔） ────────────────────────────────────────────────────
    {
        "symbol": "0050.TW",
        "name_zh": "元大台灣 50",
        "category": "benchmark",
        "tracking_index": "臺灣 50 指數",
        "expense_ratio": 0.0032,
        "payout_frequency": 2,  # 半年配（2 次/年）
        "is_active": False,
    },
    {
        "symbol": "006208.TW",
        "name_zh": "富邦台 50",
        "category": "benchmark",
        "tracking_index": "臺灣 50 指數",
        "expense_ratio": 0.0024,
        "payout_frequency": 2,
        "is_active": False,
    },
    {
        "symbol": "00646.TW",
        "name_zh": "元大 S&P500",
        "category": "benchmark",
        "tracking_index": "S&P 500 指數",
        "expense_ratio": 0.0066,
        "payout_frequency": 12,
        "is_active": False,
    },
    {
        "symbol": "00692.TW",  # 與 C 組同檔；放這裡只供 list view 對照分組顯示
        # 真正的 config 以 C 組那筆為準（去重用 symbol）
        "name_zh": "富邦公司治理",
        "category": "benchmark",
        "tracking_index": "臺灣公司治理 100 指數",
        "expense_ratio": 0.0032,
        "payout_frequency": 6,
        "is_active": False,
    },
]


# 預設對照標的（DCA 模擬器強制對照）
DEFAULT_BENCHMARK = "0050.TW"


def get_config(symbol: str) -> dict | None:
    """以 symbol 為 key 取設定。重複 symbol 取第一筆（A/B/C 組為主，E 組僅顯示用）。"""
    seen: dict[str, dict] = {}
    for cfg in ETF_CONFIGS:
        seen.setdefault(cfg["symbol"], cfg)
    return seen.get(symbol)


def list_configs() -> list[dict]:
    """回傳所有 ETF 設定。E 組中與其他組重複的 symbol 會被保留作為對照顯示。"""
    return list(ETF_CONFIGS)


def list_unique_symbols() -> list[str]:
    """去重後的 symbol 清單，用於資料抓取。"""
    seen: set[str] = set()
    out: list[str] = []
    for cfg in ETF_CONFIGS:
        if cfg["symbol"] not in seen:
            seen.add(cfg["symbol"])
            out.append(cfg["symbol"])
    return out


if __name__ == "__main__":
    print(f"Total entries: {len(ETF_CONFIGS)}")
    print(f"Unique symbols: {len(list_unique_symbols())}")
    by_cat: dict[str, int] = {}
    for c in ETF_CONFIGS:
        by_cat[c["category"]] = by_cat.get(c["category"], 0) + 1
    for cat, n in by_cat.items():
        print(f"  {cat}: {n}")
