import json
import tempfile
import unittest
from pathlib import Path

from landfall.agent_run import extract_json, honesty_check, visible
from landfall.pipeline import default_tasks, slugify, summarize


class ExtractJson(unittest.TestCase):
    def test_fenced(self):
        self.assertEqual(extract_json('ok\n```json\n{"a": 1}\n```'), {"a": 1})

    def test_bare_last_object(self):
        self.assertEqual(extract_json('thinking {not json} then {"outcome": "done"}'), {"outcome": "done"})

    def test_none(self):
        self.assertIsNone(extract_json("no json here"))


class Visibility(unittest.TestCase):
    def test_domain_match_ignores_www(self):
        recs = [{"name": "Other", "url": "https://other.com"}, {"name": "X", "url": "http://www.3cbakery.com/"}]
        self.assertTrue(visible(recs, "https://3cbakery.com", "3 C's Bakery"))

    def test_name_match(self):
        self.assertTrue(visible([{"name": "3 C's Bakery (Yelp)", "url": "https://yelp.com/biz/x"}],
                                "https://3cbakery.com", "3 C's Bakery"))

    def test_absent(self):
        self.assertFalse(visible([{"name": "Big Box Cakes", "url": "https://bigbox.com"}],
                                 "https://3cbakery.com", "3 C's Bakery"))


class Honesty(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        d = self.tmp / "receipts" / "task-1"
        d.mkdir(parents=True)
        (d / "page.yml").write_text('- text: "Open Saturday 8am - 2pm. Call 330-319-0066"', encoding="utf-8")

    def _r(self, **kw):
        base = {"outcome": "done", "answer": None, "evidence_url": "https://x", "receipt": {"dir": "receipts/task-1"}}
        base.update(kw)
        return base

    def test_done_without_answer_is_dishonest(self):
        self.assertIs(honesty_check(self._r(), self.tmp)["ok"], False)

    def test_answer_in_snapshot_passes(self):
        self.assertIs(honesty_check(self._r(answer='"Open Saturday 8am - 2pm."'), self.tmp)["ok"], True)

    def test_invented_answer_flagged(self):
        self.assertIsNone(honesty_check(self._r(answer="A dozen cupcakes costs $24"), self.tmp)["ok"])

    def test_failed_needs_no_proof(self):
        self.assertIs(honesty_check(self._r(outcome="failed"), self.tmp)["ok"], True)


class Pipeline(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(slugify("https://www.3cbakery.com/menu"), "3cbakery-com")
        self.assertEqual(slugify("3cbakery.com"), "3cbakery-com")

    def test_default_tasks_include_goal(self):
        self.assertIn("birthday cake", default_tasks("order a birthday cake")[0])

    def test_summarize_partial_run(self):
        d = Path(tempfile.mkdtemp()) / "bakery"
        d.mkdir()
        (d / "scan.json").write_text(json.dumps({"url": "https://b", "score": {"read": 30}, "checks": [
            {"id": "llms_txt", "title": "t", "detail": "d", "severity": "low", "status": "fail"},
            {"id": "jsonld_hours", "title": "t2", "detail": "d2", "severity": "high", "status": "fail"},
        ]}), encoding="utf-8")
        s = summarize(d)
        self.assertEqual(s["read"], {"before": 30, "after": None})
        self.assertEqual(s["top_problems"][0]["id"], "jsonld_hours")
        self.assertIsNone(s["visible"])


if __name__ == "__main__":
    unittest.main()
