from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from ..config import ROOT_DIR
from ..services.market_calendar import expected_latest_session

DEFAULT_DB_PATH = ROOT_DIR / "data" / "trading.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS security_profiles (
    instrument_token TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    company_name TEXT,
    sector TEXT,
    industry TEXT,
    isin TEXT,
    series TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_profiles_ticker ON security_profiles(ticker);
CREATE INDEX IF NOT EXISTS idx_profiles_sector ON security_profiles(sector);

CREATE TABLE IF NOT EXISTS daily_candles (
    trade_date TEXT NOT NULL,
    instrument_token TEXT NOT NULL,
    open_price REAL,
    high_price REAL,
    low_price REAL,
    close_price REAL,
    volume INTEGER,
    daily_return_pct REAL,
    source TEXT,
    PRIMARY KEY (trade_date, instrument_token)
);

CREATE INDEX IF NOT EXISTS idx_candles_date ON daily_candles(trade_date);
CREATE INDEX IF NOT EXISTS idx_candles_return ON daily_candles(trade_date, daily_return_pct);
CREATE INDEX IF NOT EXISTS idx_candles_token ON daily_candles(instrument_token);
CREATE INDEX IF NOT EXISTS idx_candles_token_date ON daily_candles(instrument_token, trade_date);

CREATE TABLE IF NOT EXISTS scanner_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    symbols_scanned INTEGER DEFAULT 0,
    alerts_count INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    engine_version TEXT
);

CREATE INDEX IF NOT EXISTS idx_scanner_runs_date ON scanner_runs(trade_date DESC);

CREATE TABLE IF NOT EXISTS pattern_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    trade_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    pattern_type TEXT NOT NULL,
    macro_pass INTEGER NOT NULL DEFAULT 0,
    score REAL NOT NULL,
    triggered_today INTEGER NOT NULL DEFAULT 0,
    setup_ready INTEGER NOT NULL DEFAULT 0,
    details_json TEXT,
    FOREIGN KEY (run_id) REFERENCES scanner_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_pattern_signals_date ON pattern_signals(trade_date, pattern_type, score DESC);
CREATE INDEX IF NOT EXISTS idx_pattern_signals_ticker ON pattern_signals(ticker, trade_date);
CREATE INDEX IF NOT EXISTS idx_pattern_signals_run ON pattern_signals(run_id);

CREATE TABLE IF NOT EXISTS signal_outcomes (
    signal_id INTEGER PRIMARY KEY,
    trade_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    pattern_type TEXT NOT NULL,
    entry_close REAL,
    return_1d_pct REAL,
    return_3d_pct REAL,
    return_5d_pct REAL,
    return_10d_pct REAL,
    return_20d_pct REAL,
    return_to_last_pct REAL,
    max_favorable_pct REAL,
    max_adverse_pct REAL,
    trading_days_forward INTEGER,
    evaluated_at TEXT NOT NULL,
    FOREIGN KEY (signal_id) REFERENCES pattern_signals(id)
);

CREATE INDEX IF NOT EXISTS idx_signal_outcomes_date
    ON signal_outcomes(trade_date DESC, pattern_type);
CREATE INDEX IF NOT EXISTS idx_signal_outcomes_ticker
    ON signal_outcomes(ticker, trade_date);

CREATE TABLE IF NOT EXISTS company_fundamentals (
    ticker TEXT PRIMARY KEY,
    isin TEXT,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS institutional_flows (
    flow_type TEXT NOT NULL,
    data_type TEXT NOT NULL,
    interval_code TEXT NOT NULL,
    record_ts INTEGER NOT NULL,
    buy_amount REAL,
    sell_amount REAL,
    net_amount REAL,
    buy_contracts INTEGER,
    sell_contracts INTEGER,
    oi_contracts INTEGER,
    oi_amount REAL,
    payload_json TEXT,
    synced_at TEXT NOT NULL,
    PRIMARY KEY (flow_type, data_type, interval_code, record_ts)
);

CREATE INDEX IF NOT EXISTS idx_institutional_flows_ts
    ON institutional_flows(record_ts DESC);

CREATE TABLE IF NOT EXISTS derivative_snapshots (
    instrument_key TEXT NOT NULL,
    symbol TEXT NOT NULL,
    expiry TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    total_call_oi INTEGER,
    total_put_oi INTEGER,
    spot_close REAL,
    pcr REAL,
    max_pain_strike REAL,
    oi_payload_json TEXT,
    change_oi_payload_json TEXT,
    pcr_payload_json TEXT,
    max_pain_payload_json TEXT,
    synced_at TEXT NOT NULL,
    PRIMARY KEY (instrument_key, expiry, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_derivative_snapshots_date
    ON derivative_snapshots(trade_date DESC, symbol);

CREATE TABLE IF NOT EXISTS news_channels (
    channel_key TEXT PRIMARY KEY,
    channel_id TEXT,
    title TEXT,
    last_message_id INTEGER,
    last_synced_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS telegram_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_key TEXT NOT NULL,
    channel_id TEXT,
    message_id INTEGER NOT NULL,
    posted_at TEXT NOT NULL,
    text TEXT,
    raw_json TEXT,
    processed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(channel_key, message_id)
);

CREATE INDEX IF NOT EXISTS idx_telegram_messages_posted
    ON telegram_messages(channel_key, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_telegram_messages_processed
    ON telegram_messages(processed, id);

CREATE TABLE IF NOT EXISTS news_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_pk INTEGER NOT NULL,
    ticker TEXT,
    company_name_matched TEXT,
    match_confidence REAL,
    event_date TEXT,
    sentiment TEXT,
    themes_json TEXT,
    summary TEXT,
    gemini_extract_json TEXT,
    outlook_json TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (message_pk) REFERENCES telegram_messages(id)
);

CREATE INDEX IF NOT EXISTS idx_news_events_date ON news_events(event_date DESC);
CREATE INDEX IF NOT EXISTS idx_news_events_ticker ON news_events(ticker, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_news_events_status ON news_events(status, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_news_events_message ON news_events(message_pk);

CREATE TABLE IF NOT EXISTS news_reactions (
    event_id INTEGER NOT NULL,
    horizon TEXT NOT NULL,
    return_pct REAL,
    rel_return_pct REAL,
    close_price REAL,
    trade_date TEXT,
    PRIMARY KEY (event_id, horizon),
    FOREIGN KEY (event_id) REFERENCES news_events(id)
);

CREATE INDEX IF NOT EXISTS idx_news_reactions_event ON news_reactions(event_id);

CREATE TABLE IF NOT EXISTS myb_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    strategy TEXT NOT NULL DEFAULT 'multi_year_breakout',
    lookback_years INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    symbols_scanned INTEGER DEFAULT 0,
    alerts_count INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    params_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_myb_runs_date ON myb_runs(trade_date DESC, strategy, lookback_years);

CREATE TABLE IF NOT EXISTS myb_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    trade_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    sector TEXT,
    company_name TEXT,
    strategy TEXT NOT NULL DEFAULT 'multi_year_breakout',
    status TEXT NOT NULL,
    lookback_years INTEGER NOT NULL,
    prior_high REAL NOT NULL,
    prior_high_date TEXT,
    years_since_high REAL,
    close_price REAL NOT NULL,
    breakout_pct REAL,
    drop_from_ath_pct REAL,
    rvol20 REAL,
    rsi14 REAL,
    avg_turnover_inr REAL,
    score REAL NOT NULL,
    details_json TEXT,
    FOREIGN KEY (run_id) REFERENCES myb_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_myb_signals_date ON myb_signals(trade_date, strategy, score DESC);
CREATE INDEX IF NOT EXISTS idx_myb_signals_run ON myb_signals(run_id);

CREATE TABLE IF NOT EXISTS index_candles (
    instrument_token TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    ts TEXT NOT NULL,
    open_price REAL,
    high_price REAL,
    low_price REAL,
    close_price REAL,
    volume INTEGER,
    oi INTEGER,
    source TEXT,
    PRIMARY KEY (instrument_token, timeframe, ts)
);

CREATE INDEX IF NOT EXISTS idx_index_candles_tf_ts
    ON index_candles(instrument_token, timeframe, ts);

CREATE TABLE IF NOT EXISTS grimes_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    universe_size INTEGER DEFAULT 0,
    analyzed INTEGER DEFAULT 0,
    workers INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    engine_version TEXT,
    summary_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_grimes_runs_date ON grimes_runs(trade_date DESC, status);

CREATE TABLE IF NOT EXISTS grimes_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    trade_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    instrument_key TEXT NOT NULL,
    kind TEXT,
    company_name TEXT,
    as_of TEXT,
    price REAL,
    regime TEXT,
    setup_type TEXT,
    setup_group TEXT,
    quality_score INTEGER,
    payload_json TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES grimes_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_grimes_signals_run ON grimes_signals(run_id);
CREATE INDEX IF NOT EXISTS idx_grimes_signals_date ON grimes_signals(trade_date, quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_grimes_signals_ticker ON grimes_signals(ticker, trade_date);

CREATE TABLE IF NOT EXISTS live_minute_bars (
    instrument_key TEXT NOT NULL,
    minute_ts TEXT NOT NULL,
    volume INTEGER,
    close_price REAL,
    source TEXT,
    open_price REAL,
    high_price REAL,
    low_price REAL,
    PRIMARY KEY (instrument_key, minute_ts)
);

CREATE INDEX IF NOT EXISTS idx_live_minute_bars_ts
    ON live_minute_bars(minute_ts);

CREATE TABLE IF NOT EXISTS futures_oi_daily (
    trade_date TEXT NOT NULL,
    instrument_key TEXT NOT NULL,
    symbol TEXT NOT NULL,
    expiry TEXT,
    oi REAL,
    poi REAL,
    ltp REAL,
    prev_close REAL,
    source TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (trade_date, instrument_key)
);

CREATE INDEX IF NOT EXISTS idx_futures_oi_daily_symbol
    ON futures_oi_daily(symbol, trade_date DESC);

CREATE TABLE IF NOT EXISTS live_call_journal (
    session_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    kind TEXT,
    company_name TEXT,
    stance TEXT,
    entry REAL NOT NULL,
    stop REAL NOT NULL,
    exit_price REAL NOT NULL,
    status TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    entry_at TEXT,
    closed_at TEXT,
    last_price REAL,
    result_pct REAL,
    mfe_pct REAL,
    mae_pct REAL,
    updated_at TEXT NOT NULL,
    fill_price REAL,
    swing_exit REAL,
    swing_status TEXT,
    swing_result_pct REAL,
    swing_closed_at TEXT,
    segment TEXT,
    PRIMARY KEY (session_date, symbol, side)
);

CREATE INDEX IF NOT EXISTS idx_live_call_journal_status
    ON live_call_journal(session_date, status);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chunks(items: list[Any], size: int) -> Iterator[list[Any]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


class TimelineStore:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connection() as conn:
            conn.executescript(SCHEMA_SQL)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(security_profiles)")}
            if "ingest_skip" not in cols:
                conn.execute(
                    "ALTER TABLE security_profiles ADD COLUMN ingest_skip INTEGER NOT NULL DEFAULT 0"
                )
            if "ingest_skip_reason" not in cols:
                conn.execute(
                    "ALTER TABLE security_profiles ADD COLUMN ingest_skip_reason TEXT"
                )
            run_cols = {row[1] for row in conn.execute("PRAGMA table_info(scanner_runs)")}
            if "engine_version" not in run_cols:
                conn.execute("ALTER TABLE scanner_runs ADD COLUMN engine_version TEXT")

            myb_run_cols = {row[1] for row in conn.execute("PRAGMA table_info(myb_runs)")}
            if myb_run_cols:
                if "strategy" not in myb_run_cols:
                    conn.execute(
                        "ALTER TABLE myb_runs ADD COLUMN strategy TEXT NOT NULL DEFAULT 'multi_year_breakout'"
                    )
                if "params_json" not in myb_run_cols:
                    conn.execute("ALTER TABLE myb_runs ADD COLUMN params_json TEXT")

            myb_sig_cols = {row[1] for row in conn.execute("PRAGMA table_info(myb_signals)")}
            if myb_sig_cols:
                alter_sigs = {
                    "strategy": "TEXT NOT NULL DEFAULT 'multi_year_breakout'",
                    "drop_from_ath_pct": "REAL",
                    "rsi14": "REAL",
                    "avg_turnover_inr": "REAL",
                }
                for col, decl in alter_sigs.items():
                    if col not in myb_sig_cols:
                        conn.execute(f"ALTER TABLE myb_signals ADD COLUMN {col} {decl}")

            journal_cols = {row[1] for row in conn.execute("PRAGMA table_info(live_call_journal)")}
            if journal_cols and "fill_price" not in journal_cols:
                conn.execute("ALTER TABLE live_call_journal ADD COLUMN fill_price REAL")
            for column, decl in (
                ("swing_exit", "REAL"),
                ("swing_status", "TEXT"),
                ("swing_result_pct", "REAL"),
                ("swing_closed_at", "TEXT"),
                ("segment", "TEXT"),
            ):
                if journal_cols and column not in journal_cols:
                    conn.execute(f"ALTER TABLE live_call_journal ADD COLUMN {column} {decl}")
            minute_cols = {row[1] for row in conn.execute("PRAGMA table_info(live_minute_bars)")}
            for column in ("open_price", "high_price", "low_price"):
                if minute_cols and column not in minute_cols:
                    conn.execute(f"ALTER TABLE live_minute_bars ADD COLUMN {column} REAL")

    def upsert_profiles(self, profiles: list[dict[str, Any]]) -> int:
        if not profiles:
            return 0
        now = _utc_now()
        rows = [
            (
                p["instrument_token"],
                p["ticker"],
                p.get("company_name"),
                p.get("sector"),
                p.get("industry"),
                p.get("isin"),
                p.get("series"),
                now,
            )
            for p in profiles
        ]
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO security_profiles (
                    instrument_token, ticker, company_name, sector, industry,
                    isin, series, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instrument_token) DO UPDATE SET
                    ticker = excluded.ticker,
                    company_name = COALESCE(excluded.company_name, security_profiles.company_name),
                    sector = COALESCE(excluded.sector, security_profiles.sector),
                    industry = COALESCE(excluded.industry, security_profiles.industry),
                    isin = COALESCE(excluded.isin, security_profiles.isin),
                    series = COALESCE(excluded.series, security_profiles.series),
                    updated_at = excluded.updated_at
                """,
                rows,
            )
        return len(rows)

    def update_sectors(self, sector_by_ticker: dict[str, tuple[str | None, str | None]]) -> int:
        if not sector_by_ticker:
            return 0
        now = _utc_now()
        updated = 0
        with self.connection() as conn:
            for ticker, (sector, industry) in sector_by_ticker.items():
                conn.execute(
                    """
                    UPDATE security_profiles
                    SET sector = COALESCE(?, sector),
                        industry = COALESCE(?, industry),
                        updated_at = ?
                    WHERE ticker = ?
                    """,
                    (sector, industry, now, ticker),
                )
                updated += conn.total_changes
        return updated

    def set_ingest_skip(
        self,
        ticker: str,
        skip: bool,
        reason: str | None = None,
    ) -> bool:
        now = _utc_now()
        with self.connection() as conn:
            cur = conn.execute(
                """
                UPDATE security_profiles
                SET ingest_skip = ?, ingest_skip_reason = ?, updated_at = ?
                WHERE ticker = ?
                """,
                (1 if skip else 0, reason if skip else None, now, ticker.upper()),
            )
        return cur.rowcount > 0

    def migrate_instrument_token(self, old_token: str, new_token: str) -> None:
        if old_token == new_token:
            return
        with self.connection() as conn:
            conn.execute(
                """
                DELETE FROM daily_candles
                WHERE instrument_token = ? AND trade_date IN (
                    SELECT trade_date FROM daily_candles WHERE instrument_token = ?
                )
                """,
                (old_token, new_token),
            )
            conn.execute(
                "UPDATE daily_candles SET instrument_token = ? WHERE instrument_token = ?",
                (new_token, old_token),
            )
            conn.execute(
                "DELETE FROM security_profiles WHERE instrument_token = ?",
                (old_token,),
            )

    def upsert_candles(self, candles: list[dict[str, Any]]) -> int:
        if not candles:
            return 0
        rows = [
            (
                c["trade_date"],
                c["instrument_token"],
                c.get("open_price"),
                c.get("high_price"),
                c.get("low_price"),
                c.get("close_price"),
                c.get("volume"),
                c.get("daily_return_pct"),
                c.get("source"),
            )
            for c in candles
        ]
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO daily_candles (
                    trade_date, instrument_token, open_price, high_price,
                    low_price, close_price, volume, daily_return_pct, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_date, instrument_token) DO UPDATE SET
                    open_price = excluded.open_price,
                    high_price = excluded.high_price,
                    low_price = excluded.low_price,
                    close_price = excluded.close_price,
                    volume = excluded.volume,
                    daily_return_pct = excluded.daily_return_pct,
                    source = excluded.source
                """,
                rows,
            )
        return len(rows)

    def upsert_index_candles(self, candles: list[dict[str, Any]]) -> int:
        if not candles:
            return 0
        rows = [
            (
                c["instrument_token"],
                c["timeframe"],
                c["ts"],
                c.get("open_price"),
                c.get("high_price"),
                c.get("low_price"),
                c.get("close_price"),
                c.get("volume"),
                c.get("oi"),
                c.get("source"),
            )
            for c in candles
        ]
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO index_candles (
                    instrument_token, timeframe, ts, open_price, high_price,
                    low_price, close_price, volume, oi, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instrument_token, timeframe, ts) DO UPDATE SET
                    open_price = excluded.open_price,
                    high_price = excluded.high_price,
                    low_price = excluded.low_price,
                    close_price = excluded.close_price,
                    volume = excluded.volume,
                    oi = excluded.oi,
                    source = excluded.source
                """,
                rows,
            )
        return len(rows)

    def get_index_candles(
        self,
        instrument_token: str,
        timeframe: str,
        *,
        from_ts: str | None = None,
        to_ts: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["instrument_token = ?", "timeframe = ?"]
        params: list[Any] = [instrument_token, timeframe]
        if from_ts:
            clauses.append("ts >= ?")
            params.append(from_ts)
        if to_ts:
            clauses.append("ts <= ?")
            params.append(to_ts)

        # When limited, return the most recent N bars in ascending order.
        if limit is not None and limit > 0:
            sql = f"""
                SELECT ts, open_price AS open, high_price AS high, low_price AS low,
                       close_price AS close, volume, oi, source
                FROM (
                    SELECT ts, open_price, high_price, low_price, close_price, volume, oi, source
                    FROM index_candles
                    WHERE {' AND '.join(clauses)}
                    ORDER BY ts DESC
                    LIMIT ?
                ) AS recent
                ORDER BY ts ASC
            """
            params.append(limit)
        else:
            sql = f"""
                SELECT ts, open_price AS open, high_price AS high, low_price AS low,
                       close_price AS close, volume, oi, source
                FROM index_candles
                WHERE {' AND '.join(clauses)}
                ORDER BY ts ASC
            """
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def index_candle_stats(
        self,
        instrument_token: str,
        *,
        timeframe: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["instrument_token = ?"]
        params: list[Any] = [instrument_token]
        if timeframe:
            clauses.append("timeframe = ?")
            params.append(timeframe)
        sql = f"""
            SELECT timeframe,
                   COUNT(*) AS count,
                   MIN(ts) AS min_ts,
                   MAX(ts) AS max_ts
            FROM index_candles
            WHERE {' AND '.join(clauses)}
            GROUP BY timeframe
            ORDER BY timeframe
        """
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def list_profiles(
        self,
        *,
        sector: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses = ["1=1"]
        params: list[Any] = []
        if sector:
            clauses.append("sector = ?")
            params.append(sector)
        sql = f"""
            SELECT instrument_token, ticker, company_name, sector, industry, isin, series,
                   COALESCE(ingest_skip, 0) AS ingest_skip, ingest_skip_reason
            FROM security_profiles
            WHERE {' AND '.join(clauses)}
            ORDER BY ticker
        """
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_profile_by_ticker(self, ticker: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM security_profiles WHERE ticker = ?",
                (ticker.upper(),),
            ).fetchone()
        return dict(row) if row else None

    def list_sectors(self) -> list[str]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT sector FROM security_profiles
                WHERE sector IS NOT NULL AND sector != ''
                ORDER BY sector
                """
            ).fetchall()
        return [row["sector"] for row in rows]

    def list_trade_dates(self, limit: int = 365) -> list[str]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT trade_date FROM daily_candles
                ORDER BY trade_date DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [row["trade_date"] for row in rows]

    def delete_candles_for_date(self, trade_date: str) -> int:
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM daily_candles WHERE trade_date = ?",
                (trade_date,),
            )
            return cursor.rowcount

    def query_movers(
        self,
        trade_date: str,
        *,
        sector: str | None = None,
        min_move_pct: float = 0.0,
        direction: str = "both",
        ticker: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses = ["c.trade_date = ?"]
        params: list[Any] = [trade_date]

        if ticker:
            clauses.append("p.ticker = ?")
            params.append(ticker.strip().upper())
        elif sector:
            clauses.append("p.sector = ?")
            params.append(sector)

        if not ticker:
            if direction == "up":
                clauses.append("c.daily_return_pct >= ?")
                params.append(min_move_pct)
            elif direction == "down":
                clauses.append("c.daily_return_pct <= ?")
                params.append(-min_move_pct)
            else:
                clauses.append("ABS(c.daily_return_pct) >= ?")
                params.append(min_move_pct)

        where = " AND ".join(clauses)
        count_sql = f"""
            SELECT COUNT(*) AS cnt
            FROM daily_candles c
            JOIN security_profiles p ON c.instrument_token = p.instrument_token
            WHERE {where}
        """
        data_sql = f"""
            SELECT
                p.ticker,
                p.company_name,
                p.sector,
                p.industry,
                c.trade_date,
                c.open_price,
                c.high_price,
                c.low_price,
                c.close_price,
                c.volume,
                c.daily_return_pct,
                c.source
            FROM daily_candles c
            JOIN security_profiles p ON c.instrument_token = p.instrument_token
            WHERE {where}
            ORDER BY c.daily_return_pct DESC
            LIMIT ? OFFSET ?
        """
        with self.connection() as conn:
            total = conn.execute(count_sql, params).fetchone()["cnt"]
            rows = conn.execute(data_sql, [*params, limit, offset]).fetchall()
        return [dict(row) for row in rows], total

    def get_candles_for_ticker(
        self,
        ticker: str,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        profile = self.get_profile_by_ticker(ticker)
        if not profile:
            return []

        clauses = ["c.instrument_token = ?"]
        params: list[Any] = [profile["instrument_token"]]

        if from_date:
            clauses.append("c.trade_date >= ?")
            params.append(from_date)
        if to_date:
            clauses.append("c.trade_date <= ?")
            params.append(to_date)

        sql = f"""
            SELECT
                c.trade_date AS date,
                c.open_price AS open,
                c.high_price AS high,
                c.low_price AS low,
                c.close_price AS close,
                c.volume,
                c.daily_return_pct,
                c.source
            FROM daily_candles c
            WHERE {' AND '.join(clauses)}
            ORDER BY c.trade_date ASC
        """
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_last_trade_dates(self) -> dict[str, str]:
        """Map instrument_token -> latest trade_date (YYYY-MM-DD).

        Live-feed EOD candles are provisional (close is the last print, not the
        official close), so they do not count: the next ingest overwrites them.
        """
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT instrument_token, MAX(trade_date) AS last_date
                FROM daily_candles
                WHERE COALESCE(source, '') != 'live_ws'
                GROUP BY instrument_token
                """
            ).fetchall()
        return {row["instrument_token"]: row["last_date"] for row in rows}

    def stats(self) -> dict[str, Any]:
        target_trade_date = expected_latest_session()
        with self.connection() as conn:
            profile_count = conn.execute("SELECT COUNT(*) AS cnt FROM security_profiles").fetchone()["cnt"]
            ingest_skip_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM security_profiles WHERE COALESCE(ingest_skip, 0) = 1"
            ).fetchone()["cnt"]
            candle_count = conn.execute("SELECT COUNT(*) AS cnt FROM daily_candles").fetchone()["cnt"]
            sector_count = conn.execute(
                "SELECT COUNT(DISTINCT sector) AS cnt FROM security_profiles WHERE sector IS NOT NULL"
            ).fetchone()["cnt"]
            date_range = conn.execute(
                "SELECT MIN(trade_date) AS min_date, MAX(trade_date) AS max_date FROM daily_candles"
            ).fetchone()
            symbols_with_data = conn.execute(
                "SELECT COUNT(DISTINCT instrument_token) AS cnt FROM daily_candles"
            ).fetchone()["cnt"]
            flow_count = conn.execute("SELECT COUNT(*) AS cnt FROM institutional_flows").fetchone()["cnt"]
            derivative_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM derivative_snapshots"
            ).fetchone()["cnt"]

            max_trade_date = date_range["max_date"]
            symbols_at_max_date = 0
            symbols_behind_target = 0
            if max_trade_date:
                symbols_at_max_date = conn.execute(
                    "SELECT COUNT(DISTINCT instrument_token) AS cnt FROM daily_candles WHERE trade_date = ?",
                    (max_trade_date,),
                ).fetchone()["cnt"]
                symbols_behind_target = conn.execute(
                    """
                    SELECT COUNT(*) AS cnt FROM (
                        SELECT p.instrument_token
                        FROM security_profiles p
                        LEFT JOIN daily_candles c ON c.instrument_token = p.instrument_token
                        WHERE COALESCE(p.ingest_skip, 0) = 0
                        GROUP BY p.instrument_token
                        HAVING MAX(c.trade_date) IS NULL OR MAX(c.trade_date) < ?
                    )
                    """,
                    (target_trade_date,),
                ).fetchone()["cnt"]

        is_up_to_date = bool(max_trade_date and max_trade_date >= target_trade_date)

        return {
            "db_path": str(self.db_path),
            "profile_count": profile_count,
            "candle_count": candle_count,
            "sector_count": sector_count,
            "symbols_with_data": symbols_with_data,
            "min_trade_date": date_range["min_date"],
            "max_trade_date": max_trade_date,
            "target_trade_date": target_trade_date,
            "is_up_to_date": is_up_to_date,
            "symbols_at_max_date": symbols_at_max_date,
            "symbols_behind_target": symbols_behind_target,
            "ingest_skip_count": ingest_skip_count,
            "institutional_flow_count": flow_count,
            "derivative_snapshot_count": derivative_count,
        }

    def get_recent_candles_for_scan(
        self,
        ticker: str,
        *,
        limit: int = 280,
        as_of_date: str | None = None,
        instrument_token: str | None = None,
    ) -> list[dict[str, Any]]:
        token = instrument_token
        if not token:
            profile = self.get_profile_by_ticker(ticker)
            if not profile:
                return []
            token = profile["instrument_token"]

        params: list[Any] = [token]
        date_clause = ""
        if as_of_date:
            date_clause = "AND c.trade_date <= ?"
            params.append(as_of_date)

        sql = f"""
            SELECT
                c.trade_date AS date,
                c.open_price AS open,
                c.high_price AS high,
                c.low_price AS low,
                c.close_price AS close,
                c.volume,
                c.daily_return_pct
            FROM daily_candles c
            WHERE c.instrument_token = ? {date_clause}
            ORDER BY c.trade_date DESC
            LIMIT ?
        """
        params.append(limit)
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in reversed(rows)]

    def list_scan_eligible_tickers(
        self,
        *,
        min_bars: int = 250,
        as_of_date: str | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        date_clause = ""
        if as_of_date:
            date_clause = "WHERE c.trade_date <= ?"
            params.append(as_of_date)
        params.append(min_bars)

        sql = f"""
            SELECT p.ticker, p.company_name, p.sector, p.instrument_token, COUNT(*) AS bar_count
            FROM daily_candles c
            JOIN security_profiles p ON c.instrument_token = p.instrument_token
            {date_clause}
            GROUP BY p.instrument_token
            HAVING COUNT(*) >= ?
            ORDER BY p.ticker
        """
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_candles_bulk_for_scan(
        self,
        *,
        min_bars: int = 250,
        as_of_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Load OHLCV rows for symbols with at least min_bars history."""
        if as_of_date:
            params: list[Any] = [as_of_date, min_bars, as_of_date]
            eligible_filter = "WHERE trade_date <= ?"
            candle_filter = "AND c.trade_date <= ?"
        else:
            params = [min_bars]
            eligible_filter = ""
            candle_filter = ""

        sql = f"""
            WITH eligible AS (
                SELECT instrument_token
                FROM daily_candles
                {eligible_filter}
                GROUP BY instrument_token
                HAVING COUNT(*) >= ?
            )
            SELECT
                p.ticker,
                p.company_name,
                p.sector,
                p.instrument_token,
                c.trade_date AS date,
                c.open_price AS open,
                c.high_price AS high,
                c.low_price AS low,
                c.close_price AS close,
                c.volume
            FROM daily_candles c
            JOIN security_profiles p ON c.instrument_token = p.instrument_token
            JOIN eligible e ON c.instrument_token = e.instrument_token
            WHERE 1=1 {candle_filter}
            ORDER BY p.ticker ASC, c.trade_date ASC
        """
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_recent_candles_window_for_scan(
        self,
        *,
        min_bars: int = 250,
        limit: int = 680,
        as_of_date: str | None = None,
        instrument_tokens: list[str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Load recent OHLCV bars for scan-eligible tickers in one (or few) queries.

        Returns ``{ticker: [oldest ... newest candle dicts]}`` capped at ``limit``
        bars per ticker. Prefer ``instrument_tokens`` from ``list_scan_eligible_tickers``
        to avoid a second universe aggregation.
        """
        window = max(1, int(limit))
        tokens = [t for t in (instrument_tokens or []) if t]
        by_ticker: dict[str, list[dict[str, Any]]] = {}

        # Calendar pad (~1.75x) so weekends/holidays still yield ``window`` sessions.
        as_of = as_of_date or date.today().isoformat()
        start_date = (date.fromisoformat(as_of[:10]) - timedelta(days=int(window * 1.75))).isoformat()

        def _ingest(rows: list[Any]) -> None:
            for row in rows:
                item = dict(row)
                ticker = item.pop("ticker")
                bucket = by_ticker.setdefault(ticker, [])
                bucket.append(item)

        def _trim() -> None:
            for ticker, rows in by_ticker.items():
                if len(rows) > window:
                    by_ticker[ticker] = rows[-window:]

        if tokens:
            # Chunk IN-lists to keep query plans lean on large universes.
            chunk_size = 400
            with self.connection() as conn:
                conn.execute("PRAGMA temp_store=MEMORY")
                for i in range(0, len(tokens), chunk_size):
                    chunk = tokens[i : i + chunk_size]
                    placeholders = ",".join("?" for _ in chunk)
                    params: list[Any] = [*chunk, start_date, as_of]
                    sql = f"""
                        SELECT
                            p.ticker,
                            c.trade_date AS date,
                            c.open_price AS open,
                            c.high_price AS high,
                            c.low_price AS low,
                            c.close_price AS close,
                            c.volume
                        FROM daily_candles c
                        JOIN security_profiles p ON c.instrument_token = p.instrument_token
                        WHERE c.instrument_token IN ({placeholders})
                          AND c.trade_date >= ?
                          AND c.trade_date <= ?
                        ORDER BY p.ticker ASC, c.trade_date ASC
                    """
                    _ingest(conn.execute(sql, params).fetchall())
            _trim()
            return by_ticker

        if as_of_date:
            params = [as_of_date, min_bars, start_date, as_of_date]
            eligible_filter = "WHERE trade_date <= ?"
        else:
            params = [min_bars, start_date, as_of]
            eligible_filter = ""
        sql = f"""
            WITH eligible AS (
                SELECT instrument_token
                FROM daily_candles
                {eligible_filter}
                GROUP BY instrument_token
                HAVING COUNT(*) >= ?
            )
            SELECT
                p.ticker,
                c.trade_date AS date,
                c.open_price AS open,
                c.high_price AS high,
                c.low_price AS low,
                c.close_price AS close,
                c.volume
            FROM daily_candles c
            JOIN security_profiles p ON c.instrument_token = p.instrument_token
            JOIN eligible e ON c.instrument_token = e.instrument_token
            WHERE c.trade_date >= ?
              AND c.trade_date <= ?
            ORDER BY p.ticker ASC, c.trade_date ASC
        """
        with self.connection() as conn:
            conn.execute("PRAGMA temp_store=MEMORY")
            _ingest(conn.execute(sql, params).fetchall())
        _trim()
        return by_ticker

    def create_scanner_run(self, trade_date: str, *, engine_version: str | None = None) -> int:
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO scanner_runs (trade_date, started_at, status, engine_version)
                VALUES (?, ?, 'running', ?)
                """,
                (trade_date, _utc_now(), engine_version),
            )
            return int(cur.lastrowid)

    def finish_scanner_run(
        self,
        run_id: int,
        *,
        symbols_scanned: int,
        alerts_count: int,
        status: str = "completed",
        engine_version: str | None = None,
    ) -> None:
        with self.connection() as conn:
            if engine_version is not None:
                conn.execute(
                    """
                    UPDATE scanner_runs
                    SET finished_at = ?, symbols_scanned = ?, alerts_count = ?,
                        status = ?, engine_version = ?
                    WHERE id = ?
                    """,
                    (_utc_now(), symbols_scanned, alerts_count, status, engine_version, run_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE scanner_runs
                    SET finished_at = ?, symbols_scanned = ?, alerts_count = ?, status = ?
                    WHERE id = ?
                    """,
                    (_utc_now(), symbols_scanned, alerts_count, status, run_id),
                )

    def delete_scanner_data_for_date(self, trade_date: str) -> dict[str, int]:
        """Remove prior runs/signals/outcomes for a trade date before a fresh rescan."""
        with self.connection() as conn:
            outcomes_deleted = conn.execute(
                """
                DELETE FROM signal_outcomes
                WHERE signal_id IN (
                    SELECT id FROM pattern_signals WHERE trade_date = ?
                )
                """,
                (trade_date,),
            ).rowcount
            signals_deleted = conn.execute(
                "DELETE FROM pattern_signals WHERE trade_date = ?",
                (trade_date,),
            ).rowcount
            runs_deleted = conn.execute(
                "DELETE FROM scanner_runs WHERE trade_date = ?",
                (trade_date,),
            ).rowcount
        return {
            "signal_outcomes_deleted": int(outcomes_deleted),
            "pattern_signals_deleted": int(signals_deleted),
            "scanner_runs_deleted": int(runs_deleted),
        }

    def delete_pattern_signals_for_run(self, run_id: int) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                DELETE FROM signal_outcomes
                WHERE signal_id IN (
                    SELECT id FROM pattern_signals WHERE run_id = ?
                )
                """,
                (run_id,),
            )
            conn.execute("DELETE FROM pattern_signals WHERE run_id = ?", (run_id,))

    def clear_scanner_data(self) -> dict[str, int]:
        """Remove all momentum scanner runs, pattern signals, and outcomes."""
        with self.connection() as conn:
            outcomes_deleted = conn.execute("DELETE FROM signal_outcomes").rowcount
            signals_deleted = conn.execute("DELETE FROM pattern_signals").rowcount
            runs_deleted = conn.execute("DELETE FROM scanner_runs").rowcount
        return {
            "signal_outcomes_deleted": int(outcomes_deleted),
            "pattern_signals_deleted": int(signals_deleted),
            "scanner_runs_deleted": int(runs_deleted),
        }

    def upsert_signal_outcome(self, outcome: dict[str, Any]) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO signal_outcomes (
                    signal_id, trade_date, ticker, pattern_type, entry_close,
                    return_1d_pct, return_3d_pct, return_5d_pct, return_10d_pct,
                    return_20d_pct, return_to_last_pct, max_favorable_pct,
                    max_adverse_pct, trading_days_forward, evaluated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(signal_id) DO UPDATE SET
                    trade_date = excluded.trade_date,
                    ticker = excluded.ticker,
                    pattern_type = excluded.pattern_type,
                    entry_close = excluded.entry_close,
                    return_1d_pct = excluded.return_1d_pct,
                    return_3d_pct = excluded.return_3d_pct,
                    return_5d_pct = excluded.return_5d_pct,
                    return_10d_pct = excluded.return_10d_pct,
                    return_20d_pct = excluded.return_20d_pct,
                    return_to_last_pct = excluded.return_to_last_pct,
                    max_favorable_pct = excluded.max_favorable_pct,
                    max_adverse_pct = excluded.max_adverse_pct,
                    trading_days_forward = excluded.trading_days_forward,
                    evaluated_at = excluded.evaluated_at
                """,
                (
                    int(outcome["signal_id"]),
                    outcome["trade_date"],
                    outcome["ticker"],
                    outcome["pattern_type"],
                    outcome.get("entry_close"),
                    outcome.get("return_1d_pct"),
                    outcome.get("return_3d_pct"),
                    outcome.get("return_5d_pct"),
                    outcome.get("return_10d_pct"),
                    outcome.get("return_20d_pct"),
                    outcome.get("return_to_last_pct"),
                    outcome.get("max_favorable_pct"),
                    outcome.get("max_adverse_pct"),
                    outcome.get("trading_days_forward"),
                    outcome.get("evaluated_at") or _utc_now(),
                ),
            )

    def upsert_signal_outcomes(self, outcomes: list[dict[str, Any]]) -> int:
        for row in outcomes:
            self.upsert_signal_outcome(row)
        return len(outcomes)

    def list_pattern_signals_for_outcomes(
        self,
        *,
        trade_date_from: str | None = None,
        trade_date_to: str | None = None,
        limit: int = 50_000,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if trade_date_from:
            clauses.append("ps.trade_date >= ?")
            params.append(trade_date_from)
        if trade_date_to:
            clauses.append("ps.trade_date <= ?")
            params.append(trade_date_to)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT
                ps.id AS signal_id,
                ps.run_id,
                ps.trade_date,
                ps.ticker,
                ps.pattern_type,
                ps.macro_pass,
                ps.score,
                ps.triggered_today,
                ps.setup_ready,
                ps.details_json,
                c.close_price AS close
            FROM pattern_signals ps
            LEFT JOIN security_profiles p ON p.ticker = ps.ticker
            LEFT JOIN daily_candles c
                ON c.trade_date = ps.trade_date
               AND c.instrument_token = p.instrument_token
            {where}
            ORDER BY ps.trade_date ASC, ps.id ASC
            LIMIT ?
        """
        params.append(int(limit))
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            raw = item.pop("details_json", None)
            try:
                item["details"] = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                item["details"] = {}
            item["macro_pass"] = bool(item.get("macro_pass"))
            item["triggered_today"] = bool(item.get("triggered_today"))
            item["setup_ready"] = bool(item.get("setup_ready"))
            out.append(item)
        return out

    def list_signal_outcomes(
        self,
        *,
        trade_date_from: str | None = None,
        trade_date_to: str | None = None,
        limit: int = 50_000,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if trade_date_from:
            clauses.append("trade_date >= ?")
            params.append(trade_date_from)
        if trade_date_to:
            clauses.append("trade_date <= ?")
            params.append(trade_date_to)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT * FROM signal_outcomes
            {where}
            ORDER BY trade_date DESC, signal_id DESC
            LIMIT ?
        """
        params.append(int(limit))
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def signal_outcomes_stats(self) -> dict[str, Any]:
        with self.connection() as conn:
            total = conn.execute("SELECT COUNT(*) AS cnt FROM signal_outcomes").fetchone()["cnt"]
            with_5d = conn.execute(
                "SELECT COUNT(*) AS cnt FROM signal_outcomes WHERE return_5d_pct IS NOT NULL"
            ).fetchone()["cnt"]
            avg_5d = conn.execute(
                "SELECT AVG(return_5d_pct) AS v FROM signal_outcomes WHERE return_5d_pct IS NOT NULL"
            ).fetchone()["v"]
            win_5d = conn.execute(
                """
                SELECT AVG(CASE WHEN return_5d_pct > 0 THEN 1.0 ELSE 0.0 END) AS v
                FROM signal_outcomes WHERE return_5d_pct IS NOT NULL
                """
            ).fetchone()["v"]
        return {
            "outcome_count": int(total),
            "with_return_5d": int(with_5d),
            "avg_return_5d_pct": round(float(avg_5d), 4) if avg_5d is not None else None,
            "win_rate_5d_pct": round(float(win_5d) * 100, 2) if win_5d is not None else None,
        }

    def insert_pattern_signals(self, signals: list[dict[str, Any]]) -> int:
        if not signals:
            return 0
        rows = [
            (
                s["run_id"],
                s["trade_date"],
                s["ticker"],
                s["pattern_type"],
                1 if s.get("macro_pass") else 0,
                s["score"],
                1 if s.get("triggered_today") else 0,
                1 if s.get("setup_ready") else 0,
                json.dumps(s.get("details") or {}),
            )
            for s in signals
        ]
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO pattern_signals (
                    run_id, trade_date, ticker, pattern_type, macro_pass, score,
                    triggered_today, setup_ready, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def get_latest_scanner_run(self, trade_date: str | None = None) -> dict[str, Any] | None:
        with self.connection() as conn:
            if trade_date:
                row = conn.execute(
                    """
                    SELECT * FROM scanner_runs
                    WHERE trade_date = ? AND status = 'completed'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (trade_date,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM scanner_runs
                    WHERE status = 'completed'
                    ORDER BY id DESC LIMIT 1
                    """
                ).fetchone()
        return dict(row) if row else None

    def list_scanner_dates(self, limit: int = 90) -> list[str]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT trade_date FROM scanner_runs
                WHERE status = 'completed'
                ORDER BY trade_date DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [row["trade_date"] for row in rows]

    def list_refined_scanner_dates(
        self,
        *,
        engine_version: str,
        limit: int = 365,
    ) -> list[str]:
        """Dates whose latest completed run was produced by ``engine_version``."""
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT r.trade_date
                FROM scanner_runs r
                INNER JOIN (
                    SELECT trade_date, MAX(id) AS max_id
                    FROM scanner_runs
                    WHERE status = 'completed'
                    GROUP BY trade_date
                ) latest ON r.id = latest.max_id
                WHERE r.engine_version = ?
                ORDER BY r.trade_date DESC
                LIMIT ?
                """,
                (engine_version, limit),
            ).fetchall()
        return [row["trade_date"] for row in rows]

    def latest_scanner_date_with_alerts(self) -> str | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT trade_date FROM scanner_runs
                WHERE status = 'completed' AND alerts_count > 0
                ORDER BY trade_date DESC
                LIMIT 1
                """
            ).fetchone()
        return row["trade_date"] if row else None

    def query_pattern_signals(
        self,
        trade_date: str,
        *,
        pattern_type: str | None = None,
        pattern_types: list[str] | None = None,
        exclude_pattern_types: list[str] | None = None,
        min_score: float = 0.0,
        sector: str | None = None,
        triggered_only: bool = False,
        setup_only: bool = False,
        macro_pass_only: bool = False,
        fundamental_pass_only: bool = False,
        sort_by: str = "score",
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        run = self.get_latest_scanner_run(trade_date)
        if not run:
            return [], 0

        clauses = ["ps.run_id = ?", "ps.trade_date = ?"]
        params: list[Any] = [run["id"], trade_date]

        if pattern_type:
            clauses.append("ps.pattern_type = ?")
            params.append(pattern_type)
        elif pattern_types:
            placeholders = ", ".join("?" for _ in pattern_types)
            clauses.append(f"ps.pattern_type IN ({placeholders})")
            params.extend(pattern_types)
        if exclude_pattern_types:
            placeholders = ", ".join("?" for _ in exclude_pattern_types)
            clauses.append(f"ps.pattern_type NOT IN ({placeholders})")
            params.extend(exclude_pattern_types)
        if min_score > 0:
            clauses.append("ps.score >= ?")
            params.append(min_score)
        if triggered_only and setup_only:
            clauses.append("(ps.triggered_today = 1 OR ps.setup_ready = 1)")
        elif triggered_only:
            clauses.append("ps.triggered_today = 1")
        elif setup_only:
            clauses.append("ps.setup_ready = 1")
        if macro_pass_only:
            clauses.append("ps.macro_pass = 1")
        if fundamental_pass_only:
            clauses.append("json_extract(ps.details_json, '$.fundamental.pass') = 1")
        if sector:
            clauses.append("p.sector = ?")
            params.append(sector)

        where = " AND ".join(clauses)
        order_by = (
            "ps.setup_ready DESC, ps.score DESC, ps.ticker ASC"
            if sort_by == "setup_first"
            else "ps.score DESC, ps.ticker ASC"
        )
        count_sql = f"""
            SELECT COUNT(*) AS cnt
            FROM pattern_signals ps
            JOIN security_profiles p ON ps.ticker = p.ticker
            WHERE {where}
        """
        data_sql = f"""
            SELECT
                ps.ticker,
                p.company_name,
                p.sector,
                ps.trade_date,
                ps.pattern_type,
                ps.macro_pass,
                ps.score,
                ps.triggered_today,
                ps.setup_ready,
                ps.details_json,
                c.open_price AS open,
                c.high_price AS high,
                c.low_price AS low,
                c.close_price AS close,
                c.volume,
                c.daily_return_pct
            FROM pattern_signals ps
            JOIN security_profiles p ON ps.ticker = p.ticker
            LEFT JOIN daily_candles c
                ON c.trade_date = ps.trade_date
                AND c.instrument_token = p.instrument_token
            WHERE {where}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
        """
        with self.connection() as conn:
            total = conn.execute(count_sql, params).fetchone()["cnt"]
            rows = conn.execute(data_sql, [*params, limit, offset]).fetchall()

        results = []
        for row in rows:
            item = dict(row)
            item["macro_pass"] = bool(item["macro_pass"])
            item["triggered_today"] = bool(item["triggered_today"])
            item["setup_ready"] = bool(item["setup_ready"])
            try:
                item["details"] = json.loads(item.pop("details_json") or "{}")
            except json.JSONDecodeError:
                item["details"] = {}
                item.pop("details_json", None)
            results.append(item)
        return results, total

    def get_pattern_signals_for_ticker(
        self,
        ticker: str,
        trade_date: str,
    ) -> list[dict[str, Any]]:
        run = self.get_latest_scanner_run(trade_date)
        if not run:
            return []
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT pattern_type, macro_pass, score, triggered_today, setup_ready, details_json
                FROM pattern_signals
                WHERE run_id = ? AND ticker = ? AND trade_date = ?
                ORDER BY score DESC
                """,
                (run["id"], ticker.upper(), trade_date),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["macro_pass"] = bool(item["macro_pass"])
            item["triggered_today"] = bool(item["triggered_today"])
            item["setup_ready"] = bool(item["setup_ready"])
            try:
                item["details"] = json.loads(item.pop("details_json") or "{}")
            except json.JSONDecodeError:
                item["details"] = {}
            out.append(item)
        return out

    def get_fundamentals(self, ticker: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT ticker, isin, payload_json, updated_at FROM company_fundamentals WHERE ticker = ?",
                (ticker.upper(),),
            ).fetchone()
        if not row:
            return None
        payload = json.loads(row["payload_json"])
        return {
            "ticker": row["ticker"],
            "isin": row["isin"],
            "updated_at": row["updated_at"],
            **payload,
        }

    def list_fundamentals_tickers(self) -> set[str]:
        with self.connection() as conn:
            rows = conn.execute("SELECT ticker FROM company_fundamentals").fetchall()
        return {row["ticker"] for row in rows}

    def load_fundamentals_index(self) -> dict[str, dict[str, Any]]:
        """Ticker -> cached fundamentals payload (key_ratios, etc.)."""
        with self.connection() as conn:
            rows = conn.execute("SELECT ticker, payload_json FROM company_fundamentals").fetchall()
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                out[row["ticker"]] = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                continue
        return out

    def get_latest_fii_cash_net(self, as_of_date: str) -> float | None:
        rows = self.list_institutional_flows(
            flow_type="FII",
            data_type="NSE_EQ|CASH",
            interval_code="1D",
            limit=60,
        )
        if not rows:
            return None
        target = date.fromisoformat(as_of_date)
        for row in rows:
            net = row.get("net_amount")
            if net is None:
                continue
            ts = row.get("record_ts")
            if ts is None:
                continue
            ts_val = int(ts)
            if ts_val > 10**12:
                ts_val //= 1000
            row_date = datetime.fromtimestamp(ts_val, tz=timezone.utc).date()
            if row_date <= target:
                return float(net)
        return None

    def list_derivative_pcr_for_date(self, trade_date: str) -> dict[str, float]:
        """Nearest-expiry PCR per symbol on a trade date."""
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT symbol, pcr
                FROM derivative_snapshots
                WHERE trade_date = ? AND pcr IS NOT NULL
                ORDER BY symbol ASC, expiry ASC
                """,
                (trade_date,),
            ).fetchall()
        out: dict[str, float] = {}
        for row in rows:
            symbol = row["symbol"]
            if symbol not in out:
                out[symbol] = float(row["pcr"])
        return out

    def has_derivative_snapshot(self, symbol: str, trade_date: str) -> bool:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM derivative_snapshots
                WHERE symbol = ? AND trade_date = ?
                LIMIT 1
                """,
                (symbol.upper(), trade_date),
            ).fetchone()
        return row is not None

    def symbols_missing_derivatives(self, symbols: list[str], trade_date: str) -> list[str]:
        if not symbols:
            return []
        normalized = sorted({s.upper() for s in symbols if s})
        placeholders = ",".join("?" for _ in normalized)
        with self.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT DISTINCT symbol
                FROM derivative_snapshots
                WHERE trade_date = ? AND symbol IN ({placeholders})
                """,
                [trade_date, *normalized],
            ).fetchall()
        present = {row["symbol"] for row in rows}
        return [sym for sym in normalized if sym not in present]

    def load_derivative_metrics_for_date(self, trade_date: str) -> dict[str, dict[str, Any]]:
        """Option-chain OI + PCR per symbol with day-over-day deltas when prior row exists."""
        with self.connection() as conn:
            today_rows = conn.execute(
                """
                SELECT symbol, total_call_oi, total_put_oi, pcr, max_pain_strike, expiry
                FROM derivative_snapshots
                WHERE trade_date = ?
                ORDER BY symbol ASC, expiry ASC
                """,
                (trade_date,),
            ).fetchall()

            today_by_symbol: dict[str, dict[str, Any]] = {}
            for row in today_rows:
                symbol = row["symbol"]
                if symbol not in today_by_symbol:
                    today_by_symbol[symbol] = dict(row)

            metrics: dict[str, dict[str, Any]] = {}
            for symbol, today in today_by_symbol.items():
                call_oi = int(today["total_call_oi"] or 0)
                put_oi = int(today["total_put_oi"] or 0)
                total_oi = call_oi + put_oi
                pcr_today = today.get("pcr")

                prior = conn.execute(
                    """
                    SELECT trade_date, total_call_oi, total_put_oi, pcr
                    FROM derivative_snapshots
                    WHERE symbol = ? AND trade_date < ?
                    ORDER BY trade_date DESC, expiry ASC
                    LIMIT 1
                    """,
                    (symbol, trade_date),
                ).fetchone()

                oi_change_pct: float | None = None
                pcr_change_pct: float | None = None
                prior_trade_date: str | None = None

                if prior:
                    prior_trade_date = prior["trade_date"]
                    prior_total = int(prior["total_call_oi"] or 0) + int(prior["total_put_oi"] or 0)
                    if prior_total > 0:
                        oi_change_pct = round(((total_oi - prior_total) / prior_total) * 100.0, 2)
                    prior_pcr = prior["pcr"]
                    if (
                        pcr_today is not None
                        and prior_pcr is not None
                        and float(prior_pcr) != 0.0
                    ):
                        pcr_change_pct = round(
                            ((float(pcr_today) - float(prior_pcr)) / float(prior_pcr)) * 100.0,
                            2,
                        )

                metrics[symbol] = {
                    "total_oi": total_oi,
                    "total_call_oi": call_oi,
                    "total_put_oi": put_oi,
                    "pcr": float(pcr_today) if pcr_today is not None else None,
                    "oi_change_pct": oi_change_pct,
                    "pcr_change_pct": pcr_change_pct,
                    "prior_trade_date": prior_trade_date,
                    "max_pain_strike": today.get("max_pain_strike"),
                }
            return metrics

    def list_profiles_with_isin(
        self,
        *,
        tickers: list[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["isin IS NOT NULL", "isin != ''"]
        params: list[Any] = []
        if tickers:
            placeholders = ",".join("?" for _ in tickers)
            clauses.append(f"ticker IN ({placeholders})")
            params.extend(t.upper() for t in tickers)
        sql = f"""
            SELECT instrument_token, ticker, company_name, isin
            FROM security_profiles
            WHERE {' AND '.join(clauses)}
            ORDER BY ticker
        """
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def upsert_fundamentals(
        self,
        ticker: str,
        isin: str | None,
        payload: dict[str, Any],
    ) -> None:
        now = _utc_now()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO company_fundamentals (ticker, isin, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    isin = COALESCE(excluded.isin, company_fundamentals.isin),
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (ticker.upper(), isin, json.dumps(payload), now),
            )

    def upsert_institutional_flows(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        now = _utc_now()
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO institutional_flows (
                    flow_type, data_type, interval_code, record_ts,
                    buy_amount, sell_amount, net_amount,
                    buy_contracts, sell_contracts, oi_contracts, oi_amount,
                    payload_json, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(flow_type, data_type, interval_code, record_ts) DO UPDATE SET
                    buy_amount = excluded.buy_amount,
                    sell_amount = excluded.sell_amount,
                    net_amount = excluded.net_amount,
                    buy_contracts = excluded.buy_contracts,
                    sell_contracts = excluded.sell_contracts,
                    oi_contracts = excluded.oi_contracts,
                    oi_amount = excluded.oi_amount,
                    payload_json = excluded.payload_json,
                    synced_at = excluded.synced_at
                """,
                [
                    (
                        row["flow_type"],
                        row["data_type"],
                        row["interval_code"],
                        int(row["record_ts"]),
                        row.get("buy_amount"),
                        row.get("sell_amount"),
                        row.get("net_amount"),
                        row.get("buy_contracts"),
                        row.get("sell_contracts"),
                        row.get("oi_contracts"),
                        row.get("oi_amount"),
                        json.dumps(row.get("payload") or {}),
                        now,
                    )
                    for row in rows
                ],
            )
        return len(rows)

    def list_institutional_flows(
        self,
        *,
        flow_type: str | None = None,
        data_type: str | None = None,
        interval_code: str = "1D",
        limit: int = 120,
    ) -> list[dict[str, Any]]:
        clauses = ["interval_code = ?"]
        params: list[Any] = [interval_code]
        if flow_type:
            clauses.append("flow_type = ?")
            params.append(flow_type.upper())
        if data_type:
            clauses.append("data_type = ?")
            params.append(data_type)
        params.append(int(limit))
        sql = f"""
            SELECT flow_type, data_type, interval_code, record_ts,
                   buy_amount, sell_amount, net_amount,
                   buy_contracts, sell_contracts, oi_contracts, oi_amount,
                   payload_json, synced_at
            FROM institutional_flows
            WHERE {' AND '.join(clauses)}
            ORDER BY record_ts DESC
            LIMIT ?
        """
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
            except json.JSONDecodeError:
                item["payload"] = {}
            out.append(item)
        return out

    def upsert_derivative_snapshot(self, row: dict[str, Any]) -> None:
        now = _utc_now()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO derivative_snapshots (
                    instrument_key, symbol, expiry, trade_date,
                    total_call_oi, total_put_oi, spot_close, pcr, max_pain_strike,
                    oi_payload_json, change_oi_payload_json,
                    pcr_payload_json, max_pain_payload_json, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instrument_key, expiry, trade_date) DO UPDATE SET
                    symbol = excluded.symbol,
                    total_call_oi = excluded.total_call_oi,
                    total_put_oi = excluded.total_put_oi,
                    spot_close = excluded.spot_close,
                    pcr = excluded.pcr,
                    max_pain_strike = excluded.max_pain_strike,
                    oi_payload_json = excluded.oi_payload_json,
                    change_oi_payload_json = excluded.change_oi_payload_json,
                    pcr_payload_json = excluded.pcr_payload_json,
                    max_pain_payload_json = excluded.max_pain_payload_json,
                    synced_at = excluded.synced_at
                """,
                (
                    row["instrument_key"],
                    row["symbol"],
                    row["expiry"],
                    row["trade_date"],
                    row.get("total_call_oi"),
                    row.get("total_put_oi"),
                    row.get("spot_close"),
                    row.get("pcr"),
                    row.get("max_pain_strike"),
                    json.dumps(row.get("oi_payload") or {}),
                    json.dumps(row.get("change_oi_payload") or {}),
                    json.dumps(row.get("pcr_payload") or {}),
                    json.dumps(row.get("max_pain_payload") or {}),
                    now,
                ),
            )

    def get_derivative_snapshot(
        self,
        symbol: str,
        trade_date: str,
        *,
        expiry: str | None = None,
    ) -> dict[str, Any] | None:
        clauses = ["symbol = ?", "trade_date = ?"]
        params: list[Any] = [symbol.upper(), trade_date]
        if expiry:
            clauses.append("expiry = ?")
            params.append(expiry)
        sql = f"""
            SELECT instrument_key, symbol, expiry, trade_date,
                   total_call_oi, total_put_oi, spot_close, pcr, max_pain_strike,
                   oi_payload_json, change_oi_payload_json,
                   pcr_payload_json, max_pain_payload_json, synced_at
            FROM derivative_snapshots
            WHERE {' AND '.join(clauses)}
            ORDER BY expiry ASC
            LIMIT 1
        """
        with self.connection() as conn:
            row = conn.execute(sql, params).fetchone()
        if not row:
            return None
        item = dict(row)
        for key in (
            "oi_payload_json",
            "change_oi_payload_json",
            "pcr_payload_json",
            "max_pain_payload_json",
        ):
            json_key = key.replace("_json", "")
            try:
                item[json_key] = json.loads(item.pop(key) or "{}")
            except json.JSONDecodeError:
                item[json_key] = {}
                item.pop(key, None)
        return item

    def list_derivative_snapshots(
        self,
        *,
        trade_date: str | None = None,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if trade_date:
            clauses.append("trade_date = ?")
            params.append(trade_date)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(int(limit))
        sql = f"""
            SELECT instrument_key, symbol, expiry, trade_date,
                   total_call_oi, total_put_oi, spot_close, pcr, max_pain_strike, synced_at
            FROM derivative_snapshots
            {where}
            ORDER BY trade_date DESC, symbol ASC
            LIMIT ?
        """
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def profiles_missing_candles(self, limit: int | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT p.instrument_token, p.ticker, p.series,
                   COALESCE(p.ingest_skip, 0) AS ingest_skip
            FROM security_profiles p
            LEFT JOIN (
                SELECT DISTINCT instrument_token FROM daily_candles
            ) c ON p.instrument_token = c.instrument_token
            WHERE c.instrument_token IS NULL
              AND COALESCE(p.ingest_skip, 0) = 0
            ORDER BY p.ticker
        """
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        with self.connection() as conn:
            rows = conn.execute(sql).fetchall()
        return [dict(row) for row in rows]

    # --- News / Telegram -------------------------------------------------

    def list_company_name_index(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT ticker, company_name, sector, instrument_token
                FROM security_profiles
                WHERE company_name IS NOT NULL AND TRIM(company_name) != ''
                ORDER BY ticker
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_news_channel(
        self,
        channel_key: str,
        *,
        channel_id: str | None = None,
        title: str | None = None,
        last_message_id: int | None = None,
        last_synced_at: str | None = None,
    ) -> None:
        now = _utc_now()
        with self.connection() as conn:
            existing = conn.execute(
                "SELECT channel_key FROM news_channels WHERE channel_key = ?",
                (channel_key,),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE news_channels
                    SET channel_id = COALESCE(?, channel_id),
                        title = COALESCE(?, title),
                        last_message_id = COALESCE(?, last_message_id),
                        last_synced_at = COALESCE(?, last_synced_at),
                        updated_at = ?
                    WHERE channel_key = ?
                    """,
                    (channel_id, title, last_message_id, last_synced_at, now, channel_key),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO news_channels (
                        channel_key, channel_id, title, last_message_id, last_synced_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (channel_key, channel_id, title, last_message_id, last_synced_at, now),
                )

    def get_news_channel(self, channel_key: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM news_channels WHERE channel_key = ?",
                (channel_key,),
            ).fetchone()
        return dict(row) if row else None

    def insert_telegram_message(
        self,
        *,
        channel_key: str,
        channel_id: str | None,
        message_id: int,
        posted_at: str,
        text: str | None,
        raw_json: str | None = None,
    ) -> int | None:
        """Insert message; returns row id, or None if duplicate."""
        now = _utc_now()
        with self.connection() as conn:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO telegram_messages (
                        channel_key, channel_id, message_id, posted_at, text, raw_json, processed, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (channel_key, channel_id, message_id, posted_at, text, raw_json, now),
                )
                return int(cur.lastrowid)
            except sqlite3.IntegrityError:
                return None

    def get_telegram_message(self, message_pk: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM telegram_messages WHERE id = ?",
                (int(message_pk),),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _media_placeholder_sql(alias: str = "m") -> str:
        """Exclude empty / legacy '[photo]' caption placeholders from feeds."""
        t = f"TRIM(COALESCE({alias}.text, ''))"
        return (
            f"{t} != '' AND NOT ("
            f"substr({t}, 1, 1) = '[' AND substr({t}, -1) = ']' AND length({t}) < 24"
            f")"
        )

    def purge_media_placeholder_messages(self) -> int:
        """Delete stored media-only posts (no caption) and their events/reactions."""
        where = f"WHERE NOT ({self._media_placeholder_sql('m')})"
        with self.connection() as conn:
            ids = [
                int(r["id"])
                for r in conn.execute(
                    f"SELECT m.id FROM telegram_messages m {where}"
                ).fetchall()
            ]
            if not ids:
                return 0
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"""
                DELETE FROM news_reactions WHERE event_id IN (
                    SELECT id FROM news_events WHERE message_pk IN ({placeholders})
                )
                """,
                ids,
            )
            conn.execute(
                f"DELETE FROM news_events WHERE message_pk IN ({placeholders})",
                ids,
            )
            conn.execute(
                f"DELETE FROM telegram_messages WHERE id IN ({placeholders})",
                ids,
            )
        return len(ids)

    def list_telegram_messages(
        self,
        *,
        channel_key: str | None = None,
        processed: int | None = None,
        topic: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        from ..services.news.monitors import match_monitor_topics, topic_filter_regex

        clauses: list[str] = [self._media_placeholder_sql("m")]
        params: list[Any] = []
        if channel_key:
            clauses.append("m.channel_key = ?")
            params.append(channel_key)
        if processed is not None:
            clauses.append("m.processed = ?")
            params.append(int(processed))
        if topic:
            regex = topic_filter_regex(topic)
            if regex:
                # SQLite LIKE fallbacks for common keywords — pull then filter in Python for accuracy
                pass
        where = f"WHERE {' AND '.join(clauses)}"
        # When filtering by topic, over-fetch then slice (keyword match in Python).
        fetch_limit = int(limit) if not topic else min(2000, max(int(limit) * 20, 200))
        count_sql = f"SELECT COUNT(*) AS cnt FROM telegram_messages m {where}"
        data_sql = f"""
            SELECT
                m.*,
                (
                    SELECT COUNT(*) FROM news_events e WHERE e.message_pk = m.id
                ) AS event_count,
                (
                    SELECT e.ticker FROM news_events e
                    WHERE e.message_pk = m.id AND e.status = 'linked' AND e.ticker IS NOT NULL
                    ORDER BY e.id ASC LIMIT 1
                ) AS primary_ticker,
                (
                    SELECT e.sentiment FROM news_events e
                    WHERE e.message_pk = m.id
                    ORDER BY e.id ASC LIMIT 1
                ) AS sentiment,
                (
                    SELECT e.status FROM news_events e
                    WHERE e.message_pk = m.id
                    ORDER BY e.id ASC LIMIT 1
                ) AS event_status
            FROM telegram_messages m
            {where}
            ORDER BY m.posted_at DESC, m.id DESC
            LIMIT ? OFFSET ?
        """
        with self.connection() as conn:
            if topic:
                rows = conn.execute(data_sql, [*params, fetch_limit, 0]).fetchall()
                items = []
                topic_u = topic.upper()
                for row in rows:
                    item = dict(row)
                    topics = match_monitor_topics(item.get("text"))
                    # also check raw_json cache
                    try:
                        raw = json.loads(item.get("raw_json") or "{}")
                        for t in raw.get("monitor_topics") or []:
                            if t not in topics:
                                topics.append(t)
                    except json.JSONDecodeError:
                        pass
                    item["monitor_topics"] = topics
                    if topic_u in topics:
                        items.append(item)
                total = len(items)
                page = items[int(offset) : int(offset) + int(limit)]
                return page, total

            total = conn.execute(count_sql, params).fetchone()["cnt"]
            rows = conn.execute(data_sql, [*params, int(limit), int(offset)]).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            topics = match_monitor_topics(item.get("text"))
            try:
                raw = json.loads(item.get("raw_json") or "{}")
                for t in raw.get("monitor_topics") or []:
                    if t not in topics:
                        topics.append(t)
            except json.JSONDecodeError:
                pass
            item["monitor_topics"] = topics
            out.append(item)
        return out, int(total)

    def list_unprocessed_messages(self, *, limit: int = 200) -> list[dict[str, Any]]:
        t = "TRIM(COALESCE(text, ''))"
        caption_ok = (
            f"{t} != '' AND NOT ("
            f"substr({t}, 1, 1) = '[' AND substr({t}, -1) = ']' AND length({t}) < 24"
            f")"
        )
        with self.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM telegram_messages
                WHERE processed = 0 AND {caption_ok}
                ORDER BY posted_at ASC, id ASC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_message_processed(self, message_pk: int) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE telegram_messages SET processed = 1 WHERE id = ?",
                (int(message_pk),),
            )

    def insert_news_event(
        self,
        *,
        message_pk: int,
        ticker: str | None,
        company_name_matched: str | None,
        match_confidence: float | None,
        event_date: str | None,
        sentiment: str | None,
        themes: list[str] | None,
        summary: str | None,
        gemini_extract: dict[str, Any] | None,
        status: str,
    ) -> int:
        now = _utc_now()
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO news_events (
                    message_pk, ticker, company_name_matched, match_confidence,
                    event_date, sentiment, themes_json, summary, gemini_extract_json,
                    outlook_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    int(message_pk),
                    ticker,
                    company_name_matched,
                    match_confidence,
                    event_date,
                    sentiment,
                    json.dumps(themes or []),
                    summary,
                    json.dumps(gemini_extract) if gemini_extract is not None else None,
                    status,
                    now,
                    now,
                ),
            )
            return int(cur.lastrowid)

    def update_news_event(self, event_id: int, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "ticker",
            "company_name_matched",
            "match_confidence",
            "event_date",
            "sentiment",
            "themes_json",
            "summary",
            "gemini_extract_json",
            "outlook_json",
            "status",
        }
        updates: dict[str, Any] = {}
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key in ("themes_json", "gemini_extract_json", "outlook_json") and not isinstance(value, str):
                updates[key] = json.dumps(value) if value is not None else None
            else:
                updates[key] = value
        if not updates:
            return self.get_news_event(event_id)
        updates["updated_at"] = _utc_now()
        sets = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [int(event_id)]
        with self.connection() as conn:
            conn.execute(f"UPDATE news_events SET {sets} WHERE id = ?", params)
        return self.get_news_event(event_id)

    def _decode_news_event(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        for key, out_key in (
            ("themes_json", "themes"),
            ("gemini_extract_json", "gemini_extract"),
            ("outlook_json", "outlook"),
        ):
            raw = item.pop(key, None)
            if raw is None:
                item[out_key] = None if out_key != "themes" else []
                continue
            try:
                item[out_key] = json.loads(raw)
            except json.JSONDecodeError:
                item[out_key] = [] if out_key == "themes" else None
        return item

    def get_news_event(self, event_id: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT e.*, m.text AS message_text, m.posted_at, m.channel_key, m.message_id AS telegram_message_id
                FROM news_events e
                JOIN telegram_messages m ON m.id = e.message_pk
                WHERE e.id = ?
                """,
                (int(event_id),),
            ).fetchone()
        return self._decode_news_event(row) if row else None

    def list_news_events(
        self,
        *,
        ticker: str | None = None,
        sentiment: str | None = None,
        status: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        channel_key: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        params: list[Any] = []
        if ticker:
            clauses.append("e.ticker = ?")
            params.append(ticker.upper())
        if sentiment:
            clauses.append("e.sentiment = ?")
            params.append(sentiment.lower())
        if status:
            clauses.append("e.status = ?")
            params.append(status)
        if from_date:
            clauses.append("e.event_date >= ?")
            params.append(from_date)
        if to_date:
            clauses.append("e.event_date <= ?")
            params.append(to_date)
        if channel_key:
            clauses.append("m.channel_key = ?")
            params.append(channel_key)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        count_sql = f"""
            SELECT COUNT(*) AS cnt
            FROM news_events e
            JOIN telegram_messages m ON m.id = e.message_pk
            {where}
        """
        data_sql = f"""
            SELECT e.*, m.text AS message_text, m.posted_at, m.channel_key, m.message_id AS telegram_message_id
            FROM news_events e
            JOIN telegram_messages m ON m.id = e.message_pk
            {where}
            ORDER BY COALESCE(e.event_date, m.posted_at) DESC, e.id DESC
            LIMIT ? OFFSET ?
        """
        with self.connection() as conn:
            total = conn.execute(count_sql, params).fetchone()["cnt"]
            rows = conn.execute(data_sql, [*params, int(limit), int(offset)]).fetchall()
        return [self._decode_news_event(r) for r in rows], int(total)

    def replace_news_reactions(self, event_id: int, reactions: list[dict[str, Any]]) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM news_reactions WHERE event_id = ?", (int(event_id),))
            if not reactions:
                return
            conn.executemany(
                """
                INSERT INTO news_reactions (
                    event_id, horizon, return_pct, rel_return_pct, close_price, trade_date
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        int(event_id),
                        r["horizon"],
                        r.get("return_pct"),
                        r.get("rel_return_pct"),
                        r.get("close_price"),
                        r.get("trade_date"),
                    )
                    for r in reactions
                ],
            )

    def get_news_reactions(self, event_id: int) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT event_id, horizon, return_pct, rel_return_pct, close_price, trade_date
                FROM news_reactions
                WHERE event_id = ?
                ORDER BY horizon
                """,
                (int(event_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events_missing_reactions(self, *, limit: int = 500) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT e.*
                FROM news_events e
                LEFT JOIN news_reactions r ON r.event_id = e.id
                WHERE e.status = 'linked'
                  AND e.ticker IS NOT NULL
                  AND e.event_date IS NOT NULL
                  AND r.event_id IS NULL
                ORDER BY e.event_date ASC, e.id ASC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [self._decode_news_event(r) for r in rows]

    def list_similar_news_events(
        self,
        *,
        ticker: str | None,
        themes: list[str] | None = None,
        exclude_event_id: int | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        clauses = ["e.status = 'linked'", "e.ticker IS NOT NULL"]
        params: list[Any] = []
        if ticker:
            clauses.append("e.ticker = ?")
            params.append(ticker.upper())
        if exclude_event_id is not None:
            clauses.append("e.id != ?")
            params.append(int(exclude_event_id))
        where = " AND ".join(clauses)
        sql = f"""
            SELECT e.*, m.text AS message_text, m.posted_at, m.channel_key
            FROM news_events e
            JOIN telegram_messages m ON m.id = e.message_pk
            WHERE {where}
            ORDER BY e.event_date DESC, e.id DESC
            LIMIT ?
        """
        params.append(int(limit * 3 if themes else limit))
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        events = [self._decode_news_event(r) for r in rows]
        if themes:
            theme_set = {t.lower() for t in themes}

            def _rank(ev: dict[str, Any]) -> tuple[int, str]:
                ev_themes = {str(t).lower() for t in (ev.get("themes") or [])}
                overlap = len(theme_set & ev_themes)
                return (-overlap, ev.get("event_date") or "")

            events = sorted(events, key=_rank)[:limit]
        else:
            events = events[:limit]
        for ev in events:
            ev["reactions"] = self.get_news_reactions(int(ev["id"]))
        return events

    def news_stats(self) -> dict[str, Any]:
        with self.connection() as conn:
            msg_count = conn.execute("SELECT COUNT(*) AS cnt FROM telegram_messages").fetchone()["cnt"]
            unprocessed = conn.execute(
                "SELECT COUNT(*) AS cnt FROM telegram_messages WHERE processed = 0"
            ).fetchone()["cnt"]
            event_count = conn.execute("SELECT COUNT(*) AS cnt FROM news_events").fetchone()["cnt"]
            linked = conn.execute(
                "SELECT COUNT(*) AS cnt FROM news_events WHERE status = 'linked'"
            ).fetchone()["cnt"]
            reaction_events = conn.execute(
                "SELECT COUNT(DISTINCT event_id) AS cnt FROM news_reactions"
            ).fetchone()["cnt"]
        return {
            "message_count": int(msg_count),
            "unprocessed_messages": int(unprocessed),
            "event_count": int(event_count),
            "linked_events": int(linked),
            "events_with_reactions": int(reaction_events),
        }

    # ── Multi-year breakout / ATH pullback scanner ───────────────────────

    def create_myb_run(
        self,
        trade_date: str,
        *,
        lookback_years: int,
        strategy: str = "multi_year_breakout",
        params: dict[str, Any] | None = None,
    ) -> int:
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO myb_runs (
                    trade_date, strategy, lookback_years, started_at, status, params_json
                ) VALUES (?, ?, ?, ?, 'running', ?)
                """,
                (
                    trade_date,
                    strategy,
                    int(lookback_years),
                    _utc_now(),
                    json.dumps(params or {}),
                ),
            )
            return int(cur.lastrowid)

    def finish_myb_run(
        self,
        run_id: int,
        *,
        symbols_scanned: int,
        alerts_count: int,
        status: str = "completed",
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE myb_runs
                SET finished_at = ?, symbols_scanned = ?, alerts_count = ?, status = ?
                WHERE id = ?
                """,
                (_utc_now(), symbols_scanned, alerts_count, status, run_id),
            )

    def delete_myb_data_for_date(
        self,
        trade_date: str,
        *,
        strategy: str | None = None,
        lookback_years: int | None = None,
    ) -> None:
        with self.connection() as conn:
            if strategy is None and lookback_years is None:
                conn.execute("DELETE FROM myb_signals WHERE trade_date = ?", (trade_date,))
                conn.execute("DELETE FROM myb_runs WHERE trade_date = ?", (trade_date,))
                return

            sig_clauses = ["trade_date = ?"]
            run_clauses = ["trade_date = ?"]
            params: list[Any] = [trade_date]
            if strategy is not None:
                sig_clauses.append("strategy = ?")
                run_clauses.append("strategy = ?")
                params.append(strategy)
            if lookback_years is not None:
                sig_clauses.append("lookback_years = ?")
                run_clauses.append("lookback_years = ?")
                params.append(int(lookback_years))

            conn.execute(
                f"DELETE FROM myb_signals WHERE {' AND '.join(sig_clauses)}",
                params,
            )
            conn.execute(
                f"DELETE FROM myb_runs WHERE {' AND '.join(run_clauses)}",
                params,
            )

    def insert_myb_signals(self, signals: list[dict[str, Any]]) -> int:
        if not signals:
            return 0
        rows = [
            (
                s["run_id"],
                s["trade_date"],
                s["ticker"],
                s.get("sector"),
                s.get("company_name"),
                s.get("strategy") or "multi_year_breakout",
                s["status"],
                int(s["lookback_years"]),
                float(s["prior_high"]),
                s.get("prior_high_date"),
                s.get("years_since_high"),
                float(s["close_price"]),
                s.get("breakout_pct"),
                s.get("drop_from_ath_pct"),
                s.get("rvol20"),
                s.get("rsi14"),
                s.get("avg_turnover_inr"),
                float(s["score"]),
                json.dumps(s.get("details") or {}),
            )
            for s in signals
        ]
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO myb_signals (
                    run_id, trade_date, ticker, sector, company_name, strategy, status,
                    lookback_years, prior_high, prior_high_date, years_since_high,
                    close_price, breakout_pct, drop_from_ath_pct, rvol20, rsi14,
                    avg_turnover_inr, score, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def get_latest_myb_run(
        self,
        trade_date: str,
        *,
        strategy: str | None = None,
        lookback_years: int | None = None,
    ) -> dict[str, Any] | None:
        clauses = ["trade_date = ?", "status = 'completed'"]
        params: list[Any] = [trade_date]
        if strategy is not None:
            clauses.append("strategy = ?")
            params.append(strategy)
        if lookback_years is not None:
            clauses.append("lookback_years = ?")
            params.append(int(lookback_years))
        with self.connection() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM myb_runs
                WHERE {' AND '.join(clauses)}
                ORDER BY id DESC LIMIT 1
                """,
                params,
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        raw = item.pop("params_json", None)
        try:
            item["params"] = json.loads(raw) if raw else {}
        except (TypeError, json.JSONDecodeError):
            item["params"] = {}
        return item

    def list_myb_dates(self, limit: int = 90, *, strategy: str | None = None) -> list[str]:
        with self.connection() as conn:
            if strategy:
                rows = conn.execute(
                    """
                    SELECT DISTINCT trade_date FROM myb_runs
                    WHERE status = 'completed' AND strategy = ?
                    ORDER BY trade_date DESC
                    LIMIT ?
                    """,
                    (strategy, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT DISTINCT trade_date FROM myb_runs
                    WHERE status = 'completed'
                    ORDER BY trade_date DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [row["trade_date"] for row in rows]

    def query_myb_signals(
        self,
        trade_date: str,
        *,
        strategy: str | None = None,
        lookback_years: int | None = None,
        status: str | None = None,
        min_score: float = 0.0,
        sector: str | None = None,
        size_tier: str | None = None,
        trend: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        min_rvol: float | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        run = self.get_latest_myb_run(
            trade_date,
            strategy=strategy,
            lookback_years=lookback_years,
        )
        if not run:
            return [], 0

        clauses = ["run_id = ?", "trade_date = ?"]
        params: list[Any] = [run["id"], trade_date]
        if strategy is not None:
            clauses.append("strategy = ?")
            params.append(strategy)
        if lookback_years is not None:
            clauses.append("lookback_years = ?")
            params.append(int(lookback_years))
        if status:
            clauses.append("status = ?")
            params.append(status)
        if min_score > 0:
            clauses.append("score >= ?")
            params.append(float(min_score))
        if sector:
            clauses.append("sector = ?")
            params.append(sector)
        if min_price is not None:
            clauses.append("close_price >= ?")
            params.append(float(min_price))
        if max_price is not None:
            clauses.append("close_price <= ?")
            params.append(float(max_price))
        if min_rvol is not None:
            clauses.append("rvol20 >= ?")
            params.append(float(min_rvol))

        where = " AND ".join(clauses)
        with self.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM myb_signals
                WHERE {where}
                ORDER BY score DESC, ticker ASC
                """,
                params,
            ).fetchall()

        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            raw = item.pop("details_json", None)
            try:
                item["details"] = json.loads(raw) if raw else {}
            except (TypeError, json.JSONDecodeError):
                item["details"] = {}
            details = item.get("details") or {}
            if size_tier and size_tier != "all":
                if details.get("size_tier") != size_tier:
                    continue
            if trend and trend != "all":
                if details.get("trend") != trend:
                    continue
            out.append(item)

        total = len(out)
        page = out[offset : offset + limit]
        return page, total

    # ── Grimes TA lab ────────────────────────────────────────────────────

    def max_daily_trade_date(self) -> str | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT MAX(trade_date) AS max_date FROM daily_candles"
            ).fetchone()
        value = row["max_date"] if row else None
        return str(value) if value else None

    def delete_grimes_data_for_date(self, trade_date: str) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM grimes_signals WHERE trade_date = ?", (trade_date,))
            conn.execute("DELETE FROM grimes_runs WHERE trade_date = ?", (trade_date,))

    def replace_grimes_scan(
        self,
        trade_date: str,
        payload: dict[str, Any],
        *,
        engine_version: str,
    ) -> int:
        results = payload.get("results") or []
        summary = payload.get("summary") or {}
        now = _utc_now()
        signal_rows = [
            (
                trade_date,
                str(row.get("ticker") or ""),
                str(row.get("instrument_key") or ""),
                row.get("kind"),
                row.get("company_name"),
                row.get("as_of"),
                row.get("price"),
                row.get("regime"),
                row.get("setup_type"),
                row.get("setup_group"),
                row.get("quality_score"),
                json.dumps(row, default=str),
            )
            for row in results
            if isinstance(row, dict)
        ]
        with self.connection() as conn:
            conn.execute("DELETE FROM grimes_signals WHERE trade_date = ?", (trade_date,))
            conn.execute("DELETE FROM grimes_runs WHERE trade_date = ?", (trade_date,))
            cur = conn.execute(
                """
                INSERT INTO grimes_runs (
                    trade_date, started_at, finished_at, universe_size, analyzed,
                    workers, status, engine_version, summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'completed', ?, ?)
                """,
                (
                    trade_date,
                    payload.get("timestamp") or now,
                    now,
                    int(payload.get("universe_size") or 0),
                    int(payload.get("analyzed") or len(signal_rows)),
                    int(payload.get("workers") or 0),
                    engine_version,
                    json.dumps(summary, default=str),
                ),
            )
            run_id = int(cur.lastrowid)
            if signal_rows:
                conn.executemany(
                    """
                    INSERT INTO grimes_signals (
                        run_id, trade_date, ticker, instrument_key, kind, company_name,
                        as_of, price, regime, setup_type, setup_group, quality_score,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [(run_id, *row) for row in signal_rows],
                )
        return run_id

    def load_grimes_summary(
        self,
        trade_date: str,
        *,
        engine_version: str | None = None,
    ) -> dict[str, Any] | None:
        clauses = ["trade_date = ?", "status = 'completed'"]
        params: list[Any] = [trade_date]
        if engine_version is not None:
            clauses.append("engine_version = ?")
            params.append(engine_version)
        with self.connection() as conn:
            run = conn.execute(
                f"""
                SELECT * FROM grimes_runs
                WHERE {' AND '.join(clauses)}
                ORDER BY id DESC LIMIT 1
                """,
                params,
            ).fetchone()
            if not run:
                return None
            signal_rows = conn.execute(
                """
                SELECT payload_json FROM grimes_signals
                WHERE run_id = ?
                ORDER BY quality_score DESC, ticker ASC
                """,
                (run["id"],),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in signal_rows:
            raw = row["payload_json"]
            try:
                item = json.loads(raw) if raw else {}
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(item, dict):
                results.append(item)
        try:
            summary = json.loads(run["summary_json"]) if run["summary_json"] else {}
        except (TypeError, json.JSONDecodeError):
            summary = {}
        return {
            "timestamp": run["finished_at"] or run["started_at"],
            "trade_date": run["trade_date"],
            "universe_size": int(run["universe_size"] or 0),
            "analyzed": int(run["analyzed"] or 0),
            "workers": int(run["workers"] or 0),
            "engine_version": run["engine_version"],
            "source": "db",
            "has_run": True,
            "summary": summary,
            "results": results,
        }


    def upsert_live_minute_bars(self, bars: list[dict[str, Any]]) -> int:
        if not bars:
            return 0
        with self.connection() as conn:
            return _write_live_minute_bars(conn, bars)

    def upsert_live_batch(
        self,
        minute_bars: list[dict[str, Any]],
        journal_rows: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """Minute bars and journal changes in one transaction: one fsync, one write lock."""
        if not minute_bars and not journal_rows:
            return 0, 0
        with self.connection() as conn:
            bars = _write_live_minute_bars(conn, minute_bars) if minute_bars else 0
            plans = _write_live_call_journal(conn, journal_rows) if journal_rows else 0
        return bars, plans

    def live_minute_profile(self, before_date: str, lookback_days: int = 30) -> dict[str, dict[int, float]]:
        """Summed live minute volume per session date and 09:15-based minute index."""
        start = (date.fromisoformat(before_date) - timedelta(days=lookback_days)).isoformat()
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT substr(minute_ts, 1, 10) AS day,
                       CAST(substr(minute_ts, 12, 2) AS INTEGER) * 60
                         + CAST(substr(minute_ts, 15, 2) AS INTEGER) - 555 AS minute_index,
                       SUM(volume) AS volume
                FROM live_minute_bars
                WHERE minute_ts >= ? AND minute_ts < ?
                  AND source = 'live_ws'
                  AND instrument_key LIKE 'NSE_EQ|%'
                GROUP BY day, minute_index
                """,
                (start, before_date),
            ).fetchall()
        out: dict[str, dict[int, float]] = {}
        for row in rows:
            index = int(row["minute_index"])
            if 0 <= index < 375 and row["volume"]:
                out.setdefault(str(row["day"]), {})[index] = float(row["volume"])
        return out

    def upsert_futures_oi_daily(self, rows_in: list[dict[str, Any]]) -> int:
        if not rows_in:
            return 0
        updated_at = _utc_now()
        rows = [
            (
                row["trade_date"],
                row["instrument_key"],
                row["symbol"],
                row.get("expiry"),
                row.get("oi"),
                row.get("poi"),
                row.get("ltp"),
                row.get("prev_close"),
                row.get("source") or "live_ws",
                updated_at,
            )
            for row in rows_in
        ]
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO futures_oi_daily (
                    trade_date, instrument_key, symbol, expiry, oi, poi,
                    ltp, prev_close, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_date, instrument_key) DO UPDATE SET
                    symbol = excluded.symbol,
                    expiry = excluded.expiry,
                    oi = excluded.oi,
                    poi = excluded.poi,
                    ltp = excluded.ltp,
                    prev_close = excluded.prev_close,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                rows,
            )
        return len(rows)

    def latest_futures_oi(self, symbols: list[str], before_date: str) -> dict[str, dict[str, Any]]:
        """Last persisted futures OI for each symbol strictly before ``before_date``."""
        found: dict[str, dict[str, Any]] = {}
        unique = [symbol for symbol in dict.fromkeys(symbols) if symbol]
        for chunk in _chunks(unique, 400):
            placeholders = ",".join("?" * len(chunk))
            sql = f"""
                SELECT f.symbol, f.oi, f.trade_date, f.instrument_key, f.ltp
                FROM futures_oi_daily f
                INNER JOIN (
                    SELECT symbol, MAX(trade_date) AS trade_date
                    FROM futures_oi_daily
                    WHERE trade_date < ? AND symbol IN ({placeholders})
                    GROUP BY symbol
                ) latest
                    ON latest.symbol = f.symbol AND latest.trade_date = f.trade_date
            """
            with self.connection() as conn:
                rows = conn.execute(sql, [before_date, *chunk]).fetchall()
            for row in rows:
                found[row["symbol"]] = dict(row)
        return found

    def liquid_cash_profiles(self, before_date: str, min_bars: int) -> list[dict[str, Any]]:
        """EQ names with enough daily history, most active first.

        The window is the last 20 sessions inside 80 calendar days, so a name
        that barely trades does not take a full-mode websocket slot.
        """
        sql = """
            WITH ranked AS (
                SELECT
                    instrument_token,
                    volume,
                    ROW_NUMBER() OVER (
                        PARTITION BY instrument_token
                        ORDER BY trade_date DESC
                    ) AS rn
                FROM daily_candles
                WHERE trade_date < ?
                  AND trade_date >= date(?, '-80 days')
                  AND instrument_token LIKE 'NSE_EQ|%'
            )
            SELECT
                p.ticker,
                p.company_name,
                p.sector,
                p.instrument_token,
                COUNT(r.instrument_token) AS history_bars,
                AVG(r.volume) AS avg_volume
            FROM security_profiles p
            JOIN ranked r
                ON r.instrument_token = p.instrument_token
               AND r.rn <= 20
            WHERE COALESCE(p.series, 'EQ') = 'EQ'
              AND COALESCE(p.ingest_skip, 0) = 0
            GROUP BY p.instrument_token, p.ticker, p.company_name, p.sector
            HAVING history_bars >= ?
            ORDER BY avg_volume DESC, p.ticker
        """
        with self.connection() as conn:
            rows = conn.execute(sql, (before_date, before_date, int(min_bars))).fetchall()
        return [dict(row) for row in rows]

    def live_scan_candle_stats(self, tokens: list[str], before_date: str) -> dict[str, dict[str, Any]]:
        """Prior-day OHLC and mean of up to 20 daily volumes before ``before_date``."""
        stats: dict[str, dict[str, Any]] = {}
        unique = [token for token in dict.fromkeys(tokens) if token]
        for chunk in _chunks(unique, 400):
            placeholders = ",".join("?" * len(chunk))
            sql = f"""
                WITH ranked AS (
                    SELECT
                        instrument_token,
                        trade_date,
                        high_price,
                        low_price,
                        close_price,
                        volume,
                        ROW_NUMBER() OVER (
                            PARTITION BY instrument_token
                            ORDER BY trade_date DESC
                        ) AS rn
                    FROM daily_candles
                    WHERE instrument_token IN ({placeholders})
                      AND trade_date < ?
                )
                SELECT instrument_token, trade_date, high_price, low_price, close_price, volume, rn
                FROM ranked
                WHERE rn <= 20
            """
            with self.connection() as conn:
                rows = conn.execute(sql, [*chunk, before_date]).fetchall()
            grouped: dict[str, list[sqlite3.Row]] = {}
            for row in rows:
                grouped.setdefault(row["instrument_token"], []).append(row)
            for token, items in grouped.items():
                ordered = sorted(items, key=lambda item: int(item["rn"]))
                volumes = [float(item["volume"] or 0) for item in ordered]
                closes = [float(item["close_price"] or 0) for item in ordered if item["close_price"]]
                highs = [float(item["high_price"] or 0) for item in ordered if item["high_price"]]
                lows = [float(item["low_price"] or 0) for item in ordered if item["low_price"]]
                prior = ordered[0]
                stats[token] = _daily_history_stats(
                    volumes=volumes,
                    closes=closes,
                    highs=highs,
                    lows=lows,
                    prior_high=prior["high_price"],
                    prior_low=prior["low_price"],
                    prior_close=prior["close_price"],
                    prior_date=str(prior["trade_date"]),
                    bar_count=len(ordered),
                    bars=_aligned_bars(ordered),
                )
        return stats

    def latest_index_daily_date(self, instrument_token: str) -> str | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT MAX(substr(ts, 1, 10)) AS last_date
                FROM index_candles
                WHERE instrument_token = ? AND timeframe = 'daily'
                """,
                (instrument_token,),
            ).fetchone()
        if row is None or not row["last_date"]:
            return None
        return str(row["last_date"])

    def live_scan_index_candle_stats(self, tokens: list[str], before_date: str) -> dict[str, dict[str, Any]]:
        """Same 20-session summary as cash names, read from index_candles daily bars."""
        stats: dict[str, dict[str, Any]] = {}
        for token in dict.fromkeys(tokens):
            if not token:
                continue
            with self.connection() as conn:
                rows = conn.execute(
                    """
                    SELECT substr(ts, 1, 10) AS trade_date,
                           high_price, low_price, close_price, volume
                    FROM index_candles
                    WHERE instrument_token = ?
                      AND timeframe = 'daily'
                      AND substr(ts, 1, 10) < ?
                    ORDER BY ts DESC
                    LIMIT 20
                    """,
                    (token, before_date),
                ).fetchall()
            if not rows:
                continue
            volumes = [float(row["volume"] or 0) for row in rows]
            closes = [float(row["close_price"] or 0) for row in rows if row["close_price"]]
            highs = [float(row["high_price"] or 0) for row in rows if row["high_price"]]
            lows = [float(row["low_price"] or 0) for row in rows if row["low_price"]]
            prior = rows[0]
            stats[token] = _daily_history_stats(
                volumes=volumes,
                closes=closes,
                highs=highs,
                lows=lows,
                prior_high=prior["high_price"],
                prior_low=prior["low_price"],
                prior_close=prior["close_price"],
                prior_date=str(prior["trade_date"]),
                bar_count=len(rows),
                bars=_aligned_bars(rows),
            )
        return stats

    def tickers_missing_daily_session(self, tokens: list[str], session_date: str) -> list[str]:
        """Tickers with no daily candle on or after ``session_date``."""
        missing: list[str] = []
        unique = [token for token in dict.fromkeys(tokens) if token]
        for chunk in _chunks(unique, 400):
            placeholders = ",".join("?" * len(chunk))
            sql = f"""
                SELECT p.ticker, MAX(c.trade_date) AS last_date
                FROM security_profiles p
                LEFT JOIN daily_candles c
                    ON c.instrument_token = p.instrument_token
                   AND COALESCE(c.source, '') != 'live_ws'
                WHERE p.instrument_token IN ({placeholders})
                GROUP BY p.instrument_token
                HAVING last_date IS NULL OR last_date < ?
                ORDER BY p.ticker
            """
            with self.connection() as conn:
                rows = conn.execute(sql, [*chunk, session_date]).fetchall()
            missing.extend(str(row["ticker"]) for row in rows)
        return missing

    def upsert_live_call_journal(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        with self.connection() as conn:
            return _write_live_call_journal(conn, rows)

    def list_live_call_journal(self, session_date: str) -> list[dict[str, Any]]:
        """Plans opened today, plus earlier plans whose multi-session target is still open."""
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT session_date, symbol, side, kind, company_name, stance,
                       entry, stop, exit_price, status, opened_at, entry_at, closed_at,
                       last_price, result_pct, mfe_pct, mae_pct, updated_at, fill_price,
                       swing_exit, swing_status, swing_result_pct, swing_closed_at, segment
                FROM live_call_journal
                WHERE session_date = ?
                   OR (
                        session_date < ?
                        AND (swing_status = 'open' OR status = 'open')
                   )
                ORDER BY session_date, symbol
                """,
                (session_date, session_date),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_live_call_journal_range(self, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
        """Every saved plan with ``start <= session_date <= end``. Either bound may be open."""
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT session_date, symbol, side, kind, company_name, stance,
                       entry, stop, exit_price, status, opened_at, entry_at, closed_at,
                       last_price, result_pct, mfe_pct, mae_pct, updated_at, fill_price,
                       swing_exit, swing_status, swing_result_pct, swing_closed_at, segment
                FROM live_call_journal
                WHERE session_date >= ? AND session_date <= ?
                ORDER BY session_date, symbol, side
                """,
                (start or "0000-00-00", end or "9999-99-99"),
            ).fetchall()
        return [dict(row) for row in rows]

    def daily_bars_between(
        self,
        tokens: list[str],
        start: str,
        end: str,
    ) -> dict[str, list[tuple[str, float, float, float, float]]]:
        """Cash daily OHLC per token, oldest first, ``start <= trade_date <= end``."""
        out: dict[str, list[tuple[str, float, float, float, float]]] = {}
        unique = [token for token in dict.fromkeys(tokens) if token]
        for chunk in _chunks(unique, 400):
            placeholders = ",".join("?" * len(chunk))
            with self.connection() as conn:
                rows = conn.execute(
                    f"""
                    SELECT instrument_token, trade_date, open_price, high_price, low_price, close_price
                    FROM daily_candles
                    WHERE instrument_token IN ({placeholders})
                      AND trade_date >= ? AND trade_date <= ?
                    ORDER BY instrument_token, trade_date
                    """,
                    [*chunk, start, end],
                ).fetchall()
            for row in rows:
                out.setdefault(row[0], []).append(
                    (str(row[1]), row[2] or 0.0, row[3] or 0.0, row[4] or 0.0, row[5] or 0.0)
                )
        return out

    def live_minute_ohlc_dates(self, start: str, end: str) -> set[str]:
        """Session dates that have any live minute bar carrying a high and low."""
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT substr(minute_ts, 1, 10)
                FROM live_minute_bars
                WHERE minute_ts >= ? AND minute_ts < ? AND high_price IS NOT NULL
                """,
                (start, f"{end}T99"),
            ).fetchall()
        return {str(row[0]) for row in rows}

    def live_minute_ohlc(self, instrument_key: str, session_date: str) -> list[tuple[str, float, float, float, float]]:
        """(minute, open, high, low, close) for one instrument and session, minutes with prices only."""
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT minute_ts, open_price, high_price, low_price, close_price
                FROM live_minute_bars
                WHERE instrument_key = ? AND minute_ts >= ? AND minute_ts < ?
                  AND high_price IS NOT NULL AND low_price IS NOT NULL AND open_price IS NOT NULL
                ORDER BY minute_ts
                """,
                (instrument_key, session_date, f"{session_date}T99"),
            ).fetchall()
        return [(str(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4] or row[1])) for row in rows]

    def index_daily_bars_between(
        self,
        tokens: list[str],
        start: str,
        end: str,
    ) -> dict[str, list[tuple[str, float, float, float, float]]]:
        """Index daily OHLC per token from ``index_candles``, oldest first."""
        out: dict[str, list[tuple[str, float, float, float, float]]] = {}
        for token in dict.fromkeys(tokens):
            if not token:
                continue
            with self.connection() as conn:
                rows = conn.execute(
                    """
                    SELECT substr(ts, 1, 10), open_price, high_price, low_price, close_price
                    FROM index_candles
                    WHERE instrument_token = ? AND timeframe = 'daily'
                      AND substr(ts, 1, 10) >= ? AND substr(ts, 1, 10) <= ?
                    ORDER BY ts
                    """,
                    (token, start, end),
                ).fetchall()
            if rows:
                out[token] = [
                    (str(row[0]), row[1] or 0.0, row[2] or 0.0, row[3] or 0.0, row[4] or 0.0) for row in rows
                ]
        return out

    def latest_scan_pattern_rows(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            latest = conn.execute("SELECT MAX(trade_date) AS trade_date FROM pattern_signals").fetchone()
            trade_date = latest["trade_date"] if latest else None
            if not trade_date:
                return []
            rows = conn.execute(
                """
                SELECT ticker, pattern_type, score, details_json, trade_date
                FROM pattern_signals
                WHERE trade_date = ?
                """,
                (trade_date,),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_scan_myb_rows(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            latest = conn.execute("SELECT MAX(trade_date) AS trade_date FROM myb_signals").fetchone()
            trade_date = latest["trade_date"] if latest else None
            if not trade_date:
                return []
            rows = conn.execute(
                """
                SELECT ticker, prior_high, score, status, trade_date, strategy
                FROM myb_signals
                WHERE trade_date = ?
                """,
                (trade_date,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_grimes_dates(self, limit: int = 365, *, engine_version: str | None = None) -> list[str]:
        clauses = ["status = 'completed'"]
        params: list[Any] = []
        if engine_version is not None:
            clauses.append("engine_version = ?")
            params.append(engine_version)
        params.append(int(limit))
        with self.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT DISTINCT trade_date FROM grimes_runs
                WHERE {' AND '.join(clauses)}
                ORDER BY trade_date DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [row["trade_date"] for row in rows]


def _write_live_minute_bars(conn: sqlite3.Connection, bars: list[dict[str, Any]]) -> int:
    rows = [
        (
            bar["instrument_key"],
            bar["minute_ts"],
            bar.get("volume"),
            bar.get("close_price"),
            bar.get("source") or "live_ws",
            bar.get("open_price"),
            bar.get("high_price"),
            bar.get("low_price"),
        )
        for bar in bars
    ]
    conn.executemany(
        """
        INSERT INTO live_minute_bars (
            instrument_key, minute_ts, volume, close_price, source, open_price, high_price, low_price
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(instrument_key, minute_ts) DO UPDATE SET
            volume = excluded.volume,
            close_price = excluded.close_price,
            source = excluded.source,
            open_price = excluded.open_price,
            high_price = excluded.high_price,
            low_price = excluded.low_price
        """,
        rows,
    )
    return len(rows)


def _write_live_call_journal(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> int:
    payload = [
        (
            row["session_date"],
            row["symbol"],
            row["side"],
            row.get("kind"),
            row.get("company_name"),
            row.get("stance"),
            row["entry"],
            row["stop"],
            row["exit_price"],
            row["status"],
            row["opened_at"],
            row.get("entry_at"),
            row.get("closed_at"),
            row.get("last_price"),
            row.get("result_pct"),
            row.get("mfe_pct"),
            row.get("mae_pct"),
            row["updated_at"],
            row.get("fill_price"),
            row.get("swing_exit"),
            row.get("swing_status"),
            row.get("swing_result_pct"),
            row.get("swing_closed_at"),
            row.get("segment"),
        )
        for row in rows
    ]
    conn.executemany(
        """
        INSERT INTO live_call_journal (
            session_date, symbol, side, kind, company_name, stance,
            entry, stop, exit_price, status, opened_at, entry_at, closed_at,
            last_price, result_pct, mfe_pct, mae_pct, updated_at, fill_price,
            swing_exit, swing_status, swing_result_pct, swing_closed_at, segment
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_date, symbol, side) DO UPDATE SET
            kind = excluded.kind,
            company_name = excluded.company_name,
            stance = excluded.stance,
            status = excluded.status,
            entry_at = excluded.entry_at,
            closed_at = excluded.closed_at,
            last_price = excluded.last_price,
            result_pct = excluded.result_pct,
            mfe_pct = excluded.mfe_pct,
            mae_pct = excluded.mae_pct,
            updated_at = excluded.updated_at,
            fill_price = excluded.fill_price,
            swing_exit = COALESCE(live_call_journal.swing_exit, excluded.swing_exit),
            swing_status = excluded.swing_status,
            swing_result_pct = excluded.swing_result_pct,
            swing_closed_at = excluded.swing_closed_at,
            segment = COALESCE(excluded.segment, live_call_journal.segment)
        """,
        payload,
    )
    return len(payload)


_ATR_PERIOD = 14


def _aligned_bars(rows: list[Any]) -> list[tuple[float, float, float]]:
    return [
        (float(row["high_price"] or 0), float(row["low_price"] or 0), float(row["close_price"] or 0))
        for row in rows
    ]


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _atr_pct(bars: list[tuple[float, float, float]], last_close: float | None) -> float | None:
    """Simple 14-bar average true range as a percent of the last close. Bars newest first."""
    if not last_close or len(bars) < 2:
        return None
    ranges: list[float] = []
    for index in range(min(_ATR_PERIOD, len(bars) - 1)):
        high, low, _close = bars[index]
        prev_close = bars[index + 1][2]
        if high <= 0 or low <= 0 or prev_close <= 0:
            continue
        ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    if not ranges:
        return None
    return sum(ranges) / len(ranges) / last_close * 100.0


def _efficiency(closes: list[float]) -> float | None:
    """Kaufman efficiency ratio: net move over path length. Near 0 is chop, near 1 is trend."""
    if len(closes) < 3:
        return None
    path = sum(abs(closes[i] - closes[i + 1]) for i in range(len(closes) - 1))
    if path <= 0:
        return None
    return abs(closes[0] - closes[-1]) / path


def _daily_history_stats(
    *,
    volumes: list[float],
    closes: list[float],
    highs: list[float],
    lows: list[float],
    prior_high: Any,
    prior_low: Any,
    prior_close: Any,
    prior_date: str,
    bar_count: int,
    bars: list[tuple[float, float, float]] | None = None,
) -> dict[str, Any]:
    """Newest-first closes. ``closes[-1]`` is the oldest close in the window.

    Typical volume is the median, not the mean: one expiry, rebalance, or
    block-deal day in the window would otherwise lift the RVOL baseline for
    the next twenty sessions.
    """
    last_close = float(prior_close or 0) or None
    oldest_close = closes[-1] if closes else None
    close_5_back = closes[5] if len(closes) >= 6 else None
    trend_20 = None
    if last_close and oldest_close:
        trend_20 = (last_close - oldest_close) / oldest_close * 100.0
    return_5d = None
    if last_close and close_5_back:
        return_5d = (last_close - close_5_back) / close_5_back * 100.0
    return {
        "avg_volume_20": _median([volume for volume in volumes if volume > 0]),
        "atr_pct": _atr_pct(bars or [], last_close),
        "efficiency_20": _efficiency(closes),
        "prior_high": prior_high,
        "prior_low": prior_low,
        "prior_close": prior_close,
        "prior_date": prior_date,
        "sma20": (sum(closes) / len(closes)) if closes else None,
        "high_20": max(highs) if highs else None,
        "low_20": min(lows) if lows else None,
        "trend_20_pct": trend_20,
        "return_5d_pct": return_5d,
        "history_bars": bar_count,
    }


_store: TimelineStore | None = None


def get_store() -> TimelineStore:
    global _store
    if _store is None:
        import os

        db_path = Path(os.getenv("TIMELINE_DB_PATH", str(DEFAULT_DB_PATH)))
        _store = TimelineStore(db_path)
    return _store
