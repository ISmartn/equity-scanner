"""Order Flow: the whole F&O market's futures and option chains, from the lab's Upstox feed."""

from __future__ import annotations

from .collector import OrderFlowCollector, load_universe
from .provider import UpstoxOrderFlowProvider

_collector: OrderFlowCollector | None = None


def get_collector() -> OrderFlowCollector:
    """The one collector for this process; the last file on disk is served until the first build."""
    global _collector
    if _collector is None:
        _collector = OrderFlowCollector(UpstoxOrderFlowProvider(), load_universe())
        _collector.load_from_disk()
    return _collector


__all__ = ["OrderFlowCollector", "UpstoxOrderFlowProvider", "get_collector", "load_universe"]
