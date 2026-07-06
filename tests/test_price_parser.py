import unittest

from scripts.check_price import extract_price, extract_stock


class PriceParserTests(unittest.TestCase):
    def test_json_ld_offer_is_preferred(self):
        html = '''
        <html><head><script type="application/ld+json">
        {"@type":"Product","offers":{"@type":"Offer","priceCurrency":"GBP","price":"479.99","availability":"https://schema.org/InStock"}}
        </script></head><body>Finance from £13.11</body></html>
        '''
        self.assertEqual(str(extract_price(html)), "479.99")
        self.assertTrue(extract_stock(html))

    def test_ocuk_sale_text_uses_final_vat_price(self):
        html = '<html><body><main>£499.99 £479.99 (incl. VAT) <span>In stock</span></main></body></html>'
        self.assertEqual(str(extract_price(html)), "479.99")
        self.assertTrue(extract_stock(html))

    def test_product_price_meta(self):
        html = '<html><head><meta property="product:price:amount" content="199.95"></head><body></body></html>'
        self.assertEqual(str(extract_price(html)), "199.95")

    def test_out_of_stock(self):
        html = '<html><body><div>Currently unavailable — out of stock</div><div>£99.99 (incl. VAT)</div></body></html>'
        self.assertFalse(extract_stock(html))


if __name__ == "__main__":
    unittest.main()
