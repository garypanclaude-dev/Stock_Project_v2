"""
股票資料抓取模組 Demo
用法: python demo.py [SYMBOL]
範例: python demo.py AAPL
"""
import json
import sys
import logging

from stock_fetcher import fetch_stock_price

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(f"=== 抓取 {symbol} 的股票資料 ===\n")

    print("【1】股價資料（最近 7 天 K 線 + 最新報價）")
    print("-" * 50)
    try:
        price_data = fetch_stock_price(symbol)
        print(json.dumps(price_data, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"股價抓取失敗: {e}")
        price_data = None

    print("\n=== 抓取完成 ===")
    if price_data:
        q = price_data["latest_quote"]
        print(f"  目前股價: {q['current_price']} {q['currency']}")
        print(f"  K 線天數: {len(price_data['kline_7d'])}")


if __name__ == "__main__":
    main()
