# Equity Scan Lab

NSE equity scanners, sector rotation, timeline movers, and zero-shot forecasting. Forecast engines:

| Model | ID | Description |
|-------|-----|-------------|
| **TimesFM 2.5** (default) | `timesfm-2.5` | Google PyTorch zero-shot foundation model |
| **TimesFM-Fin** | `timesfm-fin` | [PFN financial fine-tune](https://tech.preferred.jp/en/blog/timesfm/) on TimesFM 1.0 |

Historical OHLCV is fetched from **Upstox** (primary) with automatic **NSE API fallback**. The React UI covers momentum/screener workflows plus forecast on **daily / weekly / monthly** intervals with **candlestick history** and forecast overlay.

## Architecture

```
React UI (Vite :5173)
    ↓ /api/*
FastAPI backend (:9000)
    ├── Upstox HistoryV3Api (primary)
    ├── NSE historical APIs (fallback)
    ├── TimesFM 2.5 inference (in-process PyTorch)
    └── TimesFM-Fin inference (Python 3.10 subprocess → timesfm_fin/)
```

## Quick start

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Optional but recommended for Upstox data
cp ../.env.example ../.env
# Edit ../.env and set UPSTOX_ACCESS_TOKEN

uvicorn app.main:app --reload --port 9000
```

First forecast request downloads TimesFM weights from Hugging Face (~400MB). CPU inference works; GPU is used automatically when available.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

### 3. Upstox token (optional)

Set `UPSTOX_ACCESS_TOKEN` in `.env`, or paste your OAuth token in the UI settings panel. Without a token, the backend uses NSE public historical endpoints.

Generate a token: https://upstox.com/developer/api-documentation/authentication/

### 4. TimesFM-Fin (optional)

PFN's financial fine-tune uses the JAX TimesFM 1.x API — separate Python 3.10 environment:

```bash
cd timesfm_fin && ./setup.sh
```

Then in `.env`:

```env
FORECAST_MODEL=timesfm-fin
TIMESFM_FIN_PYTHON=/absolute/path/to/trading/timesfm_fin/.venv/bin/python
```

See [timesfm_fin/README.md](timesfm_fin/README.md) for weight loading details.

## API

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Health check |
| `GET /api/nifty50` | Nifty 50 symbol list (NSE archive CSV) |
| `GET /api/models` | Available forecast models |
| `GET /api/forecast?symbol=RELIANCE&interval=daily&model=timesfm-fin` | Fetch candles + run forecast |

**Headers:** `x-upstox-access-token` (optional, overrides server env token)

**Intervals:** `daily` (20 steps), `weekly` (12 steps), `monthly` (6 steps)

All intervals use **5 years** of underlying daily data. Weekly/monthly bars are resampled from daily OHLCV.

## Charts

The UI renders full OHLC **candlesticks** (via lightweight-charts) for the selected timeframe, with TimesFM median forecast and 80% quantile band overlaid as dashed lines.

## Project layout

```
trading/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry
│   │   ├── services/
│   │   │   ├── upstox_client.py # Upstox SDK wrapper
│   │   │   ├── nse_client.py    # NSE session + historical fallback
│   │   │   ├── market_data.py   # Unified fetch + resampling
│   │   │   └── timesfm_service.py
│   │   └── routes/forecast.py
│   └── requirements.txt
├── frontend/                    # React + Vite + Tailwind + Recharts
└── .env.example
```

## Notes

- Minimum 32 historical bars required (TimesFM patch size constraint).
- Weekly/monthly series are resampled from daily Upstox/NSE candles.
- `normalize_inputs=True` in TimesFM handles scale differences across stocks.
- Quantile bands (10th–90th percentile) are surfaced as an 80% prediction interval.

## News Impact (RedboxGlobal Telegram)

Ingest headlines from [@indiaredboxglobal](https://t.me/indiaredboxglobal), link company names to NSE tickers, measure T+0…T+5 reactions on local daily candles, optional Gemini extract/outlook. Full details: [docs/news_impact.md](docs/news_impact.md).

```bash
# .env: TELEGRAM_API_ID, TELEGRAM_API_HASH, optional GEMINI_API_KEY
npm run news:login
npm run news:backfill
```

| Route | Description |
|-------|-------------|
| `/news-impact` | UI — events, chart markers, reaction table, outlook |
| `POST /api/news/sync` | Incremental or backfill sync |
| `GET /api/news/events` | Linked news events |
| `GET /api/news/ticker/{ticker}/impact` | Aggregates + markers |

## Setup watchlist (before the breakout)

Lists stocks still inside a base each evening, then alerts when one reaches its pivot: at 9:08 from the opening auction, and live during the session. It also reads NSE filings the minute they are published. Read the results section of [docs/early_setup.md](docs/early_setup.md) before trading it: on NSE data for February 2025 to November 2026, taking every setup mechanically lost money after costs.

```bash
npm run setups:data -- --days 500   # once: delivery, corporate actions, industries (add --candles / --index if needed)
npm run setups:build                # each evening, after the daily candle ingest
npm run setups:report               # how the list has done, by exit rule
npm run setups:fit                  # derive the score's weights from your candles and test them on unseen sessions
npm run setups:filings-history      # once: a year of filings, to measure what each kind did to prices
```

| Route | Description |
|-------|-------------|
| `/setups` | UI — both lists with live state, filings, resolved setups, alerts, results |
| `GET /api/early-setup/watchlist` | Stored lists (`status=`, `list=daily|weekly|all`) with flags, events, large buys, pre-open |
| `POST /api/early-setup/build` | Top up NSE data and update the lists from daily candles |
| `GET /api/early-setup/live` | Watchlist stocks against their pivots on the live feed |
| `GET/POST /api/early-setup/preopen` | The 9:08 opening-auction reading for watchlist stocks |
| `GET /api/early-setup/filings` | Price-moving NSE filings with size, and what each kind did to prices |
| `GET /api/early-setup/alerts` | Alerts raised (also sent to Telegram when configured) |
| `GET /api/early-setup/report` | Results by exit rule, market state and score (`list=`, `max_positions=`) |

## OI Support Momentum (intraday)

Live ATM support-zone scanner using **rolling Upstox option-chain polls** (3–5 minute windows). See [docs/oi_momentum_scanner.md](docs/oi_momentum_scanner.md).

| Route | Description |
|-------|-------------|
| `/oi-momentum` | UI — REST poll or **Start live OI** (WebSocket); 3–5m rolling window |
| `GET /api/oi-momentum/evaluate` | Evaluate (`source=auto|rest|websocket`) |
| `POST /api/oi-momentum/stream/start` | Upstox WS live OI on ATM zone strikes |

**Changelog (2026-06-30):** WebSocket live OI via Upstox Market Data Feed V3; hybrid with rolling 3m/5m engine.

## Order Flow

The standalone order-flow board, served from this app’s Upstox feed. A market file of nearest-expiry option chains is rebuilt every 4 minutes in the session. Futures build-up is the front-month price change read against the open-interest change. Full notes: [docs/order_flow.md](docs/order_flow.md).

| Route | Description |
|-------|-------------|
| `/order-flow` | UI — the order-flow board |
| `GET /api/order-flow/market` | Latest market file |
| `GET /api/order-flow/futures/{symbol}` | Front-month future for the current session |

The live scan uses the same daily build-up rules on its own futures ticks. A buy into short build-up, and a sell into long build-up, stand aside. The other readings are labels on the call.

## Newsdesk

Multi-source market headlines in the lab database. RSS from the Newsdesk source list is stored for 30 days, clustered into stories when headlines match, and tagged with lab tickers from the alias list. Summaries are extractive sentences from the feed blurb.

| Route | Description |
|-------|-------------|
| `/newsdesk` | UI — story list, category and ticker filters, blurb summary |
| `GET /api/newsdesk?days=3&refresh=true` | Refresh feeds and return clustered stories |
| `GET /api/newsdesk/summary?link=` | Extractive summary of a stored article |
