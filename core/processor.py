"""处理流程编排：读取 → 时间排序 → 重采样 → 指定变量滤波 → 输出。"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import exporter, resample as resample_module
from .filter import NONE, filter_column
from .loader import LoadResult, load_file


@dataclass
class VariableConfig:
    """单个变量的处理配置。"""

    enabled: bool = False
    method: str = NONE
    params: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"enabled": self.enabled, "method": self.method, "params": dict(self.params)}


@dataclass
class ProcessConfig:
    """一次处理的完整配置。"""

    resample_rule: str = ""
    variables: dict[str, VariableConfig] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "resample_rule": self.resample_rule,
            "variables": {name: cfg.as_dict() for name, cfg in self.variables.items()},
        }


@dataclass
class ProcessResult:
    frame: pd.DataFrame
    output_path: Path | None
    messages: list[str] = field(default_factory=list)
    rows_in: int = 0
    rows_out: int = 0
    processed: list[str] = field(default_factory=list)
    time_range: str = "-"
    source_path: Path | None = None


RAW_SUFFIX = "_raw"
FILTERED_SUFFIX = "_filtered"


def process_data(
    input_path: str | Path,
    config: ProcessConfig,
    progress=None,
) -> ProcessResult:
    """读取 → 时间排序 → 重采样 → 指定变量滤波，不写文件。"""
    messages: list[str] = []

    loaded = load_file(input_path)
    _report(progress, f"已读取 {loaded.source.name}，{loaded.rows} 行")
    if loaded.dropped_rows:
        messages.append(f"丢弃 {loaded.dropped_rows} 行时间无法解析的数据")
    messages.append(f"时间列: {loaded.time_column}；时间范围: {loaded.time_range_text}")

    numeric_columns = list(resample_module.numeric_like_frame(loaded.frame).columns)
    numeric_names = {str(column) for column in numeric_columns}
    # 不重采样时保留全部列（含非数值列）；重采样后才按需求忽略非数值列
    if config.resample_rule and len(numeric_columns) < len(loaded.frame.columns):
        dropped = [c for c in loaded.frame.columns if c not in numeric_columns]
        messages.append(f"非数值列 {len(dropped)} 个，重采样后被忽略: {', '.join(map(str, dropped))}")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        frame = resample_module.resample(loaded.frame, config.resample_rule)
    messages.extend(str(item.message) for item in caught)
    if config.resample_rule:
        _report(progress, f"已重采样至 {config.resample_rule}，{len(frame)} 行")
        messages.append(f"重采样: {config.resample_rule}，{loaded.rows} → {len(frame)} 行")
    else:
        messages.append("未重采样，保留原始时间间隔")

    output = pd.DataFrame(index=frame.index)
    output.index.name = frame.index.name or "Timestamp"
    processed: list[str] = []

    for column in frame.columns:
        name = str(column)
        cfg = config.variables.get(name)
        if name not in numeric_names or cfg is None or not cfg.enabled:
            output[name] = frame[column]  # 未选择：原样输出
            continue

        raw = pd.to_numeric(frame[column], errors="coerce")
        output[f"{name}{RAW_SUFFIX}"] = raw

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            filtered = filter_column(frame[column], cfg.method, cfg.params)
        for item in caught:
            messages.append(f"[{name}] {item.message}")
        output[f"{name}{FILTERED_SUFFIX}"] = filtered
        processed.append(name)
        _report(progress, f"已滤波 {name}（{cfg.method}）")

    if not processed:
        messages.append("未选择任何变量进行滤波，输出为重采样后的原始数据")

    skipped = [n for n, c in config.variables.items() if c.enabled and n not in frame.columns]
    if skipped:
        messages.append(f"以下变量在重采样后不存在，已跳过: {', '.join(skipped)}")

    return ProcessResult(
        frame=output,
        output_path=None,
        messages=messages,
        rows_in=loaded.rows,
        rows_out=len(output),
        processed=processed,
        time_range=f"{output.index.min()} ~ {output.index.max()}" if len(output) else "-",
        source_path=Path(loaded.source),
    )


def process_file(
    input_path: str | Path,
    output_dir: str | Path,
    config: ProcessConfig,
    progress=None,
) -> ProcessResult:
    """兼容入口：执行完整流程并导出 CSV。"""
    result = process_data(input_path, config, progress)
    output_path = exporter.export_csv(result.frame, output_dir, result.source_path or input_path)
    result.output_path = output_path
    _report(progress, f"已写出 {output_path}")
    return result


def inspect_file(input_path: str | Path) -> LoadResult:
    """仅读取并预览，供 GUI 使用。"""
    return load_file(input_path)


def _report(progress, text: str) -> None:
    if progress:
        progress(text)
