# Setup watchlist (before the breakout)

The momentum scanner reports a breakout after the close of the day it happened.
The setup watchlist works the other way round. Each evening it lists stocks
that are still inside a base. At 9:08 the next morning it reads the opening
auction, during the session the live feed alerts when a listed stock reaches
its pivot, and all day it reads NSE filings as they are published.

## Read this first: what the real data says

Everything below was run on NSE data for every listed stock, 17 February 2025
to 18 November 2026 (prices loaded from December 2023, the first 14 months
used as history). Trades are a buy-stop at the pivot, the stop at the base low, and
0.25% round-trip costs.

**Taking every setup mechanically lost money.**

| Daily list, 12,652 setups | |
|---|---|
| Crossed the pivot | 64.1% |
| Crossed and closed above it | 30.6% |
| Of those that crossed, closed back under the same day | 52.3% |
| Entering at the pivot against buying that day's close | +0.01% (no advantage) |

| Exit rule | Trades | Average | Middle trade | Made money | Account, 10 positions |
|---|---|---|---|---|---|
| Sell after 5 sessions | 7,917 | −0.14% | −0.49% | 45.4% | −9.8% |
| Sell after 10 sessions | 7,788 | −0.14% | −0.86% | 44.7% | −13.6% |
| Sell at twice the risk, or after 10 | 7,793 | −0.15% | −0.83% | 44.9% | −2.6% |
| Hold until a close under the 10-day average | 7,829 | −0.16% | −1.97% | 32.9% | −16.8% |
| Hold until a close under the 20-day average | 7,725 | −0.12% | −2.83% | 31.5% | −32.0% |

The weekly list did worse: 4,467 setups, −0.63% to −0.72% a trade under every exit rule.

**Three things tilted the odds, none of them into a clear profit.**

- *Market health.* Trades entered after a "healthy" evening averaged +0.15%
  (3,867 trades). After a "mixed" one −0.55%, after a "weak" one −0.34%.
- *The score.* A plain fit of the 18 readings did not rank setups on months it
  had not seen. Most readings flipped direction between periods, including
  base tightness, volume dry-up and relative strength. Keeping only readings
  that agreed across two periods did better: on unseen sessions (May to
  November 2026) the top fifth by score averaged +0.51% a trade against −0.01%
  for the rest. That gap of 0.52% has a likely range of 0.03% to 1.10%, and two
  other ways of splitting the data gave ranges that include zero. Treat it as
  a lead, not a result.
- *What survived.* Nearness to the 52-week high, an industry group whose
  stocks are making new highs, and a healthy market. These are the starting
  weights the tool ships with.

**Reading filings fast is not an edge on its own.** A year of filings
(47,661 price-moving ones, November 2025 to November 2026), measured against
stocks of similar liquidity:

| Kind | Cases | Day of the news | Of which at the open | Next 5 sessions | Beat similar stocks |
|---|---|---|---|---|---|
| Results | 10,000 | −0.23% | +0.09% | −0.92% | 42% |
| Order win | 1,504 | +1.24% | +0.92% | −0.58% | 44% |
| Stake change | 4,326 | +0.08% | +0.02% | +0.10% | 51% |
| Acquisition or merger | 3,251 | +0.25% | +0.21% | −0.09% | 49% |
| Fund raising or payout | 2,825 | +0.20% | +0.27% | −0.61% | 46% |
| Credit rating | 2,400 | −0.01% | −0.02% | +0.17% | 53% |
| Management change | 1,597 | −0.16% | +0.04% | −0.80% | 44% |
| Regulatory or legal | 2,466 | −0.18% | −0.09% | −0.58% | 48% |
| Board decision | 4,232 | −0.02% | +0.17% | −0.51% | 46% |
| Business update | 7,848 | +0.30% | +0.24% | −0.39% | 47% |

An order win lifts the stock 1.24% on the day, but three quarters of that is
in the opening price, and over the next five sessions the stock gives back
more than the rest. "Next 5 sessions" starts from the first price a reader
could trade at. This table does not separate large filings from small ones;
that needs the size reader with an AI key, which has not been run on history.

What this does and does not show: one period, one market, fixed rules, no
discretion. It does not say breakouts cannot be traded. It says this list,
taken whole, is not a strategy, and that the filters above are where to look.

## How it works

1. **Evening lists.** `npm run setups:build` reads the daily candles and keeps
   two lists.
   - *Daily:* above the 50-day average, within 6% under the 20-day high (the
     pivot), a 10-day range under 12%, not up more than 25% in 20 sessions,
     trading ₹5 Cr a day. Stop: the 10-day low.
   - *Weekly:* a 50-day average that is rising, within 10% under a ten-week
     high set at least two weeks ago, the last three weekly closes within 4%.
     Stop: the three-week low.
2. **Carried day to day.** An entry stays until the high crosses the pivot
   (`triggered`), the price loses the stop (`failed`), or it drifts out of the
   base for more than 3 sessions (`expired`). A missed evening is replayed.
3. **Market health.** The share of liquid stocks above their 50-day average,
   with new 20-day highs and lows. Green at 60% or more, or above 50% and
   rising over 10 sessions. Red under 40%, or under 50% and falling fast.
4. **Score.** 0–100, where 50 is an average setup. It estimates how the trade
   turns out if the pivot is crossed, not whether it will be crossed. Distance
   to the pivot is shown separately.
5. **9:08 pre-open.** NSE's opening auction fixes each stock's opening price
   about seven minutes before trading. Watchlist stocks set to open above the
   pivot, just under it, or under the stop are listed and sent as one message.
6. **Live.** Starting the live scan loads both lists. Each stock is placed
   every second: waiting, near (within 2%), testing, breaking out on volume
   (over the pivot at 1.2× the normal volume pace), over on light volume,
   gapped, extended, or failed.
7. **Alerts.** One per stock, list and state per session, with notes: under
   surveillance, in the F&O ban, a results or ex-date within 3 days, a large
   one-sided buy in the last 10 days.
8. **Filings.** NSE announcements are read every minute from 07:00 to
   midnight, routine paperwork is dropped, and the rest is sorted into ten
   kinds. Each is then read for its size.

The entry the list implies is a buy order above the pivot with the stop at the
base low. A stock on the list has not broken out and may never do so.

## The 18 readings

Distance to the pivot · range tightness against its own history · shrinking
ATR · volume dry-up · up-day against down-day volume · relative strength
against the market, and whether it is at a high · tightness of closes · run-up
over 20 sessions · higher lows · distance from the 52-week high · the group's
strength against the market · futures OI building while price is flat ·
delivery share and its trend · industry-group heat · market breadth and its
change.

*Industry-group heat* is the share of a stock's NSE industry that closed at a
new 20-day high in the last five sessions, minus the same share for the whole
market. Industries come from NSE's Total Market list (about 750 stocks in 22
groups); other stocks fall back to the profile's sector.

## Commands

| Command | What it does |
|---------|--------------|
| `npm run setups:data -- --days 500` | Load history: delivery, corporate actions, industries |
| `npm run setups:data -- --days 500 --candles --index` | Also add daily candles and Nifty closes where the database has none |
| `npm run setups:build` | Top up NSE data and bring both lists up to the latest candle date |
| `npm run setups:build -- --rebuild --from-date 2026-01-01` | Clear the lists and replay history |
| `npm run setups:report` | Results by exit rule, market state and score (`-- --list weekly`) |
| `npm run setups:fit` | Derive the score's weights and test them on unseen sessions |
| `npm run setups:filings-history -- --days 250` | Load a year of filings and measure what each kind did to prices |

**Each evening:** `npm run timeline:daily`, then `npm run setups:build`. The
build skips a session until at least half the stocks have that day's bar, and
never processes a session that is still trading.

**Starting without Upstox.** `npm run timeline:sync-profiles`, then
`npm run setups:data -- --days 760 --candles --index`, gives every NSE stock
three years of prices, delivery and Nifty closes in about half an hour.

## Telegram alerts

Create a bot with @BotFather, send it any message, and read your chat id from
`https://api.telegram.org/bot<token>/getUpdates`. Then set in `.env`:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALERT_CHAT_ID=...
```

Restart the backend and use **Send test message** on the Alerts tab. Without
these, alerts are still listed in the app.

## Filings

| Setting | Effect |
|---|---|
| `SETUP_FILINGS_POLL=0` | Turns the NSE reader off |
| `SETUP_FILINGS_SCOPE=all` | Alerts for every stock, not only watchlist stocks. Filings read as small are skipped |
| `SETUP_FILINGS_SIZE=0` | Stops the tool downloading filing documents |
| `GEMINI_API_KEY=...` | A model reads each filing: the amount, results growth, direction and a one-line headline |

Without a Gemini key, plain rules pick out the largest rupee amount stated
beside words like "order" or "consideration", for orders, deals and fund
raising only. With stored fundamentals the amount is shown as a share of the
last four quarters' revenue. That assumes the stored figures are in ₹ crore,
which has not been checked; a share outside 0.01% to 1,000% is dropped as a
unit mismatch.

Filing text comes from third parties. It is passed to the model as material to
analyse, the answer is kept only as a fixed set of typed fields, and nothing
the model returns is acted on beyond being shown and sent in an alert.

## Fitting the score

`npm run setups:fit` plays out the trade for every stock-day whose pivot was
crossed the next session, fits on the earlier sessions, and reports on the
latest 30%, which the fit never sees. A reading keeps a weight only if it
pointed the same way in both halves of the fitting period. The weights are
saved to `data/early_setup_weights.json` only when the top fifth by score beat
the rest on the unseen sessions with the whole 90% range above zero.
Otherwise the starting weights stay in use.

The starting weights were set the same way on all of the NSE data described
above, so they have not been tested on anything later, and the "by score"
table in Results flatters them.

## Prices and corporate actions

NSE's price files are raw: on the day a 1:1 bonus takes effect the price
halves. The watchlist reads candles through two corrections. Splits and
bonuses from NSE's corporate-actions list are applied where the candles show
the jump, so already-adjusted data is left alone. Any remaining open more than
30% under or 45% over the previous close is treated as a break and closed the
same way. On the test data 271 of 310 listed actions applied and 59 further
breaks, mostly demergers, were closed. An entry stored before a split is
rescaled when the list is next updated.

## Limits

- Only stocks on the live feed get live states: the F&O list plus the most
  liquid cash names. Watchlist stocks take the spare slots first. The pre-open
  reading and filings cover every stock.
- The NSE endpoints for filings, the auction, surveillance and corporate
  actions are unofficial and can refuse or change. Each fails on its own and
  is retried. BSE is not read; it refused scripted requests.
- Large-deal history cannot be loaded (NSE's history endpoint did not answer), so large
  buys are a badge and an alert note, not a score input. About three quarters
  of each day's list is one client buying and selling the same stock; those
  rows are dropped.
- NSE's insider-trading endpoint returned nothing when tried. Those disclosures
  are picked up as filings of the "stake change" kind.
- The pre-open scan was checked against one real auction (18 November 2026:
  the auction price equalled the opening price for all 11 stocks flagged). It
  has not been run live at 9:08.
- Volume pace in the first minutes of the session is noisy.
- The results use today's list of stocks. Delisted names are missing.

## Code

| Path | Contents |
|------|----------|
| `backend/app/services/early_setup/features.py` | Base tests for both lists and the per-stock readings |
| `backend/app/services/early_setup/breadth.py` | Market health and industry-group heat |
| `backend/app/services/early_setup/candles.py` | Split adjustment, break healing, benchmarks |
| `backend/app/services/early_setup/watchlist.py` | Daily state machine for both lists, dataset builder |
| `backend/app/services/early_setup/trades.py` | Exit rules and the account view |
| `backend/app/services/early_setup/model.py` | Score, fitting, held-out evaluation |
| `backend/app/services/early_setup/report.py` | Results |
| `backend/app/services/early_setup/live.py` | Live states and alerts |
| `backend/app/services/early_setup/preopen.py` | The 9:08 auction reading |
| `backend/app/services/early_setup/filings.py` | NSE filings reader, kinds, alerts, history, typical moves |
| `backend/app/services/early_setup/sizing.py` | Reading a filing for its size |
| `backend/app/services/early_setup/nse.py` | Fetching and parsing NSE's public data |
| `backend/app/services/early_setup/market_data.py` | Daily top-up and history load |
| `backend/app/services/early_setup/repo.py` | Storage |
| `backend/app/routes/early_setup.py` | `/api/early-setup/*` |
| `frontend/src/pages/EarlySetupPage.tsx` | `/setups` page |
