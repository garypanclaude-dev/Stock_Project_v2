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
from pydantic import BaseModel

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
    get_mock_backtest, get_mock_ml_train, get_mock_ml_predict,
    get_mock_refresh_tw_data,
)
from stock_fetcher.job_manager import get_job_manager

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

    # ── Step 1: fetch price + fundamentals in parallel ──────────────────
    from stock_fetcher import (
        fetch_stock_price, fetch_fundamentals,
        compute_composite_score, detect_patterns,
        generate_commentary,
    )

    try:
        price_task = asyncio.to_thread(fetch_stock_price, ticker, period)
        fund_task = asyncio.to_thread(fetch_fundamentals, ticker)

        price_data, fundamentals = await asyncio.gather(price_task, fund_task)
    except EnvironmentError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Upstream error for %s", ticker)
        raise HTTPException(status_code=502, detail="Service temporarily unavailable") from exc

    # ── Step 2: detect candlestick patterns (pure calculation) ───────
    patterns = detect_patterns(price_data["kline"])

    # ── Step 2a: compute composite score (pure calculation, no I/O) ──
    score = compute_composite_score(
        indicators=price_data["indicators"],
        fundamentals=fundamentals,
        kline=price_data["kline"],
        patterns=patterns,
    )

    # ── Step 3: AI commentary — graceful degradation ─────────────────
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
        "latest_quote": price_data["latest_quote"],
        "kline": price_data["kline"],
        "indicators": price_data["indicators"],
        "fundamentals": fundamentals,
        "score": score,
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


# ── Stock screener (短任務，直讀 DB，不走 job) ────────────────────────────────
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


# ── Chart only (for period switching — no fundamentals) ──────────────────────
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


# ── ML model ─────────────────────────────────────────────────────────────────
_ML_MODEL_CHOICES = ("momentum", "reversal")


def _resolve_ml_module(model: str):
    """Return the ml package module matching the requested model name."""
    if model not in _ML_MODEL_CHOICES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model '{model}'. Use one of: {', '.join(_ML_MODEL_CHOICES)}",
        )
    if model == "reversal":
        from stock_fetcher.ml import reversal as mod
    else:
        from stock_fetcher.ml import momentum as mod
    return mod


@app.get("/api/ml/status")
async def get_ml_status(model: str = Query("momentum")) -> dict:
    try:
        mod = _resolve_ml_module(model)
        result = await asyncio.to_thread(mod.get_model_status)
        result["model"] = model
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("ML status error")
        raise HTTPException(status_code=502, detail="ML status check failed") from exc


# ── 重活統一走 Job 系統（POST/GET/DELETE /api/jobs） ─────────────────────────

_JOB_TYPES = ("backtest", "refresh_tw", "ml_train", "ml_predict")


class JobSubmitRequest(BaseModel):
    type: str
    mock: bool = True
    params: dict = {}


def _build_job_task(job_type: str, params: dict, mock: bool):
    """Dispatch table：type → (task_key, runnable)。

    runnable 必須接受 reporter kwarg。mock/real 兩條路產出相同 signature 的
    callable，這樣 JobManager 只需要面對一種協定。
    """
    if job_type == "backtest":
        if mock:
            return "backtest", lambda *, reporter: get_mock_backtest(reporter=reporter)
        from stock_fetcher.backtester import run_backtest
        return "backtest", lambda *, reporter: run_backtest(reporter=reporter)

    if job_type == "refresh_tw":
        if mock:
            return "refresh_tw", lambda *, reporter: get_mock_refresh_tw_data(reporter=reporter)
        from stock_fetcher.tw_market import run_incremental_update
        return "refresh_tw", lambda *, reporter: run_incremental_update(reporter=reporter)

    if job_type in ("ml_train", "ml_predict"):
        model = params.get("model", "momentum")
        if model not in _ML_MODEL_CHOICES:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown model '{model}'. Use one of: {', '.join(_ML_MODEL_CHOICES)}",
            )
        key = f"{job_type}:{model}"
        if job_type == "ml_train":
            if mock:
                return key, lambda *, reporter: get_mock_ml_train(model, reporter=reporter)
            mod = _resolve_ml_module(model)
            return key, lambda *, reporter: mod.train_model(reporter=reporter)
        # ml_predict
        if mock:
            return key, lambda *, reporter: get_mock_ml_predict(model, reporter=reporter)
        mod = _resolve_ml_module(model)
        return key, lambda *, reporter: mod.predict_today(reporter=reporter)

    raise HTTPException(status_code=400, detail=f"Unknown job type: {job_type}")


@app.post("/api/jobs")
async def submit_job(req: JobSubmitRequest) -> dict:
    if req.type not in _JOB_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown job type. Use one of: {', '.join(_JOB_TYPES)}",
        )
    key, runnable = _build_job_task(req.type, req.params, req.mock)
    job = get_job_manager().submit(key, runnable)
    return job.snapshot()


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    job = get_job_manager().get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found (可能已過期或已被回收)")
    return job.snapshot(include_result=True)


@app.delete("/api/jobs/{job_id}")
async def cancel_job(job_id: str) -> dict:
    ok = get_job_manager().cancel(job_id)
    if not ok:
        raise HTTPException(status_code=409, detail="Job not cancellable (已結束或不存在)")
    return {"cancelled": True, "job_id": job_id}


_frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
