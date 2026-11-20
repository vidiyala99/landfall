import os
import unittest
from unittest import mock

from landfall import cognee_backend as cb

ENV = {"COGNEE_API_KEY": "k-test", "COGNEE_BASE_URL": "https://tenant-x.aws.cognee.ai/", "COGNEE_TENANT_ID": "t1"}
RESULT = {
    "slug": "small-town-blooms", "url": "https://smalltownbloomsky.com",
    "read": {"before": 68, "after": 92},
    "do_fetch": {"before": {"done": 0, "total": 4}, "after": {"done": 2, "total": 4}},
    "top_problems": [{"id": "bot_challenge", "severity": "high", "detail": "AI agent gets HTTP 403."}],
    "visible": False, "visibility_query": "florist in KY",
}


class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


class FakeClient:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.calls = resp, exc, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, **kw):
        self.calls.append((url, kw))
        if self.exc:
            raise self.exc
        return self.resp


@mock.patch.dict(os.environ, ENV)
class CogneeBackendTest(unittest.TestCase):
    def test_summary_plain_english(self):
        s = cb.summarize("small-town-blooms", RESULT, {"name": "Small Town Blooms", "category": "florist", "state": "KY"})
        self.assertIn("Small Town Blooms (florist, KY)", s)
        self.assertIn("68 -> 92", s)
        self.assertIn("0/4 -> 2/4", s)
        self.assertIn("HTTP 403", s)

    def test_remember_request_shape(self):
        fc = FakeClient(FakeResp(200, {"status": "ok"}))
        with mock.patch.object(cb, "_client", return_value=fc):
            self.assertTrue(cb.remember("small-town-blooms", RESULT))
        url, kw = fc.calls[0]
        self.assertEqual(url, "https://tenant-x.aws.cognee.ai/api/v1/remember")
        self.assertEqual(kw["headers"], {"X-Api-Key": "k-test", "X-Tenant-Id": "t1"})
        self.assertEqual(kw["data"]["datasetName"], "landfall_audits")
        self.assertEqual(kw["data"]["run_in_background"], "true")
        self.assertEqual(kw["files"][0][0], "raw_data")
        self.assertIn("smalltownbloomsky.com", kw["files"][0][1][1])

    def test_recall_request_shape_and_parse(self):
        body = [{"search_result": ["CloudFront blocks agents"], "dataset_name": "landfall_audits"}]
        fc = FakeClient(FakeResp(200, body))
        with mock.patch.object(cb, "_client", return_value=fc):
            rows = cb.recall("who blocks agents?")
        url, kw = fc.calls[0]
        self.assertEqual(url, "https://tenant-x.aws.cognee.ai/api/v1/recall")
        self.assertEqual(kw["json"], {"query": "who blocks agents?", "datasets": ["landfall_audits"]})
        self.assertEqual(kw["headers"]["Content-Type"], "application/json")
        self.assertEqual(rows, [{"text": "CloudFront blocks agents"}])

    def test_warming_up_is_empty(self):
        body = [{"source": "system", "status": "memory_warming_up", "text": "Memory is still warming up"}]
        with mock.patch.object(cb, "_client", return_value=FakeClient(FakeResp(200, body))), mock.patch("sys.stderr"):
            self.assertEqual(cb.recall("q"), [])

    def test_failures_never_raise(self):
        for fc in (FakeClient(exc=TimeoutError("slow")), FakeClient(FakeResp(500, {"detail": "boom"}))):
            with mock.patch.object(cb, "_client", return_value=fc), mock.patch("sys.stderr"):
                self.assertFalse(cb.remember("x", RESULT))
                self.assertEqual(cb.recall("q"), [])

    def test_no_key_is_noop(self):
        with mock.patch.dict(os.environ, {"COGNEE_API_KEY": ""}):
            self.assertFalse(cb.remember("x", RESULT))
            self.assertEqual(cb.recall("q"), [])


if __name__ == "__main__":
    unittest.main()
