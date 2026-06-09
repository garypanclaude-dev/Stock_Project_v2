"""
Candlestick pattern detection — pure functions over kline lists.

Each kline dict needs keys: date, open, high, low, close (volume optional).
All thresholds live in `patterns_config.py`.

Returns from `detect_patterns()` are list[dict] with:
    {index, date, type, direction, label, description, color}
"""
from __future__ import annotations

from .patterns_config import (
    DEFAULT_LOOKBACK,
    DIRECTION_COLORS,
    DOJI_BODY_RATIO,
    ENGULFING_BODY_MIN_RATIO,
    ENGULFING_RELATIVE_SIZE,
    HAMMER_BODY_MAX_RATIO,
    HAMMER_OPPOSITE_SHADOW_MAX,
    HAMMER_SHADOW_MIN_RATIO,
    PATTERN_DESCRIPTIONS,
    PATTERN_DIRECTION,
    PATTERN_LABELS,
    STAR_LONG_BODY_MIN_RATIO,
    STAR_MIDDLE_BODY_MAX_RATIO,
    STAR_RECOVERY_RATIO,
    TREND_MIN_CHANGE,
    TREND_WINDOW,
)


# ── Bar geometry helpers ──────────────────────────────────────────────────────

def _body(k: dict) -> float:
    return abs(k["close"] - k["open"])


def _total_range(k: dict) -> float:
    return max(k["high"] - k["low"], 1e-9)  # guard div-by-zero


def _upper_shadow(k: dict) -> float:
    return k["high"] - max(k["open"], k["close"])


def _lower_shadow(k: dict) -> float:
    return min(k["open"], k["close"]) - k["low"]


def _is_bullish_bar(k: dict) -> bool:
    return k["close"] > k["open"]


def _is_bearish_bar(k: dict) -> bool:
    return k["close"] < k["open"]


def _body_ratio(k: dict) -> float:
    return _body(k) / _total_range(k)


# ── Trend context (cheap proxy: net change over last N bars) ──────────────────

def _is_downtrend(klines: list[dict], idx: int) -> bool:
    """True if the N bars before idx show net decline."""
    if idx < TREND_WINDOW:
        return False
    window_start = klines[idx - TREND_WINDOW]["close"]
    window_end = klines[idx - 1]["close"]
    if window_start <= 0:
        return False
    return (window_end - window_start) / window_start < -TREND_MIN_CHANGE


def _is_uptrend(klines: list[dict], idx: int) -> bool:
    if idx < TREND_WINDOW:
        return False
    window_start = klines[idx - TREND_WINDOW]["close"]
    window_end = klines[idx - 1]["close"]
    if window_start <= 0:
        return False
    return (window_end - window_start) / window_start > TREND_MIN_CHANGE


# ── Single-bar patterns ───────────────────────────────────────────────────────

def _is_doji(k: dict) -> bool:
    return _body_ratio(k) < DOJI_BODY_RATIO


def _is_hammer(k: dict, klines: list[dict], idx: int) -> bool:
    """Hammer: small body at top, long lower shadow, occurring in downtrend."""
    if not _is_downtrend(klines, idx):
        return False
    body = _body(k)
    if body == 0:
        return False
    if _body_ratio(k) > HAMMER_BODY_MAX_RATIO:
        return False
    if _lower_shadow(k) < HAMMER_SHADOW_MIN_RATIO * body:
        return False
    if _upper_shadow(k) > HAMMER_OPPOSITE_SHADOW_MAX * body:
        return False
    return True


def _is_shooting_star(k: dict, klines: list[dict], idx: int) -> bool:
    """Shooting star: small body at bottom, long upper shadow, in uptrend."""
    if not _is_uptrend(klines, idx):
        return False
    body = _body(k)
    if body == 0:
        return False
    if _body_ratio(k) > HAMMER_BODY_MAX_RATIO:
        return False
    if _upper_shadow(k) < HAMMER_SHADOW_MIN_RATIO * body:
        return False
    if _lower_shadow(k) > HAMMER_OPPOSITE_SHADOW_MAX * body:
        return False
    return True


# ── Two-bar patterns ──────────────────────────────────────────────────────────

def _is_bullish_engulfing(prev: dict, curr: dict) -> bool:
    if not _is_bearish_bar(prev):
        return False
    if not _is_bullish_bar(curr):
        return False
    if _body_ratio(prev) < ENGULFING_BODY_MIN_RATIO:
        return False
    if _body_ratio(curr) < ENGULFING_BODY_MIN_RATIO:
        return False
    # Body containment: today's body engulfs yesterday's body
    if curr["open"] > prev["close"]:
        return False
    if curr["close"] < prev["open"]:
        return False
    if _body(curr) < _body(prev) * ENGULFING_RELATIVE_SIZE:
        return False
    return True


def _is_bearish_engulfing(prev: dict, curr: dict) -> bool:
    if not _is_bullish_bar(prev):
        return False
    if not _is_bearish_bar(curr):
        return False
    if _body_ratio(prev) < ENGULFING_BODY_MIN_RATIO:
        return False
    if _body_ratio(curr) < ENGULFING_BODY_MIN_RATIO:
        return False
    if curr["open"] < prev["close"]:
        return False
    if curr["close"] > prev["open"]:
        return False
    if _body(curr) < _body(prev) * ENGULFING_RELATIVE_SIZE:
        return False
    return True


# ── Three-bar patterns ────────────────────────────────────────────────────────

def _is_morning_star(b1: dict, b2: dict, b3: dict) -> bool:
    """Long bearish → small body → long bullish reversal."""
    if not _is_bearish_bar(b1) or _body_ratio(b1) < STAR_LONG_BODY_MIN_RATIO:
        return False
    if _body_ratio(b2) > STAR_MIDDLE_BODY_MAX_RATIO:
        return False
    if not _is_bullish_bar(b3) or _body_ratio(b3) < STAR_LONG_BODY_MIN_RATIO:
        return False
    # Recovery: bar 3 closes past midpoint of bar 1
    b1_mid = (b1["open"] + b1["close"]) / 2
    if b3["close"] < b1_mid - (b1_mid - b1["close"]) * (1 - STAR_RECOVERY_RATIO):
        return False
    return True


def _is_evening_star(b1: dict, b2: dict, b3: dict) -> bool:
    """Long bullish → small body → long bearish reversal."""
    if not _is_bullish_bar(b1) or _body_ratio(b1) < STAR_LONG_BODY_MIN_RATIO:
        return False
    if _body_ratio(b2) > STAR_MIDDLE_BODY_MAX_RATIO:
        return False
    if not _is_bearish_bar(b3) or _body_ratio(b3) < STAR_LONG_BODY_MIN_RATIO:
        return False
    b1_mid = (b1["open"] + b1["close"]) / 2
    if b3["close"] > b1_mid + (b1["close"] - b1_mid) * (1 - STAR_RECOVERY_RATIO):
        return False
    return True


# ── Public API ────────────────────────────────────────────────────────────────

def detect_patterns(
    klines: list[dict],
    lookback: int = DEFAULT_LOOKBACK,
) -> list[dict]:
    """Scan the last `lookback` bars and return detected patterns.

    Returns a list sorted oldest → newest. Each entry has:
        index, date, type, direction, label, description, color
    """
    if not klines:
        return []

    # Require OHLC keys on every bar
    required = ("open", "high", "low", "close", "date")
    valid_klines = [
        k for k in klines
        if all(k.get(key) is not None for key in required)
    ]
    if len(valid_klines) < 3:
        return []

    n = len(valid_klines)
    start = max(0, n - lookback)
    results: list[dict] = []

    for i in range(start, n):
        k = valid_klines[i]
        detected: list[str] = []

        # Single-bar
        if _is_hammer(k, valid_klines, i):
            detected.append("hammer")
        elif _is_shooting_star(k, valid_klines, i):
            detected.append("shooting_star")
        elif _is_doji(k):
            detected.append("doji")

        # Two-bar (need previous bar)
        if i >= 1:
            prev = valid_klines[i - 1]
            if _is_bullish_engulfing(prev, k):
                detected.append("bullish_engulfing")
            elif _is_bearish_engulfing(prev, k):
                detected.append("bearish_engulfing")

        # Three-bar (need two previous bars)
        if i >= 2:
            b1 = valid_klines[i - 2]
            b2 = valid_klines[i - 1]
            if _is_morning_star(b1, b2, k):
                detected.append("morning_star")
            elif _is_evening_star(b1, b2, k):
                detected.append("evening_star")

        for ptype in detected:
            direction = PATTERN_DIRECTION[ptype]
            results.append({
                "index": i,
                "date": k["date"],
                "type": ptype,
                "direction": direction,
                "label": PATTERN_LABELS[ptype],
                "description": PATTERN_DESCRIPTIONS[ptype],
                "color": DIRECTION_COLORS[direction],
            })

    return results


def summarize_patterns(patterns: list[dict]) -> dict:
    """Aggregate counts by direction for quick downstream use."""
    counts = {"bullish": 0, "bearish": 0, "neutral": 0}
    for p in patterns:
        counts[p["direction"]] = counts.get(p["direction"], 0) + 1
    counts["total"] = sum(counts.values())
    return counts
