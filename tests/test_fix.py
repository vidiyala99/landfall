import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urljoin

from landfall import fix

FIX = Path(__file__).parent / "fixtures" / "run"


def load_scan():
    return json.loads((FIX / "scan.json").read_text(encoding="utf-8"))


class HoursTest(unittest.TestCase):
    def test_brief_example(self):
        specs = fix.parse_hours("Mon-Fri 7am-3pm, Sat 8-2")
        self.assertEqual(specs, [
            {"@type": "OpeningHoursSpecification",
             "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
             "opens": "07:00", "closes": "15:00"},
            {"@type": "OpeningHoursSpecification", "dayOfWeek": ["Saturday"],
             "opens": "08:00", "closes": "14:00"},
        ])

    def test_variants(self):
        s = fix.parse_hours("Tues - Sat: 7:00 AM to 2:00 PM; Sun 8am-noon")
        self.assertEqual([(x["dayOfWeek"][0], x["opens"], x["closes"]) for x in s],
                         [("Tuesday", "07:00", "14:00"), ("Sunday", "08:00", "12:00")])
        s = fix.parse_hours("Open daily 6am-9pm")
        self.assertEqual(len(s[0]["dayOfWeek"]), 7)
        s = fix.parse_hours("Wed-Sun 11-2pm")
        self.assertEqual((s[0]["opens"], s[0]["closes"]), ("11:00", "14:00"))
        self.assertEqual(fix.parse_hours("Call for hours"), [])


class JsonLdNoInventionTest(unittest.TestCase):
    def test_every_value_comes_from_facts(self):
        scan = load_scan()
        html = (FIX / "mirror" / "index.html").read_text(encoding="utf-8")
        text, links = fix.page_text_and_links(html)
        ld, _ = fix.build_jsonld(scan, text, links)
        link_urls = [urljoin(scan["url"], h) for h, _ in links]
        blob = json.dumps(scan["facts"]) + " " + scan["url"] + " " + " ".join(link_urls)
        specs = ld.get("openingHoursSpecification", [])
        derived = {d for s in specs for d in s["dayOfWeek"]} | {s[k] for s in specs for k in ("opens", "closes")}
        for v in fix.jsonld_leaf_strings(ld):
            if v in derived:
                continue
            self.assertIn(v, blob, f"JSON-LD value not found in facts: {v!r}")
        # hours are derived only from the facts' hours text
        self.assertEqual(specs, fix.parse_hours(scan["facts"]["hours_text"]))

    def test_planted_fake_is_not_used(self):
        scan = load_scan()
        # Planted values live in a check detail and in page text, never in facts.
        scan["facts"]["phone"] = None
        scan["facts"]["address"] = ""
        text = "Call us at (555) 010-9999. We are at 9 Fake Ave, Springfield, IL 62701."
        ld, questions = fix.build_jsonld(scan, text, [])
        dump = json.dumps(ld)
        self.assertNotIn("010-9999", dump)
        self.assertNotIn("Fake Ave", dump)
        self.assertNotIn("telephone", ld)
        self.assertNotIn("address", ld)
        self.assertTrue(any("phone" in q.lower() for q in questions))
        self.assertTrue(any("address" in q.lower() for q in questions))
        for absent in ("priceRange", "geo", "image", "logo", "servesCuisine", "aggregateRating"):
            self.assertNotIn(absent, ld)

    def test_subtype(self):
        self.assertEqual(fix.pick_subtype("Sweet Crumb Bakery", ""), "Bakery")
        self.assertEqual(fix.pick_subtype("Luigi's", "best pizza in town, pizza by the slice"), "Restaurant")
        self.assertEqual(fix.pick_subtype("Acme", "we sell things"), "LocalBusiness")

    def test_address(self):
        a = fix.parse_address("123 Main St, Dayton, OH 45402")
        self.assertEqual((a["streetAddress"], a["addressLocality"], a["addressRegion"], a["postalCode"]),
                         ("123 Main St", "Dayton", "OH", "45402"))
        self.assertEqual(fix.parse_address("Unit 4, Market Hall"),
                         {"@type": "PostalAddress", "streetAddress": "Unit 4, Market Hall"})


class RobotsTest(unittest.TestCase):
    def test_keeps_existing_rules(self):
        existing = "User-agent: *\nDisallow: /admin\nDisallow: /cart\n\nUser-agent: GPTBot\nDisallow: /\n"
        out, added, blocked = fix.patch_robots(existing, "https://x.test/sitemap.xml")
        self.assertTrue(out.startswith(existing.rstrip("\n")))
        self.assertEqual(added, list(fix.AGENT_UAS))
        for ua in fix.AGENT_UAS:
            self.assertIn(f"User-agent: {ua}", out)
        self.assertIn("Sitemap: https://x.test/sitemap.xml", out)
        self.assertEqual(blocked, [])

    def test_agent_group_keeps_star_disallows(self):
        out, _, _ = fix.patch_robots("User-agent: *\nDisallow: /wp-admin/\nDisallow: /\n")
        added = out.split("# Added by Landfall", 1)[1]
        self.assertIn("Disallow: /wp-admin/", added)
        self.assertNotIn("Disallow: /\n", added)
        self.assertIn("Allow: /", added)

    def test_link_phone(self):
        html = '<html><body><p class="x">Call 330-319-0066 today</p></body></html>'
        out, ok = fix.link_phone(html, "330-319-0066")
        self.assertTrue(ok)
        self.assertIn('<a href="tel:3303190066">330-319-0066</a>', out)
        self.assertEqual(fix.link_phone('<body><a href="tel:1">1</a></body>', "1")[1], False)

    def test_does_not_override_explicit_block(self):
        out, added, blocked = fix.patch_robots("User-agent: ChatGPT-User\nDisallow: /\n")
        self.assertEqual(blocked, ["ChatGPT-User"])
        self.assertNotIn("ChatGPT-User", added)
        self.assertIn("Disallow: /", out)

    def test_empty(self):
        out, _, _ = fix.patch_robots("")
        self.assertIn("User-agent: Claude-User", out)
        self.assertIn("Allow: /", out)


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(FIX, self.tmp / "run")
        self.run_dir = self.tmp / "run"
        self.res = fix.run(self.run_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_changes_lists_every_fixable_fail(self):
        scan = load_scan()
        changes = (self.run_dir / "fixes" / "CHANGES.md").read_text(encoding="utf-8")
        fixable = [c for c in scan["checks"] if c["fixable"] and c["status"] in ("fail", "warn")]
        self.assertTrue(fixable)
        for c in fixable:
            self.assertIn(f"`{c['id']}`", changes)
            if c["receipt"].get("url"):
                self.assertIn(c["receipt"]["url"], changes)
        self.assertIn("`bot_challenge`", changes)   # non-fixable fail -> "Needs you"
        self.assertNotIn("`nojs_content`", changes)  # pass -> not listed

    def test_mirror_fixed_applied(self):
        fixed = self.run_dir / "mirror-fixed"
        html = (fixed / "index.html").read_text(encoding="utf-8")
        m = re.search(r'<script type="application/ld\+json" data-landfall="1">(.*?)</script>', html, re.S)
        self.assertIsNotNone(m)
        self.assertLess(m.start(), html.lower().index("</head>"))
        ld = json.loads(m.group(1))
        self.assertEqual(ld["@type"], "Bakery")
        self.assertEqual(ld["telephone"], "(937) 555-0142")
        self.assertNotIn("010-9999", html)
        for f in ("llms.txt", "robots.txt", "sitemap.xml", ".well-known/agent.json"):
            self.assertTrue((fixed / f).exists(), f)
        self.assertIn("Disallow: /admin", (fixed / "robots.txt").read_text(encoding="utf-8"))
        self.assertIn('aria-label="Email address"', html)
        self.assertIn('aria-label="Your phone"', html)
        self.assertIn('alt="Chocolate layer cake"', html)
        self.assertNotIn("Img 4821", html)
        card = json.loads((fixed / ".well-known" / "agent.json").read_text(encoding="utf-8"))
        self.assertEqual(card["status"], "proposal")
        self.assertIn("call", [c["id"] for c in card["capabilities"]])
        llms = (fixed / "llms.txt").read_text(encoding="utf-8")
        self.assertIn("Mon-Fri 7am-3pm, Sat 8-2", llms)
        self.assertIn("https://order.example-bakery.test/cakes", llms)
        self.assertIn("Sunday", (self.run_dir / "fixes" / "needs-owner.md").read_text(encoding="utf-8"))
        self.assertIn("suggested, owner to confirm", (self.run_dir / "fixes" / "alt-text.md").read_text(encoding="utf-8"))
        self.assertTrue((self.run_dir / "fixes" / "facts-text.md").exists())

    def test_two_page_mirror(self):
        fixed = self.run_dir / "mirror-fixed"
        contact = (fixed / "contact" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("ld+json", contact)  # JSON-LD only on the homepage
        sitemap = (fixed / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn("<loc>https://example-bakery.test/</loc>", sitemap)
        self.assertIn("<loc>https://example-bakery.test/contact/</loc>", sitemap)
        self.assertFalse((fixed / "contact" / "llms.txt").exists())

    def test_source_mirror_untouched(self):
        self.assertNotIn("ld+json", (self.run_dir / "mirror" / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
