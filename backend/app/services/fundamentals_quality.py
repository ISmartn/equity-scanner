"""Fundamentally-strong quality gate over cached Upstox fundamentals payloads."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

# Tunable baselines — keep in sync with frontend tooltip copy.
MIN_PAT_GROWTH_PCT = 0.0
MIN_OPM_PCT = 12.0
MIN_ROE_PCT = 15.0
MIN_ROCE_PCT = 15.0
MAX_DEBT_TO_EQUITY = 1.0
MIN_INTEREST_COVERAGE = 3.0  # applied only when computable (usually unavailable)
MIN_EPS = 0.0
MIN_CFO = 0.0

# Sectors where standard D/E is not a meaningful solvency proxy.
_DE_SKIP_SECTOR_FRAGMENTS = (
    "bank",
    "nbfc",
    "finance",
    "insurance",
    "housing finance",
    "stock broking",
    "investment",
)


@dataclass(frozen=True)
class FundamentalStrongThresholds:
    min_pat_growth_pct: float = MIN_PAT_GROWTH_PCT
    min_opm_pct: float = MIN_OPM_PCT
    min_roe_pct: float = MIN_ROE_PCT
    min_roce_pct: float = MIN_ROCE_PCT
    max_debt_to_equity: float = MAX_DEBT_TO_EQUITY
    min_interest_coverage: float = MIN_INTEREST_COVERAGE
    min_eps: float = MIN_EPS
    min_cfo: float = MIN_CFO


DEFAULT_STRONG_THRESHOLDS = FundamentalStrongThresholds()


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


def _ratio_items(key_ratios: Any) -> list[dict[str, Any]]:
    if isinstance(key_ratios, list):
        return [item for item in key_ratios if isinstance(item, dict)]
    if isinstance(key_ratios, dict):
        nested = key_ratios.get("ratios") or key_ratios.get("data")
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
    return []


def extract_ratio(key_ratios: Any, names: tuple[str, ...]) -> float | None:
    aliases = {name.lower() for name in names}
    for item in _ratio_items(key_ratios):
        label = str(item.get("name") or item.get("ratio_name") or "").strip().lower()
        if label not in aliases:
            continue
        return _parse_number(item.get("company_value") or item.get("value"))
    return None


def _unwrap_section(section: Any) -> Any:
    if isinstance(section, dict) and "data" in section:
        return section.get("data")
    return section


def _profile_sector(payload: dict[str, Any]) -> str | None:
    profile = _unwrap_section(payload.get("profile"))
    if not isinstance(profile, dict):
        return None
    sector = profile.get("sector")
    return sector.strip() if isinstance(sector, str) and sector.strip() else None


def _skip_debt_equity(sector: str | None) -> bool:
    if not sector:
        return False
    low = sector.lower()
    return any(frag in low for frag in _DE_SKIP_SECTOR_FRAGMENTS)


def _income_category_history(payload: dict[str, Any], category: str) -> list[dict[str, Any]]:
    income = payload.get("income_statement")
    if not isinstance(income, dict):
        return []
    for row in income.get("income_statement") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("category") or "").strip().lower() == category:
            hist = row.get("history")
            return [h for h in hist if isinstance(h, dict)] if isinstance(hist, list) else []
    return []


def _latest_history_value(history: list[dict[str, Any]]) -> float | None:
    if not history:
        return None
    return _parse_number(history[0].get("value"))


def _latest_history_change_pct(history: list[dict[str, Any]]) -> float | None:
    if not history:
        return None
    return _parse_number(history[0].get("change"))


def _full_statement_latest(section: Any, particulars: tuple[str, ...]) -> float | None:
    if not isinstance(section, dict):
        return None
    wanted = {p.lower() for p in particulars}
    for row in section.get("full_statement") or []:
        if not isinstance(row, dict):
            continue
        label = str(row.get("particular") or "").strip().lower()
        if label not in wanted:
            continue
        hist = row.get("history")
        if isinstance(hist, list) and hist and isinstance(hist[0], dict):
            return _parse_number(hist[0].get("value"))
    return None


def _cash_flow_operating(payload: dict[str, Any]) -> float | None:
    cf = payload.get("cash_flow")
    if not isinstance(cf, dict):
        return None
    for row in cf.get("cash_flow") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("category") or "").strip().lower() == "operating":
            hist = row.get("history")
            if isinstance(hist, list) and hist and isinstance(hist[0], dict):
                return _parse_number(hist[0].get("value"))
    return _full_statement_latest(cf, ("cash flow from operations", "cash flow from operation"))


def _debt_to_equity(payload: dict[str, Any]) -> float | None:
    """Approximate D/E from latest balance-sheet totals when explicit ratio is absent."""
    balance = payload.get("balance_sheet")
    if not isinstance(balance, dict):
        return None
    hist = balance.get("history")
    if not isinstance(hist, list) or not hist or not isinstance(hist[0], dict):
        return None
    assets = _parse_number(hist[0].get("total_asset"))
    liabilities = _parse_number(hist[0].get("total_liability"))
    if assets is None or liabilities is None:
        return None
    equity = assets - liabilities
    if equity <= 0:
        return None
    return liabilities / equity


def evaluate_fundamentally_strong(
    payload: dict[str, Any] | None,
    *,
    thresholds: FundamentalStrongThresholds = DEFAULT_STRONG_THRESHOLDS,
) -> dict[str, Any]:
    """
    Evaluate whether a company clears the fundamentally-strong baseline.

    Missing fields are skipped (not failed). ``pass`` is None when too little
    data exists to judge; True/False when at least one core check ran.
    """
    thr = thresholds
    empty = {
        "available": False,
        "pass": None,
        "strong": None,
        "label": "Insufficient data",
        "summary": (
            "No fundamentals payload available yet. Sync fundamentals for this ticker, "
            "then re-open the research view."
        ),
        "sector": None,
        "metrics": {},
        "checks": {},
        "reasons": [],
        "skipped": {},
        "thresholds": asdict(thr),
    }
    if not payload or not isinstance(payload, dict):
        return empty

    sector = _profile_sector(payload)
    key_ratios = payload.get("key_ratios")
    roe = extract_ratio(key_ratios, ("roe",))
    roce = extract_ratio(key_ratios, ("roce",))

    net_hist = _income_category_history(payload, "net_profit")
    rev_hist = _income_category_history(payload, "revenue")
    op_hist = _income_category_history(payload, "operating_profit")
    net_profit = _latest_history_value(net_hist)
    pat_growth = _latest_history_change_pct(net_hist)
    revenue = _latest_history_value(rev_hist)
    operating_profit = _latest_history_value(op_hist)
    opm = None
    if revenue is not None and revenue > 0 and operating_profit is not None:
        opm = (operating_profit / revenue) * 100.0

    income = payload.get("income_statement")
    eps = _full_statement_latest(income, ("eps - basic", "eps - diluted", "eps"))
    if eps is None and net_profit is not None:
        # Fallback: positive PAT stands in when EPS line is missing.
        eps = net_profit

    cfo = _cash_flow_operating(payload)
    debt_equity = _debt_to_equity(payload)
    interest_coverage = extract_ratio(
        key_ratios,
        ("interest coverage", "interest coverage ratio", "icr"),
    )

    metrics = {
        "roe": roe,
        "roce": roce,
        "pat_growth_pct": pat_growth,
        "net_profit": net_profit,
        "opm_pct": round(opm, 2) if opm is not None else None,
        "debt_to_equity": round(debt_equity, 3) if debt_equity is not None else None,
        "interest_coverage": interest_coverage,
        "eps": eps,
        "cfo": cfo,
    }

    checks: dict[str, bool] = {}
    skipped: dict[str, str] = {}
    reasons: list[dict[str, Any]] = []

    def _add_reason(
        check_id: str,
        *,
        ok: bool,
        title: str,
        message: str,
        actual: float | None = None,
        threshold: float | None = None,
        unit: str = "",
    ) -> None:
        checks[check_id] = ok
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

    # Profitability & growth
    if pat_growth is not None:
        ok = pat_growth > thr.min_pat_growth_pct
        if ok:
            msg = (
                f"Latest PAT grew {pat_growth:.1f}% YoY — earnings are expanding "
                f"(needs > {thr.min_pat_growth_pct:.0f}%)."
            )
        elif pat_growth == 0:
            msg = "Latest PAT was flat YoY — no earnings growth."
        else:
            msg = (
                f"Latest PAT fell {abs(pat_growth):.1f}% YoY — profits are shrinking "
                f"(needs growth above {thr.min_pat_growth_pct:.0f}%)."
            )
        _add_reason(
            "pat_growth",
            ok=ok,
            title="Profit growth (PAT)",
            message=msg,
            actual=round(pat_growth, 2),
            threshold=thr.min_pat_growth_pct,
            unit="%",
        )
    elif net_profit is not None:
        ok = net_profit > 0
        _add_reason(
            "pat_positive",
            ok=ok,
            title="Profitability (PAT)",
            message=(
                "Company reported a positive net profit in the latest period."
                if ok
                else "Latest net profit is negative — the business is loss-making on PAT."
            ),
            actual=round(net_profit, 2),
            threshold=0.0,
        )
    else:
        skipped["pat_growth"] = "unavailable"

    if opm is not None:
        ok = opm >= thr.min_opm_pct
        _add_reason(
            "opm",
            ok=ok,
            title="Operating margin",
            message=(
                f"Operating margin is {opm:.1f}% — healthy conversion of sales to operating profit "
                f"(baseline ≥ {thr.min_opm_pct:.0f}%)."
                if ok
                else (
                    f"Operating margin is only {opm:.1f}% — thin operating leverage "
                    f"(baseline ≥ {thr.min_opm_pct:.0f}%)."
                )
            ),
            actual=round(opm, 2),
            threshold=thr.min_opm_pct,
            unit="%",
        )
    else:
        skipped["opm"] = "unavailable"

    if roe is not None or roce is not None:
        roe_ok = roe is not None and roe >= thr.min_roe_pct
        roce_ok = roce is not None and roce >= thr.min_roce_pct
        ok = bool(roe_ok or roce_ok)
        bits: list[str] = []
        if roe is not None:
            bits.append(f"ROE {roe:.1f}%")
        if roce is not None:
            bits.append(f"ROCE {roce:.1f}%")
        metric_txt = " / ".join(bits)
        _add_reason(
            "roe_or_roce",
            ok=ok,
            title="Return on capital",
            message=(
                f"{metric_txt} clears the capital-efficiency bar "
                f"(need ROE ≥ {thr.min_roe_pct:.0f}% or ROCE ≥ {thr.min_roce_pct:.0f}%)."
                if ok
                else (
                    f"{metric_txt} is soft — capital is not earning enough "
                    f"(need ROE ≥ {thr.min_roe_pct:.0f}% or ROCE ≥ {thr.min_roce_pct:.0f}%)."
                )
            ),
            actual=roe if roe is not None else roce,
            threshold=thr.min_roe_pct,
            unit="%",
        )
    else:
        skipped["roe_or_roce"] = "unavailable"

    # Solvency
    if _skip_debt_equity(sector):
        skipped["debt_to_equity"] = f"skipped_for_sector:{sector}"
    elif debt_equity is not None:
        ok = debt_equity < thr.max_debt_to_equity
        _add_reason(
            "debt_to_equity",
            ok=ok,
            title="Leverage (D/E)",
            message=(
                f"Debt-to-equity is {debt_equity:.2f}x — balance sheet leverage looks contained "
                f"(baseline < {thr.max_debt_to_equity:.1f}x)."
                if ok
                else (
                    f"Debt-to-equity is {debt_equity:.2f}x — relatively leveraged "
                    f"(baseline < {thr.max_debt_to_equity:.1f}x)."
                )
            ),
            actual=round(debt_equity, 3),
            threshold=thr.max_debt_to_equity,
            unit="x",
        )
    else:
        skipped["debt_to_equity"] = "unavailable"

    if interest_coverage is not None:
        ok = interest_coverage > thr.min_interest_coverage
        _add_reason(
            "interest_coverage",
            ok=ok,
            title="Interest coverage",
            message=(
                f"Interest coverage is {interest_coverage:.1f}x — earnings comfortably cover interest "
                f"(baseline > {thr.min_interest_coverage:.0f}x)."
                if ok
                else (
                    f"Interest coverage is only {interest_coverage:.1f}x — debt servicing looks tight "
                    f"(baseline > {thr.min_interest_coverage:.0f}x)."
                )
            ),
            actual=round(interest_coverage, 2),
            threshold=thr.min_interest_coverage,
            unit="x",
        )
    else:
        skipped["interest_coverage"] = "unavailable"

    # Consistency
    if cfo is not None:
        ok = cfo > thr.min_cfo
        _add_reason(
            "cfo_positive",
            ok=ok,
            title="Operating cash flow",
            message=(
                "Operating cash flow is positive — profits are converting into cash."
                if ok
                else "Operating cash flow is negative — reported profits are not backed by cash generation."
            ),
            actual=round(cfo, 2),
            threshold=thr.min_cfo,
        )
    else:
        skipped["cfo_positive"] = "unavailable"

    if eps is not None:
        ok = eps > thr.min_eps
        _add_reason(
            "eps_positive",
            ok=ok,
            title="Earnings per share",
            message=(
                f"EPS is positive ({eps:.2f}) — shareholders have a profitable bottom line."
                if ok
                else f"EPS is {eps:.2f} — earnings per share are not positive."
            ),
            actual=round(eps, 2),
            threshold=thr.min_eps,
        )
    else:
        skipped["eps_positive"] = "unavailable"

    if not checks:
        gate_pass: bool | None = None
    else:
        gate_pass = all(checks.values())

    failed = [r for r in reasons if not r["ok"]]
    passed = [r for r in reasons if r["ok"]]
    if gate_pass is None:
        summary = (
            "Too few reported metrics to form a view. Sync fundamentals or pick a stock "
            "with fuller filings, then re-check."
        )
        label = "Insufficient data"
    elif gate_pass:
        summary = (
            f"Clears all {len(passed)} available quality checks spanning profitability, "
            "returns, cash generation, and leverage."
        )
        label = "Fundamentally strong"
    else:
        weak = ", ".join(r["title"] for r in failed[:3])
        if len(failed) > 3:
            weak += f" (+{len(failed) - 3} more)"
        lead = failed[0]["message"] if failed else "Key quality checks failed."
        summary = (
            f"Below the quality bar on {weak}. {lead}"
            + (
                f" Also watch: {failed[1]['title'].lower()}."
                if len(failed) > 1
                else ""
            )
        )
        label = "Weak fundamentals"

    return {
        "available": True,
        "pass": gate_pass,
        "strong": gate_pass,
        "label": label,
        "summary": summary,
        "sector": sector,
        "metrics": metrics,
        "checks": checks,
        "reasons": reasons,
        "skipped": skipped,
        "thresholds": asdict(thr),
    }


def list_fundamentally_strong_tickers(
    fundamentals_index: dict[str, dict[str, Any]],
    *,
    thresholds: FundamentalStrongThresholds = DEFAULT_STRONG_THRESHOLDS,
) -> list[str]:
    strong: list[str] = []
    for ticker, payload in fundamentals_index.items():
        result = evaluate_fundamentally_strong(payload, thresholds=thresholds)
        if result.get("strong") is True:
            strong.append(str(ticker).upper())
    return sorted(strong)
