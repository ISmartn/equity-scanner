# OI Support Momentum Scanner

Live intraday scanner for **ATM support-zone** bullish momentum: put writers adding OI while call writers unwind, with volume confirmation.

**Research / monitoring only — not investment advice.**

## Why not cumulative `change_oi`?

Upstox `get_change_oi_data` measures OI change over **days** (the `interval` parameter is a day count, e.g. `5` = five sessions). That is useful for EOD positioning (see `/market-info` and scanner FO overlay) but **not** for intraday momentum:

| Approach | Source | Window | Problem |
|----------|--------|--------|---------|
| Cumulative daily change | `get_change_oi_data` | 1–N **days** | Fires once threshold breached; no velocity |
| **Rolling snapshot delta** | `get_put_call_option_chain` polled every 60–90s | 3–5 **minutes** | Captures what is happening *right now* |

This module uses the second approach.

## Strategy (refined)

### Support zone

Instead of a single ATM strike (which flickers when spot oscillates ±25 pts), we monitor:

- **Smoothed ATM** — hysteresis: ATM only shifts when spot moves ≥ 35% of strike step away from the sticky strike
- **ATM − 1 step** — OTM put wall (e.g. 22,000 + 21,950 for Nifty)

### Rolling momentum

Between poll `t` and baseline `t − Δt`:

```
Δput_OI_zone  = Σ max(0, put_oi_now − put_oi_prev)   over zone strikes
Δcall_OI_zone = Σ min(0, call_oi_now − call_oi_prev)
Δput_vol_zone = Σ max(0, put_vol_now − put_vol_prev)
```

### Alert levels

| Level | Conditions |
|-------|------------|
| **warming** | First polls — building baseline (need ~1× window of history) |
| **neutral** | No rapid put surge in window |
| **mild** | Put OI surge (>2% of zone put OI) + volume gate |
| **strong** | Mild gates + call unwind + PCR momentum ≥ 2 + volume confirmed |

### Volume gate (illiquidity filter)

Put OI Δ alone can be a block-deal mirage. **Strong** alerts require zone put **volume** Δ ≥ 500 contracts in the window (tunable in `engine.py`).

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/oi-momentum/symbols` | Default symbol list |
| `GET` | `/api/oi-momentum/evaluate?symbol=NIFTY&window_sec=180` | Poll chain + evaluate (requires Upstox token) |

**Headers:** `x-upstox-access-token` (optional if set in server `.env`)

**Query params:**

- `symbol` — `NIFTY`, `BANKNIFTY`, or F&O stock in `security_profiles`
- `window_sec` — rolling compare window (60–900, default **180** = 3 min)
- `expiry` — optional `YYYY-MM-DD`; nearest expiry from NSE if omitted

## UI

Route: **`/oi-momentum`**

- Symbol + window (3m / 5m) selectors
- Auto-poll every 45–90s (recommended; respects Upstox rate limits)
- Alert banner, gate checklist, zone strike table

## Polling recommendation

**Use 3- or 5-minute windows with 60–90 second polls** — not tick-by-tick. Tick-level OI would hammer the API and OI updates on NSE are not true tick streams anyway.

After ~3 minutes of polling at 60s intervals, the **warming** state clears and rolling alerts become meaningful.

## Code layout

```
backend/app/services/oi_momentum/
├── engine.py          # Zone math, ATM smoothing, alert rules
├── snapshot_store.py  # In-memory rolling chain history per symbol
└── service.py         # Upstox chain fetch + orchestration

backend/app/routes/oi_momentum.py
frontend/src/pages/OiMomentumPage.tsx
```

## Upstox endpoints used

| Endpoint | Purpose |
|----------|---------|
| `OptionsApi.get_put_call_option_chain` | Live per-strike OI + volume + spot |
| NSE `option-chain-contract-info` | Nearest expiry resolution |

**Not used for intraday momentum:** `MarketApi.get_change_oi_data` (day interval only).

## WebSocket live OI (recommended in session)

Upstox **Market Data Feed V3** (`MarketDataStreamerV3`) pushes protobuf ticks with **`oi`** and **`vtt`** (volume) in `full` mode — confirmed in [MarketDataFeed.proto](https://assets.upstox.com/feed/market-data-feed/v3/MarketDataFeed.proto).

### Hybrid architecture (optimal for this app)

| Layer | Mechanism | Purpose |
|-------|-----------|---------|
| **Bootstrap** | One REST `get_put_call_option_chain` | Map zone strikes → `instrument_key` |
| **Stream** | WS `ltpc` on index + `full` on 4 zone options | Live spot + OI/volume ticks |
| **Sample** | ~5s (3s in 30s scalp) | Finer history for short live windows |
| **Alerts** | Same engine, scaled gates | **30s scalp** (live only) through **5m** |

REST-only mode keeps **3m / 5m** windows (60s poll cadence makes shorter windows unreliable). Live mode can use **1m / 2m** because OI updates continuously over WS — not once per REST poll.

### API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/oi-momentum/stream/start` | `{ "symbol": "NIFTY" }` — connect WS |
| `POST` | `/api/oi-momentum/stream/stop?symbol=NIFTY` | Disconnect |
| `GET` | `/api/oi-momentum/stream/status?symbol=NIFTY` | Connection + tick count |
| `GET` | `/api/oi-momentum/evaluate?source=auto` | WS if stream active, else REST |

| UI: **Start live OI** on `/oi-momentum` — evaluate auto-switches to WebSocket; UI refreshes every **~10s** (no REST chain fetch). Window dropdown adds **1m / 2m** when live is on.

**System alerts:** toggle **Alerts on** — sound, floating toast, and OS browser notification when the backend emits a **new** `alert_event` (mild/strong full window, or early partial with surge + volume). Each event is logged to `backend/data/oi_momentum_alerts.jsonl` with spot trail, price delta, and zone OI. Use **Export alerts** or `GET /api/oi-momentum/alerts`.

### Limits & notes

- Subscribes to **5 keys** (index spot + 2 strikes × CE/PE) — well within Upstox feeder limits.
- **Not** full chain over WS (200+ strikes) — only ATM zone.
- Zone rotation on smoothed ATM shift re-subscribes using bootstrap strike map (refresh chain on long sessions if needed).
- `full_d30` available for depth; OI momentum uses `full` (includes OI + volume).

## Changelog

### Phase 1.4 — Alert quality refinements (2026-06-30)

From live NIFTY 30s scalp session analysis (42 alerts):

- **Volume gate:** OI/volume ratio band (cumulative `vtt` deltas always passed naive ≥250 threshold)
- **Price alignment:** suppress when spot falls sharply vs baseline (bullish OI + falling price)
- **Strike rotation:** suppress when ATM put build pairs with lower-strike put unwind
- **Cooldown:** ≥45s between alerts per symbol; dedup bucket 25k OI (was 1k)
- **`signal_quality`** on evaluation + alert records for post-trade review

### Phase 1.3 — 30s scalp mode (2026-06-30)

- Live-only **30s** window in UI with **high noise** warning
- **5s** evaluate + **3s** snapshots when window ≤ 30s
- Volume/surge gates scaled linearly from 60s baseline (500 vol / 2% surge → 250 / 1% at 30s)
- REST path still clamps to **≥60s**

### Phase 1.2 — Fast live windows (2026-06-30)

- Live-only **1m / 2m** rolling windows in UI
- Snapshot sample **5s** on stream; evaluate **~10s** when live
- Auto-default to **2m** when starting live from 3m+; revert to **3m** when stopping

### Phase 1.1 — WebSocket live OI (2026-06-30)

- `MarketDataStreamerV3` integration for zone strikes
- `POST /stream/start|stop`, `source=auto|websocket|rest`
- UI live toggle; evaluate when streaming

### Phase 1 — OI Support Momentum (2026-06-30)

- Rolling multi-strike support-zone scanner with ATM hysteresis
- Volume confirmation gate for strong alerts
- `/oi-momentum` UI + `GET /api/oi-momentum/evaluate`
- Unit tests for hysteresis and strong-alert path
