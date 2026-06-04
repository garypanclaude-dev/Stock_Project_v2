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

_snapshot_cache: dict | None = None
_snapshot_lock = threading.Lock()

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ── Screener config ───────────────────────────────────────────────────────────
SCREENER_CONFIG = {
    "min_volume": 500,
    "top_n": 20,
    "weights": {
        "momentum":  0.25,
        "value":     0.15,
        "pb_value":  0.10,
        "quality":   0.20,
        "size":      0.10,
        "low_vol":   0.10,
        "vol_price": 0.10,
    },
}

# TWSE industry code → name mapping
INDUSTRY_NAMES = {
    "01": "水泥工業", "02": "食品工業", "03": "塑膠工業", "04": "紡織纖維",
    "05": "電機機械", "06": "電器電纜", "08": "玻璃陶瓷", "09": "造紙工業",
    "10": "鋼鐵工業", "11": "橡膠工業", "12": "汽車工業", "14": "建材營造",
    "15": "航運業", "16": "觀光餐旅", "17": "金融保險", "18": "貿易百貨",
    "19": "油電燃氣", "20": "其他", "21": "化學工業", "22": "生技醫療",
    "23": "資訊服務業", "24": "半導體業", "25": "電腦及週邊設備業",
    "26": "光電業", "27": "通信網路業", "28": "電子零組件業",
    "29": "電子通路業", "30": "其他電子業", "31": "綠能環保",
    "32": "數位雲端", "33": "運動休閒", "34": "居家生活",
}


# ── Public API ────────────────────────────────────────────────────────────────

def get_screener_results() -> dict:
    snapshot = _get_snapshot()
    if snapshot is None:
        snapshot = _fetch_and_save_snapshot()
    elif _is_stale(snapshot.get("date", "")):
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


def find_industry_peers(symbol: str, top_n: int = 3) -> list[str]:
    """Find same-industry peers from TW market snapshot, sorted by volume."""
    snapshot = _get_snapshot()
    if not snapshot:
        return []

    stocks = snapshot.get("stocks", [])
    target = None
    for s in stocks:
        if s["symbol"] == symbol:
            target = s
            break

    if not target or not target.get("industry"):
        return []

    industry = target["industry"]
    candidates = [
        s for s in stocks
        if s.get("industry") == industry
        and s["symbol"] != symbol
        and s.get("volume", 0) >= 100
    ]

    candidates.sort(key=lambda s: s.get("volume", 0), reverse=True)
    return [s["symbol"] for s in candidates[:top_n]]


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
        # Step 1: get industry mapping for all listed companies
        industry_map = _fetch_industry_mapping()
        logger.info("Industry mapping: %d companies", len(industry_map))

        # Step 2: get daily prices (try today, fallback to recent trading days)
        twse_stocks = _fetch_twse_daily()
        tpex_stocks = _fetch_tpex_daily()

        # Step 3: get P/E, yield, P/B
        twse_pe = _fetch_twse_pe()
        tpex_pe = _fetch_tpex_pe()

        # Merge everything
        pe_map = {**twse_pe, **tpex_pe}
        all_stocks = twse_stocks + tpex_stocks

        for s in all_stocks:
            code = s["symbol"].replace(".TW", "")
            if code in pe_map:
                s.update(pe_map[code])
            if code in industry_map:
                s["industry"] = industry_map[code]

        all_stocks = [s for s in all_stocks if s.get("close") and s.get("volume", 0) > 0]

        snapshot = {
            "date": date.today().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "stocks": all_stocks,
        }

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
    if not snapshot_date:
        return True
    try:
        snap_date = date.fromisoformat(snapshot_date)
    except ValueError:
        return True

    today = date.today()
    now = datetime.now()

    if today.weekday() >= 5:
        last_friday = today - timedelta(days=today.weekday() - 4)
        return snap_date < last_friday

    if now.hour < 14:
        prev_day = today - timedelta(days=1)
        while prev_day.weekday() >= 5:
            prev_day -= timedelta(days=1)
        return snap_date < prev_day

    return snap_date < today


# ── Industry mapping ──────────────────────────────────────────────────────────

def _fetch_industry_mapping() -> dict[str, str]:
    """Fetch company code → industry name mapping from TWSE open data."""
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.encoding = "utf-8"
        data = resp.json()

        result = {}
        for row in data:
            values = list(row.values())
            if len(values) < 6:
                continue
            code = str(values[1]).strip()       # index 1 = company code
            industry_code = str(values[5]).strip()  # index 5 = industry code
            industry_name = INDUSTRY_NAMES.get(industry_code, f"其他({industry_code})")
            result[code] = industry_name

        return result

    except Exception as e:
        logger.error("Industry mapping fetch failed: %s", e)
        return {}


# ── TWSE daily ────────────────────────────────────────────────────────────────

def _fetch_twse_daily() -> list[dict]:
    """Fetch TWSE daily closing data. Tries today first, falls back to recent trading days."""
    for delta in range(0, 5):
        d = date.today() - timedelta(days=delta)
        if d.weekday() >= 5:
            continue
        stocks = _fetch_twse_daily_for_date(d)
        if stocks:
            return stocks
    return []


def _fetch_twse_daily_for_date(target_date: date) -> list[dict]:
    ds = target_date.strftime("%Y%m%d")
    url = f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={ds}&type=ALLBUT0999"

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        data = resp.json()

        if data.get("stat") != "OK":
            return []

        # Find the stock data table (largest table with 16 fields)
        stock_rows = []
        for table in data.get("tables", []):
            rows = table.get("data", [])
            fields = table.get("fields", [])
            if len(fields) >= 16 and len(rows) > 100:
                stock_rows = rows
                break

        if not stock_rows:
            # Fallback: try old format
            stock_rows = data.get("data9", data.get("data8", []))

        if not stock_rows:
            return []

        stocks = []
        for row in stock_rows:
            try:
                code = row[0].strip()
                name = row[1].strip()

                if not code.isdigit() or len(code) != 4:
                    continue

                close = _parse_tw_number(row[8])
                volume_shares = _parse_tw_number(row[2])
                change_str = row[10].strip() if len(row) > 10 else "0"
                change = _parse_tw_number(change_str)

                # Direction from row[9]: contains color:green for negative, color:red for positive
                direction = row[9] if len(row) > 9 else ""
                if "green" in str(direction) and change and change > 0:
                    change = -change

                if close is None or close <= 0 or volume_shares is None:
                    continue

                volume = int(volume_shares / 1000)  # shares → 張
                prev_close = close - (change or 0)
                change_pct = round((change / prev_close) * 100, 2) if change and prev_close else 0

                stocks.append({
                    "symbol": f"{code}.TW",
                    "name": name,
                    "close": close,
                    "change": change or 0,
                    "change_pct": change_pct,
                    "volume": volume,
                    "market": "TWSE",
                    "industry": "",
                })
            except (IndexError, ValueError, TypeError):
                continue

        logger.info("TWSE daily (%s): %d stocks", target_date, len(stocks))
        return stocks

    except Exception as e:
        logger.error("TWSE daily fetch failed for %s: %s", target_date, e)
        return []


# ── TPEX daily ────────────────────────────────────────────────────────────────

def _fetch_tpex_daily() -> list[dict]:
    for delta in range(0, 5):
        d = date.today() - timedelta(days=delta)
        if d.weekday() >= 5:
            continue
        stocks = _fetch_tpex_daily_for_date(d)
        if stocks:
            return stocks
    return []


def _fetch_tpex_daily_for_date(target_date: date) -> list[dict]:
    tw_date = f"{target_date.year - 1911}/{target_date.month:02d}/{target_date.day:02d}"
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
                volume_shares = _parse_tw_number(row[7])

                if close is None or close <= 0 or volume_shares is None:
                    continue

                volume = int(volume_shares / 1000)
                prev_close = close - (change or 0)
                change_pct = round((change / prev_close) * 100, 2) if change and prev_close else 0

                stocks.append({
                    "symbol": f"{code}.TW",
                    "name": name,
                    "close": close,
                    "change": change or 0,
                    "change_pct": change_pct,
                    "volume": volume,
                    "market": "TPEX",
                    "industry": "",
                })
            except (IndexError, ValueError, TypeError):
                continue

        logger.info("TPEX daily (%s): %d stocks", target_date, len(stocks))
        return stocks

    except Exception as e:
        logger.error("TPEX daily fetch failed for %s: %s", target_date, e)
        return []


# ── P/E, Yield, P/B ──────────────────────────────────────────────────────────

def _fetch_twse_pe() -> dict[str, dict]:
    for delta in range(0, 5):
        d = date.today() - timedelta(days=delta)
        if d.weekday() >= 5:
            continue
        result = _fetch_twse_pe_for_date(d)
        if result:
            return result
    return {}


def _fetch_twse_pe_for_date(target_date: date) -> dict[str, dict]:
    ds = target_date.strftime("%Y%m%d")
    url = f"https://www.twse.com.tw/exchangeReport/BWIBBU_d?response=json&date={ds}&selectType=ALL"

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        data = resp.json()

        if data.get("stat") != "OK":
            return {}

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

        logger.info("TWSE PE (%s): %d entries", target_date, len(result))
        return result

    except Exception as e:
        logger.error("TWSE PE fetch failed for %s: %s", target_date, e)
        return {}


def _fetch_tpex_pe() -> dict[str, dict]:
    for delta in range(0, 5):
        d = date.today() - timedelta(days=delta)
        if d.weekday() >= 5:
            continue
        result = _fetch_tpex_pe_for_date(d)
        if result:
            return result
    return {}


def _fetch_tpex_pe_for_date(target_date: date) -> dict[str, dict]:
    tw_date = f"{target_date.year - 1911}/{target_date.month:02d}/{target_date.day:02d}"
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

        logger.info("TPEX PE (%s): %d entries", target_date, len(result))
        return result

    except Exception as e:
        logger.error("TPEX PE fetch failed for %s: %s", target_date, e)
        return {}


# ── Multi-factor ranking ──────────────────────────────────────────────────────

def _rank_stocks(stocks: list[dict]) -> list[dict]:
    min_vol = SCREENER_CONFIG["min_volume"]
    eligible = [s for s in stocks if s.get("volume", 0) >= min_vol]

    if not eligible:
        return []

    w = SCREENER_CONFIG["weights"]

    _assign_percentile(eligible, "change_pct", "momentum_rank", reverse=False)
    _assign_percentile(eligible, "pe", "value_rank", reverse=True)
    _assign_percentile(eligible, "pb", "pb_value_rank", reverse=True)
    _assign_percentile(eligible, "yield_pct", "quality_rank", reverse=False)
    _assign_percentile(eligible, "volume", "size_rank", reverse=False)

    for s in eligible:
        s["_abs_change"] = abs(s.get("change_pct", 0))
    _assign_percentile(eligible, "_abs_change", "low_vol_rank", reverse=True)

    for s in eligible:
        chg = s.get("change_pct", 0)
        vol = s.get("volume", 0)
        s["_vol_price"] = chg * (vol ** 0.5) if chg > 0 else chg * (vol ** 0.3)
    _assign_percentile(eligible, "_vol_price", "vol_price_rank", reverse=False)

    for s in eligible:
        s["score"] = round(
            s.get("momentum_rank", 50) * w["momentum"]
            + s.get("value_rank", 50) * w["value"]
            + s.get("pb_value_rank", 50) * w["pb_value"]
            + s.get("quality_rank", 50) * w["quality"]
            + s.get("size_rank", 50) * w["size"]
            + s.get("low_vol_rank", 50) * w["low_vol"]
            + s.get("vol_price_rank", 50) * w["vol_price"]
        )

    eligible.sort(key=lambda s: s["score"], reverse=True)

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
                "pb_value": s.get("pb_value_rank", 0),
                "quality": s.get("quality_rank", 0),
                "size": s.get("size_rank", 0),
                "low_vol": s.get("low_vol_rank", 0),
                "vol_price": s.get("vol_price_rank", 0),
            },
        })

    return result


def _assign_percentile(stocks: list[dict], field: str, rank_field: str, reverse: bool = False):
    valid = [s for s in stocks if s.get(field) is not None]
    if not valid:
        for s in stocks:
            s[rank_field] = 50
        return

    valid.sort(key=lambda s: s.get(field, 0), reverse=reverse)
    n = len(valid)
    for i, s in enumerate(valid):
        s[rank_field] = round(i / max(n - 1, 1) * 100)

    valid_syms = {s["symbol"] for s in valid}
    for s in stocks:
        if s["symbol"] not in valid_syms:
            s[rank_field] = 50


def _parse_tw_number(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        cleaned = str(val).replace(",", "").replace("+", "").replace(" ", "").strip()
        if cleaned in ("", "--", "-", "N/A", "除權息", "0.00"):
            return None
        return float(cleaned)
    except (ValueError, TypeError):
        return None
