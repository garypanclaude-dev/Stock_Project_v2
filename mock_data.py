"""Mock data for UI development — no external API calls needed."""
from __future__ import annotations

import math
import random
from datetime import date, timedelta

from stock_fetcher.indicators import compute_all
from stock_fetcher.scoring import compute_composite_score
from stock_fetcher.patterns import detect_patterns


# ── Helper: generate extended kline for a period ─────────────────────────────

def _generate_klines(base_price: float, seed: str, days: int) -> list[dict]:
    rng = random.Random(seed)
    klines: list[dict] = []
    price = base_price * rng.uniform(0.75, 0.95)
    d = date(2026, 5, 21) - timedelta(days=days)
    while d <= date(2026, 5, 21):
        if d.weekday() < 5:
            drift = rng.gauss(0.0005, 0.015)
            price *= (1 + drift)
            o = round(price, 2)
            h = round(o * rng.uniform(1.002, 1.02), 2)
            l = round(o * rng.uniform(0.98, 0.998), 2)
            c = round(rng.uniform(l, h), 2)
            klines.append({
                "date": str(d),
                "open": o, "high": h, "low": l, "close": c,
                "volume": rng.randint(15_000_000, 120_000_000),
            })
            price = c
        d += timedelta(days=1)
    return klines


def _attach_indicators(klines: list[dict]) -> dict:
    closes = [k["close"] for k in klines]
    highs = [k["high"] for k in klines]
    lows = [k["low"] for k in klines]
    volumes = [k["volume"] for k in klines]
    return compute_all(closes, highs=highs, lows=lows, volumes=volumes)


def _trim_to_period(klines: list[dict], indicators: dict, period: str) -> tuple[list[dict], dict]:
    period_days = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365, "YTD": None}
    if period == "YTD":
        cutoff = "2026-01-01"
    else:
        days = period_days.get(period, 90)
        cutoff = str(date(2026, 5, 21) - timedelta(days=days))

    start_idx = 0
    for i, k in enumerate(klines):
        if k["date"] >= cutoff:
            start_idx = i
            break

    def _s(lst):
        return lst[start_idx:]

    trimmed_ind = {
        "ma": {k: _s(v) for k, v in indicators["ma"].items()},
        "rsi": _s(indicators["rsi"]),
        "macd": {k: _s(v) for k, v in indicators["macd"].items()},
        "bollinger": {k: _s(v) for k, v in indicators["bollinger"].items()},
    }
    if "kd" in indicators:
        trimmed_ind["kd"] = {k: _s(v) for k, v in indicators["kd"].items()}
    if "obv" in indicators:
        trimmed_ind["obv"] = _s(indicators["obv"])
    if "ma_alignment" in indicators:
        trimmed_ind["ma_alignment"] = indicators["ma_alignment"]
    return klines[start_idx:], trimmed_ind


# ── Pre-built full-year klines (used by all period views) ────────────────────

_AAPL_FULL = _generate_klines(302.12, "AAPL-full", 420)
_TSLA_FULL = _generate_klines(184.35, "TSLA-full", 420)
_NVDA_FULL = _generate_klines(1087.45, "NVDA-full", 420)

_AAPL_IND = _attach_indicators(_AAPL_FULL)
_TSLA_IND = _attach_indicators(_TSLA_FULL)
_NVDA_IND = _attach_indicators(_NVDA_FULL)


# ── Fundamentals ─────────────────────────────────────────────────────────────

_AAPL_FUND: dict = {
    "symbol": "AAPL",
    "valuation": {"pe_ratio": 33.21, "forward_pe": 29.45, "pb_ratio": 52.18, "ps_ratio": 8.92, "peg_ratio": 2.15},
    "per_share": {"eps_ttm": 9.10, "eps_forward": 10.26, "book_value": 5.79, "revenue_per_share": 26.32},
    "profitability": {"roe": 157.41, "roa": 30.28, "profit_margin": 26.31, "gross_margin": 46.52, "operating_margin": 31.51},
    "dividend": {"dividend_yield": 0.49, "dividend_rate": 1.00, "payout_ratio": 16.26, "ex_dividend_date": "2026-05-09"},
    "summary": {
        "sector": "Technology", "industry": "Consumer Electronics",
        "market_cap": 4_437_343_923_004, "enterprise_value": 4_498_000_000_000,
        "fifty_two_week_high": 315.84, "fifty_two_week_low": 184.21,
        "fifty_day_avg": 295.30, "two_hundred_day_avg": 268.12,
        "beta": 1.24, "short_ratio": 1.58,
    },
    "quarterly_financials": [
        {"period": "2026-Q1", "revenue": 124_300_000_000, "net_income": 33_900_000_000, "gross_profit": 58_100_000_000, "operating_income": 39_800_000_000, "ebitda": 44_200_000_000, "qoq_pct": 26.84},
        {"period": "2025-Q4", "revenue": 98_000_000_000, "net_income": 25_000_000_000, "gross_profit": 45_500_000_000, "operating_income": 30_900_000_000, "ebitda": 34_800_000_000, "qoq_pct": 3.27},
        {"period": "2025-Q3", "revenue": 94_900_000_000, "net_income": 23_600_000_000, "gross_profit": 43_900_000_000, "operating_income": 29_600_000_000, "ebitda": 33_200_000_000, "qoq_pct": 10.6},
        {"period": "2025-Q2", "revenue": 85_800_000_000, "net_income": 21_400_000_000, "gross_profit": 39_400_000_000, "operating_income": 26_500_000_000, "ebitda": 30_100_000_000},
    ],
    "annual_revenue_growth": [
        {"year": 2025, "revenue": 416_000_000_000, "net_income": 112_000_000_000, "yoy_pct": 6.43, "ni_yoy_pct": 19.5},
        {"year": 2024, "revenue": 391_000_000_000, "net_income": 93_700_000_000, "yoy_pct": 2.02, "ni_yoy_pct": -3.36},
        {"year": 2023, "revenue": 383_000_000_000, "net_income": 96_900_000_000, "yoy_pct": -2.8},
        {"year": 2022, "revenue": 394_000_000_000, "net_income": 99_800_000_000},
    ],
    "dividend_history": [
        {"year": 2022, "amount": 0.91},
        {"year": 2023, "amount": 0.95},
        {"year": 2024, "amount": 0.99},
        {"year": 2025, "amount": 1.03},
        {"year": 2026, "amount": 0.53},
    ],
    "dividend_consecutive_years": 15,
    "pe_history": {
        "labels": [f"{y}-{m:02d}" for y in range(2021, 2026) for m in range(1, 13)][-60:],
        "series": [28.5, 27.2, 26.8, 25.5, 24.9, 25.2, 26.1, 27.3, 28.0, 29.2, 30.5, 31.8] * 5,
        "median": 28.4, "p10": 23.2, "p25": 25.2, "p75": 31.4, "p90": 34.0,
        "current_pe": 35.08, "current_percentile": 94.4, "samples": 54,
    },
    "query_time": "2026-05-21T10:00:00",
}

_TSLA_FUND: dict = {
    "symbol": "TSLA",
    "valuation": {"pe_ratio": 62.45, "forward_pe": 48.30, "pb_ratio": 12.85, "ps_ratio": 6.12, "peg_ratio": 3.41},
    "per_share": {"eps_ttm": 2.95, "eps_forward": 3.82, "book_value": 14.34, "revenue_per_share": 30.12},
    "profitability": {"roe": 20.58, "roa": 8.92, "profit_margin": 9.78, "gross_margin": 17.86, "operating_margin": 8.21},
    "dividend": {"dividend_yield": None, "dividend_rate": None, "payout_ratio": None, "ex_dividend_date": None},
    "summary": {
        "sector": "Consumer Cyclical", "industry": "Auto Manufacturers",
        "market_cap": 591_432_000_000, "enterprise_value": 598_200_000_000,
        "fifty_two_week_high": 278.98, "fifty_two_week_low": 138.80,
        "fifty_day_avg": 195.40, "two_hundred_day_avg": 212.30,
        "beta": 2.31, "short_ratio": 2.87,
    },
    "quarterly_financials": [
        {"period": "2026-Q1", "revenue": 21_300_000_000, "net_income": 1_800_000_000, "gross_profit": 3_800_000_000, "operating_income": 1_600_000_000, "ebitda": 3_200_000_000, "qoq_pct": -15.48},
        {"period": "2025-Q4", "revenue": 25_200_000_000, "net_income": 2_500_000_000, "gross_profit": 4_700_000_000, "operating_income": 2_100_000_000, "ebitda": 3_900_000_000, "qoq_pct": 7.69},
        {"period": "2025-Q3", "revenue": 23_400_000_000, "net_income": 2_200_000_000, "gross_profit": 4_200_000_000, "operating_income": 1_900_000_000, "ebitda": 3_600_000_000, "qoq_pct": -6.02},
        {"period": "2025-Q2", "revenue": 24_900_000_000, "net_income": 2_700_000_000, "gross_profit": 4_900_000_000, "operating_income": 2_300_000_000, "ebitda": 4_100_000_000},
    ],
    "annual_revenue_growth": [
        {"year": 2025, "revenue": 97_700_000_000, "net_income": 9_300_000_000, "yoy_pct": 0.95, "ni_yoy_pct": -28.46},
        {"year": 2024, "revenue": 96_800_000_000, "net_income": 13_000_000_000, "yoy_pct": -0.94, "ni_yoy_pct": 18.18},
        {"year": 2023, "revenue": 97_700_000_000, "net_income": 11_000_000_000, "yoy_pct": 18.79},
        {"year": 2022, "revenue": 82_200_000_000, "net_income": 9_100_000_000},
    ],
    "dividend_history": [],
    "dividend_consecutive_years": 0,
    "pe_history": {},
    "query_time": "2026-05-21T10:00:00",
}

_NVDA_FUND: dict = {
    "symbol": "NVDA",
    "valuation": {"pe_ratio": 58.92, "forward_pe": 38.10, "pb_ratio": 45.67, "ps_ratio": 32.41, "peg_ratio": 1.18},
    "per_share": {"eps_ttm": 18.45, "eps_forward": 28.55, "book_value": 23.81, "revenue_per_share": 33.56},
    "profitability": {"roe": 115.82, "roa": 55.63, "profit_margin": 55.04, "gross_margin": 75.29, "operating_margin": 61.87},
    "dividend": {"dividend_yield": 0.02, "dividend_rate": 0.16, "payout_ratio": 1.08, "ex_dividend_date": "2026-06-11"},
    "summary": {
        "sector": "Technology", "industry": "Semiconductors",
        "market_cap": 2_678_000_000_000, "enterprise_value": 2_655_000_000_000,
        "fifty_two_week_high": 1142.50, "fifty_two_week_low": 475.20,
        "fifty_day_avg": 1050.80, "two_hundred_day_avg": 892.40,
        "beta": 1.68, "short_ratio": 1.12,
    },
    "quarterly_financials": [
        {"period": "2026-Q1", "revenue": 26_000_000_000, "net_income": 14_900_000_000, "gross_profit": 19_600_000_000, "operating_income": 16_800_000_000, "ebitda": 17_500_000_000, "qoq_pct": 17.65},
        {"period": "2025-Q4", "revenue": 22_100_000_000, "net_income": 12_300_000_000, "gross_profit": 16_700_000_000, "operating_income": 13_600_000_000, "ebitda": 14_200_000_000, "qoq_pct": 22.1},
        {"period": "2025-Q3", "revenue": 18_100_000_000, "net_income": 9_200_000_000, "gross_profit": 13_500_000_000, "operating_income": 10_400_000_000, "ebitda": 11_000_000_000, "qoq_pct": 34.07},
        {"period": "2025-Q2", "revenue": 13_500_000_000, "net_income": 6_200_000_000, "gross_profit": 9_800_000_000, "operating_income": 7_300_000_000, "ebitda": 7_800_000_000},
    ],
    "annual_revenue_growth": [
        {"year": 2026, "revenue": 130_000_000_000, "net_income": 73_000_000_000, "yoy_pct": 65.47, "ni_yoy_pct": 64.75},
        {"year": 2025, "revenue": 78_500_000_000, "net_income": 44_300_000_000, "yoy_pct": 114.2, "ni_yoy_pct": 144.89},
        {"year": 2024, "revenue": 36_600_000_000, "net_income": 18_100_000_000, "yoy_pct": 125.85},
        {"year": 2023, "revenue": 16_200_000_000, "net_income": 2_660_000_000},
    ],
    "dividend_history": [
        {"year": 2022, "amount": 0.016},
        {"year": 2023, "amount": 0.016},
        {"year": 2024, "amount": 0.034},
        {"year": 2025, "amount": 0.04},
        {"year": 2026, "amount": 0.26},
    ],
    "dividend_consecutive_years": 15,
    "pe_history": {
        "labels": [f"{y}-{m:02d}" for y in range(2021, 2026) for m in range(1, 13)][-42:],
        "series": [85.0, 92.3, 78.5, 65.2, 45.8, 38.4, 33.1, 30.5, 28.9, 31.4, 33.2, 31.5] * 4,
        "median": 55.6, "p10": 28.0, "p25": 34.0, "p75": 97.4, "p90": 128.5,
        "current_pe": 31.52, "current_percentile": 19.0, "samples": 42,
    },
    "query_time": "2026-05-21T10:00:00",
}


# ── Registry builder ─────────────────────────────────────────────────────────

def _build_stock(
    symbol: str,
    full_klines: list[dict],
    full_indicators: dict,
    fundamentals: dict,
    period: str,
) -> dict:
    klines, indicators = _trim_to_period(full_klines, full_indicators, period)
    last = klines[-1] if klines else full_klines[-1]
    prev = klines[-2] if len(klines) > 1 else full_klines[-2]

    quote = {
        "symbol": symbol,
        "current_price": last["close"],
        "previous_close": prev["close"],
        "market_cap": fundamentals["summary"]["market_cap"],
        "currency": "USD",
        "query_time": "2026-05-21T10:00:00",
    }

    patterns = detect_patterns(klines)

    score = compute_composite_score(
        indicators=indicators,
        fundamentals=fundamentals,
        kline=klines,
        patterns=patterns,
    )

    grade_label = score["grade"]["label"]
    commentary_map = {
        "強勢": "技術面多頭排列，均線呈多頭排列；基本面獲利能力穩健。短期策略建議：順勢操作，逢回佈局。",
        "偏多": "技術面偏多，RSI 處於健康區間；基本面估值合理。短期策略建議：可逢回佈局，注意壓力位。",
        "中性": "技術面與基本面訊號交織，多空力道均衡。短期策略建議：觀望為主，等待方向明確。",
        "偏空": "技術面偏弱，均線趨勢向下；基本面承壓。短期策略建議：謹慎操作，注意支撐位。",
        "弱勢": "技術面明顯弱勢，多項指標超賣；基本面數據疲軟。短期策略建議：避開或減碼，等待止穩訊號。",
    }

    return {
        "symbol": symbol,
        "period": period,
        "is_mock": True,
        "latest_quote": quote,
        "kline": klines,
        "indicators": indicators,
        "fundamentals": fundamentals,
        "score": score,
        "patterns": patterns,
        "commentary": commentary_map.get(grade_label, ""),
    }


_STOCKS = {
    "AAPL": (_AAPL_FULL, _AAPL_IND, _AAPL_FUND),
    "TSLA": (_TSLA_FULL, _TSLA_IND, _TSLA_FUND),
    "NVDA": (_NVDA_FULL, _NVDA_IND, _NVDA_FUND),
}


def get_mock_response(ticker: str, period: str = "3M") -> dict:
    if ticker in _STOCKS:
        full_kl, full_ind, fund = _STOCKS[ticker]
        return _build_stock(ticker, full_kl, full_ind, fund, period)
    return _build_generic(ticker, period)


def get_mock_chart_data(ticker: str, period: str = "3M") -> dict:
    if ticker in _STOCKS:
        full_kl, full_ind, *_ = _STOCKS[ticker]
    else:
        full_kl = _generate_klines(150.0, f"{ticker}-full", 420)
        full_ind = _attach_indicators(full_kl)
    klines, indicators = _trim_to_period(full_kl, full_ind, period)
    return {"symbol": ticker, "period": period, "kline": klines, "indicators": indicators}


def get_mock_batch_quotes(tickers: list[str]) -> list[dict]:
    results = []
    for ticker in tickers:
        resp = get_mock_response(ticker, "1M")
        q = resp["latest_quote"]
        diff = round(q["current_price"] - q["previous_close"], 2)
        pct = round((diff / q["previous_close"]) * 100, 2) if q["previous_close"] else 0
        results.append({
            "symbol": ticker,
            "current_price": q["current_price"],
            "previous_close": q["previous_close"],
            "change": diff,
            "change_pct": pct,
            "currency": q.get("currency", "USD"),
            "market_cap": q.get("market_cap"),
            "error": None,
        })
    return results


def _build_generic(ticker: str, period: str) -> dict:
    full_klines = _generate_klines(150.0, f"{ticker}-full", 420)
    full_ind = _attach_indicators(full_klines)
    klines, indicators = _trim_to_period(full_klines, full_ind, period)

    last = klines[-1] if klines else full_klines[-1]
    prev = klines[-2] if len(klines) > 1 else full_klines[-2]
    rng = random.Random(ticker)

    fund = {
        "symbol": ticker,
        "valuation": {"pe_ratio": round(rng.uniform(10, 60), 2), "forward_pe": round(rng.uniform(8, 50), 2), "pb_ratio": round(rng.uniform(1, 20), 2), "ps_ratio": round(rng.uniform(1, 15), 2), "peg_ratio": round(rng.uniform(0.5, 4), 2)},
        "per_share": {"eps_ttm": round(rng.uniform(1, 20), 2), "eps_forward": round(rng.uniform(1, 25), 2), "book_value": round(rng.uniform(5, 50), 2), "revenue_per_share": round(rng.uniform(10, 80), 2)},
        "profitability": {"roe": round(rng.uniform(5, 50), 2), "roa": round(rng.uniform(2, 25), 2), "profit_margin": round(rng.uniform(5, 30), 2), "gross_margin": round(rng.uniform(20, 60), 2), "operating_margin": round(rng.uniform(5, 35), 2)},
        "dividend": {"dividend_yield": round(rng.uniform(0, 3), 2), "dividend_rate": round(rng.uniform(0, 5), 2), "payout_ratio": round(rng.uniform(10, 60), 2), "ex_dividend_date": None},
        "summary": {"sector": "Technology", "industry": "Software", "market_cap": None, "enterprise_value": None, "fifty_two_week_high": None, "fifty_two_week_low": None, "fifty_day_avg": None, "two_hundred_day_avg": None, "beta": round(rng.uniform(0.5, 2.5), 2), "short_ratio": round(rng.uniform(0.5, 5), 2)},
        "quarterly_financials": [],
        "query_time": "2026-05-21T10:00:00",
    }

    patterns = detect_patterns(klines)

    score = compute_composite_score(
        indicators=indicators, fundamentals=fund,
        kline=klines, patterns=patterns,
    )

    return {
        "symbol": ticker,
        "period": period,
        "is_mock": True,
        "latest_quote": {
            "symbol": ticker, "current_price": last["close"], "previous_close": prev["close"],
            "market_cap": int(last["close"] * rng.randint(100_000_000, 5_000_000_000)),
            "currency": "USD", "query_time": "2026-05-21T10:00:00",
        },
        "kline": klines,
        "indicators": indicators,
        "fundamentals": fund,
        "score": score,
        "patterns": patterns,
        "commentary": "技術面與基本面訊號交織，多空力道均衡。短期策略建議：觀望為主。",
    }


# ── Mock peer comparison ──────────────────────────────────────────────────────

_MOCK_PEERS = {
    "AAPL": ["MSFT", "GOOGL", "META"],
    "TSLA": ["F", "GM", "RIVN"],
    "NVDA": ["AMD", "INTC", "AVGO"],
}

def _mock_relative_perf(symbols: list[str], seed: str, days: int = 60) -> dict:
    rng = random.Random(seed)
    labels = []
    d = date(2026, 5, 21) - timedelta(days=days)
    while d <= date(2026, 5, 21):
        if d.weekday() < 5:
            labels.append(str(d)[5:])
        d += timedelta(days=1)
    series = {}
    for sym in symbols:
        r = random.Random(f"{seed}-{sym}")
        val = 100.0
        points = []
        for _ in labels:
            val *= (1 + r.gauss(0.001, 0.015))
            points.append(round(val, 2))
        series[sym] = points
    return {"labels": labels, "series": series}


def _mock_comparison_row(symbol: str, is_target=False, is_index=False) -> dict:
    rng = random.Random(symbol)
    return {
        "symbol": symbol,
        "score": rng.randint(35, 85),
        "pe": round(rng.uniform(10, 60), 1),
        "roe": round(rng.uniform(5, 50), 1),
        "margin": round(rng.uniform(5, 35), 1),
        "mcap": int(rng.uniform(50e9, 4e12)),
        "return_period": round(rng.uniform(-10, 25), 2),
        "yield": round(rng.uniform(0, 4), 2),
        "beta": round(rng.uniform(0.5, 2.5), 2),
        "is_target": is_target,
        "is_index": is_index,
        "error": None,
    }


def get_mock_peer_comparison(ticker: str, period: str = "3M") -> dict:
    peers = _MOCK_PEERS.get(ticker, ["MSFT", "GOOGL", "META"])
    index = "0050.TW" if ".TW" in ticker else "SPY"
    all_syms = [ticker] + peers + [index]

    table = []
    for sym in all_syms:
        table.append(_mock_comparison_row(sym, is_target=(sym == ticker), is_index=(sym == index)))

    perf = _mock_relative_perf(all_syms, f"peer-{ticker}-{period}")

    return {
        "symbol": ticker,
        "peers": peers,
        "index": index,
        "comparison_table": table,
        "relative_performance": perf,
    }


def get_mock_watchlist_comparison(tickers: list[str], period: str = "3M") -> dict:
    tw_count = sum(1 for t in tickers if ".TW" in t)
    index = "0050.TW" if tw_count > len(tickers) / 2 else "SPY"
    all_syms = tickers + [index]

    table = [_mock_comparison_row(sym, is_index=(sym == index)) for sym in all_syms]
    perf = _mock_relative_perf(all_syms, f"wl-{','.join(tickers)}-{period}")

    return {
        "tickers": tickers,
        "index": index,
        "comparison_table": table,
        "relative_performance": perf,
    }


# ── Mock stock screener ───────────────────────────────────────────────────────

_MOCK_SCREENER_STOCKS = [
    {"rank": 1,  "symbol": "2330.TW", "name": "台積電",   "score": 87, "close": 2380, "change_pct": 1.21, "pe": 32.3, "yield_pct": 1.02, "volume": 45678},
    {"rank": 2,  "symbol": "2454.TW", "name": "聯發科",   "score": 83, "close": 1890, "change_pct": 2.15, "pe": 18.5, "yield_pct": 2.31, "volume": 12345},
    {"rank": 3,  "symbol": "3661.TW", "name": "世芯-KY",  "score": 79, "close": 2650, "change_pct": 3.42, "pe": 25.1, "yield_pct": 0.45, "volume": 5678},
    {"rank": 4,  "symbol": "2881.TW", "name": "富邦金",   "score": 76, "close": 92.5, "change_pct": 0.87, "pe": 12.1, "yield_pct": 4.52, "volume": 34567},
    {"rank": 5,  "symbol": "2382.TW", "name": "廣達",     "score": 75, "close": 345,  "change_pct": 1.89, "pe": 15.8, "yield_pct": 3.21, "volume": 23456},
    {"rank": 6,  "symbol": "2317.TW", "name": "鴻海",     "score": 74, "close": 210,  "change_pct": 0.48, "pe": 11.2, "yield_pct": 5.12, "volume": 67890},
    {"rank": 7,  "symbol": "3711.TW", "name": "日月光投控","score": 73, "close": 178,  "change_pct": 1.15, "pe": 14.5, "yield_pct": 3.45, "volume": 18234},
    {"rank": 8,  "symbol": "2308.TW", "name": "台達電",   "score": 72, "close": 415,  "change_pct": -0.24,"pe": 28.3, "yield_pct": 1.89, "volume": 9876},
    {"rank": 9,  "symbol": "2886.TW", "name": "兆豐金",   "score": 71, "close": 52.8, "change_pct": 0.57, "pe": 15.2, "yield_pct": 5.68, "volume": 45123},
    {"rank": 10, "symbol": "2303.TW", "name": "聯電",     "score": 70, "close": 62.3, "change_pct": 2.46, "pe": 9.8,  "yield_pct": 6.12, "volume": 56789},
    {"rank": 11, "symbol": "1301.TW", "name": "台塑",     "score": 69, "close": 52.1, "change_pct": -0.57,"pe": 22.1, "yield_pct": 4.81, "volume": 12345},
    {"rank": 12, "symbol": "2891.TW", "name": "中信金",   "score": 68, "close": 33.8, "change_pct": 1.04, "pe": 13.5, "yield_pct": 5.32, "volume": 78901},
    {"rank": 13, "symbol": "2412.TW", "name": "中華電",   "score": 67, "close": 132,  "change_pct": 0.15, "pe": 27.8, "yield_pct": 3.79, "volume": 8765},
    {"rank": 14, "symbol": "3008.TW", "name": "大立光",   "score": 66, "close": 2180, "change_pct": 1.86, "pe": 19.4, "yield_pct": 2.98, "volume": 1234},
    {"rank": 15, "symbol": "2884.TW", "name": "玉山金",   "score": 65, "close": 31.2, "change_pct": 0.65, "pe": 14.8, "yield_pct": 4.17, "volume": 34567},
    {"rank": 16, "symbol": "2357.TW", "name": "華碩",     "score": 64, "close": 580,  "change_pct": 2.29, "pe": 12.9, "yield_pct": 5.45, "volume": 6789},
    {"rank": 17, "symbol": "1303.TW", "name": "南亞",     "score": 63, "close": 45.6, "change_pct": -1.08,"pe": 35.2, "yield_pct": 3.95, "volume": 23456},
    {"rank": 18, "symbol": "2882.TW", "name": "國泰金",   "score": 62, "close": 68.9, "change_pct": 0.73, "pe": 11.8, "yield_pct": 4.63, "volume": 45678},
    {"rank": 19, "symbol": "5871.TW", "name": "中租-KY",  "score": 61, "close": 265,  "change_pct": 1.53, "pe": 10.5, "yield_pct": 6.32, "volume": 7890},
    {"rank": 20, "symbol": "2379.TW", "name": "瑞昱",     "score": 60, "close": 520,  "change_pct": 0.97, "pe": 21.3, "yield_pct": 2.15, "volume": 5432},
]


def get_mock_screener() -> dict:
    return {
        "last_updated": "2026-06-04T14:30:00",
        "total_stocks": 2487,
        "top_picks": _MOCK_SCREENER_STOCKS,
    }


def get_mock_backtest() -> dict:
    """Mock forward-return backtest results for frontend development."""
    from statistics import median as _median
    random.seed(42)

    forward_days = [1, 3, 5, 10, 20]
    mock_stocks = [
        ("2330.TW", "台積電"), ("2454.TW", "聯發科"), ("2317.TW", "鴻海"),
        ("2382.TW", "廣達"), ("3008.TW", "大立光"), ("2881.TW", "富邦金"),
        ("2303.TW", "聯電"), ("2412.TW", "中華電"), ("1301.TW", "台塑"),
        ("2886.TW", "兆豐金"), ("2891.TW", "中信金"), ("3711.TW", "日月投"),
        ("2002.TW", "中鋼"), ("1216.TW", "統一"), ("2884.TW", "玉山金"),
        ("5871.TW", "中租-KY"), ("2357.TW", "華碩"), ("4904.TW", "遠傳"),
        ("2327.TW", "國巨"), ("6669.TW", "緯穎"),
    ]

    signals = []
    base = date(2025, 7, 15)
    for i in range(60):
        signal_date = (base + timedelta(days=i * 7 // 5)).isoformat()
        buy_date = (base + timedelta(days=i * 7 // 5 + 1)).isoformat()

        day_stocks = random.sample(mock_stocks, 20)
        for rank, (sym, name) in enumerate(day_stocks, 1):
            score = round(random.uniform(50, 85) - (rank - 1) * 1.2, 1)
            entry_price = round(random.uniform(30, 900), 2)

            returns = {}
            benchmark_returns = {}
            for n in forward_days:
                rank_bonus = (21 - rank) * 0.015
                ret = round(random.gauss(0.08 + rank_bonus, 1.2 * (n ** 0.5)), 2)
                bench = round(random.gauss(0.04, 0.7 * (n ** 0.5)), 2)
                returns[n] = ret
                benchmark_returns[n] = bench

            signals.append({
                "signal_date": signal_date,
                "buy_date": buy_date,
                "symbol": sym,
                "name": name,
                "rank": rank,
                "score": score,
                "entry_price": entry_price,
                "returns": returns,
                "benchmark_returns": benchmark_returns,
            })

    def _horizon_stats(sigs, n):
        rets = [s["returns"][n] for s in sigs if n in s["returns"]]
        bench = [s["benchmark_returns"][n] for s in sigs if n in s["benchmark_returns"]]
        if not rets:
            return {"count": 0, "avg_return": 0, "median_return": 0,
                    "win_rate": 0, "avg_benchmark": 0, "avg_excess": 0}
        avg_r = sum(rets) / len(rets)
        avg_b = sum(bench) / len(bench) if bench else 0
        return {
            "count": len(rets),
            "avg_return": round(avg_r, 2),
            "median_return": round(_median(rets), 2),
            "win_rate": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1),
            "avg_benchmark": round(avg_b, 2),
            "avg_excess": round(avg_r - avg_b, 2),
        }

    by_horizon = {str(n): _horizon_stats(signals, n) for n in forward_days}

    rank_groups = [(1, 5), (6, 10), (11, 15), (16, 20)]
    by_rank_group = {}
    for lo, hi in rank_groups:
        group = [s for s in signals if lo <= s["rank"] <= hi]
        by_rank_group[f"{lo}-{hi}"] = {
            str(n): _horizon_stats(group, n) for n in forward_days
        }

    return {
        "period": {
            "start": "2025-07-15",
            "end": "2026-06-09",
            "trading_days": 150,
        },
        "config": {
            "top_n": 20,
            "forward_days": forward_days,
        },
        "summary": {
            "total_signals": len(signals),
            "by_horizon": by_horizon,
            "by_rank_group": by_rank_group,
        },
        "signals": signals,
    }
