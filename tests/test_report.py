import json
import shutil
import tempfile
import unittest
from pathlib import Path

from landfall import report

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "report_run"


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def copy_fixture(self):
        run = self.tmp / "run"
        shutil.copytree(FIXTURE, run)
        (run / "report.html").unlink(missing_ok=True)
        return run

    def test_full_data(self):
        run = self.copy_fixture()
        page = report.render(run)
        self.assertTrue((run / "report.html").exists())
        self.assertEqual(page, (run / "report.html").read_text(encoding="utf-8"))
        self.assertIn("<h1>Your website tells AI assistants to stay out</h1>", page)
        self.assertIn("An AI assistant finished 1 of 4 customer tasks.", page)
        self.assertIn("Hartwell Family Bakery", page)
        # details are collapsed rows, receipts one click away
        self.assertIn('<details class="row task">', page)
        self.assertIn('<details class="row finding sev-high">', page)
        self.assertNotIn("<details open", page)
        # scores: Read 31 -> 88, Do 1/4 -> 4/4, Found no + honest pending after
        self.assertIn('<span class="before">31</span>', page)
        self.assertIn('<span class="after">88</span>', page)
        self.assertIn('<span class="before">1/4</span>', page)
        self.assertIn('<span class="after">4/4</span>', page)
        self.assertIn('<span class="before no">No</span>', page)
        self.assertIn("re-check after you publish the fixes", page)
        # sections
        self.assertIn("Order a chocolate cake for Saturday pickup", page)
        self.assertIn("files/receipts/task-2/step-3.png", page)
        self.assertIn("files/receipts/scan/robots.txt", page)
        self.assertIn("Ashley&#x27;s Pastry Shop", page)
        self.assertIn("files/fixes/robots.txt", page)
        self.assertIn("Questions only you can answer", page)
        self.assertIn("latest day someone can order", page)
        self.assertIn("Read-only", page)
        # severity order: high before med before low
        self.assertLess(page.index("Your site tells some AI"), page.index("Your menu only appears"))
        self.assertLess(page.index("Your menu only appears"), page.index("No short guide for assistants"))
        # dishonest claim surfaced
        self.assertIn("claimed more than it showed", page)
        # no em dashes in our copy
        self.assertNotIn("\u2014", page)

    def test_only_scan(self):
        run = self.tmp / "run"
        run.mkdir()
        shutil.copy(FIXTURE / "scan.json", run / "scan.json")
        page = report.render(run)
        self.assertIn('<span class="before">31</span>', page)
        self.assertIn("re-check after you publish the fixes", page)
        self.assertIn("has not tried any tasks yet", page)
        self.assertIn("not asked an assistant about you yet", page)
        self.assertIn("No fixes yet", page)
        self.assertIn("No hidden label", page)

    def test_empty_and_broken_files(self):
        run = self.tmp / "run"
        run.mkdir()
        (run / "scan.json").write_text("{not json", encoding="utf-8")
        (run / "do.json").write_text("[1,2]", encoding="utf-8")
        page = report.render(run)
        self.assertIn("The website check has not run yet", page)
        self.assertIn("run", page)

    def test_escapes_planted_script(self):
        run = self.copy_fixture()
        scan = json.loads((run / "scan.json").read_text(encoding="utf-8"))
        scan["checks"][0]["detail"] = "<script>alert('pwned')</script>"
        scan["checks"][0]["receipt"]["path"] = "../../etc/passwd"
        scan["facts"]["name"] = "<img src=x onerror=alert(1)>"
        (run / "scan.json").write_text(json.dumps(scan), encoding="utf-8")
        page = report.render(run)
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;alert(&#x27;pwned&#x27;)&lt;/script&gt;", page)
        self.assertNotIn("<img src=x", page)
        self.assertNotIn("etc/passwd", page)
        self.assertNotIn('href="javascript:', page)  # find.json plants one
        self.assertNotIn("<script", page.lower().replace("<style", ""))

    def test_receipt_href(self):
        self.assertEqual(report.receipt_href("receipts/a b.png"), "files/receipts/a b.png")
        self.assertEqual(report.receipt_href("files/receipts/x.png"), "files/receipts/x.png")
        self.assertIsNone(report.receipt_href("../x"))
        self.assertIsNone(report.receipt_href("javascript:alert(1)"))
        self.assertIsNone(report.receipt_href("C:/x"))
        self.assertIsNone(report.receipt_href(None))

    def test_markdown_escapes(self):
        out = report.markdown("- **a** <b>x</b> [l](javascript:alert(1))\n\n[ok](fixes/robots.txt)")
        self.assertIn("<strong>a</strong>", out)
        self.assertIn("&lt;b&gt;", out)
        self.assertNotIn("javascript:", out)
        self.assertIn('href="files/fixes/robots.txt"', out)


    # ---------- headline derivation ----------

    def scan(self, *fails, passes=("https",)):
        checks = [{"id": i, "status": "fail", "severity": sev, "title": i} for i, sev in fails]
        checks += [{"id": i, "status": "pass", "severity": "low", "title": i} for i in passes]
        return {"checks": checks, "score": {"read": 50}}

    def test_headline_bot_wall_beats_missing_facts(self):
        do = {"tasks": [{"task": "a", "outcome": "failed"}, {"task": "b", "outcome": "failed"}]}
        title, sub = report.headline(self.scan(("jsonld_business", "high"), ("bot_challenge", "high"), ("llms_txt", "low")), do)
        self.assertEqual(title, "ChatGPT can't get into your website")
        self.assertIn("turns AI assistants away", sub)
        self.assertIn("tried 2 customer tasks and couldn't finish any", sub)

    def test_headline_missing_facts(self):
        title, sub = report.headline(self.scan(("jsonld_hours", "med"), ("llms_txt", "low")), None)
        self.assertEqual(title, "AI assistants can't tell when you're open")
        self.assertNotIn("customer tasks", sub)

    def test_headline_severity_wins_over_order(self):
        title, _ = report.headline(self.scan(("llms_txt", "high"), ("jsonld_hours", "med")), None)
        self.assertEqual(title, "AI assistants have no guide to your website")

    def test_headline_unknown_check(self):
        title, sub = report.headline(self.scan(("brand_new_check", "high")), None)
        self.assertEqual(title, "AI assistants are missing facts about you")
        self.assertIn("We found 1 thing that", sub)

    def test_headline_nothing_failing(self):
        do = {"score": {"done": 4, "total": 4}}
        title, sub = report.headline(self.scan(passes=("a", "b")), do)
        self.assertEqual(title, "AI assistants can read your website")
        self.assertIn("Every check we ran passed.", sub)
        self.assertIn("all 4 customer tasks", sub)
        run = self.tmp / "ok"
        run.mkdir()
        (run / "scan.json").write_text(json.dumps(self.scan(passes=("a",))), encoding="utf-8")
        page = report.render(run)
        self.assertIn("Nothing broken", page)

    def test_headline_no_scan(self):
        title, _ = report.headline(None, None)
        self.assertEqual(title, "Can AI assistants help your customers?")
        run = self.tmp / "empty"
        run.mkdir()
        self.assertIn("<h1>Can AI assistants help your customers?</h1>", report.render(run))

    def test_bot_wall_gets_host_label_not_fixed(self):
        run = self.copy_fixture()
        scan = json.loads((run / "scan.json").read_text(encoding="utf-8"))
        scan["checks"].insert(0, {"id": "bot_challenge", "status": "fail", "severity": "high", "fixable": False,
                                  "fix_id": None, "title": "AI agents are not blocked by a bot wall", "detail": "403"})
        (run / "scan.json").write_text(json.dumps(scan), encoding="utf-8")
        page = report.render(run)
        self.assertIn("<h1>ChatGPT can&#x27;t get into your website</h1>", page)
        row = page[page.index("A bot wall turns AI assistants away"):]
        row = row[:row.index("</summary>")]
        self.assertIn("Needs a setting change by you or your website host", row)
        self.assertNotIn("Fixed in our test copy", row)

    def test_unchanged_after_is_not_green(self):
        run = self.copy_fixture()
        after = run / "after" / "do.json"
        do = json.loads((run / "do.json").read_text(encoding="utf-8"))
        after.write_text(json.dumps(do), encoding="utf-8")
        page = report.render(run)
        self.assertIn('<span class="after flat">1/4</span>', page)

    def test_fix_checklist_from_changes(self):
        md = ("### Opening hours are machine-readable (`jsonld_hours`, med)\n\n- **File:** `fixes/jsonld.html`\n"
              "- **Where to paste:** Paste inside the <head>.\n\n"
              "### Menu (`jsonld_offers`, med)\n\n- **File:** `fixes/jsonld.html`\n\n"
              "### Guide (`llms_txt`, low)\n\n- **File:** `fixes/llms.txt`\n- **Where to paste:** Upload to the root.\n")
        items = report._fix_items(md)
        self.assertEqual(list(items), ["jsonld.html", "llms.txt"])
        self.assertEqual(items["jsonld.html"]["what"], ["Labels your opening hours", "Labels what you sell"])
        self.assertEqual(items["jsonld.html"]["where"], "Paste inside the <head>.")
        run = self.copy_fixture()
        (run / "fixes" / "CHANGES.md").write_text(md, encoding="utf-8")
        page = report.render(run)
        self.assertIn("Labels your opening hours and labels what you sell", page)
        self.assertIn("Paste inside the &lt;head&gt;.", page)
        self.assertLess(page.index("files/fixes/jsonld.html"), page.index("files/fixes/robots.txt"))
        self.assertIn("Lets AI assistants read your site", page)  # undescribed file gets a plain purpose
        self.assertNotIn("0 problems", page)

    def test_owner_questions_drop_duplicate_title(self):
        run = self.copy_fixture()
        (run / "fixes" / "needs-owner.md").write_text("# Questions for the owner\n\n1. Open Sunday?\n", encoding="utf-8")
        page = report.render(run)
        self.assertNotIn("Questions for the owner", page)
        self.assertIn("Open Sunday?", page)


if __name__ == "__main__":
    unittest.main()
