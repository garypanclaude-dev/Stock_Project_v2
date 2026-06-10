"""Fetch fundamental data from yfinance."""
from __future__ import annotations

import logging
from datetime import datetime

import yfinance as yf

from .cache import ttl_cache
from .utils import retry

logger = logging.getLogger(__name__)

# ── B9: configurable thresholds ──────────────────────────────────────────────
DIVIDEND_HISTORY_YEARS = 5      # 配息歷史視窗
PE_HISTORY_YEARS = 5            # PE 河流圖視窗（年）
PE_HISTORY_MIN_SAMPLES = 12     # 樣本不足 (< 12 月) 時不算分位


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
    quarterly = _enrich_with_growth(quarterly)  # 加 qoq_pct
    annual_growth = _extract_annual_revenue_growth(ticker)

    dividend_history, consecutive_years = _extract_dividend_history(ticker)
    pe_history = _build_pe_history(ticker, info, annual_growth)

    return {
        "symbol": symbol.upper(),
        "valuation": valuation,
        "per_share": per_share,
        "profitability": profitability,
        "dividend": dividend,
        "summary": summary,
        "quarterly_financials": quarterly,
        "annual_revenue_growth": annual_growth,
        "dividend_history": dividend_history,
        "dividend_consecutive_years": consecutive_years,
        "pe_history": pe_history,
        "query_time": datetime.now().isoformat(),
    }


def _enrich_with_growth(quarterly: list[dict]) -> list[dict]:
    """Augment quarterly financials with QoQ percentage change.

    YoY requires 8 consecutive quarters which yfinance rarely provides; for
    YoY trend, use `annual_revenue_growth` instead (annual income statement
    delivers 4–5 years).

    Quarters arrive newest-first. i=0 most recent, i+1 previous quarter.
    """
    if not quarterly:
        return []
    result: list[dict] = []
    for i, q in enumerate(quarterly):
        item = dict(q)
        revenue = q.get("revenue")
        if revenue is None:
            result.append(item)
            continue
        if i + 1 < len(quarterly):
            prev_rev = quarterly[i + 1].get("revenue")
            if prev_rev and prev_rev != 0:
                item["qoq_pct"] = round((revenue - prev_rev) / abs(prev_rev) * 100, 2)
        # YoY: try i+4 if available (rare with yfinance)
        if i + 4 < len(quarterly):
            yoy_rev = quarterly[i + 4].get("revenue")
            if yoy_rev and yoy_rev != 0:
                item["yoy_pct"] = round((revenue - yoy_rev) / abs(yoy_rev) * 100, 2)
        result.append(item)
    return result


def _extract_annual_revenue_growth(ticker: yf.Ticker) -> list[dict]:
    """Annual revenue and YoY growth, newest first. 4–5 years typically.

    Returns: [{year, revenue, net_income, yoy_pct, ni_yoy_pct}, ...]
    """
    try:
        inc = ticker.income_stmt
    except Exception:
        return []
    if inc is None or inc.empty:
        return []

    try:
        revenues_row = inc.loc["Total Revenue"] if "Total Revenue" in inc.index else None
        ni_row = inc.loc["Net Income"] if "Net Income" in inc.index else None
    except Exception:
        return []

    if revenues_row is None:
        return []

    rows: list[dict] = []
    for col in inc.columns:
        try:
            year = col.year
        except AttributeError:
            continue
        rev = revenues_row.get(col) if revenues_row is not None else None
        ni = ni_row.get(col) if ni_row is not None else None
        rev_v = _safe_int(rev)
        ni_v = _safe_int(ni)
        if rev_v is None:
            continue  # skip NaN years
        rows.append({"year": year, "revenue": rev_v, "net_income": ni_v})

    rows.sort(key=lambda r: r["year"], reverse=True)

    # Compute YoY for each year vs the next-older entry
    for i, r in enumerate(rows):
        if i + 1 >= len(rows):
            continue
        prev = rows[i + 1]
        if prev["revenue"]:
            r["yoy_pct"] = round((r["revenue"] - prev["revenue"]) / abs(prev["revenue"]) * 100, 2)
        if prev.get("net_income") and r.get("net_income") is not None:
            r["ni_yoy_pct"] = round((r["net_income"] - prev["net_income"]) / abs(prev["net_income"]) * 100, 2)
    return rows


def _extract_dividend_history(ticker: yf.Ticker) -> tuple[list[dict], int]:
    """Return (dividend_history, consecutive_years).

    dividend_history: list of {year, amount} for the last DIVIDEND_HISTORY_YEARS years
    consecutive_years: 從今年向前看連續幾年有配息（含本年）
    """
    try:
        dividends = ticker.dividends
    except Exception:
        return [], 0
    if dividends is None or dividends.empty:
        return [], 0

    annual: dict[int, float] = {}
    for ts, amount in dividends.items():
        try:
            year = ts.year
            annual[year] = annual.get(year, 0) + float(amount)
        except (AttributeError, ValueError, TypeError):
            continue

    if not annual:
        return [], 0

    years = sorted(annual.keys())
    history = [
        {"year": y, "amount": round(annual[y], 4)}
        for y in years[-DIVIDEND_HISTORY_YEARS:]
    ]

    # 連續配息年數：從最新年向前回溯，連續有配息（>0）的年數
    consecutive = 0
    current_year = max(years)
    while current_year in annual and annual[current_year] > 0:
        consecutive += 1
        current_year -= 1

    return history, consecutive


def _build_pe_history(
    ticker: yf.Ticker,
    info: dict,
    annual_growth: list[dict],
) -> dict:
    """Compute monthly PE series over the past PE_HISTORY_YEARS years.

    Approach:
      1. Fetch monthly close prices via yfinance history.
      2. Build annual EPS series from `annual_revenue_growth.net_income /
         sharesOutstanding`. Each month maps to the EPS of its fiscal year.
      3. PE_t = close_t / EPS_year(t).

    Limitation: shares outstanding from `info` is current — historical
    share counts (pre-buyback / split) are not adjusted, so older PE values
    may be slightly biased. Sufficient for percentile-rank purposes.

    Returns empty dict if input data insufficient.
    """
    try:
        hist = ticker.history(period=f"{PE_HISTORY_YEARS}y", interval="1mo")
    except Exception as exc:
        logger.warning("PE history fetch failed: %s", exc)
        return {}

    if hist is None or hist.empty:
        return {}

    shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
    if not shares or shares <= 0:
        return {}

    # Build year → EPS map. Anchored to current trailingEps (which yfinance
    # reports in the share's traded currency, so ADR-friendly). Historical
    # years scale by the ratio of historical net_income to latest net_income,
    # preserving the earnings trajectory while sidestepping income-vs-price
    # currency mismatch (e.g. TSM reports TWD income, trades USD ADR).
    eps_by_year = _annual_eps_map_anchored(annual_growth, info.get("trailingEps"))
    if not eps_by_year:
        return {}
    latest_year = max(eps_by_year.keys())

    labels: list[str] = []
    series: list[float | None] = []
    valid_pe: list[float] = []
    for ts, row in hist.iterrows():
        close = row.get("Close")
        if close is None or close <= 0:
            labels.append(ts.strftime("%Y-%m"))
            series.append(None)
            continue
        # Map year → EPS; use latest year's EPS for months newer than latest
        eps_year = min(ts.year, latest_year) if ts.year > latest_year else ts.year
        eps = eps_by_year.get(eps_year)
        if not eps or eps <= 0:
            labels.append(ts.strftime("%Y-%m"))
            series.append(None)
            continue
        pe = round(float(close) / float(eps), 2)
        labels.append(ts.strftime("%Y-%m"))
        series.append(pe)
        valid_pe.append(pe)

    if len(valid_pe) < PE_HISTORY_MIN_SAMPLES:
        return {}

    valid_pe_sorted = sorted(valid_pe)
    n = len(valid_pe_sorted)

    def _percentile(p: float) -> float:
        idx = max(0, min(n - 1, int(n * p)))
        return valid_pe_sorted[idx]

    current_pe = info.get("trailingPE")
    if current_pe and current_pe > 0:
        below = sum(1 for x in valid_pe_sorted if x < current_pe)
        current_percentile = round(below / n * 100, 1)
    else:
        current_percentile = None

    return {
        "labels": labels,
        "series": series,
        "median": _percentile(0.50),
        "p10": _percentile(0.10),
        "p25": _percentile(0.25),
        "p75": _percentile(0.75),
        "p90": _percentile(0.90),
        "current_pe": _safe_round(current_pe),
        "current_percentile": current_percentile,
        "samples": n,
    }


def _annual_eps_map_anchored(
    annual_growth: list[dict],
    trailing_eps: float | None,
) -> dict[int, float]:
    """Map fiscal year → EPS, anchored to current trailing EPS.

    Why anchored:
      net_income / sharesOutstanding gives EPS in the financial-statement
      currency. For ADRs (e.g. TSM reports TWD but trades USD), this would
      mismatch the price series. Instead we use trailing_eps (already in the
      traded currency) as the anchor for the most recent year, and scale
      older years by the net_income ratio. This preserves the earnings
      trajectory while keeping units consistent with price.

    Returns empty dict if anchor or annual data missing.
    """
    if not annual_growth or not trailing_eps or trailing_eps <= 0:
        return {}
    # Pick the most recent annual row with positive net income as anchor
    anchor_ni = None
    for row in annual_growth:
        ni = row.get("net_income")
        if ni and ni > 0:
            anchor_ni = ni
            anchor_year = row.get("year")
            break
    if not anchor_ni:
        return {}

    result: dict[int, float] = {}
    for row in annual_growth:
        ni = row.get("net_income")
        year = row.get("year")
        if year is None or ni is None or ni <= 0:
            continue
        # Scale EPS by NI ratio relative to anchor
        result[year] = trailing_eps * (ni / anchor_ni)
    return result


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
