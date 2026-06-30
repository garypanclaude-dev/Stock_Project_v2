"""
SQLite data layer for ETF metadata, prices, dividends, and holdings.

獨立於 tw_market.db，因為 ETF 屬於不同領域邊界且資料來源以 yfinance 為主。
詳見 docs/dca-simulator.md §3。

Tables:
  - etf_meta:        ETF 元資料（靜態 config + 動態 yfinance 欄位合併）
  - etf_price_daily: 日線價量 + Adj Close（含息報酬序列）
  - etf_dividends:   配息歷史
  - etf_holdings:    前 N 大成分股權重（覆寫式）
  - etf_sectors:     產業分布（覆寫式）

所有函式 thread-safe（per-call connection）。
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "etf.db"

_init_lock = threading.Lock()
_initialized = False


@contextmanager
def get_conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables and indexes if missing. Safe to call repeatedly."""
    global _initialized
    with _init_lock:
        if _initialized:
            return
        with get_conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS etf_meta (
                    symbol              TEXT PRIMARY KEY,
                    name_zh             TEXT NOT NULL,
                    name_en             TEXT,
                    category            TEXT NOT NULL,
                    tracking_index      TEXT,
                    expense_ratio       REAL,
                    payout_frequency    INTEGER,
                    is_active           INTEGER NOT NULL DEFAULT 0,
                    fund_family         TEXT,
                    inception_date      TEXT,
                    aum                 REAL,
                    nav_price           REAL,
                    yield_rate          REAL,
                    currency            TEXT DEFAULT 'TWD',
                    updated_at          TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS etf_price_daily (
                    symbol      TEXT NOT NULL,
                    date        TEXT NOT NULL,
                    open        REAL,
                    high        REAL,
                    low         REAL,
                    close       REAL,
                    adj_close   REAL,
                    volume      INTEGER,
                    PRIMARY KEY (symbol, date)
                );
                CREATE INDEX IF NOT EXISTS idx_etf_price_symbol_date
                    ON etf_price_daily(symbol, date);

                CREATE TABLE IF NOT EXISTS etf_dividends (
                    symbol      TEXT NOT NULL,
                    ex_date     TEXT NOT NULL,
                    dividend    REAL NOT NULL,
                    PRIMARY KEY (symbol, ex_date)
                );
                CREATE INDEX IF NOT EXISTS idx_etf_div_symbol_date
                    ON etf_dividends(symbol, ex_date);

                CREATE TABLE IF NOT EXISTS etf_holdings (
                    symbol          TEXT NOT NULL,
                    constituent     TEXT NOT NULL,
                    name            TEXT,
                    weight          REAL NOT NULL,
                    rank            INTEGER NOT NULL,
                    snapshot_at     TEXT NOT NULL,
                    PRIMARY KEY (symbol, constituent)
                );

                CREATE TABLE IF NOT EXISTS etf_sectors (
                    symbol          TEXT NOT NULL,
                    sector          TEXT NOT NULL,
                    weight          REAL NOT NULL,
                    snapshot_at     TEXT NOT NULL,
                    PRIMARY KEY (symbol, sector)
                );
                """
            )
            logger.info("ETF SQLite DB initialized at %s", DB_PATH)
        _initialized = True


# ── etf_meta ─────────────────────────────────────────────────────────────────

def upsert_meta(row: dict) -> None:
    """Insert or update one ETF meta row. Required keys: symbol, name_zh, category, updated_at."""
    init_db()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO etf_meta (
                symbol, name_zh, name_en, category, tracking_index,
                expense_ratio, payout_frequency, is_active, fund_family,
                inception_date, aum, nav_price, yield_rate, currency, updated_at
            ) VALUES (
                :symbol, :name_zh, :name_en, :category, :tracking_index,
                :expense_ratio, :payout_frequency, :is_active, :fund_family,
                :inception_date, :aum, :nav_price, :yield_rate, :currency, :updated_at
            )
            ON CONFLICT(symbol) DO UPDATE SET
                name_zh          = excluded.name_zh,
                name_en          = excluded.name_en,
                category         = excluded.category,
                tracking_index   = excluded.tracking_index,
                expense_ratio    = excluded.expense_ratio,
                payout_frequency = excluded.payout_frequency,
                is_active        = excluded.is_active,
                fund_family      = COALESCE(excluded.fund_family, etf_meta.fund_family),
                inception_date   = COALESCE(excluded.inception_date, etf_meta.inception_date),
                aum              = COALESCE(excluded.aum, etf_meta.aum),
                nav_price        = COALESCE(excluded.nav_price, etf_meta.nav_price),
                yield_rate       = COALESCE(excluded.yield_rate, etf_meta.yield_rate),
                currency         = excluded.currency,
                updated_at       = excluded.updated_at
            """,
            {
                "symbol": row["symbol"],
                "name_zh": row["name_zh"],
                "name_en": row.get("name_en"),
                "category": row["category"],
                "tracking_index": row.get("tracking_index"),
                "expense_ratio": row.get("expense_ratio"),
                "payout_frequency": row.get("payout_frequency"),
                "is_active": 1 if row.get("is_active") else 0,
                "fund_family": row.get("fund_family"),
                "inception_date": row.get("inception_date"),
                "aum": row.get("aum"),
                "nav_price": row.get("nav_price"),
                "yield_rate": row.get("yield_rate"),
                "currency": row.get("currency", "TWD"),
                "updated_at": row["updated_at"],
            },
        )


def get_meta(symbol: str) -> dict | None:
    init_db()
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM etf_meta WHERE symbol = ?", (symbol,)
        ).fetchone()
        return dict(r) if r else None


def list_meta() -> list[dict]:
    init_db()
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM etf_meta").fetchall()
        return [dict(r) for r in rows]


# ── etf_price_daily ──────────────────────────────────────────────────────────

def upsert_prices(symbol: str, rows: list[dict]) -> None:
    """rows: [{date, open, high, low, close, adj_close, volume}, ...]"""
    if not rows:
        return
    init_db()
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO etf_price_daily (symbol, date, open, high, low, close, adj_close, volume)
            VALUES (:symbol, :date, :open, :high, :low, :close, :adj_close, :volume)
            ON CONFLICT(symbol, date) DO UPDATE SET
                open      = excluded.open,
                high      = excluded.high,
                low       = excluded.low,
                close     = excluded.close,
                adj_close = excluded.adj_close,
                volume    = excluded.volume
            """,
            [{"symbol": symbol, **r} for r in rows],
        )


def get_prices(symbol: str, start: str | None = None, end: str | None = None) -> list[dict]:
    init_db()
    sql = "SELECT date, open, high, low, close, adj_close, volume FROM etf_price_daily WHERE symbol = ?"
    args: list = [symbol]
    if start:
        sql += " AND date >= ?"
        args.append(start)
    if end:
        sql += " AND date <= ?"
        args.append(end)
    sql += " ORDER BY date"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def get_latest_price_date(symbol: str) -> str | None:
    init_db()
    with get_conn() as conn:
        r = conn.execute(
            "SELECT MAX(date) AS d FROM etf_price_daily WHERE symbol = ?", (symbol,)
        ).fetchone()
        return r["d"] if r and r["d"] else None


# ── etf_dividends ────────────────────────────────────────────────────────────

def upsert_dividends(symbol: str, rows: list[dict]) -> None:
    """rows: [{ex_date, dividend}, ...]"""
    if not rows:
        return
    init_db()
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO etf_dividends (symbol, ex_date, dividend)
            VALUES (:symbol, :ex_date, :dividend)
            ON CONFLICT(symbol, ex_date) DO UPDATE SET dividend = excluded.dividend
            """,
            [{"symbol": symbol, **r} for r in rows],
        )


def get_dividends(symbol: str) -> list[dict]:
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ex_date, dividend FROM etf_dividends WHERE symbol = ? ORDER BY ex_date",
            (symbol,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_latest_dividend_date(symbol: str) -> str | None:
    init_db()
    with get_conn() as conn:
        r = conn.execute(
            "SELECT MAX(ex_date) AS d FROM etf_dividends WHERE symbol = ?", (symbol,)
        ).fetchone()
        return r["d"] if r and r["d"] else None


# ── etf_holdings / etf_sectors（覆寫式） ──────────────────────────────────────

def replace_holdings(symbol: str, rows: list[dict], snapshot_at: str) -> None:
    """rows: [{constituent, name, weight, rank}, ...]，整批覆寫該 symbol 的持股。"""
    init_db()
    with get_conn() as conn:
        conn.execute("DELETE FROM etf_holdings WHERE symbol = ?", (symbol,))
        if rows:
            conn.executemany(
                """
                INSERT INTO etf_holdings (symbol, constituent, name, weight, rank, snapshot_at)
                VALUES (:symbol, :constituent, :name, :weight, :rank, :snapshot_at)
                """,
                [{"symbol": symbol, "snapshot_at": snapshot_at, **r} for r in rows],
            )


def get_holdings(symbol: str) -> list[dict]:
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT constituent, name, weight, rank, snapshot_at "
            "FROM etf_holdings WHERE symbol = ? ORDER BY rank",
            (symbol,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_holdings_snapshot_at(symbol: str) -> str | None:
    init_db()
    with get_conn() as conn:
        r = conn.execute(
            "SELECT MAX(snapshot_at) AS s FROM etf_holdings WHERE symbol = ?", (symbol,)
        ).fetchone()
        return r["s"] if r and r["s"] else None


def replace_sectors(symbol: str, rows: list[dict], snapshot_at: str) -> None:
    """rows: [{sector, weight}, ...]"""
    init_db()
    with get_conn() as conn:
        conn.execute("DELETE FROM etf_sectors WHERE symbol = ?", (symbol,))
        if rows:
            conn.executemany(
                """
                INSERT INTO etf_sectors (symbol, sector, weight, snapshot_at)
                VALUES (:symbol, :sector, :weight, :snapshot_at)
                """,
                [{"symbol": symbol, "snapshot_at": snapshot_at, **r} for r in rows],
            )


def get_sectors(symbol: str) -> list[dict]:
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT sector, weight, snapshot_at FROM etf_sectors WHERE symbol = ? ORDER BY weight DESC",
            (symbol,),
        ).fetchall()
        return [dict(r) for r in rows]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    print(f"OK: {DB_PATH}")
