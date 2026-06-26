"""
Audit DB completeness across all tables.

Outputs a df.info()-style report plus three artifacts under data/audit/:
  - daily_prices_missing.txt   : trading days with < threshold stocks
  - institutional_missing.txt  : days where TWSE or TPEX institutional fetch failed
  - refetch_plan.json          : structured task list for the refetch step

Usage:
  python scripts/audit_db.py
  python scripts/audit_db.py --quiet   (skip console table, write files only)
"""
from __future__ import annotations

import argparse
import io
import json
import sqlite3
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "tw_market.db"
OUT_DIR = ROOT / "data" / "audit"

# Thresholds
PRICE_MIN_PER_DAY = 1500          # normal: ~1800; below this → likely TPEX missing
TWSE_INST_MIN_PER_DAY = 800       # normal: ~1010
TPEX_INST_MIN_PER_DAY = 500       # normal: ~750


def audit() -> dict:
    c = sqlite3.connect(DB_PATH)

    report: dict = {"tables": {}, "anomalies": {}}

    # ── Table-level summary ─────────────────────────────────────────
    specs = [
        ("companies",                 None,         "symbol", None),
        ("daily_prices",              "date",       "symbol", "date"),
        ("institutional_trading",     "date",       "symbol", "date"),
        ("monthly_revenue",           "year_month", "symbol", "year_month"),
        ("shareholder_concentration", "date",       "symbol", "date"),
    ]
    for tbl, date_col, sym_col, range_col in specs:
        rows = c.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        nsym = c.execute(f"SELECT COUNT(DISTINCT {sym_col}) FROM {tbl}").fetchone()[0]
        ndt = c.execute(f"SELECT COUNT(DISTINCT {date_col}) FROM {tbl}").fetchone()[0] if date_col else 0
        if range_col:
            mn, mx = c.execute(f"SELECT MIN({range_col}), MAX({range_col}) FROM {tbl}").fetchone()
        else:
            mn = mx = None
        report["tables"][tbl] = {
            "rows": rows, "symbols": nsym, "dates": ndt, "min_date": mn, "max_date": mx
        }

    # ── daily_prices per-day count ──────────────────────────────────
    price_per_day = c.execute(
        "SELECT date, COUNT(*) FROM daily_prices GROUP BY date ORDER BY date"
    ).fetchall()
    price_low = [(d, n) for d, n in price_per_day if n < PRICE_MIN_PER_DAY]
    report["anomalies"]["daily_prices_low"] = [
        {"date": d, "count": n} for d, n in price_low
    ]

    # ── institutional_trading per-day (TWSE / TPEX breakdown) ──────
    inst_per_day = c.execute("""
      SELECT i.date,
        SUM(CASE WHEN co.market='TWSE' THEN 1 ELSE 0 END) AS twse,
        SUM(CASE WHEN co.market='TPEX' THEN 1 ELSE 0 END) AS tpex,
        COUNT(*) AS total
      FROM institutional_trading i
      LEFT JOIN companies co ON co.symbol = i.symbol
      GROUP BY i.date ORDER BY i.date
    """).fetchall()
    inst_bad = []
    for d, tw, tp, tot in inst_per_day:
        failures = []
        if tw < TWSE_INST_MIN_PER_DAY: failures.append("TWSE")
        if tp < TPEX_INST_MIN_PER_DAY: failures.append("TPEX")
        if failures:
            inst_bad.append({"date": d, "twse": tw, "tpex": tp, "total": tot, "failed": failures})
    report["anomalies"]["institutional_bad"] = inst_bad

    # ── Date alignment ─────────────────────────────────────────────
    pd_set = {r[0] for r in c.execute("SELECT DISTINCT date FROM daily_prices")}
    inst_set = {r[0] for r in c.execute("SELECT DISTINCT date FROM institutional_trading")}
    report["anomalies"]["price_only_dates"] = sorted(pd_set - inst_set)
    report["anomalies"]["inst_only_dates"] = sorted(inst_set - pd_set)

    # ── Build refetch plan ─────────────────────────────────────────
    refetch_plan = {
        "daily_prices_tpex": [a["date"] for a in report["anomalies"]["daily_prices_low"]],
        "institutional_tpex": [a["date"] for a in inst_bad if "TPEX" in a["failed"]],
        "institutional_twse": [a["date"] for a in inst_bad if "TWSE" in a["failed"]],
    }
    report["refetch_plan"] = refetch_plan

    return report


def print_report(report: dict) -> None:
    print("=" * 78)
    print("TW_MARKET.DB Audit Report")
    print("=" * 78)

    print("\n[1] Table summary")
    print("-" * 78)
    print(f"{'Table':<28}{'Rows':>10}{'Symbols':>10}{'Dates':>8}  Date Range")
    print("-" * 78)
    for tbl, s in report["tables"].items():
        rng = f"{s['min_date']} -> {s['max_date']}" if s['min_date'] else "-"
        print(f"{tbl:<28}{s['rows']:>10}{s['symbols']:>10}{s['dates']:>8}  {rng}")

    bad_prices = report["anomalies"]["daily_prices_low"]
    print(f"\n[2] daily_prices anomalies (<{PRICE_MIN_PER_DAY} stocks/day): {len(bad_prices)} 日")
    for a in bad_prices[:15]:
        print(f"    {a['date']}: {a['count']} 檔")
    if len(bad_prices) > 15:
        print(f"    ... ({len(bad_prices) - 15} more)")

    bad_inst = report["anomalies"]["institutional_bad"]
    print(f"\n[3] institutional_trading anomalies: {len(bad_inst)} 日")
    print(f"    {'date':<12}{'TWSE':>6}{'TPEX':>6}{'total':>7}  failed")
    for a in bad_inst:
        print(f"    {a['date']:<12}{a['twse']:>6}{a['tpex']:>6}{a['total']:>7}  {'+'.join(a['failed'])}")

    print(f"\n[4] Date alignment")
    print(f"    price-only dates: {report['anomalies']['price_only_dates']}")
    print(f"    inst-only dates : {report['anomalies']['inst_only_dates']}")

    plan = report["refetch_plan"]
    print(f"\n[5] Refetch plan")
    print(f"    daily_prices (TPEX) : {len(plan['daily_prices_tpex'])} 日")
    print(f"    institutional (TPEX): {len(plan['institutional_tpex'])} 日")
    print(f"    institutional (TWSE): {len(plan['institutional_twse'])} 日")


def write_artifacts(report: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(OUT_DIR / "daily_prices_missing.txt", "w", encoding="utf-8") as f:
        f.write(f"# daily_prices days with < {PRICE_MIN_PER_DAY} stocks\n")
        for a in report["anomalies"]["daily_prices_low"]:
            f.write(f"{a['date']}\t{a['count']}\n")

    with open(OUT_DIR / "institutional_missing.txt", "w", encoding="utf-8") as f:
        f.write("# institutional_trading days where TWSE or TPEX fetch failed\n")
        f.write("# date\tTWSE\tTPEX\ttotal\tfailed\n")
        for a in report["anomalies"]["institutional_bad"]:
            f.write(f"{a['date']}\t{a['twse']}\t{a['tpex']}\t{a['total']}\t{'+'.join(a['failed'])}\n")

    with open(OUT_DIR / "refetch_plan.json", "w", encoding="utf-8") as f:
        json.dump(report["refetch_plan"], f, indent=2, ensure_ascii=False)

    print(f"\n[+] Artifacts written to {OUT_DIR}")


def main():
    parser = argparse.ArgumentParser(description="Audit DB completeness")
    parser.add_argument("--quiet", action="store_true", help="Skip console output, write files only")
    args = parser.parse_args()

    report = audit()
    if not args.quiet:
        print_report(report)
    write_artifacts(report)


if __name__ == "__main__":
    main()
