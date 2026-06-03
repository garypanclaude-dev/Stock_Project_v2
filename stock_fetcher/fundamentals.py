"""Fetch fundamental data from yfinance."""
from __future__ import annotations

import logging
from datetime import datetime

import yfinance as yf

from .cache import ttl_cache
from .utils import retry

logger = logging.getLogger(__name__)


@ttl_cache(ttl_seconds=3600)  # 1 hr
@retry(max_retries=3, base_delay=2.0, exceptions=(Exception,))
def fetch_fundamentals(symbol: str) -> dict:
    ticker = yf.Ticker(symbol)
    info = ticker.info or {}

    valuation = {
        "pe_ratio": _safe_round(info.get("trailingPE")),
        "forward_pe": _safe_round(info.get("forwardPE")),
        "pb_ratio": _safe_round(info.get("priceToBook")),
        "ps_ratio": _safe_round(info.get("priceToSalesTrailing12Months")),
        "peg_ratio": _safe_round(info.get("pegRatio")),
    }

    per_share = {
        "eps_ttm": _safe_round(info.get("trailingEps")),
        "eps_forward": _safe_round(info.get("forwardEps")),
        "book_value": _safe_round(info.get("bookValue")),
        "revenue_per_share": _safe_round(info.get("revenuePerShare")),
    }

    profitability = {
        "roe": _safe_pct(info.get("returnOnEquity")),
        "roa": _safe_pct(info.get("returnOnAssets")),
        "profit_margin": _safe_pct(info.get("profitMargins")),
        "gross_margin": _safe_pct(info.get("grossMargins")),
        "operating_margin": _safe_pct(info.get("operatingMargins")),
    }

    dividend = {
        "dividend_yield": _safe_pct(info.get("dividendYield")),
        "dividend_rate": _safe_round(info.get("dividendRate")),
        "payout_ratio": _safe_pct(info.get("payoutRatio")),
        "ex_dividend_date": _fmt_timestamp(info.get("exDividendDate")),
    }

    summary = {
        "sector": info.get("sector", ""),
        "industry": info.get("industry", ""),
        "market_cap": info.get("marketCap"),
        "enterprise_value": info.get("enterpriseValue"),
        "fifty_two_week_high": _safe_round(info.get("fiftyTwoWeekHigh")),
        "fifty_two_week_low": _safe_round(info.get("fiftyTwoWeekLow")),
        "fifty_day_avg": _safe_round(info.get("fiftyDayAverage")),
        "two_hundred_day_avg": _safe_round(info.get("twoHundredDayAverage")),
        "beta": _safe_round(info.get("beta")),
        "short_ratio": _safe_round(info.get("shortRatio")),
    }

    quarterly = _extract_quarterly(ticker)

    return {
        "symbol": symbol.upper(),
        "valuation": valuation,
        "per_share": per_share,
        "profitability": profitability,
        "dividend": dividend,
        "summary": summary,
        "quarterly_financials": quarterly,
        "query_time": datetime.now().isoformat(),
    }


def _extract_quarterly(ticker: yf.Ticker) -> list[dict]:
    try:
        qf = ticker.quarterly_financials
        if qf is None or qf.empty:
            return []
    except Exception:
        return []

    quarters: list[dict] = []
    for col in qf.columns[:4]:
        data = qf[col]
        quarters.append({
            "period": f"{col.year}-Q{(col.month - 1) // 3 + 1}" if hasattr(col, "year") else str(col)[:10],
            "revenue": _safe_int(data.get("Total Revenue")),
            "net_income": _safe_int(data.get("Net Income")),
            "gross_profit": _safe_int(data.get("Gross Profit")),
            "operating_income": _safe_int(data.get("Operating Income")),
            "ebitda": _safe_int(data.get("EBITDA")),
        })
    return quarters


def _safe_round(val, digits=2):
    if val is None:
        return None
    try:
        return round(float(val), digits)
    except (TypeError, ValueError):
        return None


def _safe_pct(val):
    if val is None:
        return None
    try:
        return round(float(val) * 100, 2)
    except (TypeError, ValueError):
        return None


def _safe_int(val):
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _fmt_timestamp(ts):
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return None
