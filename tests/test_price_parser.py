import unittest
from decimal import Decimal

from scripts.check_price import extract_price, extract_stock


class PriceParserTests(unittest.TestCase):
    def test_json_ld_offer_is_preferred(self):
        html = """
        <html><head><script type="application/ld+json">
        {"@type":"Product","offers":{"@type":"Offer","priceCurrency":"GBP","price":"479.99","availability":"https://schema.org/InStock"}}
        </script></head><body>Finance from £13.11</body></html>
        """
        self.assertEqual(str(extract_price(html)), "479.99")
        self.assertTrue(extract_stock(html))

    def test_ocuk_sale_text_uses_final_vat_price(self):
        html = '<html><body><main>£499.99 £479.99 (incl. VAT) <span>In stock</span></main></body></html>'
        self.assertEqual(str(extract_price(html)), "479.99")
        self.assertTrue(extract_stock(html))

    def test_reference_selects_matching_variant_price(self):
        html = """
        <html><head><script type="application/ld+json">
        {"@type":"Product","offers":[
          {"@type":"Offer","priceCurrency":"GBP","price":"569.00"},
          {"@type":"Offer","priceCurrency":"GBP","price":"769.00"}
        ]}</script></head><body></body></html>
        """
        self.assertEqual(extract_price(html, Decimal("769.00")), Decimal("769.00"))

    def test_variant_text_gets_priority(self):
        html = '<html><body>Standard £20.99 Other product £10.99 Black (10101) / Filament with spool / 1 kg £18.49</body></html>'
        self.assertEqual(
            extract_price(html, Decimal("20.99"), "Black (10101) / Filament with spool / 1 kg"),
            Decimal("18.49"),
        )

    def test_out_of_stock(self):
        html = '<html><body><div>TPU Feed Assist Module — out of stock</div><div>£45.99</div></body></html>'
        self.assertFalse(extract_stock(html, "TPU Feed Assist Module"))


if __name__ == "__main__":
    unittest.main()
