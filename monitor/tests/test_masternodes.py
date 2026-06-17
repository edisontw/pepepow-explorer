from __future__ import annotations

import unittest

from monitor.services.masternodes import merge_masternode_records, normalize_masternode_items


class MasternodeNormalizationTests(unittest.TestCase):
    def test_normalize_masternode_items_preserves_structured_fields(self):
        payload = [
            {
                "addr": "PEPEW123",
                "status": "enabled",
                "lastseen": 1712345678,
                "activetime": 123456,
                "ip": "203.0.113.10:8833",
                "version": 2090002,
                "subver": "/PEPEPOW Core:2.9.0.2/",
            }
        ]

        self.assertEqual(
            normalize_masternode_items(payload),
            [
                {
                    "addr": "PEPEW123",
                    "txid": None,
                    "ip": "203.0.113.10:8833",
                    "status": "ENABLED",
                    "lastseen": 1712345678,
                    "activetime": 123456,
                    "version": 2090002,
                    "subver": "/PEPEPOW Core:2.9.0.2/",
                    "fallback_only": False,
                }
            ],
        )

    def test_normalize_masternode_items_uses_fallback_fields(self):
        payload = [
            {
                "collateraladdress": "PEPEW456",
                "txhash": "ab" * 32,
                "ip_address": "203.0.113.11:8833",
                "status": "pre_enabled",
                "last_seen": 1712345600,
                "active_time": 222,
                "version": "2090002",
            }
        ]

        self.assertEqual(
            normalize_masternode_items(payload)[0],
            {
                "addr": "PEPEW456",
                "txid": "ab" * 32,
                "ip": "203.0.113.11:8833",
                "status": "PRE_ENABLED",
                "lastseen": 1712345600,
                "activetime": 222,
                "version": 2090002,
                "subver": None,
                "fallback_only": False,
            },
        )

    def test_normalize_masternode_items_drops_empty_entries_and_keeps_partial_visible_entries(self):
        payload = [
            {"status": "expired", "version": 1},
            {"raw": "not-useful"},
            {},
        ]

        self.assertEqual(
            normalize_masternode_items(payload),
            [
                {
                    "addr": None,
                    "txid": None,
                    "ip": None,
                    "status": "EXPIRED",
                    "lastseen": None,
                    "activetime": None,
                    "version": 1,
                    "subver": None,
                    "fallback_only": False,
                }
            ],
        )

    def test_normalize_masternode_items_parses_rpc_raw_lines(self):
        payload = [
            {
                "raw": "NEW_START_REQUIRED 70521 PGNYGxh4iwJ6yewp9V3depPgd8uBXJn1Ay 1774983481 1318185 invalid_version expired 192.9.180.67:8833",
                "txhash": "d9d8f461cfd8abe57c575b83efb15a505b0db4209376b454c719448275ae5adb-1",
            }
        ]

        self.assertEqual(
            normalize_masternode_items(payload),
            [
                {
                    "addr": "PGNYGxh4iwJ6yewp9V3depPgd8uBXJn1Ay",
                    "txid": "d9d8f461cfd8abe57c575b83efb15a505b0db4209376b454c719448275ae5adb",
                    "ip": "192.9.180.67:8833",
                    "status": "NEW_START_REQUIRED",
                    "lastseen": 1774983481,
                    "activetime": 1318185,
                    "version": 70521,
                    "subver": None,
                    "fallback_only": False,
                }
            ],
        )

    def test_merge_masternode_records_fills_missing_entries_from_rpc(self):
        explorer_items = [
            {"addr": "PTJy5TJXr2tk5v7YPLGhBt6CGG61oqhCGR", "txhash": "aaa", "outidx": 1, "status": "ENABLED", "ip_address": "1.1.1.1:1", "version": 70521}
        ]
        rpc_items = [
            {"raw": "ENABLED 70521 PTJy5TJXr2tk5v7YPLGhBt6CGG61oqhCGR 1775149708 785204 invalid_version expired 1.1.1.1:1", "txhash": "aaa-1"},
            {"raw": "NEW_START_REQUIRED 70521 PGNYGxh4iwJ6yewp9V3depPgd8uBXJn1Ay 1774983481 1318185 invalid_version expired 192.9.180.67:8833", "txhash": "bbb-1"}
        ]

        merged = merge_masternode_records(explorer_items, rpc_items)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["txhash"], "aaa")
        self.assertEqual(merged[0]["outidx"], 1)
        self.assertEqual(merged[1]["addr"], "PGNYGxh4iwJ6yewp9V3depPgd8uBXJn1Ay")
        self.assertEqual(merged[1]["status"], "NEW_START_REQUIRED")


if __name__ == "__main__":
    unittest.main()
