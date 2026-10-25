"""Deterministic baseline forecasting engine (``baseline_v1``).

Methodology
-----------
The engine is a transparent, reproducible statistical baseline — not a trained
model. Given the same historical series, filter/swing configuration and model
version it always produces the same forecast. It never reads data past the
reference bar; walk-forward validation truncates the series at each origin so
no future information can leak into a historical forecast.

Signals (each in [-1, 1], missing components are dropped and the remaining
weights renormalized — never treated as bearish):

- Trend (weight 0.35): ``tanh(mean_daily_log_return / sigma_daily)`` over the
  trend lookback, i.e. the recent drift measured in volatility units.
- Momentum (weight 0.15): ``tanh(log_return_20d / (sigma_daily * sqrt(20)))``.
- Filter (weight 0.30): derived from the *actual* selected filter calculation.
  Moving-average filters contribute price-above/below and filter-slope
  sub-signals; ATR filters contribute volatility only (never direction);
  other smoothing filters contribute the price-vs-filtered-distance and
  filtered-slope sub-signals.
- Structure (weight 0.20): the latest confirmed market-structure label
  (HH/HL -> +1, LH/LL -> -1, none -> unavailable). Only confirmed pivots are
  used — the trailing-bar anchor of the swing detection is excluded.

Directional bias: score >= +0.15 -> Bullish, <= -0.15 -> Bearish, otherwise
Neutral (the evidence is conflicting or weak).

Price projection (geometric Brownian-motion style baseline)::

    mu_daily = 0.6 * mean_daily_log_return + 0.4 * (score * sigma_daily * 0.25)
    ForecastPrice(t) = ReferenceClose * exp(mu_daily * t)
    band(t) = ForecastPrice(t) * exp(± z * sigma_daily * sqrt(t))

``mu_daily`` is clamped to ±2 sigma/day so a single strong signal cannot
extrapolate an implausible path. ``z`` (band_z) is 1.0 (~68% under a normal
approximation); the band is an *estimated forecast range*, not guaranteed
support/resistance. Volatility is the sample standard deviation of daily
log returns of adjusted closes.

Horizons are calendar months mapped to ``21`` trading sessions per month
(``SESSIONS_PER_MONTH``); the target epoch projects forward using the median
session gap of the recent history, which approximates the next valid trading
session without needing an exchange calendar. Evaluation against actual data
uses the first stored close on or after the calendar target date.

Forecasts are computed on adjusted closes (the chart's price series); OHLC
values are scaled by the close/adj_close ratio exactly like the chart, so ATR
and swing calculations match the visible overlays.
"""

import calendar
import logging
import math
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.models.forecast import (
    DirectionalBias,
    Forecast,
    ForecastHorizon,
    now_iso,
)
from app.services.market_structure import (
    LABEL_HH,
    LABEL_HL,
    LABEL_LH,
    LABEL_LL,
    classify_structure,
    pivot_kinds,
)
from app.services.noise_reduction import NoiseReductionAlgorithm, reduce_noise
from app.services.swing_detection import (
    SwingAlgorithm,
    SWING_THRESHOLD_PCT,
    detect_swings,
)
from app.services.swing_levels import confirmed_pivot_indices
from app.services.technical_indicators import ATR_PERIOD, compute_atr, compute_ema

logger = logging.getLogger(__name__)

FORECAST_MODEL_VERSION = "baseline_v1"

MIN_SESSIONS = 60
TREND_LOOKBACK = 60
MOMENTUM_LOOKBACK = 20
VOLATILITY_LOOKBACK = 120
SLOPE_WINDOW = 5
SESSIONS_PER_MONTH = 21
BAND_Z = 1.0
BIAS_THRESHOLD = 0.15
W_TREND = 0.35
W_MOMENTUM = 0.15
W_FILTER = 0.30
W_STRUCTURE = 0.20
DRIFT_SCORE_SIGMA = 0.25
MU_HIST_WEIGHT = 0.6
MU_DRIFT_WEIGHT = 0.4
MU_CLAMP_SIGMA = 2.0

_EMA_SPANS = {
    NoiseReductionAlgorithm.EMA: 20,
    NoiseReductionAlgorithm.EMA20: 20,
    NoiseReductionAlgorithm.EMA50: 50,
    NoiseReductionAlgorithm.EMA200: 200,
}

_STRUCTURE_BIAS = {
    LABEL_HH: 1.0,
    LABEL_HL: 1.0,
    LABEL_LH: -1.0,
    LABEL_LL: -1.0,
}


class ForecastError(Exception):
    """Raised when a forecast cannot be generated from the available data."""


def add_months(day: date, months: int) -> date:
    """Returns ``day`` shifted by whole calendar months, clamped to month end."""
    total = day.month - 1 + months
    year = day.year + total // 12
    month = total % 12 + 1
    day_of_month = min(day.day, calendar.monthrange(year, month)[1])
    return date(year, month, day_of_month)


def _finite(value) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _clean_series(
    timestamps: Sequence[float],
    closes: Sequence[float],
) -> Tuple[List[float], List[float]]:
    xs: List[float] = []
    ys: List[float] = []
    for raw_x, raw_y in zip(timestamps, closes):
        x = _finite(raw_x)
        y = _finite(raw_y)
        if x is None or y is None or y <= 0:
            continue
        xs.append(x)
        ys.append(y)
    return xs, ys


def _log_returns(closes: Sequence[float]) -> List[float]:
    return [
        math.log(closes[i] / closes[i - 1])
        for i in range(1, len(closes))
        if closes[i - 1] > 0 and closes[i] > 0
    ]


def _sample_std(values: Sequence[float]) -> Optional[float]:
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(variance)


def _median(values: Sequence[float]) -> Optional[float]:
    ordered = sorted(v for v in values if math.isfinite(v))
    if not ordered:
        return None
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _tanh_unit(x: float) -> float:
    try:
        return math.tanh(x)
    except (OverflowError, ValueError):
        return 0.0


def _slope_normalized(series: Sequence[float], window: int = SLOPE_WINDOW) -> Optional[float]:
    """Last-``window``-bar slope of ``series`` scaled by the last value."""
    if len(series) < 2:
        return None
    k = min(max(window, 1), len(series) - 1)
    start = series[-1 - k]
    end = series[-1]
    if start is None or end is None:
        return None
    start = _finite(start)
    end = _finite(end)
    if start is None or end is None or start <= 0 or end <= 0:
        return None
    return (end - start) / start


def _filter_features(
    algorithm: NoiseReductionAlgorithm,
    timestamps: Sequence[float],
    closes: Sequence[float],
    highs: Optional[Sequence[float]],
    lows: Optional[Sequence[float]],
    sigma_daily: Optional[float],
) -> Tuple[List[float], List[str], Dict[str, Any]]:
    """Derives directional (and volatility-only) sub-signals from the filter.

    Returns ``(sub_signals, supporting_lines, details)`` where each sub-signal
    is a value in [-1, 1]. ATR filters contribute no directional sub-signal —
    ATR describes volatility, not direction.
    """
    sub_signals: List[float] = []
    supporting: List[str] = []
    details: Dict[str, Any] = {"filter": algorithm.value}

    if algorithm == NoiseReductionAlgorithm.NONE:
        return sub_signals, supporting, details

    last_close = closes[-1]

    if algorithm in _EMA_SPANS:
        span = _EMA_SPANS[algorithm]
        ema = compute_ema(closes, span)
        last_ema = _finite(ema[-1]) if ema else None
        if last_ema is not None and last_ema > 0:
            above = last_close > last_ema
            sub_signals.append(1.0 if above else -1.0)
            supporting.append(
                f"Close {'above' if above else 'below'} EMA {span}"
            )
            slope = _slope_normalized(ema)
            if slope is not None:
                if sigma_daily and sigma_daily > 0:
                    slope_sig = _tanh_unit(slope / sigma_daily)
                else:
                    slope_sig = 1.0 if slope > 0 else (-1.0 if slope < 0 else 0.0)
                if abs(slope_sig) > 1e-9:
                    sub_signals.append(max(-1.0, min(1.0, slope_sig)))
                    supporting.append(
                        f"EMA {span} slope {'positive' if slope > 0 else 'negative'}"
                    )
            details["ema_span"] = span
            details["ema_value"] = last_ema
            details["price_vs_ema"] = (last_close - last_ema) / last_ema
        return sub_signals, supporting, details

    if algorithm in (NoiseReductionAlgorithm.ATR2, NoiseReductionAlgorithm.ATR4):
        multiplier = 2.0 if algorithm == NoiseReductionAlgorithm.ATR2 else 4.0
        atr_value = None
        if highs is not None and lows is not None and len(highs) == len(closes):
            atr_series = compute_atr(highs, lows, closes, period=ATR_PERIOD)
            atr_value = _finite(atr_series[-1]) if atr_series else None
        if atr_value is not None and last_close > 0:
            atr_pct = atr_value / last_close
            details["atr_pct"] = atr_pct
            details["atr_multiple"] = multiplier
            supporting.append(
                f"ATR14 at {atr_pct * 100:.2f}% of price (volatility, not direction)"
            )
        return sub_signals, supporting, details

    try:
        _, filtered = reduce_noise(algorithm, list(timestamps), list(closes))
    except Exception as e:
        logger.warning(f"Filter {algorithm.value} failed during forecast: {e}")
        return sub_signals, supporting, details

    filtered = [_finite(v) for v in filtered]
    valid = [(t, v) for t, v in zip(timestamps, filtered) if v is not None and v > 0]
    if len(valid) < 2:
        return sub_signals, supporting, details

    last_filtered = valid[-1][1]
    distance = (last_close - last_filtered) / last_filtered
    details["price_vs_filter"] = distance
    slope = _slope_normalized([v for _, v in valid])
    if slope is not None:
        details["filter_slope"] = slope
        if sigma_daily and sigma_daily > 0:
            slope_sig = _tanh_unit(slope / sigma_daily)
        else:
            slope_sig = 1.0 if slope > 0 else (-1.0 if slope < 0 else 0.0)
        if abs(slope_sig) > 1e-9:
            sub_signals.append(max(-1.0, min(1.0, slope_sig)))
            supporting.append(
                f"{algorithm.value} slope {'positive' if slope > 0 else 'negative'}"
            )
    distance_sig = max(-1.0, min(1.0, distance / 0.05))
    if abs(distance_sig) > 1e-9:
        sub_signals.append(distance_sig)
        supporting.append(
            f"Price {'above' if distance > 0 else 'below'} {algorithm.value}"
        )
    return sub_signals, supporting, details


def _structure_features(
    closes: Sequence[float],
    highs: Optional[Sequence[float]],
    lows: Optional[Sequence[float]],
    swing_algorithm: SwingAlgorithm,
    swing_params: Optional[Dict[str, float]],
) -> Tuple[Optional[float], Optional[str], Dict[str, Any], List[str]]:
    """Confirms pivots (excluding the trailing anchor) and reads structure."""
    supporting: List[str] = []
    details: Dict[str, Any] = {"swing_algorithm": swing_algorithm.value}
    if swing_params:
        details["swing_params"] = dict(swing_params)

    ohlc = None
    if swing_algorithm != SwingAlgorithm.RANGE and highs is not None and lows is not None:
        prev = [closes[0]] + list(closes[:-1])
        ohlc = (prev, highs, lows)

    try:
        pivots = detect_swings(swing_algorithm, closes, ohlc, params=swing_params)
    except Exception as e:
        logger.warning(f"Swing detection failed during forecast: {e}")
        return None, None, details, supporting

    if swing_algorithm == SwingAlgorithm.RANGE and len(closes) >= 2:
        low_index = min(range(len(closes)), key=closes.__getitem__)
        high_index = max(range(len(closes)), key=closes.__getitem__)
        pivots = sorted(set(pivots) | {low_index, high_index})

    confirmed = confirmed_pivot_indices(pivots, len(closes))
    details["confirmed_pivots"] = len(confirmed)
    if not confirmed:
        return None, None, details, supporting

    macro_threshold = (swing_params or {}).get("min_swing_pct", SWING_THRESHOLD_PCT)
    try:
        structure_points = classify_structure(
            confirmed, closes, macro_threshold_pct=macro_threshold
        )
    except Exception as e:
        logger.warning(f"Structure classification failed during forecast: {e}")
        return None, None, details, supporting

    latest = structure_points[-1] if structure_points else None
    label = latest.label if latest else None
    details["structure_label"] = label
    details["structure_macro"] = bool(latest.is_macro) if latest else False
    if label:
        supporting.append(
            f"Latest structure: {latest.text}"
        )

    kinds = pivot_kinds(pivots, closes)
    kind_by_index = {int(p): k for p, k in zip(pivots, kinds)}
    last_close = closes[-1]
    latest_high: Optional[int] = None
    latest_low: Optional[int] = None
    for idx in confirmed:
        kind = kind_by_index.get(idx)
        if kind == "high":
            latest_high = idx
        elif kind == "low":
            latest_low = idx
    for idx, key in ((latest_high, "swing_high"), (latest_low, "swing_low")):
        if idx is None:
            continue
        price = closes[idx]
        details[key] = price
        pct = (price - last_close) / last_close * 100.0 if last_close > 0 else 0.0
        supporting.append(
            f"Last confirmed swing {'high' if key == 'swing_high' else 'low'}: "
            f"{price:,.2f} ({pct:+.2f}% vs close)"
        )

    bias = _STRUCTURE_BIAS.get(label) if label else None
    return bias, label, details, supporting


def generate_forecast(
    ticker: str,
    timestamps: Sequence[float],
    closes: Sequence[float],
    *,
    highs: Optional[Sequence[float]] = None,
    lows: Optional[Sequence[float]] = None,
    horizon: ForecastHorizon = ForecastHorizon.ONE_MONTH,
    filter_algorithm: NoiseReductionAlgorithm = NoiseReductionAlgorithm.NONE,
    swing_algorithm: SwingAlgorithm = SwingAlgorithm.RANGE,
    swing_params: Optional[Dict[str, float]] = None,
    swing_range_settings: Optional[Dict[str, Any]] = None,
    currency_code: Optional[str] = None,
    generated_at: Optional[str] = None,
) -> Forecast:
    """Generates a deterministic forecast from the given historical series.

    ``timestamps`` are UNIX epoch floats and ``closes`` the adjusted-close
    series (chart convention). ``highs``/``lows`` are optional scaled OHLC
    values aligned bar-by-bar; ATR features degrade gracefully without them.
    Raises ``ForecastError`` when the series is too short or invalid.
    """
    months = horizon.months
    if months <= 0:
        raise ForecastError("Cannot generate a forecast for the Off horizon.")

    xs, ys = _clean_series(timestamps, closes)
    if len(ys) < MIN_SESSIONS:
        raise ForecastError(
            f"Insufficient history for forecasting: {len(ys)} valid sessions "
            f"(need at least {MIN_SESSIONS})."
        )

    n = len(ys)
    count = min(n, len(highs) if highs is not None else n, len(lows) if lows is not None else n)
    highs_valid: Optional[List[float]] = None
    lows_valid: Optional[List[float]] = None
    if highs is not None and lows is not None and count == n:
        highs_valid = list(highs[:n])
        lows_valid = list(lows[:n])

    reference_close = ys[-1]
    reference_dt = datetime.fromtimestamp(xs[-1])
    reference_date = reference_dt.date()
    target_date = add_months(reference_date, months)

    # Volatility and mean return from log returns of adjusted closes.
    returns = _log_returns(ys[-(VOLATILITY_LOOKBACK + 1):])
    sigma_daily = _sample_std(returns)
    trend_returns = _log_returns(ys[-(TREND_LOOKBACK + 1):])
    mean_daily = (sum(trend_returns) / len(trend_returns)) if trend_returns else 0.0
    if sigma_daily is None or sigma_daily <= 0:
        sigma_daily = _sample_std(returns) or 0.0
    if sigma_daily <= 0:
        # Flat series: use a tiny floor so math stays defined but drift ~ 0.
        sigma_daily = 1e-9

    # Signal score with renormalized weights over available components.
    components: List[Tuple[float, float, str]] = []
    trend_sig = _tanh_unit(mean_daily / sigma_daily)
    if abs(trend_sig) > 1e-9:
        components.append((W_TREND, trend_sig, "trend"))

    mom_slice = ys[-(MOMENTUM_LOOKBACK + 1):]
    if len(mom_slice) >= 2 and mom_slice[0] > 0:
        mom_return = math.log(mom_slice[-1] / mom_slice[0])
        mom_sig = _tanh_unit(mom_return / (sigma_daily * math.sqrt(MOMENTUM_LOOKBACK)))
        if abs(mom_sig) > 1e-9:
            components.append((W_MOMENTUM, mom_sig, "momentum"))

    filter_subs, filter_support, filter_details = _filter_features(
        filter_algorithm, xs, ys, highs_valid, lows_valid, sigma_daily
    )
    if filter_subs:
        avg = sum(filter_subs) / len(filter_subs)
        if abs(avg) > 1e-9:
            components.append((W_FILTER, max(-1.0, min(1.0, avg)), "filter"))

    struct_bias, struct_label, struct_details, struct_support = _structure_features(
        ys, highs_valid, lows_valid, swing_algorithm, swing_params
    )
    if struct_bias is not None and abs(struct_bias) > 1e-9:
        components.append((W_STRUCTURE, struct_bias, "structure"))

    if components:
        total_weight = sum(w for w, _, _ in components)
        score = sum(w * s for w, s, _ in components) / total_weight if total_weight > 0 else 0.0
    else:
        score = 0.0
    score = max(-1.0, min(1.0, score))

    if score >= BIAS_THRESHOLD:
        bias = DirectionalBias.BULLISH.value
    elif score <= -BIAS_THRESHOLD:
        bias = DirectionalBias.BEARISH.value
    else:
        bias = DirectionalBias.NEUTRAL.value

    drift = score * sigma_daily * DRIFT_SCORE_SIGMA
    mu_daily = MU_HIST_WEIGHT * mean_daily + MU_DRIFT_WEIGHT * drift
    clamp = MU_CLAMP_SIGMA * sigma_daily
    mu_daily = max(-clamp, min(clamp, mu_daily))

    n_sessions = months * SESSIONS_PER_MONTH
    gaps = [xs[i] - xs[i - 1] for i in range(1, n) if xs[i] > xs[i - 1]]
    median_gap = _median(gaps) if gaps else 86400.0
    if median_gap is None or median_gap <= 0:
        median_gap = 86400.0

    central = reference_close * math.exp(mu_daily * n_sessions)
    sigma_horizon = sigma_daily * math.sqrt(n_sessions)
    lower = central * math.exp(-BAND_Z * sigma_horizon)
    upper = central * math.exp(BAND_Z * sigma_horizon)
    expected_change_pct = (central - reference_close) / reference_close * 100.0

    path_epochs = [xs[-1]]
    path_central = [reference_close]
    path_lower = [reference_close]
    path_upper = [reference_close]
    for t in range(1, n_sessions + 1):
        c_t = reference_close * math.exp(mu_daily * t)
        band = BAND_Z * sigma_daily * math.sqrt(float(t))
        path_epochs.append(xs[-1] + median_gap * t)
        path_central.append(c_t)
        path_lower.append(c_t * math.exp(-band))
        path_upper.append(c_t * math.exp(band))

    supporting = list(filter_support) + list(struct_support)
    supporting.append(
        f"{TREND_LOOKBACK}-session mean log return {mean_daily * 100:.3f}%/day"
    )
    assumptions = [
        "Estimated forecast range (±1 sigma), not guaranteed support/resistance.",
        "Based on adjusted closes; constant drift and volatility assumptions.",
        f"Horizon mapped to {n_sessions} trading sessions (~{SESSIONS_PER_MONTH}/month).",
        "Neutral bias means evidence is conflicting, not a prediction of no move.",
    ]

    input_snapshot: Dict[str, Any] = {
        "filter": filter_algorithm.value,
        "swing_algorithm": swing_algorithm.value,
        "swing_params": dict(swing_params or {}),
        "swing_range_settings": dict(swing_range_settings or {}),
        "price_basis": "adjusted_close",
        "lookbacks": {
            "trend": TREND_LOOKBACK,
            "momentum": MOMENTUM_LOOKBACK,
            "volatility": VOLATILITY_LOOKBACK,
        },
        "sigma_daily": sigma_daily,
        "mean_daily_log_return": mean_daily,
        "mu_daily": mu_daily,
        "band_z": BAND_Z,
        "n_sessions": n_sessions,
        "sessions_per_month": SESSIONS_PER_MONTH,
        "median_gap": median_gap,
        "reference_epoch": xs[-1],
        "min_sessions": MIN_SESSIONS,
        "bias_threshold": BIAS_THRESHOLD,
        "weights": {
            "trend": W_TREND,
            "momentum": W_MOMENTUM,
            "filter": W_FILTER,
            "structure": W_STRUCTURE,
        },
    }
    signal_summary: Dict[str, Any] = {
        "score": score,
        "bias": bias,
        "components": {name: sig for _, sig, name in components},
        "filter_details": filter_details,
        "structure_label": struct_label,
        "structure_details": struct_details,
        "supporting": supporting,
        "assumptions": assumptions,
    }

    return Forecast(
        ticker=ticker.upper().strip(),
        generated_at=generated_at or now_iso(),
        reference_date=reference_date.isoformat(),
        reference_close=reference_close,
        target_date=target_date.isoformat(),
        horizon_months=months,
        directional_bias=bias,
        central_estimate=central,
        lower_estimate=lower,
        upper_estimate=upper,
        expected_change_pct=expected_change_pct,
        model_version=FORECAST_MODEL_VERSION,
        input_snapshot=input_snapshot,
        signal_summary=signal_summary,
        currency_code=currency_code,
        path_epochs=path_epochs,
        path_central=path_central,
        path_lower=path_lower,
        path_upper=path_upper,
        target_epoch=path_epochs[-1],
    )
