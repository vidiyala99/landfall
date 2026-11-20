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
        self.assertIn("Can AI assistants help your customers?", page)
        self.assertIn("Hartwell Family Bakery", page)
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


if __name__ == "__main__":
    unittest.main()
