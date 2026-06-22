"""
Information Coefficient (IC) analyzer for the stock screener.

Computes Spearman rank IC between each factor's cross-sectional rank
and N-day forward returns, across all historical trading days.

IC > +0.03  → factor has positive predictive power
IC ≈  0     → noise, should be removed or down-weighted
IC < -0.03  → factor direction is inverted (or harmful)

Usage:
    from stock_fetcher.ic_analyzer import run_ic_analysis
    result = run_ic_analysis()
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict

from . import tw_db
from .tw_market import run_screener_with_data, SCREENER_CONFIG
from .backtest_config import FORWARD_DAYS, WARM_UP_DAYS, BENCHMARK_SYMBOL

logger = logging.getLogger(__name__)

FACTOR_NAMES = list(SCREENER_CONFIG["weights"].keys())


def run_ic_analysis(
    forward_days: list[int] | None = None,
    extreme_return_cap: float = 30.0,
) -> dict:
    """Run cross-sectional Spearman IC analysis for all screener factors.

    Parameters
    ----------
    forward_days : horizons to measure (default from backtest_config).
    extreme_return_cap : exclude stocks with |return| > this % (corporate actions).

    Returns dict with keys: period, daily_ic, summary, factor_weights_suggestion.
    """
    if forward_days is None:
        forward_days = list(FORWARD_DAYS)

    logger.info("IC Analysis: loading data …")
    trading_dates = tw_db.get_trading_dates()
    min_required = WARM_UP_DAYS + max(forward_days) + 5
    if len(trading_dates) < min_required:
        return {"error": f"資料不足：DB 中僅有 {len(trading_dates)} 個交易日"}

    prices, _ = _load_prices()
    companies = tw_db.get_all_companies()
    inst_data, revenue_data, shareholder_data = _load_extended_data()
    date_to_idx = {d: i for i, d in enumerate(trading_dates)}

    backtest_dates = trading_dates[WARM_UP_DAYS:]
    max_fwd = max(forward_days)

    logger.info(
        "IC Analysis: %d dates, %d stocks, window %s ~ %s",
        len(trading_dates), len(prices),
        backtest_dates[0], backtest_dates[-1],
    )

    # daily_ic[horizon][factor_name] = list of daily IC values
    daily_ic: dict[int, dict[str, list[float]]] = {
        n: {f: [] for f in FACTOR_NAMES} for n in forward_days
    }
    # Also track composite score IC
    for n in forward_days:
        daily_ic[n]["composite"] = []

    processed_days = 0

    for signal_date in backtest_dates:
        signal_idx = date_to_idx[signal_date]
        buy_idx = signal_idx + 1
        if buy_idx >= len(trading_dates):
            break
        if buy_idx + max_fwd >= len(trading_dates):
            break

        buy_date = trading_dates[buy_idx]

        # Run screener returning ALL stocks
        snapshot = _build_snapshot(prices, companies, signal_date)
        if not snapshot:
            continue

        histories = {
            s["symbol"]: _get_history_before(prices, s["symbol"], signal_date, 200)
            for s in snapshot
        }

        all_ranked = run_screener_with_data(
            snapshot, histories, return_all=True,
            inst_data=inst_data, revenue_data=revenue_data,
            shareholder_data=shareholder_data,
        )
        if len(all_ranked) < 30:
            continue

        # Compute forward returns for each stock
        stock_returns: dict[int, dict[str, float]] = {n: {} for n in forward_days}
        for item in all_ranked:
            sym = item["symbol"]
            buy_data = prices.get(sym, {}).get(buy_date)
            if not buy_data or not buy_data.get("open") or buy_data["open"] <= 0:
                continue
            entry = buy_data["open"]

            for n in forward_days:
                target_idx = buy_idx + n
                if target_idx >= len(trading_dates):
                    continue
                target_date = trading_dates[target_idx]
                target_data = prices.get(sym, {}).get(target_date)
                if target_data and target_data.get("close"):
                    ret = (target_data["close"] / entry - 1) * 100
                    if abs(ret) <= extreme_return_cap:
                        stock_returns[n][sym] = ret

        # For each horizon, compute cross-sectional Spearman IC
        for n in forward_days:
            rets = stock_returns[n]
            if len(rets) < 30:
                continue

            symbols_with_ret = set(rets.keys())
            ranked_items = [r for r in all_ranked if r["symbol"] in symbols_with_ret]
            if len(ranked_items) < 30:
                continue

            ret_values = {r["symbol"]: rets[r["symbol"]] for r in ranked_items}

            # IC for each factor
            for factor in FACTOR_NAMES:
                factor_values = {
                    r["symbol"]: r["factors"].get(factor, 50)
                    for r in ranked_items
                }
                ic = _spearman_ic(factor_values, ret_values)
                if ic is not None:
                    daily_ic[n][factor].append(ic)

            # IC for composite score
            composite_values = {r["symbol"]: r["score"] for r in ranked_items}
            ic = _spearman_ic(composite_values, ret_values)
            if ic is not None:
                daily_ic[n]["composite"].append(ic)

        processed_days += 1
        if processed_days % 20 == 0:
            logger.info("IC Analysis: processed %d / %d days", processed_days, len(backtest_dates))

    # Compute summary statistics
    summary = _build_summary(daily_ic, forward_days)
    weights_suggestion = _suggest_weights(summary, forward_days)

    logger.info("IC Analysis complete: %d trading days processed", processed_days)

    return {
        "period": {
            "start": backtest_dates[0],
            "end": backtest_dates[-1],
            "trading_days": processed_days,
        },
        "config": {
            "forward_days": forward_days,
            "extreme_return_cap": extreme_return_cap,
        },
        "summary": summary,
        "current_weights": dict(SCREENER_CONFIG["weights"]),
        "suggested_weights": weights_suggestion,
    }


def _build_summary(
    daily_ic: dict[int, dict[str, list[float]]],
    forward_days: list[int],
) -> dict:
    summary: dict[str, dict] = {}
    all_factors = FACTOR_NAMES + ["composite"]

    for n in forward_days:
        horizon_stats: dict[str, dict] = {}
        for factor in all_factors:
            ic_series = daily_ic[n].get(factor, [])
            if not ic_series:
                horizon_stats[factor] = {
                    "mean_ic": 0, "std_ic": 0, "icir": 0,
                    "hit_rate": 0, "n_days": 0,
                }
                continue

            mean_ic = sum(ic_series) / len(ic_series)
            var = sum((x - mean_ic) ** 2 for x in ic_series) / len(ic_series)
            std_ic = math.sqrt(var) if var > 0 else 0
            icir = mean_ic / std_ic if std_ic > 0 else 0
            hit_rate = sum(1 for x in ic_series if x > 0) / len(ic_series) * 100

            horizon_stats[factor] = {
                "mean_ic": round(mean_ic, 4),
                "std_ic": round(std_ic, 4),
                "icir": round(icir, 4),
                "hit_rate": round(hit_rate, 1),
                "n_days": len(ic_series),
            }

        summary[str(n)] = horizon_stats

    return summary


def _suggest_weights(summary: dict, forward_days: list[int]) -> dict:
    """Suggest IC-weighted factor weights using 5-day horizon as primary."""
    target_horizon = "5" if "5" in summary else str(forward_days[0])
    stats = summary.get(target_horizon, {})

    abs_ics = {}
    for factor in FACTOR_NAMES:
        s = stats.get(factor, {})
        mean_ic = s.get("mean_ic", 0)
        abs_ics[factor] = abs(mean_ic)

    total = sum(abs_ics.values())
    if total == 0:
        return dict(SCREENER_CONFIG["weights"])

    suggested = {f: round(v / total, 3) for f, v in abs_ics.items()}

    # Normalize to exactly 1.0
    remainder = round(1.0 - sum(suggested.values()), 3)
    if remainder != 0:
        max_factor = max(suggested, key=suggested.get)
        suggested[max_factor] = round(suggested[max_factor] + remainder, 3)

    return suggested


def _spearman_ic(
    x_values: dict[str, float],
    y_values: dict[str, float],
) -> float | None:
    """Compute Spearman rank correlation between two dicts keyed by symbol."""
    common = sorted(set(x_values) & set(y_values))
    n = len(common)
    if n < 20:
        return None

    x_list = [x_values[s] for s in common]
    y_list = [y_values[s] for s in common]

    x_ranks = _rank_array(x_list)
    y_ranks = _rank_array(y_list)

    mean_x = sum(x_ranks) / n
    mean_y = sum(y_ranks) / n

    cov = sum((x_ranks[i] - mean_x) * (y_ranks[i] - mean_y) for i in range(n))
    var_x = sum((x_ranks[i] - mean_x) ** 2 for i in range(n))
    var_y = sum((y_ranks[i] - mean_y) ** 2 for i in range(n))

    denom = math.sqrt(var_x * var_y)
    if denom == 0:
        return 0.0

    return cov / denom


def _rank_array(values: list[float]) -> list[float]:
    """Average-rank assignment (handles ties)."""
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j - 1) / 2.0 + 1
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


# ── Data loading (same pattern as backtester) ────────────────────────────────

def _load_extended_data() -> tuple[dict, dict, dict]:
    """Load institutional, revenue, shareholder data into memory indexes."""
    inst_data: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in tw_db.get_all_institutional_trading():
        sym = row.pop("symbol")
        dt = row.pop("date")
        inst_data[sym][dt] = row

    revenue_data: dict[str, list[dict]] = defaultdict(list)
    for row in tw_db.get_all_monthly_revenue():
        sym = row.pop("symbol")
        revenue_data[sym].append(row)

    shareholder_data: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in tw_db.get_all_shareholder_concentration():
        sym = row.pop("symbol")
        dt = row.pop("date")
        shareholder_data[sym][dt] = row

    logger.info(
        "Extended data: %d w/ inst, %d w/ revenue, %d w/ shareholder",
        len(inst_data), len(revenue_data), len(shareholder_data),
    )
    return dict(inst_data), dict(revenue_data), dict(shareholder_data)


def _load_prices() -> tuple[dict[str, dict[str, dict]], dict[str, list[str]]]:
    raw = tw_db.get_all_daily_prices()
    prices: dict[str, dict[str, dict]] = defaultdict(dict)
    prices_by_date: dict[str, list[str]] = defaultdict(list)
    for row in raw:
        sym = row.pop("symbol")
        dt = row.pop("date")
        prices[sym][dt] = row
        prices_by_date[dt].append(sym)
    return dict(prices), dict(prices_by_date)


def _get_history_before(
    prices: dict[str, dict[str, dict]],
    symbol: str,
    before_date: str,
    days: int = 65,
) -> list[dict]:
    sym_prices = prices.get(symbol)
    if not sym_prices:
        return []
    filtered = [
        {"date": d, **p}
        for d, p in sym_prices.items()
        if d <= before_date
    ]
    return list(reversed(filtered[-days:]))


def _build_snapshot(
    prices: dict[str, dict[str, dict]],
    companies: dict[str, dict],
    target_date: str,
) -> list[dict]:
    snapshot = []
    for sym, date_prices in prices.items():
        if target_date not in date_prices:
            continue
        row = date_prices[target_date]
        company = companies.get(sym, {})
        snapshot.append({
            "symbol": sym,
            "name": company.get("name", ""),
            "industry": company.get("industry", ""),
            "market": company.get("market", ""),
            "date": target_date,
            **row,
        })
    return snapshot
