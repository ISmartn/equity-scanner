from __future__ import annotations

import time
from typing import Any

_cache: dict[str, tuple[Any, float]] = {}


def get_cached(key: str) -> Any | None:
    entry = _cache.get(key)
    if not entry:
        return None
    value, expires_at = entry
    if time.time() > expires_at:
        _cache.pop(key, None)
        return None
    return value


def set_cache(key: str, value: Any, ttl_seconds: float) -> None:
    _cache[key] = (value, time.time() + ttl_seconds)


def delete_cache(key: str) -> None:
    _cache.pop(key, None)


def delete_cache_prefix(prefix: str) -> None:
    for key in list(_cache.keys()):
        if key.startswith(prefix):
            _cache.pop(key, None)
