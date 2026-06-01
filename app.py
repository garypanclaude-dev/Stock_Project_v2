"""
Stock Insights — FastAPI backend
Run: uvicorn app:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
load_dotenv()  # 自動讀取專案根目錄的 .env 檔

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from mock_data import get_mock_response


def _normalize_ticker(raw: str) -> str:
    """
    自動補齊股票代號後綴。
    規則（依序判斷）：
      - 已有後綴（含 '.'）→ 直接回傳，如 2330.TW、9984.T
      - 純數字 4 碼        → 台灣上市，補 .TW，如 2330 → 2330.TW
      - 純數字 6 碼        → 中國 A 股，補 .SS（上交所）或 .SZ（深交所）
                             簡化：以 6 開頭→.SH，其餘→.SZ
      - 其餘               → 視為美股，不變
    """
    t = raw.upper().strip()
    if "." in t:
        return t                          # 使用者已自行指定後綴
    if t.isdigit():
        if len(t) == 4:
            return t + ".TW"             # 台灣上市 (TWSE)
        if len(t) == 5:
            return t + ".TW"             # 台灣上市（部分代號為 5 碼）
        if len(t) == 6:
            return t + (".SS" if t.startswith("6") else ".SZ")  # 中國 A 股
    return t                             # 美股等字母代號


app = FastAPI(title="Stock Insights API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ── Health ─────────────────────────────────────────────────────────────────────
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": "1.0.0"}


# ── Env check (開發用，確認伺服器程序有讀到 Key) ─────────────────────────────
@app.get("/api/env-check")
def env_check() -> dict:
    key = os.environ.get("GEMINI_API_KEY", "")
    return {
        "GEMINI_API_KEY_set": bool(key),
        "GEMINI_API_KEY_length": len(key),
        "GEMINI_API_KEY_prefix": key[:8] + "…" if key else "(not set)",
    }


# ── Main API ───────────────────────────────────────────────────────────────────
@app.get("/api/stock-insights")
async def get_stock_insights(
    ticker: str = Query(..., min_length=1, max_length=10, description="Stock symbol, e.g. AAPL"),
    mock: bool = Query(True, description="Use mock data (skip external API calls)"),
) -> dict:
    ticker = _normalize_ticker(ticker)

    # ── Mock mode (no external calls) ─────────────────────────────────────────
    if mock:
        return get_mock_response(ticker)

    # ── Real pipeline ──────────────────────────────────────────────────────────
    try:
        from stock_fetcher import analyze_news, fetch_stock_news, fetch_stock_price

        # Run blocking I/O in thread pool so FastAPI event loop stays free
        price_data = await asyncio.to_thread(fetch_stock_price, ticker)
        news_data = await asyncio.to_thread(fetch_stock_news, ticker)
        catalysts = await asyncio.to_thread(analyze_news, news_data)

    except EnvironmentError as exc:
        # Missing API key etc.
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        # Unknown ticker / no data found
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Upstream error: {exc}") from exc

    bullish = sum(1 for c in catalysts if c.get("sentiment") == "Bullish")
    bearish = sum(1 for c in catalysts if c.get("sentiment") == "Bearish")
    neutral = sum(1 for c in catalysts if c.get("sentiment") == "Neutral")

    return {
        "symbol": ticker,
        "is_mock": False,
        "latest_quote": price_data["latest_quote"],
        "kline_7d": price_data["kline_7d"],
        "catalysts": catalysts,
        "sentiment_summary": {
            "bullish": bullish,
            "bearish": bearish,
            "neutral": neutral,
            "total": len(catalysts),
        },
    }


# ── Serve frontend (must be registered AFTER API routes) ──────────────────────
_frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
