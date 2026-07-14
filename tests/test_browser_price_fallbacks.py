import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import apply_browser_price_fallbacks  # noqa: E402


RENDERED_TPU_PAGE = """
<html><body>
  <main>
    <h1>TPU Feed Assist Module</h1>
    <div class="product-price">
      <span class="sale-price">£39.09 GBP</span>
      <del class="compare-at-price">£45.99 GBP</del>
    </div>
    <button>Add to Cart</button>
  </main>
  <aside>Save £10 on another order</aside>
</body></html>
"""


class BrowserPriceFallbackTests(unittest.TestCase):
    def test_visible_sale_price_beats_compare_at_price(self):
        price = apply_browser_price_fallbacks.extract_rendered_current_price(
            RENDERED_TPU_PAGE,
            product_name="TPU Feed Assist Module",
            reference_price=Decimal("45.99"),
        )
        self.assertEqual(price, Decimal("39.09"))

    def test_failed_bambu_check_is_replaced_by_rendered_price_and_stock(self):
        config = {
            "currency": "GBP",
            "request_timeout_seconds": 35,
            "products": [
                {
                    "id": "bambu-tpu-feed-assist",
                    "product_name": "TPU Feed Assist Module",
                    "product_url": "https://uk.store.bambulab.com/products/tpu-feed-assist-module",
                    "retailer": "Bambu Lab UK",
                    "variant": "H2 Series/X1 Series/P1 Series/P2S/X2D",
                    "initial_price": 45.99,
                    "notify_on_any_drop": True,
                    "target_price": None,
                }
            ],
        }
        latest = {
            "generated_at": "2026-07-14T10:07:00Z",
            "currency": "GBP",
            "failed_checks": 1,
            "products": [
                {
                    "id": "bambu-tpu-feed-assist",
                    "product_name": "TPU Feed Assist Module",
                    "product_url": "https://uk.store.bambulab.com/products/tpu-feed-assist-module",
                    "retailer": "Bambu Lab UK",
                    "variant": "H2 Series/X1 Series/P1 Series/P2S/X2D",
                    "price": 45.99,
                    "previous_price": 45.99,
                    "in_stock": True,
                    "check_error": "Could not find a plausible GBP product price in the page",
                }
            ],
        }
        histories = {
            "bambu-tpu-feed-assist": [
                {
                    "timestamp": "2026-07-14T10:00:58Z",
                    "price": 45.99,
                    "currency": "GBP",
                    "in_stock": True,
                    "reason": "stock-fallback",
                }
            ]
        }

        changed, alerts = apply_browser_price_fallbacks.apply_browser_price_fallbacks(
            config,
            latest,
            histories,
            renderer=lambda _url, _timeout: RENDERED_TPU_PAGE,
        )

        product = latest["products"][0]
        self.assertTrue(changed)
        self.assertEqual(product["price"], 39.09)
        self.assertTrue(product["in_stock"])
        self.assertIsNone(product["check_error"])
        self.assertEqual(product["price_source"], "Live Bambu product page via headless Chrome")
        self.assertEqual(latest["failed_checks"], 0)
        self.assertEqual(histories["bambu-tpu-feed-assist"][-1]["price"], 39.09)
        self.assertEqual(alerts[0]["current_price"], "39.09")
        self.assertEqual(alerts[0]["previous_price"], "45.99")


if __name__ == "__main__":
    unittest.main()
