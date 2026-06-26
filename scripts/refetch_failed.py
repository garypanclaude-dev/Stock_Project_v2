"""
Refetch specific failed dates listed in data/audit/refetch_plan.json.

Throttle-heavy: 3s between API calls, 10s every 10 dates, to avoid TWSE/TPEX
rate-limit that caused empty responses during the original backfill.

Usage:
  python scripts/refetch_failed.py                # refetch all targets
  python scripts/refetch_failed.py --p0           # only P0 (TPEX 2024-03 ~ 2024-07)
  python scripts/refetch_failed.py --dry-run      # show targets only
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import sys
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from stock_fetcher import tw_db
from stock_fetcher.tw_market import fetch_for_date, fetch_institutional_for_date

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("refetch")

PLAN_PATH = ROOT / "data" / "audit" / "refetch_plan.json"

# Throttle settings — heavier than default API_DELAY_SECONDS=0.5
PER_DATE_SLEEP = 3.0    # between dates
BATCH_SIZE = 10
BATCH_PAUSE = 10.0      # extra pause every N dates


def _parse(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()


def load_targets(p0_only: bool) -> list[date]:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    targets: set[str] = set()
    targets.update(plan["daily_prices_tpex"])
    targets.update(plan["institutional_tpex"])
    if not p0_only:
        targets.update(plan["institutional_twse"])

    if p0_only:
        targets = {d for d in targets if d <= "2024-07-24"}

    return sorted(_parse(d) for d in targets)


def refetch_one(d: date) -> tuple[int, int]:
    """Returns (prices_saved, inst_saved)."""
    prices_n = 0
    inst_n = 0

    # ── Prices ──────────────────────────────────────────────────────
    try:
        result = fetch_for_date(d)
        if result["trading_day"] and result["prices"]:
            prices_n = tw_db.upsert_daily_prices(result["prices"])
    except Exception as e:
        logger.error("  prices %s failed: %s", d, e)

    time.sleep(PER_DATE_SLEEP / 2)

    # ── Institutional ───────────────────────────────────────────────
    try:
        result = fetch_institutional_for_date(d)
        if result["trading_day"] and result["records"]:
            inst_n = tw_db.upsert_institutional_trading(result["records"])
    except Exception as e:
        logger.error("  institutional %s failed: %s", d, e)

    return prices_n, inst_n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--p0", action="store_true", help="Only P0 (TPEX 2024-03-15 ~ 2024-07-24)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    targets = load_targets(args.p0)
    label = "P0 only" if args.p0 else "ALL failed dates"
    logger.info("Refetch plan (%s): %d dates", label, len(targets))
    logger.info("  first: %s  last: %s", targets[0], targets[-1])
    logger.info("  throttle: %.1fs/date, +%.1fs every %d dates",
                PER_DATE_SLEEP, BATCH_PAUSE, BATCH_SIZE)

    if args.dry_run:
        for d in targets:
            logger.info("  would refetch: %s", d)
        return

    tw_db.init_db()
    total_prices = 0
    total_inst = 0
    started = time.time()

    for i, d in enumerate(targets, 1):
        prices_n, inst_n = refetch_one(d)
        total_prices += prices_n
        total_inst += inst_n
        logger.info("[%d/%d] %s  prices=%d  inst=%d", i, len(targets), d, prices_n, inst_n)

        if i < len(targets):
            time.sleep(PER_DATE_SLEEP)
            if i % BATCH_SIZE == 0:
                logger.info("  -- batch pause %.0fs --", BATCH_PAUSE)
                time.sleep(BATCH_PAUSE)

    elapsed = time.time() - started
    logger.info("=" * 60)
    logger.info("Done in %.0fs.  Total: prices=%d, inst=%d", elapsed, total_prices, total_inst)


if __name__ == "__main__":
    main()
