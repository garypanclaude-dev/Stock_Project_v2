import yfinance as yf
from datetime import datetime, timedelta

from .utils import retry


@retry(max_retries=3, base_delay=2.0, exceptions=(Exception,))
def fetch_stock_price(symbol: str) -> dict:
    """
    取得指定股票代號的最近 7 天 K 線數據與最新報價。
    """
    ticker = yf.Ticker(symbol)

    end_date = datetime.now()
    start_date = end_date - timedelta(days=10)

    hist = ticker.history(start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"))

    if hist.empty:
        raise ValueError(f"No data found for symbol: {symbol}")

    hist = hist.tail(7)

    kline_data = []
    for date, row in hist.iterrows():
        kline_data.append({
            "date": date.strftime("%Y-%m-%d"),
            "open": round(row["Open"], 2),
            "high": round(row["High"], 2),
            "low": round(row["Low"], 2),
            "close": round(row["Close"], 2),
            "volume": int(row["Volume"]),
        })

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
        "latest_quote": latest_quote,
        "kline_7d": kline_data,
    }
