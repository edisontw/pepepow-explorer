from __future__ import annotations

import unittest

from monitor.services.aggregation import (
    build_masternode_summary_fingerprint,
    build_masternode_summary,
    build_peer_version_summary,
    classify_semver_evidence,
    compress_semver_labels,
    format_hashrate,
    is_probable_ip_semver_noise,
    mask_peer_address,
    parse_version_tuple,
)


class AggregationTests(unittest.TestCase):
    def test_parse_version_tuple(self):
        self.assertEqual(parse_version_tuple("/PEPEPOW Core:2.9.0.2/"), (2, 9, 0, 2))
        self.assertIsNone(parse_version_tuple("unknown"))

    def test_build_peer_version_summary(self):
        peers = [
            {"subver": "/PEPEPOW Core:2.9.0.2/"},
            {"subver": "/PEPEPOW Core:2.8.1.3/"},
            {"subver": "something-strange"},
        ]
        summary = build_peer_version_summary(peers, "2.9.0.2")
        self.assertEqual(summary["total_peers"], 3)
        self.assertEqual(summary["upgraded_peers"], 1)
        self.assertEqual(summary["legacy_peers"], 1)
        self.assertEqual(summary["unknown_peers"], 1)

    def test_compress_semver_labels(self):
        self.assertEqual(compress_semver_labels(["2.8.1.1", "2.8.1.3"]), "2.8.1.x")
        self.assertEqual(compress_semver_labels(["2.9.0.2"]), "2.9.0.2")

    def test_classify_semver_evidence_mixed_bucket_is_unknown(self):
        self.assertIsNone(classify_semver_evidence(["2.9.0.0", "2.9.0.2"], "2.9.0.2"))
        self.assertTrue(classify_semver_evidence(["2.9.0.2", "2.9.0.3"], "2.9.0.2"))
        self.assertFalse(classify_semver_evidence(["2.8.9.9", "2.9.0.0"], "2.9.0.2"))

    def test_probable_ip_semver_noise_detection(self):
        self.assertTrue(is_probable_ip_semver_noise("1.34.236.202"))
        self.assertTrue(is_probable_ip_semver_noise("192.9.160.179"))
        self.assertFalse(is_probable_ip_semver_noise("2.9.0.2"))
        self.assertFalse(is_probable_ip_semver_noise("2.9.0.x"))

    def test_build_masternode_summary_groups_by_protocol_version(self):
        peers = [
            {"addr": "203.0.113.10:8833", "version": 70521, "subver": "/PEPEPOW Core:2.9.0.2/"},
            {"addr": "203.0.113.11:8833", "version": 70520, "subver": "/PEPEPOW Core:2.8.1.3/"},
            {"addr": "203.0.113.12:8833", "version": 70520, "subver": "/PEPEPOW Core:2.8.1.1/"},
        ]
        masternodes = [
            {"status": "ENABLED", "ip_address": "203.0.113.10:8833", "version": 70521},
            {"status": "ENABLED", "ip_address": "203.0.113.20:8833", "version": 70521},
            {"status": "ENABLED", "ip_address": "203.0.113.11:8833", "version": 70520},
            {"status": "ENABLED", "ip_address": "203.0.113.12:8833", "version": 70520},
            {"status": "NEW_START_REQUIRED", "ip_address": "203.0.113.13:8833", "version": 70521},
        ]
        summary = build_masternode_summary(masternodes, {"enabled": 4, "total": 5}, "2.9.0.2", peers)
        self.assertEqual(summary["upgraded_enabled"], 2)
        self.assertEqual(summary["legacy_enabled"], 2)
        self.assertEqual(summary["unknown_enabled"], 0)
        self.assertAlmostEqual(summary["upgrade_ratio"], 0.5, places=4)
        self.assertEqual(
            summary["versions"],
            [
                {
                    "protocol_version": 70521,
                    "display_version": "70521",
                    "semver": "2.9.0.2",
                    "count": 2,
                    "is_upgraded": True,
                },
                {
                    "protocol_version": 70520,
                    "display_version": "70520",
                    "semver": "2.8.1.3",
                    "count": 1,
                    "is_upgraded": False,
                },
                {
                    "protocol_version": 70520,
                    "display_version": "70520",
                    "semver": "2.8.1.1",
                    "count": 1,
                    "is_upgraded": False,
                },
            ],
        )

    def test_build_masternode_summary_without_peerinfo_keeps_protocol_only(self):
        masternodes = [
            {"status": "ENABLED", "version": 70521},
            {"status": "ENABLED", "version": 70520},
        ]
        summary = build_masternode_summary(masternodes, {"enabled": 2, "total": 2}, "2.9.0.2", [])
        self.assertEqual(summary["unknown_enabled"], 2)
        self.assertEqual(summary["versions"][0]["protocol_version"], 70521)
        self.assertIsNone(summary["versions"][0]["semver"])

    def test_build_masternode_summary_distinct_semver_buckets(self):
        peers = [
            {"addr": "203.0.113.10:8833", "version": 70521, "subver": "/PEPEPOW Core:2.9.0.0/"},
            {"addr": "203.0.113.11:8833", "version": 70521, "subver": "/PEPEPOW Core:2.9.0.2/"},
        ]
        masternodes = [
            {"status": "ENABLED", "ip_address": "203.0.113.10:8833", "version": 70521},
            {"status": "ENABLED", "ip_address": "203.0.113.11:8833", "version": 70521},
        ]

        summary = build_masternode_summary(masternodes, {"enabled": 2, "total": 2}, "2.9.0.2", peers)
        self.assertEqual(summary["upgraded_enabled"], 1)
        self.assertEqual(summary["legacy_enabled"], 1)
        self.assertEqual(summary["unknown_enabled"], 0)
        self.assertEqual(summary["versions"][0]["semver"], "2.9.0.2")
        self.assertEqual(summary["versions"][1]["semver"], "2.9.0.0")
        self.assertTrue(summary["versions"][0]["is_upgraded"])
        self.assertFalse(summary["versions"][1]["is_upgraded"])

    def test_build_masternode_summary_does_not_treat_raw_ip_as_semver(self):
        masternodes = [
            {
                "status": "ENABLED",
                "version": 70520,
                "raw": "ENABLED 70520 PTJy5TJXr2tk5v7YPLGhBt6CGG61oqhCGR 1775149708 785204 invalid_version expired 1.34.236.202:8833",
            }
        ]
        summary = build_masternode_summary(masternodes, {"enabled": 1, "total": 1}, "2.9.0.2", [])
        self.assertEqual(summary["versions"][0]["protocol_version"], 70520)
        self.assertIsNone(summary["versions"][0]["semver"])

    def test_format_hashrate(self):
        self.assertEqual(format_hashrate(916518.2836), "916.5183 KH/s")

    def test_mask_peer_address(self):
        self.assertEqual(mask_peer_address("144.91.102.0:8833"), "144.91.102.x:8833")

    def test_masternode_summary_fingerprint_changes_with_peer_version_evidence(self):
        masternodes = [{"status": "ENABLED", "ip_address": "203.0.113.10:8833", "version": 70521}]
        fingerprint_a = build_masternode_summary_fingerprint(
            masternodes,
            {"enabled": 1, "total": 1},
            [{"addr": "203.0.113.10:8833", "version": 70521, "subver": "/PEPEPOW Core:2.9.0.2/"}],
        )
        fingerprint_b = build_masternode_summary_fingerprint(
            masternodes,
            {"enabled": 1, "total": 1},
            [{"addr": "203.0.113.10:8833", "version": 70521, "subver": "/PEPEPOW Core:2.9.0.3/"}],
        )
        self.assertNotEqual(fingerprint_a, fingerprint_b)


if __name__ == "__main__":
    unittest.main()
