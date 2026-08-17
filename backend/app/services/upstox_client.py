from __future__ import annotations

import asyncio
import os
from datetime import date, datetime
from typing import Any

import upstox_client
from upstox_client.rest import ApiException

from ..config import UPSTOX_BASE, get_access_token

_api_cache: dict[str, upstox_client.HistoryV3Api] = {}
_fundamentals_api_cache: dict[str, upstox_client.FundamentalsApi] = {}
_market_api_cache: dict[str, upstox_client.MarketApi] = {}
_options_api_cache: dict[str, upstox_client.OptionsApi] = {}


def _use_sandbox() -> bool:
    return os.getenv("UPSTOX_SANDBOX", "").strip().lower() in ("1", "true", "yes")


def _create_configuration(access_token: str) -> upstox_client.Configuration:
    configuration = upstox_client.Configuration(sandbox=_use_sandbox())
    configuration.access_token = access_token
    configuration.host = UPSTOX_BASE
    return configuration


def _get_history_api(access_token: str | None) -> upstox_client.HistoryV3Api:
    token = get_access_token(access_token)
    if not token:
        raise RuntimeError("UPSTOX_ACCESS_TOKEN not configured")

    if token not in _api_cache:
        api_client = upstox_client.ApiClient(_create_configuration(token))
        _api_cache[token] = upstox_client.HistoryV3Api(api_client)
    return _api_cache[token]


def _get_options_api(access_token: str | None) -> upstox_client.OptionsApi:
    token = get_access_token(access_token)
    if not token:
        raise RuntimeError("UPSTOX_ACCESS_TOKEN not configured")

    if token not in _options_api_cache:
        api_client = upstox_client.ApiClient(_create_configuration(token))
        _options_api_cache[token] = upstox_client.OptionsApi(api_client)
    return _options_api_cache[token]


def _get_market_api(access_token: str | None) -> upstox_client.MarketApi:
    token = get_access_token(access_token)
    if not token:
        raise RuntimeError("UPSTOX_ACCESS_TOKEN not configured")

    if token not in _market_api_cache:
        api_client = upstox_client.ApiClient(_create_configuration(token))
        _market_api_cache[token] = upstox_client.MarketApi(api_client)
    return _market_api_cache[token]


def _call_market_api(api_method, access_token: str | None, *args, **kwargs) -> dict[str, Any]:
    market_api = _get_market_api(access_token)
    try:
        response = api_method(market_api, *args, **kwargs)
    except ApiException as exc:
        status = getattr(exc, "status", None) or "unknown"
        body = getattr(exc, "body", None) or str(exc)
        body_text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)
        raise RuntimeError(f"Upstox API error [{status}]: {body_text}") from exc
    return _sdk_to_dict(response)


def _call_options_api(api_method, access_token: str | None, *args, **kwargs) -> dict[str, Any]:
    options_api = _get_options_api(access_token)
    try:
        response = api_method(options_api, *args, **kwargs)
    except ApiException as exc:
        status = getattr(exc, "status", None) or "unknown"
        body = getattr(exc, "body", None) or str(exc)
        body_text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)
        raise RuntimeError(f"Upstox API error [{status}]: {body_text}") from exc
    return _sdk_to_dict(response)


def _get_fundamentals_api(access_token: str | None) -> upstox_client.FundamentalsApi:
    token = get_access_token(access_token)
    if not token:
        raise RuntimeError("UPSTOX_ACCESS_TOKEN not configured")

    if token not in _fundamentals_api_cache:
        api_client = upstox_client.ApiClient(_create_configuration(token))
        _fundamentals_api_cache[token] = upstox_client.FundamentalsApi(api_client)
    return _fundamentals_api_cache[token]


def _call_fundamentals_api(
    api_method,
    access_token: str | None,
    *args,
    **kwargs,
) -> dict[str, Any]:
    fundamentals_api = _get_fundamentals_api(access_token)
    try:
        response = api_method(fundamentals_api, *args, **kwargs)
    except ApiException as exc:
        status = getattr(exc, "status", None) or "unknown"
        body = getattr(exc, "body", None) or str(exc)
        body_text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)
        raise RuntimeError(f"Upstox API error [{status}]: {body_text}") from exc
    return _sdk_to_dict(response)


def _get_company_profile_sync(access_token: str | None, isin: str) -> dict[str, Any]:
    return _call_fundamentals_api(
        lambda api, i: api.get_company_profile(i),
        access_token,
        isin,
    )


def _get_key_ratios_sync(access_token: str | None, isin: str) -> dict[str, Any]:
    return _call_fundamentals_api(
        lambda api, i: api.get_key_ratios(i),
        access_token,
        isin,
    )


def _get_share_holdings_sync(access_token: str | None, isin: str) -> dict[str, Any]:
    return _call_fundamentals_api(
        lambda api, i: api.get_share_holdings(i),
        access_token,
        isin,
    )


def _get_balance_sheet_sync(
    access_token: str | None,
    isin: str,
    *,
    type: str = "consolidated",
    fs: bool = True,
) -> dict[str, Any]:
    return _call_fundamentals_api(
        lambda api, i, **kw: api.get_balance_sheet(i, **kw),
        access_token,
        isin,
        type=type,
        fs=fs,
    )


def _get_cash_flow_sync(
    access_token: str | None,
    isin: str,
    *,
    type: str = "consolidated",
    fs: bool = True,
) -> dict[str, Any]:
    return _call_fundamentals_api(
        lambda api, i, **kw: api.get_cash_flow(i, **kw),
        access_token,
        isin,
        type=type,
        fs=fs,
    )


def _get_income_statement_sync(
    access_token: str | None,
    isin: str,
    *,
    type: str = "consolidated",
    time_period: str = "yearly",
    fs: bool = True,
) -> dict[str, Any]:
    return _call_fundamentals_api(
        lambda api, i, **kw: api.get_income_statement(i, **kw),
        access_token,
        isin,
        type=type,
        time_period=time_period,
        fs=fs,
    )


def _get_corporate_actions_sync(access_token: str | None, isin: str) -> dict[str, Any]:
    return _call_fundamentals_api(
        lambda api, i: api.get_corporate_actions(i),
        access_token,
        isin,
    )


def _get_competitors_sync(access_token: str | None, instrument_key: str) -> dict[str, Any]:
    return _call_fundamentals_api(
        lambda api, ik: api.get_competitors(ik),
        access_token,
        instrument_key,
    )


async def get_company_profile(access_token: str | None, isin: str) -> dict[str, Any]:
    return await asyncio.to_thread(_get_company_profile_sync, access_token, isin)


async def get_key_ratios(access_token: str | None, isin: str) -> dict[str, Any]:
    return await asyncio.to_thread(_get_key_ratios_sync, access_token, isin)


async def get_share_holdings(access_token: str | None, isin: str) -> dict[str, Any]:
    return await asyncio.to_thread(_get_share_holdings_sync, access_token, isin)


async def get_balance_sheet(access_token: str | None, isin: str) -> dict[str, Any]:
    return await asyncio.to_thread(_get_balance_sheet_sync, access_token, isin)


async def get_cash_flow(access_token: str | None, isin: str) -> dict[str, Any]:
    return await asyncio.to_thread(_get_cash_flow_sync, access_token, isin)


async def get_income_statement(access_token: str | None, isin: str) -> dict[str, Any]:
    return await asyncio.to_thread(_get_income_statement_sync, access_token, isin)


async def get_corporate_actions(access_token: str | None, isin: str) -> dict[str, Any]:
    return await asyncio.to_thread(_get_corporate_actions_sync, access_token, isin)


async def get_competitors(access_token: str | None, instrument_key: str) -> dict[str, Any]:
    return await asyncio.to_thread(_get_competitors_sync, access_token, instrument_key)


def _sdk_to_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, list):
        return [_sdk_to_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {key: _sdk_to_dict(value) for key, value in obj.items()}
    if hasattr(obj, "to_dict"):
        return _sdk_to_dict(obj.to_dict())
    return obj


def _get_historical_candles_sync(
    access_token: str | None,
    instrument_key: str,
    unit: str,
    interval: str,
    to_date: str,
    from_date: str,
) -> dict[str, Any]:
    history_api = _get_history_api(access_token)
    try:
        response = history_api.get_historical_candle_data1(
            instrument_key,
            unit,
            interval,
            to_date,
            from_date,
        )
    except ApiException as exc:
        status = getattr(exc, "status", None) or "unknown"
        body = getattr(exc, "body", None) or str(exc)
        body_text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)
        raise RuntimeError(f"Upstox API error [{status}]: {body_text}") from exc
    return _sdk_to_dict(response)


async def get_historical_candles(
    access_token: str | None,
    instrument_key: str,
    unit: str,
    interval: str,
    to_date: str,
    from_date: str,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _get_historical_candles_sync,
        access_token,
        instrument_key,
        unit,
        interval,
        to_date,
        from_date,
    )


def _get_fii_data_sync(
    access_token: str | None,
    data_type: str,
    interval: str,
    from_date: str | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if from_date:
        kwargs["_from"] = from_date
    return _call_market_api(
        lambda api, dt, iv, **kw: api.get_fii_data(dt, iv, **kw),
        access_token,
        data_type,
        interval,
        **kwargs,
    )


def _get_dii_data_sync(
    access_token: str | None,
    data_type: str,
    interval: str,
    from_date: str | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if from_date:
        kwargs["_from"] = from_date
    return _call_market_api(
        lambda api, dt, iv, **kw: api.get_dii_data(dt, iv, **kw),
        access_token,
        data_type,
        interval,
        **kwargs,
    )


def _get_oi_data_sync(
    access_token: str | None,
    instrument_key: str,
    expiry: str,
    trade_date: str,
) -> dict[str, Any]:
    return _call_market_api(
        lambda api, ik, ex, td: api.get_oi_data(ik, ex, td),
        access_token,
        instrument_key,
        expiry,
        trade_date,
    )


def _get_change_oi_data_sync(
    access_token: str | None,
    instrument_key: str,
    expiry: str,
    trade_date: str,
    interval: str,
) -> dict[str, Any]:
    return _call_market_api(
        lambda api, ik, ex, td, iv: api.get_change_oi_data(ik, ex, td, iv),
        access_token,
        instrument_key,
        expiry,
        trade_date,
        interval,
    )


def _get_pcr_data_sync(
    access_token: str | None,
    instrument_key: str,
    expiry: str,
    trade_date: str,
    bucket_interval: int,
) -> dict[str, Any]:
    return _call_market_api(
        lambda api, ik, ex, td, bi: api.get_pcr_data(ik, ex, td, bi),
        access_token,
        instrument_key,
        expiry,
        trade_date,
        bucket_interval,
    )


def _get_max_pain_data_sync(
    access_token: str | None,
    instrument_key: str,
    expiry: str,
    trade_date: str,
    bucket_interval: int,
) -> dict[str, Any]:
    return _call_market_api(
        lambda api, ik, ex, td, bi: api.get_max_pain_data(ik, ex, td, bi),
        access_token,
        instrument_key,
        expiry,
        trade_date,
        bucket_interval,
    )


async def get_fii_data(
    access_token: str | None,
    data_type: str,
    interval: str,
    from_date: str | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _get_fii_data_sync, access_token, data_type, interval, from_date
    )


async def get_dii_data(
    access_token: str | None,
    data_type: str,
    interval: str,
    from_date: str | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _get_dii_data_sync, access_token, data_type, interval, from_date
    )


def _get_option_contracts_sync(
    access_token: str | None,
    instrument_key: str,
    expiry_date: str | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if expiry_date:
        kwargs["expiry_date"] = expiry_date
    return _call_options_api(
        lambda api, ik, **kw: api.get_option_contracts(ik, **kw),
        access_token,
        instrument_key,
        **kwargs,
    )


async def get_option_contracts(
    access_token: str | None,
    instrument_key: str,
    expiry_date: str | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _get_option_contracts_sync, access_token, instrument_key, expiry_date
    )


def extract_option_expiries(payload: dict[str, Any]) -> list[str]:
    """Collect unique ISO expiries from an Upstox option-contracts response."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if data is None and isinstance(payload, dict):
        data = payload
    rows = data if isinstance(data, list) else []
    expiries: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("expiry") or row.get("expiry_date") or row.get("expiryDate")
        if not raw:
            continue
        text = str(raw).strip()
        if len(text) >= 10 and text[4] == "-" and text[7] == "-":
            expiries.add(text[:10])
            continue
        for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
            try:
                expiries.add(datetime.strptime(text, fmt).strftime("%Y-%m-%d"))
                break
            except ValueError:
                continue
    return sorted(expiries)


def pick_nearest_expiry(expiries: list[str], as_of: date) -> str | None:
    as_of_iso = as_of.isoformat()
    future = [exp for exp in expiries if exp >= as_of_iso]
    if future:
        return future[0]
    return expiries[-1] if expiries else None


async def resolve_nearest_option_expiry(
    access_token: str | None,
    instrument_key: str,
    as_of: date | None = None,
) -> str:
    """Fetch option contracts from Upstox and return the nearest expiry on/after as_of."""
    trade_day = as_of or date.today()
    contracts = await get_option_contracts(access_token, instrument_key)
    expiries = extract_option_expiries(contracts)
    expiry = pick_nearest_expiry(expiries, trade_day)
    if not expiry:
        raise RuntimeError(f"Upstox returned no option expiries for {instrument_key}")
    return expiry


async def get_oi_data(
    access_token: str | None,
    instrument_key: str,
    expiry: str,
    trade_date: str,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _get_oi_data_sync, access_token, instrument_key, expiry, trade_date
    )


async def get_change_oi_data(
    access_token: str | None,
    instrument_key: str,
    expiry: str,
    trade_date: str,
    interval: str,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _get_change_oi_data_sync,
        access_token,
        instrument_key,
        expiry,
        trade_date,
        interval,
    )


async def get_pcr_data(
    access_token: str | None,
    instrument_key: str,
    expiry: str,
    trade_date: str,
    bucket_interval: int,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _get_pcr_data_sync,
        access_token,
        instrument_key,
        expiry,
        trade_date,
        bucket_interval,
    )


async def get_max_pain_data(
    access_token: str | None,
    instrument_key: str,
    expiry: str,
    trade_date: str,
    bucket_interval: int,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _get_max_pain_data_sync,
        access_token,
        instrument_key,
        expiry,
        trade_date,
        bucket_interval,
    )


def _get_put_call_option_chain_sync(
    access_token: str | None,
    instrument_key: str,
    expiry_date: str,
) -> dict[str, Any]:
    options_api = _get_options_api(access_token)
    try:
        response = options_api.get_put_call_option_chain(instrument_key, expiry_date)
    except ApiException as exc:
        status = getattr(exc, "status", None) or "unknown"
        body = getattr(exc, "body", None) or str(exc)
        body_text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)
        raise RuntimeError(f"Upstox API error [{status}]: {body_text}") from exc
    return _sdk_to_dict(response)


async def get_put_call_option_chain(
    access_token: str | None,
    instrument_key: str,
    expiry_date: str,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _get_put_call_option_chain_sync,
        access_token,
        instrument_key,
        expiry_date,
    )
