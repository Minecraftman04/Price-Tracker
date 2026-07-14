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

    def test_rendered_fallback_preserves_live_stock_when_price_is_client_rendered(self):
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
            html, source = run_price_check.fetch_with_shopify(url, 35)

        self.assertIn("configured reference price", source)
        self.assertEqual(run_price_check.check_price.extract_price(html), run_price_check.Decimal("45.99"))
        self.assertTrue(run_price_check.check_price.extract_stock(html))


if __name__ == "__main__":
    unittest.main()
