from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...db.store import TimelineStore

from .scoring import FUNDAMENTAL_SCORE_BONUS

MIN_ROE = 15.0
MIN_ROCE = 12.0

NIFTY_PCR_BULLISH = 0.75
NIFTY_PCR_BEARISH = 1.25
STOCK_PCR_BULLISH = 0.85
STOCK_PCR_BEARISH = 1.15

FII_NET_BONUS = 2.0
FII_NET_PENALTY = -2.0


def _parse_ratio_value(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1].strip()
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


def _extract_ratio(key_ratios: Any, names: tuple[str, ...]) -> float | None:
    aliases = {name.lower() for name in names}
    for item in _ratio_items(key_ratios):
        label = str(item.get("name") or item.get("ratio_name") or "").strip().lower()
        if label not in aliases:
            continue
        return _parse_ratio_value(item.get("company_value") or item.get("value"))
    return None


def evaluate_fundamental_gate(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return fundamental context; pass is None when ratios unavailable."""
    if not payload:
        return {
            "available": False,
            "pass": None,
            "roe": None,
            "roce": None,
            "thresholds": {"roe_min": MIN_ROE, "roce_min": MIN_ROCE},
            "checks": {},
        }

    key_ratios = payload.get("key_ratios")
    roe = _extract_ratio(key_ratios, ("roe",))
    roce = _extract_ratio(key_ratios, ("roce",))

    checks: dict[str, bool] = {}
    if roe is not None:
        checks["roe"] = roe >= MIN_ROE
    if roce is not None:
        checks["roce"] = roce >= MIN_ROCE

    if not checks:
        gate_pass: bool | None = None
    else:
        gate_pass = all(checks.values())

    return {
        "available": True,
        "pass": gate_pass,
        "roe": roe,
        "roce": roce,
        "thresholds": {"roe_min": MIN_ROE, "roce_min": MIN_ROCE},
        "checks": checks,
    }


@dataclass
class MarketContext:
    nifty_pcr: float | None
    fii_net_cash: float | None
    stock_pcr: dict[str, float]
    derivatives: dict[str, dict[str, Any]]


def load_market_context(store: TimelineStore, trade_date: str) -> MarketContext:
    pcr_map = store.list_derivative_pcr_for_date(trade_date)
    return MarketContext(
        nifty_pcr=pcr_map.get("NIFTY"),
        fii_net_cash=store.get_latest_fii_cash_net(trade_date),
        stock_pcr=pcr_map,
        derivatives=store.load_derivative_metrics_for_date(trade_date),
    )


def compute_market_score_delta(market: MarketContext, ticker: str) -> tuple[float, dict[str, Any]]:
    delta = 0.0
    details: dict[str, Any] = {"available": False}

    if market.nifty_pcr is not None:
        details["available"] = True
        details["nifty_pcr"] = round(market.nifty_pcr, 4)
        if market.nifty_pcr < NIFTY_PCR_BULLISH:
            delta += 2.0
        elif market.nifty_pcr > NIFTY_PCR_BEARISH:
            delta -= 3.0

    if market.fii_net_cash is not None:
        details["available"] = True
        details["fii_net_cash"] = round(market.fii_net_cash, 2)
        if market.fii_net_cash > 0:
            delta += FII_NET_BONUS
        elif market.fii_net_cash < 0:
            delta += FII_NET_PENALTY

    stock_pcr = market.stock_pcr.get(ticker.upper())
    if stock_pcr is not None:
        details["available"] = True
        details["stock_pcr"] = round(stock_pcr, 4)
        if stock_pcr < STOCK_PCR_BULLISH:
            delta += 1.0
        elif stock_pcr > STOCK_PCR_BEARISH:
            delta -= 1.0

    details["score_delta"] = round(delta, 1)
    return delta, details


def compute_context_adjustment(
    fundamental: dict[str, Any],
    market_delta: float,
) -> float:
    """Market + fundamental overlay; kept separate from OHLCV pattern score."""
    bonus = FUNDAMENTAL_SCORE_BONUS if fundamental.get("pass") is True else 0.0
    return round(market_delta + bonus, 1)


def adjust_pattern_score(
    base_score: float,
    fundamental: dict[str, Any],
    market_delta: float,
) -> float:
    """Legacy composite score (pattern + overlays). Prefer pattern-only score in engine."""
    adjustment = compute_context_adjustment(fundamental, market_delta)
    return round(min(100.0, max(0.0, base_score + adjustment)), 1)
