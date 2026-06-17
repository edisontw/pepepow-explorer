from __future__ import annotations

import asyncio
import logging
import time
import unittest
from pathlib import Path
from typing import Any

from monitor.cache.memory import MemoryCache
from monitor.collector.scheduler import MonitorCollector
from monitor.config import MiningPoolTarget, Settings, SiteStatusTarget


class SpySources:
    def __init__(self) -> None:
        self.calls: dict[str, int] = {}
        self.height = 100
        self.hashrate = 12345.0
        self.peerinfo = [
            {"addr": "203.0.113.10:8833", "subver": "/PEPEPOW Core:2.9.0.2/", "version": 70521, "inbound": False},
        ]
        self.masternode_count = {"enabled": 1, "total": 4}
        self.masternode_list = [
            {
                "addr": "PEPEW123",
                "txhash": "ab" * 32,
                "status": "ENABLED",
                "lastseen": 1712345678,
                "activetime": 123456,
                "ip_address": "203.0.113.10:8833",
                "version": 70521,
                "subver": "/PEPEPOW Core:2.9.0.2/",
            },
            {
                "addr": "PEPEW456",
                "status": "EXPIRED",
                "lastseen": 1712345600,
                "ip_address": "203.0.113.11:8833",
                "version": 70520,
            },
        ]
        self.rpc_masternode_list = [
            {
                "raw": "NEW_START_REQUIRED 70521 PGNYGxh4iwJ6yewp9V3depPgd8uBXJn1Ay 1774983481 1318185 invalid_version expired 192.9.180.67:8833",
                "txhash": "cd" * 32 + "-1",
            },
            {
                "raw": "NEW_START_REQUIRED 70521 PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho 1774979701 811557 invalid_version expired 192.9.160.179:8833",
                "txhash": "ef" * 32 + "-1",
            },
        ]
        self.block_hashes = {
            99: "hash99",
            100: "hash100",
            101: "hash101",
            102: "hash102",
        }
        now = int(time.time())
        self.blocks = {
            "hash99": {"height": 99, "hash": "hash99", "previousblockhash": "hash98", "version": 1, "time": now - 180, "difficulty": 1.0},
            "hash100": {"height": 100, "hash": "hash100", "previousblockhash": "hash99", "version": 1, "time": now - 120, "difficulty": 1.0},
            "hash101": {"height": 101, "hash": "hash101", "previousblockhash": "hash100", "version": 1, "time": now - 60, "difficulty": 1.0},
            "hash102": {"height": 102, "hash": "hash102", "previousblockhash": "hash101", "version": 1, "time": now, "difficulty": 1.0},
        }
        self.delay_rpc_seconds = 0.0
        self.site_responses = {
            "https://pepepow.org": {"status_code": 200, "latency_ms": 120.0},
            "https://explorer.pepepow.org": {"status_code": 200, "latency_ms": 140.0},
            "https://explorer.pepepow.net": {"status_code": 200, "latency_ms": 160.0},
            "https://wallet.pepepow.net": {"status_code": 200, "latency_ms": 180.0},
        }
        self.mining_pool_responses = {
            "hoohash-pepew.eu.mine.zpool.ca:8335": {
                "tcp_connect_ok": True,
                "stratum_ok": True,
                "latency_ms": 80.0,
                "error": None,
            },
            "eu.mining4people.com:4176": {
                "tcp_connect_ok": True,
                "stratum_ok": True,
                "latency_ms": 95.0,
                "error": None,
            },
            "us-west.mining4people.com:4176": {
                "tcp_connect_ok": True,
                "stratum_ok": True,
                "latency_ms": 70.0,
                "error": None,
            },
            "stratum-eu.pepepow.foztor.net:13232": {
                "tcp_connect_ok": True,
                "stratum_ok": True,
                "latency_ms": 115.0,
                "error": None,
            },
        }

    async def close(self) -> None:
        return None

    async def rpc_get_blockcount(self) -> int:
        self.calls["rpc_get_blockcount"] = self.calls.get("rpc_get_blockcount", 0) + 1
        if self.delay_rpc_seconds:
            await asyncio.sleep(self.delay_rpc_seconds)
        return self.height

    async def explorer_get_blockcount(self) -> int:
        self.calls["explorer_get_blockcount"] = self.calls.get("explorer_get_blockcount", 0) + 1
        return self.height

    async def public_get_height(self) -> int:
        self.calls["public_get_height"] = self.calls.get("public_get_height", 0) + 1
        return self.height

    async def public_get_mempool(self) -> dict[str, int]:
        self.calls["public_get_mempool"] = self.calls.get("public_get_mempool", 0) + 1
        return {"size": 0, "bytes": 0}

    async def explorer_get_difficulty(self) -> float:
        self.calls["explorer_get_difficulty"] = self.calls.get("explorer_get_difficulty", 0) + 1
        return 1.0

    async def rpc_get_peerinfo(self) -> list[dict[str, object]]:
        self.calls["rpc_get_peerinfo"] = self.calls.get("rpc_get_peerinfo", 0) + 1
        return self.peerinfo

    async def rpc_get_networkhashps(self) -> float:
        self.calls["rpc_get_networkhashps"] = self.calls.get("rpc_get_networkhashps", 0) + 1
        return self.hashrate

    async def explorer_get_masternodecount(self) -> dict[str, int]:
        self.calls["explorer_get_masternodecount"] = self.calls.get("explorer_get_masternodecount", 0) + 1
        return self.masternode_count

    async def explorer_get_masternodelist(self) -> list[dict[str, object]]:
        self.calls["explorer_get_masternodelist"] = self.calls.get("explorer_get_masternodelist", 0) + 1
        return self.masternode_list

    async def rpc_get_masternodecount(self) -> dict[str, int]:
        self.calls["rpc_get_masternodecount"] = self.calls.get("rpc_get_masternodecount", 0) + 1
        return self.masternode_count

    async def rpc_get_masternodelist(self) -> list[dict[str, object]]:
        self.calls["rpc_get_masternodelist"] = self.calls.get("rpc_get_masternodelist", 0) + 1
        return self.rpc_masternode_list

    async def rpc_get_blockhash(self, height: int) -> str:
        self.calls["rpc_get_blockhash"] = self.calls.get("rpc_get_blockhash", 0) + 1
        return self.block_hashes[height]

    async def rpc_get_block(self, blockhash: str) -> dict[str, object]:
        self.calls["rpc_get_block"] = self.calls.get("rpc_get_block", 0) + 1
        return self.blocks[blockhash]

    async def comparison_get_state(self, source, local_height: int) -> dict[str, object]:
        self.calls["comparison_get_state"] = self.calls.get("comparison_get_state", 0) + 1
        return {"height": local_height, "hash": self.block_hashes.get(local_height)}

    async def check_site(self, url: str) -> dict[str, object]:
        self.calls["check_site"] = self.calls.get("check_site", 0) + 1
        payload = self.site_responses[url]
        if isinstance(payload, Exception):
            raise payload
        return payload

    async def check_mining_pool(self, host: str, port: int) -> dict[str, object]:
        self.calls["check_mining_pool"] = self.calls.get("check_mining_pool", 0) + 1
        payload = self.mining_pool_responses[f"{host}:{port}"]
        if isinstance(payload, Exception):
            raise payload
        return payload


class SpyCache(MemoryCache):
    def __init__(self) -> None:
        super().__init__()
        self.get_calls: list[str] = []
        self.set_calls: list[str] = []
        self.replace_calls: list[str] = []

    def get_json(self, key: str, default: Any = None) -> Any:
        self.get_calls.append(key)
        return super().get_json(key, default)

    def set_json(self, key: str, value: Any) -> None:
        self.set_calls.append(key)
        super().set_json(key, value)

    def replace_json_list(self, key: str, values: list[Any]) -> list[Any]:
        self.replace_calls.append(key)
        return super().replace_json_list(key, values)


def build_settings() -> Settings:
    return Settings(
        repo_root=Path("/tmp"),
        title="test",
        root_path="/monitor",
        rpc_url="http://127.0.0.1:12345",
        rpc_username=None,
        rpc_password=None,
        explorer_base_url="http://127.0.0.1:3001",
        public_api_base_url="https://api.pepepow.net",
        redis_url=None,
        poll_interval_seconds=1,
        rpc_timeout_seconds=2.0,
        request_connect_timeout_seconds=1.0,
        request_read_timeout_seconds=2.0,
        request_retries=0,
        request_retry_backoff_seconds=(0.25, 0.75),
        rpc_max_connections=2,
        rpc_max_keepalive_connections=1,
        rpc_failure_cooldown_seconds=60,
        rpc_fail_threshold=3,
        rpc_blockcount_poll_interval_seconds=15,
        masternode_interval_seconds=60,
        peerinfo_interval_seconds=180,
        hashrate_poll_interval_seconds=180,
        site_status_interval_seconds=3600,
        mining_pool_interval_seconds=90,
        block_fetch_concurrency=2,
        block_fetch_limit_per_cycle=4,
        block_history_cold_start_limit=2,
        recent_block_window=30,
        alert_window_blocks=120,
        block_target_seconds=60,
        rate_limit_rpm=60,
        fork_height=120,
        hoohash_bit=0x4000,
        xelis_bit=0x8000,
        min_upgraded_subver="2.9.0.2",
        target_version="2.9.0.2",
        masternode_count_rpc_method="masternode",
        masternode_count_rpc_params=("count", "all"),
        masternode_list_rpc_method="masternodelist",
        masternode_list_rpc_params=("info",),
        comparison_sources=[],
        site_status_targets=[
            SiteStatusTarget(name="pepepow.org", url="https://pepepow.org"),
            SiteStatusTarget(name="explorer.pepepow.org", url="https://explorer.pepepow.org"),
            SiteStatusTarget(name="explorer.pepepow.net", url="https://explorer.pepepow.net"),
            SiteStatusTarget(name="wallet.pepepow.net", url="https://wallet.pepepow.net"),
        ],
        mining_pool_targets=[
            MiningPoolTarget(host="hoohash-pepew.eu.mine.zpool.ca", port=8335, name="(zpool) stratum+tcp://hoohash-pepew.eu.mine.zpool.ca:8335"),
            MiningPoolTarget(host="eu.mining4people.com", port=4176, name="(M4P) eu.mining4people.com:4176"),
            MiningPoolTarget(host="us-west.mining4people.com", port=4176, name="(M4P) us-west.mining4people.com:4176"),
            MiningPoolTarget(host="stratum-eu.pepepow.foztor.net", port=13232, name="(foztor) stratum-eu.pepepow.foztor.net:13232"),
        ],
    )


class SchedulerGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_rpc_fail_threshold_enters_cooldown_on_third_failure(self):
        collector = MonitorCollector(build_settings(), MemoryCache(), SpySources(), logger=logging.getLogger("test"))

        collector._mark_source_failure("rpc_local", "rpc", "boom")
        collector._mark_source_failure("rpc_local", "rpc", "boom")
        self.assertTrue(collector._rpc_can_call("getblockcount"))

        collector._mark_source_failure("rpc_local", "rpc", "boom")
        collector._enter_rpc_cooldown("threshold")
        self.assertFalse(collector._rpc_can_call("getblockcount"))

    async def test_probe_only_recovery_requires_two_successes(self):
        collector = MonitorCollector(build_settings(), MemoryCache(), SpySources(), logger=logging.getLogger("test"))
        collector._probe_only_mode = True
        collector._rpc_cooldown_until = time.monotonic() - 1

        await collector._source_call("rpc_local", "rpc", collector.sources.rpc_get_blockcount, rpc_operation="getblockcount")
        self.assertTrue(collector._probe_only_mode)

        await collector._source_call("rpc_local", "rpc", collector.sources.rpc_get_blockcount, rpc_operation="getblockcount")
        self.assertFalse(collector._probe_only_mode)

    async def test_recent_blocks_append_only_and_evict(self):
        settings = build_settings()
        settings.recent_block_window = 2
        collector = MonitorCollector(settings, MemoryCache(), SpySources(), logger=logging.getLogger("test"))
        cached = [
            {"height": 100, "hash": "hash100", "time": 1050, "interval_from_prev": None},
            {"height": 101, "hash": "hash101", "time": 1110, "interval_from_prev": 60},
        ]

        refreshed = await collector._refresh_recent_blocks(102, cached)
        self.assertEqual([block["height"] for block in refreshed], [101, 102])

    async def test_recent_blocks_reorg_pops_conflicting_tail(self):
        sources = SpySources()
        sources.block_hashes[101] = "hash101b"
        sources.blocks["hash101b"] = {"height": 101, "hash": "hash101b", "previousblockhash": "hash100", "version": 1, "time": 1120, "difficulty": 1.0}
        collector = MonitorCollector(build_settings(), MemoryCache(), sources, logger=logging.getLogger("test"))
        cached = [
            {"height": 100, "hash": "hash100", "time": 1050, "interval_from_prev": None},
            {"height": 101, "hash": "stale101", "time": 1110, "interval_from_prev": 60},
        ]

        refreshed = await collector._refresh_recent_blocks(101, cached)
        self.assertEqual(refreshed[-1]["hash"], "hash101b")

    async def test_long_rpc_cycle_enters_cooldown(self):
        sources = SpySources()
        sources.delay_rpc_seconds = 0.8
        collector = MonitorCollector(build_settings(), MemoryCache(), sources, logger=logging.getLogger("test"))

        await collector.refresh_once()
        self.assertEqual(collector._rpc_status(), "cooldown")

    async def test_tier_b_not_polled_again_before_interval(self):
        collector = MonitorCollector(build_settings(), MemoryCache(), SpySources(), logger=logging.getLogger("test"))

        await collector.refresh_once()
        first_count = collector.sources.calls.get("explorer_get_masternodecount", 0)
        await collector.refresh_once()
        second_count = collector.sources.calls.get("explorer_get_masternodecount", 0)

        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 1)

    async def test_snapshot_uses_structured_masternode_versions(self):
        collector = MonitorCollector(build_settings(), MemoryCache(), SpySources(), logger=logging.getLogger("test"))

        await collector.refresh_once()
        snapshot = collector.get_status_payload()

        self.assertEqual(snapshot["masternode_upgraded_enabled"], 1)
        self.assertEqual(
            snapshot["masternode_versions"],
            [
                {
                    "protocol_version": 70521,
                    "display_version": "70521",
                    "semver": "2.9.0.2",
                    "count": 1,
                    "is_upgraded": True,
                }
            ],
        )

    async def test_status_payload_sanitizes_legacy_ip_like_semver_from_cached_snapshot(self):
        cache = MemoryCache()
        collector = MonitorCollector(build_settings(), cache, SpySources(), logger=logging.getLogger("test"))
        snapshot = collector._empty_snapshot()
        snapshot["generated_at"] = "2026-04-10T00:00:00+00:00"
        snapshot["generated_at_unix"] = int(time.time())
        snapshot["stale"] = False
        snapshot["masternode_versions"] = [
            {
                "protocol_version": 70520,
                "display_version": "70520",
                "semver": "1.34.236.202",
                "count": 31,
                "is_upgraded": None,
            }
        ]
        cache.set_json("monitor:latest", snapshot)

        payload = collector.get_status_payload()

        self.assertIsNone(payload["masternode_versions"][0]["semver"])

    async def test_get_masternodes_payload_returns_cached_normalized_items(self):
        collector = MonitorCollector(build_settings(), MemoryCache(), SpySources(), logger=logging.getLogger("test"))

        await collector.refresh_once()
        payload = collector.get_masternodes_payload()

        self.assertFalse(payload["stale"])
        self.assertIsNotNone(payload["list_generated_at"])
        self.assertEqual(
            payload["items"][0],
            {
                "addr": "PEPEW123",
                "txid": "ab" * 32,
                "ip": "203.0.113.10:8833",
                "status": "ENABLED",
                "lastseen": 1712345678,
                "activetime": 123456,
                "version": 70521,
                "subver": "/PEPEPOW Core:2.9.0.2/",
                "fallback_only": False,
            },
        )
        self.assertEqual(len(payload["items"]), 4)
        self.assertEqual(payload["items"][2]["addr"], "PGNYGxh4iwJ6yewp9V3depPgd8uBXJn1Ay")
        self.assertEqual(payload["items"][2]["status"], "NEW_START_REQUIRED")
        self.assertTrue(payload["items"][2]["fallback_only"])
        self.assertEqual(payload["items"][3]["addr"], "PKTwq3nHNxwcVgDX4QwVxQGX5DYjJB8nho")

    async def test_get_masternodes_payload_does_not_trigger_extra_source_calls(self):
        sources = SpySources()
        collector = MonitorCollector(build_settings(), MemoryCache(), sources, logger=logging.getLogger("test"))

        await collector.refresh_once()
        first_count = dict(sources.calls)
        collector.get_masternodes_payload()

        self.assertEqual(first_count, sources.calls)

    async def test_incomplete_explorer_list_triggers_rpc_merge(self):
        sources = SpySources()
        collector = MonitorCollector(build_settings(), MemoryCache(), sources, logger=logging.getLogger("test"))

        await collector.refresh_once()

        self.assertEqual(sources.calls.get("rpc_get_masternodelist", 0), 1)

    async def test_site_status_polled_once_and_reused_until_interval(self):
        settings = build_settings()
        settings.site_status_interval_seconds = 3600
        sources = SpySources()
        collector = MonitorCollector(settings, MemoryCache(), sources, logger=logging.getLogger("test"))

        await collector.refresh_once()
        first_count = sources.calls.get("check_site", 0)
        first_snapshot = collector.get_status_payload()

        await collector.refresh_once()
        second_count = sources.calls.get("check_site", 0)
        second_snapshot = collector.get_status_payload()

        self.assertEqual(first_count, 4)
        self.assertEqual(second_count, 4)
        self.assertEqual(len(first_snapshot["services"]["public_sites"]), 4)
        self.assertEqual(first_snapshot["services"]["public_sites"], second_snapshot["services"]["public_sites"])

    async def test_mining_pool_status_populates_summary_and_items(self):
        collector = MonitorCollector(build_settings(), MemoryCache(), SpySources(), logger=logging.getLogger("test"))

        await collector.refresh_once()
        snapshot = collector.get_status_payload()

        self.assertEqual(snapshot["services"]["mining_pool_summary"]["total_pools"], 4)
        self.assertEqual(snapshot["services"]["mining_pool_summary"]["reachable_pools"], 4)
        self.assertEqual(snapshot["services"]["mining_pool_summary"]["healthy_stratum_pools"], 4)
        self.assertEqual(snapshot["services"]["mining_pool_summary"]["up_count"], 4)
        self.assertEqual(len(snapshot["services"]["mining_pools"]), 4)
        self.assertEqual(snapshot["services"]["mining_pools"][0]["endpoint"], "(M4P) eu.mining4people.com:4176")
        self.assertIsNotNone(snapshot["services"]["mining_pools"][0]["checked_at"])

    async def test_mining_pool_status_reused_until_interval(self):
        settings = build_settings()
        sources = SpySources()
        collector = MonitorCollector(settings, MemoryCache(), sources, logger=logging.getLogger("test"))

        await collector.refresh_once()
        first_count = sources.calls.get("check_mining_pool", 0)
        first_snapshot = collector.get_status_payload()

        await collector.refresh_once()
        second_count = sources.calls.get("check_mining_pool", 0)
        second_snapshot = collector.get_status_payload()

        self.assertEqual(first_count, 4)
        self.assertEqual(second_count, 4)
        self.assertEqual(first_snapshot["services"]["mining_pools"], second_snapshot["services"]["mining_pools"])

    async def test_mining_pool_summary_distinguishes_reachable_and_stratum_healthy(self):
        sources = SpySources()
        sources.mining_pool_responses["us-west.mining4people.com:4176"] = {
            "tcp_connect_ok": True,
            "stratum_ok": False,
            "latency_ms": 140.0,
            "error": "invalid json response",
        }
        sources.mining_pool_responses["hoohash-pepew.eu.mine.zpool.ca:8335"] = {
            "tcp_connect_ok": False,
            "stratum_ok": False,
            "latency_ms": 210.0,
            "error": "connect timeout",
        }
        collector = MonitorCollector(build_settings(), MemoryCache(), sources, logger=logging.getLogger("test"))

        await collector.refresh_once()
        snapshot = collector.get_status_payload()
        pools = {item["endpoint"]: item for item in snapshot["services"]["mining_pools"]}

        self.assertEqual(snapshot["services"]["mining_pool_summary"]["reachable_pools"], 3)
        self.assertEqual(snapshot["services"]["mining_pool_summary"]["healthy_stratum_pools"], 2)
        self.assertEqual(pools["(M4P) us-west.mining4people.com:4176"]["status"], "degraded")
        self.assertEqual(pools["(zpool) stratum+tcp://hoohash-pepew.eu.mine.zpool.ca:8335"]["status"], "down")

    async def test_mining_pool_last_ok_at_is_preserved_on_failure(self):
        settings = build_settings()
        sources = SpySources()
        collector = MonitorCollector(settings, MemoryCache(), sources, logger=logging.getLogger("test"))

        await collector.refresh_once()
        first_snapshot = collector.get_status_payload()
        first_pool = {
            item["endpoint"]: item
            for item in first_snapshot["services"]["mining_pools"]
        }["(M4P) eu.mining4people.com:4176"]

        sources.mining_pool_responses["eu.mining4people.com:4176"] = {
            "tcp_connect_ok": True,
            "stratum_ok": False,
            "latency_ms": 150.0,
            "error": "read timeout waiting for stratum response",
        }
        collector._last_probe_at["mining_pools"] = time.monotonic() - settings.mining_pool_interval_seconds
        await collector.refresh_once()
        second_snapshot = collector.get_status_payload()
        second_pool = {
            item["endpoint"]: item
            for item in second_snapshot["services"]["mining_pools"]
        }["(M4P) eu.mining4people.com:4176"]

        self.assertEqual(second_pool["status"], "degraded")
        self.assertEqual(second_pool["last_ok_at"], first_pool["last_ok_at"])
        self.assertEqual(second_pool["error"], "read timeout waiting for stratum response")

    async def test_status_payload_includes_8m_timing_and_summaries(self):
        collector = MonitorCollector(build_settings(), MemoryCache(), SpySources(), logger=logging.getLogger("test"))

        await collector.refresh_once()
        snapshot = collector.get_status_payload()

        self.assertEqual(snapshot["avg_block_time_8m"], 60.0)
        self.assertEqual(snapshot["avg_block_time_5m"], 60.0)
        self.assertEqual(snapshot["services"]["summary"]["overall_status"], "ok")
        self.assertEqual(snapshot["services"]["mining_pool_summary"]["healthy_stratum_pools"], 4)
        self.assertEqual(snapshot["upgrade_summary"]["classification_status"], "complete")
        self.assertEqual(snapshot["freshness"]["overall_status"], "normal")
        self.assertIn("mn_cache_age_seconds", snapshot["freshness"])
        self.assertIn("site_status_age_seconds", snapshot["freshness"])
        self.assertIn("daemon_data_age_seconds", snapshot["freshness"])
        self.assertIn("explorer_data_age_seconds", snapshot["freshness"])
        self.assertIsInstance(snapshot["recent_anomalies"]["active_critical_count"], int)

    async def test_site_repeated_failures_raise_alert(self):
        settings = build_settings()
        settings.source_failure_threshold = 2
        sources = SpySources()
        sources.site_responses["https://wallet.pepepow.net"] = RuntimeError("timeout")
        collector = MonitorCollector(settings, MemoryCache(), sources, logger=logging.getLogger("test"))

        await collector.refresh_once()
        collector._last_probe_at["site_status"] = time.monotonic() - settings.site_status_interval_seconds
        await collector.refresh_once()
        snapshot = collector.get_status_payload()

        self.assertTrue(any(alert["type"] == "public_site_degraded" for alert in snapshot["alerts"]))

    async def test_status_payload_only_reads_latest_snapshot_cache(self):
        cache = SpyCache()
        collector = MonitorCollector(build_settings(), cache, SpySources(), logger=logging.getLogger("test"))

        await collector.refresh_once()
        cache.get_calls.clear()
        payload = collector.get_status_payload()

        self.assertIn("freshness", payload)
        self.assertEqual(cache.get_calls, ["monitor:latest"])

    async def test_status_payload_ages_increase_without_extra_cache_reads(self):
        cache = SpyCache()
        collector = MonitorCollector(build_settings(), cache, SpySources(), logger=logging.getLogger("test"))

        await collector.refresh_once()
        collector._latest_snapshot["generated_at_unix"] = int(time.time()) - 20
        collector._latest_snapshot["freshness"]["snapshot_age_seconds"] = 0
        collector._latest_snapshot["freshness"]["mn_cache_age_seconds"] = 5
        collector._latest_snapshot["freshness"]["masternode_list_age_seconds"] = 5
        collector._latest_snapshot["freshness"]["site_status_age_seconds"] = 30
        collector._latest_snapshot["freshness"]["site_checks_age_seconds"] = 30
        collector._latest_snapshot["freshness"]["daemon_data_age_seconds"] = 3
        collector._latest_snapshot["freshness"]["explorer_data_age_seconds"] = 4
        collector._latest_snapshot["last_block_age"] = 7
        cache.set_json("monitor:latest", collector._latest_snapshot)

        payload = collector.get_status_payload()

        self.assertGreaterEqual(payload["freshness"]["snapshot_age_seconds"], 20)
        self.assertGreaterEqual(payload["freshness"]["mn_cache_age_seconds"], 25)
        self.assertGreaterEqual(payload["freshness"]["site_status_age_seconds"], 50)
        self.assertGreaterEqual(payload["last_block_age"], 27)

    async def test_masternode_summary_reuses_previous_when_fingerprint_unchanged(self):
        settings = build_settings()
        sources = SpySources()
        collector = MonitorCollector(settings, MemoryCache(), sources, logger=logging.getLogger("test"))

        await collector.refresh_once()
        first_snapshot = collector.get_status_payload()
        first_fingerprint = first_snapshot.get("_masternode_summary_fingerprint")
        sources.peerinfo = list(sources.peerinfo)
        collector._last_probe_at["tier_b"] = time.monotonic() - settings.masternode_interval_seconds
        collector._last_probe_at["peerinfo"] = time.monotonic() - settings.peerinfo_interval_seconds
        await collector.refresh_once()
        second_snapshot = collector.get_status_payload()

        self.assertEqual(first_fingerprint, second_snapshot.get("_masternode_summary_fingerprint"))
        self.assertEqual(first_snapshot["upgrade_summary"], second_snapshot["upgrade_summary"])


if __name__ == "__main__":
    unittest.main()
