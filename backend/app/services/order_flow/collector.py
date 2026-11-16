"""Order Flow's collector: the market file every minute, futures on demand.

Ported from the standalone server (server/index.mjs). Each build reads every
underlying's nearest live option chain (eight at a time) and writes one market
file. In market hours it rebuilds every ``BUILD_EVERY_S`` and keeps each build's
minute under ``backend/data/order_flow`` for the 15m and 1h windows. Outside
them it rebuilds hourly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from .market_file import encode_series, market_file
from .session import filter_live_expiries, ist_hhmm, is_market_session_time, latest_trading_session_date

logger = logging.getLogger(__name__)

WORKERS = 8
# Upstox's Standard APIs allow 2,000 calls per 30 minutes. One build is about 208 option-chain calls, so
# rebuilding every minute used the whole allowance in about ten minutes. Every 4 minutes leaves room for
# the futures reads and the rest of the lab.
BUILD_EVERY_S = 240
FUTURES_KEEP_S = 60
UNIVERSE_PATH = Path(__file__).with_name("underlyings.json")
DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "order_flow"
PROVIDER_ERROR = "The data provider did not answer. The server log has the detail."


def load_universe() -> list[dict[str, Any]]:
    raw = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))["underlyings"]
    return [u for u in raw if isinstance(u, dict) and isinstance(u.get("symbol"), str) and (u.get("lot") or 0) > 0]


class OrderFlowCollector:
    def __init__(self, provider: Any, universe: list[dict[str, Any]], data_dir: Path = DATA_DIR) -> None:
        self.provider = provider
        self.universe = universe
        self.by_symbol = {u["symbol"]: u for u in universe}
        self.data_dir = data_dir
        self.scan_dir = data_dir / provider.id
        self.ready = False
        self.building = False
        self.latest: dict[str, Any] | None = None
        self.latest_json: str | None = None
        self.last_build: dict[str, Any] | None = None
        self.last_error: dict[str, Any] | None = None
        self._ladder_session = ""
        self._ladders: dict[str, list[str]] = {}
        self._futures: dict[str, tuple[float, asyncio.Future]] = {}
        self._task: asyncio.Task | None = None

    # ── Clock and storage ──────────────────────────────────────────────────

    @staticmethod
    def now_ms() -> float:
        return time.time() * 1000

    def _read_minutes(self, date: str) -> list[list[Any]]:
        try:
            return json.loads((self.scan_dir / date / "index.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _store_minute(self, date: str, at: float, payload: str) -> list[list[Any]]:
        day_dir = self.scan_dir / date
        day_dir.mkdir(parents=True, exist_ok=True)
        hhmm = ist_hhmm(at)
        (day_dir / f"{hhmm}.json").write_text(payload, encoding="utf-8")
        minutes = [entry for entry in self._read_minutes(date) if entry[0] != hhmm]
        minutes.append([hhmm, at])
        minutes.sort(key=lambda entry: entry[1])
        (day_dir / "index.json").write_text(json.dumps(minutes), encoding="utf-8")
        return minutes

    def _prune_old_days(self, today: str) -> None:
        if not self.scan_dir.exists():
            return
        for entry in self.scan_dir.iterdir():
            if entry.is_dir() and len(entry.name) == 10 and entry.name < today:
                shutil.rmtree(entry, ignore_errors=True)

    def load_from_disk(self) -> None:
        """Serve the last file on disk at once, so a restart does not start blank."""
        try:
            self.latest_json = (self.scan_dir / "latest.json").read_text(encoding="utf-8")
            self.latest = json.loads(self.latest_json)
        except (OSError, ValueError):
            pass

    # ── Market file ────────────────────────────────────────────────────────

    async def build(self) -> None:
        if self.building:
            return
        self.building = True
        started = time.monotonic()
        clock = self.now_ms()
        session = latest_trading_session_date(clock)
        if self._ladder_session != session:
            self._ladder_session = session
            self._ladders.clear()

        series: list[dict[str, Any]] = []
        ladders: dict[str, list[str]] = {}
        failed: list[str] = []
        errors: dict[str, int] = {}
        semaphore = asyncio.Semaphore(WORKERS)

        async def read(u: dict[str, Any]) -> None:
            symbol = u["symbol"]
            async with semaphore:
                try:
                    ladder = self._ladders.get(symbol)
                    if ladder is None:
                        ladder = await self.provider.expiries(u)
                        if ladder:
                            self._ladders[symbol] = ladder
                    live = filter_live_expiries(ladder or [], clock)
                    ladders[symbol] = live
                    if not live:
                        return
                    chain = await self.provider.option_chain(u, live[0])
                    chain = {**chain, "expiry": chain.get("expiry") or live[0]}
                    encoded = encode_series(u, chain, self.now_ms())
                    if encoded is not None:
                        series.append(encoded)
                    else:
                        failed.append(symbol)
                except Exception as error:  # one underlying must not stop the board
                    failed.append(symbol)
                    message = str(error)[:200]
                    errors[message] = errors.get(message, 0) + 1

        try:
            await asyncio.gather(*(read(u) for u in self.universe))
            # Count the reasons, so a rate limit that hits every underlying is named, not one stray miss.
            top_error = max(errors.items(), key=lambda item: item[1]) if errors else None
            first_error = f"{top_error[0]} (x{top_error[1]} of {len(self.universe)})" if top_error else None
            if not series:
                detail = f"No underlying answered: {first_error}" if first_error else "No underlying answered."
                raise RuntimeError(detail)
            at = self.now_ms()
            ordered = sorted(series, key=lambda s: s["s"])
            if is_market_session_time(at):
                payload = json.dumps(market_file(at=at, date=session, series=ordered, minutes=[], ladders=ladders))
                minutes = self._store_minute(session, at, payload)
            else:
                minutes = self._read_minutes(session)
            file = market_file(at=at, date=session, series=ordered, minutes=minutes, ladders=ladders)
            self.latest = file
            self.latest_json = json.dumps(file)
            self.scan_dir.mkdir(parents=True, exist_ok=True)
            (self.scan_dir / "latest.json").write_text(self.latest_json, encoding="utf-8")
            self._prune_old_days(session)
            self.last_build = {
                "at": at,
                "ms": round((time.monotonic() - started) * 1000),
                "series": len(series),
                "failed": len(failed),
                "failedSymbols": failed[:20],
                "firstError": first_error,
            }
            self.last_error = None
            logger.info(
                "order flow market file: %d series, %d failed, %d ms%s",
                len(series),
                len(failed),
                self.last_build["ms"],
                f"; failures: {first_error}" if failed and first_error else "",
            )
        except Exception as error:
            logger.exception("order flow market file failed: %s", error)
            self.last_error = {"at": round(time.time() * 1000), "message": PROVIDER_ERROR}
        finally:
            self.building = False

    # ── Futures, on demand ─────────────────────────────────────────────────

    async def futures_for(self, symbol: str, session: str) -> dict[str, Any]:
        key = f"{symbol}|{session}"
        held = self._futures.get(key)
        live = is_market_session_time(self.now_ms())
        if held and (not live or time.monotonic() - held[0] < FUTURES_KEEP_S):
            value = await held[1]
            return value
        task = asyncio.ensure_future(self._read_futures(symbol, session))
        self._futures[key] = (time.monotonic(), task)
        try:
            return await task
        except Exception:
            self._futures.pop(key, None)
            raise

    async def _read_futures(self, symbol: str, session: str) -> dict[str, Any]:
        months = await self.provider.futures(self.by_symbol[symbol], session)
        return {"symbol": symbol, "session": session, "months": months}

    # ── Schedule ───────────────────────────────────────────────────────────

    async def run(self) -> None:
        """First build at once, then every BUILD_EVERY_S in market hours (a few seconds past the boundary), else hourly."""
        try:
            await self.build()
            self.ready = True
        except Exception:
            logger.exception("order flow collector failed to start")
        while True:
            now = time.time()
            if is_market_session_time(now * 1000):
                wait = BUILD_EVERY_S - (now % BUILD_EVERY_S) + 3
            else:
                wait = 3600
            await asyncio.sleep(wait)
            await self.build()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self.run())

    def status(self) -> dict[str, Any]:
        latest = self.latest
        return {
            "provider": {"id": self.provider.id, "label": self.provider.label, "alwaysLive": bool(self.provider.alwaysLive)},
            "ready": self.ready,
            "clock": round(self.now_ms()),
            "session": latest_trading_session_date(self.now_ms()),
            "market": {"at": latest["t"], "date": latest["date"], "series": len(latest["series"])} if latest else None,
            "lastBuild": self.last_build and {"at": self.last_build["at"], "series": self.last_build["series"], "failed": self.last_build["failed"]},
            "lastError": self.last_error and {"at": self.last_error["at"], "message": self.last_error["message"]},
            "universe": len(self.universe),
        }
