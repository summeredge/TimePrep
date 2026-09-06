"""在独立进程中打开 Windows 原生文件或目录选择框。"""

from __future__ import annotations

import argparse
import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog


def _initial_dir(value: str) -> str:
    if not value:
        return str(Path.home())
    candidate = Path(value).expanduser()
    if candidate.is_dir():
        return str(candidate)
    return str(candidate.parent if candidate.parent != candidate else Path.home())


def _pick(mode: str, initial_path: str) -> dict:
    root = tk.Tk()
    root.withdraw()
    try:
        initial_dir = _initial_dir(initial_path)
        if mode == "file":
            selected = filedialog.askopenfilename(
                parent=root,
                initialdir=initial_dir,
                title="选择输入文件",
                filetypes=(("数据文件", "*.csv *.txt *.xls *.xlsx *.xlsm"),),
            )
        else:
            selected = filedialog.askdirectory(
                parent=root,
                initialdir=initial_dir,
                title="选择输出目录",
                mustexist=True,
            )
    finally:
        root.destroy()

    return {"cancelled": True} if not selected else {"path": selected}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("file", "dir"))
    parser.add_argument("--initial", default="")
    args = parser.parse_args()
    print(json.dumps(_pick(args.mode, args.initial), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
