# Elliott Wave & Gann — Practical Guide

This note explains **Elliott Wave / Neo Wave** and **Gann** methods as used by discretionary traders (including frameworks often referenced by Nifty options educators). Both are **manual / interpretive** frameworks: they are not single formulas you plug OHLC into and get one “correct” answer.

They appear high in `@kyalashish`’s tweet toolkit ranking because he frames forecasts around **wave structure + time**, often combined with price levels, Volume Profile, and options context (CAS, OI, IV).

---

## Part 1 — Elliott Wave / Neo Wave

### What it is

**Elliott Wave Theory** (Ralph Nelson Elliott) says markets move in repeating **crowd-psychology patterns**:

| Phase | Structure | Idea |
|-------|-----------|------|
| Impulse (with trend) | **5 waves**: 1-2-3-4-5 | Progress in the main direction |
| Corrective (against trend) | **3 waves**: A-B-C | Digestion / pullback |

**Neo Wave** (Glenn Neely) is a stricter, more rule-heavy refinement of Elliott. It emphasizes:

- Clearer rules for what qualifies as a valid wave
- Time relationships between waves (not only price)
- More precise labeling before acting

In practice, many Indian market educators say “Elliott / Neo Wave” when they mean: *label the structure, wait for a completion zone, then trade the next leg with confirmation*.

### Core rules of thumb (classic Elliott)

1. **Wave 2** does not retrace beyond the start of Wave 1.
2. **Wave 3** is often the strongest / longest (never the shortest of 1, 3, 5 in many textbooks).
3. **Wave 4** does not overlap Wave 1 price territory in a standard impulse (guidelines vary by degree).
4. Corrective patterns can be zigzags, flats, triangles, complexes — labeling is the hard part.
5. Waves exist on **multiple degrees** (intraday → daily → weekly). A “Wave 3 up” on daily can contain smaller 1–5 swings inside.

### How to use it (workflow)

1. **Choose the degree** you care about (e.g. swing on daily Nifty, or hourly for expiry week).
2. **Mark swings** — clear highs/lows, not every noise bar.
3. **Propose 1–2 counts** (bullish count vs alternate bearish count). Never cling to one count.
4. **Identify the active wave** — e.g. “Wave iii of larger Wave 3” or “Wave b of a correction.”
5. **Define invalidation** — a price that kills the count (e.g. break of Wave 1 start).
6. **Wait for confirmation** — break of a micro structure, reclaim of a level, or time turn — don’t enter only because the label looks pretty.
7. **Target zones** — Wave 3 / Wave 5 extensions (often Fib 1.618 / 2.618 of a prior wave), and corrective Fibs (0.382 / 0.5 / 0.618).

**Neo Wave add-on:** also check **time symmetry** (e.g. Wave b taking ~1.618× Wave a in time) before calling a reversal.

### Who uses Elliott Wave

| Audience | Why |
|----------|-----|
| Swing / positional traders | Map multi-day / multi-week legs |
| Index & options traders (Nifty / Bank Nifty) | Structure + expiry timing |
| Forex & crypto discretionary traders | Highly trend / sentiment driven markets |
| Educators & newsletter writers | Narrative + levels in one framework |
| Fund / prop discretionary desks (selectively) | Scenario planning, not usually as a sole systematic signal |

**Rarely used alone by quants** as a black-box alpha source — counts are subjective and hard to backtest cleanly.

### When to use it

Use Elliott / Neo Wave when:

- The market has made a **clear impulsive move** and you need to judge: extension vs correction
- You are planning **swing targets** and want a story for “why here”
- You want an **invalidation level** tied to structure (not just a random stop)
- Multiple tools **agree** (time cycle, support/resistance, Volume Profile POC, OI)

Avoid relying on it when:

- Price is **chopping** in a tight range with no clear swings
- You keep **re-labeling** every few bars to stay “right”
- You need a **fully automated** rule for scanners without human review

### Situations where it is most useful

1. **After a sharp selloff** — deciding if it was Wave a/b/c complete vs early Wave 3 down  
2. **Mid-trend pullbacks** — trading Wave 2 / Wave 4 with the larger trend  
3. **Breakout legs** — identifying Wave 3 acceleration (momentum + structure)  
4. **Index weekly planning** — “blueprint” for the coming week (common in Nifty commentary)  
5. **Confluence setups** — Wave completion + Fib + time cycle + key horizontal level  

### Limitations (why our app marks it “manual”)

- Two experienced analysts can label the **same chart differently**
- No unique closed-form calculation from OHLC
- Wrong degree = wrong trade even if the “rules” look satisfied
- Best treated as a **scenario framework**, confirmed by price action and risk limits

### Practical checklist

- [ ] Primary count written down  
- [ ] Alternate count written down  
- [ ] Invalidation price set  
- [ ] Confirmation trigger defined (close above / below X)  
- [ ] Target zone + R:R acceptable  
- [ ] At least one independent confluence (level / volume / time / indicator)  

---

## Part 2 — Gann

### What it is

**W.D. Gann** methods treat markets as geometric and cyclical: **price and time are related**. Common tools traders mean by “Gann” today:

| Tool | Idea |
|------|------|
| **Gann angles / fans** | Lines from a pivot at fixed slopes (e.g. 1×1 — one price unit per one time unit) |
| **Square of 9 / Gann square** | Number spiral used to project support/resistance |
| **Price–time squares** | Ranges that “square” a move in time |
| **Percentage retracements** | 50%, 12.5%–87.5% style geometric levels |
| **Anniversary / time cycles** | Important dates / bars from prior highs–lows |

Modern practitioners often use **Gann levels** as **key resistance/support** derived from a chosen swing, not the full mystical toolkit.

### How to use it (workflow)

1. **Pick a significant pivot** (major high or low you believe still matters).
2. **Scale the chart** consistently (Gann angles depend on how price vs time is scaled — misuse here is common).
3. Draw **angles or project levels** from that pivot (or compute Square-of-9 style prices around a round number / prior extreme).
4. Treat Gann lines as **reaction zones**, not magic magnets.
5. Trade **reactions + confirmation**: rejection wick, reclaim, failed break, volume/OI cue.
6. Drop the level if price **accepts beyond** it with time (close through and hold).

**Common practical pattern (index stocks):**  
“Break above Gann resistance + bounce from Volume Profile POC → watch for continuation.”

### Who uses Gann

| Audience | Why |
|----------|-----|
| Discretionary technical traders | Geometric S/R overlays |
| Commodity & futures traders (historically strong Gann culture) | Time–price squares on seasonal markets |
| Index & stock swing traders | Alternate resistance map vs plain horizontals |
| Astro / cycle-oriented traders | Overlap with time-cycle thinking |
| Educators packaging “levels + story” | Memorable key prices |

Less common in pure systematic shops unless converted into **fixed geometric level generators** with strict rules.

### When to use it

Use Gann when:

- You have a **clear major pivot** and need projected resistance/support above/below  
- Horizontal S/R alone is ambiguous and you want **geometric alternatives**  
- You combine with **Volume Profile / OI** to see if that Gann price is also a liquidity magnet  
- Trading **swings** where traders defend “round” or geometrically derived levels  

Avoid as primary tool when:

- Pivot selection is arbitrary (every swing becomes a new fan → clutter)  
- Chart scaling is inconsistent (angles become meaningless)  
- You need explainable, regulation-friendly **model risk** documentation (hard to justify “Square of 9” alone)

### Situations where it is most useful

1. **Breakout stocks** — price approaching a Gann resistance after a base  
2. **Reversal attempts** — sharp reaction exactly at a projected Gann level  
3. **Range expansion** — projecting the next geometric target after a measured move  
4. **Confluence days** — Gann level overlaps Fib 0.618 / VWAP / prior day high / OI wall  
5. **Time–price coincidence** — price hits a Gann level as a known time cycle turns (Elliott/Neo time users often pair these)

### Limitations (why our app marks it “manual”)

- Requires a **chosen origin** and often **chart scaling** assumptions  
- Many “Gann” implementations differ (angles vs Square of 9 vs percentages)  
- Easy to **curve-fit** after the fact  
- Not a drop-in indicator series like RSI or Bollinger  

### Practical checklist

- [ ] One primary pivot selected (and why)  
- [ ] Levels/angles drawn with consistent scale  
- [ ] Reaction plan at level (accept vs reject)  
- [ ] Invalidation if accepted beyond  
- [ ] Confluence noted (volume node, OI, Fib, trend tool)  

---

## Elliott vs Gann — quick compare

| | Elliott / Neo Wave | Gann |
|--|--------------------|------|
| Main question | *What structure are we in?* | *Where are geometric price–time levels?* |
| Output | Wave labels + invalidation + targets | Angles / squares / projected prices |
| Strength | Narrative + risk framework for swings | Alternate S/R map, time–price thinking |
| Weakness | Subjective counts | Subjective pivots + scaling |
| Best with | Fib, time cycles, price action | Volume Profile, OI, breakouts |
| Automation | Hard | Hard (unless rule-frozen level engine) |

---

## How they fit this project

On **Indicator Analysis** (`/indicator-analysis`):

- Both show as **manual / reference** because the backend only has candle data.
- They remain in the catalog because they are **high-frequency concepts** in the studied tweet set.
- Computable companions that often appear *with* them in that style of analysis:
  - Support / Resistance, Breakout, Price Action  
  - Time Cycle (55-day proxy)  
  - Volume Profile (POC)  
  - Bollinger / Keltner / KST / Supertrend  
  - Fibonacci (swing-based approximation)

**Suggested use in this desk:**  
Use the live indicators for **state** (trend, stretch, POC, momentum). Use Elliott/Gann offline on the chart for **scenario + key levels**, then only act when price confirms.

---

## Further reading (classic)

- R.N. Elliott — *The Wave Principle* / Frost & Prechter — *Elliott Wave Principle*  
- Glenn Neely — *Mastering Elliott Wave* (Neo Wave rules)  
- W.D. Gann — *How to Make Profits in Commodities* (historical; interpret critically)  
- Modern practice: treat both as **risk frameworks + level generators**, not prophecy

---

## Disclaimer

Educational only. Wave counts and Gann geometry are interpretive. Markets can invalidate structure quickly — always define risk before entry. Not investment advice.
