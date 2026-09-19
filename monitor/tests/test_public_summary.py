from __future__ import annotations

import logging
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from monitor.api.routes import build_router
from monitor.cache.memory import MemoryCache
from monitor.collector.scheduler import MonitorCollector
from monitor.tests.test_scheduler import SpyCache, SpySources, build_settings


PUBLIC_TOP_LEVEL_KEYS = {
    "generated_at",
    "stale",
    "height",
    "hashrate_hps",
    "hashrate_display",
    "difficulty",
    "peer_count",
    "avg_block_time_8m",
    "last_block_age_seconds",
    "masternode_enabled",
    "masternode_total",
    "services",
    "freshness",
}


class StubCollector:
    def get_public_summary_payload(self) -> dict:
        return {
            "generated_at": "2026-09-20T00:00:00+00:00",
            "stale": False,
            "height": 5000000,
            "hashrate_hps": 123456789.0,
            "hashrate_display": "123.46 MH/s",
            "difficulty": 1234.5,
            "peer_count": 8,
            "avg_block_time_8m": 20.5,
            "last_block_age_seconds": 9,
            "masternode_enabled": 42,
            "masternode_total": 45,
            "services": {
                "overall_status": "ok",
                "ok_count": 6,
                "degraded_count": 0,
                "down_count": 0,
                "mining_pool_total": 4,
                "mining_pool_up": 4,
                "mining_pool_degraded": 0,
                "mining_pool_down": 0,
            },
            "freshness": {
                "snapshot_age_seconds": 3,
                "snapshot_status": "normal",
                "last_block_status": "normal",
                "overall_status": "normal",
            },
        }


class PublicSummaryRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(build_router(StubCollector()))
        self.client = TestClient(app)

    def test_allowed_site_origin_receives_cors_and_cache_headers(self):
        response = self.client.get(
            "/api/public-summary",
            headers={"Origin": "https://pepepow.net"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "https://pepepow.net",
        )
        self.assertEqual(response.headers.get("vary"), "Origin")
        self.assertIn("max-age=10", response.headers.get("cache-control", ""))
        self.assertEqual(set(response.json()), PUBLIC_TOP_LEVEL_KEYS)

    def test_unapproved_origin_is_not_granted_cors(self):
        response = self.client.get(
            "/api/public-summary",
            headers={"Origin": "https://example.com"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("access-control-allow-origin", response.headers)


class PublicSummaryCollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_summary_is_allowlisted_and_cache_only(self):
        cache = SpyCache()
        sources = SpySources()
        collector = MonitorCollector(
            build_settings(),
            cache,
            sources,
            logger=logging.getLogger("test"),
        )

        await collector.refresh_once()
        cache.get_calls.clear()
        source_calls_before = dict(sources.calls)

        payload = collector.get_public_summary_payload()

        self.assertEqual(set(payload), PUBLIC_TOP_LEVEL_KEYS)
        self.assertEqual(cache.get_calls, ["monitor:latest"])
        self.assertEqual(source_calls_before, sources.calls)
        self.assertNotIn("local_hash", payload)
        self.assertNotIn("alerts", payload)
        self.assertNotIn("peers", payload)
        self.assertNotIn("masternode_versions", payload)


if __name__ == "__main__":
    unittest.main()
