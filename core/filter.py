"""滤波：按变量独立选择滤波方式与参数。

对外主接口 filter_column(series, method, params)。
短序列、参数越界等情况会降级为原始数据并发出 UserWarning，不抛异常中断批处理。
"""

from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt, savgol_filter

NONE = "none"
MOVING_AVERAGE = "moving_average"
EWM = "ewm"
BUTTERWORTH = "butterworth"
SAVGOL = "savgol"

METHODS = (NONE, MOVING_AVERAGE, EWM, BUTTERWORTH, SAVGOL)

METHOD_LABELS = {
    NONE: "无滤波",
    MOVING_AVERAGE: "移动平均",
    EWM: "指数移动平均 (EMA)",
    BUTTERWORTH: "Butterworth 低通",
    SAVGOL: "Savitzky-Golay",
}

DEFAULT_PARAMS = {
    NONE: {},
    MOVING_AVERAGE: {"window": 5},
    EWM: {"alpha": 0.2},
    BUTTERWORTH: {"order": 3, "cutoff": 0.05},
    SAVGOL: {"window": 11, "polyorder": 2},
}

# 少于该点数时不进行滤波，直接返回原始数据
_MIN_POINTS = 4


def filter_column(
    series: pd.Series,
    method: str = NONE,
    params: dict | None = None,
) -> pd.Series:
    """对单个变量做滤波，返回与输入同长度、同索引的 Series。

    缺失值处理：滤波前线性插值（filtfilt 无法处理 NaN），
    滤波后原始缺失位置重新置为 NaN，不伪造数据点。
    """
    method = (method or NONE).lower()
    if method not in METHODS:
        raise ValueError(f"未知滤波方式: {method}（可选: {', '.join(METHODS)}）")

    merged = {**DEFAULT_PARAMS[method], **(params or {})}
    values = pd.to_numeric(series, errors="coerce").astype(float)
    values.name = series.name

    if method == NONE or values.notna().sum() < _MIN_POINTS:
        return values

    filled = values.interpolate(limit_direction="both") if values.isna().any() else values
    result = _apply(filled.to_numpy(dtype=float), method, merged)
    filtered = pd.Series(result, index=values.index, name=series.name)
    filtered[values.isna()] = np.nan
    return filtered


def _apply(x: np.ndarray, method: str, params: dict) -> np.ndarray:
    n = len(x)
    if method == MOVING_AVERAGE:
        return _moving_average(x, params)
    if method == EWM:
        return _ewm(x, params)
    if method == BUTTERWORTH:
        return _butterworth(x, params, n)
    return _savgol(x, params, n)


def _moving_average(x: np.ndarray, params: dict) -> np.ndarray:
    window = int(params["window"])
    if window < 2:
        raise ValueError("移动平均 window 必须 >= 2")
    series = pd.Series(x)
    return series.rolling(window, min_periods=1).mean().to_numpy()


def _ewm(x: np.ndarray, params: dict) -> np.ndarray:
    alpha = float(params["alpha"])
    if not 0 < alpha <= 1:
        raise ValueError("EMA alpha 必须在 (0, 1] 区间内")
    return pd.Series(x).ewm(alpha=alpha, adjust=False).mean().to_numpy()


def _butterworth(x: np.ndarray, params: dict, n: int) -> np.ndarray:
    order = int(params["order"])
    cutoff = float(params["cutoff"])
    if order < 1:
        raise ValueError("Butterworth order 必须 >= 1")
    if not 0 < cutoff < 1:
        raise ValueError("Butterworth cutoff 为归一化频率，必须位于 (0, 1) 之间")

    b, a = butter(order, cutoff, btype="low")
    padlen = 3 * max(len(a), len(b))
    if n <= padlen:
        warnings.warn(
            f"序列过短（{n} 点，需要 > {padlen} 点），Butterworth 已跳过，返回原始数据",
            stacklevel=2,
        )
        return x
    # filtfilt 前后向滤波，抵消相位偏移
    return filtfilt(b, a, x, padlen=padlen)


def _savgol(x: np.ndarray, params: dict, n: int) -> np.ndarray:
    window = int(params["window"])
    polyorder = int(params["polyorder"])
    if window % 2 == 0:
        window += 1
    if window > n:
        window = n if n % 2 == 1 else n - 1
    if polyorder >= window:
        polyorder = window - 1
    if window < 3 or polyorder < 1:
        warnings.warn(
            f"序列过短（{n} 点），Savitzky-Golay 已跳过，返回原始数据",
            stacklevel=2,
        )
        return x
    return savgol_filter(x, window, polyorder)


def parse_params(text: str | None) -> dict:
    """解析参数文本，支持 'window=10, order=3' 与 JSON 两种写法。"""
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
