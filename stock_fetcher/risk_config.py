"""
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
