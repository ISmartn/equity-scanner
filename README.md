# TimesFM Nifty 50 Forecast

Zero-shot stock price forecasting for Nifty 50 constituents. Supports two forecast engines:

| Model | ID | Description |
|-------|-----|-------------|
| **TimesFM 2.5** (default) | `timesfm-2.5` | Google PyTorch zero-shot foundation model |
| **TimesFM-Fin** | `timesfm-fin` | [PFN financial fine-tune](https://tech.preferred.jp/en/blog/timesfm/) on TimesFM 1.0 |

Historical OHLCV is fetched from **Upstox** (primary) with automatic **NSE API fallback**. The React UI lets you pick any Nifty 50 stock, switch **daily / weekly / monthly** intervals, and choose the forecast model — each showing **5 years of candlestick history** plus forecast overlay.

## Architecture

```
React UI (Vite :5173)
    ↓ /api/*
FastAPI backend (:8000)
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

uvicorn app.main:app --reload --port 8000
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

## OI Support Momentum (intraday)

Live ATM support-zone scanner using **rolling Upstox option-chain polls** (3–5 minute windows). See [docs/oi_momentum_scanner.md](docs/oi_momentum_scanner.md).

| Route | Description |
|-------|-------------|
| `/oi-momentum` | UI — REST poll or **Start live OI** (WebSocket); 3–5m rolling window |
| `GET /api/oi-momentum/evaluate` | Evaluate (`source=auto|rest|websocket`) |
| `POST /api/oi-momentum/stream/start` | Upstox WS live OI on ATM zone strikes |

**Changelog (2026-06-30):** WebSocket live OI via Upstox Market Data Feed V3; hybrid with rolling 3m/5m engine.
