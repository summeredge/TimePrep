"""滤波：按变量独立选择滤波方式与参数。

对外主接口 filter_column(series, method, params)。
短序列仍按现有规则返回原始数据；参数错误会抛出 ValueError。
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

NONE = "none"
MOVING_AVERAGE = "moving_average"
FIRST_ORDER_LOWPASS = "first_order_lowpass"
EWM = "ewm"

METHODS = (NONE, MOVING_AVERAGE, FIRST_ORDER_LOWPASS, EWM)

METHOD_LABELS = {
    NONE: "无滤波",
    MOVING_AVERAGE: "移动平均",
    FIRST_ORDER_LOWPASS: "一阶低通滤波",
    EWM: "指数移动平均",
}

DEFAULT_PARAMS = {
    NONE: {},
    MOVING_AVERAGE: {"window": 5},
    FIRST_ORDER_LOWPASS: {"tau": "10min"},
    EWM: {"alpha": 0.2},
}

# 少于该点数时不进行滤波，直接返回原始数据
_MIN_POINTS = 4


def filter_column(
    series: pd.Series,
    method: str = NONE,
    params: dict | None = None,
) -> pd.Series:
    """对单个变量做滤波，返回与输入同长度、同索引的 Series。

    缺失值处理：滤波前线性插值，
    滤波后原始缺失位置重新置为 NaN，不伪造数据点。
    """
    method = (method or NONE).lower()
    if method not in METHODS:
        raise ValueError(f"未知滤波方式: {method}（可选: {', '.join(METHODS)}）")

    merged = {**DEFAULT_PARAMS[method], **(params or {})}
    values = pd.to_numeric(series, errors="coerce").astype(float)
    values.name = series.name

    if method == FIRST_ORDER_LOWPASS:
        if not isinstance(values.index, pd.DatetimeIndex):
            raise ValueError("一阶低通滤波需要时间索引")
        _parse_tau(merged["tau"])

    if method == NONE or values.notna().sum() < _MIN_POINTS:
        return values

    filled = values.interpolate(limit_direction="both") if values.isna().any() else values
    result = _apply(filled.to_numpy(dtype=float), method, merged, values.index)
    filtered = pd.Series(result, index=values.index, name=series.name)
    filtered[values.isna()] = np.nan
    return filtered


def _apply(x: np.ndarray, method: str, params: dict, index: pd.Index) -> np.ndarray:
    if method == MOVING_AVERAGE:
        return _moving_average(x, params)
    if method == FIRST_ORDER_LOWPASS:
        return _first_order_lowpass(x, params, index)
    if method == EWM:
        return _ewm(x, params)
    raise ValueError(f"未知滤波方式: {method}")


def _moving_average(x: np.ndarray, params: dict) -> np.ndarray:
    window = int(params["window"])
    if window < 2:
        raise ValueError("移动平均窗口必须不小于 2")
    series = pd.Series(x)
    return series.rolling(window, min_periods=1).mean().to_numpy()


def _ewm(x: np.ndarray, params: dict) -> np.ndarray:
    alpha = float(params["alpha"])
    if not 0 < alpha <= 1:
        raise ValueError("指数移动平均系数必须大于 0 且不大于 1")
    return pd.Series(x).ewm(alpha=alpha, adjust=False).mean().to_numpy()


def _first_order_lowpass(x: np.ndarray, params: dict, index: pd.Index) -> np.ndarray:
    tau = _parse_tau(params["tau"])
    result = np.empty(len(x), dtype=float)
    result[0] = x[0]
    tau_seconds = tau.total_seconds()
    for position in range(1, len(x)):
        delta_seconds = (index[position] - index[position - 1]).total_seconds()
        alpha = -np.expm1(-delta_seconds / tau_seconds)
        result[position] = result[position - 1] + alpha * (x[position] - result[position - 1])
    return result


def _parse_tau(value) -> pd.Timedelta:
    try:
        tau = pd.to_timedelta(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("一阶低通时间常数必须是大于 0 的时间间隔") from exc
    if not isinstance(tau, pd.Timedelta) or pd.isna(tau) or tau <= pd.Timedelta(0):
        raise ValueError("一阶低通时间常数必须是大于 0 的时间间隔")
    return tau


def parse_params(text: str | None) -> dict:
    """解析参数文本，支持 'window=10, tau=5min' 与 JSON 两种写法。"""
    if text is None:
        return {}
    raw = str(text).strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except ValueError:
        pass

    result: dict = {}
    for part in raw.replace(";", ",").split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        result[key.strip()] = _to_number(value.strip())
    return result


def format_params(params: dict | None) -> str:
    if not params:
        return ""
    return ", ".join(f"{key}={value}" for key, value in params.items())


def _to_number(text: str):
    lowered = text.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text
