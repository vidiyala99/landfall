import json
import shutil
import tempfile
import unittest
from pathlib import Path

from landfall import fix, products

FIX = Path(__file__).parent / "fixtures" / "run"
BASE = "https://blooms.example/"

# Raw HTML as the server sends it: Knockout card has a name but an EMPTY price span.
RAW = """<html><body><ol class="products list">
<li class="product-item"><div class="product-item-info">
  <img src="/media/b2s.jpg"><strong class="product-item-name">
  <a class="product-item-link" href="/back2school-special.html">Back2School Special</a></strong>
  <div class="price-box"><span class="price" data-bind="text: price"></span></div>
</div></li></ol></body></html>"""

# The same page after a browser ran the scripts, plus a generic card and a microdata card.
RENDERED = """<html><body><nav><a href="/sympathy.html">Sympathy</a><a href="/checkout/cart/">Cart</a>
<a href="/birthday.html">Birthday</a></nav><ol class="products list">
<li class="product-item"><div class="product-item-info">
  <img src="/media/b2s.jpg"><strong class="product-item-name">
  <a class="product-item-link" href="/back2school-special.html">Back2School Special</a></strong>
  <div class="price-box"><span class="price" data-bind="text: price">$69.99</span></div>
</div></li>
<li class="product-item"><div class="product-item-info">
  <strong class="product-item-name"><a class="product-item-link" href="/lots-of-love.html">Lots of Love</a></strong>
  <div class="price-box"><span data-price-type="oldPrice"><span class="price">$110.00</span></span>
  <span data-price-type="finalPrice"><span class="price">$95.00</span></span></div>
</div></li>
<li class="product-item"><div class="product-item-info">
  <strong class="product-item-name"><a class="product-item-link" href="/no-price.html">No Price Posy</a></strong>
  <div class="price-box"><span class="price" data-bind="text: price"></span></div>
</div></li></ol>
<div class="grid"><div class="card"><a href="/sunflowers"><h3>Sunflower Fields</h3></a><span>$59.99</span></div>
<div class="card"><a href="/tulips"><h3>Tulip Cup</h3></a><span>$45.00</span></div></div>
<div itemscope itemtype="https://schema.org/Product"><span itemprop="name">Rose Dozen</span>
<a itemprop="url" href="/rose-dozen">see</a><span itemprop="price">$80.00</span></div>
</body></html>"""


def by_name(items):
    return {p["name"]: p for p in items}


class ParseTest(unittest.TestCase):
    def test_raw_knockout_page_lists_nothing(self):
        # Name without a seen price is never listed.
        self.assertEqual(products.parse_products(RAW, BASE), [])

    def test_rendered_page(self):
        got = by_name(products.parse_products(RENDERED, BASE))
        self.assertEqual(got["Back2School Special"]["price"], "$69.99")
        self.assertEqual(got["Back2School Special"]["url"], "https://blooms.example/back2school-special.html")
        self.assertEqual(got["Back2School Special"]["image"], "https://blooms.example/media/b2s.jpg")
        self.assertEqual(got["Lots of Love"]["price"], "$95.00")  # final price, not the struck-out one
        self.assertEqual(got["Sunflower Fields"]["price"], "$59.99")
        self.assertEqual(got["Tulip Cup"]["price"], "$45.00")
        self.assertEqual(got["Rose Dozen"]["price"], "$80.00")
        self.assertNotIn("No Price Posy", got)

    def test_dedupe_by_url(self):
        got = products.parse_products(RENDERED + RENDERED, BASE)
        urls = [p["url"] for p in got]
        self.assertEqual(len(urls), len(set(urls)))

    def test_category_links_skip_cart(self):
        self.assertEqual(products.category_links(RENDERED, BASE),
                         ["https://blooms.example/sympathy.html", "https://blooms.example/birthday.html"])


class OutputTest(unittest.TestCase):
    def setUp(self):
        self.items = products.parse_products(RENDERED, BASE)

    def test_jsonld_only_seen_prices(self):
        ld = products.to_jsonld(self.items + [{"name": "Planted", "price": "", "url": BASE + "x"}], "Blooms")
        self.assertEqual(ld["@type"], "ItemList")
        seen = {float(p["price"].strip("$").replace(",", "")) for p in self.items}
        got = [e["item"]["offers"]["price"] for e in ld["itemListElement"]]
        self.assertEqual(set(got), seen)
        names = [e["item"]["name"] for e in ld["itemListElement"]]
        self.assertNotIn("Planted", names)
        self.assertNotIn("No Price Posy", names)
        self.assertEqual(ld["itemListElement"][0]["item"]["offers"]["priceCurrency"], "USD")
        self.assertEqual(ld["numberOfItems"], len(self.items))
        # Absent price never appears anywhere in the output.
        self.assertNotIn("110", json.dumps(ld))

    def test_text_and_html(self):
        t = products.to_text(self.items)
        self.assertIn("- Back2School Special: $69.99 (https://blooms.example/back2school-special.html)", t)
        h = products.to_html_section(self.items)
        self.assertIn("Our arrangements and prices", h)
        self.assertIn("$95.00", h)
        self.assertNotIn("<script", h)


class FixIntegrationTest(unittest.TestCase):
    def test_fix_writes_product_files(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            run = tmp / "run"
            shutil.copytree(FIX, run)
            items = products.parse_products(RENDERED, BASE)
            (run / "products.json").write_text(json.dumps({
                "url": BASE, "extracted_at": "2026-11-20T22:00:00+00:00",
                "pages": [{"url": BASE, "screenshot": "receipts/products/page-1.png"}],
                "count": len(items), "products": items}), encoding="utf-8")
            res = fix.run(run)
            self.assertEqual(res["products"], len(items))
            fx = run / "fixes"
            self.assertIn('"ItemList"', (fx / "products.jsonld.html").read_text(encoding="utf-8"))
            self.assertIn("Back2School Special: $69.99", (fx / "products.md").read_text(encoding="utf-8"))
            self.assertIn("Lots of Love: $95.00", (fx / "llms.txt").read_text(encoding="utf-8"))
            ch = (fx / "CHANGES.md").read_text(encoding="utf-8")
            self.assertIn(f"Listed {len(items)} products with prices so assistants that don't run scripts can see them", ch)
            self.assertIn("products.json", ch)
            idx = (run / "mirror-fixed" / "index.html").read_text(encoding="utf-8")
            self.assertIn("Our arrangements and prices", idx)
            self.assertIn("$69.99", idx)
            self.assertIn('"ItemList"', idx)
            self.assertNotIn("No Price Posy", idx)
            self.assertTrue((run / "mirror-fixed" / "products" / "index.html").exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_products_no_files(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            run = tmp / "run"
            shutil.copytree(FIX, run)
            res = fix.run(run)
            self.assertEqual(res["products"], 0)
            self.assertFalse((run / "fixes" / "products.md").exists())
            self.assertNotIn("Listed", (run / "fixes" / "CHANGES.md").read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
