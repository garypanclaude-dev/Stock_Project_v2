"""
Stock Insights — FastAPI backend
Run: uvicorn app:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import List

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import logging

# Ensure our application loggers (stock_fetcher.*, app, etc.) are visible alongside uvicorn's.
# Idempotent: only configures the root logger if it has no handlers yet.
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

from mock_data import (
    get_mock_response, get_mock_batch_quotes, get_mock_chart_data,
    get_mock_peer_comparison, get_mock_watchlist_comparison, get_mock_screener,
)

logger = logging.getLogger(__name__)


# ── Startup background refresh ───────────────────────────────────────────────
# Trigger an incremental TW data fetch on server startup so the screener has
# up-to-date data without waiting for the user to click "重新整理".
# Runs as a fire-and-forget task: failures are logged, never block startup.

async def _startup_refresh_tw_data() -> None:
    try:
        from stock_fetcher.tw_market import run_incremental_update
        result = await asyncio.to_thread(run_incremental_update)
        if result.get("bootstrap_required"):
            logger.warning(
                "Startup refresh skipped: DB is empty. "
                "Run `python scripts/update_tw_history.py --backfill 60` first."
            )
        elif result["dates_attempted"] == 0:
            logger.info("Startup refresh: already up to date (latest=%s)", result["latest_date"])
        else:
            logger.info(
                "Startup refresh: %d added, %d skipped, %d failed, latest=%s",
                result["success"], result["skipped"], len(result["failed"]), result["latest_date"],
            )
    except Exception as exc:
        logger.warning("Startup refresh failed (non-fatal): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_startup_refresh_tw_data())
    yield


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

app = FastAPI(title="Stock Insights API", version="2.1.0", lifespan=lifespan)

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
    from stock_fetcher import (
        analyze_news, fetch_stock_news, fetch_stock_price, fetch_fundamentals,
        compute_composite_score, compute_risk_metrics, detect_patterns,
        generate_commentary,
    )

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

    sentiment_summary = {"bullish": bullish, "bearish": bearish, "neutral": neutral, "total": len(catalysts)}

    # ── Step 3: detect candlestick patterns (pure calculation) ───────
    patterns = detect_patterns(price_data["kline"])

    # ── Step 3a: compute composite score (pure calculation, no I/O) ──
    score = compute_composite_score(
        indicators=price_data["indicators"],
        fundamentals=fundamentals,
        sentiment_summary=sentiment_summary if not ai_error else None,
        catalysts=catalysts if not ai_error else None,
        kline=price_data["kline"],
        patterns=patterns,
    )

    # ── Step 3b: compute risk metrics (HV, MDD, ATR, stop-loss) ──────
    risk = compute_risk_metrics(price_data["kline"], price_data["indicators"], patterns)

    # ── Step 4: AI commentary — graceful degradation ─────────────────
    commentary = None
    try:
        commentary = await asyncio.to_thread(
            generate_commentary, ticker, score, fundamentals, price_data["kline"]
        )
    except Exception as exc:
        logger.warning("AI commentary failed for %s: %s", ticker, exc)

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
        "sentiment_summary": sentiment_summary,
        "score": score,
        "risk": risk,
        "patterns": patterns,
        "commentary": commentary,
    }


# ── Peer comparison ───────────────────────────────────────────────────────────
@app.get("/api/peer-comparison")
async def get_peer_comparison(
    ticker: str = Query(..., min_length=1, max_length=10),
    period: str = Query("3M"),
    mock: bool = Query(True),
) -> dict:
    ticker = _normalize_ticker(ticker)
    if period not in VALID_PERIODS:
        raise HTTPException(status_code=400, detail=f"Invalid period. Choose from: {VALID_PERIODS}")

    if mock:
        return get_mock_peer_comparison(ticker, period)

    try:
        from stock_fetcher import build_peer_comparison
        return await asyncio.to_thread(build_peer_comparison, ticker, period)
    except Exception as exc:
        logger.exception("Peer comparison error for %s", ticker)
        raise HTTPException(status_code=502, detail="Service temporarily unavailable") from exc


# ── Watchlist comparison ──────────────────────────────────────────────────────
@app.get("/api/watchlist-comparison")
async def get_watchlist_comparison(
    tickers: str = Query(..., description="Comma-separated tickers"),
    period: str = Query("3M"),
    mock: bool = Query(True),
) -> dict:
    raw_list = [t.strip() for t in tickers.split(",") if t.strip()]
    if not raw_list or len(raw_list) > 20:
        raise HTTPException(status_code=400, detail="Provide 1-20 tickers")
    normalized = [_normalize_ticker(t) for t in raw_list]

    if mock:
        return get_mock_watchlist_comparison(normalized, period)

    try:
        from stock_fetcher import build_watchlist_comparison
        return await asyncio.to_thread(build_watchlist_comparison, normalized, period)
    except Exception as exc:
        logger.exception("Watchlist comparison error")
        raise HTTPException(status_code=502, detail="Service temporarily unavailable") from exc


# ── Refresh TW market data (incremental fetch from latest DB date → today) ────
@app.post("/api/refresh-tw-data")
async def refresh_tw_data() -> dict:
    try:
        from stock_fetcher.tw_market import run_incremental_update
        return await asyncio.to_thread(run_incremental_update)
    except Exception as exc:
        logger.exception("TW data refresh failed")
        raise HTTPException(status_code=502, detail="TW data refresh failed") from exc


# ── Stock screener ────────────────────────────────────────────────────────────
@app.get("/api/stock-screener")
async def get_stock_screener(mock: bool = Query(True)) -> dict:
    if mock:
        return get_mock_screener()

    try:
        from stock_fetcher.tw_market import get_screener_results
        return await asyncio.to_thread(get_screener_results)
    except Exception as exc:
        logger.exception("Stock screener error")
        raise HTTPException(status_code=502, detail="Service temporarily unavailable") from exc


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
