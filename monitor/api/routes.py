from __future__ import annotations

from fastapi import APIRouter

from monitor.api.schemas import HealthModel, MasternodesPayloadModel, StatusModel


def build_router(collector) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["monitor"])

    @router.get("/status", response_model=StatusModel)
    async def get_status() -> dict:
        return collector.get_status_payload()

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
