from __future__ import annotations

from telethon import TelegramClient

from .config import telegram_api_hash, telegram_api_id, telegram_session_path


def require_telegram_credentials() -> tuple[int, str]:
    api_id = telegram_api_id()
    api_hash = telegram_api_hash()
    if not api_id or not api_hash:
        raise RuntimeError(
            "Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env "
            "(create an app at https://my.telegram.org)."
        )
    return api_id, api_hash


def build_telegram_client() -> TelegramClient:
    api_id, api_hash = require_telegram_credentials()
    session = str(telegram_session_path())
    return TelegramClient(session, api_id, api_hash)
