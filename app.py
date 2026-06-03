"""
Stock Insights — FastAPI backend
Run: uvicorn app:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import os
from typing import List

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import logging

from mock_data import get_mock_response, get_mock_batch_quotes, get_mock_chart_data

logger = logging.getLogger(__name__)


def _normalize_ticker(raw: str) -> str:
    t = raw.upper().strip()
    if "." in t:
        return t
    if t.isdigit():
        if len(t) == 4:
            return t + ".TW"
        if len(t) == 5:
            return t + ".TW"
        if len(t) == 6:
            return t + (".SS" if t.startswith("6") else ".SZ")
    return t


VALID_PERIODS = {"1M", "3M", "6M", "1Y", "YTD"}

app = FastAPI(title="Stock Insights API", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": "2.1.0"}


# ── Full insights (single stock) ─────────────────────────────────────────────
@app.get("/api/stock-insights")
async def get_stock_insights(
    ticker: str = Query(..., min_length=1, max_length=10),
    period: str = Query("3M", description="1M, 3M, 6M, 1Y, YTD"),
    mock: bool = Query(True),
) -> dict:
    ticker = _normalize_ticker(ticker)
    if period not in VALID_PERIODS:
        raise HTTPException(status_code=400, detail=f"Invalid period. Choose from: {VALID_PERIODS}")

    if mock:
        return get_mock_response(ticker, period)

    # ── Step 1: fetch price, news, fundamentals in parallel ─────────────
    from stock_fetcher import analyze_news, fetch_stock_news, fetch_stock_price, fetch_fundamentals

    try:
        price_task = asyncio.to_thread(fetch_stock_price, ticker, period)
        news_task = asyncio.to_thread(fetch_stock_news, ticker)
        fund_task = asyncio.to_thread(fetch_fundamentals, ticker)

        price_data, news_data, fundamentals = await asyncio.gather(
            price_task, news_task, fund_task
        )
    except EnvironmentError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Upstream error for %s", ticker)
        raise HTTPException(status_code=502, detail="Service temporarily unavailable") from exc

    # ── Step 2: AI analysis — graceful degradation if it fails ────────
    catalysts: list[dict] = []
    ai_error: str | None = None
    try:
        catalysts = await asyncio.to_thread(analyze_news, news_data)
    except Exception as exc:
        logger.warning("AI analysis failed for %s: %s", ticker, exc)
        ai_error = "AI 分析暫時不可用（可能為 API 配額已達上限），其餘數據正常顯示。"

    bullish = sum(1 for c in catalysts if c.get("sentiment") == "Bullish")
    bearish = sum(1 for c in catalysts if c.get("sentiment") == "Bearish")
    neutral = sum(1 for c in catalysts if c.get("sentiment") == "Neutral")

    return {
        "symbol": ticker,
        "period": period,
        "is_mock": False,
        "ai_error": ai_error,
        "latest_quote": price_data["latest_quote"],
        "kline": price_data["kline"],
        "indicators": price_data["indicators"],
        "fundamentals": fundamentals,
        "catalysts": catalysts,
        "sentiment_summary": {
            "bullish": bullish,
            "bearish": bearish,
            "neutral": neutral,
            "total": len(catalysts),
        },
    }


# ── Chart only (for period switching — no news/gemini/fundamentals) ────────────
@app.get("/api/stock-chart")
async def get_stock_chart(
    ticker: str = Query(..., min_length=1, max_length=10),
    period: str = Query("3M"),
    mock: bool = Query(True),
) -> dict:
    ticker = _normalize_ticker(ticker)
    if period not in VALID_PERIODS:
        raise HTTPException(status_code=400, detail=f"Invalid period. Choose from: {VALID_PERIODS}")

    if mock:
        return get_mock_chart_data(ticker, period)

    try:
        from stock_fetcher import fetch_stock_price
        price_data = await asyncio.to_thread(fetch_stock_price, ticker, period)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Chart fetch error for %s", ticker)
        raise HTTPException(status_code=502, detail="Service temporarily unavailable") from exc

    return {
        "symbol": ticker,
        "period": period,
        "kline": price_data["kline"],
        "indicators": price_data["indicators"],
    }


# ── Batch quotes (for watchlist) ──────────────────────────────────────────────
@app.get("/api/batch-quotes")
async def get_batch_quotes(
    tickers: str = Query(..., description="Comma-separated tickers, e.g. AAPL,TSLA,NVDA"),
    mock: bool = Query(True),
) -> dict:
    raw_list = [t.strip() for t in tickers.split(",") if t.strip()]
    if not raw_list:
        raise HTTPException(status_code=400, detail="No tickers provided")
    if len(raw_list) > 20:
        raise HTTPException(status_code=400, detail="Max 20 tickers per request")

    normalized = [_normalize_ticker(t) for t in raw_list]

    if mock:
        return {"quotes": get_mock_batch_quotes(normalized)}

    try:
        from stock_fetcher.stock_price import fetch_stock_price

        async def _fetch_one(symbol: str) -> dict:
            try:
                data = await asyncio.to_thread(fetch_stock_price, symbol, "1M")
                q = data["latest_quote"]
                diff = q["current_price"] - q["previous_close"]
                pct = (diff / q["previous_close"]) * 100 if q["previous_close"] else 0
                return {
                    "symbol": symbol,
                    "current_price": q["current_price"],
                    "previous_close": q["previous_close"],
                    "change": round(diff, 2),
                    "change_pct": round(pct, 2),
                    "currency": q.get("currency", "USD"),
                    "market_cap": q.get("market_cap"),
                    "error": None,
                }
            except Exception as e:
                return {"symbol": symbol, "error": str(e)}

        results = await asyncio.gather(*[_fetch_one(s) for s in normalized])

    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Upstream error: {exc}") from exc

    return {"quotes": list(results)}


_frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
