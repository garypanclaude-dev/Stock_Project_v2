import hashlib
import json
import logging
import os
import re

from google import genai
from google.genai import types

from .cache import ttl_cache
from .utils import retry

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位資深金融分析師，專精於從新聞中辨識對股價有實質影響的「市場催化劑 (Market Catalyst)」。

## 你的任務

針對輸入的每一則新聞，執行以下判斷：

### 第一步：過濾
判斷該新聞是否為「市場催化劑」。只保留以下類型：
- 財報公布或營收數據（earnings, revenue）
- 產品重大發布或重大技術突破
- 併購、拆分、重大合作案
- 監管/法規變動（反壟斷、關稅、制裁）
- 管理層重大異動（CEO/CFO 更替）
- 重大訴訟或法律裁決
- 分析師評級調整（upgrade/downgrade）
- 總體經濟事件對該公司的直接影響

以下類型應被過濾掉：
- 一般性公關稿、品牌宣傳
- 純粹的股價報價頁面或行情看板
- 投資組合持倉揭露（某基金買入/賣出）
- 重複或資訊量極低的新聞
- 無具體數據支撐的泛泛而談

### 第二步：情緒分析
對保留的每則新聞給出情緒判定：
- **Bullish**：利多，預期推動股價上漲
- **Bearish**：利空，預期導致股價下跌
- **Neutral**：影響不明確或多空交織

### 第三步：重點摘要
用繁體中文將新聞濃縮成 50 字以內的重點摘要。直接點出關鍵事實與數據。

## 輸出格式

嚴格輸出純 JSON Array，不要加任何 Markdown 標記、程式碼區塊或額外文字。
如果所有新聞都被過濾掉，輸出空陣列 []。

每個元素格式：
[
  {
    "original_title": "原始新聞標題",
    "link": "原始新聞連結",
    "published": "原始發布時間",
    "source": "新聞來源",
    "sentiment": "Bullish 或 Bearish 或 Neutral",
    "catalyst_type": "催化劑類型（如 earnings / product_launch / regulation / analyst_rating / m_and_a / management / litigation / macro）",
    "summary": "50字以內繁體中文重點摘要"
  }
]"""

MODEL = "gemini-2.5-flash"

VALID_SENTIMENTS = {"Bullish", "Bearish", "Neutral"}
VALID_CATALYST_TYPES = {"earnings", "product_launch", "regulation", "analyst_rating", "m_and_a", "management", "litigation", "macro"}


def analyze_news(news_data: dict) -> list[dict]:
    """
    Entry point — uses a content hash so identical news hits cache.
    """
    symbol = news_data.get("symbol", "UNKNOWN")
    news_list = news_data.get("news", [])

    if not news_list:
        logger.info("No news to analyze for %s", symbol)
        return []

    # Build a stable hash of the news content for cache keying
    content_hash = _hash_news(news_list)
    return _analyze_cached(symbol, content_hash, json.dumps(news_list, ensure_ascii=False))


@ttl_cache(ttl_seconds=3600)  # 1 hr — same news set won't be re-analyzed
@retry(max_retries=3, base_delay=3.0, backoff_factor=2.0)
def _analyze_cached(symbol: str, content_hash: str, news_json: str) -> list[dict]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY environment variable is not set")

    client = genai.Client(api_key=api_key)
    user_message = f"請分析以下 {symbol} 的相關新聞：\n\n{news_json}"

    response = client.models.generate_content(
        model=MODEL,
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=4096,
            temperature=0.2,
            response_mime_type="application/json",
        ),
    )

    raw_text = response.text.strip()
    result = _parse_json_response(raw_text)
    result = _validate_catalysts(result)

    logger.info(
        "Analyzed news for %s → %d catalysts identified (hash=%s)",
        symbol, len(result), content_hash[:8],
    )
    return result


def _hash_news(news_list: list[dict]) -> str:
    titles = "|".join(n.get("title", "") for n in news_list)
    return hashlib.md5(titles.encode()).hexdigest()


def _parse_json_response(text: str) -> list[dict]:
    text = text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Try direct parse first
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # Fallback: extract first [...] block via regex
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, list):
                logger.warning("Used regex fallback to extract JSON array")
                return parsed
        except json.JSONDecodeError:
            pass

    logger.error("Failed to parse LLM response as JSON. Raw: %s", text[:500])
    return []  # graceful degradation instead of crashing


def _validate_catalysts(catalysts: list[dict]) -> list[dict]:
    """Filter out malformed catalyst entries."""
    valid = []
    for c in catalysts:
        if not isinstance(c, dict):
            continue
        # Ensure required fields exist
        if not c.get("original_title") or not c.get("sentiment"):
            continue
        # Normalize sentiment
        if c["sentiment"] not in VALID_SENTIMENTS:
            c["sentiment"] = "Neutral"
        # Normalize catalyst_type
        if c.get("catalyst_type") not in VALID_CATALYST_TYPES:
            c["catalyst_type"] = "macro"
        valid.append(c)
    return valid
