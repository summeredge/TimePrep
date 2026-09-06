"""重采样：统一时间轴，numeric-like 列按 mean 聚合。"""

from __future__ import annotations

import pandas as pd
from pandas.tseries.frequencies import to_offset

# 界面下拉框中的常用周期
PRESET_RULES = ("1s", "5s", "10s", "1min", "5min")

# 至少四分之三的非空值可转为数字，允许少量 PI/DCS 质量字符串。
NUMERIC_LIKE_MIN_RATIO = 0.75


def numeric_like_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """返回可处理的 numeric-like 列，并将不可转换值变为 NaN。"""
    converted = {}
    for column in frame.columns:
        series = frame[column]
        try:
            numeric = pd.to_numeric(series, errors="coerce")
        except (TypeError, ValueError):
            continue
        non_empty = series.notna() & series.astype("string").str.strip().ne("")
        if non_empty.any() and numeric[non_empty].notna().mean() >= NUMERIC_LIKE_MIN_RATIO:
            converted[column] = numeric
    return pd.DataFrame(converted, index=frame.index)


def normalize_rule(rule: str | None) -> str | None:
    """校验并规范化周期字符串；空字符串/None 表示不重采样。"""
    if rule is None:
        return None
    text = str(rule).strip()
    if not text or text.lower() in ("none", "不重采样", "原始"):
        return None
    try:
        to_offset(text)
    except ValueError as exc:
        raise ValueError(f"无法识别的重采样周期: {text}（示例: 1s / 5min / 30s / 1H）") from exc
    return text


def resample(frame: pd.DataFrame, rule: str | None) -> pd.DataFrame:
    """按周期重采样。numeric-like 列取均值，纯文本列忽略。

    返回 DataFrame 的时间轴为均匀网格，空区间为 NaN（统一时间轴）。
    """
    rule = normalize_rule(rule)
    ordered = frame.sort_index()
    if rule is None:
        return ordered

    numeric = numeric_like_frame(ordered)
    if numeric.empty:
        raise ValueError("没有可用于重采样的数值列")
    return numeric.resample(rule).mean()
