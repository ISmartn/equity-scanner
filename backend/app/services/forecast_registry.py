from __future__ import annotations

import os

import numpy as np

from .forecast_types import ForecastModel, ForecastResult
from . import timesfm_25_service, timesfm_fin_runner

MODEL_META: dict[str, dict[str, str | bool]] = {
    "timesfm-2.5": {
        "label": "TimesFM 2.5 (Google zero-shot)",
        "description": "Latest Google foundation model with quantile uncertainty bands.",
        "available": True,
    },
    "timesfm-fin": {
        "label": "TimesFM-Fin (PFN financial fine-tune)",
        "description": "TimesFM 1.0 fine-tuned on financial data via log-transform (Preferred Networks).",
        "available": timesfm_fin_runner.is_fin_available(),
    },
}


def normalize_model(value: str | None) -> ForecastModel:
    raw = (value or os.getenv("FORECAST_MODEL", "timesfm-2.5")).strip().lower()
    if raw in ("fin", "timesfm_fin", "timesfm-fin", "pfn"):
        return "timesfm-fin"
    if raw in ("2.5", "timesfm-2.5", "timesfm25", "google"):
        return "timesfm-2.5"
    raise ValueError(f"Unknown forecast model: {value}. Use timesfm-2.5 or timesfm-fin.")


def list_models() -> list[dict]:
    default = normalize_model(None)
    from . import timesfm_25_service

    items: list[dict] = []
    for model_id, meta in MODEL_META.items():
        loaded = model_id == "timesfm-2.5" and timesfm_25_service.is_model_loaded()
        items.append(
            {
                "id": model_id,
                "label": meta["label"],
                "description": meta["description"],
                "available": bool(meta["available"]),
                "default": model_id == default,
                "loaded": loaded,
            }
        )
    return items


async def run_forecast(
    model: ForecastModel,
    closes: np.ndarray,
    horizon: int,
    interval: str,
    context_length: int | None = None,
) -> ForecastResult:
    if model == "timesfm-fin":
        return await timesfm_fin_runner.run_forecast(closes, horizon, interval)
    return timesfm_25_service.run_forecast(closes, horizon, context_length)
