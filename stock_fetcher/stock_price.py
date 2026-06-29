import yfinance as yf
from datetime import datetime, timedelta

from .cache import ttl_cache
from .indicators import compute_all
from .utils import retry

PERIOD_MAP = {
    "1M":  30,
    "3M":  90,
    "6M":  180,
    "1Y":  365,
    "YTD": None,
}


@ttl_cache(ttl_seconds=300)  # 5 min
@retry(max_retries=3, base_delay=2.0, exceptions=(Exception,))
def fetch_stock_price(symbol: str, period: str = "3M") -> dict:
    ticker = yf.Ticker(symbol)
    end_date = datetime.now()

    if period == "YTD":
        start_date = datetime(end_date.year, 1, 1)
    else:
        days = PERIOD_MAP.get(period, 90)
        # fetch extra 80 days so MA60 has enough warm-up data
        start_date = end_date - timedelta(days=days + 80)

    hist = ticker.history(
        start=start_date.strftime("%Y-%m-%d"),
        end=(end_date + timedelta(days=1)).strftime("%Y-%m-%d"),
    )

    if hist.empty:
        raise ValueError(f"No data found for symbol: {symbol}")

    # Yahoo's daily endpoint sometimes leaves the most-recent row with NaN OHLC
    # for hours after close (TW market in particular). Backfill that row from
    # the 1m intraday endpoint, which is the same source as fast_info.last_price.
    last_row = hist.iloc[-1]
    if last_row[["Open", "High", "Low", "Close"]].isna().any():
        try:
            intraday = ticker.history(period="2d", interval="1m")
            if not intraday.empty:
                target_date = hist.index[-1].date()
                day_slice = intraday[intraday.index.date == target_date]
                if not day_slice.empty:
                    hist.loc[hist.index[-1], "Open"] = day_slice["Open"].iloc[0]
                    hist.loc[hist.index[-1], "High"] = day_slice["High"].max()
                    hist.loc[hist.index[-1], "Low"] = day_slice["Low"].min()
                    hist.loc[hist.index[-1], "Close"] = day_slice["Close"].iloc[-1]
                    hist.loc[hist.index[-1], "Volume"] = int(day_slice["Volume"].sum())
        except Exception:
            pass  # fallback: leave NaN, frontend will skip that bar

    # Drop any remaining NaN OHLC rows so the frontend never receives nulls.
    hist = hist.dropna(subset=["Open", "High", "Low", "Close"])
    if hist.empty:
        raise ValueError(f"No data found for symbol: {symbol}")

    all_klines = []
    for date, row in hist.iterrows():
        all_klines.append({
            "date": date.strftime("%Y-%m-%d"),
            "open": round(row["Open"], 2),
            "high": round(row["High"], 2),
            "low": round(row["Low"], 2),
            "close": round(row["Close"], 2),
            "volume": int(row["Volume"]),
        })

    closes = [k["close"] for k in all_klines]
    highs = [k["high"] for k in all_klines]
    lows = [k["low"] for k in all_klines]
    volumes = [k["volume"] for k in all_klines]
    indicators = compute_all(closes, highs=highs, lows=lows, volumes=volumes)

    # trim warm-up: only return the requested calendar range
    if period == "YTD":
        cutoff = datetime(end_date.year, 1, 1).strftime("%Y-%m-%d")
    else:
        days = PERIOD_MAP.get(period, 90)
        cutoff = (end_date - timedelta(days=days)).strftime("%Y-%m-%d")

    start_idx = 0
    for i, k in enumerate(all_klines):
        if k["date"] >= cutoff:
            start_idx = i
            break

    trimmed_klines = all_klines[start_idx:]
    trimmed_indicators = _trim_indicators(indicators, start_idx, len(all_klines))

    fast_info = ticker.fast_info
    latest_quote = {
        "symbol": symbol.upper(),
        "current_price": round(fast_info.last_price, 2),
        "previous_close": round(fast_info.previous_close, 2),
        "market_cap": fast_info.market_cap,
        "currency": fast_info.currency,
        "query_time": datetime.now().isoformat(),
    }

    return {
        "symbol": symbol.upper(),
        "period": period,
        "latest_quote": latest_quote,
        "kline": trimmed_klines,
        "indicators": trimmed_indicators,
    }


def _trim_indicators(indicators: dict, start: int, total: int) -> dict:
    def _slice(lst):
        return lst[start:]

    trimmed = {
        "ma": {k: _slice(v) for k, v in indicators["ma"].items()},
        "rsi": _slice(indicators["rsi"]),
        "macd": {k: _slice(v) for k, v in indicators["macd"].items()},
        "bollinger": {k: _slice(v) for k, v in indicators["bollinger"].items()},
    }
    if "kd" in indicators:
        trimmed["kd"] = {k: _slice(v) for k, v in indicators["kd"].items()}
    if "obv" in indicators:
        trimmed["obv"] = _slice(indicators["obv"])
    if "ma_alignment" in indicators:
        # status is a dict (not a list) — recompute on trimmed closes via caller, or pass through.
        # Trimmed slice doesn't change the "latest" status, so just pass through.
        trimmed["ma_alignment"] = indicators["ma_alignment"]
    return trimmed
