"""
ETF 歷史價格手動修補腳本。

用途：彌補 yfinance 對某些 ETF 分割事件的回溯不完整（例如 0050.TW 2025/6/18
進行 1:4 分割，但 yfinance 只把 2014/1/2 以後的歷史價 ÷4，2014/1/2 之前未調整）。

設計：
- PATCHES 為硬編碼修補規則清單，每筆對應一個獨立的歷史修補
- 直接覆寫 etf_price_daily 的 open/high/low/close/adj_close ÷ factor、volume × factor
- 寫入 etf_split_adjustments 稽核紀錄（idempotent，重跑同一筆會跳過）
- 不備份原始資料（依使用者要求）

執行：
    python -m scripts.patch_etf_history
"""
from __future__ import annotations

import logging
from datetime import datetime

from stock_fetcher import etf_db

logger = logging.getLogger(__name__)


PATCHES = [
    {
        "symbol": "0050.TW",
        "split_date": "2025-06-18",
        "factor": 4,
        "adjustment_type": "manual_backfill",
        "date_range_start": None,         # 從歷史起點
        "date_range_end": "2014-01-01",   # 到 2014-01-01 為止（含）
        "note": "yfinance 對 2025/6/18 1:4 分割的回溯調整只到 2014/1/2，"
                "更早的歷史價未被 ÷4。手動補齊 2014-01-01 之前資料。",
    },
]


def apply_patches() -> list[dict]:
    """對每筆 PATCH 套用修補並寫入稽核紀錄。回傳執行摘要。"""
    results = []
    now_iso = datetime.utcnow().isoformat(timespec="seconds")

    for patch in PATCHES:
        existing = etf_db.list_split_adjustments(patch["symbol"])
        already = any(
            a["split_date"] == patch["split_date"]
            and (a["date_range_start"] or None) == patch["date_range_start"]
            and (a["date_range_end"] or None) == patch["date_range_end"]
            for a in existing
        )
        if already:
            results.append({**patch, "status": "skipped (already applied)"})
            logger.info("Skip %s: already patched", patch["symbol"])
            continue

        rows_affected = etf_db.apply_price_factor(
            symbol=patch["symbol"],
            factor=patch["factor"],
            date_range_start=patch["date_range_start"],
            date_range_end=patch["date_range_end"],
        )

        etf_db.insert_split_adjustment({
            "symbol": patch["symbol"],
            "split_date": patch["split_date"],
            "factor": patch["factor"],
            "adjustment_type": patch["adjustment_type"],
            "date_range_start": patch["date_range_start"],
            "date_range_end": patch["date_range_end"],
            "rows_affected": rows_affected,
            "applied_at": now_iso,
            "note": patch["note"],
        })

        results.append({**patch, "rows_affected": rows_affected, "status": "applied"})
        logger.info("Applied %s: %d rows ÷ %g (range: %s ~ %s)",
                    patch["symbol"], rows_affected, patch["factor"],
                    patch["date_range_start"] or "始", patch["date_range_end"] or "今")

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    results = apply_patches()
    print("\n===== Patch Summary =====")
    for r in results:
        print(f"  {r['symbol']:>10s}  {r['status']:>30s}  "
              f"rows={r.get('rows_affected', '-')}  factor=÷{r['factor']}")
