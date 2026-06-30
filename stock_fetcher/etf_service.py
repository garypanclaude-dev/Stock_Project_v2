"""
ETF 業務邏輯層：yfinance 抓取 → etf.db 同步 → 指標計算 → DCA 模擬。

對外四個主要入口：
  - sync_etf(symbol)         : 增量同步單檔 ETF 所有資料到 etf.db
  - get_list_summary()       : 列表頁需要的摘要（22 檔）
  - get_detail(symbol)       : 詳情頁完整資料
  - simulate_dca(...)        : DCA + DRIP 模擬，含 benchmark 對照

詳見 docs/dca-simulator.md §4 公式 & §5 API。
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta
from typing import Any

import yfinance as yf

from . import etf_anomaly, etf_config, etf_db
from .cache import ttl_cache

logger = logging.getLogger(__name__)

# ── TTL 設定（秒） ────────────────────────────────────────────────────────────
META_TTL_HOURS = 24
PRICE_REFRESH_HOURS = 6
HOLDINGS_TTL_DAYS = 7


# ============================================================================
# 1. 同步：yfinance → etf.db
# ============================================================================

def sync_etf(symbol: str, force: bool = False) -> dict:
    """
    增量同步 ETF 元資料、價格、配息、持股、產業到 etf.db。
    根據 docs §3.3 的 TTL 策略決定是否真的去 yfinance 抓。
    回傳 sync 摘要（哪些被刷新）。
    """
    cfg = etf_config.get_config(symbol)
    if cfg is None:
        raise ValueError(f"Unknown ETF symbol: {symbol}")

    t = yf.Ticker(symbol)
    now_iso = datetime.utcnow().isoformat(timespec="seconds")
    summary: dict[str, Any] = {"symbol": symbol, "refreshed": []}

    # ---- meta ----
    existing_meta = etf_db.get_meta(symbol)
    if force or _meta_stale(existing_meta):
        info = _safe_info(t)
        meta_row = {
            "symbol": symbol,
            "name_zh": cfg["name_zh"],
            "name_en": info.get("longName") or info.get("shortName"),
            "category": cfg["category"],
            "tracking_index": cfg.get("tracking_index"),
            "expense_ratio": cfg.get("expense_ratio"),
            "payout_frequency": cfg.get("payout_frequency"),
            "is_active": cfg.get("is_active", False),
            "fund_family": info.get("fundFamily"),
            "inception_date": _ts_to_iso(info.get("fundInceptionDate")),
            "aum": info.get("totalAssets"),
            "nav_price": info.get("navPrice") or info.get("previousClose"),
            "yield_rate": info.get("yield"),
            "currency": info.get("currency", "TWD"),
            "updated_at": now_iso,
        }
        etf_db.upsert_meta(meta_row)
        summary["refreshed"].append("meta")

    # ---- prices ----
    last_price_date = etf_db.get_latest_price_date(symbol)
    if force or _price_stale(last_price_date):
        rows = _fetch_price_rows(t, last_price_date)
        if rows:
            etf_db.upsert_prices(symbol, rows)
            summary["refreshed"].append(f"prices({len(rows)})")

    # ---- dividends ----
    last_div_date = etf_db.get_latest_dividend_date(symbol)
    if force or _div_stale(last_div_date):
        divs = _fetch_dividend_rows(t)
        # 只寫入新的部分
        new_divs = [d for d in divs if last_div_date is None or d["ex_date"] > last_div_date]
        if new_divs:
            etf_db.upsert_dividends(symbol, new_divs)
            summary["refreshed"].append(f"dividends({len(new_divs)})")
        elif not divs and last_div_date is None:
            summary["refreshed"].append("dividends(empty)")

    # ---- holdings / sectors ----
    snap = etf_db.get_holdings_snapshot_at(symbol)
    if force or _holdings_stale(snap):
        holdings_rows, sector_rows = _fetch_holdings(t)
        if holdings_rows:
            etf_db.replace_holdings(symbol, holdings_rows, now_iso)
            summary["refreshed"].append(f"holdings({len(holdings_rows)})")
        if sector_rows:
            etf_db.replace_sectors(symbol, sector_rows, now_iso)
            summary["refreshed"].append(f"sectors({len(sector_rows)})")

    return summary


def sync_all() -> list[dict]:
    """同步全部 ETF（含對照組）。第一次啟動或排程刷新用。"""
    results = []
    for sym in etf_config.list_unique_symbols():
        try:
            results.append(sync_etf(sym))
        except Exception as e:
            logger.warning("sync_etf(%s) failed: %s", sym, e)
            results.append({"symbol": sym, "error": str(e)})
    return results


# ── 私有：yfinance 抓取 + TTL 判斷 ─────────────────────────────────────────────

def _meta_stale(existing: dict | None) -> bool:
    if not existing or not existing.get("updated_at"):
        return True
    try:
        updated = datetime.fromisoformat(existing["updated_at"])
        return (datetime.utcnow() - updated) > timedelta(hours=META_TTL_HOURS)
    except Exception:
        return True


def _price_stale(last_date_str: str | None) -> bool:
    if not last_date_str:
        return True
    try:
        last = datetime.fromisoformat(last_date_str).date()
        # 留 1 天 buffer 避免時區問題
        return last < (date.today() - timedelta(days=1))
    except Exception:
        return True


def _div_stale(last_date_str: str | None) -> bool:
    # 配息資料不會每天變，但 staleness 比照 price（增量便宜）
    return _price_stale(last_date_str)


def _holdings_stale(snapshot_iso: str | None) -> bool:
    if not snapshot_iso:
        return True
    try:
        snap = datetime.fromisoformat(snapshot_iso)
        return (datetime.utcnow() - snap) > timedelta(days=HOLDINGS_TTL_DAYS)
    except Exception:
        return True


def _safe_info(t: yf.Ticker) -> dict:
    try:
        return t.info or {}
    except Exception as e:
        logger.warning("yfinance .info failed: %s", e)
        return {}


def _ts_to_iso(ts: Any) -> str | None:
    if not ts:
        return None
    try:
        return datetime.utcfromtimestamp(int(ts)).date().isoformat()
    except Exception:
        return None


def _fetch_price_rows(t: yf.Ticker, last_known: str | None) -> list[dict]:
    """
    抓 yfinance 日線。若 DB 為空 → 抓 max 歷史；否則 incremental。
    保留 Adj Close 給含息報酬計算用。
    """
    try:
        if last_known:
            start = (datetime.fromisoformat(last_known).date() + timedelta(days=1)).isoformat()
            hist = t.history(start=start, auto_adjust=False)
        else:
            hist = t.history(period="max", auto_adjust=False)
    except Exception as e:
        logger.warning("yfinance .history failed: %s", e)
        return []

    if hist is None or hist.empty:
        return []

    rows = []
    for idx, r in hist.iterrows():
        d = idx.date().isoformat() if hasattr(idx, "date") else str(idx)
        rows.append({
            "date": d,
            "open": _safe_float(r.get("Open")),
            "high": _safe_float(r.get("High")),
            "low": _safe_float(r.get("Low")),
            "close": _safe_float(r.get("Close")),
            "adj_close": _safe_float(r.get("Adj Close")),
            "volume": _safe_int(r.get("Volume")),
        })
    return rows


def _fetch_dividend_rows(t: yf.Ticker) -> list[dict]:
    try:
        divs = t.dividends
    except Exception as e:
        logger.warning("yfinance .dividends failed: %s", e)
        return []
    if divs is None or divs.empty:
        return []
    out = []
    for idx, amt in divs.items():
        d = idx.date().isoformat() if hasattr(idx, "date") else str(idx)
        out.append({"ex_date": d, "dividend": float(amt)})
    return out


def _fetch_holdings(t: yf.Ticker) -> tuple[list[dict], list[dict]]:
    """回傳 (holdings_rows, sector_rows)。任一失敗回空 list。"""
    holdings_rows: list[dict] = []
    sector_rows: list[dict] = []
    try:
        fd = t.funds_data
    except Exception as e:
        logger.warning("funds_data failed: %s", e)
        return [], []
    if fd is None:
        return [], []

    try:
        top = fd.top_holdings
        if top is not None and not top.empty:
            for rank, (sym_idx, row) in enumerate(top.iterrows(), start=1):
                holdings_rows.append({
                    "constituent": str(sym_idx),
                    "name": row.get("Name"),
                    "weight": _safe_float(row.get("Holding Percent")) or 0.0,
                    "rank": rank,
                })
    except Exception as e:
        logger.warning("top_holdings failed: %s", e)

    try:
        sec = fd.sector_weightings or {}
        for sector, w in sec.items():
            if w and w > 0:
                sector_rows.append({"sector": sector, "weight": float(w)})
    except Exception as e:
        logger.warning("sector_weightings failed: %s", e)

    return holdings_rows, sector_rows


def _safe_float(v: Any) -> float | None:
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> int | None:
    f = _safe_float(v)
    return int(f) if f is not None else None


# ============================================================================
# 2. 指標計算
# ============================================================================

RISK_FREE_RATE = 0.015  # 假設無風險利率 1.5%


def _detect_payout_frequency(ex_dates: list[date]) -> int:
    """從最近 4 次除息日反推配息頻率。fallback = 12。"""
    if len(ex_dates) < 2:
        return 12
    recent = sorted(ex_dates)[-4:]
    gaps = [(b - a).days for a, b in zip(recent, recent[1:])]
    avg = sum(gaps) / len(gaps)
    if avg < 45:
        return 1
    if avg < 120:
        return 3
    if avg < 200:
        return 6
    return 12


def compute_dividend_stats(dividends: list[dict], payout_frequency: int | None) -> dict:
    """
    回傳 monthly_dividend_latest / monthly_dividend_avg_12m / latest_vs_avg_pct
    + 最新一期配息金額與日期。
    """
    if not dividends:
        return {
            "monthly_dividend_latest": None,
            "monthly_dividend_avg_12m": None,
            "latest_vs_avg_pct": None,
            "latest_dividend": None,
            "latest_ex_date": None,
            "payout_frequency": payout_frequency or None,
        }

    sorted_divs = sorted(dividends, key=lambda d: d["ex_date"])
    latest = sorted_divs[-1]
    ex_dates = [date.fromisoformat(d["ex_date"]) for d in sorted_divs]

    freq = payout_frequency or _detect_payout_frequency(ex_dates)
    months_per_payout = max(1, freq)
    monthly_latest = latest["dividend"] / months_per_payout

    cutoff = date.today() - timedelta(days=365)
    last_12m_total = sum(d["dividend"] for d in sorted_divs
                         if date.fromisoformat(d["ex_date"]) >= cutoff)
    avg_monthly_12m = last_12m_total / 12 if last_12m_total > 0 else None

    delta_pct = None
    if avg_monthly_12m and avg_monthly_12m > 0:
        delta_pct = (monthly_latest - avg_monthly_12m) / avg_monthly_12m * 100

    return {
        "monthly_dividend_latest": round(monthly_latest, 4),
        "monthly_dividend_avg_12m": round(avg_monthly_12m, 4) if avg_monthly_12m else None,
        "latest_vs_avg_pct": round(delta_pct, 2) if delta_pct is not None else None,
        "latest_dividend": latest["dividend"],
        "latest_ex_date": latest["ex_date"],
        "payout_frequency": freq,
    }


def compute_performance(prices: list[dict]) -> dict:
    """
    含息報酬指標。用 adj_close。
    回傳 1Y/3Y/5Y/成立至今 含息年化、MDD、波動度、Sharpe。
    """
    if not prices or len(prices) < 2:
        return {}

    # 用 adj_close（含息序列）；若全為 None，fallback 用 close
    series = [(date.fromisoformat(p["date"]), p.get("adj_close") or p.get("close"))
              for p in prices if (p.get("adj_close") or p.get("close"))]
    if len(series) < 2:
        return {}

    today = series[-1][0]

    def cagr_window(years: float) -> float | None:
        cutoff = today - timedelta(days=int(years * 365.25))
        window = [(d, v) for d, v in series if d >= cutoff]
        if len(window) < 30:
            return None
        actual_years = (window[-1][0] - window[0][0]).days / 365.25
        if actual_years < years * 0.5 or window[0][1] <= 0:
            return None
        return (window[-1][1] / window[0][1]) ** (1 / actual_years) - 1

    inception_years = (series[-1][0] - series[0][0]).days / 365.25
    cagr_incep = ((series[-1][1] / series[0][1]) ** (1 / max(inception_years, 0.01)) - 1
                  if series[0][1] > 0 else None)

    # MDD
    peak = series[0][1]
    mdd = 0.0
    for _, v in series:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak
            if dd < mdd:
                mdd = dd

    # 波動度 + Sharpe（用日報酬）
    daily_rets = []
    for (d1, v1), (d2, v2) in zip(series, series[1:]):
        if v1 and v1 > 0:
            daily_rets.append(v2 / v1 - 1)
    if daily_rets:
        mean_r = sum(daily_rets) / len(daily_rets)
        var = sum((r - mean_r) ** 2 for r in daily_rets) / max(len(daily_rets) - 1, 1)
        vol_annual = math.sqrt(var) * math.sqrt(252)
    else:
        vol_annual = None

    sharpe = ((cagr_incep - RISK_FREE_RATE) / vol_annual
              if cagr_incep is not None and vol_annual and vol_annual > 0 else None)

    return {
        "return_1y_pct": _pct(cagr_window(1)),
        "return_3y_pct": _pct(cagr_window(3)),
        "return_5y_pct": _pct(cagr_window(5)),
        "return_since_inception_pct": _pct(cagr_incep),
        "mdd_pct": _pct(mdd),
        "volatility_pct": _pct(vol_annual),
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "history_start": series[0][0].isoformat(),
        "history_end": series[-1][0].isoformat(),
    }


def _pct(v: float | None) -> float | None:
    return round(v * 100, 2) if v is not None else None


# ============================================================================
# 3. DCA + DRIP 模擬
# ============================================================================

def simulate_dca(
    symbol: str,
    monthly_amount: float,
    start_date: str,
    end_date: str | None = None,
    drip: bool = True,
    benchmark: str | None = etf_config.DEFAULT_BENCHMARK,
) -> dict:
    """
    執行 DCA + DRIP 模擬，同時對 benchmark 跑一份。
    回傳 {target, benchmark} 兩份結果。
    """
    sync_etf(symbol)
    target_result = _simulate_one(symbol, monthly_amount, start_date, end_date, drip)

    benchmark_result = None
    if benchmark and benchmark != symbol:
        try:
            sync_etf(benchmark)
            benchmark_result = _simulate_one(benchmark, monthly_amount, start_date, end_date, drip)
        except Exception as e:
            logger.warning("benchmark sim failed: %s", e)

    return {"target": target_result, "benchmark": benchmark_result}


def _simulate_one(symbol: str, monthly: float, start_date: str,
                  end_date: str | None, drip: bool) -> dict:
    prices = etf_db.get_prices(symbol, start_date, end_date)
    if not prices:
        raise ValueError(f"No price data for {symbol} in [{start_date}, {end_date}]")

    divs = etf_db.get_dividends(symbol)
    start_d = date.fromisoformat(start_date)
    end_d = date.fromisoformat(end_date) if end_date else date.fromisoformat(prices[-1]["date"])

    # 過濾配息到區間內 & 建立 ex_date → amount map
    div_map: dict[date, float] = {}
    for d in divs:
        ex = date.fromisoformat(d["ex_date"])
        if start_d <= ex <= end_d:
            div_map[ex] = d["dividend"]

    # 每月第一個交易日
    monthly_dates: set[date] = set()
    seen_ym: set[tuple[int, int]] = set()
    for p in prices:
        d = date.fromisoformat(p["date"])
        ym = (d.year, d.month)
        if ym not in seen_ym:
            seen_ym.add(ym)
            monthly_dates.add(d)

    # 主迴圈
    shares = 0.0
    total_invested = 0.0
    total_cash_div = 0.0
    cashflows: list[tuple[date, float]] = []
    timeline: list[dict] = []

    for p in prices:
        d = date.fromisoformat(p["date"])
        close = p.get("close")
        if not close or close <= 0:
            continue

        # 1) 配息日（用收盤價 DRIP 簡化）
        if d in div_map:
            cash_div = shares * div_map[d]
            if drip and cash_div > 0:
                shares += cash_div / close
            elif cash_div > 0:
                total_cash_div += cash_div
                cashflows.append((d, cash_div))

        # 2) 月度定期定額
        if d in monthly_dates:
            shares += monthly / close
            total_invested += monthly
            cashflows.append((d, -monthly))

        # 紀錄 timeline（取樣：每月 1 筆即可，避免回傳過大）
        if d in monthly_dates:
            timeline.append({
                "date": d.isoformat(),
                "invested": round(total_invested, 0),
                "shares": round(shares, 2),
                "market_value": round(shares * close, 0),
                "cash_div_received": round(total_cash_div, 0),
            })

    last_close = next((p["close"] for p in reversed(prices) if p.get("close")), None)
    if not last_close:
        raise ValueError(f"No valid close price for {symbol}")
    last_date = date.fromisoformat(prices[-1]["date"])

    market_value = shares * last_close
    cashflows.append((last_date, market_value))

    total_value = market_value + total_cash_div
    total_return_pct = (total_value - total_invested) / total_invested * 100 if total_invested > 0 else 0
    years = (last_date - start_d).days / 365.25
    cagr = ((total_value / total_invested) ** (1 / years) - 1
            if years > 0 and total_invested > 0 else None)
    irr = _xirr(cashflows)

    # 退休現金流：用最新的「近一年月均月化配息」推
    div_stats = compute_dividend_stats(divs, etf_config.get_config(symbol).get("payout_frequency"))
    monthly_income_now = None
    if div_stats.get("monthly_dividend_avg_12m"):
        monthly_income_now = round(shares * div_stats["monthly_dividend_avg_12m"], 0)

    return {
        "symbol": symbol,
        "period": f"{start_date} ~ {last_date.isoformat()}",
        "total_invested": round(total_invested, 0),
        "shares": round(shares, 2),
        "last_price": round(last_close, 2),
        "market_value": round(market_value, 0),
        "cash_dividends_received": round(total_cash_div, 0),
        "total_value": round(total_value, 0),
        "total_return_pct": round(total_return_pct, 2),
        "cagr_pct": round(cagr * 100, 2) if cagr is not None else None,
        "xirr_pct": round(irr * 100, 2) if irr is not None else None,
        "estimated_monthly_income_now": monthly_income_now,
        "timeline": timeline,
    }


def _xirr(cashflows: list[tuple[date, float]]) -> float | None:
    """Bisection XIRR。輸入須含正負現金流，否則回 None。"""
    if not cashflows or len(cashflows) < 2:
        return None
    positives = any(cf > 0 for _, cf in cashflows)
    negatives = any(cf < 0 for _, cf in cashflows)
    if not (positives and negatives):
        return None

    d0 = cashflows[0][0]

    def npv(rate: float) -> float:
        return sum(cf / (1 + rate) ** ((d - d0).days / 365.25) for d, cf in cashflows)

    lo, hi = -0.99, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-6:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


# ============================================================================
# 4. API 入口：列表 / 詳情
# ============================================================================

@ttl_cache(ttl_seconds=300)
def get_list_summary() -> list[dict]:
    """列表頁摘要。確保所有 ETF 已 sync 過。"""
    out = []
    for cfg in etf_config.list_configs():
        sym = cfg["symbol"]
        try:
            sync_etf(sym)
        except Exception as e:
            logger.warning("sync %s failed: %s", sym, e)

        meta = etf_db.get_meta(sym) or {}
        divs = etf_db.get_dividends(sym)
        prices = etf_db.get_prices(sym)
        div_stats = compute_dividend_stats(divs, meta.get("payout_frequency"))
        perf = compute_performance(prices) if prices else {}

        out.append({
            "symbol": sym,
            "name_zh": cfg["name_zh"],
            "category": cfg["category"],
            "is_active": cfg.get("is_active", False),
            "payout_frequency": meta.get("payout_frequency") or cfg.get("payout_frequency"),
            "expense_ratio": cfg.get("expense_ratio"),
            "aum": meta.get("aum"),
            "nav_price": meta.get("nav_price"),
            "yield_rate": meta.get("yield_rate"),
            "monthly_dividend_latest": div_stats["monthly_dividend_latest"],
            "monthly_dividend_avg_12m": div_stats["monthly_dividend_avg_12m"],
            "latest_vs_avg_pct": div_stats["latest_vs_avg_pct"],
            "return_5y_pct": perf.get("return_5y_pct"),
            "as_of": meta.get("updated_at"),
        })
    return out


def get_detail(symbol: str) -> dict:
    """詳情頁完整資料：meta + performance + dividends + holdings + sectors。"""
    sync_etf(symbol)
    meta = etf_db.get_meta(symbol) or {}
    prices = etf_db.get_prices(symbol)
    divs = etf_db.get_dividends(symbol)
    holdings = etf_db.get_holdings(symbol)
    sectors = etf_db.get_sectors(symbol)

    perf = compute_performance(prices) if prices else {}
    div_stats = compute_dividend_stats(divs, meta.get("payout_frequency"))
    anomalies = etf_anomaly.detect_price_anomalies(prices) if prices else []

    # 取樣縮減 price_history（每週 1 筆，避免回傳 1500+ 筆）
    sampled_prices = _downsample_prices(prices, target=400)

    return {
        "meta": meta,
        "performance": {**perf, "price_history": sampled_prices},
        "dividends": {
            **div_stats,
            "history": divs,
        },
        "holdings": {
            "snapshot_at": holdings[0]["snapshot_at"] if holdings else None,
            "top": holdings,
            "sectors": sectors,
        },
        "anomalies": anomalies,
    }


def _downsample_prices(prices: list[dict], target: int = 400) -> list[dict]:
    if len(prices) <= target:
        return [{"date": p["date"], "close": p.get("close"),
                 "adj_close": p.get("adj_close")} for p in prices]
    step = max(1, len(prices) // target)
    return [{"date": p["date"], "close": p.get("close"),
             "adj_close": p.get("adj_close")} for p in prices[::step]]
