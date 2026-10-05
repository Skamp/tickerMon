import logging
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from app.services.noise_reduction import apply_kalman_filter, apply_savitzky_golay_reduction

logger = logging.getLogger(__name__)

SWING_THRESHOLD_PCT = 10.0

try:
    from scipy.signal import find_peaks as _scipy_find_peaks
except Exception:
    _scipy_find_peaks = None

try:
    import ruptures as _ruptures
except Exception:
    _ruptures = None


class SwingAlgorithm(Enum):
    RANGE = "Min-Max Range (10%)"
    ZIGZAG = "ZigZag"
    WILLIAMS_FRACTALS = "Williams Fractals"
    PIVOT_WINDOW = "Pivot Window (find_peaks)"
    SWING_INDEX = "Swing Index / ASI (Wilder)"
    PARABOLIC_SAR = "Parabolic SAR"
    SUPERTREND = "SuperTrend"
    CHANDELIER_EXIT = "Chandelier Exit"
    DONCHIAN = "Donchian Channels"
    HEIKIN_ASHI = "Heikin-Ashi"
    RSI = "RSI"
    STOCHASTIC = "Stochastic"
    MACD = "MACD"
    CCI = "CCI"
    BOLLINGER = "Bollinger Bands"
    KELTNER = "Keltner Channels"
    CHANGE_POINT = "Change-Point (CUSUM / PELT / BOCPD)"
    KALMAN = "Kalman Filter"
    SAVITZKY_GOLAY = "Savitzky-Golay Filter"
    HILBERT = "Hilbert Transform"
    WAVELETS = "Wavelets"
    HMM = "Hidden Markov Model"

    @classmethod
    def from_str(cls, val: str) -> "SwingAlgorithm":
        for item in cls:
            if item.value == val or item.name == val:
                return item
        return cls.RANGE


class SwingRangeMode(Enum):
    MIN_DURATION = "Minimum duration"
    MAX_DURATION = "Maximum duration"
    LOOKBACK = "Lookback window"
    DURATION_WINDOW = "Duration window (both bounds)"

    @classmethod
    def from_str(cls, val: str) -> "SwingRangeMode":
        needle = str(val).strip().lower()
        if not needle:
            return cls.MIN_DURATION
        for item in cls:
            if needle in (item.value.lower(), item.name.lower()):
                return item
        matches = [item for item in cls if needle in item.value.lower()]
        if len(matches) == 1:
            return matches[0]
        return cls.MIN_DURATION


SWING_ALGORITHM_DESCRIPTIONS: Dict[SwingAlgorithm, str] = {
    SwingAlgorithm.RANGE: "Current algorithm. Swings when the highest and lowest price of the range differ by at least 10%.",
    SwingAlgorithm.ZIGZAG: "Filters movements lower than a percentage or a multiple of the ATR, detailing only significant changes.",
    SwingAlgorithm.WILLIAMS_FRACTALS: "A maximum or minimum is valid when it is higher or lower than the N candles on each side (normally 2).",
    SwingAlgorithm.PIVOT_WINDOW: "Pivot detection inside a configurable window using prominence and distance (scipy.signal.find_peaks or argrelextrema).",
    SwingAlgorithm.SWING_INDEX: "Swing Index / Accumulative Swing Index (Welles Wilder) quantifies the strength of each movement combining OHLC.",
    SwingAlgorithm.PARABOLIC_SAR: "Parabolic SAR reversals mark the end of each trend leg.",
    SwingAlgorithm.SUPERTREND: "SuperTrend flips between bullish and bearish bands built from ATR.",
    SwingAlgorithm.CHANDELIER_EXIT: "Chandelier Exit trailing stop (highest high / lowest low minus ATR) flips mark reversals.",
    SwingAlgorithm.DONCHIAN: "Donchian channels: maximum and minimum of N periods, useful for breakouts.",
    SwingAlgorithm.HEIKIN_ASHI: "Heikin-Ashi softens candle information to enhance the view of changes.",
    SwingAlgorithm.RSI: "RSI overbought (70) and oversold (30) threshold crossings mark swing points.",
    SwingAlgorithm.STOCHASTIC: "Stochastic overbought (80) and oversold (20) threshold crossings mark swing points.",
    SwingAlgorithm.MACD: "MACD line / signal line crossovers mark momentum reversals.",
    SwingAlgorithm.CCI: "CCI crossings of the +100 / -100 levels mark swing points.",
    SwingAlgorithm.BOLLINGER: "Bollinger band walks: touches and exits of the 2 sigma bands.",
    SwingAlgorithm.KELTNER: "Keltner channel walks: EMA band touches expanded by ATR.",
    SwingAlgorithm.CHANGE_POINT: "Change-point detection (PELT/CUSUM/BOCPD, ruptures when available) finds structural breaks in the series.",
    SwingAlgorithm.KALMAN: "Kalman filter state estimate is used to expose the underlying trend turning points.",
    SwingAlgorithm.SAVITZKY_GOLAY: "Savitzky-Golay smoothing removes noise before extrema detection.",
    SwingAlgorithm.HILBERT: "Hilbert transform analytic signal phase is used to locate cycle turning points.",
    SwingAlgorithm.WAVELETS: "Multi-resolution Haar wavelet decomposition exposes structural swing points.",
    SwingAlgorithm.HMM: "Hidden Markov Model regime states (down / flat / up) mark regime flips.",
}


@dataclass(frozen=True)
class SwingParam:
    key: str
    label: str
    kind: str  # "int" or "float"
    default: float
    minimum: float
    maximum: float
    step: float = 1.0
    decimals: int = 2


MIN_SWING_PCT = SwingParam(
    key="min_swing_pct",
    label="Min swing size (%)",
    kind="float",
    default=SWING_THRESHOLD_PCT,
    minimum=0.1,
    maximum=1000.0,
    step=0.5,
    decimals=1,
)

SWING_ALGORITHM_PARAMS: Dict[SwingAlgorithm, Tuple[SwingParam, ...]] = {
    SwingAlgorithm.RANGE: (MIN_SWING_PCT,),
    SwingAlgorithm.ZIGZAG: (
        MIN_SWING_PCT,
        SwingParam("threshold_pct", "Reversal threshold (%)", "float", 5.0, 0.1, 100.0, 0.5, 1),
        SwingParam("atr_multiple", "ATR multiple (0 = % mode)", "float", 0.0, 0.0, 20.0, 0.1, 1),
    ),
    SwingAlgorithm.WILLIAMS_FRACTALS: (
        MIN_SWING_PCT,
        SwingParam("order", "Bars per side", "int", 2.0, 1, 20, 1, 0),
    ),
    SwingAlgorithm.PIVOT_WINDOW: (
        MIN_SWING_PCT,
        SwingParam("window", "Window / distance", "int", 5.0, 1, 50, 1, 0),
        SwingParam("prominence_ratio", "Prominence ratio", "float", 0.05, 0.0, 1.0, 0.01, 2),
    ),
    SwingAlgorithm.SWING_INDEX: (
        MIN_SWING_PCT,
        SwingParam("limit_factor", "Limit factor", "float", 3.0, 0.5, 100.0, 0.5, 1),
    ),
    SwingAlgorithm.PARABOLIC_SAR: (
        MIN_SWING_PCT,
        SwingParam("af_step", "Acceleration step", "float", 0.02, 0.001, 0.2, 0.001, 3),
        SwingParam("af_max", "Acceleration max", "float", 0.2, 0.01, 1.0, 0.01, 2),
    ),
    SwingAlgorithm.SUPERTREND: (
        MIN_SWING_PCT,
        SwingParam("period", "ATR period", "int", 10.0, 2, 100, 1, 0),
        SwingParam("mult", "ATR multiplier", "float", 3.0, 0.5, 10.0, 0.1, 1),
    ),
    SwingAlgorithm.CHANDELIER_EXIT: (
        MIN_SWING_PCT,
        SwingParam("period", "Lookback period", "int", 22.0, 2, 200, 1, 0),
        SwingParam("mult", "ATR multiplier", "float", 3.0, 0.5, 10.0, 0.1, 1),
    ),
    SwingAlgorithm.DONCHIAN: (
        MIN_SWING_PCT,
        SwingParam("period", "Channel period", "int", 20.0, 2, 200, 1, 0),
    ),
    SwingAlgorithm.HEIKIN_ASHI: (
        MIN_SWING_PCT,
        SwingParam("order", "Extrema order", "int", 2.0, 1, 20, 1, 0),
    ),
    SwingAlgorithm.RSI: (
        MIN_SWING_PCT,
        SwingParam("period", "RSI period", "int", 14.0, 2, 100, 1, 0),
        SwingParam("upper", "Overbought level", "float", 70.0, 50.0, 100.0, 1.0, 1),
        SwingParam("lower", "Oversold level", "float", 30.0, 0.0, 50.0, 1.0, 1),
    ),
    SwingAlgorithm.STOCHASTIC: (
        MIN_SWING_PCT,
        SwingParam("period", "Lookback period", "int", 14.0, 2, 100, 1, 0),
        SwingParam("smooth", "%K smoothing", "int", 3.0, 1, 20, 1, 0),
        SwingParam("upper", "Overbought level", "float", 80.0, 50.0, 100.0, 1.0, 1),
        SwingParam("lower", "Oversold level", "float", 20.0, 0.0, 50.0, 1.0, 1),
    ),
    SwingAlgorithm.MACD: (
        MIN_SWING_PCT,
        SwingParam("fast", "Fast EMA", "int", 12.0, 2, 100, 1, 0),
        SwingParam("slow", "Slow EMA", "int", 26.0, 3, 200, 1, 0),
        SwingParam("signal", "Signal EMA", "int", 9.0, 2, 100, 1, 0),
    ),
    SwingAlgorithm.CCI: (
        MIN_SWING_PCT,
        SwingParam("period", "CCI period", "int", 20.0, 2, 200, 1, 0),
        SwingParam("upper", "Upper level", "float", 100.0, 1.0, 500.0, 1.0, 1),
        SwingParam("lower", "Lower level", "float", -100.0, -500.0, -1.0, 1.0, 1),
    ),
    SwingAlgorithm.BOLLINGER: (
        MIN_SWING_PCT,
        SwingParam("period", "MA period", "int", 20.0, 2, 200, 1, 0),
        SwingParam("mult", "Std-dev multiplier", "float", 2.0, 0.5, 6.0, 0.1, 1),
    ),
    SwingAlgorithm.KELTNER: (
        MIN_SWING_PCT,
        SwingParam("period", "EMA period", "int", 20.0, 2, 200, 1, 0),
        SwingParam("mult", "ATR multiplier", "float", 2.0, 0.5, 6.0, 0.1, 1),
        SwingParam("atr_period", "ATR period", "int", 10.0, 2, 100, 1, 0),
    ),
    SwingAlgorithm.CHANGE_POINT: (
        MIN_SWING_PCT,
        SwingParam("min_size", "Min segment size", "int", 5.0, 2, 100, 1, 0),
        SwingParam("penalty_factor", "PELT penalty factor", "float", 3.0, 0.1, 100.0, 0.5, 1),
        SwingParam("cusum_threshold", "CUSUM threshold (0 = auto)", "float", 0.0, 0.0, 10.0, 0.1, 2),
    ),
    SwingAlgorithm.KALMAN: (
        MIN_SWING_PCT,
        SwingParam("process_noise", "Process noise", "float", 1e-4, 0.0, 1.0, 0.0001, 6),
        SwingParam("measurement_noise", "Measurement noise", "float", 0.5, 0.001, 100.0, 0.01, 2),
    ),
    SwingAlgorithm.SAVITZKY_GOLAY: (
        MIN_SWING_PCT,
        SwingParam("window_size", "Window size", "int", 7.0, 3, 51, 2, 0),
        SwingParam("polyorder", "Polynomial order", "int", 2.0, 1, 10, 1, 0),
    ),
    SwingAlgorithm.HILBERT: (MIN_SWING_PCT,),
    SwingAlgorithm.WAVELETS: (
        MIN_SWING_PCT,
        SwingParam("level", "Decomposition level (0 = auto)", "int", 0.0, 0, 6, 1, 0),
    ),
    SwingAlgorithm.HMM: (
        MIN_SWING_PCT,
        SwingParam("n_states", "Hidden states", "int", 3.0, 2, 6, 1, 0),
        SwingParam("iterations", "Training iterations", "int", 8.0, 1, 50, 1, 0),
    ),
}


def default_swing_params(algorithm: SwingAlgorithm) -> Dict[str, float]:
    return {spec.key: spec.default for spec in SWING_ALGORITHM_PARAMS.get(algorithm, ())}


def normalize_swing_params(
    algorithm: SwingAlgorithm, params: Optional[Dict[str, Any]] = None
) -> Dict[str, float]:
    specs = SWING_ALGORITHM_PARAMS.get(algorithm, ())
    source = params if isinstance(params, dict) else {}
    normalized: Dict[str, float] = {}
    for spec in specs:
        raw = source.get(spec.key, spec.default)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = float(spec.default)
        if not math.isfinite(value):
            value = float(spec.default)
        value = min(max(value, spec.minimum), spec.maximum)
        if spec.kind == "int":
            value = float(int(round(value)))
        normalized[spec.key] = value

    if algorithm == SwingAlgorithm.MACD:
        fast = int(normalized.get("fast", 12))
        slow = int(normalized.get("slow", 26))
        if fast >= slow:
            slow = min(slow, 200)
            fast = min(fast, slow - 1)
            normalized["fast"] = float(fast)
            normalized["slow"] = float(slow)
    elif algorithm in (SwingAlgorithm.RSI, SwingAlgorithm.STOCHASTIC):
        lower = normalized.get("lower", 30.0)
        upper = normalized.get("upper", 70.0)
        if lower >= upper:
            normalized["lower"] = float(max(0.0, upper - 1.0))
    elif algorithm == SwingAlgorithm.CCI:
        if normalized.get("lower", -100.0) >= normalized.get("upper", 100.0):
            normalized["lower"] = float(normalized.get("upper", 100.0) - 1.0)
    elif algorithm == SwingAlgorithm.SAVITZKY_GOLAY:
        window = int(normalized.get("window_size", 7))
        if window % 2 == 0:
            window += 1
        window = max(3, min(window, 51))
        polyorder = int(normalized.get("polyorder", 2))
        polyorder = max(1, min(polyorder, window - 1))
        normalized["window_size"] = float(window)
        normalized["polyorder"] = float(polyorder)

    return normalized


def format_swing_params(
    algorithm: SwingAlgorithm, params: Optional[Dict[str, Any]] = None
) -> str:
    """Formats the normalized parameters of an algorithm as 'Label: value | Label: value'."""
    values = normalize_swing_params(algorithm, params)
    parts: List[str] = []
    for spec in SWING_ALGORITHM_PARAMS.get(algorithm, ()):
        value = values.get(spec.key, spec.default)
        if spec.kind == "int":
            text = str(int(value))
        else:
            text = f"{value:.6g}"
        parts.append(f"{spec.label}: {text}")
    return " | ".join(parts)


SWING_RANGE_SECONDS = {
    "weeks": 7.0 * 86400.0,
    "months": 30.4375 * 86400.0,
}


def _parse_swing_range_settings(
    settings: Optional[Dict[str, Any]],
) -> Tuple[SwingRangeMode, int, int, str]:
    source = settings if isinstance(settings, dict) else {}
    mode = SwingRangeMode.from_str(str(source.get("mode", "")))

    def _clamp(raw: Any) -> int:
        try:
            value = int(round(float(raw)))
        except (TypeError, ValueError):
            return 0
        return max(0, min(value, 520))

    value = _clamp(source.get("value", 0))
    value_max = _clamp(source.get("value_max", 0))
    unit_raw = str(source.get("unit", "weeks")).lower()
    unit = "months" if unit_raw.startswith("month") else "weeks"
    return mode, value, value_max, unit


def _swing_range_enabled(mode: SwingRangeMode, value: int, value_max: int) -> bool:
    if mode == SwingRangeMode.DURATION_WINDOW:
        return value > 0 and value_max > 0
    return value > 0


def restrict_swing_pivots(
    pivots: Sequence[int],
    timestamps: Sequence[float],
    settings: Optional[Dict[str, Any]] = None,
) -> Tuple[List[int], List[Tuple[int, int]]]:
    """Filters detected pivots according to the swing range settings.

    Returns ``(kept_pivots, kept_legs)`` where each leg is a ``(start, end)``
    pivot index pair. With an inactive range (value 0) every pivot and every
    consecutive leg is kept.
    """
    pivot_list = sorted({int(p) for p in pivots})
    all_legs: List[Tuple[int, int]] = list(zip(pivot_list, pivot_list[1:]))

    mode, value, value_max, unit = _parse_swing_range_settings(settings)
    if not _swing_range_enabled(mode, value, value_max):
        return pivot_list, all_legs

    if len(timestamps) < 2 or (pivot_list and pivot_list[-1] >= len(timestamps)):
        return pivot_list, all_legs

    unit_seconds = SWING_RANGE_SECONDS[unit]

    if mode == SwingRangeMode.LOOKBACK:
        cutoff = float(timestamps[-1]) - value * unit_seconds
        kept = [p for p in pivot_list if float(timestamps[p]) >= cutoff]
        return kept, list(zip(kept, kept[1:]))

    low_seconds = value * unit_seconds
    high_seconds = value_max * unit_seconds
    kept_legs: List[Tuple[int, int]] = []
    for start, end in all_legs:
        duration = abs(float(timestamps[end]) - float(timestamps[start]))
        if mode == SwingRangeMode.MIN_DURATION:
            keep = duration >= low_seconds
        elif mode == SwingRangeMode.MAX_DURATION:
            keep = duration <= low_seconds
        else:
            keep = low_seconds <= duration <= high_seconds
        if keep:
            kept_legs.append((start, end))

    kept_pivots = sorted({index for leg in kept_legs for index in leg})
    return kept_pivots, kept_legs


def describe_swing_range(settings: Optional[Dict[str, Any]] = None) -> str:
    """Formats the swing range settings as a short human readable label."""
    mode, value, value_max, unit = _parse_swing_range_settings(settings)
    if not _swing_range_enabled(mode, value, value_max):
        return "off"

    word = "week" if unit == "weeks" else "month"
    if value != 1:
        word += "s"

    if mode == SwingRangeMode.MIN_DURATION:
        return f">= {value} {word}"
    if mode == SwingRangeMode.MAX_DURATION:
        return f"<= {value} {word}"
    if mode == SwingRangeMode.LOOKBACK:
        return f"last {value} {word}"

    upper_word = "week" if unit == "weeks" else "month"
    if value_max != 1:
        upper_word += "s"
    return f"{value} {word} to {value_max} {upper_word}"


def _local_extrema(values: Sequence[float], order: int = 2) -> Tuple[List[int], List[int]]:
    y = np.asarray(values, dtype=float)
    n = len(y)
    maxima: List[int] = []
    minima: List[int] = []
    if n < 2 * order + 1:
        return maxima, minima
    for i in range(order, n - order):
        left = y[i - order: i]
        right = y[i + 1: i + order + 1]
        if y[i] > left.max() and y[i] > right.max():
            maxima.append(i)
        elif y[i] < left.min() and y[i] < right.min():
            minima.append(i)
    return maxima, minima


def _finalize_pivots(candidates: Sequence[int], prices: np.ndarray) -> List[int]:
    n = len(prices)
    if n == 0:
        return []
    if n == 1:
        return [0]

    indices = sorted({int(i) for i in candidates if 0 <= int(i) < n})
    if not indices or indices[0] != 0:
        indices.insert(0, 0)
    if indices[-1] != n - 1:
        indices.append(n - 1)

    directions: List[bool] = []
    for k in range(len(indices) - 1):
        a, b = indices[k], indices[k + 1]
        directions.append(bool(prices[a] >= prices[b]))
    directions.append(not directions[-1] if directions else True)

    merged_idx: List[int] = []
    merged_dir: List[bool] = []
    for idx, is_high in zip(indices, directions):
        if merged_dir and merged_dir[-1] == is_high:
            prev_idx = merged_idx[-1]
            if (is_high and prices[idx] > prices[prev_idx]) or (not is_high and prices[idx] < prices[prev_idx]):
                merged_idx[-1] = idx
        else:
            merged_idx.append(idx)
            merged_dir.append(is_high)
    return merged_idx


def _ema(values: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1.0)
    out = np.empty(len(values), dtype=float)
    if len(values) == 0:
        return out
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def _sma(values: np.ndarray, period: int) -> np.ndarray:
    n = len(values)
    period = max(1, min(period, n))
    out = np.empty(n, dtype=float)
    total = 0.0
    for i in range(n):
        total += values[i]
        if i >= period:
            total -= values[i - period]
        out[i] = total / min(i + 1, period)
    return out


def _wilder_smooth(values: np.ndarray, period: int) -> np.ndarray:
    out = np.empty(len(values), dtype=float)
    if len(values) == 0:
        return out
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = (out[i - 1] * (period - 1) + values[i]) / period
    return out


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(close)
    prev_close = np.empty(n, dtype=float)
    prev_close[0] = close[0]
    prev_close[1:] = close[:-1]
    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)),
    )
    return _wilder_smooth(tr, period)


def _rolling_max(values: np.ndarray, window: int) -> np.ndarray:
    n = len(values)
    return np.array([values[max(0, i - window + 1): i + 1].max() for i in range(n)], dtype=float)


def _rolling_min(values: np.ndarray, window: int) -> np.ndarray:
    n = len(values)
    return np.array([values[max(0, i - window + 1): i + 1].min() for i in range(n)], dtype=float)


def _resolve_ohlc(close: np.ndarray, ohlc: Optional[Tuple[Sequence[float], Sequence[float], Sequence[float]]]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(close)
    prev = np.empty(n, dtype=float)
    prev[0] = close[0]
    prev[1:] = close[:-1]
    open_fallback = prev
    high_fallback = np.maximum(prev, close)
    low_fallback = np.minimum(prev, close)

    if ohlc is None:
        return open_fallback, high_fallback, low_fallback

    try:
        opens, highs, lows = (np.asarray(part, dtype=float) for part in ohlc)
        if len(opens) != n or len(highs) != n or len(lows) != n:
            raise ValueError("ohlc length mismatch")
        opens = np.where(np.isfinite(opens) & (opens > 0), opens, open_fallback)
        highs = np.where(np.isfinite(highs) & (highs > 0), highs, high_fallback)
        lows = np.where(np.isfinite(lows) & (lows > 0), lows, low_fallback)
    except Exception:
        return open_fallback, high_fallback, low_fallback

    highs = np.maximum(highs, np.maximum(opens, close))
    lows = np.minimum(lows, np.minimum(opens, close))
    return opens, highs, lows


def _detect_zigzag(close: np.ndarray, threshold_pct: float = 5.0, atr: Optional[np.ndarray] = None, atr_multiple: Optional[float] = None) -> List[int]:
    n = len(close)
    if n < 2 or threshold_pct <= 0:
        return []

    pivots: List[int] = []
    trend = 0
    low_idx, low_price = 0, float(close[0])
    high_idx, high_price = 0, float(close[0])
    extreme_idx, extreme_price = 0, float(close[0])

    def threshold(reference: float, index: int) -> float:
        if atr_multiple is not None and atr is not None:
            return atr_multiple * float(atr[index])
        return threshold_pct / 100.0 * abs(reference)

    for i in range(1, n):
        price = float(close[i])
        if trend == 0:
            if price < low_price:
                low_idx, low_price = i, price
            if price > high_price:
                high_idx, high_price = i, price
            if price >= low_price + threshold(low_price, i):
                pivots.append(low_idx)
                trend = 1
                extreme_idx, extreme_price = i, price
            elif price <= high_price - threshold(high_price, i):
                pivots.append(high_idx)
                trend = -1
                extreme_idx, extreme_price = i, price
        elif trend == 1:
            if price > extreme_price:
                extreme_idx, extreme_price = i, price
            elif extreme_price - price >= threshold(extreme_price, i):
                pivots.append(extreme_idx)
                trend = -1
                extreme_idx, extreme_price = i, price
        else:
            if price < extreme_price:
                extreme_idx, extreme_price = i, price
            elif price - extreme_price >= threshold(extreme_price, i):
                pivots.append(extreme_idx)
                trend = 1
                extreme_idx, extreme_price = i, price

    if trend != 0:
        pivots.append(extreme_idx)
    return pivots


def _detect_williams_fractals(close: np.ndarray, high: np.ndarray, low: np.ndarray, order: int = 2) -> List[int]:
    n = len(close)
    pivots: List[int] = []
    if n < 2 * order + 1:
        return pivots
    for i in range(order, n - order):
        left_h = high[i - order: i]
        right_h = high[i + 1: i + order + 1]
        left_l = low[i - order: i]
        right_l = low[i + 1: i + order + 1]
        if high[i] >= left_h.max() and high[i] >= right_h.max():
            pivots.append(i)
        if low[i] <= left_l.min() and low[i] <= right_l.min():
            pivots.append(i)
    return pivots


def _prominence(values: np.ndarray, index: int) -> float:
    n = len(values)
    peak = values[index]
    left = index
    while left > 0 and values[left - 1] <= peak:
        left -= 1
    right = index
    while right < n - 1 and values[right + 1] <= peak:
        right += 1
    return float(peak - max(values[left: index + 1].min(), values[index: right + 1].min()))


def _find_peaks_numpy(values: np.ndarray, prominence: Optional[float] = None, distance: Optional[int] = None) -> List[int]:
    n = len(values)
    if n < 3:
        return []
    idx = np.where((values[1:-1] > values[:-2]) & (values[1:-1] >= values[2:]))[0] + 1
    if prominence is not None and len(idx):
        keep = [i for i in idx if _prominence(values, int(i)) >= prominence]
        idx = np.array(keep, dtype=int)
    if distance is not None and distance > 1 and len(idx):
        order = idx[np.argsort(values[idx])[::-1]]
        taken = np.zeros(n, dtype=bool)
        selected: List[int] = []
        for i in order:
            i = int(i)
            lo = max(0, i - distance)
            hi = min(n, i + distance + 1)
            if not taken[lo:hi].any():
                selected.append(i)
                taken[i] = True
        idx = np.array(sorted(selected), dtype=int)
    return [int(i) for i in idx]


def _find_peaks(values: np.ndarray, prominence: Optional[float] = None, distance: Optional[int] = None) -> List[int]:
    if _scipy_find_peaks is not None:
        peaks, _ = _scipy_find_peaks(values, prominence=prominence, distance=distance)
        return [int(i) for i in peaks]
    return _find_peaks_numpy(values, prominence=prominence, distance=distance)


def _detect_pivot_window(close: np.ndarray, window: int = 5, prominence_ratio: float = 0.05) -> List[int]:
    n = len(close)
    if n < 3:
        return []
    price_range = float(close.max() - close.min())
    prominence = prominence_ratio * price_range
    distance = max(1, int(window))
    maxima = _find_peaks(close, prominence=prominence, distance=distance)
    minima = _find_peaks(-close, prominence=prominence, distance=distance)
    return maxima + minima


def _detect_swing_index(high: np.ndarray, low: np.ndarray, open_: np.ndarray, close: np.ndarray, limit_factor: float = 3.0) -> List[int]:
    n = len(close)
    if n < 3:
        return []
    limit = limit_factor if limit_factor and limit_factor > 0 else 3.0
    si = np.zeros(n, dtype=float)
    for i in range(1, n):
        prev_close = close[i - 1]
        movement = (close[i] - prev_close) + 0.5 * (close[i] - open_[i]) + 0.25 * (prev_close - open_[i - 1])
        spread = max(abs(high[i] - prev_close), abs(low[i] - prev_close), abs(high[i] - low[i]))
        if spread > 0:
            si[i] = 50.0 * movement / (spread * limit)
    asi = np.cumsum(si)
    maxima, minima = _local_extrema(asi, order=3)
    return maxima + minima


def _detect_parabolic_sar(high: np.ndarray, low: np.ndarray, close: np.ndarray, af_step: float = 0.02, af_max: float = 0.2) -> List[int]:
    n = len(close)
    if n < 3:
        return []

    trend = 1 if close[1] >= close[0] else -1
    af = af_step
    extreme_idx = 0
    extreme = float(high[0] if trend == 1 else low[0])
    sar = float(low[0] if trend == 1 else high[0])
    pivots: List[int] = [0]

    for i in range(1, n):
        sar += af * (extreme - sar)
        if trend == 1:
            sar = min(sar, float(low[i - 1]), float(low[i - 2] if i >= 2 else low[i - 1]))
            if low[i] < sar:
                pivots.append(extreme_idx)
                trend = -1
                sar = extreme
                extreme_idx = i
                extreme = float(low[i])
                af = af_step
            elif high[i] > extreme:
                extreme_idx = i
                extreme = float(high[i])
                af = min(af + af_step, af_max)
        else:
            sar = max(sar, float(high[i - 1]), float(high[i - 2] if i >= 2 else high[i - 1]))
            if high[i] > sar:
                pivots.append(extreme_idx)
                trend = 1
                sar = extreme
                extreme_idx = i
                extreme = float(high[i])
                af = af_step
            elif low[i] < extreme:
                extreme_idx = i
                extreme = float(low[i])
                af = min(af + af_step, af_max)

    pivots.append(extreme_idx)
    return pivots


def _flip_pivots(direction: np.ndarray, high: np.ndarray, low: np.ndarray) -> List[int]:
    n = len(direction)
    if n == 0:
        return []
    nonzero = np.nonzero(direction)[0]
    if len(nonzero) == 0:
        return []
    start = int(nonzero[0])
    pivots: List[int] = [start]
    current = int(direction[start])
    seg_start = start
    for i in range(start + 1, n):
        value = int(direction[i])
        if value == 0:
            continue
        if value != current:
            seg = slice(seg_start, i)
            if current == 1:
                pivots.append(seg_start + int(np.argmax(high[seg])))
            else:
                pivots.append(seg_start + int(np.argmin(low[seg])))
            seg_start = i
            current = value
    seg = slice(seg_start, n)
    if current == 1:
        pivots.append(seg_start + int(np.argmax(high[seg])))
    else:
        pivots.append(seg_start + int(np.argmin(low[seg])))
    return pivots


def _detect_supertrend(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 10, mult: float = 3.0) -> List[int]:
    n = len(close)
    if n < 3:
        return []
    period = max(2, min(period, n))
    atr = _atr(high, low, close, period)
    mid = (high + low) / 2.0
    upper = mid + mult * atr
    lower = mid - mult * atr

    final_upper = np.empty(n, dtype=float)
    final_lower = np.empty(n, dtype=float)
    direction = np.zeros(n, dtype=int)

    final_upper[0] = upper[0]
    final_lower[0] = lower[0]

    for i in range(1, n):
        if close[i - 1] > final_upper[i - 1]:
            final_upper[i] = upper[i]
        else:
            final_upper[i] = min(upper[i], final_upper[i - 1])
        if close[i - 1] < final_lower[i - 1]:
            final_lower[i] = lower[i]
        else:
            final_lower[i] = max(lower[i], final_lower[i - 1])

    for i in range(n):
        if close[i] > final_upper[i]:
            direction[i] = 1
        elif close[i] < final_lower[i]:
            direction[i] = -1
        elif i > 0:
            direction[i] = direction[i - 1]

    return _flip_pivots(direction, high, low)


def _detect_chandelier(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 22, mult: float = 3.0) -> List[int]:
    n = len(close)
    if n < 3:
        return []
    period = max(2, min(period, n))
    atr = _atr(high, low, close, period)
    highest = _rolling_max(high, period)
    lowest = _rolling_min(low, period)
    long_stop = highest - mult * atr
    short_stop = lowest + mult * atr

    direction = np.zeros(n, dtype=int)
    current = 1 if close[1] >= close[0] else -1
    direction[0] = current
    for i in range(1, n):
        if current == 1 and close[i] < long_stop[i]:
            current = -1
        elif current == -1 and close[i] > short_stop[i]:
            current = 1
        direction[i] = current

    return _flip_pivots(direction, high, low)


def _detect_donchian(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 20) -> List[int]:
    n = len(close)
    if n < 3:
        return []
    period = max(2, min(period, n))
    pivots: List[int] = []
    for i in range(1, n):
        start = max(0, i - period)
        if start >= i:
            continue
        if high[i] > high[start: i].max():
            pivots.append(i)
        if low[i] < low[start: i].min():
            pivots.append(i)
    return pivots


def _detect_heikin_ashi(open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray, order: int = 2) -> List[int]:
    n = len(close)
    if n < 3:
        return []
    ha_close = (open_ + high + low + close) / 4.0
    ha_open = np.empty(n, dtype=float)
    ha_open[0] = (open_[0] + close[0]) / 2.0
    for i in range(1, n):
        ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2.0
    ha_high = np.maximum(high, np.maximum(ha_open, ha_close))
    ha_low = np.minimum(low, np.minimum(ha_open, ha_close))
    maxima, minima = _local_extrema(ha_close, order=order)
    high_maxima, _ = _local_extrema(ha_high, order=order)
    _, low_minima = _local_extrema(ha_low, order=order)
    return maxima + minima + high_maxima + low_minima


def _threshold_cross_indices(indicator: np.ndarray, upper: float, lower: float, close: np.ndarray) -> List[int]:
    n = len(indicator)
    out: List[int] = []
    for i in range(1, n):
        if indicator[i - 1] >= upper > indicator[i]:
            out.append(i)
        elif indicator[i - 1] <= lower < indicator[i]:
            out.append(i)
    if not out:
        maxima, minima = _local_extrema(indicator, order=3)
        out = maxima + minima
    if not out:
        maxima, minima = _local_extrema(close, order=3)
        out = maxima + minima
    return out


def _rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    deltas = np.diff(close, prepend=close[0])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = _wilder_smooth(gains, period)
    avg_loss = _wilder_smooth(losses, period)
    rs = np.divide(avg_gain, avg_loss, out=np.ones_like(avg_gain), where=avg_loss > 0)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi = np.where(avg_loss <= 0, np.where(avg_gain > 0, 100.0, 50.0), rsi)
    return rsi


def _detect_rsi(close: np.ndarray, period: int = 14, upper: float = 70.0, lower: float = 30.0) -> List[int]:
    if len(close) < period + 2:
        maxima, minima = _local_extrema(close, order=2)
        return maxima + minima
    return _threshold_cross_indices(_rsi(close, period), upper, lower, close)


def _detect_stochastic(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14, smooth: int = 3, upper: float = 80.0, lower: float = 20.0) -> List[int]:
    n = len(close)
    if n < period + 2:
        maxima, minima = _local_extrema(close, order=2)
        return maxima + minima
    lowest = _rolling_min(low, period)
    highest = _rolling_max(high, period)
    spread = np.where(highest - lowest > 0, highest - lowest, np.nan)
    raw = 100.0 * (close - lowest) / spread
    raw = np.where(np.isfinite(raw), raw, 50.0)
    k = _sma(raw, smooth)
    return _threshold_cross_indices(k, upper, lower, close)


def _detect_macd(close: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> List[int]:
    n = len(close)
    if n < 5:
        maxima, minima = _local_extrema(close, order=2)
        return maxima + minima
    macd = _ema(close, fast) - _ema(close, slow)
    sig = _ema(macd, signal)
    out: List[int] = []
    for i in range(1, n):
        if macd[i - 1] <= sig[i - 1] and macd[i] > sig[i]:
            out.append(i)
        elif macd[i - 1] >= sig[i - 1] and macd[i] < sig[i]:
            out.append(i)
    if not out:
        maxima, minima = _local_extrema(macd, order=3)
        out = maxima + minima
    return out


def _detect_cci(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 20, upper: float = 100.0, lower: float = -100.0) -> List[int]:
    n = len(close)
    if n < period + 2:
        maxima, minima = _local_extrema(close, order=2)
        return maxima + minima
    tp = (high + low + close) / 3.0
    ma = _sma(tp, period)
    dev = np.empty(n, dtype=float)
    for i in range(n):
        start = max(0, i - period + 1)
        dev[i] = np.abs(tp[start: i + 1] - ma[i]).mean()
    scale = np.where(dev > 0, 0.015 * dev, np.nan)
    cci = (tp - ma) / scale
    cci = np.where(np.isfinite(cci), cci, 0.0)
    return _threshold_cross_indices(cci, upper, lower, close)


def _band_walk(close: np.ndarray, upper: np.ndarray, lower: np.ndarray) -> List[int]:
    n = len(close)
    out: List[int] = []
    i = 0
    while i < n:
        if close[i] > upper[i]:
            best = i
            while i < n and close[i] > upper[i]:
                if close[i] >= close[best]:
                    best = i
                i += 1
            out.append(best)
        elif close[i] < lower[i]:
            best = i
            while i < n and close[i] < lower[i]:
                if close[i] <= close[best]:
                    best = i
                i += 1
            out.append(best)
        else:
            i += 1
    return out


def _detect_bollinger(close: np.ndarray, period: int = 20, mult: float = 2.0) -> List[int]:
    n = len(close)
    if n < 5:
        maxima, minima = _local_extrema(close, order=2)
        return maxima + minima
    ma = _sma(close, period)
    dev = np.empty(n, dtype=float)
    for i in range(n):
        start = max(0, i - period + 1)
        dev[i] = close[start: i + 1].std()
    upper = ma + mult * dev
    lower = ma - mult * dev
    return _band_walk(close, upper, lower)


def _detect_keltner(close: np.ndarray, high: np.ndarray, low: np.ndarray, period: int = 20, mult: float = 2.0, atr_period: int = 10) -> List[int]:
    n = len(close)
    if n < 5:
        maxima, minima = _local_extrema(close, order=2)
        return maxima + minima
    mid = _ema(close, period)
    atr = _atr(high, low, close, atr_period)
    upper = mid + mult * atr
    lower = mid - mult * atr
    return _band_walk(close, upper, lower)


def _cusum_breakpoints(close: np.ndarray, threshold: Optional[float] = None) -> List[int]:
    n = len(close)
    sigma = float(close.std())
    if n < 4 or sigma <= 0:
        return []
    z = (close - close.mean()) / sigma
    k = threshold if threshold is not None else math.sqrt(2.0 * math.log(n))
    positive = 0.0
    negative = 0.0
    breakpoints: List[int] = []
    cooldown = max(1, n // 40)
    last = -cooldown
    for i, value in enumerate(z):
        positive = max(0.0, positive + float(value))
        negative = max(0.0, negative - float(value))
        if (positive > k or negative > k) and i - last >= cooldown:
            breakpoints.append(i)
            positive = 0.0
            negative = 0.0
            last = i
    return breakpoints


def _detect_change_point(close: np.ndarray, min_size: int = 5, penalty_factor: float = 3.0, cusum_threshold: float = 0.0) -> List[int]:
    n = len(close)
    if n < 8:
        maxima, minima = _local_extrema(close, order=2)
        return maxima + minima

    segment = max(2, int(min_size))
    factor = penalty_factor if penalty_factor and penalty_factor > 0 else 3.0
    breakpoints: Optional[List[int]] = None
    if _ruptures is not None:
        try:
            variance = float(close.var())
            penalty = factor * variance * math.log(max(n, 2))
            model = _ruptures.Pelt(model="l2", min_size=segment, jump=1)
            breakpoints = [int(b) for b in model.fit(close).predict(pen=max(penalty, 1e-9))]
        except Exception as e:
            logger.warning(f"Change-point detection via ruptures failed, using CUSUM: {e}")
            breakpoints = None

    if breakpoints is None:
        breakpoints = _cusum_breakpoints(close, threshold=cusum_threshold if cusum_threshold > 0 else None)

    return [b for b in breakpoints if 0 < b < n - 1]


def _detect_kalman(close: np.ndarray, process_noise: float = 1e-4, measurement_noise: float = 0.5) -> List[int]:
    if len(close) < 3:
        return []
    _, filtered = apply_kalman_filter(
        list(range(len(close))),
        close.tolist(),
        process_noise=process_noise,
        measurement_noise=measurement_noise,
    )
    maxima, minima = _local_extrema(filtered, order=2)
    return maxima + minima


def _detect_savitzky_golay(close: np.ndarray, window_size: int = 7, polyorder: int = 2) -> List[int]:
    if len(close) < 3:
        return []
    window = max(3, int(window_size))
    if window % 2 == 0:
        window += 1
    order = max(1, min(int(polyorder), window - 1))
    if len(close) < window:
        maxima, minima = _local_extrema(close, order=2)
        return maxima + minima
    if window == 7 and order == 2:
        _, smoothed = apply_savitzky_golay_reduction(list(range(len(close))), close.tolist())
    elif _scipy_find_peaks is not None:
        try:
            from scipy.signal import savgol_filter

            smoothed = savgol_filter(close, window_length=window, polyorder=order)
        except Exception:
            _, smoothed = apply_savitzky_golay_reduction(list(range(len(close))), close.tolist())
    else:
        _, smoothed = apply_savitzky_golay_reduction(list(range(len(close))), close.tolist())
    maxima, minima = _local_extrema(smoothed, order=2)
    return maxima + minima


def _detect_hilbert(close: np.ndarray) -> List[int]:
    n = len(close)
    if n < 8:
        maxima, minima = _local_extrema(close, order=2)
        return maxima + minima

    centered = close - close.mean()
    if not np.any(centered):
        return []

    spectrum = np.fft.fft(centered)
    weights = np.zeros(n, dtype=float)
    weights[0] = 1.0
    weights[1: (n + 1) // 2] = 2.0
    if n % 2 == 0:
        weights[n // 2] = 1.0
    analytic = np.fft.ifft(spectrum * weights)
    phase = np.unwrap(np.angle(analytic))

    if np.any(np.diff(phase) < -1e-9):
        maxima, minima = _local_extrema(centered, order=2)
        return maxima + minima

    pivots: List[int] = []
    first_k = int(math.floor(phase[0] / math.pi))
    last_k = int(math.ceil(phase[-1] / math.pi))
    cursor = 0
    for k in range(first_k, last_k + 1):
        if cursor >= n - 1:
            break
        target = k * math.pi
        position = int(np.searchsorted(phase[cursor:], target)) + cursor
        if position >= n:
            break
        pivots.append(position)
        cursor = position + 1
    return pivots


def _detect_wavelets(close: np.ndarray, level: Optional[int] = None) -> List[int]:
    n = len(close)
    if n < 8:
        maxima, minima = _local_extrema(close, order=2)
        return maxima + minima

    if level is None:
        level = max(1, int(math.log2(max(n // 8, 2))))
    level = min(level, 6)

    approximation = close.copy()
    step = 1
    for _ in range(level):
        if len(approximation) < 4:
            break
        if len(approximation) % 2:
            approximation = np.append(approximation, approximation[-1])
        approximation = 0.5 * (approximation[0::2] + approximation[1::2])
        step *= 2

    if len(approximation) < 3:
        maxima, minima = _local_extrema(close, order=2)
        return maxima + minima

    maxima, minima = _local_extrema(approximation, order=1)
    pivots: List[int] = []
    for index in maxima + minima:
        mapped = index * step + step // 2
        if 0 <= mapped < n:
            pivots.append(mapped)
    return pivots


def _logsumexp(values: np.ndarray, axis: Optional[int] = None) -> np.ndarray:
    maximum = np.max(values, axis=axis, keepdims=True)
    result = np.log(np.sum(np.exp(values - maximum), axis=axis, keepdims=True)) + maximum
    if axis is not None:
        return np.squeeze(result, axis=axis)
    return result


def _fit_gaussian_hmm(observations: np.ndarray, n_states: int = 3, iterations: int = 8) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(observations)
    means = np.quantile(observations, np.linspace(0, 1, n_states + 2)[1:-1]).astype(float)
    variance = max(float(observations.var()), 1e-6)
    variances = np.full(n_states, variance)
    transition = np.full((n_states, n_states), 1.0 / n_states)
    start = np.full(n_states, 1.0 / n_states)
    log_transition = np.log(np.maximum(transition, 1e-300))

    for _ in range(iterations):
        log_emit = -0.5 * (np.log(2.0 * np.pi * variances) + (observations[:, None] - means) ** 2 / variances)

        log_alpha = np.empty((n, n_states))
        log_alpha[0] = np.log(start) + log_emit[0]
        for t in range(1, n):
            log_alpha[t] = log_emit[t] + _logsumexp(log_alpha[t - 1][:, None] + log_transition, axis=0)
        log_likelihood = _logsumexp(log_alpha[-1])

        log_beta = np.zeros((n, n_states))
        for t in range(n - 2, -1, -1):
            log_beta[t] = _logsumexp(log_transition + (log_emit[t + 1] + log_beta[t + 1])[None, :], axis=1)

        log_gamma = log_alpha + log_beta - log_likelihood
        gamma = np.exp(log_gamma)
        log_xi = (
            log_alpha[:-1, :, None]
            + log_transition[None, :, :]
            + (log_emit[1:] + log_beta[1:])[:, None, :]
            - log_likelihood
        )
        xi = np.exp(log_xi).sum(axis=0)
        xi += np.eye(n_states) * max(2.0, 0.05 * n)

        start = gamma[0] / max(gamma[0].sum(), 1e-300)
        row_sums = xi.sum(axis=1, keepdims=True)
        transition = np.where(row_sums > 0, xi / np.maximum(row_sums, 1e-300), 1.0 / n_states)
        totals = gamma.sum(axis=0)
        means = (gamma * observations[:, None]).sum(axis=0) / np.maximum(totals, 1e-300)
        variances = (gamma * (observations[:, None] - means) ** 2).sum(axis=0) / np.maximum(totals, 1e-300)
        variances = np.maximum(variances, 1e-6)
        log_transition = np.log(np.maximum(transition, 1e-300))

    return means, variances, transition, start


def _viterbi(observations: np.ndarray, means: np.ndarray, variances: np.ndarray, transition: np.ndarray, start: np.ndarray) -> np.ndarray:
    n = len(observations)
    n_states = len(means)
    log_emit = -0.5 * (np.log(2.0 * np.pi * variances) + (observations[:, None] - means) ** 2 / variances)
    log_transition = np.log(np.maximum(transition, 1e-300))

    delta = np.empty((n, n_states))
    backpointer = np.zeros((n, n_states), dtype=int)
    delta[0] = np.log(np.maximum(start, 1e-300)) + log_emit[0]
    for t in range(1, n):
        candidates = delta[t - 1][:, None] + log_transition
        backpointer[t] = np.argmax(candidates, axis=0)
        delta[t] = log_emit[t] + candidates[backpointer[t], np.arange(n_states)]

    path = np.zeros(n, dtype=int)
    path[-1] = int(np.argmax(delta[-1]))
    for t in range(n - 2, -1, -1):
        path[t] = backpointer[t + 1, path[t + 1]]
    return path


def _detect_hmm(close: np.ndarray, high: np.ndarray, low: np.ndarray, n_states: int = 3, iterations: int = 8) -> List[int]:
    n = len(close)
    if n < 30:
        maxima, minima = _local_extrema(close, order=2)
        return maxima + minima

    changes = np.diff(close)
    scale = float(changes.std())
    if scale <= 0:
        return []
    observations = changes / scale

    try:
        means, variances, transition, start = _fit_gaussian_hmm(
            observations, n_states=max(2, int(n_states)), iterations=max(1, int(iterations))
        )
        path = _viterbi(observations, means, variances, transition, start)
    except Exception as e:
        logger.warning(f"Hidden Markov Model fitting failed, falling back to extrema: {e}")
        maxima, minima = _local_extrema(close, order=2)
        return maxima + minima

    direction = np.zeros(len(path), dtype=int)
    for rank, state in enumerate(np.argsort(means)):
        direction[path == state] = rank - 1

    full_direction = np.zeros(n, dtype=int)
    full_direction[0] = direction[0]
    full_direction[1:] = direction
    return _flip_pivots(full_direction, high, low)


def detect_swings(
    algorithm: SwingAlgorithm,
    prices: Sequence[float],
    ohlc: Optional[Tuple[Sequence[float], Sequence[float], Sequence[float]]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> List[int]:
    """Returns the sorted indices of the swing pivot points detected by the given algorithm."""
    close = np.asarray(prices, dtype=float)
    n = len(close)
    if n == 0:
        return []
    if n == 1:
        return [0]

    values = default_swing_params(algorithm) if not params else normalize_swing_params(algorithm, params)

    high = low = open_ = None
    if algorithm != SwingAlgorithm.RANGE:
        open_, high, low = _resolve_ohlc(close, ohlc)

    candidates: List[int] = []
    try:
        if algorithm == SwingAlgorithm.RANGE:
            candidates = []
        elif algorithm == SwingAlgorithm.ZIGZAG:
            atr_multiple = values.get("atr_multiple", 0.0)
            atr = _atr(high, low, close) if atr_multiple > 0 else None
            candidates = _detect_zigzag(
                close,
                threshold_pct=values.get("threshold_pct", 5.0),
                atr=atr,
                atr_multiple=atr_multiple if atr_multiple > 0 else None,
            )
        elif algorithm == SwingAlgorithm.WILLIAMS_FRACTALS:
            candidates = _detect_williams_fractals(
                close, high, low, order=int(values.get("order", 2))
            )
        elif algorithm == SwingAlgorithm.PIVOT_WINDOW:
            candidates = _detect_pivot_window(
                close,
                window=int(values.get("window", 5)),
                prominence_ratio=values.get("prominence_ratio", 0.05),
            )
        elif algorithm == SwingAlgorithm.SWING_INDEX:
            candidates = _detect_swing_index(
                high, low, open_, close, limit_factor=values.get("limit_factor", 3.0)
            )
        elif algorithm == SwingAlgorithm.PARABOLIC_SAR:
            candidates = _detect_parabolic_sar(
                high,
                low,
                close,
                af_step=values.get("af_step", 0.02),
                af_max=values.get("af_max", 0.2),
            )
        elif algorithm == SwingAlgorithm.SUPERTREND:
            candidates = _detect_supertrend(
                high,
                low,
                close,
                period=int(values.get("period", 10)),
                mult=values.get("mult", 3.0),
            )
        elif algorithm == SwingAlgorithm.CHANDELIER_EXIT:
            candidates = _detect_chandelier(
                high,
                low,
                close,
                period=int(values.get("period", 22)),
                mult=values.get("mult", 3.0),
            )
        elif algorithm == SwingAlgorithm.DONCHIAN:
            candidates = _detect_donchian(high, low, close, period=int(values.get("period", 20)))
        elif algorithm == SwingAlgorithm.HEIKIN_ASHI:
            candidates = _detect_heikin_ashi(
                open_, high, low, close, order=int(values.get("order", 2))
            )
        elif algorithm == SwingAlgorithm.RSI:
            candidates = _detect_rsi(
                close,
                period=int(values.get("period", 14)),
                upper=values.get("upper", 70.0),
                lower=values.get("lower", 30.0),
            )
        elif algorithm == SwingAlgorithm.STOCHASTIC:
            candidates = _detect_stochastic(
                high,
                low,
                close,
                period=int(values.get("period", 14)),
                smooth=int(values.get("smooth", 3)),
                upper=values.get("upper", 80.0),
                lower=values.get("lower", 20.0),
            )
        elif algorithm == SwingAlgorithm.MACD:
            candidates = _detect_macd(
                close,
                fast=int(values.get("fast", 12)),
                slow=int(values.get("slow", 26)),
                signal=int(values.get("signal", 9)),
            )
        elif algorithm == SwingAlgorithm.CCI:
            candidates = _detect_cci(
                high,
                low,
                close,
                period=int(values.get("period", 20)),
                upper=values.get("upper", 100.0),
                lower=values.get("lower", -100.0),
            )
        elif algorithm == SwingAlgorithm.BOLLINGER:
            candidates = _detect_bollinger(
                close,
                period=int(values.get("period", 20)),
                mult=values.get("mult", 2.0),
            )
        elif algorithm == SwingAlgorithm.KELTNER:
            candidates = _detect_keltner(
                close,
                high,
                low,
                period=int(values.get("period", 20)),
                mult=values.get("mult", 2.0),
                atr_period=int(values.get("atr_period", 10)),
            )
        elif algorithm == SwingAlgorithm.CHANGE_POINT:
            candidates = _detect_change_point(
                close,
                min_size=int(values.get("min_size", 5)),
                penalty_factor=values.get("penalty_factor", 3.0),
                cusum_threshold=values.get("cusum_threshold", 0.0),
            )
        elif algorithm == SwingAlgorithm.KALMAN:
            candidates = _detect_kalman(
                close,
                process_noise=values.get("process_noise", 1e-4),
                measurement_noise=values.get("measurement_noise", 0.5),
            )
        elif algorithm == SwingAlgorithm.SAVITZKY_GOLAY:
            candidates = _detect_savitzky_golay(
                close,
                window_size=int(values.get("window_size", 7)),
                polyorder=int(values.get("polyorder", 2)),
            )
        elif algorithm == SwingAlgorithm.HILBERT:
            candidates = _detect_hilbert(close)
        elif algorithm == SwingAlgorithm.WAVELETS:
            level = int(values.get("level", 0))
            candidates = _detect_wavelets(close, level=level if level > 0 else None)
        elif algorithm == SwingAlgorithm.HMM:
            candidates = _detect_hmm(
                close,
                high,
                low,
                n_states=int(values.get("n_states", 3)),
                iterations=int(values.get("iterations", 8)),
            )
    except Exception as e:
        logger.error(f"Error detecting swings with {algorithm}: {e}")
        candidates = []

    return _finalize_pivots(candidates, close)


def has_significant_swing(
    algorithm: SwingAlgorithm,
    prices: Sequence[float],
    ohlc: Optional[Tuple[Sequence[float], Sequence[float], Sequence[float]]] = None,
    threshold_pct: Optional[float] = None,
    params: Optional[Dict[str, Any]] = None,
) -> bool:
    """Returns True when the price series contains a swing of at least threshold_pct for the given algorithm."""
    threshold = SWING_THRESHOLD_PCT if threshold_pct is None else threshold_pct
    if params is not None:
        min_swing = normalize_swing_params(algorithm, params).get("min_swing_pct")
        if min_swing is not None:
            threshold = min_swing

    if algorithm == SwingAlgorithm.RANGE:
        valid = [p for p in prices if p and p > 0]
        if len(valid) < 2:
            return False
        low = min(valid)
        return bool((max(valid) - low) / low * 100.0 >= threshold)

    series = [p for p in prices if p is not None]
    if len(series) < 2:
        return False

    pivots = detect_swings(algorithm, series, ohlc, params=params)
    for a, b in zip(pivots, pivots[1:]):
        first = series[a]
        second = series[b]
        low = min(first, second)
        high = max(first, second)
        if low and low > 0 and (high - low) / low * 100.0 >= threshold:
            return True
    return False
