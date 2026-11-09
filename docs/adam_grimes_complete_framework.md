# Adam Grimes Complete Framework — Technical Specification

**Source:** Adam Grimes, *The Art and Science of Technical Analysis* (Wiley, 2012), Parts I–IV, plus appendices that this app operationalizes.  
**Purpose:** Production spec for Equity Scan Lab’s Grimes engine (`backend/app/services/labs/grimes/`) and UI (`/grimes-analysis`).  
**Scope:** Daily NSE OHLCV from the local timeline DB. Not investment advice. Edges are statistical tendencies, not certainties.

This document is a **synthesis for implementation**: definitions, tests, formulas, failure modes, and UI mappings. It does not reproduce book prose.

---

## How this maps to the app


| Book domain                                                  | Engine module            | UI                              |
| ------------------------------------------------------------ | ------------------------ | ------------------------------- |
| Market cycle, two forces, swing anatomy                      | `regime.py`, `pivots.py` | Regime bar, HH/HL/LH/LL markers |
| Pullbacks, squeezes, springs/upthrusts, climaxes, absorption | `patterns.py`            | Setup badges, scanner filters   |
| Confirmation (EMA/SMA, Keltner, MACD, MTF)                   | `indicators.py`          | Overlay toggles                 |
| Stops, R-multiples, trailing, time stops, sizing             | `risk.py`                | Risk/reward box, sizing panel   |
| Expectancy, MAE/MFE, Monte Carlo vs random baseline          | `diagnostics.py`         | Diagnostics tab                 |
| Psychology + execution checklists                            | `knowledge.py`           | Knowledge hub / checklist modal |


**Universe:** F&O underlyings with local daily candles plus Nifty 50 (same DB-only pattern as the Elliott Wave lab). **Lookback:** ~520 sessions. **Min bars:** 80.

---

# Part I — Foundation of Technical Analysis

## 1. Random walk vs statistical edge

### Claims the engine is built on

1. Markets are **mostly** hard to predict. Most chart patterns are noise (apophenia).
2. A **trading edge** is a repeatable discrepancy between expected value and a random baseline, after costs and after data-mining penalties.
3. Efficient Market Hypothesis (EMH) in strong form is a straw man for discretionary work: microstructure, inventory, and behavioral clustering create **conditional** (not unconditional) edges.
4. The correct scientific posture is: *does this setup’s forward return distribution beat shuffled / random-entry controls?* If not, do not trade it.

### What is *not* an edge

- A pretty pattern with no hold-out sample.
- An indicator that always “explains” the past (curve-fit).
- Survivorship-biased universes (delisted names missing).
- Selecting only the trades that worked after the fact (selection bias).

### Engine tests (`TradeDiagnosticsEngine`)

- **Expectancy** in R (see Part III).
- **Monte Carlo control:** compare mean N-bar forward return after setup dates vs the same statistic on random dates (`runMonteCarloControl`).
- Report **p-value** as the fraction of randomized trials whose mean ≥ observed mean (one-sided). Treat *p* > 0.10 as “not distinguished from chance” for discretionary use.

### Cognitive bias checklist (UI knowledge hub)

- Confirmation bias: only counting wins that look like the template.
- Recency: last three losers do not invalidate a positive-expectancy process.
- Narrative fallacy: “smart money accumulation” stories without a testable trigger.
- Random reinforcement: intermittent wins on a negative-edge play feel skillful.

---

## 2. Market structure and the two forces

Grimes reduces tape reading to **two opposing forces**:


| Force                 | Tape signature                                               | Typical behavior                   |
| --------------------- | ------------------------------------------------------------ | ---------------------------------- |
| **Imbalance (trend)** | Initiative buying/selling, range expansion, follow-through   | Impulse legs; pullbacks are pauses |
| **Balance (range)**   | Two-sided trade, overlapping bars, mean reversion to VWAP/MA | Springs/upthrusts at edges         |


Liquidity is not a line on a chart; it is **where resting orders cluster**: prior swing highs/lows, round numbers, opening range, session VWAP, and moving averages that many desks share (20 EMA, 50 SMA).

**Bid–ask / absorption (daily proxy):** we cannot see the book on EOD bars. Proxy:

- **Absorption:** relative volume high **and** bar range small **near** a swing or MA (effort without displacement).
- **Initiative:** relative volume high **and** range large **away** from value (displacement).tre

---

## 3. Four market phases (Wyckoff–Grimes synthesis)


| Phase                                 | Structure                                               | Dominant trade                                      |
| ------------------------------------- | ------------------------------------------------------- | --------------------------------------------------- |
| **Accumulation**                      | Range after markdown; springs at lows; supply drying up | Failure tests / springs (mean reversion at support) |
| **Mark-up (trend)**                   | HH + HL; impulse > correction                           | Pullbacks with trend                                |
| **Distribution**                      | Range after markup; upthrusts at highs                  | Failure tests / upthrusts                           |
| **Mark-down**                         | LH + LL                                                 | Pullbacks (bounces) to short                        |
| **Re-accumulation / re-distribution** | Mid-trend ranges                                        | Treat as trading range until polarity resolves      |


**Regime classifier outputs** (app):

- `TREND_BULL` — HH/HL (or price vs 20/50 MA stack) with expanding or persistent impulse.
- `TREND_BEAR` — LH/LL with MA stack down.
- `TRADING_RANGE` — overlapping swings, MA flat, no clean polarity.
- `VOLATILITY_COMPRESSION` — NR7 / inside days / BB inside Keltner.
- `CLIMACTIC_EXHAUSTION` — outlier range + extension from MA + volume spike.

Re-accumulation is **not** a separate enum; it appears as `TRADING_RANGE` or `VOLATILITY_COMPRESSION` **inside** a higher-timeframe bull stack (weekly EMA up). UI shows weekly alignment separately.

---

## 4. Trend definition and anatomy

### Fundamental pattern

Impulse → retracement → impulse. Trends are **sequences of that unit**, not a single line.

### Swing pivot hierarchy

N-bar **fractal** (default N=3): bar *i* is a swing high if its high is strictly the max of highs in `[i-N, i+N]` (and analogously for lows). Successive confirmed swings:


| Sequence                      | Label  |
| ----------------------------- | ------ |
| Swing high > prior swing high | **HH** |
| Swing low > prior swing low   | **HL** |
| Swing high < prior swing high | **LH** |
| Swing low < prior swing low   | **LL** |


**Bull trend (structure):** HH + HL.  
**Bear trend:** LH + LL.  
**Range:** mixed (HH then LL, or LH then HL).

### Impulse vs corrective legs

- **Impulse:** larger range, often higher volume, closes toward the extreme, MACD fast line makes a new local extreme *with* price.
- **Corrective:** overlapping bars, declining volume/range, MACD pulls back without a new extreme.

**Three pushes / three drives:** a late-trend warning (three similar-length with-trend legs). Engine tags climax + successive failed HH/LL rather than a rigid “three magic waves.”

---

# Part II — Market structure and technical setups

## 5. Trend continuation / pullbacks

The **primary with-trend template**. In an uptrend, the pullback is a lower-timeframe downtrend that should **abort** as the higher-timeframe trend reasserts.

### Simple pullback

1. Clear impulse (new HH, momentum expansion).
2. Retrace toward **20 EMA** (shallow) or **50 SMA** (deeper / more mature trend).
3. Range and volume **contract** vs the impulse.
4. Trigger: reclaim of pullback high (stop entry) or hold of dynamic support (limit).

**Healthy vs dying pullback**


| Healthy                               | Failure-prone                                  |
| ------------------------------------- | ---------------------------------------------- |
| Holds above last HL (long)            | Breaks last HL with momentum                   |
| Volume dries up into the low          | Volume expands into the low (selling leftover) |
| First or second retrace after impulse | Late in a three-drive sequence                 |
| MACD pulled back from a new extreme   | MACD divergence into the pullback              |


Engine: `detectTrendPullback()` — proximity to EMA20/SMA50, declining 5-bar volume vs prior 10-bar impulse window, ATR range contraction, regime bull/bear.

### Complex pullback (two-legged ABC)

First retrace fails to resume the trend cleanly; a second counter-trend leg completes the correction (A–B–C). Common late in trends.

Engine: `detectComplexPullback()` — last swings form **H–L–h–L** (bull: second high lower than impulse high; second low may undercut the first) or **L–H–h–H** in bears.

### Shallow vs deep / momentum decay

- **Shallow:** holds 20 EMA; often early, strong trend.
- **Deep:** tags 50 SMA or prior HL; still valid if structure intact.
- **Decay:** successive pullbacks deeper, slower, more overlapping → reduce size or stand aside.

---

## 6. Breakouts and volatility compression

### Compression patterns


| Pattern                  | Rule (daily)                                          |
| ------------------------ | ----------------------------------------------------- |
| **NR7**                  | Current high–low is the smallest of the last 7 ranges |
| **Inside day**           | High < prior high **and** low > prior low             |
| **Inside sequence**      | 2+ consecutive inside days (coiling)                  |
| **BB / Keltner squeeze** | Bollinger(20, 2σ) **inside** Keltner(20, 1.5×ATR)     |


Grimes uses **modified Keltner** (EMA ± k·ATR). Book examples around **2.25 ATR** for fading emotional extremes. This app:

- **Squeeze detection:** k = **1.5** (tighter envelope so BB-inside-KC fires).
- **Climax / fade context:** also flag closes beyond **2.25 ATR** Keltner as emotional extreme (mean-reversion *context*, not a standalone system).

### Breakout validation

A breakout from compression or a range is **not** “close outside.” Prefer:

1. **Range expansion** vs the coil.
2. **Volume expansion** vs the coil (not always present on indices).
3. **Lack of immediate rejection** (no wide-range close back inside the same bar / next bar).
4. **First pullback after a valid breakout** is often the higher-quality continuation entry (breakout traders already trapped on the other side if it holds).

Failed breakout of the coil → see springs/upthrusts.

---

## 7. Support and resistance dynamics


| Type                 | Construction                                    | Use                                      |
| -------------------- | ----------------------------------------------- | ---------------------------------------- |
| **Static swing**     | Confirmed fractal high/low                      | Stops, failure tests, polarity           |
| **Dynamic MA**       | 20 EMA, 50 SMA                                  | Pullback location                        |
| **Hidden liquidity** | Opening gaps, prior day high/low, round numbers | Intraday; daily proxy = swing ± 0.25 ATR |


**Polarity:** broken support often acts as resistance (and vice versa). Engine `sr_zones` lists recent swing prices with `role`: support, resistance, or flipped.

Do **not** expect clean holds. Expect tests, probes, and stop runs.

---

## 8. Mean reversion, failed breakouts, climaxes

### Failure test (spring / upthrust)

Wyckoff language:

- **Spring:** probe **below** range/swing support that **fails to follow through**; close back inside → trapped breakout shorts.
- **Upthrust:** probe **above** resistance that rejects → trapped breakout longs.

Engine: `detectFailedBreakout()` — bar trades through last swing then **closes back** on the inside; optional next-bar confirmation.

### Climactic exhaustion

Wide-range bar, **> ~2.5× ATR**, far extended from the 20 EMA / 50 SMA, often with a volume spike. Mean-reversion **target** is value (EMA / Keltner mid), not a new trend by default.

Engine: `detectClimacticExhaustion()`.

**Parabolic climax (book Ch. 10):** do not fade the first spike blindly; wait for a **failure test** or a close back inside Keltner after the outlier.

### The Anti (book Ch. 6)

A short-term momentum reversal template: a sharp counter-trend thrust that **fails immediately**, then price resumes the prior trend. Related to failed breakouts of a one- or two-bar pattern. Engine tags these under failed breakout + pullback resume rather than a separate fragile classifier.

---

# Part III — Statistical analysis and quantitative edge verification

## 9. Backtesting without self-deception


| Trap           | Mitigation in this lab                                                       |
| -------------- | ---------------------------------------------------------------------------- |
| Curve-fitting  | Fixed parameters (N=3 pivots, 20/50 MA, ATR 14); no walk-forward optimizer   |
| Selection bias | Scan full F&O+Nifty universe, not “names that look good”                     |
| Survivorship   | Local DB is whatever was ingested; document missing names                    |
| Data mining    | Monte Carlo vs random entries; require *p* and sample size                   |
| Look-ahead     | Pivots confirmed only after N bars; setups marked on **close** of signal bar |


**Forward window** for diagnostics: default **10 sessions** (swing) for MC; MAE/MFE path uses the paper-trade hold (default 20 bars or stop/target).

---

## 10. Random baseline testing

`runMonteCarloControl(pattern_indices, ohlcv, n_simulations=1000, horizon=10)`:

1. For each pattern bar index *i*, compute forward return  (C_{i+h} - C_i) / C_i  (long bias) or sign-adjusted by setup direction.
2. Observed mean \mu_{obs}.
3. Repeat *n* times: draw the same count of random indices (valid range), compute mean forward return.
4.  p = \frac{1 + \mu_{rand} \ge \mu_{obs}}{n+1}  (with-trend long). For shorts, invert the inequality on returns.

Also report observed vs random **median** and a simple **t-like** z-score (\mu_{obs}-\mu_{rand}) / \sigma_{rand}.

Price-series **shuffle** (destroy serial correlation) is optional context; default control is **random entry dates** on the **same** series (keeps volatility clustering).

---

## 11. Trade expectancy math


E = (P_{win} \times \bar{R}*{win}) - (P*{loss} \times \bar{R}_{loss})


All PnL is measured in **R**, where  R = |entry - stop| .

Also report:

- Win rate, loss rate  
- Profit factor  = \sum wins / |\sum losses|   
- Average R, stdev R, skew, excess kurtosis  
- Histogram bins: `(-3,-2], (-2,-1], … (3,+∞)`

**Worked example:** 40% wins at +2.0R, 60% losses at −1.0R →  E = 0.4\times2 - 0.6\times1 = +0.20R  per trade.

Fixed-fraction compounding on a **positive** E can still ruin an account if the left tail is fat (see Ch. 9). Size small (1–2%).

---

## 12. Distribution profiling


| Statistic                | Why it matters                                                                                                              |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------- |
| **Skew**                 | Trend-following setups should be **right-skewed** (small losses, occasional large R). Mean-reversion often **left-skewed**. |
| **Kurtosis**             | Fat tails → MAE/MFE analysis and wider structural stops.                                                                    |
| **Drawdown probability** | Even E > 0 systems see long losing streaks; Monte Carlo equity paths (optional) illustrate this.                            |


UI: R-multiple bar chart + MAE vs MFE scatter.

---

# Part IV — Execution, management, psychology

## 13. Entry tactics


| Style                   | Trigger                                | Trade-off                                   |
| ----------------------- | -------------------------------------- | ------------------------------------------- |
| **Confirmation / stop** | Buy stop above trigger-bar high (long) | Worse R, higher win rate                    |
| **Limit on support**    | Bid at EMA / swing / range low         | Better R, more missed moves / knife-catches |


Engine default risk box: **next-session confirmation** — entry = signal bar high (long) or low (short); stop = structural or ATR hybrid (below).

---

## 14. Initial stop-loss models


| Model                    | Long stop                                                                | Notes                |
| ------------------------ | ------------------------------------------------------------------------ | -------------------- |
| **Volatility**           | entry - k \times ATR , k ∈ **[1.5, 2.0]**                                | Default k = **1.8**  |
| **Structural**           | Below last swing low / pattern low (buffer 0.1–0.25 ATR)                 | Invalidates the idea |
| **Hybrid (app default)** | The **closer** of structural and 2.0×ATR, but never tighter than 1.0×ATR | Avoids noise stops   |


---

## 15. Position sizing (fixed fractional)

Risk  f  of equity per idea, **f ∈ [0.01, 0.02]** typical. Grimes: **< 1% conservative**; **~2%** aggressive for a single idea.


\text{shares} = \frac{f \times \text{equity}}{|entry - stop|}


Output: shares, notional, rupee risk, R distance in price.

**Chandelier / ATR parity (portfolio):** equal **dollar risk** per name, not equal share count.

---

## 16. Dynamic trade management

### Scaled exits

Default template: **50% at 1R or 2R**, runner with trail. UI shows 1R / 2R / 3R prices.

### Trailing methods (`evaluateTrailingStop`)


| Method           | Long trail                               |
| ---------------- | ---------------------------------------- |
| `SWING_PIVOT`    | Last confirmed swing low                 |
| `EMA_TRAIL`      | 20 EMA                                   |
| `ATR_CHANDELIER` | \max(high_{entry\to now}) - 3 \times ATR |


### Time stop (`evaluateTimeStop`)

If after **N bars** (default 8) the trade is **< +0.5R**, consider the idea dead (momentum failure). Kill if still negative and structure stalled.

---

## 17. MAE / MFE diagnostics

For a closed (or paper) trade:

- **MAE** = worst adverse excursion in **R** (long: (entry - minlow) / R).
- **MFE** = best favorable excursion in **R** (long: (maxhigh - entry) / R).

**Use:**

- If many winners have MAE > 1R, stops are too tight **or** entries too early.
- If MFE ≫ realized R, targets/trails are leaving too much; or scale-out is too early.
- Scatter: x = MAE, y = MFE; color win/loss.

---

## 18. Trader’s mind and process (operational)

Not modeled as code; surfaced as **checklists**:

- Pre-trade: regime, higher TF, trigger, stop, size, invalidation, “four trades” slot.
- In-trade: do not move stop **closer** for comfort; only for structure/time rules.
- Post-trade: journal MAE/MFE, not P&L story.
- Record-keeping: every setup type tagged so expectancy is **per template**.

**Random reinforcement:** a broken process still pays randomly. Only the **sample** of tagged trades is evidence.

---

# Practical trading templates (Ch. 6) — engine tags


| Template                       | Setup type enum                       | Primary regime   |
| ------------------------------ | ------------------------------------- | ---------------- |
| Failure test (spring/upthrust) | `FAILED_BREAKOUT`                     | Range / reversal |
| Pullback buy/short support     | `TREND_PULLBACK`                      | Trend            |
| LTF breakout of pullback       | `TREND_PULLBACK` + confirmation entry | Trend            |
| Complex pullback               | `COMPLEX_PULLBACK`                    | Mature trend     |
| Breakout from base / squeeze   | `VOL_SQUEEZE`                         | Compression      |
| First PB after breakout        | `TREND_PULLBACK` after squeeze        | Trend from range |
| Climax fade *context*          | `CLIMACTIC_EXHAUSTION`                | Exhaustion       |
| Absorption at S/R              | `ABSORPTION`                          | Range edge       |


**The four trades (Ch. 2):**

1. **Trend continuation** — pullbacks.
2. **Trend termination** — failure tests / climax.
3. **Range mean reversion** — springs at support, upthrusts at resistance.
4. **Range breakout** — compression → expansion.

Scanner **setup group** filters: `Trend Continuation`, `Mean Reversion`, `Squeeze Breakout`.

---

# Confirmation tools (Ch. 7)

## Moving averages — “still center”

- **20 EMA:** short-term value; first pullback magnet.  
- **50 SMA:** deeper value; trend filter when 20 is on the correct side of 50.

## Channels

Keltner (EMA ± k·ATR) as **emotional extreme**. Fading closes **outside** the 2.25 ATR channel is a **mean-reversion hypothesis**, not a breakout system.

## MACD (momentum, not oscillator rules)

- New **MACD fast-line extreme** should precede the best pullbacks.  
- **Divergence** (price new high, MACD lower) degrades pullback quality.  
- Climax bars **distort** MACD; do not mechanically buy a new MACD low in a selling climax.

App computes MACD(12,26,9) on daily close for overlay quality score, not as a crossover robot.

## Multiple time frames

Weekly **20 EMA slope** (sign of weekly close vs prior weekly EMA) vs daily regime:

- **Aligned:** daily bull + weekly EMA rising.  
- **Counter:** daily pullback long while weekly EMA falling → lower quality.

---

# Indicator formulas (implementation)

Let  H,L,C,V  be daily series. Missing/zero volume → treat volume features as unknown (do not fire absorption/climax volume legs).

**ATR(14)** — Wilder-style optional; app uses rolling mean of true range (same as scanner module) for consistency.

**EMA(n)** — standard ewm span=n.  
**SMA(n)** — rolling mean.  
**Bollinger** — SMA20 ± 2·stdev(20).  
**Keltner** — EMA20 ± 1.5·ATR(20) for squeeze; ± 2.25·ATR(20) for extreme flags.  
**MACD** — EMA12 − EMA26; signal EMA9 of MACD; hist = MACD − signal.  
**NR7** —  H_t - L_t = \min_{i=0..6}(H_{t-i}-L_{t-i}) .  
**Volume z** — (V − mean50) / stdev50.  
**Quality score (0–100):** MTF align 20 + regime match 25 + volume/range confirmation 15 + MA proximity 15 + not-climax (continuation) 10 + squeeze-ready 15, clipped.

---

# Risk calculator API (normative)

```
calculatePositionSize(accountSize, riskPercentage, entryPrice, stopLossPrice)
  → { shares, notional, risk_amount, r_distance, valid }

calculateRMultiples(entry, stopLoss, targets=[1,2,3], side="long")
  → { r: 1.0, prices: {1:…, 2:…, 3:…} }

evaluateTrailingStop(ohlcv, side, method, entry_index)
  → { price, method }

evaluateTimeStop(entryBarIndex, currentBarIndex, maxHoldBars, currentR, minR=0.5)
  → { kill: bool, reason }
```

---

# UI specification

1. **Regime bar** — badge for selected ticker; weekly alignment chip; overlay toggles (pivots, EMA/SMA, setups, R-box).
2. **Chart** — Lightweight Charts candles + markers + price lines.
3. **Scanner** — virtualized table: ticker, regime, setup, quality, vol rank (ATR%ile).
4. **Diagnostics** — MAE/MFE scatter, R histogram, expectancy stats, Monte Carlo p.
5. **Knowledge hub** — collapsible cards + execution checklist modal.

---

# Additional features integrated (beyond the four parts)

These fit the same book logic and the existing lab:

1. **ATR percentile (volatility rank)** — 100-day percentile of ATR/close for scanner ranking.
2. **Weekly EMA alignment** — explicit MTF flag.
3. **Paper-trade path** — every chart builds hypothetical trades from historical setups for MAE/MFE even without a broker blotter.
4. **Setup group taxonomy** — maps templates to the four trades for screening.
5. **Hybrid stop** — structural × ATR as used by discretionary desks in the book’s trade-management chapters.
6. **Polarity zones** — last swings labeled flipped vs intact.
7. **Keltner 2.25 extreme** — fade *context* alongside 1.5 squeeze.
8. **MACD impulse quality** — pullback score penalty on divergence.
9. **Time-stop overlay** — optional in risk panel.
10. **Nifty included in universe** — index regime as benchmark (Wyckoff: index often leads stocks).

---

# Disclaimer

This is a research overlay on historical NSE bars. Patterns can fail. Monte Carlo p-values on one path are not a live Sharpe. Size small; the book’s core risk chapter still applies.