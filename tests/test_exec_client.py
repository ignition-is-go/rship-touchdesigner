import importlib.util
from pathlib import Path
import sys
import unittest


MOD_DIR = Path(__file__).parents[1] / "py" / "mod"
if str(MOD_DIR) not in sys.path:
    sys.path.insert(0, str(MOD_DIR))

MODULE_PATH = MOD_DIR / "exec.py"
SPEC = importlib.util.spec_from_file_location("rship_exec", MODULE_PATH)
EXEC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXEC)


class ExecClientResponseHandlerTests(unittest.TestCase):
    def setUp(self):
        self.client = EXEC.ExecClient()
        self.client.log = lambda message: None

    def test_query_response_handler_is_removed_before_callback(self):
        calls = []
        self.client.queryHandlers["query-tx"] = lambda response: calls.append(response.tx)

        self.client.parseQueryResponse({"tx": "query-tx", "upserts": []})

        self.assertEqual(calls, ["query-tx"])
        self.assertNotIn("query-tx", self.client.queryHandlers)

    def test_query_error_removes_handler(self):
        self.client.queryHandlers["query-tx"] = lambda response: None

        self.client.parseQueryError({"tx": "query-tx", "queryId": "Q", "message": "failed"})

        self.assertNotIn("query-tx", self.client.queryHandlers)

    def test_report_response_handler_is_removed_before_callback(self):
        calls = []
        self.client.reportHandlers["report-tx"] = lambda response: calls.append(response.tx)

        self.client.parseReportResponse({"tx": "report-tx", "response": {}})

        self.assertEqual(calls, ["report-tx"])
        self.assertNotIn("report-tx", self.client.reportHandlers)

    def test_report_error_removes_handler(self):
        self.client.reportHandlers["report-tx"] = lambda response: None

        self.client.parseReportError({"tx": "report-tx", "reportId": "R", "message": "failed"})

        self.assertNotIn("report-tx", self.client.reportHandlers)


if __name__ == "__main__":
    unittest.main()
