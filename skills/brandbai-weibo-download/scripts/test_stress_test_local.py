from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stress_test_local import build_synthetic_plan, run_stress


class LocalStressTests(unittest.TestCase):
    def test_synthetic_plan_builds_four_fixed_tasks_per_campaign(self) -> None:
        plan, lookup = build_synthetic_plan(3)
        self.assertEqual(len(plan["campaigns"]), 3)
        self.assertEqual(len(lookup), 3)

    def test_tiny_load_covers_delivery_package_and_recovery(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            result = run_stress(
                campaigns=2,
                comments=20,
                reposts=10,
                asset_mb=0,
                work_root=Path(temp),
            )
        self.assertTrue(result["result"]["passed"])
        self.assertEqual(result["configuration"]["source_tasks"], 8)
        self.assertEqual(result["result"]["counts"]["comments"], 20)
        self.assertEqual(result["result"]["counts"]["reposts"], 10)
        self.assertEqual(result["result"]["completed_resume_reran_tasks"], 0)
        self.assertEqual(result["result"]["recovery"]["retried_tasks"], 2)
        self.assertFalse(result["formal_stress_complete"])


if __name__ == "__main__":
    unittest.main()
