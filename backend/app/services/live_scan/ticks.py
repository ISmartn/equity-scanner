"""Per-instrument tick hygiene: spike quarantine and VWAP sanity.

A print that jumps further than the band from the last accepted price is held
back. It is accepted only when the next print confirms it (lands near it);
if the next print reverts toward the old price, the spike is discarded. Real
gaps on news confirm within a tick or two. Bad prints never touch the day
high, the breakout latches, or the journal.
"""

from __future__ import annotations

DEFAULT_BAND = 0.03
MIN_BAND = 0.015
MAX_BAND = 0.08
_ATR_BAND_MULT = 0.6
_ATP_TOLERANCE = 0.005


def spike_band(atr_pct: float | None) -> float:
    """Largest tick-to-tick move accepted without confirmation, as a fraction."""
    if atr_pct is None or atr_pct <= 0:
        return DEFAULT_BAND
    return min(MAX_BAND, max(MIN_BAND, _ATR_BAND_MULT * atr_pct / 100.0))


class TickGuard:
    __slots__ = ("band", "confirm", "_pending", "_hits", "rejected", "confirmed_jumps")

    def __init__(self, band: float = DEFAULT_BAND, confirm: int = 2) -> None:
        self.band = band
        self.confirm = max(1, confirm)
        self._pending: float | None = None
        self._hits = 0
        self.rejected = 0
        self.confirmed_jumps = 0

    @property
    def pending(self) -> float | None:
        return self._pending

    def reset(self) -> None:
        self._pending = None
        self._hits = 0

    def check(self, reference: float | None, price: float) -> bool:
        """True when ``price`` may replace ``reference`` as the accepted last price."""
        if reference is None or reference <= 0:
            self._pending = None
            return True
        if abs(price / reference - 1.0) <= self.band:
            if self._pending is not None:
                self.rejected += 1
                self._pending = None
                self._hits = 0
            return True
        pending = self._pending
        if pending is not None and abs(price / pending - 1.0) <= self.band * 0.5:
            self._hits += 1
            if self._hits >= self.confirm:
                self._pending = None
                self._hits = 0
                self.confirmed_jumps += 1
                return True
            self._pending = price
            return False
        if pending is not None:
            self.rejected += 1
        self._pending = price
        self._hits = 1
        if self.confirm <= 1:
            self._pending = None
            self._hits = 0
            self.confirmed_jumps += 1
            return True
        return False


def sane_atp(atp: float, day_low: float, day_high: float) -> bool:
    """The exchange VWAP must sit inside the day's range. Early-session ATP glitches do not."""
    if atp <= 0:
        return False
    if day_low <= 0 or day_high <= 0 or day_high < day_low:
        return True
    return day_low * (1.0 - _ATP_TOLERANCE) <= atp <= day_high * (1.0 + _ATP_TOLERANCE)
