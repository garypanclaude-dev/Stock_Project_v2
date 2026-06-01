import json
import logging
import os

from google import genai
from google.genai import types

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


@retry(max_retries=3, base_delay=60.0, backoff_factor=1.5)
def analyze_news(news_data: dict) -> list[dict]:
    """
    將原始新聞資料送入 Gemini 進行催化劑過濾與情緒分析。
    news_data: fetch_stock_news() 的回傳值。
    """
    symbol = news_data.get("symbol", "UNKNOWN")
    news_list = news_data.get("news", [])

    if not news_list:
        logger.info("No news to analyze for %s", symbol)
        return []

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY environment variable is not set")

    client = genai.Client(api_key=api_key)

    user_message = f"請分析以下 {symbol} 的相關新聞：\n\n{json.dumps(news_list, ensure_ascii=False, indent=2)}"

    response = client.models.generate_content(
        model=MODEL,
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=4096,
            temperature=0.2,
        ),
    )

    raw_text = response.text.strip()
    result = _parse_json_response(raw_text)

    logger.info(
        "Analyzed %d news for %s → %d catalysts identified",
        len(news_list), symbol, len(result),
    )
    return result


def _parse_json_response(text: str) -> list[dict]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse LLM response as JSON: %s", e)
        logger.debug("Raw response: %s", text[:500])
        raise ValueError(f"LLM response is not valid JSON: {e}") from e

    if not isinstance(parsed, list):
        raise ValueError(f"Expected JSON Array, got {type(parsed).__name__}")

    return parsed
