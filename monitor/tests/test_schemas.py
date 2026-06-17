from __future__ import annotations

import unittest

from monitor.api.schemas import MasternodesPayloadModel, StatusModel


class SchemaTests(unittest.TestCase):
    def test_status_model_accepts_extended_snapshot(self):
        model = StatusModel(
            generated_at="2026-04-01T00:00:00+00:00",
            stale=False,
            height=100,
            mempool_txs=0,
            mempool_size=0,
            mempool_bytes=0,
            mempool_zero_duration=700,
            avg_block_time_3m=60.0,
            avg_block_time_5m=61.0,
            avg_block_time_8m=62.0,
            avg_block_time_30blocks=61.0,
            last_block_age=10,
            masternode_enabled=5,
            masternode_total=6,
            masternode_upgraded_enabled=4,
            masternode_legacy_enabled=1,
            masternode_unknown_enabled=0,
            masternode_versions=[
                {
                    "protocol_version": 70521,
                    "display_version": "70521",
                    "semver": "2.9.0.2",
                    "count": 4,
                    "is_upgraded": True,
                }
            ],
            upgrade_ratio=0.8,
            target_version="2.9.0.2",
            rpc_local_status="ok",
            rpc_fail_streak=0,
            cooldown_remaining_seconds=0,
            services={
                "summary": {"overall_status": "ok", "ok_count": 7, "degraded_count": 0, "down_count": 0, "core_sources_ok": 3, "public_sites_ok": 4},
                "core_sources": {"rpc_local": {"name": "rpc_local", "kind": "rpc", "status": "ok"}},
                "public_sites": [{"name": "pepepow.org", "url": "https://pepepow.org", "status": "ok", "status_code": 200}],
                "mining_pool_summary": {
                    "total_pools": 4,
                    "reachable_pools": 3,
                    "healthy_stratum_pools": 2,
                    "up_count": 2,
                    "degraded_count": 1,
                    "down_count": 1,
                },
                "mining_pools": [
                    {
                        "endpoint": "eu.mining4people.com:4176",
                        "host": "eu.mining4people.com",
                        "port": 4176,
                        "tcp_connect_ok": True,
                        "stratum_ok": True,
                        "latency_ms": 120.5,
                        "checked_at": "2026-04-01T00:00:00+00:00",
                        "last_ok_at": "2026-04-01T00:00:00+00:00",
                        "status": "up",
                        "error": None,
                    }
                ],
            },
            freshness={
                "snapshot_age_seconds": 5,
                "mn_cache_age_seconds": 10,
                "masternode_list_age_seconds": 10,
                "site_status_age_seconds": 120,
                "site_checks_age_seconds": 120,
                "daemon_data_age_seconds": 8,
                "explorer_data_age_seconds": 9,
                "last_block_age_seconds": 10,
                "snapshot_status": "normal",
                "mn_cache_status": "normal",
                "site_status_status": "stale",
                "daemon_status": "normal",
                "explorer_status": "normal",
                "last_block_status": "normal",
                "overall_status": "stale",
                "status": "stale",
                "thresholds": {"snapshot": {"stale": 10, "critical": 30}},
            },
            upgrade_summary={"enabled": 5, "upgraded": 4, "legacy": 1, "unknown": 0, "ratio": 0.8, "classification_status": "complete"},
            recent_anomalies={"window_hours": 24, "raised_count": 2, "cleared_count": 1, "active_critical_count": 1, "latest": []},
        )
        self.assertEqual(model.masternode_enabled, 5)
        self.assertEqual(model.avg_block_time_5m, 61.0)
        self.assertEqual(model.avg_block_time_8m, 62.0)
        self.assertEqual(model.masternode_versions[0].protocol_version, 70521)
        self.assertEqual(model.services.public_sites[0].name, "pepepow.org")
        self.assertEqual(model.services.mining_pool_summary.healthy_stratum_pools, 2)
        self.assertEqual(model.services.mining_pools[0].endpoint, "eu.mining4people.com:4176")
        self.assertEqual(model.freshness.status, "stale")
        self.assertEqual(model.freshness.mn_cache_age_seconds, 10)
        self.assertEqual(model.freshness.site_status_status, "stale")

    def test_masternodes_payload_model_accepts_cached_list(self):
        model = MasternodesPayloadModel(
            generated_at="2026-04-01T00:00:00+00:00",
            generated_at_unix=1775001600,
            stale=False,
            list_generated_at="2026-04-01T00:00:00+00:00",
            list_generated_at_unix=1775001600,
            items=[
                {
                    "addr": "PEPEW123",
                    "txid": "ab" * 32,
                    "ip": "203.0.113.10:8833",
                    "status": "ENABLED",
                    "lastseen": 1775001595,
                    "activetime": 100,
                    "version": 2090002,
                    "subver": "/PEPEPOW Core:2.9.0.2/",
                    "fallback_only": False,
                }
            ],
        )
        self.assertEqual(model.items[0].addr, "PEPEW123")
        self.assertEqual(model.items[0].status, "ENABLED")


if __name__ == "__main__":
    unittest.main()
