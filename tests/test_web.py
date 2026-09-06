import http.client
import json
import os
import tempfile
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

    def test_health_reports_current_process_and_api_version(self):
        status, result = self.request("GET", "/api/health")

        self.assertEqual(status, 200)
        self.assertEqual(
            result,
            {"app": "TimePrep", "apiVersion": web_server.WEB_API_VERSION, "pid": os.getpid()},
        )

    def test_methods_reports_api_version(self):
        status, result = self.request("GET", "/api/methods")

        self.assertEqual(status, 200)
        self.assertEqual(result["apiVersion"], web_server.WEB_API_VERSION)

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

    def test_page_is_frozen_at_server_start(self):
        with tempfile.TemporaryDirectory() as directory:
            web_dir = Path(directory)
            page = web_dir / "index.html"
            page.write_text("startup page", encoding="utf-8")
            with mock.patch.object(web_server, "WEB_DIR", web_dir):
                httpd = web_server.ThreadingHTTPServer((web_server.HOST, 0), web_server.Handler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                page.write_text("updated page", encoding="utf-8")
                connection = http.client.HTTPConnection(*httpd.server_address, timeout=5)
                connection.request("GET", "/")
                response = connection.getresponse()
                body = response.read().decode("utf-8")
                connection.close()
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=2)

        self.assertEqual(response.status, 200)
        self.assertEqual(body, "startup page")

    def test_frontend_checks_api_version_and_blocks_actions_on_mismatch(self):
        page = (Path(web_server.WEB_DIR) / "index.html").read_text(encoding="utf-8")

        self.assertIn("const EXPECTED_API_VERSION = 2;", page)
        self.assertIn("meta.apiVersion !== EXPECTED_API_VERSION", page)
        self.assertIn("TimePrep 前后端版本不一致，请重新启动 TimePrep 服务。", page)
        self.assertGreaterEqual(page.count("if (!requireApi()) return;"), 4)

    def test_default_port_tries_next_port_when_occupied_by_unknown_service(self):
        replacement = object()
        with (
            mock.patch.object(
                web_server,
                "ThreadingHTTPServer",
                side_effect=[OSError("occupied"), replacement],
            ) as factory,
            mock.patch.object(web_server, "_is_compatible_timeprep", return_value=False),
        ):
            server = web_server._create_server(web_server.DEFAULT_PORT, auto_select=True)

        self.assertIs(server, replacement)
        self.assertEqual(
            factory.call_args_list,
            [
                mock.call((web_server.HOST, web_server.DEFAULT_PORT), web_server.Handler),
                mock.call((web_server.HOST, web_server.DEFAULT_PORT + 1), web_server.Handler),
            ],
        )

    def test_default_port_reuses_confirmed_compatible_service(self):
        with (
            mock.patch.object(web_server, "ThreadingHTTPServer", side_effect=OSError("occupied")) as factory,
            mock.patch.object(web_server, "_is_compatible_timeprep", return_value=True),
        ):
            server = web_server._create_server(web_server.DEFAULT_PORT, auto_select=True)

        self.assertIsNone(server)
        factory.assert_called_once_with(
            (web_server.HOST, web_server.DEFAULT_PORT), web_server.Handler
        )

    def test_explicit_port_conflict_is_not_changed(self):
        with mock.patch.object(
            web_server, "ThreadingHTTPServer", side_effect=OSError("occupied")
        ) as factory:
            with self.assertRaises(OSError):
                web_server._create_server(9000, auto_select=False)

        factory.assert_called_once_with((web_server.HOST, 9000), web_server.Handler)

    def test_old_directory_api_and_page_picker_are_gone(self):
        status, _ = self.request("GET", "/api/list")
        self.assertEqual(status, 404)
        page = (Path(web_server.WEB_DIR) / "index.html").read_text(encoding="utf-8")
        for name in ("openPicker", "listDir", "pickParent", "pickCurrentDir", "/api/list"):
            self.assertNotIn(name, page)


if __name__ == "__main__":
    unittest.main()
