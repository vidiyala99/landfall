import io
import json
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from landfall import scan

FIX = Path(__file__).parent / "fixtures"


def fx(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


OK = {"status": 200, "headers": {}, "text": "<html><body>hi</body></html>"}


def data_for(raw, rendered=None, robots=None, **kw):
    d = {
        "url": "https://bakery.test/", "slug": "bakery-test", "fetched_at": "2026-11-20T21:00:00+00:00",
        "raw_html": raw, "rendered_html": rendered or raw,
        "robots": {"status": 200, "text": robots, "saved": True} if robots is not None else {"status": 404, "text": ""},
        "llms": {"status": 404, "text": ""}, "sitemap": {"status": 404, "text": ""},
        "agent_resp": OK, "browser_resp": OK, "extra_pages": [],
    }
    d.update(kw)
    return d


def by_id(result):
    return {c["id"]: c for c in result["checks"]}


class TestRobots(unittest.TestCase):
    def test_training_only_blocked_is_warn(self):
        text = fx("robots_training_only.txt")
        self.assertTrue(scan.robots_verdict(text, "GPTBot")["blocked"])
        self.assertTrue(scan.robots_verdict(text, "Google-Extended")["blocked"])
        self.assertTrue(scan.robots_verdict(text, "Meta-ExternalAgent")["blocked"])
        for bot in ("ClaudeBot", "Claude-User", "PerplexityBot", "OAI-SearchBot"):
            v = scan.robots_verdict(text, bot)
            self.assertFalse(v["blocked"], bot)
            self.assertEqual(v["via"], "*")
        v = scan.robots_verdict(text, "GPTBot")
        self.assertIn("line 2: User-agent: GPTBot", v["lines"])
        self.assertIn("line 3: Disallow: /", v["lines"])
        c = scan.check_robots({"status": 200, "text": text, "saved": True}, "https://bakery.test/")
        self.assertEqual(c["status"], "warn")
        self.assertIn("GPTBot", c["receipt"]["excerpt"])

    def test_star_disallow_blocks_user_agents_but_specific_allow_wins(self):
        text = fx("robots_block_all.txt")
        self.assertFalse(scan.robots_verdict(text, "ClaudeBot")["blocked"])
        self.assertTrue(scan.robots_verdict(text, "Claude-User")["blocked"])
        self.assertTrue(scan.robots_verdict(text, "OAI-SearchBot")["blocked"])
        c = scan.check_robots({"status": 200, "text": text, "saved": True}, "https://bakery.test/")
        self.assertEqual(c["status"], "fail")
        self.assertIn("line 5: Disallow: /", c["detail"])
        self.assertEqual(c["receipt"]["path"], "receipts/robots.txt")
        self.assertEqual(c["fix_id"], "robots_patch")

    def test_partial_disallow_is_not_block(self):
        self.assertFalse(scan.robots_verdict("User-agent: GPTBot\nDisallow: /private\n", "GPTBot")["blocked"])

    def test_missing_robots_passes(self):
        c = scan.check_robots({"status": 404, "text": ""}, "https://bakery.test/")
        self.assertEqual(c["status"], "pass")


class TestJsonLd(unittest.TestCase):
    def test_graph_and_bakery_subtype(self):
        ents = scan.jsonld_entities(scan.parse_html(fx("bakery.html")).jsonld)
        biz = scan.best_business(ents)
        self.assertIsNotNone(biz)
        self.assertEqual(biz["@type"], "Bakery")
        f = scan.business_fields(biz)
        self.assertEqual(f["telephone"], "+1-937-555-0142")
        self.assertIn("412 Wayne Ave", f["address"])
        r = by_id(scan.analyze(data_for(fx("bakery.html"))))
        self.assertEqual(r["jsonld_business"]["status"], "pass")
        self.assertEqual(r["jsonld_hours"]["status"], "pass")
        self.assertEqual(r["jsonld_offers"]["status"], "pass")

    def test_organization_list_missing_fields_is_warn(self):
        r = by_id(scan.analyze(data_for(fx("spa_raw.html"), fx("spa_rendered.html"))))
        self.assertEqual(r["jsonld_business"]["status"], "warn")
        self.assertIn("address", r["jsonld_business"]["detail"])
        self.assertEqual(r["jsonld_hours"]["status"], "fail")
        self.assertEqual(r["jsonld_offers"]["status"], "fail")

    def test_no_jsonld_fails_with_excerpt(self):
        r = by_id(scan.analyze(data_for("<html><body><p>Hello</p></body></html>")))
        self.assertEqual(r["jsonld_business"]["status"], "fail")
        self.assertIn("ld+json", r["jsonld_business"]["receipt"]["excerpt"])

    def test_broken_jsonld_trailing_comma_and_url_type(self):
        blocks = ['{"@type":"http://schema.org/Restaurant","name":"X","telephone":"1","address":"2 A St",}']
        biz = scan.best_business(scan.jsonld_entities(blocks))
        self.assertIsNotNone(biz)


class TestNoJs(unittest.TestCase):
    def test_spa_fails_ratio_and_js_only_facts(self):
        raw_text = scan.parse_html(fx("spa_raw.html")).text
        ren_text = scan.parse_html(fx("spa_rendered.html")).text
        c = scan.check_nojs(raw_text, ren_text, "https://joe.test/", None)
        self.assertEqual(c["status"], "fail")
        self.assertIn("phone", c["detail"])
        self.assertIn("ratio", c["receipt"]["excerpt"])

    def test_static_page_passes(self):
        t = scan.parse_html(fx("bakery.html")).text
        c = scan.check_nojs(t, t, "https://bakery.test/", None)
        self.assertEqual(c["status"], "pass")

    def test_ratio_boundary(self):
        rendered = " ".join(["word"] * 100)
        self.assertEqual(scan.check_nojs(" ".join(["word"] * 29), rendered, "u", None)["status"], "fail")
        self.assertEqual(scan.check_nojs(" ".join(["word"] * 30), rendered, "u", None)["status"], "pass")

    def test_render_error_is_warn(self):
        c = scan.check_nojs("abc", "", "u", "TimeoutError")
        self.assertEqual(c["status"], "warn")


class TestScore(unittest.TestCase):
    def mk(self, status, sev):
        return scan.check("x", "t", status, sev, "d", {"kind": "html", "excerpt": "e", "url": "u"}, False, None)

    def test_weighted(self):
        checks = [self.mk("pass", "high"), self.mk("fail", "high"), self.mk("warn", "med"), self.mk("pass", "low")]
        s = scan.score(checks)
        # (3 + 0 + 1 + 1) / (3 + 3 + 2 + 1) = 5/9 = 55.6
        self.assertEqual(s, {"read": 56, "passed": 2, "total": 4})

    def test_all_pass_and_empty(self):
        self.assertEqual(scan.score([self.mk("pass", "med")])["read"], 100)
        self.assertEqual(scan.score([])["read"], 0)


class TestOtherChecks(unittest.TestCase):
    def test_bakery_details(self):
        r = by_id(scan.analyze(data_for(fx("bakery.html"), robots=fx("robots_training_only.txt"))))
        self.assertEqual(r["form_labels"]["status"], "pass")
        self.assertEqual(r["img_alt"]["status"], "pass")
        self.assertEqual(r["contact_machine_readable"]["status"], "pass")
        self.assertEqual(r["sitemap"]["status"], "pass")  # declared in robots.txt
        self.assertEqual(r["facts_in_images_or_pdf"]["status"], "fail")
        self.assertIn("https://bakery.test/files/cake-menu.pdf", r["facts_in_images_or_pdf"]["receipt"]["excerpt"])

    def test_spa_forms_images(self):
        r = by_id(scan.analyze(data_for(fx("spa_raw.html"), fx("spa_rendered.html"))))
        self.assertEqual(r["form_labels"]["status"], "fail")
        self.assertIn("phone", r["form_labels"]["receipt"]["excerpt"])
        self.assertEqual(r["img_alt"]["status"], "fail")
        self.assertIn("menu-prices.png", r["img_alt"]["detail"])
        self.assertEqual(r["contact_machine_readable"]["status"], "warn")  # phone text, no tel: link

    def test_bot_challenge(self):
        cf = {"status": 403, "headers": {"Server": "cloudflare"}, "text": "<title>Just a moment...</title>"}
        c = scan.check_bot(cf, OK, "u")
        self.assertEqual(c["status"], "fail")
        self.assertIn("Just a moment", c["detail"].replace("just a moment", "Just a moment"))
        mitigated = {"status": 200, "headers": {"cf-mitigated": "challenge"}, "text": ""}
        self.assertIsNotNone(scan.classify_response(mitigated))
        self.assertEqual(scan.check_bot(OK, OK, "u")["status"], "pass")
        # a normal page with a recaptcha form is not a challenge
        page = {"status": 200, "headers": {}, "text": "<div class='g-recaptcha'></div>" + "x" * 20000}
        self.assertIsNone(scan.classify_response(page))

    def test_llms_soft_404(self):
        c = scan.check_llms({"status": 200, "text": "<!doctype html><html>", "ctype": "text/html"}, "https://a.test/")
        self.assertEqual(c["status"], "fail")
        c = scan.check_llms({"status": 200, "text": "# Rosie's\n> bakery", "ctype": "text/plain"}, "https://a.test/")
        self.assertEqual(c["status"], "pass")


class TestContract(unittest.TestCase):
    CASES = [
        ("bakery.html", None, "robots_training_only.txt"),
        ("spa_raw.html", "spa_rendered.html", "robots_block_all.txt"),
        ("spa_raw.html", None, None),
    ]

    def results(self):
        for raw, ren, rob in self.CASES:
            yield scan.analyze(data_for(fx(raw), fx(ren) if ren else None, fx(rob) if rob else None))
        blocked = {"status": 429, "headers": {}, "text": ""}
        yield scan.analyze(data_for("", agent_resp=blocked, browser_resp=blocked, render_error="net::ERR"))

    def test_every_fail_has_receipt_and_shape(self):
        keys = {"id", "title", "status", "severity", "detail", "receipt", "fixable", "fix_id"}
        for res in self.results():
            self.assertEqual(set(res), {"url", "slug", "fetched_at", "checks", "score", "facts"})
            self.assertEqual(len(res["checks"]), 12)
            self.assertEqual(set(res["facts"]), {"name", "phone", "address", "hours_text", "offer_snippets"})
            json.dumps(res)
            for c in res["checks"]:
                self.assertEqual(set(c), keys)
                self.assertEqual(set(c["receipt"]), {"kind", "path", "excerpt", "url"})
                self.assertIn(c["receipt"]["kind"], ("http", "html", "screenshot", "file"))
                if c["receipt"]["excerpt"]:
                    self.assertLessEqual(len(c["receipt"]["excerpt"]), 300)
                if c["status"] == "fail":
                    self.assertTrue(c["receipt"]["path"] or c["receipt"]["excerpt"], c["id"])
                if not c["fixable"]:
                    self.assertIsNone(c["fix_id"])

    def test_validate_rejects_fail_without_receipt(self):
        bad = {"checks": [scan.check("x", "t", "fail", "high", "d", {"kind": "html", "url": "u"}, False, None)]}
        with self.assertRaises(ValueError):
            scan.validate(bad)

    def test_facts(self):
        f = scan.analyze(data_for(fx("spa_raw.html"), fx("spa_rendered.html")))["facts"]
        self.assertEqual(f["name"], "Joe's Auto")
        self.assertEqual(f["phone"], "937-555-0199")
        self.assertTrue(f["address"].startswith("1200 Main St"))
        self.assertIn("Sat 9am", f["hours_text"])
        self.assertTrue(any("$39.99" in s for s in f["offer_snippets"]))


class TestCli(unittest.TestCase):
    def test_dispatch_unknown_and_help(self):
        from landfall.__main__ import main
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(["nope"]), 2)
            self.assertEqual(main(["--help"]), 0)

    def test_slug(self):
        self.assertEqual(scan.slug_for("https://www.Rosies-Bakery.com/menu"), "rosies-bakery-com")

    def test_subpages_same_site_only(self):
        doc = scan.parse_html('<a href="/menu">Menu</a><a href="https://other.test/menu">x</a>'
                              '<a href="/files/m.pdf">Menu</a><a href="/blog">Blog</a><a href="/services">S</a>')
        self.assertEqual(scan.pick_subpages(doc, "https://bakery.test/"),
                         ["https://bakery.test/menu", "https://bakery.test/services"])


if __name__ == "__main__":
    unittest.main()


class TestChallengedRaw(unittest.TestCase):
    def test_nojs_is_warn_when_raw_was_a_challenge(self):
        cf = {"status": 403, "headers": {"cf-mitigated": "challenge"}, "text": "<title>Just a moment...</title>"}
        r = by_id(scan.analyze(data_for("<title>Just a moment...</title>", fx("spa_rendered.html"),
                                        agent_resp=cf, browser_resp=cf)))
        self.assertEqual(r["nojs_content"]["status"], "warn")
        self.assertIn("bot challenge", r["nojs_content"]["detail"])
        self.assertEqual(r["bot_challenge"]["status"], "fail")
        self.assertIn("full browser", r["bot_challenge"]["detail"])
