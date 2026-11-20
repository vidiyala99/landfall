import tempfile
import unittest
import urllib.request
from pathlib import Path

from landfall import mirror

FIX = Path(__file__).parent / "fixtures"


class RewriteTest(unittest.TestCase):
    def setUp(self):
        self.html = (FIX / "page.html").read_text(encoding="utf-8")
        urls = [
            "https://shop.test/sub/css/main.css?v=3",
            "https://shop.test/img/hero.jpg",
            "https://cdn.test/a.png",
            "https://cdn.test/a@2x.png",
            "https://shop.test/sub/img/b.jpg?w=300&h=200",
        ]
        self.map = {u: mirror.local_name(u) for u in urls}

    def test_assets_rewritten(self):
        out = mirror.rewrite_html(self.html, "https://shop.test/", self.map)
        for u, local in self.map.items():
            self.assertIn("assets/" + local, out, u)
        self.assertNotIn("<base", out)
        self.assertIn('srcset="assets/%s 1x, assets/%s 2x"' % (
            self.map["https://cdn.test/a.png"], self.map["https://cdn.test/a@2x.png"]), out)
        # unknown assets and ordinary page links are left alone
        self.assertIn("https://elsewhere.test/untouched.png", out)
        self.assertIn('href="https://shop.test/contact"', out)

    def test_strip_scripts_keeps_jsonld(self):
        out = mirror.strip_scripts(self.html)
        self.assertNotIn("app.js", out)
        self.assertIn("application/ld+json", out)

    def test_css_rewrite(self):
        css = "@import 'base.css'; .a{background:url(../img/x.png)} .b{background:url(data:image/png;base64,AA)}"
        m = {"https://shop.test/css/base.css": "1-base.css", "https://shop.test/img/x.png": "2-x.png"}
        out = mirror.rewrite_css(css, "https://shop.test/css/site.css", m)
        self.assertIn('@import "1-base.css"', out)
        self.assertIn('url("2-x.png")', out)
        self.assertIn("data:image/png", out)

    def test_local_name(self):
        n = mirror.local_name("https://cdn.test/fonts/Inter%20Bold?x=1", "font/woff2")
        self.assertTrue(n.endswith("Inter_Bold.woff2"), n)
        self.assertEqual(n, mirror.local_name("https://cdn.test/fonts/Inter%20Bold?x=1", "font/woff2"))


class InternalPagesTest(unittest.TestCase):
    HOME = "https://www.bake.test/"

    def test_pick_internal_links(self):
        links = [
            ("https://bake.test/contact/", False), ("https://www.bake.test/cakes-cookies/", True),
            ("https://bake.test/cart/", True), ("https://bake.test/wp-admin/", True),
            ("https://bake.test/my-account/", True), ("https://bake.test/menu.pdf", True),
            ("https://bake.test/feed/", False), ("https://other.test/x", True),
            ("https://bake.test/#top", True), ("https://bake.test/contact", True),
            ("mailto:a@bake.test", True),
        ]
        self.assertEqual(mirror.pick_internal_links(self.HOME, links),
                         ["https://www.bake.test/cakes-cookies/", "https://bake.test/contact/"])
        many = [(f"https://bake.test/p{i}/", False) for i in range(20)]
        self.assertEqual(len(mirror.pick_internal_links(self.HOME, many)), 8)

    def test_rewrite_links_two_pages(self):
        page_map = {mirror.page_key(self.HOME): "", mirror.page_key("https://bake.test/contact/"): "contact/"}
        home = ('<a href="/contact/">C</a><a href="https://bake.test/contact#map">M</a>'
                '<a href="https://www.bake.test/">H</a><a href="/about/">A</a><a href="tel:1">T</a>')
        out = mirror.rewrite_links(home, self.HOME, page_map, 0)
        self.assertIn('href="contact/"', out)
        self.assertIn('href="contact/#map"', out)
        self.assertIn('href="./"', out)
        self.assertIn('href="/about/"', out)  # not mirrored: left alone
        self.assertIn('href="tel:1"', out)
        sub = mirror.rewrite_links('<a class="x" href="https://bake.test/">Home</a><a href="/contact/">C</a>',
                                   "https://bake.test/contact/", page_map, 1)
        self.assertIn('href="../"', sub)
        self.assertIn('href="../contact/"', sub)
        self.assertEqual(mirror.page_dir("https://bake.test/cakes-cookies/"), "cakes-cookies/")
        self.assertEqual(mirror.page_dir("https://bake.test/"), "")

    def test_two_page_mirror_navigates_offline(self):
        root = FIX / "run" / "mirror"
        httpd = mirror.serve(root, 0)
        try:
            port = httpd.server_address[1]
            home = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read().decode()
            self.assertIn("Sweet Crumb", home)
            contact = urllib.request.urlopen(f"http://127.0.0.1:{port}/contact/", timeout=5).read().decode()
            self.assertIn("Contact us", contact)
        finally:
            httpd.shutdown()
            httpd.server_close()


class ServeTest(unittest.TestCase):
    def test_serves_root_files(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
            (p / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
            (p / "llms.txt").write_text("# Hi\n", encoding="utf-8")
            httpd = mirror.serve(p, 0)
            try:
                port = httpd.server_address[1]
                for path, want in (("/", "hi"), ("/robots.txt", "Allow"), ("/llms.txt", "# Hi")):
                    body = urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5).read().decode()
                    self.assertIn(want, body)
            finally:
                httpd.shutdown()
                httpd.server_close()


if __name__ == "__main__":
    unittest.main()
