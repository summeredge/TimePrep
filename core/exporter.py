"""结果导出：CSV。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

OUTPUT_SUFFIX = "_processed"


def default_output_path(output_dir: str | Path, source: str | Path) -> Path:
    source = Path(source)
    return Path(output_dir) / f"{source.stem}{OUTPUT_SUFFIX}.csv"


def export_csv(
    frame: pd.DataFrame,
    output_dir: str | Path,
    source: str | Path,
) -> Path:
    """写出 CSV（时间列 + 所有变量），返回输出文件路径。"""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = default_output_path(directory, source)
    frame.to_csv(path, index=True, index_label=frame.index.name or "Timestamp")
    return path
