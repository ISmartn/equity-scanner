# Order flow in the lab

The Order Flow page (`/order-flow`) is the standalone board mounted inside the lab. The page is the same UI. The data comes from this app’s Upstox token and from `/api/order-flow`, not from the standalone server.

The live scan uses the same idea of a futures build-up, on a smaller feed and with only two hard rules. That path is at the bottom of this note.

## What the board shows

For each F&O underlying the board reads two things together:

- The nearest live option chain: strike, call or put, price, open interest, volume, and the book.
- The near-month future: price change against the change in open interest.

A move is a build-up only when both the price and the open interest clear a noise floor. Inside the floor the reading is neutral.

| Price | Open interest | Reading |
|---|---|---|
| Up | Up | Long build-up. New longs. |
| Down | Up | Short build-up. New shorts. |
| Up | Down | Short covering. Old shorts leaving. |
| Down | Down | Long unwinding. Old longs leaving. |

The floor depends on the window. On the day and on the live read it is 0.5% of price and 2% of open interest. Shorter windows use their own floors in `frontend/src/order-flow/lib/buildUp.ts`. A strike that had no open interest yesterday is treated as new: any fresh open interest counts, and the price sign alone picks long or short build-up.

The page can look at 5 minutes, 15 minutes, 1 hour, or the day. The day is measured from the previous session’s close. The shorter windows need a stored market file close enough to the start of the window. A 7-minute gap is not a 5-minute window.

## How a refresh works

On startup the collector in `backend/app/services/order_flow/collector.py` serves the last file already on disk, then builds a new one.

One build asks Upstox for every underlying’s live option expiries, keeps the nearest expiry that is still live, and downloads that put/call chain. Eight underlyings run at once. Each chain becomes one series in a market file. A contract with neither open interest nor volume is left out.

During the cash session the file is rebuilt every 4 minutes. One build is about 208 option-chain calls, and Upstox’s standard allowance is 2,000 calls per 30 minutes, so a one-minute rebuild would use the allowance in about ten minutes. Outside the session the file rebuilds once an hour. Calls share a limit of 10 per second.

Each session file is written under `backend/data/order_flow/<provider>/<session>/`. `latest.json` is what `/api/order-flow/market` returns. Minute files (`HHMM.json`) are what the 15-minute and 1-hour windows read. Older session directories are deleted when a new session is stored.

The universe is `backend/app/services/order_flow/underlyings.json`. A name is included when it has a symbol and a lot size.

## Futures

`GET /api/order-flow/futures/{symbol}` returns the current session only. The provider looks up the front-month future already stored in `futures_oi_daily`, then loads that contract’s 1-minute candles (with open interest) and the previous day’s close and open interest.

Only one futures month is stored per name, so the board cannot add later months together. On the standalone board, open interest is the sum of every listed month, which cancels a roll from this month into the next. Here a roll still looks like falling open interest in the front month. Index futures for Nifty and Bank Nifty are not in that table, so those indices show the spot move until a future is stored for them.

A futures answer is reused for 60 seconds during the session.

## API

| Method | Path | What it returns |
|---|---|---|
| `GET` | `/api/order-flow/status` | Provider, clock, and the last build |
| `GET` | `/api/order-flow/market` | The latest market file. 503 while the first file is still building |
| `GET` | `/api/order-flow/market/{date}/{HHMM}` | One stored minute, for the 15-minute and 1-hour windows |
| `GET` | `/api/order-flow/futures/{symbol}` | The front-month future for the current session |

The page needs `UPSTOX_ACCESS_TOKEN`. Without it the collector records a provider error and the market route stays on the last file, or returns 503 if there is none.

## What the live scan does with the same reading

The live scan does not call `/api/order-flow`. It classifies the front-month future already on its own websocket, in `backend/app/services/live_scan/ranker.py`.

The comparison is the future’s last price against its previous close, and its open interest against the previous open interest. The floors are the daily ones: 0.5% price and 2% open interest. Indexes have no future on this feed, so they get no reading.

On a session call the reading is a label, except for two cases:

- A buy stands aside when the future shows short build-up.
- A sell stands aside when the future shows long build-up.

Short covering, long unwinding, and a neutral reading are written on the reason and do not block the call. In the two days before expiry the near-month change is labelled “rollover week” and is not used as a block, because that drop is usually a roll.

When a plan is first saved, `live_call_journal.fut_quadrant` and `fut_oi_change_pct` keep that moment’s reading. Later ticks do not replace it. The Record table shows the snapshot in the Futures column.

This is thinner than the board. The scan has the front month only, it does not sum later months, and it does not read the option chain. Five live sessions were not enough to show that the extra readings should block a call, which is why they stay labels.
