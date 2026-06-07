"""
Update Taiwan stock market history in SQLite.

Modes:
  (default)        Incremental: from latest DB date + 1 → today
  --full-check     Compare expected trading days vs DB, fill any gaps
  --date YYYY-MM-DD  Fetch one specific date
  --from / --to    Fetch a date range
  --backfill N     Backfill the last N trading days (use for first-time setup)
  --dry-run        Show what would be fetched, don't actually fetch

Usage examples:
  python scripts/update_tw_history.py
  python scripts/update_tw_history.py --backfill 60
  python scripts/update_tw_history.py --full-check
  python scripts/update_tw_history.py --date 2026-06-03
  python scripts/update_tw_history.py --from 2026-05-01 --to 2026-05-31 --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

# Allow running as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stock_fetcher import tw_db
from stock_fetcher.tw_market import fetch_for_date, fetch_industry_mapping

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("update_tw_history")


def _parse_date(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date format: {s} (expected YYYY-MM-DD)")


def _list_trading_days(start: date, end: date) -> list[date]:
    return tw_db.list_trading_days(start, end)


def _determine_dates(args) -> list[date]:
    """Return the list of dates to fetch based on CLI args."""
    today = date.today()

    if args.date:
        return [args.date]

    if args.from_date and args.to_date:
        return _list_trading_days(args.from_date, args.to_date)
    if args.from_date:
        return _list_trading_days(args.from_date, today)

    if args.backfill:
        days = []
        d = today
        while len(days) < args.backfill:
            if d.weekday() < 5:
                days.append(d)
            d -= timedelta(days=1)
        return sorted(days)

    if args.full_check:
        # Last 60 trading days, fill any missing
        end = today
        days = []
        d = end
        while len(days) < 60:
            if d.weekday() < 5:
                days.append(d)
            d -= timedelta(days=1)
        all_days = sorted(days)

        start_iso = all_days[0].isoformat()
        end_iso = all_days[-1].isoformat()
        existing = tw_db.get_existing_dates(start_iso, end_iso)
        missing = [d for d in all_days if d.isoformat() not in existing]
        return missing

    # Default: incremental from latest DB date + 1 to today
    latest = tw_db.get_latest_date()
    if latest is None:
        # DB is empty — bootstrap with 60 days
        logger.info("DB is empty. Bootstrapping with last 60 trading days.")
        days = []
        d = today
        while len(days) < 60:
            if d.weekday() < 5:
                days.append(d)
            d -= timedelta(days=1)
        return sorted(days)

    start = datetime.strptime(latest, "%Y-%m-%d").date() + timedelta(days=1)
    if start > today:
        return []
    return _list_trading_days(start, today)


def _refresh_companies():
    """Pull industry mapping and upsert companies table."""
    mapping = fetch_industry_mapping()
    if not mapping:
        logger.warning("Industry mapping is empty — skipping companies refresh")
        return 0

    companies = []
    for code, info in mapping.items():
        companies.append({
            "symbol": f"{code}.TW",
            "name": info["name"],
            "industry": info["industry"],
            "market": "TWSE",
        })
    affected = tw_db.upsert_companies(companies)
    logger.info("Companies upserted: %d", affected)
    return affected


def main():
    parser = argparse.ArgumentParser(
        description="Update TW stock history in SQLite (incremental gap-fill).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--full-check", action="store_true",
                        help="Check last 60 days for gaps, fill missing dates")
    parser.add_argument("--date", type=_parse_date,
                        help="Fetch one specific date (YYYY-MM-DD)")
    parser.add_argument("--from", dest="from_date", type=_parse_date,
                        help="Start date for range fetch (inclusive)")
    parser.add_argument("--to", dest="to_date", type=_parse_date,
                        help="End date for range fetch (inclusive)")
    parser.add_argument("--backfill", type=int, metavar="N",
                        help="Backfill the last N trading days")
    parser.add_argument("--skip-companies", action="store_true",
                        help="Don't refresh the companies table")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be fetched without actually fetching")
    args = parser.parse_args()

    tw_db.init_db()

    # 1. Refresh company info (cheap, only one API call)
    if not args.skip_companies and not args.dry_run:
        _refresh_companies()

    # 2. Determine which dates to fetch
    dates_to_fetch = _determine_dates(args)

    if not dates_to_fetch:
        logger.info("✅ Already up to date. Nothing to fetch.")
        stats = tw_db.get_stats()
        logger.info("DB stats: %s", stats)
        return

    logger.info("Plan: fetch %d date(s) → %s ... %s",
                len(dates_to_fetch), dates_to_fetch[0], dates_to_fetch[-1])

    if args.dry_run:
        for d in dates_to_fetch:
            logger.info("  would fetch: %s", d)
        logger.info("(dry-run) no data was actually fetched")
        return

    # 3. Fetch loop with per-day error isolation
    success_count = 0
    skipped_count = 0
    failed_dates = []

    for d in dates_to_fetch:
        try:
            result = fetch_for_date(d)
            if not result["trading_day"]:
                logger.info("  %s: non-trading day, skipped", d)
                skipped_count += 1
                continue

            prices = result["prices"]
            if not prices:
                logger.warning("  %s: empty data (possibly holiday)", d)
                skipped_count += 1
                continue

            affected = tw_db.upsert_daily_prices(prices)
            logger.info("  %s: ✅ %d stocks saved", d, affected)
            success_count += 1

        except Exception as e:
            logger.error("  %s: ❌ %s", d, e)
            failed_dates.append(d)

    # 4. Report
    logger.info("=" * 60)
    logger.info("Summary: %d ✅ saved | %d ⏭ skipped | %d ❌ failed",
                success_count, skipped_count, len(failed_dates))
    if failed_dates:
        logger.warning("Failed dates: %s", ", ".join(d.isoformat() for d in failed_dates))
        logger.warning("Re-run individually: python scripts/update_tw_history.py --date YYYY-MM-DD")

    stats = tw_db.get_stats()
    logger.info("DB stats: %s", stats)


if __name__ == "__main__":
    main()
