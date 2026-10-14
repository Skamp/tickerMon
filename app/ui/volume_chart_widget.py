"""Compact volume sub-chart rendered directly below the main price chart.

Yahoo Finance's ``Volume`` field is the *total* traded volume for a period; the
API does not provide a true buy-volume vs sell-volume breakdown. Bars are
colored with an approximation of buying/selling pressure derived from the
candle direction only:

    Close > Open -> buying pressure (green)
    Close < Open -> selling pressure (red)
    Close == Open -> neutral (dimmed)

Bar heights always represent the real traded volume; the green/red colors must
not be read as actual buy/sell order flow.
"""

import bisect
import logging
import math
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget, QHBoxLayout, QVBoxLayout

import pyqtgraph as pg

from app.utils.currency import get_currency_symbol

logger = logging.getLogger(__name__)

BUY_COLOR = "#00e676"
SELL_COLOR = "#ff5252"
NEUTRAL_COLOR = "#8b90a0"

PRESSURE_BUYING = "Buying"
PRESSURE_SELLING = "Selling"
PRESSURE_NEUTRAL = "Neutral"

_CROSSHAIR_COLOR = "#454b61"
_TOOLTIP_FILL = "#1a1c24f0"
_MIN_PLOT_HEIGHT = 90


def format_volume(value: float) -> str:
    """Abbreviates a raw volume count (1200 -> 1.2K, 3500000 -> 3.5M)."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "0"
    if not math.isfinite(value):
        return "0"
    for threshold, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= threshold:
            abbreviated = f"{value / threshold:.2f}".rstrip("0").rstrip(".")
            return f"{abbreviated}{suffix}"
    return f"{value:.0f}"


def _is_valid_price(value: Optional[float]) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def classify_volume_pressure(
    open_value: Optional[float], close_value: Optional[float]
) -> str:
    """Estimates buying/selling pressure from candle direction (see module note)."""
    if not _is_valid_price(open_value) or not _is_valid_price(close_value):
        return PRESSURE_NEUTRAL
    if close_value > open_value:
        return PRESSURE_BUYING
    if close_value < open_value:
        return PRESSURE_SELLING
    return PRESSURE_NEUTRAL


def compute_bar_width(timestamps: List[float]) -> float:
    """Returns a narrow bar width (~70% of the median bar spacing) in time units."""
    if len(timestamps) >= 2:
        gaps = sorted(b - a for a, b in zip(timestamps, timestamps[1:]) if b > a)
        if gaps:
            spacing = gaps[len(gaps) // 2]
            if spacing > 0:
                return spacing * 0.7
    return 86400.0 * 0.7


def _sanitize_volume(value) -> float:
    try:
        volume = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(volume) or volume < 0:
        return 0.0
    return volume


def _sanitize_price(value) -> float:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(price) or price <= 0:
        return 0.0
    return price


def _legend_label(color: str, text: str, parent: QWidget) -> QLabel:
    label = QLabel(parent)
    label.setTextFormat(Qt.RichText)
    label.setText(
        f'<span style="color: {color};">■</span> '
        f'<span style="color: #8b90a0;">{text}</span>'
    )
    label.setStyleSheet("font-size: 11px;")
    return label


class VolumeAxisItem(pg.AxisItem):
    """Right-hand volume axis that abbreviates raw counts (K/M/B)."""

    def tickStrings(self, values, scale, spacing):
        return [format_volume(value) for value in values]


class VolumeChartWidget(QWidget):
    """Compact volume panel showing per-period traded volume bars.

    Bar color approximates buying/selling pressure from candle direction (see
    module docstring). The horizontal (time) axis is owned by the price chart:
    ``StockChartWidget`` X-links this panel's ViewBox to the price ViewBox, so
    ticker, range, zoom and duration changes keep both charts on the same time
    scale. Mouse zoom/pan is disabled on this panel to preserve that sync.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(2)

        header = QHBoxLayout()
        header.setSpacing(12)
        title = QLabel("VOLUME", self)
        title.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #8b90a0; letter-spacing: 1px;"
        )
        header.addWidget(title)
        header.addWidget(_legend_label(BUY_COLOR, "Buying pressure", self))
        header.addWidget(_legend_label(SELL_COLOR, "Selling pressure", self))
        header.addWidget(_legend_label(NEUTRAL_COLOR, "Neutral", self))
        header.addStretch()
        self.layout.addLayout(header)

        self.y_axis = VolumeAxisItem(orientation="right")
        self.plot_widget = pg.PlotWidget(axisItems={"right": self.y_axis})
        self.plot_widget.setMinimumHeight(_MIN_PLOT_HEIGHT)
        self.layout.addWidget(self.plot_widget)

        self.plot_item = self.plot_widget.getPlotItem()
        self.plot_item.showAxis("right", True)
        self.plot_item.hideAxis("left")
        # The price chart owns the shared time axis; hide this panel's bottom
        # axis so the date labels are not duplicated.
        self.plot_item.hideAxis("bottom")
        self.plot_item.showGrid(x=True, y=True, alpha=0.10)
        self.plot_item.setMenuEnabled(False)
        self.plot_item.vb.setMenuEnabled(False)
        # Both axes follow the linked price chart; mouse zoom/pan is disabled
        # here so the panel cannot desynchronize from the price chart.
        self.plot_item.vb.setMouseEnabled(x=False, y=False)
        # Never let this panel auto-range its own time axis: the X range comes
        # exclusively from the price chart, Y is fitted manually below.
        self.plot_item.enableAutoRange(axis=pg.ViewBox.XYAxes, enable=False)

        self._buy_bars = pg.BarGraphItem(x=[], height=[], width=1.0, pen=None, brush=BUY_COLOR)
        self._sell_bars = pg.BarGraphItem(x=[], height=[], width=1.0, pen=None, brush=SELL_COLOR)
        self._neutral_bars = pg.BarGraphItem(
            x=[], height=[], width=1.0, pen=None, brush=NEUTRAL_COLOR
        )
        for bars in (self._buy_bars, self._sell_bars, self._neutral_bars):
            self.plot_item.addItem(bars, ignoreBounds=True)

        crosshair_pen = pg.mkPen(_CROSSHAIR_COLOR, width=0.8)
        crosshair_pen.setStyle(Qt.DashLine)
        self.v_line = pg.InfiniteLine(angle=90, movable=False, pen=crosshair_pen)
        self.plot_item.addItem(self.v_line, ignoreBounds=True)
        self.v_line.setVisible(False)

        self.tooltip_text = pg.TextItem(
            text="", anchor=(0.5, 1.15), color="#ffffff", fill=pg.mkBrush(_TOOLTIP_FILL)
        )
        self.plot_item.addItem(self.tooltip_text, ignoreBounds=True)
        self.tooltip_text.setVisible(False)

        self._x_data: List[float] = []
        self._volumes: List[float] = []
        self._opens: List[float] = []
        self._closes: List[float] = []
        self._date_labels: List[str] = []
        self._currency_symbol = "$"

        self.plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)

    def set_currency(self, currency_code: Optional[str]) -> None:
        """Sets the currency symbol used by the Open/Close tooltip rows."""
        self._currency_symbol = get_currency_symbol(currency_code)

    def set_data(
        self,
        timestamps: List[float],
        volumes: List[float],
        opens: List[float],
        closes: List[float],
        date_labels: List[str],
    ) -> None:
        """Renders one volume bar per price period and refits the vertical range."""
        lengths = [len(timestamps), len(volumes), len(opens), len(closes), len(date_labels)]
        count = min(lengths)
        if len(set(lengths)) > 1:
            logger.warning(
                "Volume series lengths %s differ; truncating to %d points", lengths, count
            )

        self._x_data = [float(x) for x in timestamps[:count]]
        self._volumes = [_sanitize_volume(v) for v in volumes[:count]]
        self._opens = [_sanitize_price(o) for o in opens[:count]]
        self._closes = [_sanitize_price(c) for c in closes[:count]]
        self._date_labels = list(date_labels[:count])
        self._hide_hover()

        if not self._x_data:
            for bars in (self._buy_bars, self._sell_bars, self._neutral_bars):
                bars.setOpts(x=[], height=[], width=1.0)
            return

        buckets = {
            PRESSURE_BUYING: ([], []),
            PRESSURE_SELLING: ([], []),
            PRESSURE_NEUTRAL: ([], []),
        }
        for idx, timestamp in enumerate(self._x_data):
            pressure = classify_volume_pressure(self._opens[idx], self._closes[idx])
            xs, hs = buckets[pressure]
            xs.append(timestamp)
            hs.append(self._volumes[idx])

        width = compute_bar_width(self._x_data)
        self._buy_bars.setOpts(x=buckets[PRESSURE_BUYING][0], height=buckets[PRESSURE_BUYING][1], width=width)
        self._sell_bars.setOpts(x=buckets[PRESSURE_SELLING][0], height=buckets[PRESSURE_SELLING][1], width=width)
        self._neutral_bars.setOpts(
            x=buckets[PRESSURE_NEUTRAL][0], height=buckets[PRESSURE_NEUTRAL][1], width=width
        )

        self._fit_view_to_data()

    def clear(self) -> None:
        """Drops all cached volume data and hides hover feedback."""
        self._x_data = []
        self._volumes = []
        self._opens = []
        self._closes = []
        self._date_labels = []
        for bars in (self._buy_bars, self._sell_bars, self._neutral_bars):
            bars.setOpts(x=[], height=[], width=1.0)
        self._hide_hover()

    def reset_view(self) -> None:
        """Restores the vertical fit (the time axis resets with the price chart)."""
        if self._x_data and self._volumes:
            self._fit_view_to_data()

    def _fit_view_to_data(self) -> None:
        """Fits the volume (Y) range only; the X range is driven by the price chart."""
        vb = self.plot_item.vb
        vb.setLimits(yMin=None, yMax=None, maxYRange=None)
        self.plot_item.enableAutoRange(axis=pg.ViewBox.XYAxes, enable=False)

        y_max = max(self._volumes) if self._volumes else 0.0
        if y_max <= 0:
            y_max = 1.0
        y_max *= 1.1

        vb.setYRange(0.0, y_max, padding=0)
        vb.setLimits(yMin=0.0, yMax=y_max, maxYRange=y_max)

    def _build_tooltip(self, idx: int) -> str:
        date_str = self._date_labels[idx] if idx < len(self._date_labels) else ""
        volume = self._volumes[idx]
        open_value = self._opens[idx]
        close_value = self._closes[idx]
        pressure = classify_volume_pressure(open_value, close_value)

        lines = [f"Date: {date_str}", f"Volume: {format_volume(volume)}"]
        sym = self._currency_symbol
        if open_value > 0:
            lines.append(f"Open: {sym}{open_value:,.2f}")
        else:
            lines.append("Open: n/a")
        if close_value > 0:
            lines.append(f"Close: {sym}{close_value:,.2f}")
        else:
            lines.append("Close: n/a")
        if open_value > 0 and close_value > 0:
            change_pct = (close_value - open_value) / open_value * 100.0
            lines.append(f"Change: {change_pct:+.2f}%")
        else:
            lines.append("Change: n/a")
        lines.append(f"Pressure: {pressure} (estimated from candle direction)")
        return "\n".join(lines)

    def _hide_hover(self) -> None:
        self.v_line.setVisible(False)
        self.tooltip_text.setVisible(False)

    def _on_mouse_moved(self, pos) -> None:
        if not self._x_data:
            self._hide_hover()
            return

        mouse_point = self.plot_item.vb.mapSceneToView(pos)
        x_val = mouse_point.x()
        if x_val < self._x_data[0] or x_val > self._x_data[-1]:
            self._hide_hover()
            return

        idx = bisect.bisect_left(self._x_data, x_val)
        if idx >= len(self._x_data):
            idx = len(self._x_data) - 1
        elif idx > 0 and abs(self._x_data[idx - 1] - x_val) < abs(self._x_data[idx] - x_val):
            idx -= 1

        px = self._x_data[idx]
        py = self._volumes[idx]

        self.v_line.setPos(px)
        self.v_line.setVisible(True)

        y_lo, y_hi = self.plot_item.vb.viewRange()[1]
        if y_hi > y_lo and py > y_lo + (y_hi - y_lo) * 0.7:
            # Bar reaches the top of the panel: keep the tooltip inside it.
            self.tooltip_text.setAnchor((0.5, -0.15))
        else:
            self.tooltip_text.setAnchor((0.5, 1.15))
        self.tooltip_text.setText(self._build_tooltip(idx))
        self.tooltip_text.setPos(px, py)
        self.tooltip_text.setVisible(True)
