"""
DEPRECATED (2026-06-29): Companion config for `risk.py`. No longer referenced by the live app.

Risk metrics configuration — thresholds, multipliers, level definitions.
Centralised to avoid hard-coding values in calculation logic.
"""

# ── Historical Volatility ─────────────────────────────────────────────────────
HV_WINDOWS = (20, 60)                  # 短期、中期
TRADING_DAYS_PER_YEAR = 252            # 年化縮放因子
HV_MIN_SAMPLES = 20                    # 統計穩健性下限：少於 20 樣本回 None

# Annualised HV (%) → level: (upper_bound_exclusive, key, label, color)
HV_LEVELS = [
    (20.0,   "low",     "低波動",     "#22c55e"),
    (40.0,   "medium",  "中波動",     "#f59e0b"),
    (60.0,   "high",    "高波動",     "#f97316"),
    (9999.0, "extreme", "極高波動",   "#ef4444"),
]
HV_UNKNOWN = {"key": "unknown", "label": "資料不足", "color": "#64748b"}

# ── Maximum Drawdown ──────────────────────────────────────────────────────────
MDD_WARNING_THRESHOLD = -30.0          # 超過視為警示（負值）

# ── ATR (Average True Range) ──────────────────────────────────────────────────
ATR_PERIOD = 14

# ── Stop-loss / Take-profit ───────────────────────────────────────────────────
# Method 1: ATR multipliers (three risk profiles)
ATR_PROFILES = {
    "conservative": {"stop_mult": 2.0, "target_mult": 3.0, "label": "保守"},
    "standard":     {"stop_mult": 2.5, "target_mult": 5.0, "label": "標準"},
    "aggressive":   {"stop_mult": 3.0, "target_mult": 6.0, "label": "積極"},
}

# Method 2: Fixed percentage
FIXED_PCT = {"stop_pct": 0.08, "target_pct": 0.15}

# Method 3: Bollinger Band — uses BB upper/lower directly (no config)

# Method 4: Swing high/low lookback (trading days)
SWING_LOOKBACK = 60

# ── Warning signals (v1.1: technical risk alerts from B7 indicators) ──────────
# These are non-numeric warnings shown alongside HV/MDD — they don't affect
# the risk numbers themselves, just flag noteworthy technical signals.

# KD death cross detection — when K crosses below D in the overbought zone.
WARN_KD_DEATH_CROSS_THRESHOLD = 70   # only trigger when K > this when crossing

# OBV bearish divergence — price up + OBV down over OBV_DIVERGENCE_LOOKBACK days.
WARN_OBV_DIVERGENCE_LOOKBACK = 10

# MA bearish alignment also triggers a warning.

# Pre-built warning templates (rendered into the warnings list)
WARNING_TEMPLATES = {
    "kd_death_cross": {
        "type": "kd_death_cross",
        "severity": "warn",
        "label": "KD 高檔死亡交叉",
        "description": "K 線在高檔（>70）由上向下穿越 D 線，短期回調機率提高。",
        "color": "#f97316",
    },
    "obv_bearish_divergence": {
        "type": "obv_bearish_divergence",
        "severity": "warn",
        "label": "OBV 看空背離",
        "description": "近期股價走高但 OBV 走低，量價未同步，上漲動能可能轉弱。",
        "color": "#f97316",
    },
    "ma_bearish_alignment": {
        "type": "ma_bearish_alignment",
        "severity": "danger",
        "label": "均線空頭排列",
        "description": "MA5 < MA10 < MA20 < MA60 且股價跌破 MA5，趨勢已轉空。",
        "color": "#ef4444",
    },
    "bearish_pattern": {
        "type": "bearish_pattern",
        "severity": "warn",
        "label": "近期看空反轉型態",
        "description": "近 5 日 K 線出現看空反轉型態（流星 / 夜星 / 看空吞噬），需留意回檔風險。",
        "color": "#f97316",
    },
}

# Bearish pattern detection window for risk warning
WARN_BEARISH_PATTERN_LOOKBACK = 5
