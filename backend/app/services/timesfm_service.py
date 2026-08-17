"""Backward-compatible re-export — prefer forecast_registry."""

from .forecast_types import ForecastResult
from .timesfm_25_service import run_forecast

__all__ = ["ForecastResult", "run_forecast"]
