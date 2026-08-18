# Scanner patterns and status reference

Plain-language definitions for **pattern** and **status** fields in the Momentum Scanner UI, API, and JSON export.

**Related:** [momentum_scanner.md](./momentum_scanner.md) (workflow, scoring overlays, API), [scanner_analysis.md](./scanner_analysis.md) (backtest export).

**F&O overlay (★ star, FO gate, FO n/a):** [below](#fo-overlay-futures--options).

---

## Where these fields appear

| Surface | Pattern field | Status field |
|---------|---------------|--------------|
| **API** (`GET /api/scanner/results`) | `pattern_type` (machine ID) | `triggered_today` + `setup_ready` (booleans) |
| **UI table** | Human label (e.g. “Pocket Pivot”) | Filter checkboxes **Trigger** / **Setup** (not a column) |
| **JSON export** | `pattern` (human label) | `status`: `"trigger"` \| `"setup"` \| `"structure"` |

Export mapping is implemented in `frontend/src/lib/scannerExport.ts`.

---

## Pattern (`pattern` / `pattern_type`)

A **pattern** is a named chart setup detected on the **scan date’s daily bar** from local OHLCV. Detection is **price and volume only** — fundamentals and macro trend do **not** block a pattern from firing.

### Pattern IDs and labels

| `pattern_type` (API) | Export `pattern` (label) | Category | One-line meaning |
|----------------------|--------------------------|----------|------------------|
| `vcp` | VCP | Macro structure | Volatility contracting in a base; price breaks above a 10-day pivot |
| `high_tight_flag` | High Tight Flag | Macro structure | Sharp flagpole rally, then a tight low-volume flag |
| `pocket_pivot` | Pocket Pivot | Micro trigger | Up-day with volume exceeding any recent down-day volume |
| `inside_bar_cluster` | Inside Bar Cluster | Micro setup/trigger | Wide “mother” bar, then nested inside bars; breakout optional |
| `power_gap` | Power Gap | Micro trigger | Large gap-up on heavy volume with a strong close (not earnings-verified) |
| `tight_range_near_pivot` | Tight Range Near Pivot | Micro setup | Tight 5–10d range near local pivot |
| `darvas_pre_setup` | Darvas Pre-Setup | Micro setup/trigger | Uptrend + coil near 20d high (Darvas-style); trigger on pivot break |

**Category**

- **Macro structure** — multi-week base or consolidation shape (VCP, HTF).
- **Micro trigger** — actionable signal on today’s bar (pocket pivot, power gap).
- **Micro setup/trigger** — can appear as setup before breakout or as trigger after (inside bar cluster).

A single ticker can produce **multiple rows** on the same date if more than one pattern scores above its minimum.

---

## Pattern rules (implementation)

Logic lives in `backend/app/services/scanner/patterns.py`. Minimum scores below are required to **persist** a signal (tune via `MIN_SCORES` in that file).

### VCP — Volatility Contraction Pattern

**Idea:** Price compresses in progressively tighter ranges while volume dries up, then breaks above a short-term pivot — classic Mark Minervini / William O’Neil style contraction.

| Rule | Threshold |
|------|-----------|
| Base depth (40d) | ≤ 30% |
| Range contraction | 20d range > 10d range > 5d range |
| Breakout | Close above max high of prior 10 sessions (excl. today) |
| Min score to save | **85** |

**Key `details` fields:** `stage` (`mid` \| `late`), `range_5d_pct`, `volume_dry`, `breakout`, `pivot_high`, `base_depth_pct`.

**Status on scan day:** see [Status](#status-trigger--setup--structure) — depends on whether volume is “dry” vs still elevated.

---

### High Tight Flag

**Idea:** Stock runs up sharply (flagpole), then pauses in a very tight, low-volume flag before a potential continuation.

| Rule | Threshold |
|------|-----------|
| Flagpole gain | 30–100% over ~20 sessions |
| Flag depth | ≤ 10% over last ~10 sessions |
| Closes | Prefer upper half of flag range |
| Volume | Flag volume < 70% of pole volume |
| Min score to save | **95** (effectively disabled in practice — rarely fires) |

**Key `details` fields:** `flagpole_pct`, `flag_depth_pct`, `volume_contracting`.

---

### Pocket Pivot

**Idea:** Institutional-style accumulation day — up-day volume swamps volume on prior down-days, ideally near a 52-week high base.

| Rule | Threshold |
|------|-----------|
| Day type | Up-day (close ≥ open or close > prior close) |
| Volume | Today’s volume > max volume on down-days in prior 10 sessions |
| Volume z-score | ≥ 1.0 (50-day window) |
| Base context | Within 15% of 52-week high (`in_base`) boosts score |
| Min score to save | **90** |

**Key `details` fields:** `in_base`, `volume_ratio`, `volume_zscore`, `close_position` (0–1 within day’s range).

**Status on scan day:** always **trigger** (fires only when conditions are met today).

---

### Inside Bar Cluster

**Idea:** A wide bullish mother bar, then two consecutive inside bars (lower volatility); breakout above the mother bar is the trigger.

| Rule | Threshold |
|------|-----------|
| Mother bar | Range > 1.5× ATR(10); bullish close |
| Inside bars | 2 nested inside bars after mother |
| Cluster volume | Average inside-bar volume < mother volume |
| Min score to save | **95** |

**Key `details` fields:** `inside_bars`, `mother_date`, `volume_contracting`.

**Status:** **setup** until price breaks above the mother high; **trigger** on breakout day.

---

### Power Gap

**Idea:** Gap-up open (≥ 3% above prior high), huge volume (≥ 2.5× 20d average), close in top 15% of the day’s range. **Not** confirmed against an earnings calendar.

| Rule | Threshold |
|------|-----------|
| Gap | Open ≥ 103% of prior session high |
| Volume | ≥ 2.5× 20-day average; z-score ≥ 1.5 |
| Extension | Close ≤ 125% of SMA50 (not too extended) |
| Min score to save | **85** |

**Key `details` fields:** `gap_pct`, `volume_ratio`, `volume_zscore`, `peg_confirmed: false`.

**Status on scan day:** always **trigger**.

---

### Darvas Pre-Setup

**Idea:** Recurring pre-breakout structure from Darvas-style / influencer calibration — stock already in an uptrend (higher lows, above rising SMA20), coiling with contracting ranges near the 20-day high. Setup while coiled under the pivot; trigger when close breaks the prior 20d high.

| Rule | Threshold |
|------|-----------|
| Structure | Higher lows (10d vs prior 10d) |
| Trend | Close &gt; SMA20 (prefer rising SMA20) |
| Coil | 20d &gt; 10d &gt; 5d range, **or** box-like (10d ≤12%, 5d ≤8%) |
| Location | Within ~3% of prior 20d high (or breakout today) |
| Extension | Prior 20d return ≤ 25% (hard gate) |
| Min score to save | **80** |

**Key `details` fields:** `stage` (`coil` \| `breakout`), `volatility_contraction`, `darvas_box_like`, `pivot_high_20d`, `distance_to_pivot_pct`, `volume_dry`, `pre_20d_return_pct`.

**Status:** **setup** while coiling under pivot; **trigger** on breakout day.

---

## Status (`trigger` | `setup` | `structure`)

**Status** answers: *“What happened on the scan date for this pattern?”* — not whether macro or fundamentals passed.

### Export values

| Export `status` | API flags | Meaning |
|-----------------|-----------|---------|
| **`trigger`** | `triggered_today: true` | The pattern’s **action condition** is satisfied on the scan date (e.g. pocket pivot volume surge, VCP with dry volume, inside-bar breakout). |
| **`setup`** | `setup_ready: true`, `triggered_today: false` | Structure is forming; **entry trigger not yet confirmed** on this bar (e.g. VCP before volume dries, inside bars before breakout). |
| **`structure`** | both `false` | Pattern scored and saved, but neither trigger nor setup flag is set (uncommon; mostly legacy edge cases). |

Mapping:

```text
triggered_today ? "trigger" : setup_ready ? "setup" : "structure"
```

### Per-pattern status behavior

| Pattern | Typical `status` | When it is `trigger` | When it is `setup` |
|---------|------------------|----------------------|---------------------|
| Pocket Pivot | `trigger` | Always (only saved if fired today) | Never |
| Power Gap | `trigger` | Always | Never |
| VCP | `trigger` or `setup` | `volume_dry: true` on scan bar | Contraction + breakout met, volume not yet dry |
| High Tight Flag | `trigger` or `setup` | Closes in upper flag + volume contracting | Flag forming, close not yet in upper half |
| Inside Bar Cluster | `trigger` or `setup` | Close breaks above mother high | Inside bars present, no breakout yet |

### UI filters vs export

On `/scanner`, **Status** checkboxes map to the API:

- **Trigger** → `triggered_only=true` → rows with `triggered_today`
- **Setup** → `setup_only=true` → rows with `setup_ready`

If both are unchecked, results include triggers **and** setups. If both are checked, the API returns rows that are either (OR logic in `store.list_pattern_signals`).

---

## What pattern and status do **not** mean

| Field | Common misconception | Actual behavior |
|-------|---------------------|-----------------|
| `pattern` | “This stock is a buy” | Only describes **which** price/volume rule matched |
| `status: trigger` | “All quality gates passed” | Only means **pattern-specific** trigger logic fired today |
| `macro_pass` | Part of `status` | Separate boolean — Minervini trend template (SMA stack, 52w position) |
| `fundamental_pass` | Part of `score` | Separate flag — ROE/ROCE thresholds; failure does not lower pattern score |
| `score` | Overall quality grade | **Pattern score only** (0–100 from OHLCV rubric) |

### Score fields (export)

| Field | Description |
|-------|-------------|
| `score` / `pattern_score` | Pure pattern quality from OHLCV rules |
| `context_adjustment` | Bonus/penalty from fundamentals (+3 if pass) and market (PCR, FII) |
| `composite_score` | `(pattern_score + context_adjustment) × fo_multiplier` when F&O data exists; else pattern + context, capped at 100 |

Strong pocket pivots often hit **pattern_score 100** even when `macro_pass` and `fundamental_pass` are false, because those gates are stored separately.

**Note:** When F&O overlay applies a multiplier, `composite_score` becomes `(pattern_score + context_adjustment) × fo_multiplier` (see [F&O overlay](#fo-overlay-futures--options) below). The UI **Score** column still shows `pattern_score` only.

---

## F&O overlay (Futures & Options)

For NSE equities in the **F&O segment** (~180 names vs ~2,400 in the scan universe), the scanner can layer **option-chain positioning** on top of the OHLCV pattern. This is separate from the ★ star, **Macro**, and **Fund** gates.

**Implementation:** `backend/app/services/scanner/fo_overlay.py`, enrichment on read in `fo_enrich.py`, auto-sync in `fo_sync.py`.

### UI: ★ star vs FO gate pill

| UI element | Meaning |
|------------|---------|
| **★ (amber star)** | Ticker is in the NSE F&O list (`GET /api/fno`). Shown for any F&O name in the alerts table. |
| **FO pass / warn / neutral / n/a** | Gate pill under the ticker — only on ★ rows. Reflects whether **derivative snapshot data** exists and how OI/price behaved on the scan date. |

Hover the pill for a short tooltip explaining the state.

### FO gate states

| Pill | `fo_overlay` condition | Meaning |
|------|------------------------|---------|
| **FO pass** | `available: true`, quadrant = long build-up | Price up (>0.5%) and option OI up (>5% vs prior session) — institutional confirmation. |
| **FO warn** | `available: true`, quadrant = short covering or short build-up | Fragile rally (price up, OI down) or bearish OI build (price down, OI up). Short build-up **hard-rejects** on a fresh scan. |
| **FO neutral** | `available: true`, quadrant = neutral or long unwinding | Snapshot loaded; OI/price mix is inconclusive (no strong multiplier). |
| **FO n/a** | `available: false` or missing `fo_overlay` | No usable option-chain snapshot for this **ticker + scan date**. |

**Important:** ★ means “F&O listed”; **FO n/a** means “we don’t have (or couldn’t fetch) derivative data for this date.” Most ★ alerts show **FO n/a** until you sync derivatives for that date.

### Why FO n/a appears

1. **No row in `derivative_snapshots`** for `{symbol, trade_date}` — default sync only covers indices + a few stocks; use `--all-fno` for full coverage.
2. **Auto-sync failed or didn’t run** — needs valid `UPSTOX_ACCESS_TOKEN` in `.env`, symbol in `security_profiles`, and Upstox API availability. Check the scanner banner (“Fetching F&O derivative data…” / error text).
3. **Scan predates F&O overlay** — older `details_json` may lack `fo_overlay`; `GET /api/scanner/results` recomputes it from DB on every load (no re-scan required).
4. **Not confused with neutral** — if data exists but the OI quadrant is flat, you should see **FO neutral** (blue), not n/a.

### Data source and limits

| Metric | Source | Used in overlay? |
|--------|--------|------------------|
| Total call/put OI, PCR, max pain | `derivative_snapshots` (Upstox Market Info API) | Yes — day-over-day OI Δ and PCR Δ |
| Futures OI (NSE FO bhavcopy) | Not ingested | No — option OI used as proxy (`oi_source: "options_chain"`) |
| Cost of carry, IV rank, rollover | Not ingested | No — listed in `fo_overlay.unsupported` |

Prior-session snapshot is required to compute **OI change %**; first day of sync for a symbol may show **FO neutral** with `reason: "missing_price_or_oi_delta"` until a second day exists.

### Quadrant rules (scan date)

Thresholds from `fo_overlay.py`:

| Quadrant | Condition | Scan effect |
|----------|-----------|-------------|
| Long build-up | Price ↑ >0.5% and OI ↑ >5% | ×1.15 multiplier |
| Short covering | Price ↑ and OI ↓ <-5% | ×0.85 multiplier |
| Short build-up | Price ↓ and OI ↑ | **Signal dropped** on fresh scan |
| Long unwinding | Price ↓ and OI ↓ | Neutral (×1.0) |
| PCR support | PCR change > +15% | Extra ×1.05 |

### Score fields with F&O

| Field | Description |
|-------|-------------|
| `score` / `pattern_score` | Pure OHLCV pattern quality (UI **Score** column) |
| `context_adjustment` | Additive: fundamentals (+3) + market PCR/FII (±1–3) |
| `fo_multiplier` | 1.0 default; 1.15 / 0.85 / etc. from quadrants |
| `composite_score` | `(pattern_score + context_adjustment) × fo_multiplier`, capped at 100 |
| `fo_overlay` | Quadrant, OI/PCR deltas, `available`, `reason`, `would_reject` (read path only) |

F&O overlay does **not** reduce `pattern_score`; it adjusts **composite** via multiplier and can **filter out** short build-ups at scan time.

### Auto-fetch behavior

| When | What happens |
|------|----------------|
| **Scan completes** | Engine syncs missing derivatives for F&O tickers in the hit list, then re-applies FO overlay before save. |
| **Load results** | UI calls `POST /api/scanner/ensure-derivatives` for ★ rows missing snapshots, then reloads. |
| **Select alert row** | Same ensure for that ticker if still missing. |

API: `POST /api/scanner/ensure-derivatives` with body `{ "trade_date": "YYYY-MM-DD", "tickers": ["RELIANCE", …] }`. Only F&O names are synced; others are ignored.

### Manual sync (full F&O universe)

```bash
# All F&O equity underlyings with local profiles (~180 names; slow)
npm run market-info:sync -- --derivatives-only --date 2026-06-24 --all-fno

# Specific symbols only
npm run market-info:sync -- --derivatives-only --date 2026-06-24 --symbols RELIANCE,TCS,INFY
```

Requires `UPSTOX_ACCESS_TOKEN` in `.env`. Check coverage:

```bash
cd backend && .venv/bin/python -c "
from app.db.store import get_store
s = get_store()
rows = s.list_derivative_snapshots(trade_date='2026-06-24', limit=200)
print(len(rows), 'snapshots:', sorted({r['symbol'] for r in rows}))
"
```

### VCP chart overlay (optional)

Separate from the FO gate: when pattern is **VCP**, toggle **VCP overlay** above the chart to draw 20d/10d/5d contraction bands and pivot line. Preference stored in `localStorage` (`trading.scannerVcpOverlay`).

### Example `fo_overlay` in `details`

```json
{
  "fo_overlay": {
    "available": true,
    "oi_source": "options_chain",
    "quadrant": "long_buildup",
    "quadrant_label": "Long build-up (price ↑, OI ↑)",
    "oi_change_pct": 8.2,
    "pcr_change_pct": 12.1,
    "pcr": 0.88,
    "total_oi": 2450000,
    "prior_trade_date": "2026-06-23",
    "multiplier": 1.15,
    "unsupported": ["cost_of_carry", "iv_rank", "rollover"]
  },
  "fo_multiplier": 1.15,
  "composite_score": 92.0
}
```

When data is missing:

```json
{
  "fo_overlay": {
    "available": false,
    "oi_source": "options_chain",
    "reason": "no_derivative_snapshot",
    "unsupported": ["cost_of_carry", "iv_rank", "rollover"]
  },
  "fo_multiplier": 1.0
}
```

---

`macro_pass` uses the Minervini-style **trend template** on the scan bar (`backend/app/services/scanner/trend_template.py`):

- Price > SMA50 > SMA150 > SMA200  
- SMA200 rising vs 20 sessions ago  
- Price ≥ 30% above 52-week low  
- Price within 25% of 52-week high  

Patterns are detected **whether or not** macro passes. Use the **Macro pass** UI filter to restrict results to Stage-2-style trends.

---

## Example export row

```json
{
  "date": "2026-06-24",
  "ticker": "AUBANK",
  "pattern": "Pocket Pivot",
  "score": 100,
  "pattern_score": 100,
  "macro_pass": true,
  "fundamental_pass": true,
  "status": "trigger",
  "why": "Passes Minervini trend template ... Trigger fired on 2026-06-24. ..."
}
```

- **`pattern`** — human-readable pattern name  
- **`status: trigger`** — pocket pivot conditions met on `2026-06-24`  
- **`macro_pass` / `fundamental_pass`** — independent quality flags  
- **`why`** — auto-generated narrative from flags + `details` (see `describeScannerWhy` in `scannerExport.ts`)

---

## Quick reference card

```text
PATTERN  = which setup (VCP, Pocket Pivot, …)
STATUS   = trigger (act today) | setup (watch) | structure (rare)

trigger     → triggered_today
setup       → setup_ready, not triggered
structure   → neither flag

score       → pattern quality only (UI Score column)
macro_pass  → trend template (separate filter)
fundamental_pass → ROE/ROCE (separate filter; +3 to context when true)
★           → F&O-listed (NSE); not a data-quality flag
FO pill     → pass | warn | neutral | n/a — option OI overlay (see F&O section)
composite   → (pattern + context) × fo_multiplier
```
