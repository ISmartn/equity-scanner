from __future__ import annotations

import json
import logging
import re
from typing import Any

import aiohttp

from .config import gemini_api_key, gemini_model

logger = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.I)


def gemini_enabled() -> bool:
    return bool(gemini_api_key())


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    fence = _JSON_FENCE.search(raw)
    if fence:
        raw = fence.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("No JSON object in Gemini response")
    return json.loads(raw[start : end + 1])


async def gemini_json(prompt: str, *, system: str | None = None) -> dict[str, Any]:
    api_key = gemini_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    model = gemini_model()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    parts = []
    if system:
        parts.append({"text": system})
    parts.append({"text": prompt})
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=90)) as resp:
            payload = await resp.json(content_type=None)
            if resp.status >= 400:
                raise RuntimeError(f"Gemini HTTP {resp.status}: {payload}")

    try:
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected Gemini response: {payload}") from exc
    return _extract_json_object(text)


EXTRACT_SYSTEM = (
    "You extract Indian equity news entities from RedboxGlobal Telegram headlines. "
    "Return JSON only. Prefer official company names as written in Indian markets. "
    "Ignore pure macro/index posts with no company. Sentiment is for the named companies."
)


async def extract_news_entities(text: str) -> dict[str, Any]:
    prompt = f"""Analyze this market headline/post and return JSON with keys:
companies: array of {{"name": string, "ticker_hint": string|null}}
sentiment: one of bullish|bearish|neutral|unknown (overall for equity impact)
themes: array of short tags (e.g. earnings, order_win, regulatory, stake_sale)
summary: one sentence
equity_relevant: boolean

Post:
\"\"\"{text}\"\"\"
"""
    data = await gemini_json(prompt, system=EXTRACT_SYSTEM)
    companies = data.get("companies") or []
    if not isinstance(companies, list):
        companies = []
    cleaned = []
    for c in companies:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        hint = c.get("ticker_hint")
        cleaned.append(
            {
                "name": name,
                "ticker_hint": str(hint).strip().upper() if hint else None,
            }
        )
    sentiment = str(data.get("sentiment") or "unknown").lower()
    if sentiment not in {"bullish", "bearish", "neutral", "unknown"}:
        sentiment = "unknown"
    themes = data.get("themes") or []
    if not isinstance(themes, list):
        themes = []
    return {
        "companies": cleaned,
        "sentiment": sentiment,
        "themes": [str(t).strip() for t in themes if str(t).strip()][:12],
        "summary": str(data.get("summary") or "").strip() or None,
        "equity_relevant": bool(data.get("equity_relevant", bool(cleaned))),
    }


SENTIMENT_LABELS = (
    "Good",
    "Decent",
    "Fair",
    "Passable",
    "Average",
    "Mediocre",
    "Bad",
)

SENTIMENT_SYSTEM = (
    "You are a financial and corporate sentiment analyzer. "
    "Classify the following company news into exactly one of these labels based on its impact "
    'on the company: [Good, Decent, Fair, Passable, Average, Mediocre, Bad]. '
    'Return only a raw JSON object matching this structure: '
    '{ "sentiment": "<label>", "confidence": 0.00 }.'
)


def _heuristic_sentiment(text: str) -> dict[str, Any]:
    """Offline fallback when GEMINI_API_KEY is missing."""
    low = (text or "").lower()
    bad_kw = ("loss", "probe", "fraud", "penalty", "ban", "default", "crash", "scandal", "sebi")
    good_kw = ("record profit", "beats", "surge", "wins", "upgrade", "breakthrough", "all-time high")
    mediocre_kw = ("miss", "cuts guidance", "layoff", "delay", "weak", "slump")
    decent_kw = ("wins deal", "order win", "expansion", "partnership", "growth")
    if any(k in low for k in bad_kw):
        return {"sentiment": "Bad", "confidence": 0.55}
    if any(k in low for k in good_kw):
        return {"sentiment": "Good", "confidence": 0.55}
    if any(k in low for k in mediocre_kw):
        return {"sentiment": "Mediocre", "confidence": 0.5}
    if any(k in low for k in decent_kw):
        return {"sentiment": "Decent", "confidence": 0.5}
    if "guidance" in low or "maintains" in low:
        return {"sentiment": "Passable", "confidence": 0.45}
    if "board" in low or "disclosure" in low or "appoint" in low:
        return {"sentiment": "Average", "confidence": 0.45}
    return {"sentiment": "Fair", "confidence": 0.4}


async def classify_company_news_sentiment(text: str) -> dict[str, Any]:
    """Classify headline into Good…Bad taxonomy via Gemini (or heuristic fallback)."""
    body = (text or "").strip()
    if not body:
        return {"sentiment": "Average", "confidence": 0.0, "source": "empty"}

    if not gemini_enabled():
        out = _heuristic_sentiment(body)
        out["source"] = "heuristic"
        return out

    prompt = f"Company news:\n\"\"\"{body}\"\"\""
    try:
        data = await gemini_json(prompt, system=SENTIMENT_SYSTEM)
    except Exception:
        logger.exception("Gemini sentiment classify failed; using heuristic")
        out = _heuristic_sentiment(body)
        out["source"] = "heuristic_fallback"
        return out

    label = str(data.get("sentiment") or "Average").strip()
    matched = next((s for s in SENTIMENT_LABELS if s.lower() == label.lower()), "Average")
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return {"sentiment": matched, "confidence": confidence, "source": "gemini"}


OUTLOOK_SYSTEM = (
    "You are a cautious Indian equities research assistant. "
    "Use the provided historical reaction stats; do not invent prices. "
    "If sample is thin, lower confidence. JSON only."
)


async def build_outlook(
    *,
    message_text: str,
    ticker: str | None,
    sentiment: str | None,
    themes: list[str] | None,
    similar_events: list[dict[str, Any]],
) -> dict[str, Any]:
    compact_similar = []
    for ev in similar_events[:10]:
        reactions = {
            r["horizon"]: r.get("return_pct")
            for r in (ev.get("reactions") or [])
            if r.get("horizon") in {"t0", "t1", "t3", "t5"}
        }
        compact_similar.append(
            {
                "event_date": ev.get("event_date"),
                "ticker": ev.get("ticker"),
                "sentiment": ev.get("sentiment"),
                "summary": ev.get("summary"),
                "themes": ev.get("themes"),
                "returns": reactions,
            }
        )
    prompt = f"""Given a new Redbox headline and similar past events with measured returns,
return JSON:
bias: bullish|bearish|neutral|unclear
expected_horizon: string (e.g. "1-3 sessions")
typical_move_pct: number|null (signed, from similar history)
confidence: number 0-1
rationale: string
risks: array of strings
sample_size: number

Current ticker: {ticker}
Current sentiment: {sentiment}
Themes: {themes}
Headline:
\"\"\"{message_text}\"\"\"

Similar past events:
{json.dumps(compact_similar, ensure_ascii=False)}
"""
    data = await gemini_json(prompt, system=OUTLOOK_SYSTEM)
    bias = str(data.get("bias") or "unclear").lower()
    if bias not in {"bullish", "bearish", "neutral", "unclear"}:
        bias = "unclear"
    conf = data.get("confidence")
    try:
        confidence = max(0.0, min(1.0, float(conf)))
    except (TypeError, ValueError):
        confidence = 0.0
    move = data.get("typical_move_pct")
    try:
        typical = float(move) if move is not None else None
    except (TypeError, ValueError):
        typical = None
    risks = data.get("risks") or []
    if not isinstance(risks, list):
        risks = []
    return {
        "bias": bias,
        "expected_horizon": str(data.get("expected_horizon") or "").strip() or None,
        "typical_move_pct": typical,
        "confidence": confidence,
        "rationale": str(data.get("rationale") or "").strip() or None,
        "risks": [str(r).strip() for r in risks if str(r).strip()][:8],
        "sample_size": int(data.get("sample_size") or len(compact_similar)),
    }
