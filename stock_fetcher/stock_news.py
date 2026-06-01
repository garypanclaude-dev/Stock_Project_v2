import feedparser
import requests
from datetime import datetime

from .utils import retry

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}+stock&hl=en-US&gl=US&ceid=US:en"


@retry(max_retries=3, base_delay=2.0, exceptions=(requests.RequestException, Exception))
def fetch_stock_news(symbol: str, max_items: int = 10) -> dict:
    """
    透過 Google News RSS 抓取與股票代號相關的最新新聞。
    """
    url = GOOGLE_NEWS_RSS.format(query=symbol)

    response = requests.get(url, timeout=15, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    response.raise_for_status()

    feed = feedparser.parse(response.text)

    if not feed.entries:
        return {"symbol": symbol.upper(), "news": [], "count": 0}

    news_list = []
    for entry in feed.entries[:max_items]:
        published = ""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            published = datetime(*entry.published_parsed[:6]).isoformat()

        summary = ""
        if hasattr(entry, "summary"):
            summary = _strip_html(entry.summary)

        news_list.append({
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "published": published,
            "summary": summary[:300] if summary else "",
            "source": entry.get("source", {}).get("title", ""),
        })

    return {
        "symbol": symbol.upper(),
        "news": news_list,
        "count": len(news_list),
        "query_time": datetime.now().isoformat(),
    }


def _strip_html(text: str) -> str:
    import re
    clean = re.sub(r"<[^>]+>", "", text)
    return clean.strip()
