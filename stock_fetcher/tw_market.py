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


# ── Incremental update (shared by CLI and API) ────────────────────────────────

def _incremental_extended_update(dates: list[date], today: date) -> None:
    """Best-effort fetch of institutional / revenue / TDCC for incremental updates."""
    existing_inst = tw_db.get_institutional_dates()
    for d in dates:
        if d.isoformat() not in existing_inst:
            try:
                result = fetch_institutional_for_date(d)
                if result["trading_day"] and result["records"]:
                    tw_db.upsert_institutional_trading(result["records"])
            except Exception:
                pass

    try:
        rev = fetch_monthly_revenue()
        if rev:
            tw_db.upsert_monthly_revenue(rev)
    except Exception:
        pass

    existing_sh = tw_db.get_shareholder_dates()
    days_since_friday = (today.weekday() - 4) % 7
    latest_friday = today - timedelta(days=days_since_friday)
    if latest_friday.isoformat() not in existing_sh:
        try:
            records = fetch_shareholder_distribution(latest_friday)
            if records:
                tw_db.upsert_shareholder_concentration(records)
        except Exception:
            pass


def run_incremental_update() -> dict:
    """Fetch trading days from the DB's latest date + 1 up to today.

    Designed for non-blocking calls from the web API. Skips weekends/holidays
    automatically. Per-day errors are isolated so a single failure doesn't
    abort the whole batch.

    Returns
    -------
    dict with keys:
      - dates_attempted   : int    number of trading days inspected
      - success           : int    days successfully written to DB
      - skipped           : int    non-trading days / empty payloads
      - failed            : list[str]  ISO dates that failed (for retry)
      - latest_date       : str | None  newest date in DB after update
      - bootstrap_required: bool   True if DB is empty (refuse to bootstrap)
    """
    today = date.today()
    latest = tw_db.get_latest_date()

    if latest is None:
        return {
            "dates_attempted": 0, "success": 0, "skipped": 0, "failed": [],
            "latest_date": None, "bootstrap_required": True,
        }

    start = datetime.strptime(latest, "%Y-%m-%d").date() + timedelta(days=1)
    if start > today:
        return {
            "dates_attempted": 0, "success": 0, "skipped": 0, "failed": [],
            "latest_date": latest, "bootstrap_required": False,
        }

    dates = tw_db.list_trading_days(start, today)
    success = 0
    skipped = 0
    failed: list[str] = []

    for d in dates:
        try:
            result = fetch_for_date(d)
            if not result["trading_day"] or not result["prices"]:
                skipped += 1
                continue
            tw_db.upsert_daily_prices(result["prices"])
            success += 1
        except Exception as exc:
            logger.error("Incremental update failed for %s: %s", d, exc)
            failed.append(d.isoformat())

    # Extended data: institutional + revenue + TDCC (best-effort)
    _incremental_extended_update(dates, today)

    return {
        "dates_attempted": len(dates),
        "success": success,
        "skipped": skipped,
        "failed": failed,
        "latest_date": tw_db.get_latest_date(),
        "bootstrap_required": False,
    }

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# Polite delay between API calls to avoid IP throttling
API_DELAY_SECONDS = 0.5

# ── Screener config ───────────────────────────────────────────────────────────
# v7.1: 14-factor model. Tech 50% / Chip 35% / Fund 15%.
# Replaced KD absolute-score with kd_cross (golden cross detection).
# Added tangled_ma (MA convergence). Replaced pe_percentile with revenue_mom.
SCREENER_CONFIG = {
    "min_volume": 500,
    "top_n": 20,
    "weights": {
        # 技術面 (technicals) — 50%
        "bb_squeeze":           0.08,
        "volume_breakout":      0.08,
        "box_breakout":         0.07,
        "squeeze_volume":       0.06,
        "avwap_dev":            0.05,
        "breakout":             0.05,
        "tangled_ma":           0.05,
        "kd_cross":             0.04,
        "liquidity_sweep":      0.02,
        # 籌碼面 (chipflow) — 35%
        "trust_net_5d":         0.12,
        "inst_volume_ratio":    0.07,
        "foreign_net_5d":       0.06,
        "trust_streak":         0.06,
        "foreign_streak":       0.04,
        # 基本面 (fundamentals) — 15%
        "revenue_yoy":          0.10,
        "revenue_mom":          0.05,
    },
}

# Yield stability — coefficient of variation over 60d (lower = more stable)
YIELD_STABILITY_LOOKBACK = 60

# Pattern factor scoring (within screener)
PATTERN_FACTOR_LOOKBACK = 10        # scan last 10 bars
PATTERN_FACTOR_BEARISH_OVERRIDE = 30  # any bearish in window → score
PATTERN_FACTOR_BULLISH_SCORES = {
    0: 50,    # no bullish patterns → neutral
    1: 70,
    2: 85,
}
PATTERN_FACTOR_BULLISH_DEFAULT = 95  # 3 or more

# OBV trend (price vs OBV slope over OBV_FACTOR_LOOKBACK days) → score
OBV_FACTOR_LOOKBACK = 5
OBV_FACTOR_SCORES = {
    "rising":            80,
    "divergence_bull":   70,
    "neutral":           50,
    "divergence_bear":   30,
    "falling":           20,
}

# MA 4-state → score (replaces old binary ma_trend)
MA_4STATE_SCORES = {
    "bullish_alignment": 100,
    "tangled":           50,
    "neutral":           50,
    "bearish_alignment": 0,
}
MA_TANGLED_THRESHOLD = 0.03  # spread/mean < 3% → tangled

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

    # Merge P/E into prices (date already attached by underlying fetchers)
    for p in all_prices:
        code = p["symbol"].replace(".TW", "")
        if code in pe_map:
            p.update(pe_map[code])

    return {"date": target_date.isoformat(), "prices": all_prices, "trading_day": True}


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

        iso = target_date.isoformat()
        results = []
        for row in stock_rows:
            parsed = _parse_twse_row(row)
            if parsed:
                parsed["date"] = iso
                results.append(parsed)
        return results

    except Exception as e:
        logger.error("TWSE daily fetch failed for %s: %s", target_date, e)
        return []


def _parse_twse_row(row: list) -> dict | None:
    """Parse TWSE MI_INDEX row.

    Standard 16-field format:
      [0] code, [1] name, [2] volume_shares, [3] trade_count, [4] turnover,
      [5] open, [6] high, [7] low, [8] close, [9] direction, [10] change,
      [11..15] bid/ask/PE etc.
    """
    try:
        code = row[0].strip()
        name = row[1].strip()

        if not code.isdigit() or len(code) != 4:
            return None

        open_p = _parse_tw_number(row[5]) if len(row) > 5 else None
        high   = _parse_tw_number(row[6]) if len(row) > 6 else None
        low    = _parse_tw_number(row[7]) if len(row) > 7 else None
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
            "open": open_p,
            "high": high,
            "low": low,
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

        iso = target_date.isoformat()
        results = []
        for row in rows:
            parsed = _parse_tpex_row(row)
            if parsed:
                parsed["date"] = iso
                results.append(parsed)
        return results
    except Exception as e:
        logger.error("TPEX daily fetch failed for %s: %s", target_date, e)
        return []


def _parse_tpex_row(row: list) -> dict | None:
    """Parse TPEX otc_quotes row.

    Standard 16-field format:
      [0] code, [1] name, [2] close, [3] change, [4] open, [5] high, [6] low,
      [7] volume_shares, [8] turnover, [9] trade_count, [10..] bid/ask etc.
    """
    try:
        code = row[0].strip()
        name = row[1].strip()

        if not code.isdigit() or len(code) != 4:
            return None

        close = _parse_tw_number(row[2])
        change = _parse_tw_number(row[3])
        open_p = _parse_tw_number(row[4]) if len(row) > 4 else None
        high   = _parse_tw_number(row[5]) if len(row) > 5 else None
        low    = _parse_tw_number(row[6]) if len(row) > 6 else None
        volume_shares = _parse_tw_number(row[7])

        if close is None or close <= 0 or volume_shares is None:
            return None

        volume = int(volume_shares / 1000)
        prev_close = close - (change or 0)
        change_pct = round((change / prev_close) * 100, 2) if change and prev_close else 0

        return {
            "symbol": f"{code}.TW",
            "name": name,
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "change_pct": change_pct,
            "volume": volume,
            "market": "TPEX",
        }
    except (IndexError, ValueError, TypeError):
        return None


# ── P/E fetchers ──────────────────────────────────────────────────────────────

def _fetch_twse_pe_for_date(target_date: date) -> dict[str, dict]:
    """Fetch TWSE BWIBBU_d (yield / PE / PB) for a date.

    Standard 8-field response format:
      [0] code, [1] name, [2] close, [3] yield_pct, [4] dividend_year(民國),
      [5] pe, [6] pb, [7] report_period
    """
    ds = target_date.strftime("%Y%m%d")
    url = f"https://www.twse.com.tw/exchangeReport/BWIBBU_d?response=json&date={ds}&selectType=ALL"

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        data = resp.json()
        if data.get("stat") != "OK":
            return {}

        # Newer format may put rows under tables[*]; fall back to legacy "data"
        rows: list = []
        for table in data.get("tables", []):
            if len(table.get("data", [])) > 100:
                rows = table["data"]
                break
        if not rows:
            rows = data.get("data", [])

        result = {}
        for row in rows:
            try:
                code = row[0].strip()
                result[code] = {
                    "pe":        _parse_tw_number(row[5]) if len(row) > 5 else None,
                    "yield_pct": _parse_tw_number(row[3]) if len(row) > 3 else None,
                    "pb":        _parse_tw_number(row[6]) if len(row) > 6 else None,
                }
            except (IndexError, ValueError):
                continue
        return result

    except Exception as e:
        logger.error("TWSE PE fetch failed for %s: %s", target_date, e)
        return {}


def _fetch_tpex_pe_for_date(target_date: date) -> dict[str, dict]:
    """Fetch TPEX peratio (PE / dividend / yield / PB) for a date.

    Standard 8-field response format:
      [0] code, [1] name, [2] pe, [3] dividend_per_share, [4] dividend_year(民國),
      [5] yield_pct, [6] pb, [7] report_period
    """
    tw_date = f"{target_date.year - 1911}/{target_date.month:02d}/{target_date.day:02d}"
    url = (
        f"https://www.tpex.org.tw/web/stock/aftertrading/peratio_analysis/"
        f"pera_result.php?l=zh-tw&d={tw_date}&type=ALL"
    )

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        data = resp.json()

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
                code = str(row[0]).strip()
                result[code] = {
                    "pe":        _parse_tw_number(row[2]) if len(row) > 2 else None,
                    "yield_pct": _parse_tw_number(row[5]) if len(row) > 5 else None,
                    "pb":        _parse_tw_number(row[6]) if len(row) > 6 else None,
                }
            except (IndexError, ValueError):
                continue
        return result

    except Exception as e:
        logger.error("TPEX PE fetch failed for %s: %s", target_date, e)
        return {}


# ── Institutional trading fetchers (三大法人買賣超) ──────────────────────────

def fetch_institutional_for_date(target_date: date) -> dict:
    """Fetch TWSE + TPEX institutional trading for a single date.

    Returns: { "date": ..., "records": [...], "trading_day": bool }
    """
    if target_date.weekday() >= 5:
        return {"date": target_date.isoformat(), "records": [], "trading_day": False}

    twse = _fetch_twse_institutional(target_date)
    time.sleep(API_DELAY_SECONDS)
    tpex = _fetch_tpex_institutional(target_date)

    all_records = twse + tpex
    if not all_records:
        return {"date": target_date.isoformat(), "records": [], "trading_day": False}

    return {"date": target_date.isoformat(), "records": all_records, "trading_day": True}


def _fetch_twse_institutional(target_date: date) -> list[dict]:
    """Fetch TWSE T86: 三大法人買賣超日報（上市個股）."""
    ds = target_date.strftime("%Y%m%d")
    url = (
        f"https://www.twse.com.tw/rwd/zh/fund/T86"
        f"?date={ds}&selectType=ALLBUT0999&response=json"
    )

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        data = resp.json()

        if data.get("stat") != "OK":
            return []

        rows = data.get("data", [])
        if not rows:
            for table in data.get("tables", []):
                if len(table.get("data", [])) > 100:
                    rows = table["data"]
                    break

        iso = target_date.isoformat()
        results = []
        for row in rows:
            parsed = _parse_twse_institutional_row(row)
            if parsed:
                parsed["date"] = iso
                results.append(parsed)

        logger.info("TWSE institutional: %d records for %s", len(results), target_date)
        return results

    except Exception as e:
        logger.error("TWSE institutional fetch failed for %s: %s", target_date, e)
        return []


def _parse_twse_institutional_row(row: list) -> dict | None:
    """Parse TWSE T86 row.

    Fields: [0] code, [1] name,
            [2] foreign_buy, [3] foreign_sell, [4] foreign_net,
            [5] foreign_dealer_buy, [6] foreign_dealer_sell, [7] foreign_dealer_net,
            [8] trust_buy, [9] trust_sell, [10] trust_net,
            [11] dealer_net, [12] dealer_self_buy, [13] dealer_self_sell, [14] dealer_self_net,
            [15] dealer_hedge_buy, [16] dealer_hedge_sell, [17] dealer_hedge_net,
            [18] total_net
    """
    try:
        code = str(row[0]).strip()
        if not code.isdigit() or len(code) != 4:
            return None

        return {
            "symbol": f"{code}.TW",
            "foreign_buy":  _parse_tw_int(row[2]),
            "foreign_sell": _parse_tw_int(row[3]),
            "foreign_net":  _parse_tw_int(row[4]),
            "trust_buy":    _parse_tw_int(row[8]),
            "trust_sell":   _parse_tw_int(row[9]),
            "trust_net":    _parse_tw_int(row[10]),
            "dealer_net":   _parse_tw_int(row[11]),
            "total_net":    _parse_tw_int(row[18]) if len(row) > 18 else None,
        }
    except (IndexError, ValueError, TypeError):
        return None


def _fetch_tpex_institutional(target_date: date) -> list[dict]:
    """Fetch TPEX 三大法人買賣超日報（上櫃個股）."""
    tw_date = f"{target_date.year - 1911}/{target_date.month:02d}/{target_date.day:02d}"
    url = (
        f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/"
        f"3itrade_hedge_result.php?l=zh-tw&d={tw_date}&se=EW&t=D"
    )

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        data = resp.json()

        rows = data.get("aaData", [])
        if not rows:
            for table in data.get("tables", []):
                if len(table.get("data", [])) > 100:
                    rows = table["data"]
                    break

        iso = target_date.isoformat()
        results = []
        for row in rows:
            parsed = _parse_tpex_institutional_row(row)
            if parsed:
                parsed["date"] = iso
                results.append(parsed)

        logger.info("TPEX institutional: %d records for %s", len(results), target_date)
        return results

    except Exception as e:
        logger.error("TPEX institutional fetch failed for %s: %s", target_date, e)
        return []


def _parse_tpex_institutional_row(row: list) -> dict | None:
    """Parse TPEX 3itrade row（共 24 欄，與 TWSE T86 欄位順序不同）.

    Fields: [0] code, [1] name,
            [2-4]   外資不含自營：buy / sell / net
            [5-7]   外資自營商：buy / sell / net
            [8-10]  外資合計：buy / sell / net
            [11-13] 投信：buy / sell / net
            [14-16] 自營商(自行買賣)：buy / sell / net
            [17-19] 自營商(避險)：buy / sell / net
            [20-22] 自營商合計：buy / sell / net
            [23]    三大法人買賣超合計

    foreign_net 採「不含自營」(row[4]) 以對齊 TWSE T86 的慣例。
    """
    try:
        code = str(row[0]).strip()
        if not code.isdigit() or len(code) != 4:
            return None

        return {
            "symbol":       f"{code}.TW",
            "foreign_buy":  _parse_tw_int(row[2]),
            "foreign_sell": _parse_tw_int(row[3]),
            "foreign_net":  _parse_tw_int(row[4]),
            "trust_buy":    _parse_tw_int(row[11]),
            "trust_sell":   _parse_tw_int(row[12]),
            "trust_net":    _parse_tw_int(row[13]),
            "dealer_net":   _parse_tw_int(row[22]) if len(row) > 22 else None,
            "total_net":    _parse_tw_int(row[23]) if len(row) > 23 else None,
        }
    except (IndexError, ValueError, TypeError):
        return None


# ── Monthly revenue fetchers (月營收) ────────────────────────────────────────

def fetch_monthly_revenue() -> list[dict]:
    """Fetch the latest monthly revenue for all listed + OTC companies.

    Uses TWSE/TPEX opendata APIs which provide the most recent period.
    Returns list of dicts with: symbol, year_month, revenue, revenue_yoy, etc.
    """
    twse = _fetch_twse_opendata_revenue()
    time.sleep(API_DELAY_SECONDS)
    tpex = _fetch_tpex_opendata_revenue()

    return twse + tpex


def _fetch_twse_opendata_revenue() -> list[dict]:
    """Fetch TWSE opendata t187ap05_L (上市公司月營收).

    Fields: 出表日期, 資料年月, 公司代號, 公司名稱, 產業別,
            營業收入-當月營收, 營業收入-上月營收, 營業收入-去年當月營收,
            營業收入-上月比較增減(%), 營業收入-去年同月增減(%),
            累計營業收入-當月累計營收, 累計營業收入-去年累計營收,
            累計營業收入-前期比較增減(%), 備註
    """
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        resp.encoding = "utf-8"
        data = resp.json()

        if not isinstance(data, list) or not data:
            return []

        return _parse_opendata_revenue(data, ".TW")

    except Exception as e:
        logger.error("TWSE opendata revenue fetch failed: %s", e)
        return []


def _fetch_tpex_opendata_revenue() -> list[dict]:
    """Fetch TPEX opendata mopsfin_t187ap05_O (上櫃公司月營收)."""
    url = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        resp.encoding = "utf-8"
        data = resp.json()

        if not isinstance(data, list) or not data:
            return []

        return _parse_opendata_revenue(data, ".TW")

    except Exception as e:
        logger.error("TPEX opendata revenue fetch failed: %s", e)
        return []


def _parse_opendata_revenue(data: list[dict], suffix: str) -> list[dict]:
    """Parse TWSE/TPEX opendata monthly revenue JSON records."""
    results = []
    for row in data:
        code = str(row.get("公司代號", "")).strip()  # 公司代號
        if not code.isdigit() or len(code) != 4:
            continue

        # 資料年月 is in ROC format: "11505" → 2026-05
        ym_raw = str(row.get("資料年月", "")).strip()  # 資料年月
        if len(ym_raw) < 4:
            continue
        try:
            roc_year = int(ym_raw[:-2])
            month = int(ym_raw[-2:])
            western_year = roc_year + 1911
            year_month = f"{western_year}-{month:02d}"
        except (ValueError, IndexError):
            continue

        # 營業收入-當月營收 (千元)
        revenue = _parse_tw_int_safe(
            row.get("營業收入-當月營收", "")
        )
        if revenue is None or revenue == 0:
            continue

        # 營業收入-去年同月增減(%)
        revenue_yoy = _parse_tw_number(
            row.get("營業收入-去年同月增減(%)", "")
        )
        # 營業收入-上月比較增減(%)
        revenue_mom = _parse_tw_number(
            row.get("營業收入-上月比較增減(%)", "")
        )
        # 累計營業收入-當月累計營收
        cumulative = _parse_tw_int_safe(
            row.get("累計營業收入-當月累計營收", "")
        )
        # 累計營業收入-前期比較增減(%)
        cumulative_yoy = _parse_tw_number(
            row.get("累計營業收入-前期比較增減(%)", "")
        )

        results.append({
            "symbol": f"{code}{suffix}",
            "year_month": year_month,
            "revenue": revenue,
            "revenue_yoy": revenue_yoy,
            "revenue_mom": revenue_mom,
            "cumulative_revenue": cumulative,
            "cumulative_yoy": cumulative_yoy,
        })

    logger.info("Opendata revenue: %d records for period %s",
                len(results), results[0]["year_month"] if results else "N/A")
    return results


# ── TDCC shareholder distribution fetcher (集保中心) ─────────────────────────

# TDCC 持股分級: levels 12-15 represent holders of 400,001+ shares (≈400張+)
_TDCC_LARGE_HOLDER_LEVELS = {"12", "13", "14", "15"}
_TDCC_TOTAL_LEVEL = "17"


def fetch_shareholder_distribution(target_date: date) -> list[dict]:
    """Fetch shareholder concentration for ALL stocks on a specific date.

    TDCC opendata returns all stocks in a single bulk response.
    TDCC publishes weekly (Fridays). The API always returns the latest
    available publication regardless of the date parameter, so we extract
    the actual publication date from the response ``資料日期`` field.

    Returns list of dicts: {symbol, date, large_holder_pct, total_holders}.
    The ``date`` value is the real TDCC publication date, not ``target_date``.
    """
    ds = target_date.strftime("%Y%m%d")
    url = f"https://openapi.tdcc.com.tw/v1/opendata/1-5?date={ds}"

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=120)
        data = resp.json()

        if not data or not isinstance(data, list):
            return []

        # Extract actual publication date from the first record.
        # The field name has a BOM prefix (﻿資料日期) in TDCC responses.
        raw_date_str = ""
        for key in data[0]:
            if "資料日期" in key:
                raw_date_str = str(data[0][key]).strip()
                break
        if len(raw_date_str) == 8:
            actual_date = date(
                int(raw_date_str[:4]),
                int(raw_date_str[4:6]),
                int(raw_date_str[6:8]),
            )
        else:
            actual_date = target_date

        # Group by symbol
        by_symbol: dict[str, list[dict]] = {}
        for row in data:
            code = str(row.get("證券代號", "")).strip()
            if not code.isdigit() or len(code) != 4:
                continue
            by_symbol.setdefault(code, []).append(row)

        results = []
        for code, rows in by_symbol.items():
            total_shares = 0
            large_shares = 0
            total_holders = 0

            for r in rows:
                level = str(r.get("持股分級", "")).strip()
                shares = _parse_tw_int_safe(str(r.get("股數", "0")))
                holders = _parse_tw_int_safe(str(r.get("人數", "0")))

                if level == _TDCC_TOTAL_LEVEL:
                    total_shares = shares or 0
                    total_holders = holders or 0
                elif level in _TDCC_LARGE_HOLDER_LEVELS:
                    large_shares += (shares or 0)

            if total_shares == 0:
                continue

            results.append({
                "symbol": f"{code}.TW",
                "date": actual_date.isoformat(),
                "large_holder_pct": round(large_shares / total_shares * 100, 2),
                "total_holders": total_holders,
            })

        logger.info("TDCC shareholder: %d stocks for %s (requested %s)",
                     len(results), actual_date, target_date)
        return results

    except Exception as e:
        logger.error("TDCC fetch failed for %s: %s", target_date, e)
        return []


# ── Number parsing helpers ───────────────────────────────────────────────────

def _parse_tw_int(val) -> int | None:
    """Parse a TW-format integer (with commas, +/- signs)."""
    n = _parse_tw_number(val)
    return int(n) if n is not None else None


def _parse_tw_int_safe(val) -> int | None:
    """Parse integer, returning None on failure."""
    try:
        cleaned = str(val).replace(",", "").replace(" ", "").strip()
        if not cleaned or cleaned in ("--", "-", "N/A"):
            return None
        return int(float(cleaned))
    except (ValueError, TypeError):
        return None


# ── Multi-day factor calculation ──────────────────────────────────────────────

def _compute_multi_day_factors(symbol: str, *, history: list[dict] | None = None) -> dict:
    """Compute price-based screener factors from OHLCV history (v7.0).

    Factors: kd_cross, breakout, squeeze_volume, bb_squeeze,
             volume_breakout, box_breakout, avwap_dev, liquidity_sweep,
             tangled_ma, ma200, avg_vol_5d.
    """
    if history is None:
        history = tw_db.get_history(symbol, days=200)
    if len(history) < 2:
        return {}

    history = list(reversed(history))
    closes  = [h["close"]  for h in history if h["close"]  is not None]
    volumes = [h["volume"] for h in history if h["volume"] is not None]
    changes = [h["change_pct"] for h in history if h["change_pct"] is not None]
    full_rows = [h for h in history if all(h.get(k) is not None for k in ("open", "high", "low", "close", "volume"))]

    result = {}

    # ── MA200 （保留計算供其他模組查詢；v7.3 起不再做為 ML 特徵或前置過濾）─
    if len(closes) >= 200:
        result["ma200"] = sum(closes[-200:]) / 200

    # ── KD Cross: golden cross near relative low → high score ──────────
    if len(full_rows) >= 9:
        from .indicators import stochastic_kd
        kd = stochastic_kd(
            [r["high"] for r in full_rows],
            [r["low"]  for r in full_rows],
            [r["close"] for r in full_rows],
        )
        k_vals = kd["k"]
        d_vals = kd["d"]
        k_now = k_vals[-1] if k_vals and k_vals[-1] is not None else None
        k_prev = k_vals[-2] if len(k_vals) >= 2 and k_vals[-2] is not None else None
        d_now = d_vals[-1] if d_vals and d_vals[-1] is not None else None
        d_prev = d_vals[-2] if len(d_vals) >= 2 and d_vals[-2] is not None else None
        if all(v is not None for v in (k_now, k_prev, d_now, d_prev)):
            has_cross = k_prev < d_prev and k_now >= d_now
            if has_cross and k_now < 30:
                result["kd_cross"] = 100
            elif has_cross and k_now < 50:
                result["kd_cross"] = 80
            elif has_cross:
                result["kd_cross"] = 50
            else:
                result["kd_cross"] = 0
        result["kd_value"] = k_now

    # ── Breakout: (close - 20d high) / 20d high × 100 ───────────────────
    if len(closes) >= 20:
        high_20d = max(closes[-20:])
        if high_20d > 0:
            result["breakout"] = round((closes[-1] - high_20d) / high_20d * 100, 2)
            result["near_breakout"] = round(max(-5, min(result["breakout"], 3)), 2)

    # ── Squeeze & Volume ─────────────────────────────────────────────────
    avg_vol_20 = 0.0
    if len(changes) >= 20 and len(volumes) >= 21:
        recent_20 = changes[-20:]
        recent_5 = changes[-5:]
        mean_20 = sum(recent_20) / len(recent_20)
        mean_5 = sum(recent_5) / len(recent_5)
        std_20 = (sum((x - mean_20) ** 2 for x in recent_20) / len(recent_20)) ** 0.5
        std_5 = (sum((x - mean_5) ** 2 for x in recent_5) / len(recent_5)) ** 0.5

        avg_vol_20 = sum(volumes[-21:-1]) / 20
        vol_ratio = volumes[-1] / avg_vol_20 if avg_vol_20 > 0 else 1.0

        squeeze = max(0, (std_20 - std_5) / std_20) if std_20 > 0 else 0.0
        result["squeeze_volume"] = round(squeeze * vol_ratio, 4)

    # ── Volume Breakout: today_vol / avg_vol_20d ─────────────────────────
    if len(volumes) >= 21:
        if avg_vol_20 == 0.0:
            avg_vol_20 = sum(volumes[-21:-1]) / 20
        if avg_vol_20 > 0:
            result["volume_breakout"] = round(volumes[-1] / avg_vol_20, 4)

    # ── Volume Contraction: avg_vol_5d / avg_vol_20d ──────────────────────
    if len(volumes) >= 21:
        avg_v5 = sum(volumes[-5:]) / 5
        avg_v20 = avg_vol_20 if avg_vol_20 > 0 else sum(volumes[-21:-1]) / 20
        if avg_v20 > 0:
            result["volume_contraction"] = round(avg_v5 / avg_v20, 4)

    # ── Avg Vol 5d (helper for inst_volume_ratio) ────────────────────────
    if len(volumes) >= 5:
        result["avg_vol_5d"] = sum(volumes[-5:]) / 5

    # ── BB Squeeze: bandwidth squeeze percentile within 60-day window ────
    # 60 日 lookback 對齊 10 日預測視野（Triple-Barrier MAX_HOLDING_DAYS=10）
    # 語義：100 = 今天最擠（過去 60 天 bandwidth 都 >= 今天）；0 = 今天最寬
    if len(closes) >= 20:
        from .indicators import bollinger_bands
        bb = bollinger_bands(closes, period=20, num_std=2.0)
        bandwidths = [
            (u - l) / m
            for u, m, l in zip(bb["upper"], bb["middle"], bb["lower"])
            if u is not None and m is not None and m > 0
        ]
        if bandwidths:
            lookback = bandwidths[-60:]
            current_bw = bandwidths[-1]
            wider_or_equal = sum(1 for x in lookback if x >= current_bw)
            result["bb_squeeze"] = round(wider_or_equal / len(lookback) * 100, 1)

    # ── Price Position: normalized position within 60d high-low range ────
    if len(full_rows) >= 60:
        highs_60 = [r["high"] for r in full_rows[-60:]]
        lows_60 = [r["low"] for r in full_rows[-60:]]
        high_60d = max(highs_60)
        low_60d = min(lows_60)
        rng = high_60d - low_60d
        if rng > 0:
            result["price_position"] = round((closes[-1] - low_60d) / rng, 4)

    # ── Box Breakout: break above 60-day consolidation range ─────────────
    if len(full_rows) >= 60:
        highs_60 = [r["high"] for r in full_rows[-60:]]
        lows_60 = [r["low"] for r in full_rows[-60:]]
        box_high = max(highs_60)
        box_low = min(lows_60)
        current_close = full_rows[-1]["close"]
        box_range_pct = (box_high - box_low) / current_close * 100 if current_close > 0 else 999
        if current_close >= box_high and box_range_pct > 0:
            result["box_breakout"] = round(100 / max(box_range_pct, 1), 2)
        else:
            result["box_breakout"] = 0.0

    # ── AVWAP Deviation: anchored to 60-day swing low ────────────────────
    if len(full_rows) >= 20:
        lookback = min(60, len(full_rows))
        recent = full_rows[-lookback:]
        swing_low_idx = min(range(len(recent)), key=lambda i: recent[i]["low"])
        anchor_slice = recent[swing_low_idx:]
        if len(anchor_slice) >= 2:
            cum_tp_vol = 0.0
            cum_vol = 0.0
            for r in anchor_slice:
                tp = (r["high"] + r["low"] + r["close"]) / 3
                cum_tp_vol += tp * r["volume"]
                cum_vol += r["volume"]
            if cum_vol > 0:
                avwap = cum_tp_vol / cum_vol
                result["avwap_dev"] = round((closes[-1] - avwap) / avwap * 100, 4)

    # ── Liquidity Sweep: wick below recent lows + close reclaim ──────────
    if len(full_rows) >= 6:
        today = full_rows[-1]
        preceding_lows = [r["low"] for r in full_rows[-6:-1]]
        min_preceding = min(preceding_lows)
        if today["low"] < min_preceding and today["close"] > min_preceding:
            result["liquidity_sweep"] = round(
                (today["close"] - today["low"]) / today["close"] * 100, 4
            )
        else:
            result["liquidity_sweep"] = 0.0

    # ── Tangled MA: MA5/10/20/60 spread — lower spread = more tangled ───
    if len(closes) >= 60:
        ma5 = sum(closes[-5:]) / 5
        ma10 = sum(closes[-10:]) / 10
        ma20 = sum(closes[-20:]) / 20
        ma60 = sum(closes[-60:]) / 60
        mas = [ma5, ma10, ma20, ma60]
        ma_mean = sum(mas) / 4
        if ma_mean > 0:
            spread = (max(mas) - min(mas)) / ma_mean
            result["tangled_ma"] = round(spread, 6)

    # ── OBV Divergence: normalized OBV slope minus normalized price slope ─
    if len(closes) >= 21 and len(volumes) >= 21 and len(full_rows) >= 21:
        obv = [0.0]
        for i in range(1, len(closes)):
            if closes[i] > closes[i - 1]:
                obv.append(obv[-1] + volumes[i])
            elif closes[i] < closes[i - 1]:
                obv.append(obv[-1] - volumes[i])
            else:
                obv.append(obv[-1])

        obv_20 = obv[-20:]
        price_20 = closes[-20:]

        n = len(obv_20)
        x_mean = (n - 1) / 2.0
        x_var = sum((i - x_mean) ** 2 for i in range(n))

        if x_var > 0:
            obv_mean = sum(obv_20) / n
            obv_slope = sum((i - x_mean) * (obv_20[i] - obv_mean) for i in range(n)) / x_var

            price_mean = sum(price_20) / n
            price_slope = sum((i - x_mean) * (price_20[i] - price_mean) for i in range(n)) / x_var

            obv_std = (sum((v - obv_mean) ** 2 for v in obv_20) / n) ** 0.5
            price_std = (sum((v - price_mean) ** 2 for v in price_20) / n) ** 0.5

            norm_obv = obv_slope / obv_std if obv_std > 0 else 0.0
            norm_price = price_slope / price_std if price_std > 0 else 0.0
            result["obv_divergence"] = round(norm_obv - norm_price, 4)

    return result


def _count_streak(records: list[dict], field: str) -> int:
    """Count consecutive positive/negative days for a field (newest-first)."""
    streak = 0
    for r in records:
        val = r.get(field, 0) or 0
        if val > 0 and streak >= 0:
            streak += 1
        elif val < 0 and streak <= 0:
            streak -= 1
        else:
            break
    return streak


def _compute_extended_factors(
    symbol: str,
    signal_date: str,
    *,
    inst_data: dict | None = None,
    revenue_data: dict | None = None,
    shareholder_data: dict | None = None,
) -> dict:
    """Compute factors from institutional / revenue / shareholder data (v7.0).

    Factors: foreign_net_5d, trust_net_5d, foreign_streak, trust_streak,
             revenue_yoy, revenue_mom.
    """
    result = {}

    # ── Chipflow: foreign_net_5d / trust_net_5d ──────────────────────────
    if inst_data is not None:
        sym_inst = inst_data.get(symbol, {})
        dates_5 = sorted(d for d in sym_inst if d <= signal_date)[-5:]
        if dates_5:
            result["foreign_net_5d"] = sum(sym_inst[d].get("foreign_net", 0) for d in dates_5)
            result["trust_net_5d"] = sum(sym_inst[d].get("trust_net", 0) for d in dates_5)
        # Streaks need up to 20 days
        dates_20 = sorted(d for d in sym_inst if d <= signal_date)[-20:]
        if dates_20:
            streak_records = [sym_inst[d] for d in reversed(dates_20)]
            result["foreign_streak"] = _count_streak(streak_records, "foreign_net")
            result["trust_streak"] = _count_streak(streak_records, "trust_net")
    else:
        rows = tw_db.get_institutional_history(symbol, before_date=signal_date, days=20)
        if rows:
            rows_5 = rows[:5]
            result["foreign_net_5d"] = sum(r["foreign_net"] or 0 for r in rows_5)
            result["trust_net_5d"] = sum(r["trust_net"] or 0 for r in rows_5)
            result["foreign_streak"] = _count_streak(rows, "foreign_net")
            result["trust_streak"] = _count_streak(rows, "trust_net")

    # ── Fundamentals: revenue_yoy, revenue_mom ─────────────────────────
    if revenue_data is not None:
        sym_rev = revenue_data.get(symbol, [])
        if sym_rev:
            result["revenue_yoy"] = sym_rev[-1].get("revenue_yoy")
            result["revenue_mom"] = sym_rev[-1].get("revenue_mom")
    else:
        rows = tw_db.get_latest_revenue(symbol, n=1)
        if rows:
            result["revenue_yoy"] = rows[0].get("revenue_yoy")
            result["revenue_mom"] = rows[0].get("revenue_mom")

    return result


def _lookup_factor_score(value: float, table: list[tuple], default: int) -> int:
    """Look up a value in a (upper_bound_exclusive, score) table."""
    for upper, score in table:
        if value < upper:
            return score
    return default


# ── Multi-factor ranking ──────────────────────────────────────────────────────

def _rank_stocks_with_history(
    snapshot: list[dict],
    *,
    histories: dict[str, list[dict]] | None = None,
    inst_data: dict | None = None,
    revenue_data: dict | None = None,
    shareholder_data: dict | None = None,
    result_limit: int | None = None,
    return_all: bool = False,
) -> list[dict]:
    """Rank stocks by 15-factor composite score (v7.0).

    Parameters
    ----------
    histories : optional {symbol: newest-first price list} (backtester path).
    inst_data : optional {symbol: {date: {foreign_net, trust_net, ...}}}.
    revenue_data : optional {symbol: [{year_month, revenue_yoy, ...}]}.
    shareholder_data : optional {symbol: {date: {large_holder_pct}}}.
    result_limit : optional int to override SCREENER_CONFIG["top_n"].
    return_all : if True, return ALL eligible stocks (for IC analysis).
    """
    min_vol = SCREENER_CONFIG["min_volume"]
    eligible = [s for s in snapshot if s.get("volume", 0) >= min_vol]
    if not eligible:
        return []

    signal_date = eligible[0].get("date", "")

    # Enrich each stock with price-based factors
    for s in eligible:
        sym = s["symbol"]
        if histories and sym in histories:
            s.update(_compute_multi_day_factors(sym, history=histories[sym]))
        else:
            s.update(_compute_multi_day_factors(sym))

    # Enrich with extended factors (chipflow + fundamentals)
    for s in eligible:
        s.update(_compute_extended_factors(
            s["symbol"],
            signal_date,
            inst_data=inst_data,
            revenue_data=revenue_data,
            shareholder_data=shareholder_data,
        ))

    # Compute inst_volume_ratio (needs both multi-day and extended data)
    # 單位校正：法人數值為「股」、avg_vol_5d 為「張」，需除以 1000 對齊單位
    for s in eligible:
        avg_vol = s.get("avg_vol_5d")
        fnet_lots = abs(s.get("foreign_net_5d", 0) or 0) / 1000
        tnet_lots = abs(s.get("trust_net_5d", 0) or 0) / 1000
        if avg_vol and avg_vol > 0:
            s["inst_volume_ratio"] = round((fnet_lots + tnet_lots) / (avg_vol * 5) * 100, 4)

    w = SCREENER_CONFIG["weights"]

    # ── Percentile ranks ─────────────────────────────────────────────────
    # Technical (50%)
    _assign_percentile(eligible, "bb_squeeze",      "_rank_bbsq",  reverse=False)
    _assign_percentile(eligible, "volume_breakout", "_rank_volbk", reverse=False)
    _assign_percentile(eligible, "box_breakout",    "_rank_boxbk", reverse=False)
    _assign_percentile(eligible, "squeeze_volume",  "_rank_sqvol", reverse=False)
    _assign_percentile(eligible, "avwap_dev",       "_rank_avwap", reverse=False)
    _assign_percentile(eligible, "breakout",        "_rank_bkout", reverse=False)
    _assign_percentile(eligible, "tangled_ma",      "_rank_tgma",  reverse=True)
    _assign_percentile(eligible, "kd_cross",        "_rank_kdx",   reverse=False)
    _assign_percentile(eligible, "liquidity_sweep", "_rank_liqsw", reverse=False)
    # Chipflow (35%)
    _assign_percentile(eligible, "trust_net_5d",      "_rank_tnet",  reverse=False)
    _assign_percentile(eligible, "inst_volume_ratio", "_rank_ivr",   reverse=False)
    _assign_percentile(eligible, "foreign_net_5d",    "_rank_fnet",  reverse=False)
    _assign_percentile(eligible, "trust_streak",      "_rank_tstrk", reverse=False)
    _assign_percentile(eligible, "foreign_streak",    "_rank_fstrk", reverse=False)
    # Fundamental (15%)
    _assign_percentile(eligible, "revenue_yoy",   "_rank_ryoy", reverse=False)
    _assign_percentile(eligible, "revenue_mom",   "_rank_rmom", reverse=False)

    # ── Composite score ──────────────────────────────────────────────────
    for s in eligible:
        s["score"] = round(
            # Technical (50%)
            s.get("_rank_bbsq", 50)  * w["bb_squeeze"]
            + s.get("_rank_volbk", 50) * w["volume_breakout"]
            + s.get("_rank_boxbk", 50) * w["box_breakout"]
            + s.get("_rank_sqvol", 50) * w["squeeze_volume"]
            + s.get("_rank_avwap", 50) * w["avwap_dev"]
            + s.get("_rank_bkout", 50) * w["breakout"]
            + s.get("_rank_tgma", 50)  * w["tangled_ma"]
            + s.get("_rank_kdx", 50)   * w["kd_cross"]
            + s.get("_rank_liqsw", 50) * w["liquidity_sweep"]
            # Chipflow (35%)
            + s.get("_rank_tnet", 50)  * w["trust_net_5d"]
            + s.get("_rank_ivr", 50)   * w["inst_volume_ratio"]
            + s.get("_rank_fnet", 50)  * w["foreign_net_5d"]
            + s.get("_rank_tstrk", 50) * w["trust_streak"]
            + s.get("_rank_fstrk", 50) * w["foreign_streak"]
            # Fundamental (15%)
            + s.get("_rank_ryoy", 50)  * w["revenue_yoy"]
            + s.get("_rank_rmom", 50)  * w["revenue_mom"]
        )

    eligible.sort(key=lambda s: s["score"], reverse=True)

    limit = len(eligible) if return_all else (result_limit or SCREENER_CONFIG["top_n"])
    result = []
    for rank, s in enumerate(eligible[:limit], 1):
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
                "bb_squeeze":           s.get("_rank_bbsq", 0),
                "volume_breakout":      s.get("_rank_volbk", 0),
                "box_breakout":         s.get("_rank_boxbk", 0),
                "squeeze_volume":       s.get("_rank_sqvol", 0),
                "avwap_dev":            s.get("_rank_avwap", 0),
                "breakout":             s.get("_rank_bkout", 0),
                "tangled_ma":           s.get("_rank_tgma", 0),
                "kd_cross":            s.get("_rank_kdx", 0),
                "liquidity_sweep":      s.get("_rank_liqsw", 0),
                "trust_net_5d":         s.get("_rank_tnet", 0),
                "inst_volume_ratio":    s.get("_rank_ivr", 0),
                "foreign_net_5d":       s.get("_rank_fnet", 0),
                "trust_streak":         s.get("_rank_tstrk", 0),
                "foreign_streak":       s.get("_rank_fstrk", 0),
                "revenue_yoy":          s.get("_rank_ryoy", 0),
                "revenue_mom":          s.get("_rank_rmom", 0),
            },
        })
    return result


def run_screener_with_data(
    snapshot: list[dict],
    histories: dict[str, list[dict]],
    top_n: int | None = None,
    return_all: bool = False,
    *,
    inst_data: dict | None = None,
    revenue_data: dict | None = None,
    shareholder_data: dict | None = None,
) -> list[dict]:
    """Run screener ranking with pre-loaded data.

    Public interface for the backtester — avoids DB queries by accepting
    pre-built snapshot and histories dicts.

    Parameters
    ----------
    snapshot : list of stock dicts (OHLCV + company info) for a specific date.
    histories : {symbol: newest-first price list} for factor computation.
    top_n : override default result limit (SCREENER_CONFIG["top_n"]).
    return_all : if True, return ALL eligible stocks (for IC analysis).
    inst_data : {symbol: {date: {foreign_net, trust_net, ...}}} — bulk loaded.
    revenue_data : {symbol: [{year_month, revenue_yoy, ...}]} — bulk loaded.
    shareholder_data : {symbol: {date: {large_holder_pct}}} — bulk loaded.
    """
    return _rank_stocks_with_history(
        snapshot, histories=histories, result_limit=top_n, return_all=return_all,
        inst_data=inst_data, revenue_data=revenue_data,
        shareholder_data=shareholder_data,
    )


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
