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
    patterns: list[dict] | None = None,
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
    tech = _score_technical(indicators, kline, patterns)
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

def _score_technical(
    indicators: dict | None,
    kline: list[dict] | None,
    patterns: list[dict] | None = None,
) -> dict:
    rsi_score  = _score_rsi(indicators)
    macd_score = _score_macd(indicators)
    ma_score   = _score_ma_alignment(indicators, kline)
    bb_score   = _score_bollinger(indicators, kline)
    kd_score   = _score_kd(indicators)
    obv_score  = _score_obv(indicators, kline)

    base = (
        rsi_score  * cfg.TECH_WEIGHTS["rsi"]
        + macd_score * cfg.TECH_WEIGHTS["macd"]
        + ma_score   * cfg.TECH_WEIGHTS["ma_alignment"]
        + bb_score   * cfg.TECH_WEIGHTS["bollinger"]
        + kd_score   * cfg.TECH_WEIGHTS["kd"]
        + obv_score  * cfg.TECH_WEIGHTS["obv"]
    )

    adjustment = _compute_pattern_adjustment(patterns, kline)

    return {
        "score": _clamp(round(base + adjustment)),
        "details": {
            "rsi": rsi_score,
            "macd": macd_score,
            "ma_alignment": ma_score,
            "bollinger": bb_score,
            "kd": kd_score,
            "obv": obv_score,
            "pattern_adjustment": adjustment,
        },
    }


def _compute_pattern_adjustment(
    patterns: list[dict] | None,
    kline: list[dict] | None,
) -> int:
    """Map recent candlestick patterns to a small additive technical adjustment.

    Bullish patterns add +PER_SIGNAL each, bearish subtract. Capped at ±CAP.
    Doji (neutral direction) contributes nothing. Only patterns within the
    last PATTERN_ADJUSTMENT_LOOKBACK kline bars are counted.
    """
    if not patterns or not kline:
        return 0

    n = len(kline)
    cutoff_index = n - cfg.PATTERN_ADJUSTMENT_LOOKBACK
    adjustment = 0
    for p in patterns:
        if p.get("index", -1) < cutoff_index:
            continue
        direction = p.get("direction")
        if direction == "bullish":
            adjustment += cfg.PATTERN_ADJUSTMENT_PER_SIGNAL
        elif direction == "bearish":
            adjustment -= cfg.PATTERN_ADJUSTMENT_PER_SIGNAL

    cap = cfg.PATTERN_ADJUSTMENT_CAP
    return max(-cap, min(cap, adjustment))


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
    """v2.0: classify into 4 states via indicators.ma_alignment object.

    Falls back to additive scoring if ma_alignment object missing (legacy).
    """
    if not indicators:
        return cfg.MA_ALIGNMENT_DEFAULT

    alignment = indicators.get("ma_alignment")
    if isinstance(alignment, dict):
        status = alignment.get("status", "neutral")
        return cfg.MA_ALIGNMENT_SCORES.get(status, cfg.MA_ALIGNMENT_DEFAULT)

    # Legacy fallback (old additive scoring, kept for safety)
    if not indicators.get("ma") or not kline:
        return cfg.MA_ALIGNMENT_DEFAULT
    return cfg.MA_ALIGNMENT_DEFAULT


def _score_kd(indicators: dict | None) -> int:
    """Score based on K value + golden/death cross detection.

    Base score from K's overbought/oversold zone, then ±10 for recent cross.
    """
    if not indicators or not indicators.get("kd"):
        return cfg.KD_DEFAULT

    k_vals = [v for v in indicators["kd"].get("k", []) if v is not None]
    d_vals = [v for v in indicators["kd"].get("d", []) if v is not None]
    if not k_vals or not d_vals:
        return cfg.KD_DEFAULT

    latest_k = k_vals[-1]
    base = _lookup_score(latest_k, cfg.KD_SCORES, cfg.KD_DEFAULT)

    # Cross detection (need at least 2 points)
    if len(k_vals) >= 2 and len(d_vals) >= 2:
        prev_k, prev_d = k_vals[-2], d_vals[-2]
        latest_d = d_vals[-1]
        # Golden cross: K was below D, now above D, happening in low zone
        if prev_k <= prev_d and latest_k > latest_d and latest_k < cfg.KD_CROSS_LOW_THRESHOLD:
            base += cfg.KD_GOLDEN_CROSS_BONUS
        # Death cross: K was above D, now below D, happening in high zone
        elif prev_k >= prev_d and latest_k < latest_d and latest_k > cfg.KD_CROSS_HIGH_THRESHOLD:
            base -= cfg.KD_DEATH_CROSS_PENALTY

    return _clamp(base)


def _score_obv(indicators: dict | None, kline: list[dict] | None) -> int:
    """Score based on OBV trend direction vs price direction (divergence detection)."""
    if not indicators or not indicators.get("obv") or not kline:
        return cfg.OBV_TREND_SCORES["neutral"]

    obv_vals = [v for v in indicators["obv"] if v is not None]
    if len(obv_vals) < cfg.OBV_LOOKBACK + 1:
        return cfg.OBV_TREND_SCORES["neutral"]

    closes = [k["close"] for k in kline]
    if len(closes) < cfg.OBV_LOOKBACK + 1:
        return cfg.OBV_TREND_SCORES["neutral"]

    obv_recent = obv_vals[-cfg.OBV_LOOKBACK - 1:]
    price_recent = closes[-cfg.OBV_LOOKBACK - 1:]

    obv_change = obv_recent[-1] - obv_recent[0]
    price_change = price_recent[-1] - price_recent[0]

    # Use small tolerance to avoid noise on near-zero moves
    obv_up = obv_change > 0
    obv_down = obv_change < 0
    price_up = price_change > 0
    price_down = price_change < 0

    if price_up and obv_up:
        return cfg.OBV_TREND_SCORES["rising"]
    if price_down and obv_down:
        return cfg.OBV_TREND_SCORES["falling"]
    if price_up and obv_down:
        return cfg.OBV_TREND_SCORES["divergence_bear"]
    if price_down and obv_up:
        return cfg.OBV_TREND_SCORES["divergence_bull"]
    return cfg.OBV_TREND_SCORES["neutral"]


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
