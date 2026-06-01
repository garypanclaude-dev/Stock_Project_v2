"""
Stock Insights — FastAPI backend
Run: uvicorn app:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from mock_data import get_mock_response


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

app = FastAPI(title="Stock Insights API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": "2.0.0"}


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

    try:
        from stock_fetcher import analyze_news, fetch_stock_news, fetch_stock_price, fetch_fundamentals

        price_task = asyncio.to_thread(fetch_stock_price, ticker, period)
        news_task = asyncio.to_thread(fetch_stock_news, ticker)
        fund_task = asyncio.to_thread(fetch_fundamentals, ticker)

        price_data, news_data, fundamentals = await asyncio.gather(
            price_task, news_task, fund_task
        )

        catalysts = await asyncio.to_thread(analyze_news, news_data)

    except EnvironmentError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Upstream error: {exc}") from exc

    bullish = sum(1 for c in catalysts if c.get("sentiment") == "Bullish")
    bearish = sum(1 for c in catalysts if c.get("sentiment") == "Bearish")
    neutral = sum(1 for c in catalysts if c.get("sentiment") == "Neutral")

    return {
        "symbol": ticker,
        "period": period,
        "is_mock": False,
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


_frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
