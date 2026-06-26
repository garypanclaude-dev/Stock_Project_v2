"""
回補全部歷史 TPEX 三大法人買賣超資料。

背景：
  _parse_tpex_institutional_row 原本欄位 mapping 錯誤
  （row[8-10] 是「外資合計」卻被當成「投信」讀），
  造成 DB 內所有 TPEX 個股 foreign_net == trust_net。
  Parser 已於本次修正，需重抓全部歷史以覆蓋錯誤資料。

策略：
  - 從 DB 抓出所有曾出現 TPEX 法人資料的交易日
  - 逐日 _fetch_tpex_institutional → upsert
  - 每筆失敗最多重試 MAX_RETRIES 次，指數 backoff
  - 每日完成後 sleep PER_DATE_PAUSE 秒，禮貌爬取

Usage:
  python scripts/refetch_tpex_institutional.py
  python scripts/refetch_tpex_institutional.py --dry-run
  python scripts/refetch_tpex_institutional.py --start 2025-01-01 --end 2026-06-30
"""
from __future__ import annotations

import argparse
import io
import logging
import sqlite3
import sys
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from stock_fetcher import tw_db
from stock_fetcher.tw_market import _fetch_tpex_institutional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("refetch_tpex_inst")

DB_PATH = ROOT / "data" / "tw_market.db"
MAX_RETRIES = 4
INITIAL_BACKOFF = 5.0
PER_DATE_PAUSE = 3.0
HEALTHY_THRESHOLD = 500  # 一日 TPEX 法人資料筆數低於此視為失敗


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def list_tpex_institutional_dates(
    conn: sqlite3.Connection,
    start: date | None,
    end: date | None,
) -> list[date]:
    """從 DB 取出所有曾有 TPEX 法人資料的日期。"""
    query = """
        SELECT DISTINCT i.date FROM institutional_trading i
        JOIN companies c ON c.symbol = i.symbol
        WHERE c.market = 'TPEX'
    """
    params: list = []
    if start:
        query += " AND i.date >= ?"
        params.append(start.isoformat())
    if end:
        query += " AND i.date <= ?"
        params.append(end.isoformat())
    query += " ORDER BY i.date"
    rows = conn.execute(query, params).fetchall()
    return [_parse_date(r[0]) for r in rows]


def fetch_with_retry(d: date) -> list[dict]:
    backoff = INITIAL_BACKOFF
    for attempt in range(1, MAX_RETRIES + 1):
        rows = _fetch_tpex_institutional(d)
        if rows and len(rows) >= HEALTHY_THRESHOLD:
            if attempt > 1:
                logger.info("    succeeded on attempt %d (%d rows)", attempt, len(rows))
            return rows
        if rows:
            logger.warning(
                "    attempt %d only %d rows (< %d threshold)",
                attempt, len(rows), HEALTHY_THRESHOLD,
            )
        if attempt < MAX_RETRIES:
            logger.warning("    retry in %.1fs", backoff)
            time.sleep(backoff)
            backoff *= 2
    return rows  # 回最後一次（可能不完整）


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=str, default=None, help="YYYY-MM-DD")
    parser.add_argument("--end", type=str, default=None, help="YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start = _parse_date(args.start) if args.start else None
    end = _parse_date(args.end) if args.end else None

    conn = sqlite3.connect(DB_PATH)
    dates = list_tpex_institutional_dates(conn, start, end)
    logger.info(
        "TPEX 法人資料回補目標：%d 個交易日 (%s ~ %s)",
        len(dates),
        dates[0].isoformat() if dates else "N/A",
        dates[-1].isoformat() if dates else "N/A",
    )

    if args.dry_run:
        for d in dates[:10]:
            logger.info("  would refetch: %s", d)
        if len(dates) > 10:
            logger.info("  ... 共 %d 個交易日", len(dates))
        return

    tw_db.init_db()
    success = 0
    insufficient: list[date] = []
    failed: list[date] = []
    total_upserted = 0

    for i, d in enumerate(dates, 1):
        logger.info("[%d/%d] %s", i, len(dates), d)
        rows = fetch_with_retry(d)
        if not rows:
            logger.error("  全失敗，跳過")
            failed.append(d)
        else:
            n = tw_db.upsert_institutional_trading(rows)
            total_upserted += n
            if len(rows) < HEALTHY_THRESHOLD:
                logger.warning("  upserted %d rows（不足 %d，記錄）", n, HEALTHY_THRESHOLD)
                insufficient.append(d)
            else:
                logger.info("  upserted %d rows", n)
            success += 1
        if i < len(dates):
            time.sleep(PER_DATE_PAUSE)

    logger.info("=" * 60)
    logger.info("完成。success=%d/%d, total_upserted=%d", success, len(dates), total_upserted)
    if insufficient:
        logger.warning("筆數不足日: %s", [d.isoformat() for d in insufficient])
    if failed:
        logger.error("全失敗日: %s", [d.isoformat() for d in failed])


if __name__ == "__main__":
    main()
