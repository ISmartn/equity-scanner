from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ForecastModel = Literal["timesfm-2.5", "timesfm-fin"]


@dataclass
class ForecastResult:
    median: list[float]
    lower: list[float]
    upper: list[float]
    context_length: int
    horizon: int
    device: str
    model: str
    model_label: str
