"""
Backfill institutional trading + TDCC shareholder data into SQLite.

Usage:
    python scripts/backfill_new_data.py                     # backfill all missing
    python scripts/backfill_new_data.py --inst-only          # institutional only
    python scripts/backfill_new_data.py --tdcc-only          # TDCC only
    python scripts/backfill_new_data.py --dry-run            # show plan, don't fetch
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stock_fetcher import tw_db
from stock_fetcher.tw_market import (
    fetch_institutional_for_date,
    fetch_shareholder_distribution,
    API_DELAY_SECONDS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill")


def backfill_institutional(dry_run: bool = False):
    """Backfill institutional trading for all trading days missing data."""
    trading_dates = tw_db.get_trading_dates()
    existing = tw_db.get_institutional_dates()
    missing = [d for d in trading_dates if d not in existing]

    logger.info(
        "Institutional: %d trading days total, %d already have data, %d to backfill",
        len(trading_dates), len(existing), len(missing),
    )

    if dry_run:
        logger.info("DRY RUN — would fetch %d dates: %s ... %s",
                     len(missing), missing[0] if missing else "N/A",
                     missing[-1] if missing else "N/A")
        return

    success = 0
    fail = 0
    for i, d in enumerate(missing):
        try:
            result = fetch_institutional_for_date(date.fromisoformat(d))
            if result["trading_day"] and result["records"]:
                n = tw_db.upsert_institutional_trading(result["records"])
                success += 1
                if (i + 1) % 10 == 0:
                    logger.info("  Progress: %d/%d done (%d records on %s)",
                                i + 1, len(missing), n, d)
            else:
                logger.debug("  %s: no data (holiday?)", d)
            time.sleep(API_DELAY_SECONDS)
        except Exception as e:
            logger.error("  %s FAILED: %s", d, e)
            fail += 1
            time.sleep(1)

    logger.info("Institutional backfill done: %d success, %d fail", success, fail)


def backfill_tdcc(dry_run: bool = False):
    """Backfill TDCC shareholder data for all Fridays in DB range."""
    trading_dates = tw_db.get_trading_dates()
    existing = tw_db.get_shareholder_dates()

    start = date.fromisoformat(trading_dates[0])
    end = date.fromisoformat(trading_dates[-1])

    # Generate all Fridays in range
    fridays = []
    d = start
    while d <= end:
        if d.weekday() == 4:
            fridays.append(d)
        d += timedelta(days=1)

    missing = [f for f in fridays if f.isoformat() not in existing]

    logger.info(
        "TDCC: %d Fridays in range, %d already have data, %d to backfill",
        len(fridays), len(existing), len(missing),
    )

    if dry_run:
        logger.info("DRY RUN — would fetch %d Fridays: %s ... %s",
                     len(missing),
                     missing[0].isoformat() if missing else "N/A",
                     missing[-1].isoformat() if missing else "N/A")
        return

    success = 0
    fail = 0
    for i, friday in enumerate(missing):
        try:
            records = fetch_shareholder_distribution(friday)
            if records:
                n = tw_db.upsert_shareholder_concentration(records)
                success += 1
                logger.info("  TDCC %s: %d stocks (week %d/%d)",
                            friday, n, i + 1, len(missing))
            else:
                logger.info("  TDCC %s: no data (not a publication date?)", friday)
            time.sleep(API_DELAY_SECONDS)
        except Exception as e:
            logger.error("  TDCC %s FAILED: %s", friday, e)
            fail += 1
            time.sleep(2)

    logger.info("TDCC backfill done: %d success, %d fail", success, fail)


def main():
    parser = argparse.ArgumentParser(description="Backfill new data sources")
    parser.add_argument("--inst-only", action="store_true", help="Institutional only")
    parser.add_argument("--tdcc-only", action="store_true", help="TDCC only")
    parser.add_argument("--dry-run", action="store_true", help="Show plan only")
    args = parser.parse_args()

    do_inst = not args.tdcc_only
    do_tdcc = not args.inst_only

    if do_inst:
        backfill_institutional(dry_run=args.dry_run)

    if do_tdcc:
        backfill_tdcc(dry_run=args.dry_run)

    # Summary
    inst_count = len(tw_db.get_institutional_dates())
    tdcc_count = len(tw_db.get_shareholder_dates())
    rev_months = sorted(tw_db.get_revenue_months())
    logger.info("DB state: institutional=%d days, TDCC=%d weeks, revenue=%s",
                inst_count, tdcc_count, rev_months)


if __name__ == "__main__":
    main()
