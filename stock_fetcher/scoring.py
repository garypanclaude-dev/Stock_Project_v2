"""
Composite Investment Score — rule-based scoring engine.

Pure functions: no I/O, no API calls. Takes pre-fetched data and returns scores.
"""
from __future__ import annotations

from . import scoring_config as cfg


# ── Public API ────────────────────────────────────────────────────────────────

def compute_composite_score(
    indicators: dict | None,
    fundamentals: dict | None,
    sentiment_summary: dict | None,
    catalysts: list[dict] | None,
    kline: list[dict] | None,
) -> dict:
    """
    Compute the composite investment score (0-100).

    Returns a dict with:
      - composite: int (0-100)
      - grade: { label, label_en, color }
      - technical: { score, details }
      - fundamental: { score, details }
      - sentiment: { score, details, available }
      - weights_used: which weight set was applied
    """
    tech = _score_technical(indicators, kline)
    fund = _score_fundamental(fundamentals)
    sent = _score_sentiment(sentiment_summary, catalysts)

    if sent["available"]:
        weights = cfg.DIMENSION_WEIGHTS
    else:
        weights = cfg.FALLBACK_WEIGHTS

    composite = 0.0
    if sent["available"]:
        composite = (
            tech["score"] * weights["technical"]
            + fund["score"] * weights["fundamental"]
            + sent["score"] * weights["sentiment"]
        )
    else:
        composite = (
            tech["score"] * weights["technical"]
            + fund["score"] * weights["fundamental"]
        )

    composite = _clamp(round(composite))
    grade = _get_grade(composite)

    return {
        "composite": composite,
        "grade": grade,
        "technical": tech,
        "fundamental": fund,
        "sentiment": sent,
        "weights_used": weights,
    }


# ── Technical Score ───────────────────────────────────────────────────────────

def _score_technical(indicators: dict | None, kline: list[dict] | None) -> dict:
    rsi_score = _score_rsi(indicators)
    macd_score = _score_macd(indicators)
    ma_score = _score_ma_alignment(indicators, kline)
    bb_score = _score_bollinger(indicators, kline)

    total = (
        rsi_score * cfg.TECH_WEIGHTS["rsi"]
        + macd_score * cfg.TECH_WEIGHTS["macd"]
        + ma_score * cfg.TECH_WEIGHTS["ma_alignment"]
        + bb_score * cfg.TECH_WEIGHTS["bollinger"]
    )

    return {
        "score": _clamp(round(total)),
        "details": {
            "rsi": rsi_score,
            "macd": macd_score,
            "ma_alignment": ma_score,
            "bollinger": bb_score,
        },
    }


def _score_rsi(indicators: dict | None) -> int:
    if not indicators or not indicators.get("rsi"):
        return cfg.RSI_DEFAULT
    rsi_values = [v for v in indicators["rsi"] if v is not None]
    if not rsi_values:
        return cfg.RSI_DEFAULT
    latest_rsi = rsi_values[-1]
    return _lookup_score(latest_rsi, cfg.RSI_SCORES, cfg.RSI_DEFAULT)


def _score_macd(indicators: dict | None) -> int:
    if not indicators or not indicators.get("macd"):
        return cfg.MACD_DEFAULT
    macd_line = indicators["macd"].get("macd", [])
    signal_line = indicators["macd"].get("signal", [])
    histogram = indicators["macd"].get("histogram", [])

    valid_hist = [v for v in histogram if v is not None]
    valid_macd = [v for v in macd_line if v is not None]
    valid_signal = [v for v in signal_line if v is not None]

    if not valid_macd or not valid_signal:
        return cfg.MACD_DEFAULT

    macd_above_signal = valid_macd[-1] > valid_signal[-1]
    hist_expanding = len(valid_hist) >= 2 and abs(valid_hist[-1]) > abs(valid_hist[-2])

    if macd_above_signal and hist_expanding:
        return cfg.MACD_BULLISH_EXPANDING
    elif macd_above_signal and not hist_expanding:
        return cfg.MACD_BULLISH_SHRINKING
    elif not macd_above_signal and not hist_expanding:
        return cfg.MACD_BEARISH_SHRINKING
    else:
        return cfg.MACD_BEARISH_EXPANDING


def _score_ma_alignment(indicators: dict | None, kline: list[dict] | None) -> int:
    if not indicators or not indicators.get("ma") or not kline:
        return cfg.MACD_DEFAULT

    price = kline[-1]["close"]
    ma = indicators["ma"]

    def _last_valid(key):
        vals = ma.get(key, [])
        valid = [v for v in vals if v is not None]
        return valid[-1] if valid else None

    ma5 = _last_valid("ma5")
    ma10 = _last_valid("ma10")
    ma20 = _last_valid("ma20")
    ma60 = _last_valid("ma60")

    points = 0
    if ma5 is not None and price > ma5:
        points += cfg.MA_POINTS["price_above_ma5"]
    if ma10 is not None and price > ma10:
        points += cfg.MA_POINTS["price_above_ma10"]
    if ma20 is not None and price > ma20:
        points += cfg.MA_POINTS["price_above_ma20"]
    if ma60 is not None and price > ma60:
        points += cfg.MA_POINTS["price_above_ma60"]
    if ma5 is not None and ma20 is not None and ma5 > ma20:
        points += cfg.MA_POINTS["ma5_above_ma20"]
    if ma20 is not None and ma60 is not None and ma20 > ma60:
        points += cfg.MA_POINTS["ma20_above_ma60"]

    return _clamp(points)


def _score_bollinger(indicators: dict | None, kline: list[dict] | None) -> int:
    if not indicators or not indicators.get("bollinger") or not kline:
        return cfg.BB_DEFAULT

    bb = indicators["bollinger"]
    upper_vals = [v for v in bb.get("upper", []) if v is not None]
    lower_vals = [v for v in bb.get("lower", []) if v is not None]

    if not upper_vals or not lower_vals:
        return cfg.BB_DEFAULT

    upper = upper_vals[-1]
    lower = lower_vals[-1]
    price = kline[-1]["close"]

    band_width = upper - lower
    if band_width <= 0:
        return cfg.BB_DEFAULT

    position = (price - lower) / band_width  # 0.0 = lower, 1.0 = upper
    return _lookup_score(position, cfg.BB_SCORES, cfg.BB_DEFAULT)


# ── Fundamental Score ─────────────────────────────────────────────────────────

def _score_fundamental(fundamentals: dict | None) -> dict:
    pe_score = _score_pe(fundamentals)
    roe_score = _score_roe(fundamentals)
    rev_score = _score_revenue_trend(fundamentals)
    margin_score = _score_profit_margin(fundamentals)
    div_score = _score_dividend(fundamentals)

    total = (
        pe_score * cfg.FUND_WEIGHTS["pe"]
        + roe_score * cfg.FUND_WEIGHTS["roe"]
        + rev_score * cfg.FUND_WEIGHTS["revenue_trend"]
        + margin_score * cfg.FUND_WEIGHTS["profit_margin"]
        + div_score * cfg.FUND_WEIGHTS["dividend"]
    )

    return {
        "score": _clamp(round(total)),
        "details": {
            "pe": pe_score,
            "roe": roe_score,
            "revenue_trend": rev_score,
            "profit_margin": margin_score,
            "dividend": div_score,
        },
    }


def _score_pe(fund: dict | None) -> int:
    if not fund:
        return cfg.PE_DEFAULT
    pe = (fund.get("valuation") or {}).get("pe_ratio")
    if pe is None or pe < 0:
        return cfg.PE_DEFAULT
    return _lookup_score(pe, cfg.PE_SCORES[1:], cfg.PE_DEFAULT)  # skip the <0 entry


def _score_roe(fund: dict | None) -> int:
    if not fund:
        return cfg.ROE_DEFAULT
    roe = (fund.get("profitability") or {}).get("roe")
    if roe is None:
        return cfg.ROE_DEFAULT
    return _lookup_score(roe, cfg.ROE_SCORES, cfg.ROE_DEFAULT)


def _score_revenue_trend(fund: dict | None) -> int:
    if not fund:
        return cfg.REVENUE_TREND["no_data"]
    quarters = fund.get("quarterly_financials") or []
    if len(quarters) < 2:
        return cfg.REVENUE_TREND["no_data"]

    # quarters are newest-first from API; reverse for chronological order
    revenues = [q.get("revenue") for q in reversed(quarters) if q.get("revenue")]
    if len(revenues) < 2:
        return cfg.REVENUE_TREND["no_data"]

    # Count consecutive growth/decline from the most recent quarter
    growth_streak = 0
    decline_streak = 0
    for i in range(len(revenues) - 1, 0, -1):
        change_pct = (revenues[i] - revenues[i - 1]) / abs(revenues[i - 1]) * 100 if revenues[i - 1] else 0
        if change_pct > 5:
            growth_streak += 1
            decline_streak = 0
        elif change_pct < -5:
            decline_streak += 1
            growth_streak = 0
        else:
            break

    if growth_streak >= 3:
        return cfg.REVENUE_TREND["growth_3q"]
    if growth_streak == 2:
        return cfg.REVENUE_TREND["growth_2q"]
    if growth_streak == 1:
        return cfg.REVENUE_TREND["growth_1q"]
    if decline_streak >= 2:
        return cfg.REVENUE_TREND["decline_2q_plus"]
    if decline_streak == 1:
        return cfg.REVENUE_TREND["decline_1q"]
    return cfg.REVENUE_TREND["flat"]


def _score_profit_margin(fund: dict | None) -> int:
    if not fund:
        return cfg.MARGIN_DEFAULT
    margin = (fund.get("profitability") or {}).get("profit_margin")
    if margin is None:
        return cfg.MARGIN_DEFAULT
    return _lookup_score(margin, cfg.MARGIN_SCORES, cfg.MARGIN_DEFAULT)


def _score_dividend(fund: dict | None) -> int:
    if not fund:
        return cfg.DIVIDEND_DEFAULT
    div_yield = (fund.get("dividend") or {}).get("dividend_yield")
    if div_yield is None:
        return cfg.DIVIDEND_DEFAULT
    return _lookup_score(div_yield, cfg.DIVIDEND_SCORES, cfg.DIVIDEND_DEFAULT)


# ── Sentiment Score ───────────────────────────────────────────────────────────

def _score_sentiment(
    sentiment_summary: dict | None,
    catalysts: list[dict] | None,
) -> dict:
    if not sentiment_summary or sentiment_summary.get("total", 0) == 0:
        return {"score": 50, "available": False, "details": {}}

    ratio_score = _score_bull_bear_ratio(sentiment_summary)
    count_score = _score_catalyst_count(catalysts)
    impact_score = _score_catalyst_impact(catalysts)

    total = (
        ratio_score * cfg.SENT_WEIGHTS["bull_bear_ratio"]
        + count_score * cfg.SENT_WEIGHTS["catalyst_count"]
        + impact_score * cfg.SENT_WEIGHTS["catalyst_impact"]
    )

    return {
        "score": _clamp(round(total)),
        "available": True,
        "details": {
            "bull_bear_ratio": ratio_score,
            "catalyst_count": count_score,
            "catalyst_impact": impact_score,
        },
    }


def _score_bull_bear_ratio(ss: dict) -> int:
    total = ss.get("total", 0)
    if total == 0:
        return 50
    bullish = ss.get("bullish", 0)
    return _clamp(round((bullish / total) * 100))


def _score_catalyst_count(catalysts: list[dict] | None) -> int:
    if not catalysts:
        return cfg.CATALYST_COUNT_SCORES[0]
    count = len(catalysts)
    return cfg.CATALYST_COUNT_SCORES.get(count, cfg.CATALYST_COUNT_DEFAULT)


def _score_catalyst_impact(catalysts: list[dict] | None) -> int:
    if not catalysts:
        return 50

    bullish_impact = 0.0
    bearish_impact = 0.0

    for c in catalysts:
        cat_type = c.get("catalyst_type", "")
        weight = cfg.CATALYST_IMPACT.get(cat_type, cfg.CATALYST_IMPACT_DEFAULT)
        sentiment = c.get("sentiment", "Neutral")
        if sentiment == "Bullish":
            bullish_impact += weight
        elif sentiment == "Bearish":
            bearish_impact += weight

    total_impact = bullish_impact + bearish_impact
    if total_impact == 0:
        return 50

    return _clamp(round((bullish_impact / total_impact) * 100))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _lookup_score(value: float, thresholds: list[tuple], default: int) -> int:
    """Lookup score from a list of (upper_bound_exclusive, score) tuples."""
    for upper, score in thresholds:
        if value < upper:
            return score
    return default


def _get_grade(score: int) -> dict:
    for g in cfg.GRADES:
        if g["min"] <= score <= g["max"]:
            return {"label": g["label"], "label_en": g["label_en"], "color": g["color"]}
    return {"label": "中性", "label_en": "Neutral", "color": "#f59e0b"}


def _clamp(value: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, value))
