"""Quarter-by-quarter earnings momentum verdict (separate from quality gate)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

# Soft bands — momentum is directional, not a hard fundamental screen.
MIN_YOY_IMPROVING_PCT = 0.0
MIN_YOY_ACCELERATING_PCT = 5.0
STABLE_ABS_BAND_PCT = 3.0


@dataclass(frozen=True)
class MomentumThresholds:
    min_yoy_improving_pct: float = MIN_YOY_IMPROVING_PCT
    min_yoy_accelerating_pct: float = MIN_YOY_ACCELERATING_PCT
    stable_abs_band_pct: float = STABLE_ABS_BAND_PCT


DEFAULT_MOMENTUM_THRESHOLDS = MomentumThresholds()


def _parse_number(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace(",", "")
    if not text or text in {"—", "-", "NA", "N/A", "null"}:
        return None
    if text.endswith("%"):
        text = text[:-1].strip()
    if text.startswith("+"):
        text = text[1:]
    try:
        return float(text)
    except ValueError:
        return None


def _pct_change(newer: float | None, older: float | None) -> float | None:
    if newer is None or older is None:
        return None
    if older == 0:
        return None
    return ((newer - older) / abs(older)) * 100.0


def _category_history(section: Any, category: str) -> list[dict[str, Any]]:
    if not isinstance(section, dict):
        return []
    for row in section.get("income_statement") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("category") or "").strip().lower() == category:
            hist = row.get("history")
            return [h for h in hist if isinstance(h, dict)] if isinstance(hist, list) else []
    return []


def _latest_yoy_pct(history: list[dict[str, Any]]) -> float | None:
    """Prefer vendor YoY `change` on the latest quarter (same-quarter prior year)."""
    if not history:
        return None
    return _parse_number(history[0].get("change"))


def _qoq_pct_at(history: list[dict[str, Any]], index: int = 0) -> float | None:
    if index + 1 >= len(history):
        return None
    newer = _parse_number(history[index].get("value"))
    older = _parse_number(history[index + 1].get("value"))
    return _pct_change(newer, older)


def _positive_qoq_streak(history: list[dict[str, Any]]) -> int:
    streak = 0
    for i in range(max(0, len(history) - 1)):
        ch = _qoq_pct_at(history, i)
        if ch is not None and ch > 0:
            streak += 1
        else:
            break
    return streak


def _build_quarter_rows(
    *,
    revenue: list[dict[str, Any]],
    operating: list[dict[str, Any]],
    net_profit: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    periods: list[str] = []
    for hist in (revenue, operating, net_profit):
        for item in hist:
            period = str(item.get("period") or "").strip()
            if period and period not in periods:
                periods.append(period)

    def _value_for(hist: list[dict[str, Any]], period: str) -> float | None:
        for item in hist:
            if str(item.get("period") or "").strip() == period:
                return _parse_number(item.get("value"))
        return None

    rows: list[dict[str, Any]] = []
    for i, period in enumerate(periods[:6]):
        rev = _value_for(revenue, period)
        op = _value_for(operating, period)
        pat = _value_for(net_profit, period)
        prev_period = periods[i + 1] if i + 1 < len(periods) else None
        prev_rev = _value_for(revenue, prev_period) if prev_period else None
        prev_op = _value_for(operating, prev_period) if prev_period else None
        prev_pat = _value_for(net_profit, prev_period) if prev_period else None
        rows.append(
            {
                "period": period,
                "revenue": rev,
                "operating_profit": op,
                "net_profit": pat,
                "revenue_qoq_pct": round(q, 2) if (q := _pct_change(rev, prev_rev)) is not None else None,
                "operating_profit_qoq_pct": (
                    round(q, 2) if (q := _pct_change(op, prev_op)) is not None else None
                ),
                "net_profit_qoq_pct": (
                    round(q, 2) if (q := _pct_change(pat, prev_pat)) is not None else None
                ),
            }
        )
    return rows


def evaluate_earnings_momentum(
    payload: dict[str, Any] | None,
    *,
    thresholds: MomentumThresholds = DEFAULT_MOMENTUM_THRESHOLDS,
) -> dict[str, Any]:
    """
    Score recent quarterly trajectory (YoY + QoQ). Independent of quality verdict.

    Labels: Accelerating / Improving / Stable / Slowing / Recovering / Deteriorating.
    """
    thr = thresholds
    empty = {
        "available": False,
        "pass": None,
        "strong": None,
        "label": "Insufficient quarterly data",
        "summary": (
            "No quarterly income history yet. Sync fundamentals to pull quarterly "
            "statements, then reopen research."
        ),
        "metrics": {},
        "quarters": [],
        "reasons": [],
        "thresholds": asdict(thr),
    }
    if not payload or not isinstance(payload, dict):
        return empty

    quarterly = payload.get("income_statement_quarterly")
    rev_hist = _category_history(quarterly, "revenue")
    op_hist = _category_history(quarterly, "operating_profit")
    pat_hist = _category_history(quarterly, "net_profit")

    if len(rev_hist) < 2 and len(pat_hist) < 2:
        return empty

    rev_yoy = _latest_yoy_pct(rev_hist)
    op_yoy = _latest_yoy_pct(op_hist)
    pat_yoy = _latest_yoy_pct(pat_hist)
    rev_qoq = _qoq_pct_at(rev_hist, 0)
    op_qoq = _qoq_pct_at(op_hist, 0)
    pat_qoq = _qoq_pct_at(pat_hist, 0)
    prior_pat_qoq = _qoq_pct_at(pat_hist, 1)
    pat_streak = _positive_qoq_streak(pat_hist)
    rev_streak = _positive_qoq_streak(rev_hist)

    latest_period = None
    for hist in (pat_hist, rev_hist, op_hist):
        if hist:
            latest_period = str(hist[0].get("period") or "").strip() or None
            break

    metrics = {
        "latest_period": latest_period,
        "revenue_yoy_pct": round(rev_yoy, 2) if rev_yoy is not None else None,
        "revenue_qoq_pct": round(rev_qoq, 2) if rev_qoq is not None else None,
        "operating_profit_yoy_pct": round(op_yoy, 2) if op_yoy is not None else None,
        "operating_profit_qoq_pct": round(op_qoq, 2) if op_qoq is not None else None,
        "pat_yoy_pct": round(pat_yoy, 2) if pat_yoy is not None else None,
        "pat_qoq_pct": round(pat_qoq, 2) if pat_qoq is not None else None,
        "pat_qoq_streak": pat_streak,
        "revenue_qoq_streak": rev_streak,
    }

    reasons: list[dict[str, Any]] = []

    def _add(
        check_id: str,
        *,
        ok: bool,
        title: str,
        message: str,
        actual: float | None = None,
        threshold: float | None = None,
        unit: str = "%",
    ) -> None:
        reasons.append(
            {
                "id": check_id,
                "ok": ok,
                "title": title,
                "message": message,
                "actual": actual,
                "threshold": threshold,
                "unit": unit,
            }
        )

    if pat_yoy is not None:
        _add(
            "pat_yoy",
            ok=pat_yoy > thr.min_yoy_improving_pct,
            title="PAT YoY",
            message=(
                f"Net profit {pat_yoy:+.1f}% vs same quarter last year."
                if pat_yoy != 0
                else "Net profit flat vs same quarter last year."
            ),
            actual=round(pat_yoy, 2),
            threshold=thr.min_yoy_improving_pct,
        )
    if pat_qoq is not None:
        _add(
            "pat_qoq",
            ok=pat_qoq > 0,
            title="PAT QoQ",
            message=(
                f"Net profit {pat_qoq:+.1f}% vs prior quarter."
                if pat_qoq != 0
                else "Net profit flat vs prior quarter."
            ),
            actual=round(pat_qoq, 2),
            threshold=0.0,
        )
    if rev_yoy is not None:
        _add(
            "revenue_yoy",
            ok=rev_yoy > thr.min_yoy_improving_pct,
            title="Revenue YoY",
            message=f"Revenue {rev_yoy:+.1f}% vs same quarter last year.",
            actual=round(rev_yoy, 2),
            threshold=thr.min_yoy_improving_pct,
        )
    if rev_qoq is not None:
        _add(
            "revenue_qoq",
            ok=rev_qoq > 0,
            title="Revenue QoQ",
            message=f"Revenue {rev_qoq:+.1f}% vs prior quarter.",
            actual=round(rev_qoq, 2),
            threshold=0.0,
        )
    if op_qoq is not None:
        _add(
            "op_qoq",
            ok=op_qoq > 0,
            title="Operating profit QoQ",
            message=f"Operating profit {op_qoq:+.1f}% vs prior quarter.",
            actual=round(op_qoq, 2),
            threshold=0.0,
        )

    # Classify primarily on PAT; fall back to revenue if PAT missing.
    yoy = pat_yoy if pat_yoy is not None else rev_yoy
    qoq = pat_qoq if pat_qoq is not None else rev_qoq

    if yoy is None and qoq is None:
        return empty

    label = "Stable"
    summary = "Recent quarters look roughly flat."
    strong: bool | None = False
    passed: bool | None = None

    yoy_v = yoy if yoy is not None else 0.0
    qoq_v = qoq if qoq is not None else 0.0
    band = thr.stable_abs_band_pct

    accelerating = (
        yoy is not None
        and qoq is not None
        and yoy_v >= thr.min_yoy_accelerating_pct
        and qoq_v > 0
        and (
            pat_streak >= 2
            or (prior_pat_qoq is not None and qoq_v > prior_pat_qoq)
            or (rev_streak >= 2 and pat_yoy is not None and pat_yoy > 0)
        )
    )
    improving = (
        not accelerating
        and yoy is not None
        and yoy_v > thr.min_yoy_improving_pct
        and (qoq is None or qoq_v >= 0)
    )
    recovering = yoy is not None and qoq is not None and yoy_v < 0 and qoq_v > 0
    slowing = yoy is not None and qoq is not None and yoy_v > 0 and qoq_v < 0
    deteriorating = yoy is not None and qoq is not None and yoy_v < 0 and qoq_v < 0
    stable = abs(yoy_v) <= band and abs(qoq_v) <= band

    period_bit = f" (latest {latest_period})" if latest_period else ""

    if accelerating:
        label = "Accelerating"
        strong = True
        passed = True
        summary = (
            f"Earnings momentum is accelerating{period_bit}: solid YoY growth with "
            f"improving sequential prints."
        )
    elif improving:
        label = "Improving"
        strong = False
        passed = True
        summary = (
            f"Quarterly trajectory is constructive{period_bit}: profits up YoY "
            f"without sequential deterioration."
        )
    elif recovering:
        label = "Recovering"
        strong = False
        passed = True
        summary = (
            f"Still soft vs last year{period_bit}, but the latest quarter improved "
            f"sequentially — early recovery signal."
        )
    elif deteriorating:
        label = "Deteriorating"
        strong = False
        passed = False
        summary = (
            f"Earnings are deteriorating{period_bit}: down both YoY and vs the prior quarter."
        )
    elif slowing:
        label = "Slowing"
        strong = False
        passed = False
        summary = (
            f"Still up YoY{period_bit}, but the latest quarter cooled sequentially — "
            f"momentum is slowing."
        )
    elif stable:
        label = "Stable"
        strong = False
        passed = True
        summary = f"Quarterly results look roughly stable{period_bit} within a tight band."
    else:
        # Fallback mixed state
        label = "Mixed"
        strong = False
        passed = None
        summary = f"Quarterly signals are mixed{period_bit}; weigh YoY and QoQ separately."

    return {
        "available": True,
        "pass": passed,
        "strong": strong,
        "label": label,
        "summary": summary,
        "metrics": metrics,
        "quarters": _build_quarter_rows(
            revenue=rev_hist,
            operating=op_hist,
            net_profit=pat_hist,
        ),
        "reasons": reasons,
        "thresholds": asdict(thr),
    }
