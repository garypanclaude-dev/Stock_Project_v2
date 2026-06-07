"""
Taiwan stock market data layer.

Responsibilities (separation of concerns):
  - fetch_for_date(d): pure I/O — pull TWSE/TPEX data for a single date
  - fetch_industry_mapping(): pure I/O — pull company-industry mapping
  - get_screener_results(): business logic — rank stocks from DB
  - find_industry_peers(symbol): business logic — peer lookup from DB

All storage goes through stock_fetcher.tw_db (SQLite).
Multi-day factors (momentum, MA, volatility) are computed from historical data.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, date, timedelta

import requests

from . import tw_db

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# Polite delay between API calls to avoid IP throttling
API_DELAY_SECONDS = 0.5

# ── Screener config ───────────────────────────────────────────────────────────
SCREENER_CONFIG = {
    "min_volume": 500,
    "top_n": 20,
    "weights": {
        "momentum_5d":  0.15,
        "momentum_20d": 0.15,
        "value":        0.15,
        "pb_value":     0.10,
        "quality":      0.15,
        "volume_ratio": 0.10,
        "ma_trend":     0.10,
        "low_vol":      0.10,
    },
}

# TWSE/TPEX industry code → name mapping (shared across both markets)
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
    "35": "其他電子業(35)", "36": "其他電子業(36)",
    "37": "其他電子業(37)", "38": "其他電子業(38)",
}


# ── Public API ────────────────────────────────────────────────────────────────

def get_screener_results() -> dict:
    """Read latest snapshot from DB and rank stocks with multi-day factors."""
    snapshot = tw_db.get_latest_snapshot()
    if not snapshot:
        return {"last_updated": None, "total_stocks": 0, "top_picks": []}

    ranked = _rank_stocks_with_history(snapshot)
    latest_date = tw_db.get_latest_date()

    return {
        "last_updated": f"{latest_date}T00:00:00" if latest_date else None,
        "total_stocks": len(snapshot),
        "top_picks": ranked[:SCREENER_CONFIG["top_n"]],
    }


def find_industry_peers(symbol: str, top_n: int = 3) -> list[str]:
    """Find same-industry peers via DB lookup."""
    return tw_db.find_peers_by_industry(symbol, top_n)


def fetch_for_date(target_date: date) -> dict:
    """
    Fetch all TWSE+TPEX price + P/E data for a single date.
    Returns: { "date": ..., "prices": [...], "trading_day": bool }

    A non-trading day (weekend/holiday) returns trading_day=False with empty prices.
    Raises on network errors so caller can decide retry strategy.
    """
    if target_date.weekday() >= 5:
        logger.info("Skipping weekend: %s", target_date)
        return {"date": target_date.isoformat(), "prices": [], "trading_day": False}

    twse_prices = _fetch_twse_daily_for_date(target_date)
    time.sleep(API_DELAY_SECONDS)
    tpex_prices = _fetch_tpex_daily_for_date(target_date)
    time.sleep(API_DELAY_SECONDS)
    twse_pe = _fetch_twse_pe_for_date(target_date)
    time.sleep(API_DELAY_SECONDS)
    tpex_pe = _fetch_tpex_pe_for_date(target_date)

    pe_map = {**twse_pe, **tpex_pe}
    all_prices = twse_prices + tpex_prices

    if not all_prices:
        # Likely a holiday
        return {"date": target_date.isoformat(), "prices": [], "trading_day": False}

    # Merge P/E into prices
    enriched = []
    for p in all_prices:
        code = p["symbol"].replace(".TW", "")
        if code in pe_map:
            p.update(pe_map[code])
        p["date"] = target_date.isoformat()
        enriched.append(p)

    return {"date": target_date.isoformat(), "prices": enriched, "trading_day": True}


def fetch_industry_mapping() -> dict[str, dict]:
    """
    Pull company code → {name, industry, market} from TWSE + TPEX open data.
    Returns dict keyed by 4-digit code. Market is "TWSE" (上市) or "TPEX" (上櫃).
    """
    result: dict[str, dict] = {}

    # TWSE (上市)
    try:
        resp = requests.get(
            "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
            headers=_HEADERS, timeout=15,
        )
        resp.encoding = "utf-8"
        for row in resp.json():
            values = list(row.values())
            if len(values) < 6:
                continue
            code = str(values[1]).strip()
            name = str(values[3]).strip()
            industry_code = str(values[5]).strip()
            industry_name = INDUSTRY_NAMES.get(industry_code, f"其他({industry_code})")
            result[code] = {"name": name, "industry": industry_name, "market": "TWSE"}
        logger.info("TWSE industry mapping: %d companies", sum(1 for v in result.values() if v["market"] == "TWSE"))
    except Exception as e:
        logger.error("TWSE industry mapping failed: %s", e)

    # TPEX (上櫃)
    try:
        resp = requests.get(
            "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
            headers=_HEADERS, timeout=15,
        )
        resp.encoding = "utf-8"
        for row in resp.json():
            code = str(row.get("SecuritiesCompanyCode", "")).strip()
            if not code or not code.isdigit() or len(code) != 4:
                continue
            name = str(row.get("CompanyAbbreviation", "")).strip()
            industry_code = str(row.get("SecuritiesIndustryCode", "")).strip()
            industry_name = INDUSTRY_NAMES.get(industry_code, f"其他({industry_code})")
            result[code] = {"name": name, "industry": industry_name, "market": "TPEX"}
        logger.info("TPEX industry mapping added (total: %d companies)", len(result))
    except Exception as e:
        logger.error("TPEX industry mapping failed: %s", e)

    return result


# ── TWSE daily fetcher ────────────────────────────────────────────────────────

def _fetch_twse_daily_for_date(target_date: date) -> list[dict]:
    ds = target_date.strftime("%Y%m%d")
    url = f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={ds}&type=ALLBUT0999"

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        data = resp.json()

        if data.get("stat") != "OK":
            return []

        # New format: data inside tables[].data
        stock_rows = []
        for table in data.get("tables", []):
            rows = table.get("data", [])
            fields = table.get("fields", [])
            if len(fields) >= 16 and len(rows) > 100:
                stock_rows = rows
                break

        if not stock_rows:
            stock_rows = data.get("data9", data.get("data8", []))

        return [_parse_twse_row(row) for row in stock_rows if _parse_twse_row(row)]

    except Exception as e:
        logger.error("TWSE daily fetch failed for %s: %s", target_date, e)
        return []


def _parse_twse_row(row: list) -> dict | None:
    try:
        code = row[0].strip()
        name = row[1].strip()

        if not code.isdigit() or len(code) != 4:
            return None

        close = _parse_tw_number(row[8])
        volume_shares = _parse_tw_number(row[2])
        change = _parse_tw_number(row[10]) if len(row) > 10 else None

        direction = str(row[9]) if len(row) > 9 else ""
        if "green" in direction and change and change > 0:
            change = -change

        if close is None or close <= 0 or volume_shares is None:
            return None

        volume = int(volume_shares / 1000)
        prev_close = close - (change or 0)
        change_pct = round((change / prev_close) * 100, 2) if change and prev_close else 0

        return {
            "symbol": f"{code}.TW",
            "name": name,
            "close": close,
            "change_pct": change_pct,
            "volume": volume,
            "market": "TWSE",
        }
    except (IndexError, ValueError, TypeError):
        return None


# ── TPEX daily fetcher ────────────────────────────────────────────────────────

def _fetch_tpex_daily_for_date(target_date: date) -> list[dict]:
    tw_date = f"{target_date.year - 1911}/{target_date.month:02d}/{target_date.day:02d}"
    url = (
        f"https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/"
        f"stk_wn1430_result.php?l=zh-tw&d={tw_date}&se=AL"
    )

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        data = resp.json()

        # New format: tables[0].data
        rows = []
        for table in data.get("tables", []):
            if len(table.get("fields", [])) >= 16 and len(table.get("data", [])) > 100:
                rows = table["data"]
                break

        # Fallback to legacy aaData if present
        if not rows:
            rows = data.get("aaData", [])

        return [_parse_tpex_row(row) for row in rows if _parse_tpex_row(row)]
    except Exception as e:
        logger.error("TPEX daily fetch failed for %s: %s", target_date, e)
        return []


def _parse_tpex_row(row: list) -> dict | None:
    try:
        code = row[0].strip()
        name = row[1].strip()

        if not code.isdigit() or len(code) != 4:
            return None

        close = _parse_tw_number(row[2])
        change = _parse_tw_number(row[3])
        volume_shares = _parse_tw_number(row[7])

        if close is None or close <= 0 or volume_shares is None:
            return None

        volume = int(volume_shares / 1000)
        prev_close = close - (change or 0)
        change_pct = round((change / prev_close) * 100, 2) if change and prev_close else 0

        return {
            "symbol": f"{code}.TW",
            "name": name,
            "close": close,
            "change_pct": change_pct,
            "volume": volume,
            "market": "TPEX",
        }
    except (IndexError, ValueError, TypeError):
        return None


# ── P/E fetchers ──────────────────────────────────────────────────────────────

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
        return result

    except Exception as e:
        logger.error("TWSE PE fetch failed for %s: %s", target_date, e)
        return {}


def _fetch_tpex_pe_for_date(target_date: date) -> dict[str, dict]:
    tw_date = f"{target_date.year - 1911}/{target_date.month:02d}/{target_date.day:02d}"
    url = (
        f"https://www.tpex.org.tw/web/stock/aftertrading/peratio_analysis/"
        f"pera_result.php?l=zh-tw&d={tw_date}&type=ALL"
    )

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        data = resp.json()

        # New format: tables[0].data with 8 fields
        # [0]code [1]name [2]pe [3]yield [4]year [5]dividend [6]pb [7]quarter
        rows = []
        for table in data.get("tables", []):
            if len(table.get("data", [])) > 100:
                rows = table["data"]
                break

        if not rows:
            rows = data.get("aaData", [])

        result = {}
        for row in rows:
            try:
                code = row[0].strip()
                result[code] = {
                    "pe": _parse_tw_number(row[2]),
                    "yield_pct": _parse_tw_number(row[3]),
                    "pb": _parse_tw_number(row[6]) if len(row) > 6 else None,
                }
            except (IndexError, ValueError):
                continue
        return result

    except Exception as e:
        logger.error("TPEX PE fetch failed for %s: %s", target_date, e)
        return {}


# ── Multi-day factor calculation ──────────────────────────────────────────────

def _compute_multi_day_factors(symbol: str) -> dict:
    """
    Compute factors that require historical data:
      - momentum_5d, momentum_20d
      - ma5, ma20, ma_trend (price > MA5 > MA20)
      - volume_ratio (today / 20d avg)
      - volatility_20d (std of change_pct)
    """
    history = tw_db.get_history(symbol, days=25)  # need at least 20 days
    if len(history) < 2:
        return {}

    # history is newest first; reverse for chronological
    history = list(reversed(history))
    closes = [h["close"] for h in history if h["close"] is not None]
    volumes = [h["volume"] for h in history if h["volume"] is not None]
    changes = [h["change_pct"] for h in history if h["change_pct"] is not None]

    result = {}

    # Momentum
    if len(closes) >= 6:
        result["momentum_5d"] = round((closes[-1] / closes[-6] - 1) * 100, 2)
    if len(closes) >= 21:
        result["momentum_20d"] = round((closes[-1] / closes[-21] - 1) * 100, 2)

    # Moving averages
    if len(closes) >= 5:
        ma5 = sum(closes[-5:]) / 5
        result["ma5"] = round(ma5, 2)
    if len(closes) >= 20:
        ma20 = sum(closes[-20:]) / 20
        result["ma20"] = round(ma20, 2)

    # MA trend score (0/50/100): price > MA5 > MA20 = bullish alignment
    if "ma5" in result and "ma20" in result:
        price = closes[-1]
        if price > result["ma5"] > result["ma20"]:
            result["ma_trend"] = 100
        elif price < result["ma5"] < result["ma20"]:
            result["ma_trend"] = 0
        else:
            result["ma_trend"] = 50

    # Volume ratio (latest / 20d avg, excluding latest)
    if len(volumes) >= 21:
        avg_vol = sum(volumes[-21:-1]) / 20
        if avg_vol > 0:
            result["volume_ratio"] = round(volumes[-1] / avg_vol, 2)

    # 20-day volatility (std dev of change_pct)
    if len(changes) >= 20:
        recent = changes[-20:]
        mean = sum(recent) / len(recent)
        variance = sum((x - mean) ** 2 for x in recent) / len(recent)
        result["volatility_20d"] = round(variance ** 0.5, 2)

    return result


# ── Multi-factor ranking ──────────────────────────────────────────────────────

def _rank_stocks_with_history(snapshot: list[dict]) -> list[dict]:
    min_vol = SCREENER_CONFIG["min_volume"]
    eligible = [s for s in snapshot if s.get("volume", 0) >= min_vol]
    if not eligible:
        return []

    # Enrich each stock with multi-day factors
    for s in eligible:
        s.update(_compute_multi_day_factors(s["symbol"]))

    w = SCREENER_CONFIG["weights"]

    # Assign percentile ranks
    _assign_percentile(eligible, "momentum_5d", "_rank_m5", reverse=False)
    _assign_percentile(eligible, "momentum_20d", "_rank_m20", reverse=False)
    _assign_percentile(eligible, "pe", "_rank_value", reverse=True)
    _assign_percentile(eligible, "pb", "_rank_pb", reverse=True)
    _assign_percentile(eligible, "yield_pct", "_rank_quality", reverse=False)
    _assign_percentile(eligible, "volume_ratio", "_rank_volratio", reverse=False)
    _assign_percentile(eligible, "ma_trend", "_rank_ma", reverse=False)
    _assign_percentile(eligible, "volatility_20d", "_rank_lowvol", reverse=True)

    # Composite score
    for s in eligible:
        s["score"] = round(
            s.get("_rank_m5", 50)       * w["momentum_5d"]
            + s.get("_rank_m20", 50)    * w["momentum_20d"]
            + s.get("_rank_value", 50)  * w["value"]
            + s.get("_rank_pb", 50)     * w["pb_value"]
            + s.get("_rank_quality", 50)* w["quality"]
            + s.get("_rank_volratio",50)* w["volume_ratio"]
            + s.get("_rank_ma", 50)     * w["ma_trend"]
            + s.get("_rank_lowvol", 50) * w["low_vol"]
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
                "momentum_5d":  s.get("_rank_m5", 0),
                "momentum_20d": s.get("_rank_m20", 0),
                "value":        s.get("_rank_value", 0),
                "pb_value":     s.get("_rank_pb", 0),
                "quality":      s.get("_rank_quality", 0),
                "volume_ratio": s.get("_rank_volratio", 0),
                "ma_trend":     s.get("_rank_ma", 0),
                "low_vol":      s.get("_rank_lowvol", 0),
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


# ── Helpers ───────────────────────────────────────────────────────────────────

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
