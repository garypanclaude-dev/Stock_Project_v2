"""
新聞分析模組 Demo — 抓取新聞後透過 Gemini 進行催化劑過濾與情緒分析
用法: python demo_analysis.py [SYMBOL]
需先設定環境變數: GEMINI_API_KEY
"""
import json
import sys
import logging

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from stock_fetcher import fetch_stock_news, analyze_news

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "AAPL"

    print(f"[1/2] Fetching news for {symbol}...")
    news_data = fetch_stock_news(symbol)
    print(f"      Got {news_data['count']} raw news items.\n")

    print(f"[2/2] Analyzing with Claude (catalyst filter + sentiment)...")
    catalysts = analyze_news(news_data)

    print(f"\n{'='*60}")
    print(f" {symbol} Catalyst Analysis Result")
    print(f" Raw: {news_data['count']} -> Catalysts: {len(catalysts)}")
    print(f"{'='*60}\n")

    print(json.dumps(catalysts, indent=2, ensure_ascii=False))

    if catalysts:
        bullish = sum(1 for c in catalysts if c.get("sentiment") == "Bullish")
        bearish = sum(1 for c in catalysts if c.get("sentiment") == "Bearish")
        neutral = sum(1 for c in catalysts if c.get("sentiment") == "Neutral")
        print(f"\n--- Sentiment Summary ---")
        print(f"  Bullish: {bullish}  |  Bearish: {bearish}  |  Neutral: {neutral}")


if __name__ == "__main__":
    main()
