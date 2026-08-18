#!/usr/bin/env python3
"""Rescan July 2026 trading days with current SCANNER_ENGINE_VERSION (darvas_v1)."""

from __future__ import annotations

from datetime import date

from app.services.market_calendar import trading_days_in_month_through
from app.services.scanner.engine import SCANNER_ENGINE_VERSION, run_scanner


def main() -> None:
    days = trading_days_in_month_through(date(2026, 7, 31))
    print(
        f"engine={SCANNER_ENGINE_VERSION} days={len(days)} first={days[0]} last={days[-1]}",
        flush=True,
    )

    completed: list[str] = []
    for i, scan_date in enumerate(days, start=1):

        def on_progress(update: dict, *, _i: int = i, _d: str = scan_date) -> None:
            if update.get("phase") == "ticker" and update.get("processed"):
                p = int(update.get("processed") or 0)
                t = int(update.get("total") or 0)
                if p == t or p % 500 == 0:
                    print(
                        f"  [{_i}/{len(days)}] {_d} {p}/{t} alerts={update.get('alerts_count')}",
                        flush=True,
                    )

        print(f"=== [{i}/{len(days)}] scanning {scan_date} ===", flush=True)
        result = run_scanner(trade_date=scan_date, on_progress=on_progress)
        completed.append(scan_date)
        print(
            f"done {scan_date}: alerts={result.get('alerts_count')} "
            f"scanned={result.get('symbols_scanned')} engine={result.get('engine_version')}",
            flush=True,
        )

    print("COMPLETED", len(completed), completed[0], "->", completed[-1], flush=True)


if __name__ == "__main__":
    main()
