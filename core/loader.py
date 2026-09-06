"""数据读取：CSV / Excel / TXT，自动识别时间列并设为 DatetimeIndex。

不修改源文件，不做任何数值强制转换（PI/DCS 导出中的 "Bad"/"Scan Off" 等
质量字符串会原样保留，由后续模块按需处理）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# 优先匹配的时间列名（忽略大小写与首尾空格）
TIME_COLUMN_CANDIDATES = ("time", "timestamp", "date", "datetime")

SUPPORTED_SUFFIXES = (".csv", ".txt", ".xls", ".xlsx", ".xlsm")

# 第一列作为时间列时，允许的最小有效解析比例
_MIN_PARSE_RATIO = 0.8


@dataclass
class LoadResult:
    """读取结果。"""

    frame: pd.DataFrame  # index 为 DatetimeIndex，列为原始变量
    source: Path
    time_column: str
    rows: int
    columns: list[str] = field(default_factory=list)
    dropped_rows: int = 0  # 时间列无法解析而被丢弃的行数
    start: pd.Timestamp | None = None
    end: pd.Timestamp | None = None

    @property
    def time_range_text(self) -> str:
        if self.start is None or self.end is None:
            return "-"
        return f"{self.start} ~ {self.end}"


def load_file(path: str | Path) -> LoadResult:
    """读取单个数据文件，自动识别时间列。"""
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"文件不存在: {source}")
    if source.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"不支持的文件类型: {source.suffix}（支持 {', '.join(SUPPORTED_SUFFIXES)}）"
        )

    raw = _read_raw(source)
    if raw.empty:
        raise ValueError("文件为空或没有解析到数据行")

    time_column = _detect_time_column(raw)
    if time_column is None:
        raise ValueError(
            "未找到时间列：请确认存在 Time / Timestamp / Date / Datetime 列，"
            "或第一列为可解析的时间文本"
        )

    timestamps = to_datetime(raw[time_column])
    frame = raw.drop(columns=[time_column]).copy()
    valid = timestamps.notna()
    frame = frame.loc[valid]
    frame.index = pd.DatetimeIndex(timestamps[valid], name=str(time_column))

    index = frame.index
    return LoadResult(
        frame=frame,
        source=source,
        time_column=str(time_column),
        rows=len(frame),
        columns=[str(c) for c in frame.columns],
        dropped_rows=int((~valid).sum()),
        start=index.min() if len(index) else None,
        end=index.max() if len(index) else None,
    )


def to_datetime(values: pd.Series) -> pd.Series:
    """解析时间列；无法解析的位置为 NaT。兼容混合时间格式（pandas >= 2 严格模式）。"""
    try:
        return pd.to_datetime(values, errors="coerce", format="mixed")
    except (TypeError, ValueError):
        return pd.to_datetime(values, errors="coerce")


def _read_raw(source: Path) -> pd.DataFrame:
    suffix = source.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(source)
    if suffix == ".txt":
        # 自动嗅探分隔符（制表符 / 逗号 / 分号 / 空格）
        return pd.read_csv(source, sep=None, engine="python")
    return pd.read_excel(source)


def _detect_time_column(raw: pd.DataFrame) -> str | None:
    for column in raw.columns:
        if str(column).strip().lower() in TIME_COLUMN_CANDIDATES:
            return column

    first = raw.columns[0]
    if pd.api.types.is_numeric_dtype(raw[first]):
        return None
    parsed = to_datetime(raw[first])
    if len(parsed) and parsed.notna().mean() >= _MIN_PARSE_RATIO:
        return first
    return None
