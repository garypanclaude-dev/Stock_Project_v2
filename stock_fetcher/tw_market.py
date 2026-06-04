"""
Taiwan stock market screener — TWSE/TPEX bulk data fetch + multi-factor ranking.

Data source: TWSE and TPEX official Open Data APIs.
Stores daily snapshot in data/tw_market_snapshot.json.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, date, timedelta
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SNAPSHOT_PATH = DATA_DIR / "tw_market_snapshot.json"

# In-memory cache
_snapshot_cache: dict | None = None
_snapshot_lock = threading.Lock()

# ── Screener config ───────────────────────────────────────────────────────────
SCREENER_CONFIG = {
    "min_volume": 500,       # 日均成交量 >= 500 張
    "top_n": 20,             # 回傳前 N 名
    "weights": {
        "momentum": 0.30,
        "value":    0.20,
        "quality":  0.25,
        "size":     0.10,
        "volatility": 0.15,
    },
}


# ── Public API ────────────────────────────────────────────────────────────────

def get_screener_results() -> dict:
    """Return top-N stock picks. Auto-updates snapshot if stale."""
    snapshot = _get_snapshot()
    if snapshot is None:
        snapshot = _fetch_and_save_snapshot()
    elif _is_stale(snapshot.get("date", "")):
        # Return stale data immediately, update in background
        threading.Thread(target=_fetch_and_save_snapshot, daemon=True).start()

    if snapshot is None:
        return {"last_updated": None, "total_stocks": 0, "top_picks": []}

    stocks = snapshot.get("stocks", [])
    ranked = _rank_stocks(stocks)

    return {
        "last_updated": snapshot.get("updated_at"),
        "total_stocks": len(stocks),
        "top_picks": ranked[:SCREENER_CONFIG["top_n"]],
    }


# ── Snapshot management ───────────────────────────────────────────────────────

def _get_snapshot() -> dict | None:
    global _snapshot_cache
    with _snapshot_lock:
        if _snapshot_cache is not None:
            return _snapshot_cache

    if SNAPSHOT_PATH.exists():
        try:
            data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
            with _snapshot_lock:
                _snapshot_cache = data
            logger.info("Loaded TW market snapshot from disk: %s", data.get("date"))
            return data
        except Exception as e:
            logger.error("Failed to load snapshot: %s", e)
    return None


def _fetch_and_save_snapshot() -> dict | None:
    global _snapshot_cache
    logger.info("Fetching TW market data from TWSE/TPEX...")

    try:
        twse_stocks = _fetch_twse_daily()
        tpex_stocks = _fetch_tpex_daily()
        twse_pe = _fetch_twse_pe()
        tpex_pe = _fetch_tpex_pe()

        # Merge PE data into stocks
        pe_map = {**twse_pe, **tpex_pe}
        all_stocks = twse_stocks + tpex_stocks

        for s in all_stocks:
            code = s["symbol"].replace(".TW", "")
            if code in pe_map:
                s.update(pe_map[code])

        # Filter: must have volume and close price
        all_stocks = [s for s in all_stocks if s.get("close") and s.get("volume", 0) > 0]

        snapshot = {
            "date": date.today().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "stocks": all_stocks,
        }

        # Save to disk
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

        with _snapshot_lock:
            _snapshot_cache = snapshot

        logger.info("TW market snapshot saved: %d stocks", len(all_stocks))
        return snapshot

    except Exception as e:
        logger.exception("Failed to fetch TW market data: %s", e)
        return None


def _is_stale(snapshot_date: str) -> bool:
    """Check if snapshot is outdated based on TW market schedule."""
    if not snapshot_date:
        return True

    try:
        snap_date = date.fromisoformat(snapshot_date)
    except ValueError:
        return True

    today = date.today()
    now = datetime.now()

    # Weekend: snapshot should be Friday
    if today.weekday() >= 5:
        last_friday = today - timedelta(days=today.weekday() - 4)
        return snap_date < last_friday

    # Weekday before 14:00: snapshot should be previous trading day
    if now.hour < 14:
        prev_day = today - timedelta(days=1)
        while prev_day.weekday() >= 5:
            prev_day -= timedelta(days=1)
        return snap_date < prev_day

    # Weekday after 14:00: snapshot should be today
    return snap_date < today


# ── TWSE/TPEX API fetchers ────────────────────────────────────────────────────

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _fetch_twse_daily() -> list[dict]:
    """Fetch TWSE (上市) daily closing data."""
    today_str = date.today().strftime("%Y%m%d")
    url = f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={today_str}&type=ALLBUT0999"

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        data = resp.json()

        if data.get("stat") != "OK":
            logger.warning("TWSE daily returned non-OK: %s", data.get("stat"))
            return []

        stocks = []
        for table in data.get("data9", data.get("data8", [])):
            try:
                code = table[0].strip()
                name = table[1].strip()

                # Skip ETFs, warrants, special codes
                if not code.isdigit() or len(code) != 4:
                    continue

                close = _parse_tw_number(table[8])
                change = _parse_tw_number(table[10])
                volume = _parse_tw_number(table[2]) / 1000  # shares -> 張

                if close is None or close <= 0:
                    continue

                stocks.append({
                    "symbol": f"{code}.TW",
                    "name": name,
                    "close": close,
                    "change": change or 0,
                    "change_pct": round((change / (close - change)) * 100, 2) if change and close != change else 0,
                    "volume": int(volume),
                    "market": "TWSE",
                })
            except (IndexError, ValueError):
                continue

        logger.info("TWSE daily: %d stocks fetched", len(stocks))
        return stocks

    except Exception as e:
        logger.error("TWSE daily fetch failed: %s", e)
        return []


def _fetch_tpex_daily() -> list[dict]:
    """Fetch TPEX (上櫃) daily closing data."""
    today = date.today()
    tw_date = f"{today.year - 1911}/{today.month:02d}/{today.day:02d}"
    url = f"https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php?l=zh-tw&d={tw_date}&se=AL"

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        data = resp.json()

        stocks = []
        for row in data.get("aaData", []):
            try:
                code = row[0].strip()
                name = row[1].strip()

                if not code.isdigit() or len(code) != 4:
                    continue

                close = _parse_tw_number(row[2])
                change = _parse_tw_number(row[3])
                volume = _parse_tw_number(row[7]) / 1000

                if close is None or close <= 0:
                    continue

                stocks.append({
                    "symbol": f"{code}.TW",
                    "name": name,
                    "close": close,
                    "change": change or 0,
                    "change_pct": round((change / (close - change)) * 100, 2) if change and close != change else 0,
                    "volume": int(volume),
                    "market": "TPEX",
                })
            except (IndexError, ValueError):
                continue

        logger.info("TPEX daily: %d stocks fetched", len(stocks))
        return stocks

    except Exception as e:
        logger.error("TPEX daily fetch failed: %s", e)
        return []


def _fetch_twse_pe() -> dict[str, dict]:
    """Fetch TWSE P/E, yield, P/B ratios."""
    today_str = date.today().strftime("%Y%m%d")
    url = f"https://www.twse.com.tw/exchangeReport/BWIBBU_d?response=json&date={today_str}&selectType=ALL"

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        data = resp.json()

        result = {}
        for row in data.get("data", []):
            try:
                code = row[0].strip()
                result[code] = {
                    "pe": _parse_tw_number(row[4]),
                    "yield_pct": _parse_tw_number(row[2]),
                    "pb": _parse_tw_number(row[5]) if len(row) > 5 else None,
                }
            except (IndexError, ValueError):
                continue

        logger.info("TWSE PE: %d entries", len(result))
        return result

    except Exception as e:
        logger.error("TWSE PE fetch failed: %s", e)
        return {}


def _fetch_tpex_pe() -> dict[str, dict]:
    """Fetch TPEX P/E, yield, P/B ratios."""
    today = date.today()
    tw_date = f"{today.year - 1911}/{today.month:02d}/{today.day:02d}"
    url = f"https://www.tpex.org.tw/web/stock/aftertrading/peratio_analysis/pera_result.php?l=zh-tw&d={tw_date}&type=ALL"

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        data = resp.json()

        result = {}
        for row in data.get("aaData", []):
            try:
                code = row[0].strip()
                result[code] = {
                    "pe": _parse_tw_number(row[2]),
                    "yield_pct": _parse_tw_number(row[5]),
                    "pb": _parse_tw_number(row[6]) if len(row) > 6 else None,
                }
            except (IndexError, ValueError):
                continue

        logger.info("TPEX PE: %d entries", len(result))
        return result

    except Exception as e:
        logger.error("TPEX PE fetch failed: %s", e)
        return {}


# ── Multi-factor ranking ──────────────────────────────────────────────────────

def _rank_stocks(stocks: list[dict]) -> list[dict]:
    """Apply multi-factor ranking to produce top picks."""
    # Filter minimum volume
    min_vol = SCREENER_CONFIG["min_volume"]
    eligible = [s for s in stocks if s.get("volume", 0) >= min_vol]

    if not eligible:
        return []

    # Compute percentile ranks for each factor
    w = SCREENER_CONFIG["weights"]

    # Momentum: change_pct (higher = better)
    _assign_percentile(eligible, "change_pct", "momentum_rank", reverse=False)

    # Value: P/E (lower = better)
    _assign_percentile(eligible, "pe", "value_rank", reverse=True)

    # Quality: yield (higher = better)
    _assign_percentile(eligible, "yield_pct", "quality_rank", reverse=False)

    # Size: volume as proxy (higher = better, more liquid)
    _assign_percentile(eligible, "volume", "size_rank", reverse=False)

    # Volatility: abs(change_pct) as proxy (lower = better)
    for s in eligible:
        s["_abs_change"] = abs(s.get("change_pct", 0))
    _assign_percentile(eligible, "_abs_change", "volatility_rank", reverse=True)

    # Composite score
    for s in eligible:
        s["score"] = round(
            s.get("momentum_rank", 50) * w["momentum"]
            + s.get("value_rank", 50) * w["value"]
            + s.get("quality_rank", 50) * w["quality"]
            + s.get("size_rank", 50) * w["size"]
            + s.get("volatility_rank", 50) * w["volatility"]
        )

    # Sort by score descending
    eligible.sort(key=lambda s: s["score"], reverse=True)

    # Build output
    result = []
    for rank, s in enumerate(eligible[:SCREENER_CONFIG["top_n"]], 1):
        result.append({
            "rank": rank,
            "symbol": s["symbol"],
            "name": s.get("name", ""),
            "score": s["score"],
            "close": s.get("close", 0),
            "change_pct": s.get("change_pct", 0),
            "pe": s.get("pe"),
            "yield_pct": s.get("yield_pct"),
            "volume": s.get("volume", 0),
            "factors": {
                "momentum": s.get("momentum_rank", 0),
                "value": s.get("value_rank", 0),
                "quality": s.get("quality_rank", 0),
                "size": s.get("size_rank", 0),
                "volatility": s.get("volatility_rank", 0),
            },
        })

    return result


def _assign_percentile(stocks: list[dict], field: str, rank_field: str, reverse: bool = False):
    """Assign 0-100 percentile rank based on a field value."""
    valid = [s for s in stocks if s.get(field) is not None]
    if not valid:
        for s in stocks:
            s[rank_field] = 50
        return

    valid.sort(key=lambda s: s.get(field, 0), reverse=reverse)
    n = len(valid)
    for i, s in enumerate(valid):
        s[rank_field] = round(i / max(n - 1, 1) * 100)

    # Stocks with missing values get 50
    valid_syms = {s["symbol"] for s in valid}
    for s in stocks:
        if s["symbol"] not in valid_syms:
            s[rank_field] = 50


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_tw_number(val) -> float | None:
    """Parse TWSE/TPEX number strings (may contain commas, +/- signs)."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        cleaned = str(val).replace(",", "").replace("+", "").replace(" ", "").strip()
        if cleaned in ("", "--", "-", "N/A", "除權息"):
            return None
        return float(cleaned)
    except (ValueError, TypeError):
        return None
