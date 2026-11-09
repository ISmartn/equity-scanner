"""UI knowledge cards and execution checklists (synthesis, not book quotes)."""

from __future__ import annotations

from typing import Any

KNOWLEDGE_CARDS: list[dict[str, Any]] = [
    {
        "id": "edge",
        "part": "I",
        "title": "Statistical edge vs apophenia",
        "summary": "Most chart pictures are noise. An edge is a forward-return discrepancy vs random entries after costs.",
        "rules": [
            "Tag every trade by template so expectancy is per setup, not a blended diary.",
            "Require Monte Carlo p-value context before increasing size.",
            "Do not add filters that only work on the same sample you used to invent them.",
        ],
    },
    {
        "id": "two-forces",
        "part": "I",
        "title": "Two forces: imbalance vs balance",
        "summary": "Trends are imbalance (initiative, range expansion). Ranges are two-sided trade around value.",
        "rules": [
            "Do not fade impulse closes far from the 20 EMA without a failure test.",
            "In balance, fade edges (springs/upthrusts); in imbalance, buy/sell pullbacks.",
        ],
    },
    {
        "id": "wyckoff",
        "part": "I",
        "title": "Four phases",
        "summary": "Accumulation → mark-up → distribution → mark-down, plus mid-trend re-accumulation ranges.",
        "rules": [
            "Match the four trades to the phase: pullbacks in mark-up, failure tests in ranges, breakouts out of coils.",
            "Weekly EMA alignment is the higher-timeframe phase filter.",
        ],
    },
    {
        "id": "pullback",
        "part": "II",
        "title": "Simple pullback (trend continuation)",
        "summary": "After an impulse, wait for a contracting retrace into 20 EMA / 50 SMA with declining volume.",
        "rules": [
            "Long only with HH+HL (or 20>50 stack) and a hold of the last higher low.",
            "Stop: hybrid structural / 1.5–2.0×ATR. Trigger: stop above trigger bar or limit at the MA.",
            "Skip if MACD made a lower high into a new price high (divergence).",
        ],
        "failure": "Break of last HL with expanding range/volume — idea is wrong, not 'more room'.",
        "management": "Scale 50% at 1–2R; trail remainder with swing low or 20 EMA.",
    },
    {
        "id": "complex",
        "part": "II",
        "title": "Complex pullback (ABC)",
        "summary": "Two-legged correction: first bounce fails, second leg completes, then trend resumes.",
        "rules": [
            "Second high of the correction should not recapture the impulse high (longs).",
            "Common later in a trend — reduce size vs a first pullback.",
        ],
        "failure": "Second leg becomes a new impulse against you (LH/LL sequence).",
        "management": "Same R framework; time-stop if no follow-through in 8 bars.",
    },
    {
        "id": "squeeze",
        "part": "II",
        "title": "NR7 / inside days / BB–Keltner squeeze",
        "summary": "Volatility compression precedes expansion. Direction comes from MA stack and weekly bias, not the coil itself.",
        "rules": [
            "NR7 = smallest range of the last 7 bars.",
            "Validate breakouts with range expansion and lack of immediate rejection.",
            "The first pullback after a true breakout is often the cleaner continuation.",
        ],
        "failure": "Wide-range close back inside the coil = failed breakout / Anti context.",
        "management": "Stop beyond the opposite side of the coil; do not use tiny NR7 stops (noise).",
    },
    {
        "id": "failure-test",
        "part": "II",
        "title": "Failure test (spring / upthrust)",
        "summary": "Probe beyond a swing that cannot follow through; trapped breakout traders fuel the reverse.",
        "rules": [
            "Spring: low under support, close back above. Upthrust: high over resistance, close back below.",
            "Best in trading ranges and at trend termination, not mid-impulse.",
        ],
        "failure": "Follow-through beyond the probe on the next bar — stand aside or reverse only with a new plan.",
        "management": "Stop beyond the probe extreme; target value (20 EMA) then 2R.",
    },
    {
        "id": "climax",
        "part": "II",
        "title": "Climactic exhaustion",
        "summary": "Outlier range (>2.5×ATR) far from the EMA with a volume spike. Mean-reversion context, not a new trend.",
        "rules": [
            "Do not mechanically fade the first spike; prefer a failure test or a close back inside 2.25-ATR Keltner.",
            "MACD new extremes on climax bars are often distorted — ignore naive MACD pullback buys.",
        ],
        "failure": "Continuation range expansion the next session — you are fading a real breakout.",
        "management": "Partial at the EMA; never hold a fade into a new impulse without structure.",
    },
    {
        "id": "absorption",
        "part": "II",
        "title": "Absorption",
        "summary": "High volume, narrow spread at S/R — effort without displacement (daily proxy for book absorption).",
        "rules": [
            "Requires a nearby swing or MA. Zero-volume bars are ignored.",
            "Not a standalone trigger; combine with spring/upthrust or pullback resume.",
        ],
        "failure": "Next bar range-expands through the zone.",
        "management": "Tight structural stop; small size (information bar, not a full-risk idea).",
    },
    {
        "id": "risk",
        "part": "IV",
        "title": "Risk, R, and sizing",
        "summary": "Fixed fraction 1–2% of equity per idea. Shares = f×equity / |entry−stop|.",
        "rules": [
            "<1% is conservative; ~2% is aggressive for one name.",
            "Positive expectancy does not prevent ruin if the left tail and size are too large.",
            "Equalize dollar risk across names (ATR), not share count.",
        ],
    },
    {
        "id": "mae-mfe",
        "part": "IV",
        "title": "MAE / MFE",
        "summary": "MAE is how far the trade went against you in R; MFE is the best open profit in R.",
        "rules": [
            "Winners with MAE>1R → stops too tight or entries too early.",
            "MFE ≫ realized R → scale/trail too soon or targets too close.",
        ],
    },
    {
        "id": "psychology",
        "part": "IV",
        "title": "Process over stories",
        "summary": "Random reinforcement makes broken tactics feel skillful. Journal templates, not P&L narratives.",
        "rules": [
            "Do not tighten stops for comfort.",
            "A losing streak is expected inside a positive-E process — size so you survive it.",
            "Pre-commit the four-trade slot before clicking.",
        ],
    },
]


SETUP_CHECKLISTS: dict[str, dict[str, Any]] = {
    "TREND_PULLBACK": {
        "title": "Trend pullback execution",
        "entry": "Limit at 20 EMA / 50 SMA or buy stop above the trigger-bar high (long).",
        "stop": "Hybrid: last HL (buffered) vs 1.8×ATR; never tighter than 1×ATR.",
        "targets": "50% at 1–2R; runner via swing trail or 20 EMA.",
        "fail": "Close beyond last HL with expanding range.",
        "time_stop": "Kill if still < +0.5R after 8 sessions.",
    },
    "COMPLEX_PULLBACK": {
        "title": "Complex pullback (ABC) execution",
        "entry": "After C-leg hold, confirmation stop through B-leg extreme.",
        "stop": "Beyond C-leg extreme + ATR buffer.",
        "targets": "Prior impulse high/low, then 2R.",
        "fail": "C-leg becomes a new with-trend impulse against the larger trend.",
        "time_stop": "8 bars, min +0.5R.",
    },
    "VOL_SQUEEZE": {
        "title": "Squeeze / NR7 breakout execution",
        "entry": "Stop through coil high/low with range expansion; skip if immediate rejection.",
        "stop": "Opposite side of the coil (not a 0.3×ATR NR7 stop).",
        "targets": "1R scale; trail on first pullback hold.",
        "fail": "Close back inside the compression range.",
        "time_stop": "6 bars if still inside the coil.",
    },
    "FAILED_BREAKOUT": {
        "title": "Spring / upthrust execution",
        "entry": "Close back inside the level, or next-bar confirmation stop.",
        "stop": "Beyond the probe extreme.",
        "targets": "Range midpoint / 20 EMA, then 2R.",
        "fail": "Immediate follow-through beyond the probe.",
        "time_stop": "5–8 bars.",
    },
    "CLIMACTIC_EXHAUSTION": {
        "title": "Climax mean-reversion (context)",
        "entry": "Prefer failure test or close back inside 2.25-ATR Keltner — not the spike print.",
        "stop": "Beyond climax extreme.",
        "targets": "20 EMA then 50 SMA.",
        "fail": "Another >2×ATR continuation bar.",
        "time_stop": "Aggressive: 5 bars.",
    },
    "ABSORPTION": {
        "title": "Absorption at S/R",
        "entry": "Only with a spring/upthrust or pullback resume on the next bar.",
        "stop": "Beyond the absorption bar extreme.",
        "targets": "1R; do not oversize.",
        "fail": "Displacement through the zone next bar.",
        "time_stop": "3–5 bars.",
    },
}
