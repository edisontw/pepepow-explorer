from __future__ import annotations

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from monitor.ui.tier_presentation import build_tier_display


def summary_for_enabled(
    enabled=54,
    enabled_counts=None,
    all_counts=None,
    enabled_available=True,
    stale=False,
):
    return {
        "masternode_total": 311,
        "masternode_enabled": enabled,
        "masternode_tiers": {
            "available": True, "enabled_available": enabled_available,
            "stale": stale, "source": "explorer_cache",
            "counts": all_counts or {"T1": 180, "T2": 11, "T3": 14, "T4": 106, "unknown": 0},
            "enabled_counts": enabled_counts if enabled_counts is not None else {
                "T1": 14, "T2": 3, "T3": 6, "T4": 31, "unknown": 0,
            },
        },
    }


class TierDisplayTests(unittest.TestCase):
    def test_full_explorer_cache_renders_enabled_subset_not_311(self):
        display = build_tier_display(summary_for_enabled())
        self.assertTrue(display["available"])
        self.assertEqual(display["counts"]["T1"], 14)
        self.assertEqual(display["counts"]["T4"], 31)
        self.assertEqual(sum(display["counts"].values()), 54)
        self.assertFalse(display["show_unknown"])
        self.assertEqual(display["label"], "Explorer cache · latest")

    def test_dashboard_template_contains_enabled_tier_counts_without_js(self):
        template_dir = Path(__file__).resolve().parents[1] / "ui" / "templates"
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        html = env.get_template("dashboard.html").render(
            title="Monitor", root_path="/monitor", asset_version="test123",
            tier_display=build_tier_display(summary_for_enabled()),
        )
        self.assertIn("Collateral Tiers — ENABLED Nodes", html)
        self.assertIn('<strong id="mn-tier-t1">14</strong>', html)
        self.assertIn('<strong id="mn-tier-t2">3</strong>', html)
        self.assertIn('<strong id="mn-tier-t3">6</strong>', html)
        self.assertIn('<strong id="mn-tier-t4">31</strong>', html)
        self.assertIn("Explorer cache · latest", html)
        self.assertIn('id="mn-tier-unknown-container" style="display:none"', html)

    def test_stale_but_verified_enabled_cache_remains_visible(self):
        display = build_tier_display(summary_for_enabled(stale=True))
        self.assertEqual(display["label"], "Explorer cache · stale")
        self.assertEqual(display["counts"]["T1"], 14)

    def test_missing_enabled_counts_never_falls_back_to_all_registered_counts(self):
        summary = summary_for_enabled(enabled_available=False)
        display = build_tier_display(summary)
        self.assertFalse(display["available"])
        self.assertEqual(display["counts"]["T1"], "-")
        self.assertEqual(display["label"], "ENABLED tier snapshot unavailable")

    def test_incomplete_or_mismatched_roster_does_not_fabricate_enabled_counts(self):
        cases = [
            summary_for_enabled(enabled=55),
            summary_for_enabled(all_counts={"T1": 14, "T2": 3, "T3": 6, "T4": 33, "unknown": 0}),
            summary_for_enabled(enabled_counts={"T1": 181, "T2": 0, "T3": 0, "T4": 0, "unknown": 0}),
            summary_for_enabled(enabled_counts={"T1": 14, "T2": -3, "T3": 6, "T4": 37, "unknown": 0}),
            {},
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertFalse(build_tier_display(case)["available"])

    def test_zero_enabled_nodes_can_be_verified_without_fabricating_data(self):
        summary = summary_for_enabled(enabled=0, enabled_counts={
            "T1": 0, "T2": 0, "T3": 0, "T4": 0, "unknown": 0
        })
        display = build_tier_display(summary)
        self.assertTrue(display["available"])
        self.assertEqual(display["counts"]["T1"], 0)


if __name__ == "__main__":
    unittest.main()
