"""Mock data for UI development — no external API calls needed."""
from __future__ import annotations

import math
import random
from datetime import date, timedelta

from stock_fetcher.indicators import compute_all
from stock_fetcher.scoring import compute_composite_score


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
    return compute_all(closes)


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
        {"period": "2026-Q1", "revenue": 124_300_000_000, "net_income": 33_900_000_000, "gross_profit": 58_100_000_000, "operating_income": 39_800_000_000, "ebitda": 44_200_000_000},
        {"period": "2025-Q4", "revenue": 98_000_000_000, "net_income": 25_000_000_000, "gross_profit": 45_500_000_000, "operating_income": 30_900_000_000, "ebitda": 34_800_000_000},
        {"period": "2025-Q3", "revenue": 94_900_000_000, "net_income": 23_600_000_000, "gross_profit": 43_900_000_000, "operating_income": 29_600_000_000, "ebitda": 33_200_000_000},
        {"period": "2025-Q2", "revenue": 85_800_000_000, "net_income": 21_400_000_000, "gross_profit": 39_400_000_000, "operating_income": 26_500_000_000, "ebitda": 30_100_000_000},
    ],
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
        {"period": "2026-Q1", "revenue": 21_300_000_000, "net_income": 1_800_000_000, "gross_profit": 3_800_000_000, "operating_income": 1_600_000_000, "ebitda": 3_200_000_000},
        {"period": "2025-Q4", "revenue": 25_200_000_000, "net_income": 2_500_000_000, "gross_profit": 4_700_000_000, "operating_income": 2_100_000_000, "ebitda": 3_900_000_000},
        {"period": "2025-Q3", "revenue": 23_400_000_000, "net_income": 2_200_000_000, "gross_profit": 4_200_000_000, "operating_income": 1_900_000_000, "ebitda": 3_600_000_000},
        {"period": "2025-Q2", "revenue": 24_900_000_000, "net_income": 2_700_000_000, "gross_profit": 4_900_000_000, "operating_income": 2_300_000_000, "ebitda": 4_100_000_000},
    ],
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
        {"period": "2026-Q1", "revenue": 26_000_000_000, "net_income": 14_900_000_000, "gross_profit": 19_600_000_000, "operating_income": 16_800_000_000, "ebitda": 17_500_000_000},
        {"period": "2025-Q4", "revenue": 22_100_000_000, "net_income": 12_300_000_000, "gross_profit": 16_700_000_000, "operating_income": 13_600_000_000, "ebitda": 14_200_000_000},
        {"period": "2025-Q3", "revenue": 18_100_000_000, "net_income": 9_200_000_000, "gross_profit": 13_500_000_000, "operating_income": 10_400_000_000, "ebitda": 11_000_000_000},
        {"period": "2025-Q2", "revenue": 13_500_000_000, "net_income": 6_200_000_000, "gross_profit": 9_800_000_000, "operating_income": 7_300_000_000, "ebitda": 7_800_000_000},
    ],
    "query_time": "2026-05-21T10:00:00",
}


# ── Catalysts (unchanged from v1) ────────────────────────────────────────────

_AAPL_CATALYSTS = [
    {"original_title": "Apple Reports Record Q2 Revenue of $98B, Services Hits All-Time High", "link": "https://example.com/aapl-q2", "published": "2026-05-15T22:00:00", "source": "Bloomberg", "sentiment": "Bullish", "catalyst_type": "earnings", "summary": "蘋果Q2營收破紀錄達980億美元，超預期5%；服務業務貢獻276億創歷史新高，EPS 1.65美元優於預期。"},
    {"original_title": "Apple Intelligence Gains 40M Users, JPMorgan Upgrades to Buy With $360 Target", "link": "https://example.com/aapl-upgrade", "published": "2026-05-18T14:30:00", "source": "JPMorgan", "sentiment": "Bullish", "catalyst_type": "analyst_rating", "summary": "摩根大通將AAPL目標價上調至360美元，因Apple Intelligence用戶3個月內突破4000萬，超預期40%。"},
    {"original_title": "EU Launches Antitrust Probe Into Apple App Store, Up to $5B Fine at Risk", "link": "https://example.com/aapl-eu", "published": "2026-05-19T09:00:00", "source": "Reuters", "sentiment": "Bearish", "catalyst_type": "regulation", "summary": "歐盟對App Store展開反壟斷調查，若裁定違規最高罰款50億美元，盤前股價應聲下跌2.3%。"},
    {"original_title": "Apple Vision Pro 2 Mass Production Starts, $2,499 Price Tag for Q4 2026", "link": "https://example.com/aapl-vp2", "published": "2026-05-20T11:00:00", "source": "Nikkei Asia", "sentiment": "Neutral", "catalyst_type": "product_launch", "summary": "Vision Pro 2開始量產，售價下調至2499美元（原3499），預計Q4上市，市場反應多空交織。"},
]

_TSLA_CATALYSTS = [
    {"original_title": "Tesla Q1 Deliveries Miss by 20%, Worst Quarter Since 2020", "link": "https://example.com/tsla-q1", "published": "2026-05-13T06:00:00", "source": "Wall Street Journal", "sentiment": "Bearish", "catalyst_type": "earnings", "summary": "Tesla Q1交車量34.7萬輛，較預期低20%，創2020年以來最差季度；EPS 0.45美元遠遜預期0.73美元。"},
    {"original_title": "Elon Musk Commits to Staying as Tesla CEO Through 2027", "link": "https://example.com/tsla-musk", "published": "2026-05-16T18:00:00", "source": "Financial Times", "sentiment": "Bullish", "catalyst_type": "management", "summary": "馬斯克公開承諾至少執掌Tesla至2027年，並排除出售持股計畫，緩解市場對其分心於其他業務的擔憂。"},
    {"original_title": "NHTSA Opens Formal Investigation Into Tesla FSD After 3 Fatal Crashes", "link": "https://example.com/tsla-nhtsa", "published": "2026-05-19T14:00:00", "source": "Reuters", "sentiment": "Bearish", "catalyst_type": "litigation", "summary": "美國NHTSA就Tesla FSD系統涉及3起死亡事故展開正式調查，可能觸發大規模召回，股價下跌4.1%。"},
]

_NVDA_CATALYSTS = [
    {"original_title": "NVIDIA Q1 Revenue Hits Record $26B, Data Center Up 427% YoY", "link": "https://example.com/nvda-q1", "published": "2026-05-15T20:00:00", "source": "Bloomberg", "sentiment": "Bullish", "catalyst_type": "earnings", "summary": "NVIDIA Q1營收260億美元創歷史新高，數據中心年增427%；預計Q2營收280億，再度超出市場預期。"},
    {"original_title": "US Expands AI Chip Export Restrictions to 40 More Countries", "link": "https://example.com/nvda-export", "published": "2026-05-17T16:00:00", "source": "Wall Street Journal", "sentiment": "Bearish", "catalyst_type": "regulation", "summary": "美國擴大AI晶片出口管制至40個新增國家，NVIDIA估計年損失約30億美元營收，盤前跌3.5%。"},
    {"original_title": "Microsoft Signs $10B Blackwell GPU Deal With NVIDIA Through 2027", "link": "https://example.com/nvda-msft", "published": "2026-05-19T11:00:00", "source": "Reuters", "sentiment": "Bullish", "catalyst_type": "m_and_a", "summary": "微軟與NVIDIA簽訂100億美元Blackwell GPU採購協議，鎖定至2027年，大幅提升NVIDIA營收能見度。"},
]


# ── Registry builder ─────────────────────────────────────────────────────────

def _build_stock(
    symbol: str,
    full_klines: list[dict],
    full_indicators: dict,
    fundamentals: dict,
    catalysts: list[dict],
    sentiment: dict,
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

    score = compute_composite_score(
        indicators=indicators,
        fundamentals=fundamentals,
        sentiment_summary=sentiment,
        catalysts=catalysts,
        kline=klines,
    )

    # Mock commentary based on grade
    grade_label = score["grade"]["label"]
    commentary_map = {
        "強勢": f"技術面多頭排列，均線呈多頭排列；基本面獲利能力穩健。短期策略建議：順勢操作，逢回佈局。",
        "偏多": f"技術面偏多，RSI 處於健康區間；基本面估值合理。短期策略建議：可逢回佈局，注意壓力位。",
        "中性": f"技術面與基本面訊號交織，多空力道均衡。短期策略建議：觀望為主，等待方向明確。",
        "偏空": f"技術面偏弱，均線趨勢向下；基本面承壓。短期策略建議：謹慎操作，注意支撐位。",
        "弱勢": f"技術面明顯弱勢，多項指標超賣；基本面數據疲軟。短期策略建議：避開或減碼，等待止穩訊號。",
    }

    return {
        "symbol": symbol,
        "period": period,
        "is_mock": True,
        "ai_error": None,
        "latest_quote": quote,
        "kline": klines,
        "indicators": indicators,
        "fundamentals": fundamentals,
        "catalysts": catalysts,
        "sentiment_summary": sentiment,
        "score": score,
        "commentary": commentary_map.get(grade_label, ""),
    }


_STOCKS = {
    "AAPL": (_AAPL_FULL, _AAPL_IND, _AAPL_FUND, _AAPL_CATALYSTS, {"bullish": 2, "bearish": 1, "neutral": 1, "total": 4}),
    "TSLA": (_TSLA_FULL, _TSLA_IND, _TSLA_FUND, _TSLA_CATALYSTS, {"bullish": 1, "bearish": 2, "neutral": 0, "total": 3}),
    "NVDA": (_NVDA_FULL, _NVDA_IND, _NVDA_FUND, _NVDA_CATALYSTS, {"bullish": 2, "bearish": 1, "neutral": 0, "total": 3}),
}


def get_mock_response(ticker: str, period: str = "3M") -> dict:
    if ticker in _STOCKS:
        full_kl, full_ind, fund, cats, sent = _STOCKS[ticker]
        return _build_stock(ticker, full_kl, full_ind, fund, cats, sent, period)
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
    sent = {"bullish": 0, "bearish": 0, "neutral": 0, "total": 0}

    score = compute_composite_score(
        indicators=indicators, fundamentals=fund,
        sentiment_summary=None, catalysts=None, kline=klines,
    )

    return {
        "symbol": ticker,
        "period": period,
        "is_mock": True,
        "ai_error": None,
        "latest_quote": {
            "symbol": ticker, "current_price": last["close"], "previous_close": prev["close"],
            "market_cap": int(last["close"] * rng.randint(100_000_000, 5_000_000_000)),
            "currency": "USD", "query_time": "2026-05-21T10:00:00",
        },
        "kline": klines,
        "indicators": indicators,
        "fundamentals": fund,
        "catalysts": [],
        "sentiment_summary": sent,
        "score": score,
        "commentary": "技術面與基本面訊號交織，無催化劑新聞。短期策略建議：觀望為主。",
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
