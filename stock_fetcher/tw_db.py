"""
SQLite data layer for Taiwan stock market history.

Two tables:
  - companies: static company info (symbol, name, industry, market)
  - daily_prices: time-series price data (symbol, date, close, volume, pe, pb, yield)

All functions are thread-safe via per-call connections.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "tw_market.db"

_init_lock = threading.Lock()
_initialized = False


# ── Connection management ─────────────────────────────────────────────────────

@contextmanager
def get_conn():
    """Context manager for SQLite connections. Auto-commits on success."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables and indexes if they don't exist. Safe to call multiple times."""
    global _initialized
    with _init_lock:
        if _initialized:
            return
        with get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS companies (
                    symbol      TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    industry    TEXT,
                    market      TEXT,
                    updated_at  TEXT
                );

                CREATE TABLE IF NOT EXISTS daily_prices (
                    symbol      TEXT NOT NULL,
                    date        TEXT NOT NULL,
                    open        REAL,
                    high        REAL,
                    low         REAL,
                    close       REAL,
                    change_pct  REAL,
                    volume      INTEGER,
                    pe          REAL,
                    pb          REAL,
                    yield_pct   REAL,
                    PRIMARY KEY (symbol, date)
                );

                CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_prices(date);
                CREATE INDEX IF NOT EXISTS idx_daily_symbol ON daily_prices(symbol);
                CREATE INDEX IF NOT EXISTS idx_companies_industry ON companies(industry);
            """)
            _migrate_add_ohl_columns(conn)
        _initialized = True
        logger.info("SQLite DB initialized at %s", DB_PATH)


def _migrate_add_ohl_columns(conn) -> None:
    """v3.1 migration: add open/high/low columns if missing.

    Idempotent — safe to call on every init. Existing rows get NULL for
    OHL until next refresh fills them in.
    """
    existing = {r[1] for r in conn.execute("PRAGMA table_info(daily_prices)")}
    for col in ("open", "high", "low"):
        if col not in existing:
            conn.execute(f"ALTER TABLE daily_prices ADD COLUMN {col} REAL")
            logger.info("Migrated: added column %s to daily_prices", col)


# ── Company operations ───────────────────────────────────────────────────────

def upsert_companies(companies: Iterable[dict]) -> int:
    """
    Insert or update company records.
    Each dict must have: symbol, name. Optional: industry, market.
    Returns number of rows affected.
    """
    init_db()
    now = date.today().isoformat()
    rows = [
        (c["symbol"], c["name"], c.get("industry", ""), c.get("market", ""), now)
        for c in companies if c.get("symbol") and c.get("name")
    ]
    if not rows:
        return 0
    with get_conn() as conn:
        conn.executemany("""
            INSERT INTO companies (symbol, name, industry, market, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                name = excluded.name,
                industry = excluded.industry,
                market = excluded.market,
                updated_at = excluded.updated_at
        """, rows)
    return len(rows)


def get_company(symbol: str) -> dict | None:
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM companies WHERE symbol = ?", (symbol,)
        ).fetchone()
    return dict(row) if row else None


def find_peers_by_industry(symbol: str, top_n: int = 3) -> list[str]:
    """Find same-industry peers, sorted by latest volume desc."""
    init_db()
    with get_conn() as conn:
        target = conn.execute(
            "SELECT industry FROM companies WHERE symbol = ?", (symbol,)
        ).fetchone()
        if not target or not target["industry"]:
            return []
        rows = conn.execute("""
            SELECT c.symbol, COALESCE(MAX(d.volume), 0) AS vol
            FROM companies c
            LEFT JOIN daily_prices d ON c.symbol = d.symbol
            WHERE c.industry = ? AND c.symbol != ?
            GROUP BY c.symbol
            ORDER BY vol DESC
            LIMIT ?
        """, (target["industry"], symbol, top_n)).fetchall()
    return [r["symbol"] for r in rows]


# ── Daily price operations ────────────────────────────────────────────────────

def upsert_daily_prices(prices: Iterable[dict]) -> int:
    """
    Insert or update daily price records.
    Each dict must have: symbol, date, close. Optional: change_pct, volume, pe, pb, yield_pct.
    Returns number of rows affected.
    """
    init_db()
    rows = [
        (
            p["symbol"], p["date"],
            p.get("open"), p.get("high"), p.get("low"), p.get("close"),
            p.get("change_pct"), p.get("volume"),
            p.get("pe"), p.get("pb"), p.get("yield_pct"),
        )
        for p in prices if p.get("symbol") and p.get("date") and p.get("close") is not None
    ]
    if not rows:
        return 0
    with get_conn() as conn:
        conn.executemany("""
            INSERT INTO daily_prices (symbol, date, open, high, low, close, change_pct, volume, pe, pb, yield_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, date) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                change_pct = excluded.change_pct,
                volume = excluded.volume,
                pe = excluded.pe,
                pb = excluded.pb,
                yield_pct = excluded.yield_pct
        """, rows)
    return len(rows)


def get_latest_date() -> str | None:
    """Return the latest date in daily_prices, or None if empty."""
    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT MAX(date) AS d FROM daily_prices").fetchone()
    return row["d"] if row and row["d"] else None


def get_existing_dates(start: str, end: str) -> set[str]:
    """Return set of dates that already have data within [start, end]."""
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT date FROM daily_prices WHERE date >= ? AND date <= ?",
            (start, end),
        ).fetchall()
    return {r["date"] for r in rows}


def get_history(symbol: str, days: int = 60) -> list[dict]:
    """Return latest N days of price history for a symbol, newest first."""
    init_db()
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT date, open, high, low, close, change_pct, volume, pe, pb, yield_pct
            FROM daily_prices
            WHERE symbol = ?
            ORDER BY date DESC
            LIMIT ?
        """, (symbol, days)).fetchall()
    return [dict(r) for r in rows]


def get_latest_snapshot() -> list[dict]:
    """
    Return all stocks with their latest available price + company info.
    Used by the screener for ranking.
    """
    init_db()
    with get_conn() as conn:
        rows = conn.execute("""
            WITH latest AS (
                SELECT symbol, MAX(date) AS max_date
                FROM daily_prices
                GROUP BY symbol
            )
            SELECT
                c.symbol, c.name, c.industry, c.market,
                d.date, d.open, d.high, d.low, d.close, d.change_pct, d.volume,
                d.pe, d.pb, d.yield_pct
            FROM companies c
            JOIN latest l ON c.symbol = l.symbol
            JOIN daily_prices d ON d.symbol = l.symbol AND d.date = l.max_date
        """).fetchall()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    """Return DB statistics for diagnostics."""
    init_db()
    with get_conn() as conn:
        company_count = conn.execute("SELECT COUNT(*) AS n FROM companies").fetchone()["n"]
        price_count = conn.execute("SELECT COUNT(*) AS n FROM daily_prices").fetchone()["n"]
        date_range = conn.execute(
            "SELECT MIN(date) AS mn, MAX(date) AS mx FROM daily_prices"
        ).fetchone()
        distinct_dates = conn.execute(
            "SELECT COUNT(DISTINCT date) AS n FROM daily_prices"
        ).fetchone()["n"]
    return {
        "companies": company_count,
        "price_records": price_count,
        "trading_days": distinct_dates,
        "earliest_date": date_range["mn"],
        "latest_date": date_range["mx"],
    }


def prune_older_than(cutoff_date: str) -> int:
    """Delete price records older than cutoff_date. Returns rows deleted."""
    init_db()
    with get_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM daily_prices WHERE date < ?", (cutoff_date,)
        )
    return cursor.rowcount


# ── Helpers ───────────────────────────────────────────────────────────────────

def list_trading_days(start: date, end: date) -> list[date]:
    """List weekdays (Mon-Fri) between start and end inclusive."""
    days = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days
