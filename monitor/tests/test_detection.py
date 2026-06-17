from __future__ import annotations

import unittest

from monitor.services.detection import (
    detect_fork_readiness_alert,
    detect_fork_stall_alert,
    detect_mempool_alert,
    detect_no_new_block_alert,
    detect_rpc_health_alert,
    detect_site_health_alerts,
    detect_source_degraded_alert,
    detect_upgrade_ratio_alert,
    determine_fork_state,
    evaluate_fork_state,
)


class DetectionTests(unittest.TestCase):
    def test_determine_fork_state(self):
        self.assertEqual(determine_fork_state(99, 100), "PRE_FORK")
        self.assertEqual(determine_fork_state(100, 100), "ACTIVATING")
        self.assertEqual(determine_fork_state(101, 100), "POST_FORK")

    def test_pre_fork_activation_alert(self):
        recent_blocks = [
            {
                "height": 99,
                "has_hoohash_bit": True,
                "has_xelis_bit": False,
                "difficulty": 1.0,
                "time": 1000,
            }
        ]
        fork_status, alerts = evaluate_fork_state(
            recent_blocks,
            current_height=99,
            fork_height=100,
            upgrade_ratio=0.5,
            target_version="2.9.0.2",
            fork_configured=True,
            last_block_age=65,
            block_target_seconds=60,
        )
        self.assertEqual(fork_status["state"], "PRE_FORK")
        self.assertTrue(any(alert["type"] == "pre_fork_activation_attempt" for alert in alerts))
        self.assertFalse(any(alert["type"] == "invalid_version_combination" for alert in alerts))

    def test_no_new_block_alert(self):
        recent_blocks = [
            {
                "height": 100,
                "difficulty": 1.0,
                "time": 1000,
                "interval_from_prev": 61,
            }
        ]
        alerts = detect_no_new_block_alert(
            recent_blocks,
            current_timestamp=1300,
            block_target_seconds=60,
        )
        self.assertTrue(any(alert["type"] == "stalled_blocks" for alert in alerts))

    def test_mempool_zero_alert_requires_duration_and_new_blocks(self):
        alerts = detect_mempool_alert(mempool_txs=0, mempool_zero_duration=601, zero_window_has_new_blocks=True)
        self.assertEqual(alerts[0]["type"], "mempool_zero")
        self.assertEqual(detect_mempool_alert(mempool_txs=0, mempool_zero_duration=500, zero_window_has_new_blocks=True), [])

    def test_rpc_cooldown_too_long_alert(self):
        alerts = detect_rpc_health_alert(rpc_local_status="cooldown", cooldown_active_seconds=121)
        self.assertEqual(alerts[0]["type"], "rpc_cooldown_too_long")

    def test_low_upgrade_ratio_near_fork_alert(self):
        alerts = detect_upgrade_ratio_alert(countdown_blocks=499, upgrade_ratio=0.79, target_version="2.9.0.2")
        self.assertEqual(alerts[0]["type"], "low_upgrade_ratio_near_fork")

    def test_source_degraded_alert(self):
        alerts = detect_source_degraded_alert(
            {
                "explorer_local": {"name": "explorer_local", "status": "degraded"},
                "public_api_remote": {"name": "public_api_remote", "status": "ok"},
            }
        )
        self.assertEqual(alerts[0]["type"], "source_degraded")

    def test_fork_readiness_levels(self):
        fork_status, _ = evaluate_fork_state(
            [],
            current_height=990,
            fork_height=1000,
            upgrade_ratio=0.9,
            target_version="2.9.0.2",
            fork_configured=True,
            eta_seconds=600,
            last_block_age=60,
            block_target_seconds=60,
        )
        self.assertEqual(fork_status["readiness_level"], "critical")
        alerts = detect_fork_readiness_alert(fork_status)
        self.assertEqual(alerts[0]["severity"], "critical")

    def test_fork_stall_alert_near_fork(self):
        fork_status, _ = evaluate_fork_state(
            [],
            current_height=950,
            fork_height=1000,
            upgrade_ratio=0.9,
            target_version="2.9.0.2",
            fork_configured=True,
            eta_seconds=3000,
            last_block_age=250,
            block_target_seconds=60,
        )
        self.assertEqual(fork_status["stall_level"], "critical")
        alerts = detect_fork_stall_alert(fork_status)
        self.assertEqual(alerts[0]["type"], "fork_stall")

    def test_post_fork_readiness_levels(self):
        fork_status, _ = evaluate_fork_state(
            [],
            current_height=1005,
            fork_height=1000,
            upgrade_ratio=0.95,
            target_version="2.9.0.2",
            fork_configured=True,
            eta_seconds=0,
            last_block_age=15,
            block_target_seconds=60,
        )
        self.assertEqual(fork_status["readiness_level"], "normal")
        alerts = detect_fork_readiness_alert(fork_status)
        self.assertEqual(alerts, [])
        self.assertEqual(fork_status["chain_moving_status"], "healthy")
        self.assertEqual(fork_status["blocks_after_fork"], 5)

    def test_site_health_alert_requires_repeated_failures(self):
        self.assertEqual(
            detect_site_health_alerts(
                [{"name": "pepepow.org", "status": "down", "status_code": 502, "consecutive_failures": 1}]
            ),
            [],
        )
        alerts = detect_site_health_alerts(
            [{"name": "pepepow.org", "status": "down", "status_code": 502, "consecutive_failures": 2}]
        )
        self.assertEqual(alerts[0]["type"], "public_site_degraded")


if __name__ == "__main__":
    unittest.main()
