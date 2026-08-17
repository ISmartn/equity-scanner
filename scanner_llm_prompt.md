# Momentum Scanner Refinement — LLM Task Prompt

You are working on a NSE momentum scanner (FastAPI + React). Backtest: 5,737 signals, 48 scan dates (2026-01-05 → 2026-07-10), min score 70.

## Problem

The scanner is **lagging**, not anticipatory:
- 88% `triggered_today` vs 12% `setup_ready`
- Avg +20.7% gain in prior 20 sessions before alert; only +3.0% forward over next 5 sessions (~7× more move already happened)
- 58% of signals fire after stock is already up >15% in 20d
- Score 90+ underperforms 70–79 (+2.05% vs +3.45% fwd 5d) — high scores = obvious/chase setups
- `pocket_pivot` worst (+2.0% fwd, 100% triggered); `inside_bar_cluster` best (+5.6% fwd, most anticipatory)

Edge exists but modest: 69% win rate at 5d; fades by 10d (median -0.9%).

## Current stack

- Patterns (`patterns.py`): vcp (85, ~70%), pocket_pivot (90, ~27%), high_tight_flag (95), inside_bar_cluster (95), power_gap (85)
- VCP requires breakout above 10d pivot; pocket_pivot & power_gap always `triggered_today`
- Score = pattern score × context adjustment × F&O multiplier
- UI (`MomentumScannerPage.tsx`): filters for pattern, min score 70, triggered/setup, macro/fundamental
- API: `backend/app/routes/scanner.py`

## Your task

Implement **Phase 1** first, then Phase 2 if time permits. Match existing code style; minimal focused diffs.

### Phase 1 — UI + filters (no pattern rewrite)

1. **Scan mode toggle**: `Confirmation` (default) vs `Early setup`
2. **Early setup preset**:
   - min score 75
   - patterns: vcp, inside_bar_cluster, high_tight_flag only
   - `setup_only=true`
   - exclude pocket_pivot, power_gap
   - max pre-20d return ≤ 20%
   - max signal-day return ≤ 2%
   - sort: setup_ready first, then score
3. **Compute at scan time** (store in signal `details`):
   - `pre_20d_return_pct`
   - `timing_class`: `early` | `confirmation` | `extended` (extended if pre-20d > 15%)
4. **API filters**: `max_pre_20d_return`, `max_signal_day_return`
5. **UI badges** on rows: Triggered / Setup / Extended

**Acceptance:** Early mode shows <30% of rows; filtered backtest slice targets fwd 5d ≥ 3.5%.

### Phase 2 — Scoring tuning

- Raise `pocket_pivot` MIN_SCORE 90 → 95
- Lower `inside_bar_cluster` MIN_SCORE 95 → 90
- Extension penalty on composite score: -5 to -15 if pre-20d > 15/25%
- Optional efficiency score for ranking (penalize extension, bonus setup_ready)
- macro_pass: soft context only, not hard filter

### Phase 3 (later) — Pattern logic

- VCP two-stage: setup_ready before breakout, triggered on pivot break
- Hard extension cap at 35% pre-20d
- New anticipatory pattern: tight range near pivot

## Key files

`backend/app/services/scanner/patterns.py`, `engine.py`, `analysis.py`, `backend/app/routes/scanner.py`, `frontend/src/pages/MomentumScannerPage.tsx`

## Constraints

- Daily scanner only; no intraday/WebSocket
- Confirmation mode keeps current behaviour as default
- Soft extension penalty in Confirmation; hard cap in Early mode
- Validate with: `npm run scanner:analysis -- --skip-scan --min-score 70 --days 48`

## Success metrics (early mode targets)

| Metric | Baseline | Target |
|--------|----------|--------|
| setup_ready share | 12% | ≥35% |
| avg pre-20d | +20.7% | ≤+12% |
| fwd 5d avg | +3.0% | ≥+3.5% |
| signals/scan day | ~120 | 20–50 |

Start with Phase 1.1 + 1.3: `pre_20d_return_pct` at scan time + Early setup preset in UI.
