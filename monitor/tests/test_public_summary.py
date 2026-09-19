from __future__ import annotations

import unittest

from monitor.api.routes import build_public_summary
from monitor.api.schemas import PublicSummaryModel


class PublicSummaryTests(unittest.TestCase):
    def test_public_summary_is_small_and_allowlisted(self):
        payload = {
            "generated_at": "2026-09-19T12:00:00+00:00",
            "generated_at_unix": 1789819200,
            "stale": False,
            "height": 4_500_000,
            "height_source": "rpc_local",
            "hashrate_hps": 123456.0,
            "hashrate_display": "123.46 KH/s",
            "peer_count": 12,
            "avg_block_time_8m": 61.5,
            "last_block_age": 18,
            "masternode_enabled": 42,
            "rpc_local_status": "ok",
            "source_health": {
                "rpc_local": {
                    "name": "rpc_local",
                    "kind": "rpc",
                    "status": "ok",
                }
            },
            "peers": {"items": [{"addr": "198.51.100.10:8833"}]},
            "freshness": {
                "overall_status": "normal",
                "last_block_age_seconds": 18,
            },
        }

        summary = build_public_summary(payload, 0.00001234)
        model = PublicSummaryModel(**summary)

        self.assertEqual(model.network_status, "normal")
        self.assertEqual(model.height, 4_500_000)
        self.assertEqual(model.avg_block_time_seconds, 61.5)
        self.assertEqual(model.masternode_count, 42)
        self.assertEqual(model.price_usdt, 0.00001234)

        self.assertEqual(
            set(summary),
            {
                "generated_at",
                "updated_at",
                "stale",
                "network_status",
                "height",
                "last_block_age_seconds",
                "avg_block_time_seconds",
                "hashrate_hps",
                "hashrate_display",
                "masternode_count",
                "price_usdt",
            },
        )
        self.assertNotIn("source_health", summary)
        self.assertNotIn("peers", summary)
        self.assertNotIn("rpc_local_status", summary)

    def test_public_summary_uses_safe_fallbacks(self):
        summary = build_public_summary(
            {
                "stale": True,
                "avg_block_time_5m": 62.0,
                "last_block_age": 30,
                "masternode_enabled": None,
            },
            None,
        )

        self.assertEqual(summary["network_status"], "stale")
        self.assertEqual(summary["avg_block_time_seconds"], 62.0)
        self.assertEqual(summary["last_block_age_seconds"], 30)
        self.assertEqual(summary["masternode_count"], 0)
        self.assertIsNone(summary["price_usdt"])


if __name__ == "__main__":
    unittest.main()
