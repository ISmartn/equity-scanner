# Grimes Chart — Plain-Language Guide

This guide explains **everything you see on the Grimes TA chart and scanner**, in everyday language. It is based on Adam Grimes’ market-structure framework (see `adam_grimes_complete_framework.md` for the full technical spec).

**Important:** These are *statistical tendencies*, not guarantees. Always use a stop and size positions so one loss cannot hurt your account.

---

## Quick read: the two big ideas

1. **Trend (imbalance)** — Price makes clear higher highs + higher lows (uptrend) or lower highs + lower lows (downtrend). The play is usually *with* the trend: buy pullbacks in uptrends, sell bounces in downtrends.

2. **Range (balance)** — Price chops sideways. The play is usually *at the edges*: failed breakouts (springs/upthrusts), mean reversion back toward the middle.

The **regime badge** on the chart tells you which world you are in.

---

## Top-left badge (stock info)

| What you see | What it means | What to expect |
|--------------|---------------|----------------|
| **Ticker + price** | Symbol and last close on the chart date | Click any row in the scanner to load this chart |
| **Company name** | Full NSE name (equities only) | — |
| **Bull trend / Bear trend / …** | Current market *phase* for this stock | Match your trade type to the phase (see regimes below) |
| **as of DATE** | Last candle in local DB | Not live — refresh data separately if you need today’s bar |

---

## Regimes (market phase)

| Regime | Plain English | When you see it | What to expect next | When the idea fails |
|--------|---------------|-----------------|---------------------|---------------------|
| **Bull trend** | Uptrend: peaks and pullbacks are climbing | HH + HL swings, price often above rising 20 EMA | Pullbacks toward 20 EMA or 50 SMA that *hold* and resume up | Break below last higher low with wide red bars |
| **Bear trend** | Downtrend: peaks and bounces are falling | LH + LL swings, price often below falling MAs | Bounces toward 20 EMA / 50 SMA that fail and roll over | Break above last lower high with strong follow-through |
| **Trading range** | Sideways — buyers and sellers balanced | Mixed HH/LL, flat MAs, overlapping candles | Tests of range top/bottom; springs and upthrusts | Clean breakout with range expansion *and* follow-through |
| **Volatility squeeze** | Market is “coiling” — quiet before a move | NR7, inside days, tight ranges | A **directional** breakout (not random — use trend + MA stack) | Breakout that immediately closes back inside the coil |
| **Climactic exhaustion** | One huge emotional bar — often late in a move | Bar much wider than normal, far from 20 EMA, high volume | Mean reversion toward the average (20 EMA), *not* a new trend by default | Another huge bar in the same direction (real breakout) |

---

## Swing pivot markers (● circles)

These label **confirmed swing highs and lows** (local peaks and troughs). They tell you whether structure is bullish, bearish, or messy.

| Label | Name | What it means | What to expect next |
|-------|------|---------------|---------------------|
| **HH** | Higher High | New peak above the previous peak | Uptrend intact — look for pullbacks to buy |
| **HL** | Higher Low | Pullback low *above* the prior low | Trend resume if price holds this level |
| **LH** | Lower High | Rally peak *below* the prior peak | Downtrend intact — look for bounces to sell |
| **LL** | Lower Low | New low below the prior low | Downside continuation if this level breaks again |

**Simple rule:** HH + HL = bullish structure. LH + LL = bearish structure. Mixed labels = range or transition — be pickier.

---

## Setup badges on the chart

Setups are **actionable patterns** the engine detected on a specific bar. Green ▲ = long bias, red ▼ = short bias, ◆ circle = context (direction from regime).

### PB — Trend pullback

| | |
|---|---|
| **What it is** | A pause in a trend: price retraces toward the 20 EMA (shallow) or 50 SMA (deeper) after an impulse leg |
| **When it appears** | After a clear HH (uptrend) or LL (downtrend), with smaller candles and often lower volume |
| **What to expect next** | Trend resumes — price reclaims the pullback high (long) or breaks the pullback low (short) |
| **When to worry** | Close *through* the last HL/LL with expanding range — the trend may be ending |

### ABC — Complex pullback

| | |
|---|---|
| **What it is** | A *two-legged* correction (A down, B up, C down) before trend continues |
| **When it appears** | Later in a mature trend; first pullback did not cleanly resume |
| **What to expect next** | After the C-leg holds, a breakout through the B-leg extreme often starts the next impulse |
| **When to worry** | The C-leg becomes a new trend against you (LH/LL sequence for a long) — use smaller size |

### NR7 — Volatility squeeze

| | |
|---|---|
| **What it is** | Today’s range is the **smallest of the last 7 days** — volatility is compressed |
| **When it appears** | Tight, overlapping candles; optional BB-inside-Keltner on chart |
| **What to expect next** | A **breakout** with wider range — direction from MA stack and regime, not the coil itself |
| **When to worry** | Breakout bar closes back inside the coil — “failed breakout”; fade or wait |

### FT — Failure test (spring / upthrust)

| | |
|---|---|
| **What it is** | Price **probes** past support or resistance but **closes back inside** — a trap for breakout traders |
| **When it appears** | At range edges or after a false break; spring = probe below support, upthrust = probe above resistance |
| **What to expect next** | Reversal toward the middle of the range or back toward the 20 EMA |
| **When to worry** | Next bar continues through the probe — the break was real, not a trap |

### CLX — Climactic exhaustion

| | |
|---|---|
| **What it is** | An unusually large bar (> ~2.5× normal daily range), often with a volume spike, stretched from the average |
| **When it appears** | Late in a strong move — “blow-off” or panic |
| **What to expect next** | Cooling off — drift back toward 20 EMA / 50 SMA (mean reversion) |
| **When to worry** | Another huge bar the next day in the same direction — you may be fading a real breakout |

### ABS — Absorption

| | |
|---|---|
| **What it is** | Heavy volume but a **small** candle at support/resistance — lots of trading, little progress |
| **When it appears** | Near a swing level or MA; often pairs with spring/upthrust or pullback resume |
| **What to expect next** | Indecision resolving — wait for the *next* bar to show direction |
| **When to worry** | Next bar range-expands through the zone — absorption failed |

---

## Lines on the chart

| Line | Color | What it means | How to use it |
|------|-------|---------------|---------------|
| **20 EMA** | Cyan | Short-term “fair value” / where short trends pull back | First support in uptrends, first resistance in downtrends |
| **50 SMA** | Amber | Deeper trend value — mature trends retrace here | Stronger pullback zone; break often means trend weakening |
| **Keltner ±** | Gray dotted | Average ± 1.5× daily range envelope | Optional: price outside = stretched; climax context |
| **Entry** | Cyan solid | Suggested trigger for the active setup | Enter on confirmation, not blindly at the line |
| **Stop** | Pink dashed | Where the trade idea is **wrong** | Exit if hit — do not widen without a new plan |
| **1R / 2R / 3R** | Green dotted | Profit targets at 1×, 2×, 3× your initial risk | Scale out partially; trail the rest |

**R (risk unit):** If entry is ₹100 and stop is ₹95, 1R = ₹5. A 2R target is ₹110.

---

## Overlay toggles (above the chart)

| Toggle | Shows |
|--------|--------|
| **Swings** | HH / HL / LH / LL pivot circles |
| **20/50 MA** | Moving averages |
| **Keltner** | Volatility envelope |
| **Setups** | PB, ABC, NR7, FT, CLX, ABS badges |
| **R-box** | Entry, stop, and R targets for the latest setup |

Turn off clutter if the chart feels busy; keep **Setups** and **R-box** on when planning a trade.

---

## Scanner columns (left table)

| Column | Meaning | How to read it |
|--------|---------|----------------|
| **Symbol** | NSE ticker | ★ = F&O eligible · IDX = Nifty index |
| **Regime** | Current phase (short label) | Filter by regime to match your strategy |
| **Setup** | Latest detected pattern name | Empty = no fresh setup on the last bar |
| **Q** | Quality score 0–100 | Higher = cleaner structure + alignment; ≥70 is “high quality” filter |
| **Vol%** | ATR percentile (100-day) | High = more volatile than usual; low = quiet (squeeze context) |

---

## Capital & risk box (above chart)

When **R-box** is on and a setup exists, you see:

- **Side** — long or short bias  
- **Entry / Stop** — levels from the engine  
- **Shares · risk ₹** — position size from your **Capital (₹)** and **Risk / trade (%)** inputs  

Example: ₹10,00,000 capital, 1% risk → ₹10,000 max loss on this trade. Shares = risk amount ÷ (entry − stop).

This is a **planning aid**, not a broker order.

---

## Practical workflow

1. **Scan** — Filter regime + setup type you trade (e.g. Bull + Continuation).  
2. **Open chart** — Check structure (HH/HL), regime badge, and latest setup marker.  
3. **Read the guide** — Tap **ℹ** on the chart or open the **Guide** tab for “what to expect next.”  
4. **Plan** — Note entry, stop, 1R/2R from R-box; size from capital settings.  
5. **Execute elsewhere** — Place orders in your broker with your own confirmation.

---

## Also see

- **Knowledge tab** — Deeper rules, failure modes, and execution checklists per setup  
- **MAE / MFE tab** — How far winning/losing trades typically move (after you have history)  
- **Full spec** — `docs/adam_grimes_complete_framework.md`
