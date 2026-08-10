import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_price_check  # noqa: E402


class BambuShopifyTests(unittest.TestCase):
    def test_storefront_js_prices_are_converted_from_pence(self):
        payload = {
            "title": "TPU Feed Assist Module",
            "available": True,
            "variants": [
                {
                    "title": "H2 Series/X1 Series/P1 Series/P2S/X2D",
                    "sku": "SLA",
                    "price": 4599,
                    "available": True,
                }
            ],
        }

        product = run_price_check.normalise_product_payload(payload, prices_in_cents=True)

        self.assertIsNotNone(product)
        self.assertEqual(product["variants"][0]["price"], "45.99")
        variant = run_price_check.choose_variant(
            product,
            {
                "variant": "H2 Series/X1 Series/P1 Series/P2S/X2D",
                "sku": "SLA",
                "initial_price": 45.99,
            },
        )
        self.assertIsNotNone(variant)
        html = run_price_check.synthetic_product_html(
            product,
            variant,
            {"product_name": "TPU Feed Assist Module", "variant": variant["title"], "sku": "SLA"},
        )
        self.assertEqual(run_price_check.check_price.extract_price(html), run_price_check.Decimal("45.99"))
        self.assertTrue(run_price_check.check_price.extract_stock(html))

    def test_wrapped_product_json_stays_in_pounds(self):
        payload = {
            "product": {
                "title": "TPU Feed Assist Module",
                "variants": [{"title": "Default", "price": "45.99", "available": False}],
            }
        }

        product = run_price_check.normalise_product_payload(payload)

        self.assertEqual(product["variants"][0]["price"], "45.99")
        self.assertFalse(product["variants"][0]["available"])

    def test_predictive_search_price_scale_matches_known_price(self):
        candidate = {
            "title": "TPU Feed Assist Module",
            "available": True,
            "variants": [
                {
                    "title": "H2 Series/X1 Series/P1 Series/P2S/X2D",
                    "sku": "SLA",
                    "price": 4599,
                    "available": True,
                }
            ],
        }
        wanted = {
            "product_name": "TPU Feed Assist Module",
            "variant": "H2 Series/X1 Series/P1 Series/P2S/X2D",
            "sku": "SLA",
            "initial_price": 45.99,
        }

        product = run_price_check.normalise_best_price_scale(candidate, wanted)

        self.assertIsNotNone(product)
        self.assertEqual(product["variants"][0]["price"], "45.99")
        self.assertTrue(product["variants"][0]["available"])

    def test_rendered_fallback_accepts_plausible_visible_price_and_stock(self):
        url = "https://uk.store.bambulab.com/products/tpu-feed-assist-module"
        rendered = """
        <html><body>
          <h1>TPU Feed Assist Module</h1>
          <p>H2 Series/X1 Series/P1 Series/P2S/X2D</p>
          <span>£39.09</span>
          <button>Add to cart</button>
        </body></html>
        """

        with (
            patch.object(run_price_check, "resolve_product", return_value=None),
            patch.object(run_price_check, "ORIGINAL_FETCH", return_value=(rendered, "Rendered product page")),
        ):
            html, source = run_price_check.fetch_with_shopify(url, 35)

        self.assertIn("plausible rendered price", source)
        self.assertEqual(run_price_check.check_price.extract_price(html), run_price_check.Decimal("39.09"))
        self.assertTrue(run_price_check.check_price.extract_stock(html))

    def test_rendered_fallback_rejects_unrelated_ten_pound_price(self):
        url = "https://uk.store.bambulab.com/products/tpu-feed-assist-module"
        rendered = """
        <html><body>
          <h1>TPU Feed Assist Module</h1>
          <p>H2 Series/X1 Series/P1 Series/P2S/X2D</p>
          <button>Add to cart</button>
          <aside>Save £10 on another order</aside>
        </body></html>
        """

        with (
            patch.object(run_price_check, "resolve_product", return_value=None),
            patch.object(run_price_check, "ORIGINAL_FETCH", return_value=(rendered, "Rendered product page")),
        ):
            with self.assertRaisesRegex(RuntimeError, "Rejected suspicious rendered Bambu price"):
                run_price_check.fetch_with_shopify(url, 35)

    def test_rendered_fallback_without_price_remains_failed_for_browser_verification(self):
        url = "https://uk.store.bambulab.com/products/tpu-feed-assist-module"
        rendered = """
        <html><body>
          <h1>TPU Feed Assist Module</h1>
          <p>H2 Series/X1 Series/P1 Series/P2S/X2D</p>
          <button>Add to cart</button>
        </body></html>
        """

        with (
            patch.object(run_price_check, "resolve_product", return_value=None),
            patch.object(run_price_check, "ORIGINAL_FETCH", return_value=(rendered, "Rendered product page")),
        ):
            with self.assertRaisesRegex(RuntimeError, "trustworthy product price"):
                run_price_check.fetch_with_shopify(url, 35)


if __name__ == "__main__":
    unittest.main()
