# News Impact — RedboxGlobal Telegram

Research tool that ingests headlines from **[@indiaredboxglobal](https://t.me/indiaredboxglobal)**, links **company names** to NSE tickers, measures **T+0…T+5** price reactions on local daily candles, and optionally asks **Gemini** for extraction + a forward outlook grounded in similar past events.

This is decision support, not an auto-trading signal.

## What is implemented

| Area | Details |
|------|---------|
| Telegram ingest | Telethon user session; backfill + incremental sync for `@indiaredboxglobal` |
| Storage | SQLite tables: `news_channels`, `telegram_messages`, `news_events`, `news_reactions` |
| Company linking | Normalize + RapidFuzz against `security_profiles.company_name`; Gemini extract when `GEMINI_API_KEY` is set |
| Event study | Maps post time (IST) → session `event_date`; stores absolute and Nifty-relative returns for horizons `t_m2`…`t5` |
| Gemini | Extract (companies, sentiment, themes, summary); on-demand outlook using similar historical reactions |
| API | `/api/news/*` — sync, list/detail events, ticker impact, outlook, manual override |
| UI | **News Impact** tab (`/news-impact`) — event list, chart with news markers, reaction table, outlook panel |
| CLI | `npm run news:login`, `news:backfill`, `news:sync`, `news:reactions` |

## Setup

1. Create Telegram API credentials at [my.telegram.org](https://my.telegram.org) → `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`.
2. Subscribe to [@indiaredboxglobal](https://t.me/indiaredboxglobal) with the same phone account.
3. Optional: set `GEMINI_API_KEY` (Google AI Studio).
4. Install backend deps and login once:

```bash
cd backend && .venv/bin/pip install -r requirements.txt
npm run news:login
npm run news:backfill
```

Env keys (see `.env.example`):

```env
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_SESSION_PATH=data/telegram_news.session
TELEGRAM_CHANNELS=@indiaredboxglobal
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.0-flash
```

Do not commit the `.session` file.

## Pipeline

```
Telegram @indiaredboxglobal
  → telegram_messages
  → Gemini extract (optional) + name linker
  → news_events (skip if no equity company)
  → event_study vs daily_candles (+ Nifty when available)
  → news_reactions
  → UI / outlook
```

## API

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/news/sync` | Incremental pull + process |
| `GET` | `/api/news/events` | Filter by ticker, sentiment, dates |
| `GET` | `/api/news/events/{id}` | Message, reactions, extract, outlook |
| `GET` | `/api/news/ticker/{ticker}/impact` | Aggregates + markers |
| `POST` | `/api/news/events/{id}/outlook` | Gemini forward outlook |
| `PATCH` | `/api/news/events/{id}` | Manual ticker / dismiss |
| `GET` | `/api/news/stats` | Counts |

## UI

Open **News Impact** in the app nav. Sync pulls new posts; select an event to see chart markers, T+N table, and Gemini outlook.

## Live pool + catch-up

| Control | Behavior |
|---------|----------|
| **Sync news** (UI) / `POST /api/news/sync` | Incremental pull from `last_message_id` |
| **Live on/off** (UI) / `POST /api/news/live/start\|stop` | In-process Telethon listener (catch-up then NewMessage) |
| `npm run news:listen` | Same live listener as a standalone CLI process |

**Monitors:** Gold, Silver, Crude Oil — keyword tags on stored posts (`NEWS_MONITOR_TOPICS`). Filter via News Impact monitor chips / `GET /api/news/messages?topic=GOLD`.

**Are all news stored in DB?**  
Yes — once ingested, every channel post is in `telegram_messages`. Company links → `news_events`; reactions → `news_reactions`.

## Company news sidebar (UI)

Right-rail **Company news** on Forecast / Timeline / Scanner:

- Prefers linked events from DB for the selected ticker; falls back to mock for styling
- News Impact → **All recent posts** shows every stored Telegram message (not ticker-filtered)

## Limits

- Daily OHLC only (no intraday reaction windows).
- Company-name matching can miss or collide — use PATCH / manual override.
- High channel volume: Gemini is batched/skipped for empty or non-equity posts.
- Outlook is explanatory, conditioned on past sample size — not a price guarantee.
- Live listener is a **separate long-running process** (`news:listen`), not inside the Vite UI.
