"""
Retry TPEX daily-quotes fetch for dates that failed with "Response ended
prematurely" during the P0 refetch.

Strategy:
  - Read refetch_plan.json → take dates from daily_prices_tpex
  - For each date, call _fetch_tpex_daily_for_date with up to MAX_RETRIES,
    exponential backoff between attempts
  - Skip dates already at full TPEX coverage (TPEX rows ≥ 700) to avoid
    redoing successes
  - Upsert only the TPEX rows (TWSE already complete)

Usage:
  python scripts/retry_tpex_daily.py
  python scripts/retry_tpex_daily.py --dry-run
"""
from __future__ import annotations

import argparse
import io
import json
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
from stock_fetcher.tw_market import _fetch_tpex_daily_for_date

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("retry_tpex")

PLAN_PATH = ROOT / "data" / "audit" / "refetch_plan.json"
DB_PATH = ROOT / "data" / "tw_market.db"

MAX_RETRIES = 4
INITIAL_BACKOFF = 5.0    # seconds, doubled each retry
PER_DATE_PAUSE = 4.0
TPEX_HEALTHY_THRESHOLD = 700  # if DB already has >= this many TPEX rows, skip


def _parse(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()


def tpex_count_in_db(c: sqlite3.Connection, d: date) -> int:
    return c.execute("""
      SELECT COUNT(*) FROM daily_prices p
      LEFT JOIN companies co ON co.symbol = p.symbol
      WHERE p.date = ? AND co.market = 'TPEX'
    """, (d.isoformat(),)).fetchone()[0]


def fetch_with_retry(d: date) -> list[dict]:
    backoff = INITIAL_BACKOFF
    for attempt in range(1, MAX_RETRIES + 1):
        rows = _fetch_tpex_daily_for_date(d)
        if rows:
            if attempt > 1:
                logger.info("    succeeded on attempt %d (%d rows)", attempt, len(rows))
            return rows
        if attempt < MAX_RETRIES:
            logger.warning("    attempt %d empty, sleeping %.1fs", attempt, backoff)
            time.sleep(backoff)
            backoff *= 2
    return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    targets = sorted(_parse(d) for d in plan["daily_prices_tpex"])
    logger.info("Loaded %d candidate dates from refetch_plan.json", len(targets))

    conn = sqlite3.connect(DB_PATH)
    pending: list[date] = []
    for d in targets:
        n = tpex_count_in_db(conn, d)
        if n >= TPEX_HEALTHY_THRESHOLD:
            logger.info("  skip %s (already has %d TPEX rows)", d, n)
        else:
            pending.append(d)
    logger.info("Need retry: %d dates", len(pending))

    if args.dry_run:
        for d in pending:
            logger.info("  would retry: %s", d)
        return

    tw_db.init_db()
    success = 0
    still_failed: list[date] = []

    for i, d in enumerate(pending, 1):
        logger.info("[%d/%d] %s", i, len(pending), d)
        rows = fetch_with_retry(d)
        if rows:
            n = tw_db.upsert_daily_prices(rows)
            logger.info("  upserted %d TPEX rows", n)
            success += 1
        else:
            logger.error("  still failed after %d attempts", MAX_RETRIES)
            still_failed.append(d)
        if i < len(pending):
            time.sleep(PER_DATE_PAUSE)

    logger.info("=" * 60)
    logger.info("Done. Success: %d/%d", success, len(pending))
    if still_failed:
        logger.warning("Still failed: %s", [d.isoformat() for d in still_failed])


if __name__ == "__main__":
    main()
