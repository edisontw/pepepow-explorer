from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from fastapi import APIRouter

from monitor.api.schemas import HealthModel, MasternodesPayloadModel, StatusModel


_PRICE_CACHE_TTL_SECONDS = 600
_LIGHT_CACHE_TTL_SECONDS = 20
_price_cache: dict[str, float | None] = {"value": None, "updated_at": 0.0}
_light_cache: dict[str, Any] = {"value": None, "updated_at": 0.0}


async def _get_cached_price(collector) -> float | None:
    now = time.monotonic()
    if _price_cache["value"] is not None and now - float(_price_cache["updated_at"] or 0.0) < _PRICE_CACHE_TTL_SECONDS:
        return _price_cache["value"]
    try:
        price = await collector.sources.explorer_get_cached_price()
    except Exception:
        return _price_cache["value"]
    if price is not None:
        _price_cache["value"] = price
        _price_cache["updated_at"] = now
    return _price_cache["value"]


def _with_price(payload: dict, price: float | None) -> dict:
    reward = dict(payload.get("reward_estimate") or {})
    per_day = reward.get("per_day")
    per_month_coin = (float(per_day) * 30.0) if per_day is not None else None
    per_month_usdt = (per_month_coin * price) if per_month_coin is not None and price is not None else None
    reward["price_usdt"] = price
    reward["per_month_coin"] = per_month_coin
    reward["per_month_usdt"] = per_month_usdt
    payload = dict(payload)
    payload["price_usdt"] = price
    payload["reward_estimate"] = reward
    return payload


async def _probe_light_endpoint(client: httpx.AsyncClient, name: str, url: str, parse_json: bool = False) -> dict[str, Any]:
    started = time.perf_counter()
    checked_at = int(time.time())
    try:
        response = await client.get(url, follow_redirects=True)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        payload: Any = None
        if parse_json:
            try:
                payload = response.json()
            except ValueError:
                payload = {"raw": response.text[:500]}
        return {
            "name": name,
            "url": url,
            "ok": 200 <= response.status_code < 400,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "checked_at": checked_at,
            "data": payload,
            "error": None,
        }
    except Exception as exc:
        return {
            "name": name,
            "url": url,
            "ok": False,
            "status_code": None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "checked_at": checked_at,
            "data": None,
            "error": str(exc) or exc.__class__.__name__,
        }


async def _get_light_status() -> dict[str, Any]:
    now = time.monotonic()
    cached = _light_cache.get("value")
    if cached is not None and now - float(_light_cache.get("updated_at") or 0.0) < _LIGHT_CACHE_TTL_SECONDS:
        return cached

    timeout = httpx.Timeout(8.0, connect=3.0)
    headers = {"User-Agent": "PEPEPOWMonitor/1.0"}
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        service, wallet, api = await asyncio.gather(
            _probe_light_endpoint(client, "PEPEW Light", "https://light.pepepow.net/"),
            _probe_light_endpoint(client, "PEPEW Light Wallet", "https://light.pepepow.net/wallet/"),
            _probe_light_endpoint(client, "PEPEW Light API", "https://light.pepepow.net/api/status", parse_json=True),
        )

    result = {
        "overall_status": "ok" if all(item["ok"] for item in (service, wallet, api)) else "degraded",
        "checked_at": int(time.time()),
        "endpoints": [service, wallet, api],
        "api_status": api.get("data"),
    }
    _light_cache["value"] = result
    _light_cache["updated_at"] = now
    return result


def build_router(collector) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["monitor"])

    @router.get("/status", response_model=StatusModel)
    async def get_status() -> dict:
        payload = collector.get_status_payload()
        price = await _get_cached_price(collector)
        return _with_price(payload, price)

    @router.get("/light-status")
    async def get_light_status() -> dict:
        return await _get_light_status()

    @router.get("/masternodes", response_model=MasternodesPayloadModel)
    async def get_masternodes() -> dict:
        return collector.get_masternodes_payload()

    @router.get("/fork")
    async def get_fork() -> dict:
        return collector.get_fork_payload()

    @router.get("/hashrate")
    async def get_hashrate() -> dict:
        return collector.get_hashrate_payload()

    @router.get("/peers")
    async def get_peers() -> dict:
        return collector.get_peers_payload()

    @router.get("/blocks/recent")
    async def get_recent_blocks() -> dict:
        return collector.get_recent_blocks_payload()

    @router.get("/alerts")
    async def get_alerts() -> dict:
        return collector.get_alerts_payload()

    @router.get("/health", response_model=HealthModel)
    async def get_health() -> dict:
        return collector.get_health_payload()

    return router
