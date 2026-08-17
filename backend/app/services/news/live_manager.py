"""In-process Telegram live feed manager (start/stop from API)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from .listen import run_live_listener

logger = logging.getLogger(__name__)


class LiveFeedManager:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self.status: str = "stopped"  # stopped | starting | running | stopping | error
        self.error: str | None = None
        self.started_at: str | None = None
        self.stopped_at: str | None = None
        self.last_event_at: str | None = None
        self.catch_up: bool = True

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "running": self.status in {"starting", "running"},
            "error": self.error,
            "started_at": self.started_at,
            "stopped_at": self.stopped_at,
            "last_event_at": self.last_event_at,
            "catch_up": self.catch_up,
        }

    def note_event(self) -> None:
        self.last_event_at = datetime.now(timezone.utc).isoformat()

    async def start(self, *, catch_up: bool = True, process: bool = True) -> dict[str, Any]:
        if self._task and not self._task.done():
            raise RuntimeError("Live feed is already running")

        self.catch_up = catch_up
        self.error = None
        self.status = "starting"
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.stopped_at = None
        self._stop_event = asyncio.Event()

        async def _runner() -> None:
            try:
                self.status = "running"
                await run_live_listener(
                    catch_up=catch_up,
                    process=process,
                    stop_event=self._stop_event,
                    on_message=lambda: self.note_event(),
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Live feed crashed")
                self.status = "error"
                self.error = str(exc)
            finally:
                if self.status != "error":
                    self.status = "stopped"
                self.stopped_at = datetime.now(timezone.utc).isoformat()
                self._task = None
                self._stop_event = None

        self._task = asyncio.create_task(_runner(), name="telegram-news-live")
        return self.snapshot()

    async def stop(self) -> dict[str, Any]:
        if not self._task or self._task.done():
            self.status = "stopped"
            return self.snapshot()

        self.status = "stopping"
        if self._stop_event:
            self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.error = str(exc)
        self.status = "stopped"
        self.stopped_at = datetime.now(timezone.utc).isoformat()
        self._task = None
        self._stop_event = None
        return self.snapshot()


_manager: LiveFeedManager | None = None


def get_live_manager() -> LiveFeedManager:
    global _manager
    if _manager is None:
        _manager = LiveFeedManager()
    return _manager
