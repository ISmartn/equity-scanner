# x-tweet-fetcher smoke test

Isolated sandbox for [ythx-101/x-tweet-fetcher](https://github.com/ythx-101/x-tweet-fetcher) (v3.x).

## Setup

```bash
cd experiments/x-tweet-fetcher-test
# needs Python >= 3.10 (system python3 is often 3.8)
/usr/bin/python3.11 -m venv .venv
.venv/bin/pip install ./src
```

## Run

```bash
.venv/bin/python smoke_test.py
```

Results land in `out/`:

- `single_tweet_fxtwitter.json` — FxTwitter single tweet (no API key)
- `report.json` — pass/fail summary

## Fetch a user's recent tweets (URLs)

FxTwitter API v2 can list profile posts (no Nitter):

```bash
.venv/bin/python fetch_user_tweets.py kyalashish --count 10
# optional: also hit each URL with xtf --url
.venv/bin/python fetch_user_tweets.py kyalashish --count 10 --fetch
```

Listing alone already returns `url`, `text`, `likes`, etc. Use `--fetch` only if you need the exact `xtf --url` JSON shape.
