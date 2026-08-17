from __future__ import annotations

import os
import sys
import threading
import time
from typing import Callable


def _supports_ansi() -> bool:
    return sys.stdout.isatty() and os.getenv("NO_COLOR") is None


def _status_color(status: str, text: str) -> str:
    if not _supports_ansi():
        return text
    colors = {
        "Overbought": "\033[91m",  # red
        "Oversold": "\033[92m",  # green
        "Neutral": "\033[97m",  # white
        "Warming": "\033[93m",  # yellow
    }
    reset = "\033[0m"
    return f"{colors.get(status, '')}{text}{reset}"


class TerminalDashboard:
    """Live-updating terminal snapshot for multi-TF RSI."""

    def __init__(
        self,
        get_snapshot: Callable[[], dict],
        get_feed_status: Callable[[], str],
        *,
        refresh_hz: float = 4.0,
        instrument_label: str = "Nifty 50",
    ) -> None:
        self._get_snapshot = get_snapshot
        self._get_feed_status = get_feed_status
        self._interval = 1.0 / max(refresh_hz, 0.5)
        self._label = instrument_label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._use_clear = _supports_ansi()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="mtf-rsi-dashboard",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def render_once(self) -> str:
        snap = self._get_snapshot()
        period = snap.get("rsi_period", "?")
        ltp = snap.get("ltp")
        ts = snap.get("ts") or "—"
        frames = snap.get("timeframes") or {}

        lines: list[str] = []
        lines.append("=" * 64)
        lines.append(f"  {self._label} Multi-Timeframe RSI  |  feed={self._get_feed_status()}")
        lines.append("-" * 64)
        ltp_txt = f"{ltp:,.2f}" if isinstance(ltp, (int, float)) else "—"
        lines.append(f"  Time     : {ts}")
        lines.append(f"  LTP      : {ltp_txt}")
        lines.append(f"  Period   : RSI({period})")
        lines.append("-" * 64)
        lines.append(f"  {'TF':<6}{'RSI':>8}  {'Status':<12}{'Buf':>6}")
        lines.append(f"  {'-'*6}{'-'*8}  {'-'*12}{'-'*6}")

        for tf in sorted(frames.keys(), key=lambda x: int(x)):
            row = frames[tf]
            value = row.get("rsi")
            status = row.get("status") or "Warming"
            buf = row.get("buffer", 0)
            rsi_txt = f"{value:6.2f}" if isinstance(value, (int, float)) else "   n/a"
            colored_status = _status_color(status, f"{status:<12}")
            lines.append(f"  {str(tf)+'m':<6}{rsi_txt:>8}  {colored_status}{buf:>6}")

        lines.append("=" * 64)
        lines.append("  Commands: rsi <n>   |   q / quit")
        return "\n".join(lines)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                frame = self.render_once()
                if self._use_clear:
                    sys.stdout.write("\033[H\033[J")
                sys.stdout.write(frame + "\n")
                sys.stdout.flush()
            except Exception as exc:
                sys.stderr.write(f"dashboard error: {exc}\n")
            self._stop.wait(self._interval)
