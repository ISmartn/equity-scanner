"""Elliott impulse / zigzag pattern rules + surety scoring."""

from __future__ import annotations

from typing import Any

import numpy as np


def _fib_score(ratio: float, targets: list[float], tol: float = 0.12) -> float:
    """0-1 score for how close ``ratio`` is to any Fibonacci target."""
    if not np.isfinite(ratio) or ratio <= 0:
        return 0.0
    best = 0.0
    for t in targets:
        err = abs(ratio - t) / max(t, 1e-9)
        best = max(best, max(0.0, 1.0 - err / tol))
    return best


def _wave_len(a: dict[str, Any], b: dict[str, Any]) -> float:
    return abs(float(b["price"]) - float(a["price"]))


def _wave_bars(a: dict[str, Any], b: dict[str, Any]) -> int:
    return max(1, int(b["index"]) - int(a["index"]))


def validate_impulse(p0: dict, p1: dict, p2: dict, p3: dict, p4: dict, p5: dict) -> dict[str, Any] | None:
    """
    Bullish impulse: TROUGH-PEAK-TROUGH-PEAK-TROUGH-PEAK
    Bearish impulse: PEAK-TROUGH-PEAK-TROUGH-PEAK-TROUGH
    """
    types = [p["type"] for p in (p0, p1, p2, p3, p4, p5)]
    if types == ["TROUGH", "PEAK", "TROUGH", "PEAK", "TROUGH", "PEAK"]:
        bullish = True
    elif types == ["PEAK", "TROUGH", "PEAK", "TROUGH", "PEAK", "TROUGH"]:
        bullish = False
    else:
        return None

    w1 = _wave_len(p0, p1)
    w2 = _wave_len(p1, p2)
    w3 = _wave_len(p2, p3)
    w4 = _wave_len(p3, p4)
    w5 = _wave_len(p4, p5)
    if min(w1, w2, w3, w4, w5) <= 0:
        return None

    # Rule 1: Wave 2 retracement <= 100% of Wave 1
    if w2 > w1 * 1.001:
        return None

    # Rule 2: Wave 3 cannot be shortest of 1, 3, 5
    if w3 <= min(w1, w5) + 1e-9:
        return None

    # Rule 3: Wave 4 must not overlap Wave 1 extreme (0.5% buffer)
    buf = 0.005
    if bullish:
        # Wave 4 trough should stay above Wave 1 peak *(1 - buffer)
        if float(p4["price"]) < float(p1["price"]) * (1.0 - buf):
            return None
    else:
        if float(p4["price"]) > float(p1["price"]) * (1.0 + buf):
            return None

    # Neo-Wave similarity: time ratio Wave2 / Wave4 in [0.382, 2.618]
    t2 = _wave_bars(p1, p2)
    t4 = _wave_bars(p3, p4)
    time_ratio = t2 / t4
    neo_ok = 0.382 <= time_ratio <= 2.618

    retr_2 = w2 / w1
    ext_3 = w3 / w1
    retr_4 = w4 / w3
    ext_5 = w5 / w1

    surety = 0.0
    surety += 18 * _fib_score(retr_2, [0.382, 0.5, 0.618])
    surety += 28 * _fib_score(ext_3, [1.0, 1.618, 2.0, 2.618])
    surety += 18 * _fib_score(retr_4, [0.236, 0.382, 0.5])
    surety += 18 * _fib_score(ext_5, [0.618, 1.0, 1.618])
    surety += 10 if neo_ok else 0
    # Structure bonus
    surety += 8
    surety = float(min(100.0, round(surety, 1)))

    if bullish:
        invalidation = float(p4["price"])  # below Wave 4 trough voids count
        last_price_ref = float(p5["price"])
    else:
        invalidation = float(p4["price"])
        last_price_ref = float(p5["price"])

    # Phase heuristic from how recently wave 5 completed vs still mid-structure
    # (caller may refine using live price)
    phase = "Impulse Complete"
    labels = [
        {"label": "0", "pivot": p0},
        {"label": "1", "pivot": p1},
        {"label": "2", "pivot": p2},
        {"label": "3", "pivot": p3},
        {"label": "4", "pivot": p4},
        {"label": "5", "pivot": p5},
    ]

    return {
        "pattern": "impulse",
        "direction": "bullish" if bullish else "bearish",
        "phase": phase,
        "surety_score": surety,
        "invalidation_price": round(invalidation, 4),
        "neo_wave_ok": neo_ok,
        "time_ratio_2_4": round(time_ratio, 3),
        "fib": {
            "wave2_retr": round(retr_2, 3),
            "wave3_ext": round(ext_3, 3),
            "wave4_retr": round(retr_4, 3),
            "wave5_ext": round(ext_5, 3),
        },
        "waves": labels,
        "pivot_indices": [p0["index"], p1["index"], p2["index"], p3["index"], p4["index"], p5["index"]],
        "_last_ref": last_price_ref,
    }


def validate_zigzag(p0: dict, p1: dict, p2: dict, p3: dict) -> dict[str, Any] | None:
    """A-B-C zigzag: Wave B <= 61.8% of A; Wave C beyond A."""
    types = [p["type"] for p in (p0, p1, p2, p3)]
    if types == ["PEAK", "TROUGH", "PEAK", "TROUGH"]:
        # bearish zigzag (down A, up B, down C)
        bearish = True
    elif types == ["TROUGH", "PEAK", "TROUGH", "PEAK"]:
        bearish = False
    else:
        return None

    wa = _wave_len(p0, p1)
    wb = _wave_len(p1, p2)
    wc = _wave_len(p2, p3)
    if min(wa, wb, wc) <= 0:
        return None

    if wb > wa * 0.618 + 1e-9:
        return None

    # C must go beyond A
    if bearish:
        if float(p3["price"]) >= float(p1["price"]):
            return None
        invalidation = float(p2["price"])
    else:
        if float(p3["price"]) <= float(p1["price"]):
            return None
        invalidation = float(p2["price"])

    retr_b = wb / wa
    ext_c = wc / wa
    surety = 0.0
    surety += 35 * _fib_score(retr_b, [0.382, 0.5, 0.618])
    surety += 35 * _fib_score(ext_c, [1.0, 1.272, 1.618])
    surety += 15
    surety = float(min(100.0, round(surety, 1)))

    return {
        "pattern": "zigzag",
        "direction": "bearish" if bearish else "bullish",
        "phase": "Zigzag Corrective",
        "surety_score": surety,
        "invalidation_price": round(invalidation, 4),
        "neo_wave_ok": None,
        "time_ratio_2_4": None,
        "fib": {
            "wave_b_retr": round(retr_b, 3),
            "wave_c_ext": round(ext_c, 3),
        },
        "waves": [
            {"label": "A", "pivot": p0},
            {"label": "B", "pivot": p1},
            {"label": "C", "pivot": p2},
            {"label": "C-end", "pivot": p3},
        ],
        "pivot_indices": [p0["index"], p1["index"], p2["index"], p3["index"]],
    }


def refine_phase(hit: dict[str, Any], last_close: float) -> str:
    """Label actionable phases for scanner filters."""
    if hit["pattern"] == "zigzag":
        return "Zigzag Corrective"

    bullish = hit["direction"] == "bullish"
    waves = hit["waves"]
    p3 = waves[3]["pivot"]
    p4 = waves[4]["pivot"]
    p5 = waves[5]["pivot"]

    # If price still near/above wave 3 and hasn't finished a deep wave 4 → Wave 3 breakout
    if bullish:
        if last_close >= float(p3["price"]) * 0.98 and float(p5["price"]) >= float(p3["price"]):
            # Completed through 5 but if recent pivot is 4 region
            if float(p4["price"]) >= float(p3["price"]) * 0.92 and last_close <= float(p3["price"]) * 1.02:
                return "Wave 4 Dip"
            if last_close >= float(p3["price"]) and last_close < float(p5["price"]) * 0.97:
                return "Wave 3 Breakout"
        if last_close <= float(p3["price"]) and last_close >= float(p4["price"]) * 0.98:
            return "Wave 4 Dip"
    else:
        if last_close <= float(p3["price"]) * 1.02:
            if last_close >= float(p4["price"]) * 0.98 and last_close <= float(p3["price"]):
                return "Wave 4 Dip"
            if last_close <= float(p3["price"]):
                return "Wave 3 Breakout"

    return "Impulse Complete"


def _lvl(label: str, price: float, role: str, note: str) -> dict[str, Any]:
    return {
        "label": label,
        "price": round(float(price), 2),
        "role": role,  # support | resistance | target | invalidation
        "note": note,
    }


def build_beginner_guide(hit: dict[str, Any] | None, last_close: float) -> dict[str, Any]:
    """Plain-language guidance for newcomers (current wave, trend, next, levels)."""
    if not hit:
        return {
            "current_wave": "Unknown",
            "trend": "Unclear",
            "trend_plain": "No clear Elliott count yet — wait for clearer swings.",
            "what_next": "Watch for a fresh ZigZag swing before trusting a count.",
            "plain_summary": (
                "The scanner could not lock a valid impulse (1–5) or zigzag (A–B–C). "
                "That often means the recent moves are noisy. Prefer waiting over forcing a count."
            ),
            "levels": [],
            "glossary": [
                "Impulse 1–5 = trending move in five swings.",
                "Zigzag A–B–C = corrective / counter-trend move.",
                "Invalidation = price level that breaks this count.",
            ],
        }

    pattern = hit.get("pattern")
    direction = hit.get("direction")
    phase = hit.get("phase") or ""
    inv = hit.get("invalidation_price")
    waves = hit.get("waves") or []
    bullish = direction == "bullish"
    trend = "Uptrend" if bullish else "Downtrend"
    levels: list[dict[str, Any]] = []

    if pattern == "impulse" and len(waves) >= 6:
        p0 = waves[0]["pivot"]
        p1 = waves[1]["pivot"]
        p2 = waves[2]["pivot"]
        p3 = waves[3]["pivot"]
        p4 = waves[4]["pivot"]
        p5 = waves[5]["pivot"]
        w1 = _wave_len(p0, p1)
        w3 = _wave_len(p2, p3)

        if phase == "Wave 3 Breakout":
            current_wave = "Wave 3 (strong trend leg)"
            what_next = (
                "Wave 3 is often the strongest leg. Next, expect a Wave 4 pause/pullback, "
                "then a final Wave 5 push in the trend direction."
            )
            if bullish:
                t1 = float(p2["price"]) + w1  # 1.0 extension of W1 from W2
                t2 = float(p2["price"]) + 1.618 * w1
                levels.extend(
                    [
                        _lvl("Wave 3 target (1× W1)", t1, "target", "Common Wave 3 objective"),
                        _lvl("Wave 3 stretch (1.618× W1)", t2, "target", "Extended Wave 3 zone"),
                        _lvl("Wave 2 low (support)", float(p2["price"]), "support", "Trend support if still in Wave 3"),
                    ]
                )
            else:
                t1 = float(p2["price"]) - w1
                t2 = float(p2["price"]) - 1.618 * w1
                levels.extend(
                    [
                        _lvl("Wave 3 target (1× W1)", t1, "target", "Common Wave 3 objective"),
                        _lvl("Wave 3 stretch (1.618× W1)", t2, "target", "Extended Wave 3 zone"),
                        _lvl("Wave 2 high (resistance)", float(p2["price"]), "resistance", "Trend resistance if still in Wave 3"),
                    ]
                )
        elif phase == "Wave 4 Dip":
            current_wave = "Wave 4 (pause / pullback)"
            what_next = (
                "Wave 4 is a rest after Wave 3. Next expected move is Wave 5 — "
                "another push in the main trend direction. Wave 4 should not wipe out Wave 1."
            )
            if bullish:
                # Fib retracements of Wave 3
                r382 = float(p3["price"]) - 0.382 * w3
                r5 = float(p3["price"]) - 0.5 * w3
                w5_eq = float(p4["price"]) + w1
                levels.extend(
                    [
                        _lvl("W4 shallow (38.2%)", r382, "support", "Typical shallow Wave 4"),
                        _lvl("W4 mid (50%)", r5, "support", "Deeper Wave 4 zone"),
                        _lvl("Wave 5 equal-W1 target", w5_eq, "target", "If Wave 5 ≈ Wave 1"),
                        _lvl("Wave 1 high (no-overlap)", float(p1["price"]), "support", "Wave 4 should stay above this"),
                    ]
                )
            else:
                r382 = float(p3["price"]) + 0.382 * w3
                r5 = float(p3["price"]) + 0.5 * w3
                w5_eq = float(p4["price"]) - w1
                levels.extend(
                    [
                        _lvl("W4 shallow (38.2%)", r382, "resistance", "Typical shallow Wave 4"),
                        _lvl("W4 mid (50%)", r5, "resistance", "Deeper Wave 4 zone"),
                        _lvl("Wave 5 equal-W1 target", w5_eq, "target", "If Wave 5 ≈ Wave 1"),
                        _lvl("Wave 1 low (no-overlap)", float(p1["price"]), "resistance", "Wave 4 should stay below this"),
                    ]
                )
        else:
            current_wave = "Wave 5 (final impulse leg) / complete"
            what_next = (
                "A full 1–5 impulse may be finishing. Next is often an A–B–C correction "
                "against the prior trend. Treat new highs/lows with caution until a clear pullback forms."
            )
            if bullish:
                levels.extend(
                    [
                        _lvl("Wave 5 peak (recent)", float(p5["price"]), "resistance", "Impulse high"),
                        _lvl("Wave 4 low", float(p4["price"]), "support", "First support after Wave 5"),
                        _lvl("Wave 2 low", float(p2["price"]), "support", "Deeper corrective support"),
                    ]
                )
            else:
                levels.extend(
                    [
                        _lvl("Wave 5 trough (recent)", float(p5["price"]), "support", "Impulse low"),
                        _lvl("Wave 4 high", float(p4["price"]), "resistance", "First resistance after Wave 5"),
                        _lvl("Wave 2 high", float(p2["price"]), "resistance", "Deeper corrective resistance"),
                    ]
                )

        if inv is not None:
            levels.append(
                _lvl(
                    "Invalidation",
                    float(inv),
                    "invalidation",
                    "If price breaks this, the 1–5 count is likely wrong",
                )
            )

        plain = (
            f"Best count looks like a {'rising' if bullish else 'falling'} impulse (waves 1–5). "
            f"Right now we label it as: {current_wave}. "
            f"Trend bias: {trend}. "
            f"{what_next}"
        )

    elif pattern == "zigzag" and len(waves) >= 4:
        p0 = waves[0]["pivot"]
        p1 = waves[1]["pivot"]
        p2 = waves[2]["pivot"]
        p3 = waves[3]["pivot"]
        wa = _wave_len(p0, p1)
        current_wave = "Wave C (zigzag ending / active)"
        # For zigzag, "bullish" zigzag means A up B down C up (corrective up in a larger down? )
        # Our validate: TROUGH-PEAK-TROUGH-PEAK = bullish zigzag (A up)
        what_next = (
            "Zigzag A–B–C is usually a correction. After Wave C finishes, price often "
            "resumes the larger trend that was in place before A–B–C."
        )
        if bullish:
            # A up, C beyond A high
            levels.extend(
                [
                    _lvl("Wave A high", float(p1["price"]), "resistance", "A top"),
                    _lvl("Wave B low", float(p2["price"]), "support", "B trough"),
                    _lvl("Wave C 1× A target", float(p2["price"]) + wa, "target", "C ≈ A length"),
                    _lvl("Wave C 1.618× A", float(p2["price"]) + 1.618 * wa, "target", "Extended C"),
                ]
            )
        else:
            levels.extend(
                [
                    _lvl("Wave A low", float(p1["price"]), "support", "A bottom"),
                    _lvl("Wave B high", float(p2["price"]), "resistance", "B peak"),
                    _lvl("Wave C 1× A target", float(p2["price"]) - wa, "target", "C ≈ A length"),
                    _lvl("Wave C 1.618× A", float(p2["price"]) - 1.618 * wa, "target", "Extended C"),
                ]
            )
        if inv is not None:
            levels.append(
                _lvl("Invalidation", float(inv), "invalidation", "Break voids this zigzag count")
            )
        plain = (
            f"Best count looks like a zigzag correction (A–B–C), direction {direction}. "
            f"Current focus: {current_wave}. Trend of this pattern: {trend}. {what_next}"
        )
    else:
        current_wave = phase or "Unclear"
        what_next = "Wait for the next confirmed pivot before acting on this count."
        plain = "Pattern detected but guidance is limited — treat levels as experimental."

    # De-dupe levels by rounded price
    seen: set[float] = set()
    uniq: list[dict[str, Any]] = []
    for lv in levels:
        key = round(lv["price"], 2)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(lv)
    # Sort nearest to last_close first for readability
    uniq.sort(key=lambda x: abs(x["price"] - last_close))

    return {
        "current_wave": current_wave,
        "trend": trend,
        "trend_plain": (
            f"{trend}: prices in this count are making {'higher' if bullish else 'lower'} "
            f"impulse swings."
        ),
        "what_next": what_next,
        "plain_summary": plain,
        "levels": uniq[:8],
        "glossary": [
            "Wave 1 = first push in a new direction.",
            "Wave 2 = pullback (cannot erase Wave 1).",
            "Wave 3 = usually the strongest trend push.",
            "Wave 4 = pause (should not overlap Wave 1).",
            "Wave 5 = final push of the impulse.",
            "A–B–C = corrective zigzag against a larger move.",
        ],
    }


def detect_best_pattern(pivots: list[dict[str, Any]], last_close: float) -> dict[str, Any] | None:
    """Scan recent pivot windows; keep highest-surety valid structure."""
    best: dict[str, Any] | None = None

    # Prefer structures that end on the latest pivots
    for end in range(len(pivots) - 1, 4, -1):
        window = pivots[end - 5 : end + 1]
        if len(window) < 6:
            continue
        hit = validate_impulse(*window)
        if hit:
            hit["phase"] = refine_phase(hit, last_close)
            if best is None or hit["surety_score"] > best["surety_score"]:
                best = hit
            # Prefer the most recent valid impulse
            if end >= len(pivots) - 2:
                break

    if best is None:
        for end in range(len(pivots) - 1, 2, -1):
            window = pivots[end - 3 : end + 1]
            if len(window) < 4:
                continue
            hit = validate_zigzag(*window)
            if hit:
                if best is None or hit["surety_score"] > best["surety_score"]:
                    best = hit
                if end >= len(pivots) - 2:
                    break

    if best:
        best.pop("_last_ref", None)
    return best
