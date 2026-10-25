"""Forecast domain models: horizons, biases, immutable forecast records.

A ``Forecast`` is an immutable prediction snapshot: every field is fixed at
generation time and must never be recalculated when market data changes. The
only mutable data lives on a ``SavedForecast``'s evaluation fields, which
record the actual outcome once the target date has passed.

Forecasts are based on adjusted closing prices (the same scaled series the
chart renders); the input snapshot records this so saved forecasts remain
interpretable later.
"""

import html as html_lib
import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from app.utils.currency import get_currency_symbol

EVALUATION_PENDING = "pending"
EVALUATION_EVALUATED = "evaluated"
EVALUATION_UNAVAILABLE = "unavailable"

FORECAST_ANNOTATION_ANCHORS = (
    "top_right",
    "top_left",
    "bottom_right",
    "bottom_left",
    "hidden",
)
FORECAST_ANNOTATION_DEFAULT_ANCHOR = "top_right"
FORECAST_DRAG_HANDLE = "\u2261"
FORECAST_ANNOTATION_ANCHOR_LABELS = {
    "top_right": "Top Right",
    "top_left": "Top Left",
    "bottom_right": "Bottom Right",
    "bottom_left": "Bottom Left",
    "hidden": "Hide",
}


def normalize_forecast_annotation_anchor(raw: Any) -> str:
    """Returns a valid annotation anchor key, defaulting to ``top_right``."""
    if isinstance(raw, str):
        needle = raw.strip().lower().replace("-", "_").replace(" ", "_")
        if needle in FORECAST_ANNOTATION_ANCHOR_LABELS:
            return needle
    return FORECAST_ANNOTATION_DEFAULT_ANCHOR


FORECAST_FILTERS = ("off", "bullish", "bearish", "neutral", "any")
FORECAST_FILTER_DEFAULT = "off"
FORECAST_FILTER_LABELS = {
    "off": "Off",
    "bullish": "Bullish",
    "bearish": "Bearish",
    "neutral": "Neutral",
    "any": "Has forecast",
}


def normalize_forecast_filter(raw: Any) -> str:
    """Returns a valid forecast filter key, defaulting to ``off``."""
    if isinstance(raw, str):
        needle = raw.strip().lower().replace("-", "_").replace(" ", "_")
        if needle in FORECAST_FILTERS:
            return needle
    return FORECAST_FILTER_DEFAULT


class ForecastHorizon(Enum):
    OFF = "Off"
    ONE_MONTH = "1 Month"
    TWO_MONTHS = "2 Months"
    THREE_MONTHS = "3 Months"

    @classmethod
    def from_str(cls, val: str) -> "ForecastHorizon":
        for item in cls:
            if item.value == val or item.name == val:
                return item
        return cls.OFF

    @property
    def months(self) -> int:
        return {
            ForecastHorizon.OFF: 0,
            ForecastHorizon.ONE_MONTH: 1,
            ForecastHorizon.TWO_MONTHS: 2,
            ForecastHorizon.THREE_MONTHS: 3,
        }[self]


class DirectionalBias(Enum):
    BULLISH = "Bullish"
    BEARISH = "Bearish"
    NEUTRAL = "Neutral"

    @classmethod
    def from_str(cls, val: str) -> "DirectionalBias":
        needle = str(val).strip().lower()
        for item in cls:
            if needle in (item.value.lower(), item.name.lower()):
                return item
        return cls.NEUTRAL


@dataclass
class Forecast:
    """An immutable price forecast snapshot for one ticker and horizon.

    ``input_snapshot`` / ``signal_summary`` are JSON-serializable dicts that
    preserve the exact configuration and derived signals used to produce the
    prediction, so a saved forecast can be explained and reproduced later.
    """

    ticker: str
    generated_at: str
    reference_date: str
    reference_close: float
    target_date: str
    horizon_months: int
    directional_bias: str
    central_estimate: float
    lower_estimate: float
    upper_estimate: float
    expected_change_pct: float
    model_version: str
    input_snapshot: Dict[str, Any] = field(default_factory=dict)
    signal_summary: Dict[str, Any] = field(default_factory=dict)
    currency_code: Optional[str] = None
    path_epochs: List[float] = field(default_factory=list)
    path_central: List[float] = field(default_factory=list)
    path_lower: List[float] = field(default_factory=list)
    path_upper: List[float] = field(default_factory=list)
    target_epoch: float = 0.0

    @property
    def horizon_label(self) -> str:
        labels = {1: "1 Month", 2: "2 Months", 3: "3 Months"}
        return labels.get(self.horizon_months, f"{self.horizon_months} Months")

    @property
    def bias(self) -> DirectionalBias:
        return DirectionalBias.from_str(self.directional_bias)

    @property
    def estimated_volatility_pct(self) -> Optional[float]:
        sigma = self.input_snapshot.get("sigma_daily")
        if sigma is None:
            return None
        try:
            return float(sigma) * (252.0 ** 0.5) * 100.0
        except (TypeError, ValueError):
            return None


def forecast_matches_filter(forecast: Optional[Forecast], filter_key: str) -> bool:
    """Whether ``forecast`` satisfies the given forecast filter key.

    ``off`` matches everything; ``any`` requires a forecast to exist; the
    direction keys compare against the forecast's stored ``directional_bias``.
    """
    key = normalize_forecast_filter(filter_key)
    if key == "off":
        return True
    if forecast is None:
        return False
    if key == "any":
        return True
    return DirectionalBias.from_str(forecast.directional_bias).value.lower() == key


@dataclass
class SavedForecast:
    """A forecast persisted in SQLite plus its evaluation outcome fields."""

    id: int
    forecast: Forecast
    evaluation_status: str = EVALUATION_PENDING
    actual_price: Optional[float] = None
    actual_date: Optional[str] = None
    actual_change_pct: Optional[float] = None
    absolute_error: Optional[float] = None
    percentage_error: Optional[float] = None
    evaluated_at: Optional[str] = None


def rebuild_projection(forecast: Forecast) -> None:
    """Recomputes the chart projection path from the stored input snapshot.

    Saved forecasts do not persist the full path arrays; the deterministic
    geometric path is reconstructed from ``mu_daily``, ``sigma_daily``,
    ``band_z``, ``n_sessions`` and ``median_gap`` recorded in the snapshot,
    so the redrawn path always matches the original model.
    """
    snapshot = forecast.input_snapshot or {}
    try:
        mu = float(snapshot["mu_daily"])
        sigma = float(snapshot["sigma_daily"])
        z = float(snapshot.get("band_z", 1.0))
        n_sessions = int(snapshot["n_sessions"])
        gap = float(snapshot["median_gap"])
        ref_epoch = float(snapshot["reference_epoch"])
        ref_close = float(forecast.reference_close)
    except (KeyError, TypeError, ValueError):
        forecast.path_epochs = []
        forecast.path_central = []
        forecast.path_lower = []
        forecast.path_upper = []
        return

    epochs = [ref_epoch]
    central = [ref_close]
    lower = [ref_close]
    upper = [ref_close]
    for t in range(1, max(n_sessions, 1) + 1):
        c_t = ref_close * math.exp(mu * t)
        band = z * sigma * math.sqrt(float(t))
        epochs.append(ref_epoch + gap * t)
        central.append(c_t)
        lower.append(c_t * math.exp(-band))
        upper.append(c_t * math.exp(band))
    forecast.path_epochs = epochs
    forecast.path_central = central
    forecast.path_lower = lower
    forecast.path_upper = upper
    forecast.target_epoch = epochs[-1]


def format_forecast_annotation(forecast: Forecast, currency_code: Optional[str] = None) -> str:
    """Builds the compact multi-line chart annotation for a forecast."""
    symbol = get_currency_symbol(currency_code or forecast.currency_code)
    bias = DirectionalBias.from_str(forecast.directional_bias).value
    lines = [
        f"Forecast: {forecast.horizon_label} ({forecast.model_version})",
        f"Generated: {forecast.reference_date} | Target: {forecast.target_date}",
        f"Bias: {bias}",
        f"Central estimate: {symbol}{forecast.central_estimate:,.2f}",
        f"Estimated range: {symbol}{forecast.lower_estimate:,.2f} – {symbol}{forecast.upper_estimate:,.2f}",
        f"Expected change: {forecast.expected_change_pct:+.2f}%",
    ]
    return "\n".join(lines)


def format_forecast_annotation_html(
    forecast: Forecast,
    currency_code: Optional[str] = None,
    saved: bool = False,
) -> str:
    """Builds the chart annotation as HTML with a drag-handle line.

    A centered ``[ <U+2261> drag box ]`` line below the last information line
    marks the box as draggable without consuming space at the top or shifting
    the information lines.
    """
    lines = format_forecast_annotation(forecast, currency_code).split("\n")
    if saved:
        lines.insert(0, "Saved forecast")
    parts = [f"<div style='color:#e1e3ea;'>{html_lib.escape(line)}</div>" for line in lines]
    parts.append(
        f"<div align='center' style='color:#8b90a0;'>"
        f"[ {FORECAST_DRAG_HANDLE} drag box ]</div>"
    )
    return "".join(parts)


def format_forecast_details(forecast: Forecast, currency_code: Optional[str] = None) -> str:
    """Builds the long-form description used by dialogs and tooltips."""
    symbol = get_currency_symbol(currency_code or forecast.currency_code)
    bias = DirectionalBias.from_str(forecast.directional_bias).value
    lines = [
        f"Ticker: {forecast.ticker}",
        f"Horizon: {forecast.horizon_label}",
        f"Model: {forecast.model_version}",
        f"Reference close ({forecast.reference_date}): {symbol}{forecast.reference_close:,.2f}",
        "",
        f"Directional bias: {bias}",
        f"Central estimate: {symbol}{forecast.central_estimate:,.2f}",
        f"Lower estimate: {symbol}{forecast.lower_estimate:,.2f}",
        f"Upper estimate: {symbol}{forecast.upper_estimate:,.2f}",
        f"Expected change: {forecast.expected_change_pct:+.2f}%",
        f"Forecast generated: {forecast.generated_at}",
        f"Target date: {forecast.target_date}",
    ]

    vol_pct = forecast.estimated_volatility_pct
    if vol_pct is not None:
        lines.append(f"Estimated annualized volatility: {vol_pct:.1f}%")

    signals = forecast.signal_summary or {}
    supporting = signals.get("supporting") or []
    if supporting:
        lines.append("")
        lines.append("Supporting signals:")
        for item in supporting:
            lines.append(f"- {item}")

    assumptions = signals.get("assumptions") or []
    if assumptions:
        lines.append("")
        lines.append("Assumptions / limitations:")
        for item in assumptions:
            lines.append(f"- {item}")

    return "\n".join(lines)


def format_evaluation_details(record: SavedForecast, currency_code: Optional[str] = None) -> str:
    """Appends the actual outcome to the forecast details for history views."""
    symbol = get_currency_symbol(currency_code or record.forecast.currency_code)
    lines = [format_forecast_details(record.forecast, currency_code), ""]
    status = record.evaluation_status
    lines.append(f"Evaluation status: {status}")
    if record.evaluation_status == EVALUATION_EVALUATED:
        lines.append(f"Actual date: {record.actual_date}")
        if record.actual_price is not None:
            lines.append(f"Actual price: {symbol}{record.actual_price:,.2f}")
        if record.actual_change_pct is not None:
            lines.append(f"Actual change: {record.actual_change_pct:+.2f}%")
        if record.absolute_error is not None:
            lines.append(f"Absolute error: {symbol}{record.absolute_error:,.2f}")
        if record.percentage_error is not None:
            lines.append(f"Percentage error: {record.percentage_error:.2f}%")
        if record.evaluated_at:
            lines.append(f"Evaluated at: {record.evaluated_at}")
    return "\n".join(lines)


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
