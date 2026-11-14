from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from monitor.config import load_settings


class MonitorDefaultTargetTests(unittest.TestCase):
    def test_public_site_and_bowserlab_defaults(self):
        with patch.dict(os.environ, {
            "MONITOR_SITE_STATUS_TARGETS": "",
            "MONITOR_MINING_POOL_TARGETS": "",
        }):
            settings = load_settings()
        names = [target.name for target in settings.site_status_targets]
        self.assertIn("pepepow.net", names)
        self.assertEqual(names[names.index("pepepow.org") + 1], "pepepow.net")
        bowser = next(target for target in settings.mining_pool_targets if target.host == "bowserlab.ddns.net")
        self.assertEqual(bowser.port, 9912)
        self.assertEqual(bowser.probe_type, "stratum")


if __name__ == "__main__":
    unittest.main()
