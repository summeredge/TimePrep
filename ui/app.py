"""tkinter GUI：文件选择 / 数据预览 / 变量配置 / 执行处理。"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from core import processor
from core.filter import DEFAULT_PARAMS, METHOD_LABELS, METHODS, format_params, parse_params
from core.resample import PRESET_RULES

FILE_TYPES = [
    ("数据文件", "*.csv *.txt *.xls *.xlsx *.xlsm"),
    ("CSV", "*.csv"),
    ("TXT", "*.txt"),
    ("Excel", "*.xls *.xlsx *.xlsm"),
    ("所有文件", "*.*"),
]

NO_RESAMPLE = ""


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("工业时序数据预处理工具 MVP")
        self.root.geometry("900x700")

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.rule_var = tk.StringVar(value=NO_RESAMPLE)
        self.status_var = tk.StringVar(value="请选择输入文件")
        self.output_path_var = tk.StringVar(value="")

        self.info = {
            "file": tk.StringVar(value="-"),
            "rows": tk.StringVar(value="-"),
            "range": tk.StringVar(value="-"),
            "time": tk.StringVar(value="-"),
            "vars": tk.StringVar(value="-"),
        }
        self.rows: list[dict] = []

        self._build_file_section()
        self._build_preview_section()
        self._build_variable_section()
        self._build_execute_section()

    # ---------- 界面构建 ----------
    def _build_file_section(self) -> None:
        box = ttk.LabelFrame(self.root, text="文件", padding=8)
        box.pack(fill="x", padx=10, pady=(10, 5))
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="输入文件:").grid(row=0, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.input_var).grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Button(box, text="浏览...", command=self._choose_input).grid(row=0, column=2)

        ttk.Label(box, text="输出目录:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(box, textvariable=self.output_var).grid(
            row=1, column=1, sticky="ew", padx=5, pady=(6, 0)
        )
        ttk.Button(box, text="浏览...", command=self._choose_output).grid(row=1, column=2, pady=(6, 0))

    def _build_preview_section(self) -> None:
        box = ttk.LabelFrame(self.root, text="数据预览", padding=8)
        box.pack(fill="x", padx=10, pady=5)
        box.columnconfigure(1, weight=1)
        box.columnconfigure(3, weight=1)

        ttk.Label(box, text="文件名:").grid(row=0, column=0, sticky="w")
        ttk.Label(box, textvariable=self.info["file"]).grid(row=0, column=1, sticky="w")
        ttk.Label(box, text="数据行数:").grid(row=0, column=2, sticky="w", padx=(20, 0))
        ttk.Label(box, textvariable=self.info["rows"]).grid(row=0, column=3, sticky="w")

        ttk.Label(box, text="时间范围:").grid(row=1, column=0, sticky="w")
        ttk.Label(box, textvariable=self.info["range"]).grid(row=1, column=1, sticky="w")
        ttk.Label(box, text="时间列:").grid(row=1, column=2, sticky="w", padx=(20, 0))
        ttk.Label(box, textvariable=self.info["time"]).grid(row=1, column=3, sticky="w")

        ttk.Label(box, text="变量列表:").grid(row=2, column=0, sticky="nw", pady=(6, 0))
        self.variable_text = tk.Text(box, height=3, wrap="word", relief="solid", borderwidth=1)
        self.variable_text.grid(row=2, column=1, columnspan=3, sticky="ew", padx=5, pady=(6, 0))
        self.variable_text.insert("1.0", "-")
        self.variable_text.configure(state="disabled")

        ttk.Label(box, text="重采样周期:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        rule_box = ttk.Frame(box)
        rule_box.grid(row=3, column=1, sticky="w", padx=5, pady=(8, 0))
        ttk.Combobox(
            rule_box,
            textvariable=self.rule_var,
            values=[NO_RESAMPLE, *PRESET_RULES],
            width=10,
        ).pack(side="left")
        ttk.Label(rule_box, text="留空=不重采样；可直接输入自定义周期，如 30s / 15min / 1H").pack(
            side="left", padx=(8, 0)
        )

    def _build_variable_section(self) -> None:
        box = ttk.LabelFrame(self.root, text="变量处理配置", padding=8)
        box.pack(fill="both", expand=True, padx=10, pady=5)

        toolbar = ttk.Frame(box)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="全选", command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(toolbar, text="全不选", command=lambda: self._set_all(False)).pack(
            side="left", padx=5
        )
        ttk.Label(toolbar, text="勾选的变量才会滤波；未勾选变量原样输出").pack(side="left", padx=10)

        self.scroll = _ScrollableFrame(box)
        self.scroll.pack(fill="both", expand=True, pady=(6, 0))
        self._build_table_header()

    def _build_table_header(self) -> None:
        header = self.scroll.inner
        ttk.Label(header, text="处理", width=6).grid(row=0, column=0, padx=(2, 6))
        ttk.Label(header, text="变量").grid(row=0, column=1, sticky="w")
        ttk.Label(header, text="滤波方式").grid(row=0, column=2, sticky="w", padx=(10, 0))
        ttk.Label(header, text="参数").grid(row=0, column=3, sticky="w", padx=(10, 0))
        ttk.Separator(header, orient="horizontal").grid(
            row=1, column=0, columnspan=4, sticky="ew", pady=4
        )

    def _build_execute_section(self) -> None:
        box = ttk.LabelFrame(self.root, text="执行", padding=8)
        box.pack(fill="x", padx=10, pady=(5, 10))

        bar = ttk.Frame(box)
        bar.pack(fill="x")
        ttk.Button(bar, text="开始处理", command=self._run).pack(side="left")
        ttk.Label(bar, textvariable=self.status_var).pack(side="left", padx=10)

        ttk.Label(box, text="输出文件:").pack(anchor="w", pady=(8, 0))
        ttk.Label(box, textvariable=self.output_path_var, foreground="#0a5f9c", wraplength=850).pack(
            anchor="w"
        )

        self.log = tk.Text(box, height=5, wrap="word", relief="solid", borderwidth=1)
        self.log.pack(fill="x", pady=(6, 0))

    # ---------- 交互 ----------
    def _choose_input(self) -> None:
        path = filedialog.askopenfilename(title="选择输入文件", filetypes=FILE_TYPES)
        if not path:
            return
        self.input_var.set(path)
        if not self.output_var.get():
            self.output_var.set(str(Path(path).parent))
        self._load_preview()

    def _choose_output(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_var.set(path)

    def _load_preview(self) -> None:
        path = self.input_var.get()
        if not path:
            return
        try:
            loaded = processor.inspect_file(path)
        except Exception as exc:  # noqa: BLE001 - 预览阶段统一提示
            messagebox.showerror("读取失败", str(exc))
            self.status_var.set("读取失败")
            return

        self.info["file"].set(loaded.source.name)
        self.info["rows"].set(f"{loaded.rows} 行")
        self.info["range"].set(loaded.time_range_text)
        self.info["time"].set(loaded.time_column)
        self.info["vars"].set(f"{len(loaded.columns)} 个")
        self._set_text(self.variable_text, "、".join(loaded.columns))

        self._build_variable_rows(loaded.frame)
        self.status_var.set(f"已载入 {loaded.source.name}，共 {len(loaded.columns)} 个变量")
        self._log(f"读取成功：{loaded.source.name}，{loaded.rows} 行，时间列 {loaded.time_column}\n")

    def _build_variable_rows(self, frame) -> None:
        for row in self.rows:
            for widget in row["widgets"]:
                widget.destroy()
        self.rows = []

        for offset, column in enumerate(frame.columns):
            name = str(column)
            index = offset + 2  # 0/1 为表头与分隔线
            enabled = tk.BooleanVar(value=False)
            method = tk.StringVar(value=METHODS[0])
            params = tk.StringVar(value="")

            check = ttk.Checkbutton(
                self.scroll.inner, variable=enabled, command=self._update_status
            )
            check.grid(row=index, column=0, padx=(2, 6))

            label = ttk.Label(self.scroll.inner, text=name, width=24, anchor="w")
            label.grid(row=index, column=1, sticky="w")

            combo = ttk.Combobox(
                self.scroll.inner,
                textvariable=method,
                values=[METHOD_LABELS[m] for m in METHODS],
                state="readonly",
                width=22,
            )
            combo.grid(row=index, column=2, sticky="w", padx=(10, 0))
            combo.bind(
                "<<ComboboxSelected>>",
                lambda _event, m=method, p=params: self._on_method_changed(m, p),
            )

            entry = ttk.Entry(self.scroll.inner, textvariable=params, width=30)
            entry.grid(row=index, column=3, sticky="w", padx=(10, 0))

            self.rows.append(
                {
                    "name": name,
                    "enabled": enabled,
                    "method": method,
                    "params": params,
                    "widgets": (check, label, combo, entry),
                }
            )

        self.scroll.refresh()

    def _on_method_changed(self, method_var: tk.StringVar, params_var: tk.StringVar) -> None:
        key = self._method_key(method_var.get())
        params_var.set(format_params(DEFAULT_PARAMS.get(key, {})))

    @staticmethod
    def _method_key(label: str) -> str:
        for key, text in METHOD_LABELS.items():
            if text == label:
                return key
        return METHODS[0]

    def _set_all(self, value: bool) -> None:
        for row in self.rows:
            row["enabled"].set(value)
        self._update_status()

    def _update_status(self) -> None:
        count = sum(1 for row in self.rows if row["enabled"].get())
        self.status_var.set(f"已选择 {count} 个变量待处理")

    def _collect_config(self) -> processor.ProcessConfig:
        config = processor.ProcessConfig(resample_rule=self.rule_var.get().strip())
        for row in self.rows:
            method = self._method_key(row["method"].get())
            config.variables[row["name"]] = processor.VariableConfig(
                enabled=row["enabled"].get(),
                method=method,
                params=parse_params(row["params"].get()),
            )
        return config

    def _run(self) -> None:
        input_path = self.input_var.get().strip()
        output_dir = self.output_var.get().strip()
        if not input_path:
            messagebox.showwarning("缺少输入", "请先选择输入文件")
            return
        if not output_dir:
            messagebox.showwarning("缺少输出目录", "请先选择输出目录")
            return

        self.status_var.set("处理中...")
        self.root.update_idletasks()

        def progress(text: str) -> None:
            self.status_var.set(text)
            self.root.update_idletasks()

        try:
            config = self._collect_config()
            result = processor.process_file(input_path, output_dir, config, progress=progress)
        except Exception as exc:  # noqa: BLE001 - GUI 中统一展示失败原因
            self.status_var.set("处理失败")
            self._log(f"{type(exc).__name__}: {exc}\n")
            messagebox.showerror("处理失败", f"{type(exc).__name__}: {exc}")
            return

        self.output_path_var.set(str(result.output_path))
        self.status_var.set(f"完成：{result.rows_in} → {result.rows_out} 行")
        self._log(
            f"完成：{result.rows_in} → {result.rows_out} 行；"
            f"滤波变量 {len(result.processed)} 个：{', '.join(result.processed) or '无'}\n"
            f"输出：{result.output_path}\n"
        )
        for message in result.messages:
            self._log(f"  - {message}\n")
        messagebox.showinfo("处理完成", f"已输出：\n{result.output_path}")

    # ---------- 工具 ----------
    @staticmethod
    def _set_text(widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _log(self, text: str) -> None:
        self.log.insert("end", text)
        self.log.see("end")


class _ScrollableFrame(ttk.Frame):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)

        self.inner.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.inner.bind("<MouseWheel>", self._on_wheel)

    def refresh(self) -> None:
        self.inner.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._bind_children(self.inner)

    def _bind_children(self, widget) -> None:
        for child in widget.winfo_children():
            child.bind("<MouseWheel>", self._on_wheel)
            self._bind_children(child)

    def _on_wheel(self, event) -> None:
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
