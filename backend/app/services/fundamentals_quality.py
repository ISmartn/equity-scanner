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
        "sector": None,
        "metrics": {},
        "checks": {},
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

    # Profitability & growth
    if pat_growth is not None:
        checks["pat_growth"] = pat_growth > thr.min_pat_growth_pct
    elif net_profit is not None:
        checks["pat_positive"] = net_profit > 0
    else:
        skipped["pat_growth"] = "unavailable"

    if opm is not None:
        checks["opm"] = opm >= thr.min_opm_pct
    else:
        skipped["opm"] = "unavailable"

    if roe is not None or roce is not None:
        roe_ok = roe is not None and roe >= thr.min_roe_pct
        roce_ok = roce is not None and roce >= thr.min_roce_pct
        checks["roe_or_roce"] = bool(roe_ok or roce_ok)
    else:
        skipped["roe_or_roce"] = "unavailable"

    # Solvency
    if _skip_debt_equity(sector):
        skipped["debt_to_equity"] = f"skipped_for_sector:{sector}"
    elif debt_equity is not None:
        checks["debt_to_equity"] = debt_equity < thr.max_debt_to_equity
    else:
        skipped["debt_to_equity"] = "unavailable"

    if interest_coverage is not None:
        checks["interest_coverage"] = interest_coverage > thr.min_interest_coverage
    else:
        skipped["interest_coverage"] = "unavailable"

    # Consistency
    if cfo is not None:
        checks["cfo_positive"] = cfo > thr.min_cfo
    else:
        skipped["cfo_positive"] = "unavailable"

    if eps is not None:
        checks["eps_positive"] = eps > thr.min_eps
    else:
        skipped["eps_positive"] = "unavailable"

    if not checks:
        gate_pass: bool | None = None
    else:
        gate_pass = all(checks.values())

    return {
        "available": True,
        "pass": gate_pass,
        "strong": gate_pass,
        "sector": sector,
        "metrics": metrics,
        "checks": checks,
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
