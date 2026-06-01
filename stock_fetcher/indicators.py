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


def compute_all(closes: list[float]) -> dict:
    return {
        "ma": moving_averages(closes),
        "rsi": rsi(closes),
        "macd": macd(closes),
        "bollinger": bollinger_bands(closes),
    }
