import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from apply_stock_fallbacks import apply_stock_fallbacks  # noqa: E402


class StockFallbackTests(unittest.TestCase):
    def test_failed_live_check_uses_configured_fallback(self):
        config = {
            "currency": "GBP",
            "products": [{"id": "tpu", "fallback_in_stock": True}],
        }
        latest = {
            "generated_at": "2026-07-14T10:00:00Z",
            "currency": "GBP",
            "products": [
                {
                    "id": "tpu",
                    "product_name": "TPU Feed Assist Module",
                    "price": 45.99,
                    "in_stock": False,
                    "history_count": 1,
                    "check_error": "blocked",
                }
            ],
        }
        histories = {
            "tpu": [
                {
                    "timestamp": "2026-07-14T09:45:00Z",
                    "price": 45.99,
                    "currency": "GBP",
                    "in_stock": False,
                    "reason": "heartbeat",
                }
            ]
        }

        changed = apply_stock_fallbacks(config, latest, histories)

        self.assertTrue(changed)
        self.assertTrue(latest["products"][0]["in_stock"])
        self.assertEqual(latest["products"][0]["history_count"], 2)
        self.assertEqual(histories["tpu"][-1]["reason"], "stock-fallback")
        self.assertTrue(histories["tpu"][-1]["in_stock"])

    def test_successful_live_check_is_never_overridden(self):
        config = {"products": [{"id": "tpu", "fallback_in_stock": True}]}
        latest = {
            "generated_at": "2026-07-14T10:00:00Z",
            "products": [{"id": "tpu", "price": 45.99, "in_stock": False, "check_error": None}],
        }
        histories = {"tpu": []}

        changed = apply_stock_fallbacks(config, latest, histories)

        self.assertFalse(changed)
        self.assertFalse(latest["products"][0]["in_stock"])
        self.assertEqual(histories["tpu"], [])


if __name__ == "__main__":
    unittest.main()
