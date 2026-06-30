"""
Forward-return backtester for the stock screener.

For each historical trading day:
  1. Run screener at date D → pick Top N candidates
  2. Entry at D+1 open price
  3. Measure close-price returns at [1, 3, 5, 10, 20] trading days forward

Measures pure signal quality without portfolio/capital management assumptions.
All data comes from SQLite (tw_market.db), pre-loaded into memory.
Screener uses only data available up to the signal date (no look-ahead bias).

Usage:
    from stock_fetcher.backtester import run_backtest
    result = run_backtest()  # uses defaults from backtest_config.py
"""
from __future__ import annotations

import logging
from collections import defaultdict
from statistics import median

from . import tw_db
from .tw_market import run_screener_with_data
from .backtest_config import (
    FORWARD_DAYS,
    TOP_N,
    WARM_UP_DAYS,
    BENCHMARK_SYMBOL,
)
from .cancellation import ProgressReporter

logger = logging.getLogger(__name__)

RANK_GROUPS = [(1, 5), (6, 10), (11, 15), (16, 20)]


# ── Public API ───────────────────────────────────────────────────────────────

def run_backtest(
    top_n: int = TOP_N,
    forward_days: list[int] | None = None,
    *,
    reporter: ProgressReporter | None = None,
) -> dict:
    """Run forward-return backtest and return structured results.

    Returns dict with keys: period, config, summary, signals.
    On error returns dict with "error" key.
    """
    reporter = reporter or ProgressReporter.noop()
    if forward_days is None:
        forward_days = list(FORWARD_DAYS)

    # ── 1. Load all data into memory ─────────────────────────────────────────
    reporter.update(0, "載入交易日資料 …")
    logger.info("Backtest: loading data from DB …")
    trading_dates = tw_db.get_trading_dates()
    min_required = WARM_UP_DAYS + max(forward_days) + 5
    if len(trading_dates) < min_required:
        return {
            "error": (
                f"資料不足：DB 中僅有 {len(trading_dates)} 個交易日"
                f"（回測至少需要 {min_required} 個交易日）"
            )
        }

    reporter.update(2, "載入價量資料 …")
    prices, _ = _load_prices_into_memory()
    reporter.update(5, "載入基本資料 …")
    companies = tw_db.get_all_companies()
    inst_data, revenue_data, shareholder_data = _load_extended_data()
    date_to_idx = {d: i for i, d in enumerate(trading_dates)}

    backtest_dates = trading_dates[WARM_UP_DAYS:]
    max_fwd = max(forward_days)
    reporter.update(8, f"準備回測 {len(backtest_dates)} 個交易日 …")

    logger.info(
        "Backtest: %d trading days loaded, %d stocks, "
        "backtest window %s ~ %s (%d days)",
        len(trading_dates), len(prices),
        backtest_dates[0], backtest_dates[-1], len(backtest_dates),
    )

    # ── 2. Generate signals with forward returns ─────────────────────────────
    signals: list[dict] = []
    screener_cache: dict[str, list[dict]] = {}

    total = len(backtest_dates)
    # 主迴圈映射到 10~95%（前 10% 留給載入、最後 5% 留給 summary）
    for i, signal_date in enumerate(backtest_dates):
        # 每個 date 都 check cancel — 單一 date 內含全 symbol 迴圈，可能跑幾秒
        reporter.check_cancelled()
        if i % 5 == 0:
            pct = 10 + (i / max(total, 1)) * 85
            reporter.update(pct, f"回測進度 {i}/{total} ({signal_date})")
        signal_idx = date_to_idx[signal_date]
        buy_idx = signal_idx + 1
        if buy_idx >= len(trading_dates):
            break
        if buy_idx + max_fwd >= len(trading_dates):
            break

        buy_date = trading_dates[buy_idx]

        # Run screener at signal_date (cached)
        if signal_date not in screener_cache:
            screener_cache[signal_date] = _run_screener_inmem(
                signal_date, prices, companies, trading_dates,
                inst_data=inst_data, revenue_data=revenue_data,
                shareholder_data=shareholder_data,
            )

        candidates = screener_cache[signal_date]
        if not candidates:
            continue

        # Benchmark entry price (same buy_date open)
        bench_buy = _get_price(prices, BENCHMARK_SYMBOL, buy_date)
        bench_entry = (
            bench_buy["open"]
            if bench_buy and bench_buy.get("open") and bench_buy["open"] > 0
            else None
        )

        for c in candidates[:top_n]:
            sym = c["symbol"]
            buy_data = _get_price(prices, sym, buy_date)
            if not buy_data or not buy_data.get("open") or buy_data["open"] <= 0:
                continue

            entry_price = buy_data["open"]
            returns: dict[int, float] = {}
            benchmark_returns: dict[int, float] = {}

            for n in forward_days:
                target_idx = buy_idx + n
                if target_idx >= len(trading_dates):
                    continue
                target_date = trading_dates[target_idx]

                target_data = _get_price(prices, sym, target_date)
                if target_data and target_data.get("close"):
                    returns[n] = round(
                        (target_data["close"] / entry_price - 1) * 100, 2,
                    )

                if bench_entry:
                    bench_target = _get_price(
                        prices, BENCHMARK_SYMBOL, target_date,
                    )
                    if bench_target and bench_target.get("close"):
                        benchmark_returns[n] = round(
                            (bench_target["close"] / bench_entry - 1) * 100, 2,
                        )

            if not returns:
                continue

            signals.append({
                "signal_date": signal_date,
                "buy_date": buy_date,
                "symbol": sym,
                "name": c.get("name", ""),
                "rank": c["rank"],
                "score": round(c["score"], 1),
                "entry_price": round(entry_price, 2),
                "returns": returns,
                "benchmark_returns": benchmark_returns,
            })

    # ── 3. Compute summary ───────────────────────────────────────────────────
    reporter.update(95, "計算統計摘要 …")
    summary = _compute_summary(signals, forward_days)
    reporter.update(100, "完成")

    logger.info(
        "Backtest complete: %d signals across %d trading days",
        len(signals), len(backtest_dates),
    )

    return {
        "period": {
            "start": backtest_dates[0],
            "end": backtest_dates[-1],
            "trading_days": len(backtest_dates),
        },
        "config": {
            "top_n": top_n,
            "forward_days": forward_days,
        },
        "summary": summary,
        "signals": signals,
    }


# ── Summary statistics ───────────────────────────────────────────────────────

def _compute_summary(signals: list[dict], forward_days: list[int]) -> dict:
    if not signals:
        return {"total_signals": 0, "by_horizon": {}, "by_rank_group": {}}

    by_horizon: dict[str, dict] = {}
    for n in forward_days:
        by_horizon[str(n)] = _calc_horizon_stats(signals, n)

    by_rank_group: dict[str, dict] = {}
    for lo, hi in RANK_GROUPS:
        group_signals = [s for s in signals if lo <= s["rank"] <= hi]
        group: dict[str, dict] = {}
        for n in forward_days:
            stats = _calc_horizon_stats(group_signals, n)
            if stats["count"] > 0:
                group[str(n)] = stats
        by_rank_group[f"{lo}-{hi}"] = group

    return {
        "total_signals": len(signals),
        "by_horizon": by_horizon,
        "by_rank_group": by_rank_group,
    }


def _calc_horizon_stats(signals: list[dict], n: int) -> dict:
    rets = [s["returns"][n] for s in signals if n in s["returns"]]
    bench = [s["benchmark_returns"][n] for s in signals if n in s["benchmark_returns"]]

    if not rets:
        return {
            "count": 0, "avg_return": 0, "median_return": 0,
            "win_rate": 0, "avg_benchmark": 0, "avg_excess": 0,
        }

    avg_ret = sum(rets) / len(rets)
    avg_bench = sum(bench) / len(bench) if bench else 0

    return {
        "count": len(rets),
        "avg_return": round(avg_ret, 2),
        "median_return": round(median(rets), 2),
        "win_rate": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1),
        "avg_benchmark": round(avg_bench, 2),
        "avg_excess": round(avg_ret - avg_bench, 2),
    }


# ── Data loading ─────────────────────────────────────────────────────────────

def _load_extended_data() -> tuple[dict, dict, dict]:
    """Load institutional, revenue, and shareholder data into memory indexes.

    Returns
    -------
    inst_data : {symbol: {date: {foreign_net, trust_net, dealer_net, total_net}}}
    revenue_data : {symbol: [{year_month, revenue_yoy, revenue_mom}]}  (sorted asc)
    shareholder_data : {symbol: {date: {large_holder_pct}}}
    """
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
        "Extended data loaded: %d symbols w/ inst, %d w/ revenue, %d w/ shareholder",
        len(inst_data), len(revenue_data), len(shareholder_data),
    )
    return dict(inst_data), dict(revenue_data), dict(shareholder_data)


def _load_prices_into_memory() -> tuple[
    dict[str, dict[str, dict]],
    dict[str, list[str]],
]:
    """Load all daily prices into two in-memory indexes.

    Returns
    -------
    prices : {symbol: {date: {open, high, low, close, …}}}
    prices_by_date : {date: [symbol, …]}
    """
    raw = tw_db.get_all_daily_prices()
    prices: dict[str, dict[str, dict]] = defaultdict(dict)
    prices_by_date: dict[str, list[str]] = defaultdict(list)

    for row in raw:
        sym = row.pop("symbol")
        dt = row.pop("date")
        prices[sym][dt] = row
        prices_by_date[dt].append(sym)

    logger.info(
        "Loaded %d price records for %d symbols",
        len(raw), len(prices),
    )
    return dict(prices), dict(prices_by_date)


# ── In-memory helpers ────────────────────────────────────────────────────────

def _get_price(
    prices: dict[str, dict[str, dict]],
    symbol: str,
    date: str,
) -> dict | None:
    """O(1) price lookup."""
    return prices.get(symbol, {}).get(date)


def _get_history_before(
    prices: dict[str, dict[str, dict]],
    symbol: str,
    before_date: str,
    days: int = 65,
) -> list[dict]:
    """Return up to *days* of history ending at *before_date*, newest first."""
    sym_prices = prices.get(symbol)
    if not sym_prices:
        return []
    filtered = [
        {"date": d, **p}
        for d, p in sym_prices.items()
        if d <= before_date
    ]
    return list(reversed(filtered[-days:]))


# ── Screener replay ──────────────────────────────────────────────────────────

def _run_screener_inmem(
    target_date: str,
    prices: dict[str, dict[str, dict]],
    companies: dict[str, dict],
    trading_dates: list[str],
    *,
    inst_data: dict | None = None,
    revenue_data: dict | None = None,
    shareholder_data: dict | None = None,
) -> list[dict]:
    """Replay the screener at a historical date using in-memory data."""
    snapshot: list[dict] = []
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

    if not snapshot:
        return []

    histories: dict[str, list[dict]] = {}
    for s in snapshot:
        sym = s["symbol"]
        histories[sym] = _get_history_before(prices, sym, target_date, days=200)

    return run_screener_with_data(
        snapshot, histories,
        inst_data=inst_data, revenue_data=revenue_data,
        shareholder_data=shareholder_data,
    )
