"""
Peer comparison — industry mapping, batch data fetch, relative performance.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import yfinance as yf

from .cache import ttl_cache
from .scoring import _score_fundamental
from .utils import retry

logger = logging.getLogger(__name__)

# ── Peer mapping ──────────────────────────────────────────────────────────────
# Manually curated for major stocks; fallback uses yfinance sector lookup.

PEER_MAP: dict[str, list[str]] = {
    # US Tech
    "AAPL":  ["MSFT", "GOOGL", "META"],
    "MSFT":  ["AAPL", "GOOGL", "META"],
    "GOOGL": ["AAPL", "MSFT", "META"],
    "META":  ["AAPL", "MSFT", "GOOGL"],
    "AMZN":  ["MSFT", "GOOGL", "AAPL"],
    # US Semis
    "NVDA":  ["AMD", "INTC", "AVGO"],
    "AMD":   ["NVDA", "INTC", "QCOM"],
    "INTC":  ["NVDA", "AMD", "AVGO"],
    "AVGO":  ["NVDA", "AMD", "QCOM"],
    # US Auto
    "TSLA":  ["F", "GM", "RIVN"],
    "F":     ["GM", "TSLA", "TM"],
    "GM":    ["F", "TSLA", "TM"],
    # TW Semis
    "2330.TW": ["2454.TW", "3711.TW", "2303.TW"],
    "2454.TW": ["2330.TW", "3711.TW", "2379.TW"],
    "3711.TW": ["2330.TW", "2454.TW", "2303.TW"],
    # TW Finance
    "2881.TW": ["2882.TW", "2884.TW", "2886.TW"],
    "2882.TW": ["2881.TW", "2884.TW", "2886.TW"],
    # TW Electronics
    "2317.TW": ["2382.TW", "3231.TW", "2354.TW"],
    "2308.TW": ["2301.TW", "2357.TW", "2395.TW"],
}

# Market index per region
INDEX_MAP: dict[str, str] = {
    "TW": "0050.TW",
    "US": "SPY",
    "SS": "000300.SS",
    "SZ": "000300.SS",
    "DEFAULT": "SPY",
}


def get_peers(symbol: str) -> list[str]:
    """
    Return peer tickers for a given symbol.
    Three-layer fallback: hardcoded → TWSE industry → empty.
    """
    # Layer 1: hardcoded mapping
    if symbol in PEER_MAP:
        return PEER_MAP[symbol]

    # Layer 2: TWSE industry classification (TW stocks only) via SQLite
    if ".TW" in symbol:
        try:
            from .tw_market import find_industry_peers
            industry_peers = find_industry_peers(symbol, top_n=3)
            if industry_peers:
                return industry_peers
        except Exception as e:
            logger.warning("Industry peer lookup failed for %s: %s", symbol, e)

    # Layer 3: no peers found
    return []


def get_market_index(symbol: str) -> str:
    """Return the appropriate market index for the symbol's region."""
    if ".TW" in symbol:
        return INDEX_MAP["TW"]
    if ".SS" in symbol:
        return INDEX_MAP["SS"]
    if ".SZ" in symbol:
        return INDEX_MAP["SZ"]
    return INDEX_MAP["DEFAULT"]


@ttl_cache(ttl_seconds=300)
@retry(max_retries=2, base_delay=2.0)
def fetch_comparison_data(symbols: tuple[str, ...], period: str = "3M") -> dict:
    """
    Fetch comparison table data + relative performance for multiple symbols.
    symbols must be a tuple (for cache hashability).
    """
    period_days = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365, "YTD": None}

    end_date = datetime.now()
    if period == "YTD":
        start_date = datetime(end_date.year, 1, 1)
    else:
        days = period_days.get(period, 90)
        start_date = end_date - timedelta(days=days)

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    comparison_table = []
    relative_series = {}
    labels = []
    labels_built = False

    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(start=start_str, end=end_str)

            if hist.empty:
                comparison_table.append({"symbol": sym, "error": "No data"})
                continue

            closes = hist["Close"].tolist()
            dates = [d.strftime("%Y-%m-%d") for d in hist.index]

            if not labels_built:
                labels = [d[5:] for d in dates]  # MM-DD
                labels_built = True

            # Relative performance (normalized to 100)
            base = closes[0] if closes[0] > 0 else 1
            normalized = [round(c / base * 100, 2) for c in closes]
            relative_series[sym] = normalized

            # Returns
            return_val = round((closes[-1] / closes[0] - 1) * 100, 2) if closes[0] else 0

            # Fundamentals
            info = ticker.info or {}

            # Compute fundamental score from available data
            fund_data = {
                "valuation": {"pe_ratio": _safe_round(info.get("trailingPE"))},
                "profitability": {
                    "roe": _safe_round(_pct(info.get("returnOnEquity"))),
                    "profit_margin": _safe_round(_pct(info.get("profitMargins"))),
                },
                "dividend": {"dividend_yield": _safe_round(_pct(info.get("dividendYield")))},
                "quarterly_financials": [],
            }
            fund_score = _score_fundamental(fund_data)

            comparison_table.append({
                "symbol": sym,
                "score": fund_score["score"],
                "pe": _safe_round(info.get("trailingPE")),
                "roe": _safe_round(_pct(info.get("returnOnEquity"))),
                "margin": _safe_round(_pct(info.get("profitMargins"))),
                "mcap": info.get("marketCap"),
                "return_period": return_val,
                "yield": _safe_round(_pct(info.get("dividendYield"))),
                "beta": _safe_round(info.get("beta")),
                "error": None,
            })

        except Exception as e:
            logger.warning("Failed to fetch peer data for %s: %s", sym, e)
            comparison_table.append({"symbol": sym, "error": str(e)})

    return {
        "comparison_table": comparison_table,
        "relative_performance": {
            "labels": labels,
            "series": relative_series,
        },
    }


def build_peer_comparison(symbol: str, period: str = "3M") -> dict:
    """High-level: build full peer comparison response."""
    peers = get_peers(symbol)
    index = get_market_index(symbol)
    all_symbols = tuple([symbol] + peers + [index])

    data = fetch_comparison_data(all_symbols, period)

    # Mark the target stock
    for row in data["comparison_table"]:
        row["is_target"] = row["symbol"] == symbol
        row["is_index"] = row["symbol"] == index

    return {
        "symbol": symbol,
        "peers": peers,
        "index": index,
        "comparison_table": data["comparison_table"],
        "relative_performance": data["relative_performance"],
    }


def build_watchlist_comparison(tickers: list[str], period: str = "3M") -> dict:
    """High-level: build watchlist comparison response."""
    # Determine index based on majority market
    tw_count = sum(1 for t in tickers if ".TW" in t)
    index = "0050.TW" if tw_count > len(tickers) / 2 else "SPY"

    all_symbols = tuple(tickers + [index])
    data = fetch_comparison_data(all_symbols, period)

    for row in data["comparison_table"]:
        row["is_target"] = False
        row["is_index"] = row["symbol"] == index

    return {
        "tickers": tickers,
        "index": index,
        "comparison_table": data["comparison_table"],
        "relative_performance": data["relative_performance"],
    }


def _safe_round(val, digits=2):
    if val is None:
        return None
    try:
        return round(float(val), digits)
    except (TypeError, ValueError):
        return None


def _pct(val):
    if val is None:
        return None
    try:
        return float(val) * 100
    except (TypeError, ValueError):
        return None
