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
