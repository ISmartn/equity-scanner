"""Intraday volume U-curve.

NSE cash volume is heavy in the first minutes, thin at midday, and heavy into
the 15:00–15:30 closing-price window. A linear clock says 4% of the day has
traded at 09:30; in practice it is closer to 11%. Dividing session volume by a
linear clock therefore reads every morning as ~3x RVOL and every afternoon as
quiet. This module supplies the expected cumulative fraction and a per-minute
intensity (mean 1.0) for normalising one-minute bursts.

The default curve is ``a + b·e^(-t/τ1) + c·e^(-(T-t)/τ2)``. When enough full
sessions of persisted live minute bars exist, the empirical shape is blended
in with a shrinkage prior so one odd day cannot bend the curve.
"""

from __future__ import annotations

import math
from typing import Iterable

from datetime import datetime

from .clocks import IST, SESSION_MINUTES, is_muhurat_epoch, session_minute, session_progress

_BASE = 1.0
_OPEN_AMP = 4.0
_OPEN_TAU = 12.0
_CLOSE_AMP = 2.5
_CLOSE_TAU = 15.0
_MIN_COVERAGE = 0.9
_PRIOR_SESSIONS = 3.0
_SMOOTH = 2
_FLOOR_MINUTES = 2


def _default_weights() -> list[float]:
    last = SESSION_MINUTES - 1
    return [
        _BASE + _OPEN_AMP * math.exp(-t / _OPEN_TAU) + _CLOSE_AMP * math.exp(-(last - t) / _CLOSE_TAU)
        for t in range(SESSION_MINUTES)
    ]


def _smooth(values: list[float], radius: int) -> list[float]:
    if radius <= 0:
        return values
    out: list[float] = []
    n = len(values)
    for i in range(n):
        lo = max(0, i - radius)
        hi = min(n, i + radius + 1)
        out.append(sum(values[lo:hi]) / (hi - lo))
    return out


class VolumeProfile:
    __slots__ = ("shares", "cumulative", "intensity", "sessions")

    def __init__(self, weights: Iterable[float], sessions: int = 0) -> None:
        raw = [max(0.0, float(value)) for value in weights]
        if len(raw) != SESSION_MINUTES or sum(raw) <= 0:
            raw = _default_weights()
        total = sum(raw)
        self.shares = [value / total for value in raw]
        running = 0.0
        cumulative: list[float] = []
        for share in self.shares:
            running += share
            cumulative.append(running)
        self.cumulative = cumulative
        self.intensity = [share * SESSION_MINUTES for share in self.shares]
        self.sessions = sessions

    @classmethod
    def default(cls) -> "VolumeProfile":
        return cls(_default_weights())

    @classmethod
    def calibrated(cls, day_minutes: dict[str, dict[int, float]]) -> "VolumeProfile":
        """``day_minutes`` maps session date -> {session minute index: summed volume}."""
        prior = cls.default().shares
        empirical = [0.0] * SESSION_MINUTES
        used = 0
        for minutes in day_minutes.values():
            volumes = [float(minutes.get(i) or 0.0) for i in range(SESSION_MINUTES)]
            covered = sum(1 for volume in volumes if volume > 0)
            total = sum(volumes)
            if total <= 0 or covered < _MIN_COVERAGE * SESSION_MINUTES:
                continue
            for i, volume in enumerate(volumes):
                empirical[i] += volume / total
            used += 1
        if used == 0:
            return cls(prior)
        empirical = _smooth([value / used for value in empirical], _SMOOTH)
        blended = [
            (used * emp + _PRIOR_SESSIONS * pri) / (used + _PRIOR_SESSIONS)
            for emp, pri in zip(empirical, prior)
        ]
        return cls(blended, sessions=used)

    def expected_fraction(self, epoch: float) -> float:
        """Share of a normal day's volume expected to have traded by ``epoch``."""
        if is_muhurat_epoch(epoch):
            return session_progress(datetime.fromtimestamp(epoch, IST))
        minute = session_minute(epoch)
        floor = self.cumulative[_FLOOR_MINUTES - 1]
        if minute < 0:
            return floor
        if minute >= SESSION_MINUTES:
            return 1.0
        within = ((epoch % 60.0) / 60.0) * self.shares[minute]
        done = self.cumulative[minute - 1] if minute > 0 else 0.0
        return max(floor, min(1.0, done + within))

    def minute_intensity(self, minute: int) -> float:
        if 0 <= minute < SESSION_MINUTES:
            return self.intensity[minute]
        return 1.0
