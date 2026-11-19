"""SQLite storage for the setup watchlist and its alerts.

Kept beside the feature code instead of in ``db/store.py``. It borrows the
store's connection, so it shares the same database file and WAL settings.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from ...config import normalize_symbol
from ...db.store import TimelineStore, get_store

NIFTY_TOKEN = "NSE_INDEX|Nifty 50"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS setup_watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    instrument_token TEXT,
    company_name TEXT,
    sector TEXT,
    timeframe TEXT NOT NULL DEFAULT 'daily',
    status TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    last_checked TEXT NOT NULL,
    days_in_base INTEGER NOT NULL DEFAULT 1,
    misses INTEGER NOT NULL DEFAULT 0,
    pivot REAL NOT NULL,
    stop REAL NOT NULL,
    last_close REAL,
    score REAL,
    first_score REAL,
    features_json TEXT,
    resolved_date TEXT,
    resolved_price REAL,
    resolved_close REAL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_setup_watchlist_status ON setup_watchlist(status, score);
CREATE INDEX IF NOT EXISTS idx_setup_watchlist_ticker ON setup_watchlist(ticker, status);

CREATE TABLE IF NOT EXISTS setup_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    state TEXT NOT NULL,
    price REAL,
    pivot REAL,
    stop REAL,
    session_rvol REAL,
    message TEXT,
    delivered INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (session_date, ticker, state)
);

CREATE TABLE IF NOT EXISTS setup_filings (
    seq_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    company_name TEXT,
    category TEXT NOT NULL,
    subject TEXT,
    summary TEXT,
    url TEXT,
    filed_at TEXT NOT NULL,
    published_at TEXT NOT NULL,
    alerted INTEGER NOT NULL DEFAULT 0,
    delivered INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    sized INTEGER NOT NULL DEFAULT 0,
    impact TEXT,
    size_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_setup_filings_time ON setup_filings(published_at);
CREATE INDEX IF NOT EXISTS idx_setup_filings_ticker ON setup_filings(ticker, published_at);

CREATE TABLE IF NOT EXISTS setup_events (
    ticker TEXT NOT NULL,
    event_date TEXT NOT NULL,
    purpose TEXT NOT NULL,
    detail TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (ticker, event_date, purpose)
);

CREATE TABLE IF NOT EXISTS setup_delivery (
    trade_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    traded_qty REAL,
    deliv_qty REAL,
    deliv_pct REAL,
    PRIMARY KEY (trade_date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_setup_delivery_ticker ON setup_delivery(ticker, trade_date);

CREATE TABLE IF NOT EXISTS setup_deals (
    trade_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    client TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    kind TEXT NOT NULL,
    churn INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (trade_date, ticker, client, side, quantity, price, kind)
);

CREATE TABLE IF NOT EXISTS setup_industry (
    ticker TEXT PRIMARY KEY,
    industry TEXT NOT NULL,
    company_name TEXT
);

CREATE TABLE IF NOT EXISTS setup_flags (
    ticker TEXT NOT NULL,
    flag TEXT NOT NULL,
    detail TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (ticker, flag)
);

CREATE TABLE IF NOT EXISTS setup_actions (
    ticker TEXT NOT NULL,
    ex_date TEXT NOT NULL,
    subject TEXT NOT NULL,
    kind TEXT NOT NULL,
    factor REAL,
    PRIMARY KEY (ticker, ex_date, subject)
);

CREATE TABLE IF NOT EXISTS setup_market_health (
    trade_date TEXT PRIMARY KEY,
    stocks INTEGER NOT NULL,
    pct_above_50 REAL,
    new_highs INTEGER,
    new_lows INTEGER,
    breadth_chg REAL,
    state TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS setup_preopen (
    session_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    iep REAL,
    prev_close REAL,
    pivot REAL,
    stop REAL,
    gap_to_pivot_pct REAL,
    qty_pct REAL,
    state TEXT NOT NULL,
    label TEXT,
    PRIMARY KEY (session_date, ticker, timeframe)
);

CREATE TABLE IF NOT EXISTS setup_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

_ready: set[str] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(store: TimelineStore | None = None) -> TimelineStore:
    db = store or get_store()
    key = str(db.db_path)
    if key not in _ready:
        with db.connection() as conn:
            conn.executescript(_SCHEMA)
            # Columns added after the first release of these tables.
            for table, column, decl in (
                ("setup_watchlist", "timeframe", "TEXT NOT NULL DEFAULT 'daily'"),
                ("setup_filings", "sized", "INTEGER NOT NULL DEFAULT 0"),
                ("setup_filings", "impact", "TEXT"),
                ("setup_filings", "size_json", "TEXT"),
            ):
                have = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                if column not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        _ready.add(key)
    return db


@dataclass
class WatchEntry:
    ticker: str
    pivot: float
    stop: float
    first_seen: str
    last_seen: str
    last_checked: str
    status: str = "active"
    timeframe: str = "daily"
    instrument_token: str | None = None
    company_name: str | None = None
    sector: str | None = None
    days_in_base: int = 1
    misses: int = 0
    last_close: float | None = None
    score: float | None = None
    first_score: float | None = None
    features: dict[str, Any] = field(default_factory=dict)
    resolved_date: str | None = None
    resolved_price: float | None = None
    resolved_close: float | None = None
    id: int | None = None
    dirty: bool = True

    def public(self) -> dict[str, Any]:
        row = asdict(self)
        row.pop("dirty", None)
        for name in ("pivot", "stop", "last_close", "resolved_price", "resolved_close"):
            if row[name] is not None:
                row[name] = round(float(row[name]), 2)
        if self.last_close and self.pivot:
            row["distance_pct"] = round((self.pivot - self.last_close) / self.pivot * 100.0, 2)
            row["risk_pct"] = round((self.pivot - self.stop) / self.pivot * 100.0, 2)
        if self.status == "triggered" and self.resolved_close:
            # Crossing the pivot is common; closing above it is the part that counts.
            row["held_above_pivot"] = self.resolved_close >= self.pivot
        return row


def _entry(row: Any) -> WatchEntry:
    item = dict(row)
    try:
        features = json.loads(item.get("features_json") or "{}")
    except json.JSONDecodeError:
        features = {}
    return WatchEntry(
        id=int(item["id"]),
        ticker=str(item["ticker"]),
        instrument_token=item.get("instrument_token"),
        company_name=item.get("company_name"),
        sector=item.get("sector"),
        timeframe=str(item.get("timeframe") or "daily"),
        status=str(item["status"]),
        first_seen=str(item["first_seen"]),
        last_seen=str(item["last_seen"]),
        last_checked=str(item["last_checked"]),
        days_in_base=int(item.get("days_in_base") or 1),
        misses=int(item.get("misses") or 0),
        pivot=float(item["pivot"]),
        stop=float(item["stop"]),
        last_close=item.get("last_close"),
        score=item.get("score"),
        first_score=item.get("first_score"),
        features=features if isinstance(features, dict) else {},
        resolved_date=item.get("resolved_date"),
        resolved_price=item.get("resolved_price"),
        resolved_close=item.get("resolved_close"),
        dirty=False,
    )


def list_entries(
    *,
    status: str | None = "active",
    limit: int = 200,
    since: str | None = None,
    timeframe: str | None = None,
    store: TimelineStore | None = None,
) -> list[WatchEntry]:
    db = ensure_schema(store)
    clauses: list[str] = []
    params: list[Any] = []
    if timeframe:
        clauses.append("timeframe = ?")
        params.append(timeframe)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if since:
        clauses.append("first_seen >= ?")
        params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order = "score DESC" if status == "active" else "COALESCE(resolved_date, last_seen) DESC, score DESC"
    params.append(max(1, int(limit)))
    with db.connection() as conn:
        rows = conn.execute(f"SELECT * FROM setup_watchlist {where} ORDER BY {order} LIMIT ?", params).fetchall()
    return [_entry(row) for row in rows]


def save_entries(entries: list[WatchEntry], store: TimelineStore | None = None) -> int:
    db = ensure_schema(store)
    changed = [entry for entry in entries if entry.dirty]
    if not changed:
        return 0
    stamp = _now()
    with db.connection() as conn:
        for entry in changed:
            values = (
                entry.ticker,
                entry.instrument_token,
                entry.company_name,
                entry.sector,
                entry.timeframe,
                entry.status,
                entry.first_seen,
                entry.last_seen,
                entry.last_checked,
                entry.days_in_base,
                entry.misses,
                entry.pivot,
                entry.stop,
                entry.last_close,
                entry.score,
                entry.first_score,
                json.dumps(entry.features),
                entry.resolved_date,
                entry.resolved_price,
                entry.resolved_close,
                stamp,
            )
            if entry.id is None:
                cursor = conn.execute(
                    """
                    INSERT INTO setup_watchlist (
                        ticker, instrument_token, company_name, sector, timeframe, status, first_seen, last_seen,
                        last_checked, days_in_base, misses, pivot, stop, last_close, score, first_score,
                        features_json, resolved_date, resolved_price, resolved_close, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    values,
                )
                entry.id = int(cursor.lastrowid)
            else:
                conn.execute(
                    """
                    UPDATE setup_watchlist SET
                        ticker=?, instrument_token=?, company_name=?, sector=?, timeframe=?, status=?, first_seen=?,
                        last_seen=?, last_checked=?, days_in_base=?, misses=?, pivot=?, stop=?, last_close=?,
                        score=?, first_score=?, features_json=?, resolved_date=?, resolved_price=?,
                        resolved_close=?, updated_at=?
                    WHERE id=?
                    """,
                    (*values, entry.id),
                )
            entry.dirty = False
    return len(changed)


def clear_watchlist(store: TimelineStore | None = None) -> None:
    db = ensure_schema(store)
    with db.connection() as conn:
        conn.execute("DELETE FROM setup_watchlist")
        conn.execute("DELETE FROM setup_meta WHERE key = 'processed_through'")


def get_meta(key: str, store: TimelineStore | None = None) -> str | None:
    db = ensure_schema(store)
    with db.connection() as conn:
        row = conn.execute("SELECT value FROM setup_meta WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row and row["value"] is not None else None


def set_meta(key: str, value: str, store: TimelineStore | None = None) -> None:
    db = ensure_schema(store)
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO setup_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def status_counts(store: TimelineStore | None = None, timeframe: str | None = None) -> dict[str, int]:
    db = ensure_schema(store)
    where, params = ("WHERE timeframe = ?", (timeframe,)) if timeframe else ("", ())
    with db.connection() as conn:
        rows = conn.execute(
            f"SELECT status, COUNT(*) AS n FROM setup_watchlist {where} GROUP BY status", params
        ).fetchall()
    return {str(row["status"]): int(row["n"]) for row in rows}


# -------------------------------------------------------------------- alerts


def record_alert(alert: dict[str, Any], store: TimelineStore | None = None) -> bool:
    """True when this (session, ticker, state) had not been recorded before."""
    db = ensure_schema(store)
    with db.connection() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO setup_alerts (
                session_date, ticker, state, price, pivot, stop, session_rvol, message, delivered, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                alert["session_date"],
                alert["ticker"],
                alert["state"],
                alert.get("price"),
                alert.get("pivot"),
                alert.get("stop"),
                alert.get("session_rvol"),
                alert.get("message"),
                1 if alert.get("delivered") else 0,
                _now(),
            ),
        )
        return cursor.rowcount > 0


def mark_alert_delivered(session_date: str, ticker: str, state: str, store: TimelineStore | None = None) -> None:
    db = ensure_schema(store)
    with db.connection() as conn:
        conn.execute(
            "UPDATE setup_alerts SET delivered = 1 WHERE session_date = ? AND ticker = ? AND state = ?",
            (session_date, ticker, state),
        )


def list_alerts(
    *,
    session_date: str | None = None,
    limit: int = 100,
    store: TimelineStore | None = None,
) -> list[dict[str, Any]]:
    db = ensure_schema(store)
    params: list[Any] = []
    where = ""
    if session_date:
        where = "WHERE session_date = ?"
        params.append(session_date)
    params.append(max(1, int(limit)))
    with db.connection() as conn:
        rows = conn.execute(f"SELECT * FROM setup_alerts {where} ORDER BY id DESC LIMIT ?", params).fetchall()
    return [dict(row) for row in rows]


def alert_keys(session_date: str, store: TimelineStore | None = None) -> set[tuple[str, str]]:
    db = ensure_schema(store)
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT ticker, state FROM setup_alerts WHERE session_date = ?", (session_date,)
        ).fetchall()
    return {(str(row["ticker"]), str(row["state"])) for row in rows}


# ------------------------------------------------------------------- loading


def load_candles(start: str, end: str, store: TimelineStore | None = None) -> pd.DataFrame:
    """Daily bars for every profiled stock between two dates, sorted by ticker then date."""
    db = store or get_store()
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT p.ticker, p.company_name, p.sector, p.instrument_token,
                   c.trade_date AS date, c.open_price AS open, c.high_price AS high,
                   c.low_price AS low, c.close_price AS close, c.volume
            FROM daily_candles c
            JOIN security_profiles p ON c.instrument_token = p.instrument_token
            WHERE c.trade_date >= ? AND c.trade_date <= ?
              AND c.open_price > 0 AND c.high_price > 0 AND c.low_price > 0 AND c.close_price > 0
            ORDER BY p.ticker ASC, c.trade_date ASC
            """,
            (start, end),
        ).fetchall()
    columns = ["ticker", "company_name", "sector", "instrument_token", "date", "open", "high", "low", "close", "volume"]
    frame = pd.DataFrame([tuple(row) for row in rows], columns=columns)
    if not frame.empty:
        frame["date"] = frame["date"].astype(str).str[:10]
        frame["volume"] = frame["volume"].fillna(0)
    return frame


def load_benchmark(start: str, end: str, store: TimelineStore | None = None) -> pd.Series:
    """Nifty 50 daily closes indexed by date. Empty when the index has not been synced."""
    db = store or get_store()
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT substr(ts, 1, 10) AS date, close_price AS close
            FROM index_candles
            WHERE instrument_token = ? AND timeframe = 'daily'
              AND substr(ts, 1, 10) >= ? AND substr(ts, 1, 10) <= ?
            ORDER BY ts ASC
            """,
            (NIFTY_TOKEN, start, end),
        ).fetchall()
    series = pd.Series({str(row["date"]): float(row["close"]) for row in rows if row["close"]}, dtype=float)
    return series[~series.index.duplicated(keep="last")]


def load_futures_oi(start: str, end: str, store: TimelineStore | None = None) -> dict[str, pd.DataFrame]:
    """Front-month futures OI per symbol, indexed by date."""
    db = store or get_store()
    with db.connection() as conn:
        rows = conn.execute(
            """
            SELECT symbol, trade_date, instrument_key, expiry, oi
            FROM futures_oi_daily
            WHERE trade_date >= ? AND trade_date <= ? AND oi IS NOT NULL
            ORDER BY symbol ASC, trade_date ASC, expiry ASC
            """,
            (start, end),
        ).fetchall()
    if not rows:
        return {}
    frame = pd.DataFrame([tuple(row) for row in rows], columns=["symbol", "date", "instrument_key", "expiry", "oi"])
    frame["date"] = frame["date"].astype(str).str[:10]
    # Nearest expiry first within a day, so the first row per day is the front month.
    frame = frame.drop_duplicates(subset=["symbol", "date"], keep="first")
    return {
        normalize_symbol(str(symbol)): group.set_index("date")[["oi", "instrument_key"]]
        for symbol, group in frame.groupby("symbol")
    }


# ------------------------------------------------------------------- filings


def known_filing_ids(seq_ids: list[str], store: TimelineStore | None = None) -> set[str]:
    db = ensure_schema(store)
    ids = [seq for seq in dict.fromkeys(seq_ids) if seq and seq != "None"]
    if not ids:
        return set()
    with db.connection() as conn:
        rows = conn.execute(
            f"SELECT seq_id FROM setup_filings WHERE seq_id IN ({','.join('?' * len(ids))})", ids
        ).fetchall()
    return {str(row["seq_id"]) for row in rows}


def save_filings(filings: list[dict[str, Any]], store: TimelineStore | None = None) -> list[dict[str, Any]]:
    """Insert filings not stored yet and return those. A filing is stored once, by NSE's id."""
    db = ensure_schema(store)
    new: list[dict[str, Any]] = []
    stamp = _now()
    with db.connection() as conn:
        for filing in filings:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO setup_filings (
                    seq_id, ticker, company_name, category, subject, summary, url, filed_at, published_at, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    filing["seq_id"], filing["ticker"], filing.get("company_name"), filing["category"],
                    filing.get("subject"), filing.get("summary"), filing.get("url"),
                    filing["filed_at"], filing["published_at"], stamp,
                ),
            )
            if cursor.rowcount > 0:
                new.append(filing)
    return new


def mark_filing_alerted(seq_id: str, delivered: bool, store: TimelineStore | None = None) -> None:
    db = ensure_schema(store)
    with db.connection() as conn:
        conn.execute(
            "UPDATE setup_filings SET alerted = 1, delivered = ? WHERE seq_id = ?", (1 if delivered else 0, seq_id)
        )


def list_filings(
    *,
    since: str,
    tickers: list[str] | None = None,
    limit: int = 300,
    store: TimelineStore | None = None,
) -> list[dict[str, Any]]:
    """Material filings published at or after ``since`` (ISO time), newest first."""
    db = ensure_schema(store)
    clauses = ["published_at >= ?"]
    params: list[Any] = [since]
    if tickers is not None:
        if not tickers:
            return []
        clauses.append(f"ticker IN ({','.join('?' * len(tickers))})")
        params.extend(tickers)
    params.append(max(1, int(limit)))
    with db.connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM setup_filings WHERE {' AND '.join(clauses)} ORDER BY published_at DESC LIMIT ?", params
        ).fetchall()
    return [dict(row) for row in rows]


def save_events(events: list[dict[str, Any]], store: TimelineStore | None = None) -> int:
    db = ensure_schema(store)
    stamp = _now()
    with db.connection() as conn:
        conn.executemany(
            """
            INSERT INTO setup_events (ticker, event_date, purpose, detail, updated_at) VALUES (?,?,?,?,?)
            ON CONFLICT(ticker, event_date, purpose) DO UPDATE SET detail = excluded.detail, updated_at = excluded.updated_at
            """,
            [(e["ticker"], e["event_date"], e["purpose"], e.get("detail"), stamp) for e in events],
        )
    return len(events)


def upcoming_events(from_date: str, to_date: str, store: TimelineStore | None = None) -> dict[str, dict[str, Any]]:
    """The nearest scheduled event per ticker between two dates."""
    db = ensure_schema(store)
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT ticker, event_date, purpose, detail FROM setup_events "
            "WHERE event_date >= ? AND event_date <= ? ORDER BY event_date DESC",
            (from_date, to_date),
        ).fetchall()
    return {str(row["ticker"]): dict(row) for row in rows}


# ----------------------------------------------------------------- market data


def save_delivery(rows: list[dict[str, Any]], store: TimelineStore | None = None) -> int:
    db = ensure_schema(store)
    values = [
        (row["trade_date"], row["ticker"], row.get("volume"), row.get("deliv_qty"), row.get("deliv_pct"))
        for row in rows
        if row.get("deliv_pct") is not None
    ]
    with db.connection() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO setup_delivery (trade_date, ticker, traded_qty, deliv_qty, deliv_pct) VALUES (?,?,?,?,?)",
            values,
        )
    return len(values)


def delivery_days(store: TimelineStore | None = None) -> set[str]:
    db = ensure_schema(store)
    with db.connection() as conn:
        rows = conn.execute("SELECT DISTINCT trade_date FROM setup_delivery").fetchall()
    return {str(row[0]) for row in rows}


def load_delivery(start: str, end: str, store: TimelineStore | None = None) -> dict[str, pd.Series]:
    """Delivery share (0–100) per ticker, indexed by date."""
    db = ensure_schema(store)
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT ticker, trade_date, deliv_pct FROM setup_delivery "
            "WHERE trade_date >= ? AND trade_date <= ? ORDER BY ticker ASC, trade_date ASC",
            (start, end),
        ).fetchall()
    if not rows:
        return {}
    frame = pd.DataFrame([tuple(row) for row in rows], columns=["ticker", "date", "deliv_pct"])
    return {str(ticker): group.set_index("date")["deliv_pct"].astype(float) for ticker, group in frame.groupby("ticker", sort=False)}


def save_deals(deals: list[dict[str, Any]], store: TimelineStore | None = None) -> int:
    db = ensure_schema(store)
    with db.connection() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO setup_deals (trade_date, ticker, client, side, quantity, price, kind, churn) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [
                (d["trade_date"], d["ticker"], d["client"], d["side"], d["quantity"], d["price"], d["kind"], d["churn"])
                for d in deals
            ],
        )
    return len(deals)


def one_sided_buys(since: str, store: TimelineStore | None = None) -> dict[str, list[dict[str, Any]]]:
    """Large buys since ``since`` by clients that did not also sell the stock that day, newest first."""
    db = ensure_schema(store)
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT trade_date, ticker, client, quantity, price, kind FROM setup_deals "
            "WHERE trade_date >= ? AND churn = 0 AND side = 'BUY' ORDER BY trade_date DESC, quantity DESC",
            (since,),
        ).fetchall()
    found: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        found.setdefault(str(row["ticker"]), []).append(dict(row))
    return found


def save_industries(rows: list[dict[str, Any]], store: TimelineStore | None = None) -> int:
    db = ensure_schema(store)
    with db.connection() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO setup_industry (ticker, industry, company_name) VALUES (?,?,?)",
            [(row["ticker"], row["industry"], row.get("company_name")) for row in rows],
        )
    return len(rows)


def load_industries(store: TimelineStore | None = None) -> dict[str, str]:
    db = ensure_schema(store)
    with db.connection() as conn:
        rows = conn.execute("SELECT ticker, industry FROM setup_industry").fetchall()
    return {str(row["ticker"]): str(row["industry"]) for row in rows}


def replace_flags(kinds: list[str], rows: list[dict[str, Any]], store: TimelineStore | None = None) -> int:
    """Replace every stored flag of the given kinds with ``rows`` (the lists are full snapshots)."""
    db = ensure_schema(store)
    stamp = _now()
    with db.connection() as conn:
        conn.execute(f"DELETE FROM setup_flags WHERE flag IN ({','.join('?' * len(kinds))})", kinds)
        conn.executemany(
            "INSERT OR REPLACE INTO setup_flags (ticker, flag, detail, updated_at) VALUES (?,?,?,?)",
            [(row["ticker"], row["flag"], row.get("detail"), stamp) for row in rows if row["flag"] in kinds],
        )
    return len(rows)


def load_flags(store: TimelineStore | None = None) -> dict[str, list[dict[str, Any]]]:
    db = ensure_schema(store)
    with db.connection() as conn:
        rows = conn.execute("SELECT ticker, flag, detail FROM setup_flags ORDER BY flag").fetchall()
    found: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        found.setdefault(str(row["ticker"]), []).append({"flag": row["flag"], "detail": row["detail"]})
    return found


def save_actions(rows: list[dict[str, Any]], store: TimelineStore | None = None) -> int:
    db = ensure_schema(store)
    with db.connection() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO setup_actions (ticker, ex_date, subject, kind, factor) VALUES (?,?,?,?,?)",
            [(row["ticker"], row["ex_date"], row["subject"], row["kind"], row.get("factor")) for row in rows],
        )
    return len(rows)


def load_actions(
    start: str,
    end: str,
    *,
    with_factor: bool = False,
    store: TimelineStore | None = None,
) -> list[dict[str, Any]]:
    db = ensure_schema(store)
    extra = "AND factor IS NOT NULL" if with_factor else ""
    with db.connection() as conn:
        rows = conn.execute(
            f"SELECT ticker, ex_date, subject, kind, factor FROM setup_actions "
            f"WHERE ex_date >= ? AND ex_date <= ? {extra} ORDER BY ex_date ASC",
            (start, end),
        ).fetchall()
    return [dict(row) for row in rows]


def save_health(rows: list[dict[str, Any]], store: TimelineStore | None = None) -> int:
    db = ensure_schema(store)
    with db.connection() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO setup_market_health "
            "(trade_date, stocks, pct_above_50, new_highs, new_lows, breadth_chg, state) VALUES (?,?,?,?,?,?,?)",
            [
                (r["trade_date"], r["stocks"], r.get("pct_above_50"), r.get("new_highs"), r.get("new_lows"), r.get("breadth_chg"), r["state"])
                for r in rows
            ],
        )
    return len(rows)


def load_health(start: str, end: str, store: TimelineStore | None = None) -> list[dict[str, Any]]:
    db = ensure_schema(store)
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT * FROM setup_market_health WHERE trade_date >= ? AND trade_date <= ? ORDER BY trade_date ASC",
            (start, end),
        ).fetchall()
    return [dict(row) for row in rows]


def latest_health(store: TimelineStore | None = None) -> dict[str, Any] | None:
    db = ensure_schema(store)
    with db.connection() as conn:
        row = conn.execute("SELECT * FROM setup_market_health ORDER BY trade_date DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def save_preopen(rows: list[dict[str, Any]], store: TimelineStore | None = None) -> int:
    db = ensure_schema(store)
    with db.connection() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO setup_preopen (session_date, ticker, timeframe, iep, prev_close, pivot, stop, "
            "gap_to_pivot_pct, qty_pct, state, label) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    r["session_date"], r["ticker"], r["timeframe"], r.get("iep"), r.get("prev_close"), r.get("pivot"),
                    r.get("stop"), r.get("gap_to_pivot_pct"), r.get("qty_pct"), r["state"], r.get("label"),
                )
                for r in rows
            ],
        )
    return len(rows)


def load_preopen(session_date: str, store: TimelineStore | None = None) -> dict[tuple[str, str], dict[str, Any]]:
    db = ensure_schema(store)
    with db.connection() as conn:
        rows = conn.execute("SELECT * FROM setup_preopen WHERE session_date = ?", (session_date,)).fetchall()
    return {(str(row["ticker"]), str(row["timeframe"])): dict(row) for row in rows}


def candle_days(store: TimelineStore | None = None, min_rows: int = 500) -> set[str]:
    """Dates that already have daily candles for most of the market."""
    db = store or get_store()
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT trade_date FROM daily_candles GROUP BY trade_date HAVING COUNT(*) >= ?", (min_rows,)
        ).fetchall()
    return {str(row[0])[:10] for row in rows}


def index_days(store: TimelineStore | None = None) -> set[str]:
    db = store or get_store()
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT substr(ts, 1, 10) FROM index_candles WHERE instrument_token = ? AND timeframe = 'daily'",
            (NIFTY_TOKEN,),
        ).fetchall()
    return {str(row[0]) for row in rows}


def fill_missing_candles(rows: list[dict[str, Any]], store: TimelineStore | None = None) -> int:
    """Add daily candles from NSE's file for stocks and days that have none. Never overwrites."""
    db = store or get_store()
    with db.connection() as conn:
        tokens = {
            str(row["ticker"]): str(row["instrument_token"])
            for row in conn.execute("SELECT ticker, instrument_token FROM security_profiles")
        }
        values = []
        for row in rows:
            token = tokens.get(row["ticker"])
            if not token or not all(row.get(key) for key in ("open", "high", "low", "close")):
                continue
            prev = row.get("prev_close")
            change = (row["close"] / prev - 1.0) * 100.0 if prev else None
            values.append(
                (row["trade_date"], token, row["open"], row["high"], row["low"], row["close"], int(row.get("volume") or 0), change, "nse_bhavcopy")
            )
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO daily_candles (trade_date, instrument_token, open_price, high_price, low_price, "
            "close_price, volume, daily_return_pct, source) VALUES (?,?,?,?,?,?,?,?,?)",
            values,
        )
        return conn.total_changes - before


def fill_missing_index(row: dict[str, Any], store: TimelineStore | None = None) -> int:
    """Add one Nifty 50 daily bar unless that date already has one."""
    db = store or get_store()
    with db.connection() as conn:
        before = conn.total_changes
        conn.execute(
            """
            INSERT INTO index_candles (instrument_token, timeframe, ts, open_price, high_price, low_price, close_price, volume, oi, source)
            SELECT ?, 'daily', ?, ?, ?, ?, ?, 0, 0, 'nse_index_file'
            WHERE NOT EXISTS (
                SELECT 1 FROM index_candles WHERE instrument_token = ? AND timeframe = 'daily' AND substr(ts, 1, 10) = ?
            )
            """,
            (NIFTY_TOKEN, f"{row['trade_date']}T00:00:00+05:30", row["open"], row["high"], row["low"], row["close"], NIFTY_TOKEN, row["trade_date"]),
        )
        return conn.total_changes - before


# -------------------------------------------------------------- filing sizing


def filings_to_size(limit: int = 10, store: TimelineStore | None = None) -> list[dict[str, Any]]:
    """Newest filings that have not been read for size yet."""
    db = ensure_schema(store)
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT * FROM setup_filings WHERE sized = 0 ORDER BY published_at DESC LIMIT ?", (max(1, int(limit)),)
        ).fetchall()
    return [dict(row) for row in rows]


def save_filing_size(seq_id: str, size: dict[str, Any] | None, store: TimelineStore | None = None) -> None:
    db = ensure_schema(store)
    with db.connection() as conn:
        conn.execute(
            "UPDATE setup_filings SET sized = 1, impact = ?, size_json = ? WHERE seq_id = ?",
            ((size or {}).get("impact"), json.dumps(size) if size else None, seq_id),
        )
