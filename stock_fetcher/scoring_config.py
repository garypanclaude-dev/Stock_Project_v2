"""
Composite Score — all thresholds, weights, and grade definitions.
Centralised here so tuning doesn't require touching business logic.
"""

# ── Dimension weights ─────────────────────────────────────────────────────────
DIMENSION_WEIGHTS = {
    "technical": 0.40,
    "fundamental": 0.35,
    "sentiment": 0.25,
}

# Used when sentiment is unavailable (AI failure)
FALLBACK_WEIGHTS = {
    "technical": 0.55,
    "fundamental": 0.45,
}

# ── Grade definitions ─────────────────────────────────────────────────────────
GRADES = [
    {"min": 81, "max": 100, "label": "強勢", "label_en": "Strong",  "color": "#16a34a"},
    {"min": 61, "max": 80,  "label": "偏多", "label_en": "Bullish", "color": "#22c55e"},
    {"min": 41, "max": 60,  "label": "中性", "label_en": "Neutral", "color": "#f59e0b"},
    {"min": 21, "max": 40,  "label": "偏空", "label_en": "Bearish", "color": "#ef4444"},
    {"min": 0,  "max": 20,  "label": "弱勢", "label_en": "Weak",    "color": "#dc2626"},
]

# ── Technical sub-indicator weights ───────────────────────────────────────────
# v2.0 (B7 integration): 4 → 6 sub-indicators, added KD + OBV.
# MA alignment upgraded to 4-state (bullish / bearish / tangled / neutral).
TECH_WEIGHTS = {
    "rsi":          0.15,
    "macd":         0.15,
    "ma_alignment": 0.20,
    "bollinger":    0.15,
    "kd":           0.20,
    "obv":          0.15,
}

# RSI score lookup: (upper_bound_exclusive, score)
RSI_SCORES = [
    (20,  85),
    (30,  75),
    (45,  60),
    (55,  50),
    (70,  65),
    (80,  40),
    (101, 25),  # > 80
]
RSI_DEFAULT = 50

# MACD conditions → scores
MACD_BULLISH_EXPANDING = 80
MACD_BULLISH_SHRINKING = 65
MACD_BEARISH_SHRINKING = 45
MACD_BEARISH_EXPANDING = 20
MACD_DEFAULT = 50

# MA alignment scoring moved to MA_ALIGNMENT_SCORES below (v2.0 — 4-state classification).
# Legacy additive MA_POINTS removed; see scoring._score_ma_alignment for new logic.

# Bollinger band position → score: (upper_bound_exclusive, score)
BB_SCORES = [
    (0.10, 70),
    (0.30, 55),
    (0.70, 65),
    (0.90, 50),
    (1.01, 30),  # > 90%
]
BB_DEFAULT = 50

# ── KD (Stochastic) scoring ───────────────────────────────────────────────────
# K value lookup: (upper_bound_exclusive, score)
KD_SCORES = [
    (20,  85),  # K < 20 oversold — strong rebound chance
    (30,  75),
    (50,  60),
    (70,  50),
    (80,  35),  # K > 70 elevated
    (101, 20),  # K > 80 severely overbought
]
KD_DEFAULT = 50
KD_GOLDEN_CROSS_BONUS = 10    # K crosses above D in last 2 bars (low region)
KD_DEATH_CROSS_PENALTY = 10   # K crosses below D in last 2 bars (high region)
KD_CROSS_LOW_THRESHOLD = 50   # only count golden cross as bullish if happening below this
KD_CROSS_HIGH_THRESHOLD = 50  # only count death cross as bearish if happening above this

# ── OBV trend scoring ─────────────────────────────────────────────────────────
# Compares OBV slope direction vs price slope direction over last N days.
OBV_LOOKBACK = 5
OBV_TREND_SCORES = {
    "rising":           75,  # price up + OBV up = healthy momentum
    "falling":          25,  # price down + OBV down = weak / distribution
    "divergence_bear":  30,  # price up + OBV down = bearish divergence (risk)
    "divergence_bull":  70,  # price down + OBV up = bullish divergence (accumulation)
    "neutral":          50,
}

# ── MA alignment (4-state) scoring ────────────────────────────────────────────
# Replaces the old additive MA_POINTS system with discrete state classification.
MA_ALIGNMENT_SCORES = {
    "bullish_alignment": 90,  # MA5>MA10>MA20>MA60 and price>MA5
    "bearish_alignment": 15,  # MA5<MA10<MA20<MA60 and price<MA5
    "tangled":           50,  # spread < 3% → variance signal
    "neutral":           50,  # crossed / partial alignment
}
MA_ALIGNMENT_DEFAULT = 50

# ── Fundamental sub-indicator weights ─────────────────────────────────────────
FUND_WEIGHTS = {
    "pe": 0.25,
    "roe": 0.20,
    "revenue_trend": 0.25,
    "profit_margin": 0.15,
    "dividend": 0.15,
}

# P/E score lookup: (upper_bound_exclusive, score)
PE_SCORES = [
    (0,   30),   # negative or None
    (10,  85),
    (15,  75),
    (25,  65),
    (35,  50),
    (50,  35),
    (9999, 20),  # > 50
]
PE_DEFAULT = 30

# ROE score lookup: (upper_bound_exclusive, score)
ROE_SCORES = [
    (0,   10),
    (5,   25),
    (10,  45),
    (15,  60),
    (25,  75),
    (9999, 90),  # > 25%
]
ROE_DEFAULT = 50

# Revenue trend scores
REVENUE_TREND = {
    "growth_3q": 90,
    "growth_2q": 75,
    "growth_1q": 60,
    "flat":      50,
    "decline_1q": 40,
    "decline_2q_plus": 20,
    "no_data":   50,
}

# Profit margin score lookup: (upper_bound_exclusive, score)
MARGIN_SCORES = [
    (0,   10),
    (5,   30),
    (10,  45),
    (20,  65),
    (30,  80),
    (9999, 90),  # > 30%
]
MARGIN_DEFAULT = 50

# Dividend yield score lookup: (upper_bound_exclusive, score)
DIVIDEND_SCORES = [
    (0.5, 40),
    (2.0, 55),
    (4.0, 70),
    (9999, 85),  # > 4%
]
DIVIDEND_DEFAULT = 50

# ── Sentiment sub-indicator weights ───────────────────────────────────────────
SENT_WEIGHTS = {
    "bull_bear_ratio": 0.60,
    "catalyst_count": 0.20,
    "catalyst_impact": 0.20,
}

# Catalyst count → score
CATALYST_COUNT_SCORES = {
    0: 50,
    1: 60,
    2: 60,
    3: 70,
    4: 70,
    5: 70,
}
CATALYST_COUNT_DEFAULT = 65  # > 5

# Catalyst type impact weights (higher = more market-moving)
CATALYST_IMPACT = {
    "earnings":       1.0,
    "regulation":     0.9,
    "m_and_a":        0.85,
    "analyst_rating": 0.8,
    "management":     0.7,
    "litigation":     0.7,
    "product_launch": 0.6,
    "macro":          0.5,
}
CATALYST_IMPACT_DEFAULT = 0.5
