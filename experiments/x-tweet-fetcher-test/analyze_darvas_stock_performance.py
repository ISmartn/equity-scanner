#!/usr/bin/env python3
"""Analyze @darvasboxtrader stock mentions vs local daily_candles (no network)."""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
TWEETS_PATH = ROOT / "experiments/x-tweet-fetcher-test/out/darvasboxtrader_own_500.json"
DB = ROOT / "data/trading.db"
OUT_DIR = ROOT / "experiments/x-tweet-fetcher-test/out"
OUT_JSON = OUT_DIR / "darvasboxtrader_stock_performance.json"
OUT_MD = OUT_DIR / "darvasboxtrader_stock_performance_report.md"
IST = ZoneInfo("Asia/Kolkata")

STOP = {
    "DARVAS", "DARR", "SMALLCAP", "SUGAR", "AI", "FNO", "PROCESS", "SPACEX", "SPCX", "DXY", "IT",
    "GENZ", "PATIENCE", "SUBSCRIPTION", "UNIVERSE", "JOCKEY", "KOSPI", "HSI", "COMMODITIES",
    "DOLLAR", "SALARY", "EXPENSE", "INFLATION", "POLITICIAN", "NIMO", "GROWW", "CRUDE",
    "ETHANOL", "RESULT", "RESULTS", "CHART", "CHARTS", "BUY", "SELL", "LONG", "SHORT",
    "BULL", "BEAR", "MARKET", "STOCK", "STOCKS", "NIFTY", "BANKNIFTY", "SENSEX", "INDIA",
    "USA", "US", "CEO", "IPO", "SME", "MIDCAP", "LARGECAP", "INTRADAY", "SWING", "POSITION",
    "TARGET", "SL", "STOPLOSS", "BREAKOUT", "BREAKDOWN", "SUPPORT", "RESISTANCE", "VOLUME",
    "RSI", "EMA", "SMA", "ATH", "ATL", "CMP", "LTP", "PE", "CE", "FII", "DII", "GDP", "RBI",
    "SEBI", "NSE", "BSE", "MCX", "GOLD", "SILVER", "OIL", "COPPER", "ZINC", "ALUMINIUM",
    "WAR", "PEACE", "LIFE", "LOVE", "FAMILY", "TRAINING", "INFLUENCER", "INFLUENCERS",
    "AND", "THE", "FOR", "YOU", "THIS", "THAT", "WITH", "FROM", "YOUR", "HAVE", "WILL",
    "JUST", "LIKE", "WHAT", "WHEN", "WHERE", "WHICH", "THERE", "HERE", "THEY", "THEM",
    "INTO", "OVER", "UNDER", "AFTER", "BEFORE", "ABOUT", "AGAIN", "ALSO", "ONLY", "MORE",
    "MOST", "SOME", "MANY", "MUCH", "VERY", "EVEN", "STILL", "THEN", "THAN", "BEEN", "BEING",
    "WERE", "WAS", "ARE", "IS", "AM", "DO", "DID", "DOES", "DONT", "CANT", "WONT", "NOT",
    "YES", "NO", "OK", "OKAY", "ALL", "ANY", "EACH", "EVERY", "OWN", "OUR", "OUT", "UP", "DOWN",
    "ON", "OFF", "IN", "AT", "TO", "OF", "OR", "AS", "BY", "IF", "SO", "WE", "ME", "MY", "HE",
    "SHE", "HIS", "HER", "ITS", "WHO", "WHY", "HOW", "CAN", "MAY", "MUST", "SHOULD", "COULD",
    "WOULD", "SHALL", "MIGHT", "NEED", "WANT", "MAKE", "MADE", "TAKE", "GET", "GOT", "GO",
    "GOING", "COME", "CAME", "SEE", "SAW", "LOOK", "LOOKS", "KNOW", "THINK", "SAY", "SAID",
    "PUT", "SET", "LET", "KEEP", "GIVE", "GAVE", "USE", "USED", "USING", "NEW", "OLD", "BIG",
    "TOP", "LOW", "HIGH", "OPEN", "CLOSE", "FIRE", "FIRED", "ONFIRE", "NEXT", "LAST", "FIRST",
    "WEEK", "MONTH", "YEAR", "DAY", "TODAY", "TOMORROW", "YESTERDAY", "NOW", "TIME", "MONEY",
    "PAISA", "BHAI", "MAIN", "MERA", "MERI", "HUM", "HO", "HAI", "HAIN", "NA", "SE", "KO",
    "KA", "KI", "KE", "PAR", "PE", "MEIN", "ETC", "VIA", "PER", "VS",
}

ALIASES = {
    "HARIOM": "HARIOMPIPE",
    "HARIOMPIPE": "HARIOMPIPE",
    "SHAKTIPUMP": "SHAKTIPUMP",
    "TARIL": "TARIL",
    "MARINE": "MARINE",
    "EXICOM": "EXICOM",
    "IFCI": "IFCI",
    "SUPRAJIT": "SUPRAJIT",
    "PROTEAN": "PROTEAN",
    "LXCHEM": "LXCHEM",
    "NALCO": "NALCO",
    "RATNAVEER": "RATNAVEER",
    "MANALIPETRO": "MANALIPETRO",
    "CONFIPET": "CONFIPET",
    "WOCKPHARMA": "WOCKPHARMA",
    "PATANJALI": "PATANJALI",
    "STALLION": "STALLION",
    "GODREJIND": "GODREJIND",
    "TI": "TI",
}

HASHTAG_RE = re.compile(r"#([A-Za-z][A-Za-z0-9]{1,24})")
CASHTAG_RE = re.compile(r"\$([A-Za-z][A-Za-z0-9.&_-]{1,24})")
BARE_RE = re.compile(r"\b([A-Z]{3,15})\b")


def tweet_date_ist(tweet: dict):
    ts = tweet.get("created_timestamp")
    if ts:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(IST).date()
    raw = tweet.get("created_at") or ""
    dt = datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y")
    return dt.astimezone(IST).date()


def main() -> int:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    tickers = {r[0].upper() for r in conn.execute("SELECT ticker FROM security_profiles")}
    resolved_aliases = {}
    for k, v in ALIASES.items():
        if v in tickers:
            resolved_aliases[k] = v
        elif k in tickers:
            resolved_aliases[k] = k

    def extract_tickers(text: str) -> set[str]:
        found: set[str] = set()
        for m in HASHTAG_RE.findall(text or ""):
            key = m.upper()
            if key in STOP:
                continue
            if key in resolved_aliases:
                found.add(resolved_aliases[key])
            elif key in tickers:
                found.add(key)
        for m in CASHTAG_RE.findall(text or ""):
            key = m.upper().replace(".", "").replace("-", "")
            if key in tickers:
                found.add(key)
            elif key in resolved_aliases:
                found.add(resolved_aliases[key])
        for m in BARE_RE.findall(text or ""):
            key = m.upper()
            if key in STOP or len(key) < 3:
                continue
            if key in tickers:
                found.add(key)
            elif key in resolved_aliases:
                found.add(resolved_aliases[key])
        return found

    tweets = json.loads(TWEETS_PATH.read_text())["tweets"]
    mentions = []
    ticker_mention_counts: Counter[str] = Counter()
    for t in tweets:
        tickers_found = extract_tickers(t.get("text") or "")
        if not tickers_found:
            continue
        d = tweet_date_ist(t)
        for tk in sorted(tickers_found):
            mentions.append(
                {
                    "tweet_id": t["id"],
                    "url": t["url"],
                    "text": t["text"],
                    "created_at": t["created_at"],
                    "mention_date": d.isoformat(),
                    "ticker": tk,
                    "likes": t.get("likes"),
                    "views": t.get("views"),
                }
            )
            ticker_mention_counts[tk] += 1

    candle_cache: dict[str, list] = {}

    def load_candles(ticker: str):
        if ticker in candle_cache:
            return candle_cache[ticker]
        rows = conn.execute(
            """
            SELECT c.trade_date, c.open_price AS open, c.high_price AS high,
                   c.low_price AS low, c.close_price AS close
            FROM daily_candles c
            JOIN security_profiles p ON p.instrument_token = c.instrument_token
            WHERE p.ticker = ?
            ORDER BY c.trade_date
            """,
            (ticker,),
        ).fetchall()
        candle_cache[ticker] = rows
        return rows

    def analyze_window(candles, mention_date: str, days: int):
        if not candles:
            return None
        after = [r for r in candles if r["trade_date"] >= mention_date]
        if not after:
            return {"status": "no_future_data", "entry_date": None}
        entry = after[0]
        entry_date = entry["trade_date"]
        entry_close = float(entry["close"]) if entry["close"] is not None else None
        entry_open = float(entry["open"]) if entry["open"] is not None else entry_close
        # Baseline = session open on first trade day on/after the tweet (IST).
        # Close baseline makes max-high% almost always >= 0 by construction.
        basing = entry_open if entry_open else entry_close
        if not basing:
            return {"status": "bad_entry_price", "entry_date": entry_date}

        window_end = (datetime.fromisoformat(entry_date).date() + timedelta(days=days)).isoformat()
        win = [r for r in candles if entry_date <= r["trade_date"] <= window_end]
        if not win:
            return {"status": "empty_window", "entry_date": entry_date, "entry_open": basing}

        highs = [float(r["high"]) for r in win if r["high"] is not None]
        lows = [float(r["low"]) for r in win if r["low"] is not None]
        closes = [float(r["close"]) for r in win if r["close"] is not None]
        max_high = max(highs) if highs else None
        min_low = min(lows) if lows else None
        end_close = closes[-1] if closes else None
        high_date = None
        if max_high is not None:
            for r in win:
                if r["high"] is not None and float(r["high"]) == max_high:
                    high_date = r["trade_date"]
                    break

        db_max = candles[-1]["trade_date"]
        complete = db_max >= window_end
        high_pct = ((max_high / basing) - 1.0) * 100.0 if max_high else None
        end_pct = ((end_close / basing) - 1.0) * 100.0 if end_close else None
        drawdown_pct = ((min_low / basing) - 1.0) * 100.0 if min_low else None

        return {
            "status": "ok" if complete else "partial",
            "entry_date": entry_date,
            "entry_open": round(basing, 4),
            "entry_close": round(entry_close, 4) if entry_close is not None else None,
            "window_end": window_end,
            "sessions": len(win),
            "max_high": round(max_high, 4) if max_high is not None else None,
            "max_high_date": high_date,
            "max_high_pct": round(high_pct, 2) if high_pct is not None else None,
            "min_low": round(min_low, 4) if min_low is not None else None,
            "min_low_pct": round(drawdown_pct, 2) if drawdown_pct is not None else None,
            "end_close": round(end_close, 4) if end_close is not None else None,
            "end_close_pct": round(end_pct, 2) if end_pct is not None else None,
            "complete": complete,
            "db_max_date": db_max,
        }

    results = []
    skipped_no_data = 0
    for m in mentions:
        candles = load_candles(m["ticker"])
        if not candles:
            skipped_no_data += 1
            results.append({**m, "has_candles": False, "w1": None, "w2": None})
            continue
        w1 = analyze_window(candles, m["mention_date"], 7)
        w2 = analyze_window(candles, m["mention_date"], 14)
        results.append({**m, "has_candles": True, "w1": w1, "w2": w2})

    def okish(w):
        return w and w.get("status") in ("ok", "partial") and w.get("max_high_pct") is not None

    events_w1 = [r for r in results if okish(r.get("w1"))]
    events_w2 = [r for r in results if okish(r.get("w2"))]
    complete_w1 = [r for r in events_w1 if r["w1"].get("complete")]
    complete_w2 = [r for r in events_w2 if r["w2"].get("complete")]

    def summarize(events, key):
        pcts = [r[key]["max_high_pct"] for r in events]
        end_pcts = [r[key]["end_close_pct"] for r in events if r[key].get("end_close_pct") is not None]
        wins = sum(1 for p in pcts if p > 0)
        big = sum(1 for p in pcts if p >= 10)
        end_wins = sum(1 for p in end_pcts if p > 0)
        return {
            "n": len(pcts),
            "avg_max_high_pct": round(sum(pcts) / len(pcts), 2) if pcts else None,
            "median_max_high_pct": round(sorted(pcts)[len(pcts) // 2], 2) if pcts else None,
            "avg_end_close_pct": round(sum(end_pcts) / len(end_pcts), 2) if end_pcts else None,
            "pct_positive_mfe": round(100 * wins / len(pcts), 1) if pcts else None,
            "pct_mfe_ge_10": round(100 * big / len(pcts), 1) if pcts else None,
            "pct_end_positive": round(100 * end_wins / len(end_pcts), 1) if end_pcts else None,
            "best": max(events, key=lambda r: r[key]["max_high_pct"]) if events else None,
            "worst": min(events, key=lambda r: r[key]["max_high_pct"]) if events else None,
        }

    sum_w1 = summarize(complete_w1, "w1")
    sum_w2 = summarize(complete_w2, "w2")
    sum_w1_all = summarize(events_w1, "w1")
    sum_w2_all = summarize(events_w2, "w2")

    by_ticker: dict[str, list] = defaultdict(list)
    for r in complete_w1:
        by_ticker[r["ticker"]].append(r)

    ticker_stats = []
    for tk, rows in by_ticker.items():
        mfe1 = [x["w1"]["max_high_pct"] for x in rows]
        rows2 = [x for x in complete_w2 if x["ticker"] == tk]
        mfe2 = [x["w2"]["max_high_pct"] for x in rows2]
        ticker_stats.append(
            {
                "ticker": tk,
                "mentions_complete_1w": len(rows),
                "avg_1w_max_high_pct": round(sum(mfe1) / len(mfe1), 2),
                "best_1w_max_high_pct": round(max(mfe1), 2),
                "mentions_complete_2w": len(rows2),
                "avg_2w_max_high_pct": round(sum(mfe2) / len(mfe2), 2) if mfe2 else None,
                "best_2w_max_high_pct": round(max(mfe2), 2) if mfe2 else None,
                "last_mention": max(x["mention_date"] for x in rows),
            }
        )
    ticker_stats.sort(key=lambda x: (-(x["avg_1w_max_high_pct"] or -999), -x["mentions_complete_1w"]))

    top_w1 = sorted(complete_w1, key=lambda r: r["w1"]["max_high_pct"], reverse=True)[:25]
    top_w2 = sorted(complete_w2, key=lambda r: r["w2"]["max_high_pct"], reverse=True)[:25]
    bottom_w1 = sorted(complete_w1, key=lambda r: r["w1"]["max_high_pct"])[:10]
    db_range = conn.execute("SELECT MIN(trade_date), MAX(trade_date) FROM daily_candles").fetchone()

    payload = {
        "source_tweets": str(TWEETS_PATH),
        "tweet_count": len(tweets),
        "mention_events": len(mentions),
        "unique_tickers_mentioned": len(ticker_mention_counts),
        "events_with_candles": sum(1 for r in results if r["has_candles"]),
        "events_missing_candles": skipped_no_data,
        "db_candle_range": {"min": db_range[0], "max": db_range[1]},
        "methodology": {
            "entry": "First trading session on or after tweet date (IST)",
            "baseline": "That session open",
            "1w": "Max high over sessions from entry through entry+7 calendar days",
            "2w": "Max high over sessions from entry through entry+14 calendar days",
            "max_high_pct": "(window_max_high / entry_open - 1) * 100",
            "reposts_excluded": True,
            "data_source": "local data/trading.db daily_candles only (no refetch)",
        },
        "top_mentioned_tickers": ticker_mention_counts.most_common(30),
        "summary_complete_1w": {k: v for k, v in sum_w1.items() if k not in ("best", "worst")},
        "summary_complete_2w": {k: v for k, v in sum_w2.items() if k not in ("best", "worst")},
        "summary_incl_partial_1w": {k: v for k, v in sum_w1_all.items() if k not in ("best", "worst")},
        "summary_incl_partial_2w": {k: v for k, v in sum_w2_all.items() if k not in ("best", "worst")},
        "best_1w": {
            "ticker": sum_w1["best"]["ticker"],
            "mention_date": sum_w1["best"]["mention_date"],
            "max_high_pct": sum_w1["best"]["w1"]["max_high_pct"],
            "url": sum_w1["best"]["url"],
            "text": sum_w1["best"]["text"][:240],
        }
        if sum_w1.get("best")
        else None,
        "best_2w": {
            "ticker": sum_w2["best"]["ticker"],
            "mention_date": sum_w2["best"]["mention_date"],
            "max_high_pct": sum_w2["best"]["w2"]["max_high_pct"],
            "url": sum_w2["best"]["url"],
            "text": sum_w2["best"]["text"][:240],
        }
        if sum_w2.get("best")
        else None,
        "ticker_stats": ticker_stats[:40],
        "top_events_1w": [
            {
                "ticker": r["ticker"],
                "mention_date": r["mention_date"],
                "entry_date": r["w1"]["entry_date"],
                "entry_open": r["w1"]["entry_open"],
                "entry_close": r["w1"]["entry_close"],
                "max_high": r["w1"]["max_high"],
                "max_high_date": r["w1"]["max_high_date"],
                "max_high_pct": r["w1"]["max_high_pct"],
                "end_close_pct": r["w1"]["end_close_pct"],
                "min_low_pct": r["w1"]["min_low_pct"],
                "url": r["url"],
                "text": (r["text"] or "")[:180],
            }
            for r in top_w1
        ],
        "top_events_2w": [
            {
                "ticker": r["ticker"],
                "mention_date": r["mention_date"],
                "entry_date": r["w2"]["entry_date"],
                "entry_open": r["w2"]["entry_open"],
                "entry_close": r["w2"]["entry_close"],
                "max_high": r["w2"]["max_high"],
                "max_high_date": r["w2"]["max_high_date"],
                "max_high_pct": r["w2"]["max_high_pct"],
                "end_close_pct": r["w2"]["end_close_pct"],
                "min_low_pct": r["w2"]["min_low_pct"],
                "url": r["url"],
                "text": (r["text"] or "")[:180],
            }
            for r in top_w2
        ],
        "worst_events_1w": [
            {
                "ticker": r["ticker"],
                "mention_date": r["mention_date"],
                "max_high_pct": r["w1"]["max_high_pct"],
                "end_close_pct": r["w1"]["end_close_pct"],
                "min_low_pct": r["w1"]["min_low_pct"],
                "url": r["url"],
            }
            for r in bottom_w1
        ],
        "all_events": [
            {
                "ticker": r["ticker"],
                "mention_date": r["mention_date"],
                "url": r["url"],
                "has_candles": r["has_candles"],
                "w1": r["w1"],
                "w2": r["w2"],
                "text": (r["text"] or "")[:220],
            }
            for r in results
        ],
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "# @darvasboxtrader stock mention performance",
        "",
        f"Source: `{TWEETS_PATH.name}` ({len(tweets)} own tweets, no reposts).",
        f"Price data: local `data/trading.db` only ({db_range[0]} → {db_range[1]}). **No new market data fetched.**",
        "",
        "## Methodology",
        "- Extract NSE tickers from hashtags / cashtags / ALLCAPS tokens matched to `security_profiles`.",
        "- Entry = first trading day on/after tweet date (IST); baseline = that day’s **open**.",
        "- **1 week** / **2 week** = max **high** from entry through entry+7 / +14 calendar days.",
        "- `max_high_pct` = (window max high / entry open − 1) × 100. Complete = DB has candles through window end.",
        "",
        "## Coverage",
        f"- Mention events (tweet×ticker): **{len(mentions)}** across **{len(ticker_mention_counts)}** tickers",
        f"- With local candles: **{sum(1 for r in results if r['has_candles'])}**; missing candles: **{skipped_no_data}**",
        f"- Complete 1w windows: **{sum_w1['n']}**; complete 2w: **{sum_w2['n']}**",
        "",
        "## Headline stats (complete windows only)",
        "",
        "| Window | N | Avg max-high % | Median max-high % | Avg end-close % | % MFE>0 | % MFE≥10% | % end>0 |",
        "|--------|---|----------------|-------------------|-----------------|---------|-----------|---------|",
        f"| 1 week | {sum_w1['n']} | {sum_w1['avg_max_high_pct']} | {sum_w1['median_max_high_pct']} | {sum_w1['avg_end_close_pct']} | {sum_w1['pct_positive_mfe']} | {sum_w1['pct_mfe_ge_10']} | {sum_w1['pct_end_positive']} |",
        f"| 2 week | {sum_w2['n']} | {sum_w2['avg_max_high_pct']} | {sum_w2['median_max_high_pct']} | {sum_w2['avg_end_close_pct']} | {sum_w2['pct_positive_mfe']} | {sum_w2['pct_mfe_ge_10']} | {sum_w2['pct_end_positive']} |",
        "",
    ]
    if payload["best_1w"]:
        b = payload["best_1w"]
        lines.append(
            f"**Best 1w MFE:** {b['ticker']} on {b['mention_date']} → **+{b['max_high_pct']}%** high ([tweet]({b['url']}))"
        )
    if payload["best_2w"]:
        b = payload["best_2w"]
        lines.append(
            f"**Best 2w MFE:** {b['ticker']} on {b['mention_date']} → **+{b['max_high_pct']}%** high ([tweet]({b['url']}))"
        )
    lines += [
        "",
        "## Most mentioned tickers",
        "",
        "| Ticker | Mentions |",
        "|--------|----------|",
    ]
    for tk, n in ticker_mention_counts.most_common(20):
        lines.append(f"| {tk} | {n} |")
    lines += [
        "",
        "## Top 1-week max-high events",
        "",
        "| Ticker | Mention | Entry open | Max high | Max high % | End close % | Tweet |",
        "|--------|---------|------------|----------|------------|-------------|-------|",
    ]
    for r in payload["top_events_1w"][:15]:
        lines.append(
            f"| {r['ticker']} | {r['mention_date']} | {r['entry_open']} | {r['max_high']} | **{r['max_high_pct']}%** | {r['end_close_pct']}% | [link]({r['url']}) |"
        )
    lines += [
        "",
        "## Top 2-week max-high events",
        "",
        "| Ticker | Mention | Entry open | Max high | Max high % | End close % | Tweet |",
        "|--------|---------|------------|----------|------------|-------------|-------|",
    ]
    for r in payload["top_events_2w"][:15]:
        lines.append(
            f"| {r['ticker']} | {r['mention_date']} | {r['entry_open']} | {r['max_high']} | **{r['max_high_pct']}%** | {r['end_close_pct']}% | [link]({r['url']}) |"
        )
    lines += [
        "",
        "## Per-ticker averages (complete 1w, sorted by avg MFE)",
        "",
        "| Ticker | #1w | Avg 1w max-high % | Best 1w % | #2w | Avg 2w max-high % | Best 2w % |",
        "|--------|-----|-------------------|-----------|-----|-------------------|-----------|",
    ]
    for s in ticker_stats[:20]:
        lines.append(
            f"| {s['ticker']} | {s['mentions_complete_1w']} | {s['avg_1w_max_high_pct']} | {s['best_1w_max_high_pct']} | {s['mentions_complete_2w']} | {s['avg_2w_max_high_pct']} | {s['best_2w_max_high_pct']} |"
        )
    lines += [
        "",
        "## Notes / caveats",
        "- Mentions are not always bullish calls (sold, hoping, sector chatter).",
        "- Recent tweets after DB max date have partial/incomplete windows.",
        "- Hashtag nicknames may miss some names; US tickers ($AAPL) won’t resolve in NSE DB.",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print("complete_w1", payload["summary_complete_1w"])
    print("complete_w2", payload["summary_complete_2w"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
