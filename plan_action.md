# Momentum Scanner — Plan of Action

**Date:** 2026-07-14  
**Dataset:** 5,737 signals · 48 scan dates (2026-01-05 → 2026-07-10) · min score 70  
**Key finding:** Scanner is primarily a **confirmation / lagging** system — alerts fire after stocks have already moved, with modest follow-through.

---

## 1. Executive Summary

| Question | Answer |
|----------|--------|
| Does the scanner flag stocks **before** they move? | **Mostly no** — only ~12% are `setup_ready` (pre-breakout) |
| Does it flag stocks **after** they move? | **Yes** — 88% `triggered_today`; avg +20.7% in prior 20 sessions |
| Is there still edge after the alert? | **Some** — +3.0% avg at 5d, 69% win rate; fades by 10d (median -0.9%) |
| Best pattern for early entry? | `inside_bar_cluster` (+5.6% fwd, 46% triggered) |
| Weakest pattern? | `pocket_pivot` (+2.0% fwd, 100% triggered, already extended) |

**Strategic choice:** Keep as a momentum-confirmation scanner (tune thresholds) **or** pivot toward an early-setup scanner (new filters + pattern weighting). This plan supports both via phased changes.

---

## 2. Current Implementation

### 2.1 Pipeline

```
daily_candles (SQLite)
    → run_scanner()                    [engine.py]
        → liquidity filter             [filters.py]
        → Minervini trend template     [trend_template.py]  → macro_pass
        → 5 pattern scorers            [patterns.py]
        → fundamental gate             [context.py]
        → market score delta           [context.py]
        → F&O overlay + multiplier     [fo_overlay.py]
    → pattern_signals table
    → GET /api/scanner/results         [routes/scanner.py]
    → MomentumScannerPage              [frontend]
```

**Scripts**

| Command | Purpose |
|---------|---------|
| `npm run scanner:run` | Run scan for a date |
| `npm run scanner:analysis` | Build backtest export |
| `npm run scanner:analysis:llm` | Compact 1 MB LLM export |

**Analysis outputs:** `data/scanner_analysis/` — see `docs/scanner_analysis.md`

### 2.2 Patterns (`backend/app/services/scanner/patterns.py`)

| Pattern | MIN_SCORE | Trigger logic | Share of signals | Nature |
|---------|-----------|---------------|------------------|--------|
| `vcp` | 85 | Requires price > 10d pivot; `triggered_today` if vol dry | ~70% | Breakout confirmation |
| `pocket_pivot` | 90 | Up day + vol > max down-day vol; always triggered | ~27% | Same-day volume thrust |
| `high_tight_flag` | 95 | 30%+ flagpole + tight flag | ~2% | Late-stage continuation |
| `inside_bar_cluster` | 95 | 2 inside bars; triggered if breaks mother high | ~1% | Most anticipatory |
| `power_gap` | 85 | 3%+ gap + 2.5× vol + strong close; always triggered | <1% | Gap chase |

### 2.3 Scoring

- **Pattern score** (0–100) from pattern-specific rules
- **Composite score** = pattern score × context adjustment × F&O multiplier
- **macro_pass** = Minervini trend template (price > SMA50 > 150 > 200, near 52w high, etc.)
- **fundamental_pass** = fundamentals gate (informational; not a hard filter today)
- UI default **min score = 70**; API filters: pattern, sector, `triggered_only`, `setup_only`, `macro_pass_only`

### 2.4 Frontend (`MomentumScannerPage.tsx`)

- Scan date picker with alert-date markers
- Filters: pattern, sector, min score, triggered/setup toggles, macro/fundamental pass
- Chart with optional VCP overlay
- F&O derivative sync on load
- Default loads `latest_with_alerts` date

### 2.5 What the backtest measured

- **Entry:** signal-day close
- **Pre-scan:** 25 sessions (~5 weeks) before signal
- **Forward:** 5d / 10d / 20d returns, max favorable/adverse

---

## 3. Backtest Findings (Evidence)

### 3.1 Pre-move vs post-move

| Window | Avg return |
|--------|------------|
| Prior 20 sessions (to entry) | **+20.7%** |
| Prior 10 sessions | +6.5% |
| Signal day | +1.0% |
| Forward 5 sessions | **+3.0%** |
| Forward 10 sessions | +0.4% (median **-0.9%**) |

~**7×** more gain happened **before** the alert than in the next 5 sessions.

### 3.2 Extension at signal time

| Pre-20d gain | % of signals | Forward 5d |
|--------------|--------------|------------|
| > 30% | 22% | +3.3% |
| 20–30% | 21% | +3.8% |
| 10–20% | 32% | +2.7% |
| 0–10% | 22% | +2.3% |
| < 0% | 3% | +3.9% |

**58%** of signals fire after the stock is already up **>15%** in 20 sessions.

### 3.3 Triggered vs setup

| Flag | Count | Pre-20d | Forward 5d | Win 5d |
|------|-------|---------|------------|--------|
| `triggered_today` | 88% | +20.0% | +2.9% | 68.5% |
| `setup_ready` | 12% | +25.9% | +3.7% | 72.9% |

Setup-ready signals are fewer but slightly better forward — worth surfacing in UI.

### 3.4 By pattern (forward 5d)

| Pattern | Avg 5d | Win 5d | Notes |
|---------|--------|--------|-------|
| inside_bar_cluster | +5.6% | 76% | Best; often pre-breakout |
| power_gap | +4.8% | 67% | Already gapped; small N |
| high_tight_flag | +4.7% | 76% | Late but strong |
| vcp | +3.3% | 73% | Bulk of output |
| pocket_pivot | +2.0% | 59% | Worst; chase pattern |

### 3.5 Score paradox

| Score band | Avg 5d | Win 5d |
|------------|--------|--------|
| 70–79 | +3.45% | 73% |
| 80–89 | +3.39% | 73% |
| 90+ | +2.05% | 60% |

Higher scores correlate with **more obvious / already-moved** setups, not better forward returns.

### 3.6 Signal-day spike penalty

| Signal-day return | Forward 5d |
|-------------------|------------|
| Spike > 3% | +2.6% |
| Flat / down | +3.5% |

Chasing the obvious green day slightly **hurts** follow-through.

---

## 4. Suggested Changes

### Phase 1 — Quick wins (UI + filters, no pattern rewrite)

**Goal:** Let users avoid chase entries without changing core detectors.

| # | Change | Rationale | Files |
|---|--------|-----------|-------|
| 1.1 | Add **scan mode** toggle: `Confirmation` (default) vs `Early setup` | Early mode applies preset filters | `MomentumScannerPage.tsx`, `scanner.py` |
| 1.2 | Early setup preset: `setup_only=true`, hide `pocket_pivot` + `power_gap` by default | Best forward slice in data | Frontend preset |
| 1.3 | Add **extension filter**: max pre-20d return (e.g. skip if > 20%) | 58% of signals are already extended | `analysis.py` compute `pre_20d_return_pct` at scan time; store in `details`; API filter |
| 1.4 | Add **signal-day spike filter**: skip if daily return > 3% | Spike days underperform forward | Use `daily_return_pct` already in details |
| 1.5 | Show **timing badges** on rows: `Triggered` / `Setup` / `Extended` | Makes lag visible at a glance | `MomentumScannerPage.tsx` |
| 1.6 | Default sort: `setup_ready` first, then score | Surfaces anticipatory signals | Frontend + API sort option |

**Acceptance:** Early-setup mode shows < 30% of current row count; backtest slice shows fwd 5d ≥ 3.5%.

---

### Phase 2 — Scoring & threshold tuning

**Goal:** Align MIN_SCORES and composite score with measured forward returns.

| # | Change | Current | Suggested | Rationale |
|---|--------|---------|-----------|-----------|
| 2.1 | Raise `pocket_pivot` MIN_SCORE | 90 | **95** | Worst fwd (+2.0%); reduce volume |
| 2.2 | Lower `inside_bar_cluster` MIN_SCORE | 95 | **90** | Best fwd (+5.6%); tiny sample — encourage more |
| 2.3 | Add **extension penalty** to composite score | — | -5 to -15 pts if pre-20d > 15/25% | Penalize chase without hard-dropping |
| 2.4 | Add **trigger penalty** optional | — | -3 pts if `triggered_today` in Early mode | Nudge ranking toward setup |
| 2.5 | Invert score-band trust | UI treats 90+ as "best" | Show **efficiency score** = fwd_potential proxy (lower extension + setup_ready bonus) | Fixes score paradox |
| 2.6 | Revisit `macro_pass` weighting | macro_pass slightly worse fwd | Do **not** hard-require macro; use as soft +5 context only | Data: macro_pass 5d +2.4% vs +3.2% |

**Files:** `patterns.py`, `engine.py`, `context.py`, `patterns.py` MIN_SCORES

**Validation:** Re-run `npm run scanner:analysis -- --skip-scan --min-score 70 --days 48` and compare aggregates.

---

### Phase 3 — Pattern logic improvements

**Goal:** Add true leading setups; reduce breakout-day-only detection.

| # | Change | Description |
|---|--------|-------------|
| 3.1 | **VCP two-stage** | Emit `setup_ready` when contracting + near pivot (no breakout); `triggered_today` only on pivot break + vol confirmation |
| 3.2 | **Pocket pivot variant** | New `pocket_pivot_setup`: vol building but not yet exceeded down-day max (pre-trigger) |
| 3.3 | **Extension cap** | Hard reject patterns when pre-20d return > 35% (except HTF with shallow flag) |
| 3.4 | **Base depth gate** | Prefer VCP with base_depth < 25%; penalize deep bases already up 20%+ |
| 3.5 | **New pattern: tight range near pivot** | 5–10 day range < 5% within 5% of pivot — pure anticipatory |

**Files:** `patterns.py`, `indicators.py`, tests

---

### Phase 4 — Analysis & feedback loop

| # | Change | Description |
|---|--------|-------------|
| 4.1 | Store `pre_20d_return_pct` + `signal_day_return_pct` on every signal at scan time | Enables live filtering without re-backtest |
| 4.2 | Add `timing_class` enum: `early` / `confirmation` / `extended` | Single field for UI + API |
| 4.3 | Weekly auto-export hook | Cron or manual `scanner:analysis` to track drift |
| 4.4 | Dashboard card: lagging vs leading mix per scan date | Ops visibility |

---

## 5. Recommended Priority Order

```
Week 1   Phase 1 (UI presets + extension/spike filters + badges)
Week 2   Phase 2.1–2.3 (MIN_SCORES + extension penalty)
Week 3   Phase 3.1 (VCP two-stage) — highest impact for early setups
Week 4   Phase 4.1–4.2 (persist timing metrics) + re-backtest
```

---

## 6. Proposed Default Presets

### Confirmation mode (current behaviour, tuned)

- min score: 70
- all patterns
- no extension cap
- sort: composite score desc
- **Use when:** riding established momentum, accepting lag

### Early setup mode (new)

- min score: 75
- patterns: `vcp`, `inside_bar_cluster`, `high_tight_flag`
- `setup_only = true`
- max pre-20d return: 20%
- max signal-day return: 2%
- exclude: `pocket_pivot`, `power_gap`
- sort: setup_ready first, then efficiency score
- **Use when:** seeking entries before breakout

---

## 7. Success Metrics

Re-evaluate after each phase with `scanner:analysis`:

| Metric | Baseline (now) | Target (early mode) |
|--------|----------------|---------------------|
| `setup_ready` share | 12% | ≥ 35% of displayed rows |
| Avg pre-20d at entry | +20.7% | ≤ +12% |
| Forward 5d avg | +3.0% | ≥ +3.5% |
| Forward 10d median | -0.9% | ≥ 0% |
| Signals per scan day | ~120 | 20–50 (quality over quantity) |
| pocket_pivot share | 27% | ≤ 10% |

---

## 8. Key Files Reference

| Area | Path |
|------|------|
| Pattern detectors | `backend/app/services/scanner/patterns.py` |
| Scan engine | `backend/app/services/scanner/engine.py` |
| Trend template | `backend/app/services/scanner/trend_template.py` |
| Analysis / export | `backend/app/services/scanner/analysis.py` |
| Build script | `backend/scripts/build_scanner_analysis.py` |
| LLM compact script | `backend/scripts/compact_scanner_for_llm.py` |
| API routes | `backend/app/routes/scanner.py` |
| Frontend | `frontend/src/pages/MomentumScannerPage.tsx` |
| Analysis docs | `docs/scanner_analysis.md` |
| LLM dataset | `data/scanner_analysis/scanner_refinement_llm.json` |
| Full dataset | `data/scanner_analysis/scanner_refinement_dataset.json` |

---

## 9. Open Decisions

1. **Product positioning:** Confirmation scanner vs early-setup scanner — or both via mode toggle? *(Recommend: both via toggle.)*
2. **Hard vs soft extension cap:** Filter out extended stocks entirely, or penalize score only? *(Recommend: soft penalty in Confirmation, hard cap in Early.)*
3. **Pocket pivot:** Raise threshold, rework, or demote to watchlist-only? *(Recommend: raise to 95 + exclude from Early mode.)*
4. **Intraday / WebSocket:** Future work for same-day spike detection — out of scope for daily scanner refactor.

---

## 10. Next Step

Start **Phase 1.1 + 1.3**: add `pre_20d_return_pct` at scan time and an **Early setup** preset in the scanner UI. Re-run analysis to validate the filtered slice matches backtest expectations.
