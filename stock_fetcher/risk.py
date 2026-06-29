"""
DEPRECATED (2026-06-29): Risk metrics feature has been removed from /api/stock-insights and the frontend.
This module is retained for historical reference and possible future revival; it is no longer imported by the live app.

Risk metrics — Historical Volatility, Max Drawdown, ATR, and stop-loss/take-profit suggestions.

All functions are pure: they read kline lists and return dicts. No I/O, no external calls.
Thresholds and parameters live in `risk_config.py`.
"""
from __future__ import annotations

import math

from .risk_config import (
    ATR_PERIOD,
    ATR_PROFILES,
    FIXED_PCT,
    HV_LEVELS,
    HV_MIN_SAMPLES,
    HV_UNKNOWN,
    HV_WINDOWS,
    SWING_LOOKBACK,
    TRADING_DAYS_PER_YEAR,
    WARN_BEARISH_PATTERN_LOOKBACK,
    WARN_KD_DEATH_CROSS_THRESHOLD,
    WARN_OBV_DIVERGENCE_LOOKBACK,
    WARNING_TEMPLATES,
)


# ── Historical Volatility ─────────────────────────────────────────────────────

def historical_volatility(closes: list[float], window: int) -> float | None:
    """Annualised HV (%) using log returns over the most recent `window` days.

    Returns None when there are fewer than `window` returns available, or when
    the sample size falls below HV_MIN_SAMPLES.
    """
    if window < HV_MIN_SAMPLES or len(closes) < window + 1:
        return None

    recent = closes[-(window + 1):]
    log_returns: list[float] = []
    for i in range(1, len(recent)):
        prev, curr = recent[i - 1], recent[i]
        if prev > 0 and curr > 0:
            log_returns.append(math.log(curr / prev))

    if len(log_returns) < HV_MIN_SAMPLES:
        return None

    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
    daily_std = math.sqrt(variance)
    annualised = daily_std * math.sqrt(TRADING_DAYS_PER_YEAR) * 100
    return round(annualised, 2)


def classify_hv(hv: float | None) -> dict:
    """Map annualised HV value to {key, label, color}."""
    if hv is None:
        return dict(HV_UNKNOWN)
    for upper, key, label, color in HV_LEVELS:
        if hv < upper:
            return {"key": key, "label": label, "color": color}
    return {"key": "extreme", "label": "極高波動", "color": "#ef4444"}


# ── Maximum Drawdown ──────────────────────────────────────────────────────────

def max_drawdown(kline: list[dict]) -> dict:
    """Find the largest peak-to-trough drop over the kline range.

    Returns a dict including peak/trough dates and recovery information.
    """
    if not kline or len(kline) < 2:
        return _empty_drawdown()

    closes = [k["close"] for k in kline]
    dates = [k["date"] for k in kline]

    running_peak = closes[0]
    running_peak_idx = 0
    mdd_pct = 0.0
    mdd_peak_idx = 0
    mdd_trough_idx = 0

    for i, price in enumerate(closes):
        if price > running_peak:
            running_peak = price
            running_peak_idx = i
        dd = (price - running_peak) / running_peak
        if dd < mdd_pct:
            mdd_pct = dd
            mdd_peak_idx = running_peak_idx
            mdd_trough_idx = i

    peak_price = closes[mdd_peak_idx]
    trough_price = closes[mdd_trough_idx]

    recovered = False
    recovery_days: int | None = None
    for i in range(mdd_trough_idx + 1, len(closes)):
        if closes[i] >= peak_price:
            recovered = True
            recovery_days = i - mdd_trough_idx
            break

    # 目前距離全期最高點的回撤
    all_time_high = max(closes)
    current_dd_pct = (closes[-1] - all_time_high) / all_time_high * 100

    return {
        "mdd_pct": round(mdd_pct * 100, 2),
        "peak_date": dates[mdd_peak_idx],
        "trough_date": dates[mdd_trough_idx],
        "peak_price": round(peak_price, 2),
        "trough_price": round(trough_price, 2),
        "recovered": recovered,
        "recovery_days": recovery_days,
        "current_drawdown_pct": round(current_dd_pct, 2),
    }


def _empty_drawdown() -> dict:
    return {
        "mdd_pct": None,
        "peak_date": None,
        "trough_date": None,
        "peak_price": None,
        "trough_price": None,
        "recovered": None,
        "recovery_days": None,
        "current_drawdown_pct": None,
    }


# ── ATR (Average True Range) ──────────────────────────────────────────────────

def average_true_range(kline: list[dict], period: int = ATR_PERIOD) -> float | None:
    """Wilder-smoothed ATR over `period` days."""
    if len(kline) < period + 1:
        return None

    true_ranges: list[float] = []
    for i in range(1, len(kline)):
        high = kline[i]["high"]
        low = kline[i]["low"]
        prev_close = kline[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    atr = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + tr) / period
    return round(atr, 4)


# ── Stop-loss / Take-profit methods ───────────────────────────────────────────

def _build_rr(current: float, stop: float, target: float, label: str) -> dict:
    """Compute risk/reward metadata for a (stop, target) pair."""
    if current <= 0:
        return _empty_method(label)
    risk_amount = current - stop
    reward_amount = target - current
    rr_ratio = (reward_amount / risk_amount) if risk_amount > 0 else None
    return {
        "label": label,
        "stop_loss": round(stop, 2),
        "take_profit": round(target, 2),
        "risk_pct": round((stop / current - 1) * 100, 2),
        "reward_pct": round((target / current - 1) * 100, 2),
        "rr_ratio": round(rr_ratio, 2) if rr_ratio else None,
    }


def _empty_method(label: str) -> dict:
    return {
        "label": label,
        "stop_loss": None,
        "take_profit": None,
        "risk_pct": None,
        "reward_pct": None,
        "rr_ratio": None,
    }


def method_atr(current: float, atr: float | None, profile: str = "standard") -> dict:
    """ATR-based stop/target."""
    cfg = ATR_PROFILES.get(profile, ATR_PROFILES["standard"])
    name = f"ATR ({cfg['label']})"
    if atr is None or atr <= 0 or current <= 0:
        return _empty_method(name)
    stop = current - cfg["stop_mult"] * atr
    target = current + cfg["target_mult"] * atr
    return _build_rr(current, stop, target, name)


def method_fixed_pct(current: float) -> dict:
    name = "固定百分比"
    if current <= 0:
        return _empty_method(name)
    stop = current * (1 - FIXED_PCT["stop_pct"])
    target = current * (1 + FIXED_PCT["target_pct"])
    return _build_rr(current, stop, target, name)


def method_bollinger(current: float, bb_upper: float | None, bb_lower: float | None) -> dict:
    name = "布林通道"
    if bb_upper is None or bb_lower is None or current <= 0:
        return _empty_method(name)
    # 已突破上軌時，停利改為「目前價 + (上軌 - 下軌)」維持 R:R 意義
    stop = bb_lower
    target = bb_upper if bb_upper > current else current + (bb_upper - bb_lower)
    return _build_rr(current, stop, target, name)


def method_swing(current: float, kline: list[dict], lookback: int = SWING_LOOKBACK) -> dict:
    name = "波段支撐壓力"
    if not kline or current <= 0:
        return _empty_method(name)
    recent = kline[-lookback:] if len(kline) >= lookback else kline
    swing_low = min(k["low"] for k in recent)
    swing_high = max(k["high"] for k in recent)
    if swing_low >= current or swing_high <= current:
        # 當前價已超出區間，仍提供數字但風報比可能無意義
        return _build_rr(current, swing_low, swing_high, name)
    return _build_rr(current, swing_low, swing_high, name)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _latest_non_null(seq) -> float | None:
    if not seq:
        return None
    for v in reversed(seq):
        if v is not None:
            return v
    return None


# ── Warning signals (technical risk alerts) ───────────────────────────────────

def compute_risk_warnings(
    kline: list[dict],
    indicators: dict | None,
    patterns: list[dict] | None = None,
) -> list[dict]:
    """Detect technical risk warnings from B7 / B8 signals.

    Returns a list of warning dicts, each with keys:
      type, severity, label, description, color

    Empty list = no warnings detected. These do not affect numeric risk metrics.
    """
    warnings: list[dict] = []
    if not kline:
        return warnings
    if not indicators and not patterns:
        return warnings
    indicators = indicators or {}

    # 1. KD high-zone death cross
    kd = indicators.get("kd")
    if isinstance(kd, dict):
        k_vals = [v for v in kd.get("k", []) if v is not None]
        d_vals = [v for v in kd.get("d", []) if v is not None]
        if len(k_vals) >= 2 and len(d_vals) >= 2:
            prev_k, latest_k = k_vals[-2], k_vals[-1]
            prev_d, latest_d = d_vals[-2], d_vals[-1]
            # death cross: K was above D, now below D, occurring in high zone
            if (prev_k >= prev_d and latest_k < latest_d
                    and latest_k > WARN_KD_DEATH_CROSS_THRESHOLD):
                warnings.append(dict(WARNING_TEMPLATES["kd_death_cross"]))

    # 2. OBV bearish divergence (price up + OBV down over lookback window)
    obv_vals = [v for v in (indicators.get("obv") or []) if v is not None]
    closes = [k["close"] for k in kline]
    n = WARN_OBV_DIVERGENCE_LOOKBACK
    if len(obv_vals) > n and len(closes) > n:
        obv_change = obv_vals[-1] - obv_vals[-(n + 1)]
        price_change = closes[-1] - closes[-(n + 1)]
        if price_change > 0 and obv_change < 0:
            warnings.append(dict(WARNING_TEMPLATES["obv_bearish_divergence"]))

    # 3. MA bearish alignment
    ma_align = indicators.get("ma_alignment")
    if isinstance(ma_align, dict) and ma_align.get("status") == "bearish_alignment":
        warnings.append(dict(WARNING_TEMPLATES["ma_bearish_alignment"]))

    # 4. Bearish candlestick pattern in recent N bars (B8)
    if patterns:
        n = len(kline)
        cutoff_index = n - WARN_BEARISH_PATTERN_LOOKBACK
        bearish_recent = [
            p for p in patterns
            if p.get("direction") == "bearish" and p.get("index", -1) >= cutoff_index
        ]
        if bearish_recent:
            tmpl = dict(WARNING_TEMPLATES["bearish_pattern"])
            # Enrich with the actual pattern labels for context
            labels = ", ".join(sorted({p["label"] for p in bearish_recent}))
            tmpl["description"] = f"近 {WARN_BEARISH_PATTERN_LOOKBACK} 日出現{labels}，需留意回檔風險。"
            warnings.append(tmpl)

    return warnings


# ── Main entry ────────────────────────────────────────────────────────────────

def compute_risk_metrics(
    kline: list[dict],
    indicators: dict | None = None,
    patterns: list[dict] | None = None,
) -> dict:
    """Compute the full risk-metrics payload for the given kline.

    Parameters
    ----------
    kline : list of {date, open, high, low, close, volume}
    indicators : optional dict from `indicators.compute_all()` — used to reuse
                 Bollinger band values for the BB stop-loss method.
    """
    if not kline or len(kline) < 2:
        return _empty_payload()

    closes = [k["close"] for k in kline]
    current = closes[-1]

    # Historical Volatility
    hv_values = {f"hv_{w}d": historical_volatility(closes, w) for w in HV_WINDOWS}
    primary_hv = hv_values.get("hv_20d") or hv_values.get("hv_60d")
    level = classify_hv(primary_hv)

    # Drawdown
    drawdown = max_drawdown(kline)

    # ATR
    atr = average_true_range(kline)

    # Bollinger latest values from indicators (if available)
    bb_upper = bb_lower = None
    if indicators and isinstance(indicators.get("bollinger"), dict):
        bb_upper = _latest_non_null(indicators["bollinger"].get("upper"))
        bb_lower = _latest_non_null(indicators["bollinger"].get("lower"))

    # Four-method stop-loss / take-profit
    methods = {
        "atr_standard":     method_atr(current, atr, "standard"),
        "atr_conservative": method_atr(current, atr, "conservative"),
        "atr_aggressive":   method_atr(current, atr, "aggressive"),
        "fixed_pct":        method_fixed_pct(current),
        "bollinger":        method_bollinger(current, bb_upper, bb_lower),
        "swing":            method_swing(current, kline),
    }

    return {
        "volatility": {
            **hv_values,
            "level": level,
        },
        "drawdown": drawdown,
        "suggestions": {
            "current_price": round(current, 2),
            "atr_14": atr,
            "methods": methods,
        },
        "warnings": compute_risk_warnings(kline, indicators, patterns),
    }


def _empty_payload() -> dict:
    return {
        "volatility": {f"hv_{w}d": None for w in HV_WINDOWS} | {"level": dict(HV_UNKNOWN)},
        "drawdown": _empty_drawdown(),
        "suggestions": {"current_price": None, "atr_14": None, "methods": {}},
        "warnings": [],
    }
