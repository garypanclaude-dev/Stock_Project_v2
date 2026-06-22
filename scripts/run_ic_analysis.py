"""
CLI: Run IC analysis on the stock screener's 13 factors.

Usage:
    python scripts/run_ic_analysis.py
    python scripts/run_ic_analysis.py --output results/ic_report.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stock_fetcher.ic_analyzer import run_ic_analysis, FACTOR_NAMES


def main():
    parser = argparse.ArgumentParser(description="Screener factor IC analysis")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Save JSON results to this path")
    parser.add_argument("--cap", type=float, default=30.0,
                        help="Extreme return cap %% (default 30)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    result = run_ic_analysis(extreme_return_cap=args.cap)

    if "error" in result:
        print(f"ERROR: {result['error']}")
        sys.exit(1)

    # Print report
    print("=" * 80)
    print(f"IC Analysis Report — {result['period']['start']} ~ {result['period']['end']}")
    print(f"Trading days: {result['period']['trading_days']}")
    print("=" * 80)

    summary = result["summary"]
    horizons = sorted(summary.keys(), key=int)

    all_factors = FACTOR_NAMES + ["composite"]

    for h in horizons:
        print(f"\n{'─' * 80}")
        print(f"  Forward {h}D returns")
        print(f"{'─' * 80}")
        print(f"  {'Factor':<20} {'Mean IC':>9} {'Std IC':>9} {'ICIR':>8} {'Hit%':>7} {'Days':>6}  Signal")
        print(f"  {'─' * 18}   {'─' * 7}   {'─' * 7}  {'─' * 6}  {'─' * 5}  {'─' * 4}  {'─' * 12}")

        stats_list = []
        for f in all_factors:
            s = summary[h].get(f, {})
            stats_list.append((f, s))

        for f, s in stats_list:
            mean_ic = s.get("mean_ic", 0)
            std_ic = s.get("std_ic", 0)
            icir = s.get("icir", 0)
            hit = s.get("hit_rate", 0)
            n = s.get("n_days", 0)

            if abs(mean_ic) >= 0.03:
                signal = "*** STRONG" if abs(mean_ic) >= 0.05 else "** OK"
            elif abs(mean_ic) >= 0.015:
                signal = "* weak"
            else:
                signal = "  noise"

            marker = " <--" if f == "composite" else ""
            print(f"  {f:<20} {mean_ic:>+9.4f} {std_ic:>9.4f} {icir:>+8.3f} {hit:>6.1f}% {n:>5d}  {signal}{marker}")

    # Weight comparison
    print(f"\n{'=' * 80}")
    print("  Weight comparison: Current vs IC-suggested (based on 5D horizon)")
    print(f"{'=' * 80}")
    current = result["current_weights"]
    suggested = result["suggested_weights"]
    print(f"  {'Factor':<20} {'Current':>9} {'Suggested':>10} {'Delta':>8}")
    print(f"  {'─' * 18}   {'─' * 7}   {'─' * 8}   {'─' * 6}")
    for f in FACTOR_NAMES:
        c = current.get(f, 0)
        s = suggested.get(f, 0)
        d = s - c
        arrow = "^" if d > 0.01 else ("v" if d < -0.01 else "=")
        print(f"  {f:<20} {c:>8.1%} {s:>9.1%} {d:>+7.1%}  {arrow}")

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as fp:
            json.dump(result, fp, ensure_ascii=False, indent=2)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
