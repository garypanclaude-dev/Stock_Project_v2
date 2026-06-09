"""Technical indicator calculations — pure functions over price lists."""
from __future__ import annotations


def moving_averages(closes: list[float], windows: tuple[int, ...] = (5, 10, 20, 60)) -> dict[str, list[float | None]]:
    result: dict[str, list[float | None]] = {}
    for w in windows:
        ma: list[float | None] = []
        for i in range(len(closes)):
            if i < w - 1:
                ma.append(None)
            else:
                ma.append(round(sum(closes[i - w + 1 : i + 1]) / w, 2))
        result[f"ma{w}"] = ma
    return result


def rsi(closes: list[float], period: int = 14) -> list[float | None]:
    if len(closes) < 2:
        return [None] * len(closes)

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    out: list[float | None] = [None] * period

    gains = [max(d, 0) for d in deltas[:period]]
    losses = [abs(min(d, 0)) for d in deltas[:period]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        out.append(100.0)
    else:
        rs = avg_gain / avg_loss
        out.append(round(100 - 100 / (1 + rs), 2))

    for i in range(period, len(deltas)):
        d = deltas[i]
        avg_gain = (avg_gain * (period - 1) + max(d, 0)) / period
        avg_loss = (avg_loss * (period - 1) + abs(min(d, 0))) / period
        if avg_loss == 0:
            out.append(100.0)
        else:
            rs = avg_gain / avg_loss
            out.append(round(100 - 100 / (1 + rs), 2))

    return out


def macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> dict[str, list[float | None]]:
    def ema(data: list[float], span: int) -> list[float]:
        k = 2 / (span + 1)
        result = [data[0]]
        for v in data[1:]:
            result.append(v * k + result[-1] * (1 - k))
        return result

    if len(closes) < slow:
        n = len(closes)
        return {"macd": [None] * n, "signal": [None] * n, "histogram": [None] * n}

    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = [round(f - s, 4) for f, s in zip(ema_fast, ema_slow)]

    valid_macd = macd_line[slow - 1 :]
    if len(valid_macd) < signal_period:
        n = len(closes)
        return {"macd": [None] * n, "signal": [None] * n, "histogram": [None] * n}

    signal_line_raw = ema(valid_macd, signal_period)

    macd_out: list[float | None] = [None] * (slow - 1) + [round(v, 2) for v in valid_macd]
    signal_out: list[float | None] = [None] * (slow - 1 + signal_period - 1) + [
        round(v, 2) for v in signal_line_raw[signal_period - 1 :]
    ]
    histogram: list[float | None] = []
    for m, s in zip(macd_out, signal_out):
        if m is not None and s is not None:
            histogram.append(round(m - s, 2))
        else:
            histogram.append(None)

    return {"macd": macd_out, "signal": signal_out, "histogram": histogram}


def bollinger_bands(
    closes: list[float], period: int = 20, num_std: float = 2.0
) -> dict[str, list[float | None]]:
    upper: list[float | None] = []
    middle: list[float | None] = []
    lower: list[float | None] = []

    for i in range(len(closes)):
        if i < period - 1:
            upper.append(None)
            middle.append(None)
            lower.append(None)
        else:
            window = closes[i - period + 1 : i + 1]
            mean = sum(window) / period
            variance = sum((x - mean) ** 2 for x in window) / period
            std = variance ** 0.5
            middle.append(round(mean, 2))
            upper.append(round(mean + num_std * std, 2))
            lower.append(round(mean - num_std * std, 2))

    return {"upper": upper, "middle": middle, "lower": lower}


def stochastic_kd(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 9,
    k_smooth: int = 3,
    d_smooth: int = 3,
) -> dict[str, list[float | None]]:
    """KD (Stochastic Oscillator) — Taiwan retail variant.

    Formula:
        RSV_n = (C - L_n) / (H_n - L_n) × 100
        K_t   = (k_smooth-1)/k_smooth × K_{t-1} + 1/k_smooth × RSV_t
        D_t   = (d_smooth-1)/d_smooth × D_{t-1} + 1/d_smooth × K_t

    Returns {"k": [...], "d": [...]} aligned with input length.
    """
    n = len(closes)
    if n < period or len(highs) != n or len(lows) != n:
        return {"k": [None] * n, "d": [None] * n}

    rsv: list[float | None] = [None] * n
    for i in range(period - 1, n):
        window_h = max(highs[i - period + 1 : i + 1])
        window_l = min(lows[i - period + 1 : i + 1])
        if window_h == window_l:
            rsv[i] = 50.0  # avoid div-by-zero on flat window
        else:
            rsv[i] = (closes[i] - window_l) / (window_h - window_l) * 100

    k_out: list[float | None] = [None] * n
    d_out: list[float | None] = [None] * n

    # Initial K/D = 50 at first valid RSV index
    prev_k = 50.0
    prev_d = 50.0
    k_alpha = 1 / k_smooth
    d_alpha = 1 / d_smooth

    for i in range(period - 1, n):
        if rsv[i] is None:
            continue
        k_t = (1 - k_alpha) * prev_k + k_alpha * rsv[i]
        d_t = (1 - d_alpha) * prev_d + d_alpha * k_t
        k_out[i] = round(k_t, 2)
        d_out[i] = round(d_t, 2)
        prev_k, prev_d = k_t, d_t

    return {"k": k_out, "d": d_out}


def obv(closes: list[float], volumes: list[int]) -> list[float | None]:
    """On-Balance Volume: cumulative volume signed by price direction.

        OBV_0 = 0
        OBV_i = OBV_{i-1} + volume_i   if close_i > close_{i-1}
              = OBV_{i-1} - volume_i   if close_i < close_{i-1}
              = OBV_{i-1}              if close_i == close_{i-1}
    """
    n = len(closes)
    if n == 0 or len(volumes) != n:
        return [None] * n

    out: list[float | None] = [0.0]
    for i in range(1, n):
        prev_obv = out[-1] or 0.0
        if closes[i] > closes[i - 1]:
            out.append(prev_obv + volumes[i])
        elif closes[i] < closes[i - 1]:
            out.append(prev_obv - volumes[i])
        else:
            out.append(prev_obv)
    return out


def ma_alignment_status(
    closes: list[float],
    mas: dict[str, list[float | None]],
    tangled_threshold: float = 0.03,
) -> dict:
    """Classify MA alignment into 4 mutually-exclusive states.

    Priority order: tangled > bullish > bearish > neutral
    """
    if not closes:
        return {"status": "neutral", "label": "資料不足", "color": "#94a3b8"}

    def _last_valid(key: str) -> float | None:
        vals = mas.get(key) or []
        for v in reversed(vals):
            if v is not None:
                return v
        return None

    price = closes[-1]
    ma5 = _last_valid("ma5")
    ma10 = _last_valid("ma10")
    ma20 = _last_valid("ma20")
    ma60 = _last_valid("ma60")

    if None in (ma5, ma10, ma20, ma60):
        return {"status": "neutral", "label": "資料不足", "color": "#94a3b8"}

    ma_values = [ma5, ma10, ma20, ma60]
    mean = sum(ma_values) / 4
    spread = (max(ma_values) - min(ma_values)) / mean if mean else 1.0

    # 1. Tangled (highest priority — variance dominates direction)
    if spread < tangled_threshold:
        return {"status": "tangled", "label": "均線糾結", "color": "#eab308"}

    # 2. Bullish alignment
    if price > ma5 > ma10 > ma20 > ma60:
        return {"status": "bullish_alignment", "label": "多頭排列", "color": "#22c55e"}

    # 3. Bearish alignment
    if price < ma5 < ma10 < ma20 < ma60:
        return {"status": "bearish_alignment", "label": "空頭排列", "color": "#ef4444"}

    # 4. Neutral (crossed / partial)
    return {"status": "neutral", "label": "均線交錯", "color": "#94a3b8"}


def compute_all(
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    volumes: list[int] | None = None,
) -> dict:
    """Compute all technical indicators. KD / OBV / MA alignment only if OHLC+V provided."""
    result = {
        "ma": moving_averages(closes),
        "rsi": rsi(closes),
        "macd": macd(closes),
        "bollinger": bollinger_bands(closes),
    }
    if highs is not None and lows is not None:
        result["kd"] = stochastic_kd(highs, lows, closes)
    if volumes is not None:
        result["obv"] = obv(closes, volumes)
    result["ma_alignment"] = ma_alignment_status(closes, result["ma"])
    return result
