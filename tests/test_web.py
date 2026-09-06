import http.client
import json
import threading
import unittest
from pathlib import Path
from unittest import mock

from web import server as web_server


class WebApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = web_server.ThreadingHTTPServer((web_server.HOST, 0), web_server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.address = cls.httpd.server_address

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def request(self, method, path, payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {} if body is None else {"Content-Type": "application/json"}
        connection = http.client.HTTPConnection(*self.address, timeout=5)
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        result = json.loads(response.read().decode("utf-8"))
        connection.close()
        return response.status, result

    def test_dialog_result_parser_handles_path_and_cancel(self):
        self.assertEqual(
            web_server._parse_dialog_result('{"path":"C:\\\\data.csv"}'),
            {"path": "C:\\data.csv"},
        )
        self.assertEqual(
            web_server._parse_dialog_result('{"cancelled":true}'),
            {"cancelled": True},
        )
        with self.assertRaises(RuntimeError):
            web_server._parse_dialog_result("not json")

    def test_pick_file_returns_absolute_path(self):
        selected = str(Path.home() / "data.csv")
        with mock.patch.object(web_server, "_run_native_dialog", return_value={"path": selected}):
            status, result = self.request("GET", "/api/pick-file")

        self.assertEqual(status, 200)
        self.assertEqual(result["path"], str(Path(selected).resolve()))
        self.assertTrue(Path(result["path"]).is_absolute())

    def test_pick_dir_returns_absolute_path(self):
        selected = str(Path.home())
        with mock.patch.object(web_server, "_run_native_dialog", return_value={"path": selected}):
            status, result = self.request("GET", "/api/pick-dir")

        self.assertEqual(status, 200)
        self.assertEqual(result["path"], str(Path(selected).resolve()))
        self.assertTrue(Path(result["path"]).is_absolute())

    def test_cancelled_pick_is_not_an_error(self):
        with mock.patch.object(web_server, "_run_native_dialog", return_value={"cancelled": True}):
            status, result = self.request("GET", "/api/pick-file")

        self.assertEqual(status, 200)
        self.assertEqual(result, {"cancelled": True})

    def test_helper_error_is_returned_as_api_error(self):
        with mock.patch.object(
            web_server, "_run_native_dialog", side_effect=RuntimeError("helper failed")
        ):
            status, result = self.request("GET", "/api/pick-dir")

        self.assertEqual(status, 500)
        self.assertIn("helper failed", result["error"])

    def test_preview_and_process_routes_still_dispatch(self):
        with mock.patch.object(web_server, "_preview", return_value={"preview": True}):
            status, result = self.request("POST", "/api/preview", {"path": "data.csv"})
        self.assertEqual((status, result), (200, {"preview": True}))

        with mock.patch.object(web_server, "_process", return_value={"processed": True}):
            status, result = self.request("POST", "/api/process", {})
        self.assertEqual((status, result), (200, {"processed": True}))

    def test_old_directory_api_and_page_picker_are_gone(self):
        status, _ = self.request("GET", "/api/list")
        self.assertEqual(status, 404)
        page = (Path(web_server.WEB_DIR) / "index.html").read_text(encoding="utf-8")
        for name in ("openPicker", "listDir", "pickParent", "pickCurrentDir", "/api/list"):
            self.assertNotIn(name, page)


if __name__ == "__main__":
    unittest.main()
