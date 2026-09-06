"""重采样：统一时间轴，数值列按 mean 聚合。"""

from __future__ import annotations

import pandas as pd
from pandas.tseries.frequencies import to_offset

# 界面下拉框中的常用周期
PRESET_RULES = ("1s", "5s", "10s", "1min", "5min")


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
    """按周期重采样。数值列取均值，非数值列忽略。

    返回 DataFrame 的时间轴为均匀网格，空区间为 NaN（统一时间轴）。
    """
    rule = normalize_rule(rule)
    ordered = frame.sort_index()
    if rule is None:
        return ordered

    numeric = ordered.select_dtypes(include="number")
    if numeric.empty:
        raise ValueError("没有可用于重采样的数值列")
    return numeric.resample(rule).mean()
