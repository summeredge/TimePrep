import http.client
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

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

    def setUp(self):
        self.httpd.pending_result = None

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
        self.assertEqual(
            [(item["key"], item["label"], item["defaultParams"]) for item in result["methods"]],
            [
                ("none", "无滤波", ""),
                ("moving_average", "移动平均", "window=5"),
                ("first_order_lowpass", "一阶低通滤波", "tau=10min"),
                ("ewm", "指数移动平均 (EMA)", "alpha=0.2"),
            ],
        )

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

    def test_preview_marks_numeric_like_columns_processable(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "industrial.csv"
            pd.DataFrame(
                {
                    "Time": pd.date_range("2026-09-01 10:00", periods=4, freq="min"),
                    "TIC101": [85.1, 85.3, "Bad", 85.4],
                    "PIC102": [10.1, "Scan Off", 10.2, 10.4],
                    "Mode": ["AUTO", "AUTO", "AUTO", "MAN"],
                }
            ).to_csv(source, index=False)

            status, result = self.request("POST", "/api/preview", {"path": str(source)})

        self.assertEqual(status, 200)
        columns = {item["name"]: item for item in result["columns"]}
        self.assertTrue(columns["TIC101"]["processable"])
        self.assertTrue(columns["PIC102"]["processable"])
        self.assertFalse(columns["Mode"]["processable"])
        self.assertEqual(
            {name: item["numeric"] for name, item in columns.items()},
            {name: item["processable"] for name, item in columns.items()},
        )

    def test_api_process_needs_no_output_dir_and_does_not_create_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            pd.DataFrame(
                {
                    "Time": pd.date_range("2026-09-01 10:00", periods=4, freq="min"),
                    "A": [1.0, 2.0, 3.0, 4.0],
                }
            ).to_csv(source, index=False)

            status, result = self.request(
                "POST",
                "/api/process",
                {
                    "inputPath": str(source),
                    "rule": "",
                    "variables": {
                        "A": {
                            "enabled": True,
                            "method": "ewm",
                            "params": "alpha=0.5",
                        }
                    },
                },
            )
            self.assertFalse(list(root.glob("*_processed.csv")))

        self.assertEqual(status, 200)
        self.assertEqual(result["processed"], ["A"])
        self.assertEqual(result["exportable"], True)
        self.assertIsNone(result.get("outputPath"))
        self.assertNotIn("previewColumns", result)
        self.assertNotIn("previewRows", result)

    def test_api_export_uses_cached_result_and_source_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            pd.DataFrame(
                {
                    "Time": pd.date_range("2026-09-01 10:00", periods=4, freq="min"),
                    "A": [1.0, 2.0, 3.0, 4.0],
                }
            ).to_csv(source, index=False)
            self._process_source(source)

            status, result = self.request(
                "POST", "/api/export", {"outputDir": str(root / "output")}
            )

            self.assertEqual(status, 200)
            exported = Path(result["outputPath"])
            self.assertEqual(exported.name, "source_processed.csv")
            self.assertTrue(exported.is_file())

    def test_api_trend_returns_raw_filtered_on_shared_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            expected_time = pd.date_range("2026-09-01 10:00", periods=4, freq="min")
            pd.DataFrame(
                {"Time": expected_time, "A": [1.0, 2.0, 3.0, 4.0]}
            ).to_csv(source, index=False)
            self._process_source(source)

            status, result = self.request("GET", "/api/trend?variable=A")

        self.assertEqual(status, 200)
        self.assertEqual(result["variable"], "A")
        self.assertEqual(len(result["time"]), 4)
        self.assertEqual(
            [str(value) for value in result["time"]],
            [str(value) for value in expected_time],
        )
        self.assertEqual(result["raw"], [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(len(result["filtered"]), 4)

    def test_api_trend_downsamples_long_series_within_display_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            index = pd.date_range("2026-09-01 10:00", periods=50_000, freq="s")
            pd.DataFrame({"Time": index, "A": range(50_000)}).to_csv(source, index=False)
            self._process_source(source)

            status, result = self.request("GET", "/api/trend?variable=A")

        self.assertEqual(status, 200, result)
        self.assertLessEqual(len(result["time"]), web_server.TREND_MAX_POINTS)
        self.assertEqual(len(result["raw"]), len(result["time"]))
        self.assertEqual(len(result["filtered"]), len(result["time"]))
        self.assertEqual(str(result["time"][0]), str(index[0]))
        self.assertEqual(str(result["time"][-1]), str(index[-1]))

    def test_api_export_and_trend_reject_without_result(self):
        status, result = self.request(
            "POST", "/api/export", {"outputDir": r"C:\out"}
        )
        self.assertEqual(status, 400)
        self.assertIn("请先完成数据处理", result["error"])

        status, result = self.request("GET", "/api/trend?variable=A")
        self.assertEqual(status, 400)
        self.assertIn("请先完成数据处理", result["error"])

    def test_previewing_new_file_invalidates_cached_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            other = root / "other.csv"
            pd.DataFrame(
                {"Time": pd.date_range("2026-09-01", periods=2, freq="min"), "A": [1, 2]}
            ).to_csv(source, index=False)
            pd.DataFrame(
                {"Time": pd.date_range("2026-09-02", periods=2, freq="min"), "A": [3, 4]}
            ).to_csv(other, index=False)
            self._process_source(source)

            preview_status, _ = self.request("POST", "/api/preview", {"path": str(other)})
            self.assertEqual(preview_status, 200)
            export_status, export_result = self.request(
                "POST", "/api/export", {"outputDir": str(root / "output")}
            )
            trend_status, trend_result = self.request("GET", "/api/trend?variable=A")

        self.assertIsNone(self.httpd.pending_result)
        self.assertEqual(export_status, 400)
        self.assertIn("请先完成数据处理", export_result["error"])
        self.assertEqual(trend_status, 400)
        self.assertIn("请先完成数据处理", trend_result["error"])

    def test_failed_process_invalidates_cached_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            pd.DataFrame(
                {"Time": pd.date_range("2026-09-01", periods=2, freq="min"), "A": [1, 2]}
            ).to_csv(source, index=False)
            self._process_source(source)

            process_status, _ = self.request(
                "POST",
                "/api/process",
                {
                    "inputPath": str(root / "missing.csv"),
                    "rule": "",
                    "variables": {},
                },
            )
            export_status, export_result = self.request(
                "POST", "/api/export", {"outputDir": str(root / "output")}
            )

        self.assertEqual(process_status, 400)
        self.assertIsNone(self.httpd.pending_result)
        self.assertEqual(export_status, 400)
        self.assertIn("请先完成数据处理", export_result["error"])

    def _process_source(self, source):
        status, result = self.request(
            "POST",
            "/api/process",
            {
                "inputPath": str(source),
                "rule": "",
                "variables": {
                    "A": {
                        "enabled": True,
                        "method": "ewm",
                        "params": "alpha=0.5",
                    }
                },
            },
        )
        self.assertEqual(status, 200, result)
        return result

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

    def test_html_response_has_no_store_cache_control(self):
        connection = http.client.HTTPConnection(*self.address, timeout=5)
        connection.request("GET", "/")
        response = connection.getresponse()
        response.read()
        connection.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Cache-Control"), "no-store")

    def test_frontend_has_trend_workspace_and_export_but_no_result_table(self):
        page = (Path(web_server.WEB_DIR) / "index.html").read_text(encoding="utf-8")
        script = page[page.index("<script>") : page.index("</script>")]

        self.assertIn("趋势对比", page)
        self.assertIn('id="trendVar"', page)
        self.assertIn('id="trendCanvas"', page)
        self.assertIn('id="exportBtn"', page)
        self.assertIn("async function exportResult", script)
        self.assertIn("async function loadTrend", script)
        self.assertIn("JSON.stringify({ inputPath, rule, variables })", script)
        self.assertIn("processable", script)
        self.assertNotIn(".numeric", script)
        self.assertIn(
            "grid-template-columns: minmax(0, 35fr) minmax(0, 65fr)", page
        )
        self.assertNotIn("载入预览", page)
        self.assertNotIn("resultWrap", page)
        self.assertNotIn("resultHead", page)
        self.assertNotIn("resultBody", page)
        self.assertNotIn("renderResult()", page)

    def test_frontend_uses_hidden_only_and_invalidates_on_config_change(self):
        page = (Path(web_server.WEB_DIR) / "index.html").read_text(encoding="utf-8")
        script = page[page.index("<script>") : page.index("</script>")]

        self.assertIn('<div id="trendChartWrap" hidden>', page)
        self.assertNotIn(
            "#trendChartWrap { position: relative; display: none;", page
        )
        self.assertIn("$('" + "trendChartWrap" + "').hidden = false", script)
        self.assertIn("function invalidateConfig", script)
        self.assertIn("addEventListener('input', invalidateInput)", script)
        self.assertIn("addEventListener('change', invalidateInput)", script)
        self.assertIn("addEventListener('change', invalidateConfig)", script)
        self.assertIn("addEventListener('input', invalidateConfig)", script)
        self.assertIn("配置已修改，请重新处理", page)
        self.assertIn("输入文件已修改，请重新处理", page)

        trend_script = script[
            script.index("function bindTrendEvents") : script.index(
                "/* ---------- 原生文件/目录选择 ---------- */"
            )
        ]
        self.assertIn("loadTrend", trend_script)
        self.assertNotIn("invalidateConfig", trend_script)

    def test_frontend_has_no_global_permanent_button_disable(self):
        page = (Path(web_server.WEB_DIR) / "index.html").read_text(encoding="utf-8")
        script = page[page.index("<script>") : page.index("</script>")]

        self.assertIn("const EXPECTED_API_VERSION = 2;", page)
        self.assertIn("function applyMethods(meta)", script)
        self.assertIn("async function fetchService", script)
        self.assertIn("async function connectService", script)
        self.assertIn("async function reconnect", script)
        self.assertIn("apiReady = true;", script)
        self.assertIn("versionMismatch = false;", script)
        self.assertIn("TimePrep 前后端版本不一致", page)
        self.assertIn("重新检测服务", page)
        self.assertGreaterEqual(page.count("if (!requireApi()) return;"), 4)
        self.assertNotIn("document.querySelectorAll('button').forEach((button) => { button.disabled = true; })", script)

    def test_frontend_smoke_scenarios_via_node(self):
        """在 Node 中执行真实页面前端脚本，模拟 healthy / mismatch / 恢复 / 网络错误 场景。"""
        node = shutil.which("node") or shutil.which("node.exe")
        if not node:
            self.skipTest("Node.js 不可用，无法运行前端冒烟测试")
        project_root = Path(web_server.WEB_DIR).parent
        harness = Path(__file__).resolve().parent / "frontend_smoke.js"
        page = project_root / "web" / "index.html"
        for scenario, checks in {
            "healthy": [
                ("initial", True),
                ("state.apiReady", True),
                ("state.versionMismatch", False),
                ("runDisabled", False),
                ("reconnectHidden", True),
            ],
            "mismatch": [
                ("state.apiReady", False),
                ("state.versionMismatch", True),
                ("reconnectVisible", True),
                ("runDisabled", False),
            ],
            "error": [
                ("state.apiReady", False),
                ("state.versionMismatch", False),
                ("reconnectVisible", True),
                ("runDisabled", False),
            ],
            "healthy_recovery": [
                ("initial", True),
                ("initialState.apiReady", True),
                ("initialState.versionMismatch", False),
                ("afterMismatch.apiReady", False),
                ("afterMismatch.versionMismatch", True),
                ("reconnectVisibleAfterMismatch", True),
                ("afterRecover.apiReady", True),
                ("afterRecover.versionMismatch", False),
                ("runDisabled", False),
                ("reconnectHidden", True),
            ],
            "never_disable": [
                ("runDisabled", False),
                ("hasDisableAll", False),
            ],
            "preview_processable_rows": [
                ("varsText", "TIC101  |  Mode [非数值]"),
                ("tableRows", 1),
                ("rowNames", ["TIC101"]),
                ("status", "已载入 industrial.csv，共 2 个变量，其中 1 个可处理变量"),
            ],
        }.items():
            completed = subprocess.run(
                [node, str(harness), str(page), scenario],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=60,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertNotIn("error", result, result.get("error"))
            for key, expected in checks:
                actual = result
                for part in key.split("."):
                    actual = actual[part]
                self.assertEqual(
                    actual, expected, f"{scenario}: {key} 期望 {expected}，实际 {actual}"
                )

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
