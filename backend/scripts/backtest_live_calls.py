#!/usr/bin/env python3
"""Replay the live Session Call rules on daily candles and score the saved live record.

Writes one JSON report per run to data/live_scan_backtest/, named by the
parameters, so runs with different settings can be compared side by side.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ROOT_DIR
from app.db.store import get_store
from app.services.live_scan.backtest import BacktestParams, journal_scorecard, last_completed_session, run_backtest

OUTPUT_DIR = ROOT_DIR / "data" / "live_scan_backtest"
_DEFAULTS = BacktestParams(start="2000-01-01", end="2000-01-01")


def _fmt(value: object, suffix: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:+.3f}{suffix}" if suffix == "R" else f"{value:.1f}{suffix}"
    return f"{value}{suffix}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from-date", default=None, help="YYYY-MM-DD inclusive, default one year before --to-date")
    parser.add_argument("--to-date", default=None, help="YYYY-MM-DD inclusive, default the last session")
    parser.add_argument("--segment", default="all", choices=["fno", "cash", "all"])
    parser.add_argument("--side", default="both", choices=["buy", "sell", "both"])
    for name in ("reward_r", "swing_r", "entry_window_r", "min_efficiency", "risk_min_atr", "risk_max_atr", "cost_pct"):
        parser.add_argument(f"--{name.replace('_', '-')}", type=float, default=getattr(_DEFAULTS, name))
    parser.add_argument("--max-swing-days", type=int, default=_DEFAULTS.max_swing_days)
    parser.add_argument("--trades", type=int, default=500, help="Most recent trades kept in the report")
    args = parser.parse_args()

    end = args.to_date or last_completed_session()
    start = args.from_date or (date.fromisoformat(end) - timedelta(days=365)).isoformat()
    params = BacktestParams(
        start=start,
        end=end,
        segment=args.segment,
        side=args.side,
        reward_r=args.reward_r,
        swing_r=args.swing_r,
        entry_window_r=args.entry_window_r,
        min_efficiency=args.min_efficiency,
        risk_min_atr=args.risk_min_atr,
        risk_max_atr=args.risk_max_atr,
        max_swing_days=args.max_swing_days,
        cost_pct=args.cost_pct,
    )
    print(f"Replaying {params.segment} {params.side} calls {start} → {end} …", flush=True)
    result = run_backtest(params, trades_limit=args.trades)
    result["live_record"] = journal_scorecard(
        get_store().list_live_call_journal_range(None, None),
        cost_pct=params.cost_pct,
        segment=params.segment,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = (
        f"{start}_{end}_{params.segment}_{params.side}_r{params.reward_r:g}_s{params.swing_r:g}"
        f"_w{params.entry_window_r:g}_e{params.min_efficiency:g}_c{params.cost_pct:g}"
    )
    path = OUTPUT_DIR / f"{stem}.json"
    path.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")

    day, swing, bounds = result["day"], result["swing"], result["day"].get("bounds") or {}
    live = result["live_record"]["day"]
    print(f"  universe {result['universe']['symbols']} symbols, {result['elapsed_ms'] / 1000:.1f}s")
    print(f"  funnel   {result['funnel']}")
    print(
        f"  day      {day.get('trades', 0)} trades, win {_fmt(day.get('win_rate_pct'), '%')}, "
        f"avg {_fmt(day.get('avg_r'), 'R')}, PF {_fmt(day.get('profit_factor'))}, "
        f"optimistic avg {_fmt(bounds.get('optimistic_avg_r'), 'R')} ({_fmt(bounds.get('ambiguous_pct'), '%')} ambiguous)"
    )
    print(
        f"  swing    {swing.get('trades', 0)} resolved, win {_fmt(swing.get('win_rate_pct'), '%')}, "
        f"avg {_fmt(swing.get('avg_r'), 'R')}, PF {_fmt(swing.get('profit_factor'))}, {swing.get('avg_days')} days held"
    )
    print(f"  live     {live.get('trades', 0)} resolved, win {_fmt(live.get('win_rate_pct'), '%')}, avg {_fmt(live.get('avg_r'), 'R')}")
    for item in result["insights"][:8]:
        print(
            f"  {item['direction']:>6}  {item['dimension']}: {item['group']} — {item['trades']} trades, "
            f"{item['avg_r']:+.3f}R ({item['delta_r']:+.3f}R, t={item['t_stat']})"
        )
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
