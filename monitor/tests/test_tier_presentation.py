from __future__ import annotations

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from monitor.ui.tier_presentation import build_tier_display


class TierDisplayTests(unittest.TestCase):
    def test_full_explorer_cache_renders_even_without_browser_javascript(self):
        summary = {
            "masternode_total": 311,
            "masternode_tiers": {
                "available": True,
                "stale": False,
                "source": "explorer_cache",
                "counts": {"T1": 180, "T2": 11, "T3": 14, "T4": 106, "unknown": 0},
            },
        }
        display = build_tier_display(summary)
        self.assertTrue(display["available"])
        self.assertEqual(display["counts"]["T1"], 180)
        self.assertEqual(display["counts"]["T4"], 106)
        self.assertFalse(display["show_unknown"])
        self.assertEqual(display["label"], "Explorer cache · latest")

    def test_dashboard_template_contains_tier_counts_without_any_javascript(self):
        summary = {
            "masternode_total": 311,
            "masternode_tiers": {
                "available": True,
                "stale": False,
                "source": "explorer_cache",
                "counts": {"T1": 180, "T2": 11, "T3": 14, "T4": 106, "unknown": 0},
            },
        }
        template_dir = Path(__file__).resolve().parents[1] / "ui" / "templates"
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        html = env.get_template("dashboard.html").render(
            title="Monitor", root_path="/monitor", asset_version="test123",
            tier_display=build_tier_display(summary),
        )
        self.assertIn('<strong id="mn-tier-t1">180</strong>', html)
        self.assertIn('<strong id="mn-tier-t2">11</strong>', html)
        self.assertIn('<strong id="mn-tier-t3">14</strong>', html)
        self.assertIn('<strong id="mn-tier-t4">106</strong>', html)
        self.assertIn("Explorer cache · latest", html)
        self.assertIn('id="mn-tier-unknown-container" style="display:none"', html)

    def test_stale_cache_remains_visible_but_labelled_stale(self):
        display = build_tier_display({
            "masternode_total": 2,
            "masternode_tiers": {
                "available": True, "stale": True, "source": "core_rpc",
                "counts": {"T1": 1, "T2": 0, "T3": 0, "T4": 0, "unknown": 1},
            },
        })
        self.assertEqual(display["label"], "Core RPC · stale")
        self.assertEqual(display["counts"]["T1"], 1)
        self.assertTrue(display["show_unknown"])

    def test_missing_or_partial_data_shows_unavailable_not_fabricated_zero(self):
        summary = {
            "masternode_total": 311,
            "masternode_tiers": {
                "available": True, "stale": False, "source": "explorer_cache",
                "counts": {"T1": 14, "T2": 3, "T3": 6, "T4": 33, "unknown": 0},
            },
        }
        display = build_tier_display(summary)
        self.assertFalse(display["available"])
        self.assertEqual(display["counts"]["T1"], "-")
        self.assertEqual(display["label"], "Tier snapshot unavailable")
        self.assertFalse(build_tier_display({})["available"])


if __name__ == "__main__":
    unittest.main()
