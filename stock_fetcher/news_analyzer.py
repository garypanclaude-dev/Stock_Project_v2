import json
import logging
import os

from google import genai
from google.genai import types

from .cache import ttl_cache
from .utils import retry

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"


# ── AI Commentary ─────────────────────────────────────────────────────────────

COMMENTARY_PROMPT = """你是一位資深金融分析師。根據以下股票的綜合評分與關鍵指標，撰寫 100 字以內的繁體中文投資研判摘要。

要求：
1. 點出技術面、基本面的各一個關鍵事實
2. 給出短期策略建議（如：逢回佈局、觀望、減碼）
3. 如有足夠資料，提供支撐位與壓力位
4. 語氣專業精確

直接輸出純文字，不要加任何標題、標記或前綴。"""


def generate_commentary(symbol: str, score_data: dict, fundamentals: dict | None, kline: list[dict] | None) -> str | None:
    """
    Generate AI commentary based on composite score + key metrics.
    Returns commentary string or None on failure (graceful degradation).
    """
    try:
        return _generate_commentary_cached(
            symbol,
            score_data.get("composite", 0),
            score_data.get("grade", {}).get("label", ""),
            json.dumps(_build_commentary_context(score_data, fundamentals, kline), ensure_ascii=False),
        )
    except Exception as exc:
        logger.warning("AI commentary failed for %s: %s", symbol, exc)
        return None


@ttl_cache(ttl_seconds=3600)
@retry(max_retries=2, base_delay=3.0, backoff_factor=2.0)
def _generate_commentary_cached(symbol: str, composite: int, grade_label: str, context_json: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY environment variable is not set")

    client = genai.Client(api_key=api_key)
    user_message = f"股票：{symbol}\n綜合評分：{composite}/100（{grade_label}）\n\n詳細指標：\n{context_json}"

    response = client.models.generate_content(
        model=MODEL,
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=COMMENTARY_PROMPT,
            max_output_tokens=300,
            temperature=0.3,
        ),
    )

    return response.text.strip()


def _build_commentary_context(score_data: dict, fundamentals: dict | None, kline: list[dict] | None) -> dict:
    ctx = {
        "composite": score_data.get("composite"),
        "technical_score": score_data.get("technical", {}).get("score"),
        "fundamental_score": score_data.get("fundamental", {}).get("score"),
    }

    if fundamentals:
        v = fundamentals.get("valuation") or {}
        p = fundamentals.get("profitability") or {}
        ctx["pe_ratio"] = v.get("pe_ratio")
        ctx["roe"] = p.get("roe")
        ctx["profit_margin"] = p.get("profit_margin")

    if kline and len(kline) > 0:
        ctx["current_price"] = kline[-1]["close"]
        if len(kline) >= 5:
            ctx["price_5d_ago"] = kline[-5]["close"]

    return ctx
