"""本地网页服务：仅监听 127.0.0.1，复用 core 模块完成处理。

启动: python web/server.py [port]
依赖: 仅标准库（http.server），不引入 Web 框架。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from core import processor  # noqa: E402
from core.filter import DEFAULT_PARAMS, METHOD_LABELS, METHODS, format_params, parse_params  # noqa: E402
from core.loader import SUPPORTED_SUFFIXES  # noqa: E402
from core.resample import PRESET_RULES  # noqa: E402

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
UPLOAD_DIR = ROOT / "uploads"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path)
        path = route.path

        if path in ("/", "/index.html"):
            self._html(WEB_DIR / "index.html")
            return
        if path == "/api/methods":
            self._json(
                {
                    "methods": [
                        {
                            "key": key,
                            "label": METHOD_LABELS[key],
                            "defaultParams": format_params(DEFAULT_PARAMS[key]),
                        }
                        for key in METHODS
                    ],
                    "presetRules": ["", *PRESET_RULES],
                }
            )
            return
        if path in ("/api/pick-file", "/api/pick-dir"):
            query = parse_qs(route.query)
            initial_path = query.get("path", [""])[0]
            mode = "file" if path.endswith("file") else "dir"
            try:
                self._json(_pick_native(mode, initial_path))
            except Exception as exc:  # noqa: BLE001 - 统一转成接口错误
                self._json({"error": f"{type(exc).__name__}: {exc}"}, status=500)
            return
        self._json({"error": f"未知接口: {path}"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/upload":
            name = unquote(parse_qs(parsed.query).get("name", [""])[0])
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            try:
                self._json(_save_upload(name, body))
            except Exception as exc:  # noqa: BLE001
                self._json({"error": f"{type(exc).__name__}: {exc}"}, status=400)
            return

        try:
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except (ValueError, TypeError):
            payload = {}

        try:
            if path == "/api/preview":
                self._json(_preview(payload.get("path", "")))
            elif path == "/api/process":
                self._json(_process(payload))
            else:
                self._json({"error": f"未知接口: {path}"}, status=404)
        except Exception as exc:  # noqa: BLE001 - 统一转成接口错误
            self._json({"error": f"{type(exc).__name__}: {exc}"}, status=400)

    # ---------- 输出 ----------
    def _html(self, file: Path) -> None:
        body = file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))


def _save_upload(name: str, body: bytes) -> dict:
    """保存页面拖放进来的文件。浏览器不暴露本地绝对路径，只能上传副本。"""
    safe = Path(name).name.strip()
    if not safe or safe in (".", ".."):
        raise ValueError("无效的文件名")
    if Path(safe).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"不支持的文件类型: {Path(safe).suffix}")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / safe
    target.write_bytes(body)
    return {"path": str(target), "name": safe, "size": len(body)}


def _parse_dialog_result(stdout: str) -> dict:
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("原生选择框返回了无效结果") from exc

    if not isinstance(result, dict):
        raise RuntimeError("原生选择框返回了无效结果")
    if result.get("cancelled") is True:
        return {"cancelled": True}

    selected = result.get("path")
    if not isinstance(selected, str) or not selected.strip():
        raise RuntimeError("原生选择框未返回路径")
    return {"path": selected.strip()}


def _run_native_dialog(mode: str, initial_path: str) -> dict:
    command = [sys.executable, str(WEB_DIR / "native_dialog.py"), mode]
    if initial_path:
        command.extend(("--initial", initial_path))

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("原生选择框超时") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(detail or f"helper 退出码 {completed.returncode}")
    return _parse_dialog_result(completed.stdout)


def _pick_native(mode: str, initial_path: str) -> dict:
    result = _run_native_dialog(mode, initial_path)
    if result.get("cancelled"):
        return result
    return {"path": str(Path(result["path"]).expanduser().resolve())}


def _preview(path: str) -> dict:
    loaded = processor.inspect_file(path)
    frame = loaded.frame
    return {
        "file": loaded.source.name,
        "path": str(loaded.source),
        "rows": loaded.rows,
        "timeColumn": loaded.time_column,
        "timeRange": loaded.time_range_text,
        "droppedRows": loaded.dropped_rows,
        "columns": [
            {"name": name, "numeric": bool(pd.api.types.is_numeric_dtype(frame[name]))}
            for name in loaded.columns
        ],
    }


def _process(payload: dict) -> dict:
    input_path = payload.get("inputPath", "").strip()
    output_dir = payload.get("outputDir", "").strip()
    if not input_path:
        raise ValueError("请先选择输入文件")
    if not output_dir:
        raise ValueError("请先选择输出目录")

    config = processor.ProcessConfig(resample_rule=payload.get("rule", "").strip())
    for name, item in (payload.get("variables") or {}).items():
        config.variables[name] = processor.VariableConfig(
            enabled=bool(item.get("enabled")),
            method=item.get("method", METHODS[0]),
            params=parse_params(item.get("params", "")),
        )

    result = processor.process_file(input_path, output_dir, config)

    head = result.frame.head(5).reset_index()
    rows = [
        [_jsonable(value) for value in record] for record in head.itertuples(index=False)
    ]
    return {
        "outputPath": str(result.output_path),
        "rowsIn": result.rows_in,
        "rowsOut": result.rows_out,
        "processed": result.processed,
        "messages": result.messages,
        "previewColumns": [str(column) for column in head.columns],
        "previewRows": rows,
    }


def _jsonable(value):
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return str(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    return str(value)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("ITST_PORT", DEFAULT_PORT))
    url = f"http://{HOST}:{port}/"
    try:
        server = ThreadingHTTPServer((HOST, port), Handler)
    except OSError as exc:
        print(f"无法启动服务: {exc}")
        print(f"请更换端口后重试，例如: python web/server.py {port + 1}")
        sys.exit(1)

    print(f"服务已启动: {url}")
    print("关闭此窗口即停止服务。")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止服务")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
