from __future__ import annotations

import os
from pathlib import Path

from ...config import ROOT_DIR


def telegram_api_id() -> int | None:
    raw = os.getenv("TELEGRAM_API_ID", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def telegram_api_hash() -> str | None:
    value = os.getenv("TELEGRAM_API_HASH", "").strip()
    return value or None


def telegram_session_path() -> Path:
    raw = os.getenv("TELEGRAM_SESSION_PATH", "data/telegram_news.session").strip()
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    # Telethon appends .session itself if you pass path without suffix handling;
    # pass stem path without forcing .session twice.
    if path.suffix == ".session":
        return path.with_suffix("")
    return path


def telegram_channels() -> list[str]:
    raw = os.getenv("TELEGRAM_CHANNELS", "@indiaredboxglobal").strip()
    channels: list[str] = []
    for part in raw.split(","):
        key = part.strip()
        if not key:
            continue
        if not key.startswith("@") and not key.lstrip("-").isdigit():
            key = f"@{key}"
        channels.append(key)
    return channels or ["@indiaredboxglobal"]


def gemini_api_key() -> str | None:
    value = os.getenv("GEMINI_API_KEY", "").strip()
    return value or None


def gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite"


def normalize_channel_key(channel: str) -> str:
    key = channel.strip()
    if key.startswith("https://t.me/"):
        key = key.rstrip("/").split("/")[-1]
    if not key.startswith("@") and not key.lstrip("-").isdigit():
        key = f"@{key}"
    return key
