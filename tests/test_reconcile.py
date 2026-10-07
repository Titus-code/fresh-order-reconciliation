from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from src.reconcile_engine import RAW, reconcile


ROOT = Path(__file__).resolve().parents[1]
DIRTY_RAW = ROOT / "tests" / "fixtures" / "dirty" / "raw"


class ReconciliationTests(unittest.TestCase):
    def test_clean_snapshot_matches_expected_totals_at_both_cutoffs(self):
        current, current_problems = reconcile(RAW, "2026-10-06")
        month_end, month_end_problems = reconcile(RAW, "2026-09-30")

        self.assertEqual(len(current["orders"]), 143)
        self.assertEqual(len(current["valid_lines"]), 966)
        self.assertEqual(str(current["net"]), "44914.30")
        self.assertEqual(str(current["received"]), "26254.15")
        self.assertEqual(str(current["balance"]), "18660.15")
        self.assertEqual(current_problems, [])

        self.assertEqual(str(month_end["net"]), "44914.30")
        self.assertEqual(str(month_end["received"]), "6000.00")
        self.assertEqual(str(month_end["balance"]), "38914.30")
        self.assertEqual(len(month_end_problems), 84)
        self.assertTrue(all(p["classification"] == "口径排除" for p in month_end_problems))

    def test_dirty_snapshot_blocks_bad_orders_but_keeps_good_order(self):
        result, problems = reconcile(DIRTY_RAW, "2026-10-01")
        kinds = {problem["kind"] for problem in problems}

        self.assertEqual([row["order_id"] for row in result["orders"]], ["GOOD-1"])
        self.assertEqual(str(result["net"]), "2.00")
        self.assertEqual(str(result["received"]), "0.00")
        self.assertEqual(set(result["blocked_orders"]), {"BAD-1", "BAD-2", "BAD-3"})
        self.assertTrue({"主键重复", "数量非法", "商品不存在"}.issubset(kinds))
        self.assertIn("超出截止日", kinds)
        self.assertTrue(all(p["blocking"] == "是" for p in problems if p["kind"] in {
            "主键重复", "数量非法", "商品不存在", "整单暂缓"
        }))

    def test_malformed_numeric_input_is_reported_without_crashing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_dir = Path(temp_dir) / "raw"
            shutil.copytree(DIRTY_RAW, raw_dir)
            path = raw_dir / "order_lines.csv"
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[2]["delivered_qty"] = "not-a-number"
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

            result, problems = reconcile(raw_dir, "2026-10-06")

        self.assertNotIn("GOOD-1", [row["order_id"] for row in result["orders"]])
        self.assertTrue(any(problem["kind"] == "数值非法" for problem in problems))
        self.assertIn("GOOD-1", result["blocked_orders"])

    def test_line_rounding_is_half_up_per_component(self):
        from src.reconcile_engine import money

        self.assertEqual(str(money("1.005")), "1.01")
        self.assertEqual(str(money("0.004")), "0.00")


if __name__ == "__main__":
    unittest.main()
