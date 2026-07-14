import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from clear_price_history import clear_price_history, parse_request  # noqa: E402


class ClearPriceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.latest = {
            "generated_at": "2026-07-14T10:30:00Z",
            "currency": "GBP",
            "products": [
                {
                    "id": "one",
                    "product_name": "First product",
                    "price": 12.34,
                    "previous_price": 15.00,
                    "change": -2.66,
                    "change_percent": -17.73,
                    "lowest_price": 10.00,
                    "highest_price": 15.00,
                    "in_stock": True,
                    "checked_at": "2026-07-14T10:29:00Z",
                    "first_seen_at": "2026-07-01T00:00:00Z",
                    "history_count": 3,
                },
                {
                    "id": "two",
                    "product_name": "Second product",
                    "price": 20.00,
                    "previous_price": 19.00,
                    "change": 1.00,
                    "change_percent": 5.26,
                    "lowest_price": 18.00,
                    "highest_price": 20.00,
                    "in_stock": False,
                    "checked_at": "2026-07-14T10:28:00Z",
                    "first_seen_at": "2026-07-02T00:00:00Z",
                    "history_count": 2,
                },
            ],
        }
        self.histories = {
            "one": [
                {"timestamp": "a", "price": 15.00},
                {"timestamp": "b", "price": 10.00},
                {"timestamp": "c", "price": 12.34},
            ],
            "two": [
                {"timestamp": "a", "price": 18.00},
                {"timestamp": "b", "price": 20.00},
            ],
            "removed-product": [{"timestamp": "old", "price": 99.00}],
        }

    def test_parse_product_request(self):
        request = parse_request(
            "action: clear-price-history\nscope: product\nproduct_id: one\nproduct_name: First product\n"
        )
        self.assertEqual(request["scope"], "product")
        self.assertEqual(request["product_id"], "one")

    def test_clear_one_product_retains_current_baseline(self):
        changed, summary = clear_price_history(
            self.latest,
            self.histories,
            {"action": "clear-price-history", "scope": "product", "product_id": "one"},
        )

        self.assertTrue(changed)
        self.assertIn("First product", summary)
        self.assertEqual(len(self.histories["one"]), 1)
        self.assertEqual(self.histories["one"][0]["reason"], "manual-reset")
        self.assertEqual(self.histories["one"][0]["price"], 12.34)
        self.assertEqual(len(self.histories["two"]), 2)
        self.assertIn("removed-product", self.histories)
        product = self.latest["products"][0]
        self.assertEqual(product["previous_price"], 12.34)
        self.assertEqual(product["change"], 0.0)
        self.assertEqual(product["lowest_price"], 12.34)
        self.assertEqual(product["highest_price"], 12.34)
        self.assertEqual(product["history_count"], 1)

    def test_clear_all_products_removes_stale_history(self):
        changed, summary = clear_price_history(
            self.latest,
            self.histories,
            {"action": "clear-price-history", "scope": "all"},
        )

        self.assertTrue(changed)
        self.assertIn("all tracked products", summary)
        self.assertEqual(set(self.histories), {"one", "two"})
        self.assertEqual(len(self.histories["one"]), 1)
        self.assertEqual(len(self.histories["two"]), 1)
        self.assertEqual(self.latest["products"][1]["lowest_price"], 20.00)
        self.assertEqual(self.latest["products"][1]["change_percent"], 0.0)

    def test_invalid_product_is_rejected(self):
        with self.assertRaises(ValueError):
            clear_price_history(
                self.latest,
                self.histories,
                {"action": "clear-price-history", "scope": "product", "product_id": "missing"},
            )

    def test_dashboard_loads_history_control_assets(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("history-controls.css", index)
        self.assertIn("history-controls.js", index)

    def test_history_controls_javascript_has_valid_syntax(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is not installed")
        subprocess.run(
            [node, "--check", str(ROOT / "history-controls.js")],
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()
