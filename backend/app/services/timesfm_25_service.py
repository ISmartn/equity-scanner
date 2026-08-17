from __future__ import annotations

import logging
import threading

import numpy as np

from .forecast_types import ForecastResult

logger = logging.getLogger(__name__)

_model_lock = threading.Lock()
_model = None
_model_config = None


def _ensure_model(max_horizon: int):
    global _model, _model_config

    import torch
    import timesfm

    torch.set_float32_matmul_precision("high")

    with _model_lock:
        if _model is not None and _model_config is not None and _model_config.max_horizon >= max_horizon:
            return _model

        config = timesfm.ForecastConfig(
            max_context=1024,
            max_horizon=max(max_horizon, 32),
            normalize_inputs=True,
            use_continuous_quantile_head=True,
        )
        logger.info("Loading TimesFM 2.5 on demand (google/timesfm-2.5-200m-pytorch)...")
        model = timesfm.TimesFM_2p5_200M_torch.from_pretrained("google/timesfm-2.5-200m-pytorch")
        model.compile(config)
        logger.info("TimesFM 2.5 model ready (loaded on first forecast request)")
        _model = model
        _model_config = config
        return _model


def is_model_loaded() -> bool:
    return _model is not None


def run_forecast(
    closes: np.ndarray,
    horizon: int,
    context_length: int | None = None,
) -> ForecastResult:
    import torch

    if len(closes) < 32:
        raise ValueError("TimesFM requires at least 32 historical points")

    window = context_length or min(len(closes), 512)
    context = np.asarray(closes[-window:], dtype=np.float64)

    model = _ensure_model(horizon)
    point_forecast, quantile_forecast = model.forecast(
        horizon=horizon,
        inputs=[context],
    )

    median = point_forecast[0].tolist()
    lower = quantile_forecast[0, :, 1].tolist()
    upper = quantile_forecast[0, :, 9].tolist()
    device = "cuda" if torch.cuda.is_available() else "cpu"

    return ForecastResult(
        median=median,
        lower=lower,
        upper=upper,
        context_length=len(context),
        horizon=horizon,
        device=device,
        model="timesfm-2.5",
        model_label="TimesFM 2.5 (Google zero-shot)",
    )
