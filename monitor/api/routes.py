from __future__ import annotations

import time

from fastapi import APIRouter

from monitor.api.schemas import HealthModel, MasternodesPayloadModel, StatusModel


_PRICE_CACHE_TTL_SECONDS = 600
_price_cache: dict[str, float | None] = {"value": None, "updated_at": 0.0}


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


def build_router(collector) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["monitor"])

    @router.get("/status", response_model=StatusModel)
    async def get_status() -> dict:
        payload = collector.get_status_payload()
        price = await _get_cached_price(collector)
        return _with_price(payload, price)

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
