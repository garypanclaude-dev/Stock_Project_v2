"""
Candlestick pattern detection configuration.

All thresholds for body/shadow ratios, trend context windows, and label/
description text live here to avoid hard-coding in detection logic.
"""

# ── Body / shadow ratio thresholds ────────────────────────────────────────────
DOJI_BODY_RATIO = 0.10          # body < 10% of high-low range → doji

# Hammer / shooting star
HAMMER_BODY_MAX_RATIO = 0.35    # body must be at most 35% of total range
HAMMER_SHADOW_MIN_RATIO = 2.0   # long shadow ≥ 2 × body
HAMMER_OPPOSITE_SHADOW_MAX = 0.5  # opposite shadow ≤ 0.5 × body

# Engulfing
ENGULFING_BODY_MIN_RATIO = 0.20  # bars in pattern must have body ≥ 20% of range
ENGULFING_RELATIVE_SIZE = 1.0    # today body ≥ yesterday body × this multiplier

# Morning / evening star
STAR_LONG_BODY_MIN_RATIO = 0.50  # outer bars must have body ≥ 50% of range
STAR_MIDDLE_BODY_MAX_RATIO = 0.30  # middle bar body ≤ 30% of range
STAR_RECOVERY_RATIO = 0.50       # bar 3 must close past midpoint of bar 1

# ── Trend context window ─────────────────────────────────────────────────────
TREND_WINDOW = 3                # check last N bars for trend bias
TREND_MIN_CHANGE = 0.01         # require ≥ 1% directional move

# ── Detection scan window ────────────────────────────────────────────────────
DEFAULT_LOOKBACK = 10           # how many recent bars to scan

# ── Pattern metadata (rendered into result dicts) ────────────────────────────
PATTERN_DIRECTION = {
    "doji":               "neutral",
    "hammer":             "bullish",
    "shooting_star":      "bearish",
    "bullish_engulfing":  "bullish",
    "bearish_engulfing":  "bearish",
    "morning_star":       "bullish",
    "evening_star":       "bearish",
}

PATTERN_LABELS = {
    "doji":               "十字線",
    "hammer":             "錘子線",
    "shooting_star":      "流星線",
    "bullish_engulfing":  "看多吞噬",
    "bearish_engulfing":  "看空吞噬",
    "morning_star":       "晨星",
    "evening_star":       "夜星",
}

PATTERN_DESCRIPTIONS = {
    "doji":               "開收盤接近，多空僵持。出現在趨勢末端常為變盤訊號。",
    "hammer":             "下影線長、實體小，下跌段尾出現代表低檔反彈動能。",
    "shooting_star":      "上影線長、實體小，上漲段尾出現代表高檔遇壓回測。",
    "bullish_engulfing":  "陽線完全包覆前日陰線，買盤強勢翻多。",
    "bearish_engulfing":  "陰線完全包覆前日陽線，賣壓強勢翻空。",
    "morning_star":       "三日反轉：長陰 → 小實體 → 長陽，下跌動能耗盡。",
    "evening_star":       "三日反轉：長陽 → 小實體 → 長陰，上漲動能耗盡。",
}

# ── Color mapping by direction ───────────────────────────────────────────────
DIRECTION_COLORS = {
    "bullish": "#22c55e",
    "bearish": "#ef4444",
    "neutral": "#94a3b8",
}
