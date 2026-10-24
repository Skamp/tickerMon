"""Technical indicator calculations used by the chart overlays.

EMA seeding: the EMA is seeded with the first value of the input series
(``EMA_1 = values[0]``) and then recursed with ``alpha = 2 / (period + 1)``.
This matches the existing ``apply_ema_reduction`` convention in
``noise_reduction.py``. When the caller supplies a warm-up series (extra
history before the visible chart range), the seed is set far back from the
visible range so the values at the left edge of the chart are accurate.

ATR smoothing: Wilder's smoothing (the conventional ATR definition):
``ATR_t = (ATR_(t-1) * (period - 1) + TR_t) / period``. The series is seeded
with the simple average of the first ``period`` True Range values; bars before
the seed index yield ``None`` (rendered as gaps). Fewer than ``period`` valid
True Range values yields an all-``None`` series (insufficient history).
"""

import math
from typing import List, Optional, Sequence, Tuple

ATR_PERIOD = 14


def _to_float(value) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def compute_ema(values: Sequence[float], period: int) -> List[Optional[float]]:
    """Returns the exponential moving average of ``values`` for the given period.

    Seeded with the first valid value; non-finite inputs are skipped (the
    running EMA is carried forward). Returns None entries until the first
    valid value is seen.
    """
    result: List[Optional[float]] = []
    if period < 1:
        return [None] * len(values)

    alpha = 2.0 / (period + 1.0)
    current: Optional[float] = None
    for raw in values:
        value = _to_float(raw)
        if value is None:
            result.append(current)
            continue
        if current is None:
            current = value
        else:
            current = alpha * value + (1.0 - alpha) * current
        result.append(current)
    return result


def compute_true_range(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
) -> List[Optional[float]]:
    """Returns the True Range series: max(H-L, |H-prevC|, |L-prevC|).

    The first bar has no previous close, so its True Range is simply H-L.
    Bars with missing/invalid OHLC values yield None.
    """
    count = min(len(highs), len(lows), len(closes))
    result: List[Optional[float]] = []
    prev_close: Optional[float] = None

    for i in range(count):
        high = _to_float(highs[i])
        low = _to_float(lows[i])
        close = _to_float(closes[i])

        if high is None or low is None:
            result.append(None)
            continue

        tr = high - low
        if prev_close is not None:
            tr = max(tr, abs(high - prev_close), abs(low - prev_close))
        result.append(tr)

        if close is not None:
            prev_close = close

    return result


def compute_atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = ATR_PERIOD,
) -> List[Optional[float]]:
    """Returns the Wilder-smoothed ATR series for the given period.

    Seeded with the simple average of the first ``period`` valid True Range
    values; earlier bars and bars with invalid inputs yield None. Fewer than
    ``period`` valid True Range values yields an all-None series.
    """
    true_ranges = compute_true_range(highs, lows, closes)
    count = len(true_ranges)
    result: List[Optional[float]] = [None] * count
    if period < 1:
        return result

    valid_trs = [tr for tr in true_ranges if tr is not None]
    if len(valid_trs) < period:
        return result

    atr: Optional[float] = None
    seed_trs: List[float] = []
    for i, tr in enumerate(true_ranges):
        if tr is None:
            continue
        if atr is None:
            seed_trs.append(tr)
            if len(seed_trs) == period:
                atr = sum(seed_trs) / period
                result[i] = atr
            continue
        atr = (atr * (period - 1) + tr) / period
        result[i] = atr

    return result


def compute_atr_bands(
    closes: Sequence[float],
    atr: Sequence[float],
    multiplier: float,
) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    """Returns (upper, lower) volatility bands: Close ± multiplier × ATR.

    Entries are None wherever the close or ATR value is missing, so the
    rendered bands gapped rather than interpolated across invalid bars.
    """
    count = min(len(closes), len(atr))
    upper: List[Optional[float]] = []
    lower: List[Optional[float]] = []
    for i in range(count):
        close = _to_float(closes[i])
        atr_value = _to_float(atr[i])
        if close is None or atr_value is None:
            upper.append(None)
            lower.append(None)
            continue
        offset = abs(float(multiplier)) * atr_value
        upper.append(close + offset)
        lower.append(close - offset)
    return upper, lower
