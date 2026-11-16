"""Extractive summary of a stored headline and blurb. No article-page fetch."""

from __future__ import annotations

import math
import re

STOP = set(
    """a an the and or but if then than so as of to in on at by for with from into over under about after before
between during without within is are was were be been being am do does did done have has had having will would shall should can
could may might must it its this that these those there here he she they them his her their our your we you i not no nor too very
just also more most less least much many some any all each every other such own same only up down out off again further once
said says say told according per via new news mr mrs ms dr""".split()
)
BOILERPLATE = re.compile(
    r"(cookie|subscribe|sign in|log in|newsletter|advertis|all rights reserved|copyright|click here|read more|"
    r"follow us|download the app|terms of (use|service)|privacy policy|javascript|enable js|share this|"
    r"related (stories|articles)|also read|watch:|photo:|image:|file photo|getty|sponsored|we use cookies)",
    re.IGNORECASE,
)
ABBR = re.compile(
    r"\b(Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|Inc|Ltd|Co|Corp|vs|etc|No|Rs|Cr|Lt|Gen|Col|Sen|Rep|Gov|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|U\.S|U\.K|U\.N|E\.U|a\.m|p\.m)\.$"
)
SPLIT = re.compile(r'(?<=[.!?])["”’)]*\s+(?=["“‘(]?[A-Z0-9₹$])')
FIGURE_RE = re.compile(
    r"(?:₹|Rs\.?\s?|INR\s?|US\$|\$|€|£)\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:trillion|billion|million|thousand|crore|lakh|bn|mn|tn|cr|k)\b)?"
    r"|\b\d[\d,]*(?:\.\d+)?(?:\s?%|\s?(?:per cent|percent|basis points|bps|crore|lakh|billion|million|trillion)\b)",
    re.IGNORECASE,
)
GENERIC_DESC = re.compile(
    r"(entire business world|one-stop finance|get the latest|breaking news,? (world|latest)|top stories|news hub|subscribe)",
    re.IGNORECASE,
)


def _stem(word: str) -> str:
    match = re.search(r"(ing|ed|es|s|ly)$", word)
    if match and match.start() > 3:
        return word[: match.start()]
    return word


def _tokenize(text: str) -> list[str]:
    cleaned = re.sub(r"[^a-z0-9₹$%.\s]", " ", text.lower())
    out = []
    for word in cleaned.split():
        word = word.strip(".")
        if len(word) > 2 and word not in STOP:
            out.append(_stem(word))
    return out


def split_sentences(text: str) -> list[str]:
    raw = SPLIT.split(re.sub(r"\s+", " ", text))
    out: list[str] = []
    for piece in raw:
        piece = piece.strip()
        if not piece:
            continue
        last = out[-1] if out else ""
        if last and (ABBR.search(last) or re.search(r"\b[A-Z]\.$", last) or (re.search(r"\d\.$", last) and len(piece) < 4)):
            out[-1] = f"{last} {piece}"
        else:
            out.append(piece)
    return out


def _text_rank(tokens: list[list[str]]) -> list[float]:
    count = len(tokens)
    sets = [set(row) for row in tokens]
    sim = [[0.0] * count for _ in range(count)]
    for i in range(count):
        for j in range(i + 1, count):
            if len(sets[i]) < 3 or len(sets[j]) < 3:
                continue
            inter = len(sets[i] & sets[j])
            score = inter / (math.log(len(sets[i]) + 1) + math.log(len(sets[j]) + 1))
            sim[i][j] = sim[j][i] = score
    rank = [1 / count] * count
    row_sum = [sum(row) for row in sim]
    for _ in range(30):
        nxt = []
        for i in range(count):
            acc = 0.0
            for j in range(count):
                if sim[j][i] and row_sum[j]:
                    acc += (sim[j][i] / row_sum[j]) * rank[j]
            nxt.append(0.15 / count + 0.85 * acc)
        rank = nxt
    return rank


def summarize_text(text: str, *, title: str = "", count: int = 3, min_len: int = 45, max_len: int = 320) -> list[str]:
    all_sentences = split_sentences(text)
    candidates = [
        {"text": sentence, "idx": index}
        for index, sentence in enumerate(all_sentences)
        if min_len <= len(sentence) <= max_len and not BOILERPLATE.search(sentence) and not re.match(r'^["“]?(Also|Read|Watch|See)\b', sentence)
    ]
    if len(candidates) <= count:
        return [item["text"] for item in candidates]
    sentences = [item["text"] for item in candidates]
    tokens = [_tokenize(sentence) for sentence in sentences]
    rank = _text_rank(tokens)
    title_set = set(_tokenize(title))
    scored = []
    for index, item in enumerate(candidates):
        title_hits = sum(1 for token in tokens[index] if token in title_set)
        title_boost = 1 + (title_hits / len(title_set)) * 0.8 if title_set else 1
        lead = 1 + max(0.0, 0.6 - (item["idx"] / max(len(all_sentences), 1)) * 1.5)
        has_figure = 1.08 if re.search(r"(\d|₹|\$|%)", item["text"]) else 1
        scored.append({**item, "tokens": tokens[index], "score": rank[index] * title_boost * lead * has_figure})
    picked: list[dict] = []
    for cand in sorted(scored, key=lambda row: row["score"], reverse=True):
        token_set = set(cand["tokens"])
        duplicate = False
        for previous in picked:
            previous_set = set(previous["tokens"])
            inter = len(token_set & previous_set)
            if inter / (min(len(token_set), len(previous_set)) or 1) > 0.7:
                duplicate = True
                break
        if not duplicate:
            picked.append(cand)
        if len(picked) == count:
            break
    picked.sort(key=lambda row: row["idx"])
    return [row["text"] for row in picked]


def extract_figures(sentences: list[str], limit: int = 5) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for sentence in sentences:
        for match in FIGURE_RE.finditer(sentence):
            figure = re.sub(r"\s+", " ", match.group(0)).strip().rstrip(".,")
            figure = re.sub(r"^(?:Rs\.?\s?|INR\s?)", "₹", figure, flags=re.IGNORECASE)
            key = figure.lower()
            if key not in seen and len(figure) >= 2:
                seen.add(key)
                out.append(figure)
            if len(out) == limit:
                return out
    return out


def summarize_blurb(title: str, description: str) -> dict:
    text = "" if not description or GENERIC_DESC.search(description) else description
    title_tokens = set(_tokenize(title))
    summary = []
    for sentence in summarize_text(text, title=title, count=2, min_len=25):
        tokens = _tokenize(sentence)
        hits = sum(1 for word in tokens if word in title_tokens)
        if tokens and hits / len(tokens) >= 0.75:
            continue
        summary.append(sentence)
    return {
        "status": "blurb",
        "title": title,
        "summary": summary,
        "figures": extract_figures(summary or split_sentences(text)[:4]),
    }
