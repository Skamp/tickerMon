import logging
import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPen, QBrush, QLinearGradient
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QGraphicsRectItem,
    QGraphicsItem,
    QMenu,
)

import pyqtgraph as pg

from app.models.chart_type import ChartType
from app.models.earnings import EarningsEvent, format_earnings_tooltip
from app.models.forecast import (
    FORECAST_ANNOTATION_ANCHOR_LABELS,
    FORECAST_ANNOTATION_DEFAULT_ANCHOR,
    Forecast,
    format_forecast_annotation_html,
    normalize_forecast_annotation_anchor,
)
from app.utils.currency import get_currency_symbol
from app.ui.volume_chart_widget import (
    BUY_COLOR,
    NEUTRAL_COLOR,
    SELL_COLOR,
    VolumeChartWidget,
    compute_bar_width,
)

logger = logging.getLogger(__name__)

# Configure PyQtGraph global options for ultra-clean dark financial terminal
pg.setConfigOption("background", "#121318")
pg.setConfigOption("foreground", "#8b90a0")
pg.setConfigOption("antialias", True)

CANDLE_BULLISH = "bullish"
CANDLE_BEARISH = "bearish"
CANDLE_NEUTRAL = "neutral"

_CANDLE_KINDS = (CANDLE_BULLISH, CANDLE_BEARISH, CANDLE_NEUTRAL)
_MIN_BODY_HEIGHT_RATIO = 0.004
_ABS_MIN_BODY_HEIGHT = 0.01

ATR2_COLOR = "#29b6f6"
ATR4_COLOR = "#ab47bc"
EMA20_COLOR = "#26c6da"

EARNINGS_CONFIRMED_COLOR = "#ffca28"
EARNINGS_ESTIMATED_COLOR = "#78909c"

FORECAST_COLOR = "#7e57c2"
FORECAST_BULLISH_COLOR = "#00e676"
FORECAST_BEARISH_COLOR = "#ff5252"
FORECAST_NEUTRAL_COLOR = "#8b90a0"

_FORECAST_ANCHOR_POINTS = {
    "top_right": (1.0, 0.0),
    "top_left": (0.0, 0.0),
    "bottom_right": (1.0, 1.0),
    "bottom_left": (0.0, 1.0),
}

_LEVEL_NEUTRAL_COLOR = "#8b90a0"


def _is_valid_ohlc(open_value, high_value, low_value, close_value) -> bool:
    try:
        o = float(open_value)
        h = float(high_value)
        l = float(low_value)
        c = float(close_value)
    except (TypeError, ValueError):
        return False
    if not all(math.isfinite(v) and v > 0 for v in (o, h, l, c)):
        return False
    top = max(o, c)
    bottom = min(o, c)
    return h >= top - 1e-9 and l <= bottom + 1e-9 and h >= l - 1e-9


def classify_candles(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
) -> List[Optional[str]]:
    """Classifies each OHLC row as bullish/bearish/neutral, or None when invalid."""
    count = min(len(opens), len(highs), len(lows), len(closes))
    kinds: List[Optional[str]] = []
    for i in range(count):
        o = opens[i]
        h = highs[i]
        l = lows[i]
        c = closes[i]
        if not _is_valid_ohlc(o, h, l, c):
            kinds.append(None)
            continue
        if c > o:
            kinds.append(CANDLE_BULLISH)
        elif c < o:
            kinds.append(CANDLE_BEARISH)
        else:
            kinds.append(CANDLE_NEUTRAL)
    return kinds


def build_candle_bodies(
    timestamps: List[float],
    opens: List[float],
    closes: List[float],
    kinds: List[Optional[str]],
    min_body_height: float = 0.0,
) -> Dict[str, Tuple[List[float], List[float], List[float]]]:
    """Returns per-direction (xs, center_ys, heights) arrays for BarGraphItem bodies.

    ``y`` is the body center because pyqtgraph centers bars on ``y`` when only
    ``y``/``height`` are supplied. Bodies shorter than ``min_body_height``
    (doji / near-zero moves) are widened to that floor so they stay visible.
    """
    result: Dict[str, Tuple[List[float], List[float], List[float]]] = {
        kind: ([], [], []) for kind in _CANDLE_KINDS
    }
    count = min(len(timestamps), len(opens), len(closes), len(kinds))
    for i in range(count):
        kind = kinds[i]
        if kind is None:
            continue
        o = float(opens[i])
        c = float(closes[i])
        height = abs(c - o)
        if height < min_body_height:
            height = min_body_height
        xs, ys, hs = result[kind]
        xs.append(float(timestamps[i]))
        ys.append((o + c) / 2.0)
        hs.append(height)
    return result


def build_wick_series(
    timestamps: List[float],
    highs: List[float],
    lows: List[float],
    kinds: List[Optional[str]],
) -> Dict[str, Tuple[List[float], List[float]]]:
    """Returns per-direction NaN-separated (xs, ys) arrays connecting each high to its low."""
    result: Dict[str, Tuple[List[float], List[float]]] = {
        kind: ([], []) for kind in _CANDLE_KINDS
    }
    count = min(len(timestamps), len(highs), len(lows), len(kinds))
    for i in range(count):
        kind = kinds[i]
        if kind is None:
            continue
        xs, ys = result[kind]
        if xs and not math.isnan(xs[-1]):
            xs.append(float("nan"))
            ys.append(float("nan"))
        x = float(timestamps[i])
        xs.extend([x, x])
        ys.extend([float(highs[i]), float(lows[i])])
    return result


def candle_price_bounds(
    highs: List[float], lows: List[float], kinds: List[Optional[str]]
) -> Optional[Tuple[float, float]]:
    """Returns (max_high, min_low) over valid candles, or None when none are valid."""
    max_high: Optional[float] = None
    min_low: Optional[float] = None
    count = min(len(highs), len(lows), len(kinds))
    for i in range(count):
        if kinds[i] is None:
            continue
        h = float(highs[i])
        l = float(lows[i])
        max_high = h if max_high is None else max(max_high, h)
        min_low = l if min_low is None else min(min_low, l)
    if max_high is None or min_low is None:
        return None
    return max_high, min_low


def split_baseline_series(
    timestamps: List[float],
    prices: List[float],
    baseline: float,
) -> Tuple[List[float], List[float], List[float], List[float]]:
    """Splits a price series into above/below segments relative to ``baseline``.

    Crossing points are linearly interpolated so each segment ends exactly on
    the baseline, and disjoint segments of the same side are separated by NaN
    so fills never bridge across a crossing. Returns
    ``(above_x, above_y, below_x, below_y)``.
    """
    above_x: List[float] = []
    above_y: List[float] = []
    below_x: List[float] = []
    below_y: List[float] = []

    if not timestamps or not prices:
        return above_x, above_y, below_x, below_y
    try:
        baseline = float(baseline)
    except (TypeError, ValueError):
        return above_x, above_y, below_x, below_y
    if not math.isfinite(baseline):
        return above_x, above_y, below_x, below_y

    prev_x: Optional[float] = None
    prev_y: Optional[float] = None
    prev_side: Optional[int] = None

    for raw_x, raw_y in zip(timestamps, prices):
        try:
            x = float(raw_x)
            y = float(raw_y)
        except (TypeError, ValueError):
            prev_side = None
            continue
        if not math.isfinite(x) or not math.isfinite(y):
            prev_side = None
            continue

        side = 1 if y >= baseline else -1

        if prev_side is None:
            target_x, target_y = (above_x, above_y) if side == 1 else (below_x, below_y)
            if target_x and not math.isnan(target_x[-1]):
                target_x.append(float("nan"))
                target_y.append(float("nan"))
            target_x.append(x)
            target_y.append(y)
        elif side != prev_side:
            dy = y - prev_y
            xc = x if dy == 0 else prev_x + (baseline - prev_y) / dy * (x - prev_x)
            prev_tx, prev_ty = (above_x, above_y) if prev_side == 1 else (below_x, below_y)
            prev_tx.append(float(xc))
            prev_ty.append(float(baseline))
            new_tx, new_ty = (above_x, above_y) if side == 1 else (below_x, below_y)
            if new_tx and not math.isnan(new_tx[-1]):
                new_tx.append(float("nan"))
                new_ty.append(float("nan"))
            new_tx.append(float(xc))
            new_ty.append(float(baseline))
            new_tx.append(x)
            new_ty.append(y)
        else:
            target_x, target_y = (above_x, above_y) if side == 1 else (below_x, below_y)
            target_x.append(x)
            target_y.append(y)

        prev_x = x
        prev_y = y
        prev_side = side

    return above_x, above_y, below_x, below_y


class TimeAxisItem(pg.AxisItem):
    """Custom PyQtGraph AxisItem to format unix timestamps as human-readable dates."""

    def tickStrings(self, values, scale, spacing):
        strings = []
        for v in values:
            try:
                dt = datetime.fromtimestamp(v)
                if spacing < 86400:
                    strings.append(dt.strftime("%b %d %H:%M"))
                elif spacing < 86400 * 30:
                    strings.append(dt.strftime("%b %d"))
                else:
                    strings.append(dt.strftime("%b %Y"))
            except Exception:
                strings.append("")
        return strings


class PriceAxisItem(pg.AxisItem):
    """Custom Y-axis item to format price ticks with the active currency symbol."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._symbol = "$"

    def set_symbol(self, symbol: str) -> None:
        self._symbol = symbol

    def tickStrings(self, values, scale, spacing):
        strings = []
        for v in values:
            if v >= 1000:
                strings.append(f"{self._symbol}{v:,.0f}")
            else:
                strings.append(f"{self._symbol}{v:,.2f}")
        return strings


class ForecastAnnotationItem(pg.TextItem):
    """Draggable forecast info box with an anchor-selection context menu.

    pyqtgraph's TextItem has no drag support, so this subclass enables Qt's
    built-in item movement and reports user drags and anchor choices back to
    the chart through callbacks.
    """

    def __init__(self, *args, on_user_moved=None, on_anchor_chosen=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._on_user_moved = on_user_moved
        self._on_anchor_chosen = on_anchor_chosen
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self._on_user_moved is not None:
            self._on_user_moved()
        return super().itemChange(change, value)

    def contextMenuEvent(self, ev):
        if self._on_anchor_chosen is None:
            ev.ignore()
            return
        menu = QMenu()
        for key, label in FORECAST_ANNOTATION_ANCHOR_LABELS.items():
            action = menu.addAction(label)
            action.setData(key)
        chosen = menu.exec(ev.screenPos().toPoint())
        if chosen is not None:
            ev.accept()
            self._on_anchor_chosen(str(chosen.data()))
        else:
            ev.ignore()


class StockChartWidget(QWidget):
    hover_changed = Signal(str, float)  # Emits (date_string, hovered_price)
    hover_left = Signal()               # Emits when mouse exits chart bounds
    forecast_annotation_anchor_changed = Signal(str)  # Emits the chosen info-box anchor

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # Custom Axes
        self.x_axis = TimeAxisItem(orientation="bottom")
        self.y_axis = PriceAxisItem(orientation="right")

        self.plot_widget = pg.PlotWidget(axisItems={"bottom": self.x_axis, "right": self.y_axis})
        self.layout.addWidget(self.plot_widget, 3)

        self.plot_item = self.plot_widget.getPlotItem()
        self.plot_item.showAxis("right", True)
        self.plot_item.hideAxis("left")
        self.plot_item.showGrid(x=True, y=True, alpha=0.10)
        self.plot_item.setMenuEnabled(True)

        # Compact volume panel below the price chart; its time axis is X-linked
        # to the price ViewBox so zoom, pan, range and ticker changes always
        # keep both charts on exactly the same time scale.
        self.volume_chart = VolumeChartWidget(self)
        self.volume_chart.plot_item.vb.setXLink(self.plot_item.vb)
        self.layout.addWidget(self.volume_chart, 1)

        # Raw Price Plot Curve Pen (1.2px width)
        self.pen = QPen(QColor("#00e676"))
        self.pen.setWidthF(1.2)
        self.pen.setCosmetic(True)
        self.curve = self.plot_item.plot(pen=self.pen)

        # Candlestick bodies (bucketed by direction) and wicks; hidden outside Candle mode
        self._candle_bull_bars = pg.BarGraphItem(x=[], height=[], width=1.0, pen=None, brush=BUY_COLOR)
        self._candle_bear_bars = pg.BarGraphItem(x=[], height=[], width=1.0, pen=None, brush=SELL_COLOR)
        self._candle_neutral_bars = pg.BarGraphItem(x=[], height=[], width=1.0, pen=None, brush=NEUTRAL_COLOR)
        for bars in (self._candle_bull_bars, self._candle_bear_bars, self._candle_neutral_bars):
            self.plot_item.addItem(bars, ignoreBounds=True)
            bars.setVisible(False)

        self._wick_pen_bull = QPen(QColor(BUY_COLOR))
        self._wick_pen_bull.setWidthF(1.0)
        self._wick_pen_bull.setCosmetic(True)
        self._wick_pen_bear = QPen(QColor(SELL_COLOR))
        self._wick_pen_bear.setWidthF(1.0)
        self._wick_pen_bear.setCosmetic(True)
        self._wick_pen_neutral = QPen(QColor(NEUTRAL_COLOR))
        self._wick_pen_neutral.setWidthF(1.0)
        self._wick_pen_neutral.setCosmetic(True)

        self._wick_bull_curve = self.plot_item.plot(pen=self._wick_pen_bull)
        self._wick_bear_curve = self.plot_item.plot(pen=self._wick_pen_bear)
        self._wick_neutral_curve = self.plot_item.plot(pen=self._wick_pen_neutral)
        for wick_curve in (self._wick_bull_curve, self._wick_bear_curve, self._wick_neutral_curve):
            wick_curve.setVisible(False)

        # Baseline mode: price split into above/below segments with fills meeting the baseline
        self._baseline_above_pen = QPen(QColor(BUY_COLOR))
        self._baseline_above_pen.setWidthF(1.2)
        self._baseline_above_pen.setCosmetic(True)
        self._baseline_below_pen = QPen(QColor(SELL_COLOR))
        self._baseline_below_pen.setWidthF(1.2)
        self._baseline_below_pen.setCosmetic(True)
        self._baseline_above_curve = self.plot_item.plot(pen=self._baseline_above_pen)
        self._baseline_below_curve = self.plot_item.plot(pen=self._baseline_below_pen)
        self._baseline_above_curve.setVisible(False)
        self._baseline_below_curve.setVisible(False)

        baseline_pen = QPen(QColor("#8b90a0"))
        baseline_pen.setWidthF(1.0)
        baseline_pen.setStyle(Qt.DashLine)
        baseline_pen.setCosmetic(True)
        self._baseline_line = pg.InfiniteLine(angle=0, movable=False, pen=baseline_pen)
        self.plot_item.addItem(self._baseline_line, ignoreBounds=True)
        self._baseline_line.setVisible(False)

        # Noise-Reduced Overlay Curve Pen (1.8px Amber Gold stroke)
        self.overlay_pen = QPen(QColor("#ffab00"))
        self.overlay_pen.setWidthF(1.8)
        self.overlay_pen.setCosmetic(True)
        self.overlay_curve = self.plot_item.plot(pen=self.overlay_pen)
        self.overlay_curve.setVisible(False)
        self._overlay_label = "Filtered"

        # Forecast filter extension: dashed continuation of the active filter
        # into the forecast region, drawn in the same colour as overlay_curve.
        self._forecast_filter_pen = QPen(QColor("#ffab00"))
        self._forecast_filter_pen.setWidthF(1.8)
        self._forecast_filter_pen.setStyle(Qt.DashLine)
        self._forecast_filter_pen.setCosmetic(True)
        self._forecast_filter_curve = self.plot_item.plot(pen=self._forecast_filter_pen)
        self._forecast_filter_curve.setVisible(False)

        # ATR volatility band overlay (upper/lower curves + subtle fill)
        self._atr_upper_pen = QPen(QColor(ATR2_COLOR))
        self._atr_upper_pen.setWidthF(1.0)
        self._atr_upper_pen.setCosmetic(True)
        self._atr_lower_pen = QPen(QColor(ATR2_COLOR))
        self._atr_lower_pen.setWidthF(1.0)
        self._atr_lower_pen.setCosmetic(True)
        self._atr_upper_curve = self.plot_item.plot(pen=self._atr_upper_pen)
        self._atr_lower_curve = self.plot_item.plot(pen=self._atr_lower_pen)
        self._atr_fill = pg.FillBetweenItem(
            self._atr_upper_curve, self._atr_lower_curve, brush=pg.mkBrush(QColor(0, 0, 0, 0))
        )
        self.plot_item.addItem(self._atr_fill, ignoreBounds=True)
        self._atr_upper_curve.setVisible(False)
        self._atr_lower_curve.setVisible(False)
        self._atr_fill.setVisible(False)
        self._atr_upper: List[Optional[float]] = []
        self._atr_lower: List[Optional[float]] = []
        self._atr_label = ""

        # Swing levels: latest confirmed high/low as horizontal price lines
        self._swing_high_line = pg.InfiniteLine(angle=0, movable=False)
        self._swing_low_line = pg.InfiniteLine(angle=0, movable=False)
        self.plot_item.addItem(self._swing_high_line, ignoreBounds=True)
        self.plot_item.addItem(self._swing_low_line, ignoreBounds=True)
        self._swing_high_line.setVisible(False)
        self._swing_low_line.setVisible(False)

        self._swing_high_text = pg.TextItem(
            text="", anchor=(1.0, 1.35), color="#ffffff", fill=pg.mkBrush("#1a1c24f0")
        )
        self._swing_low_text = pg.TextItem(
            text="", anchor=(1.0, -0.35), color="#ffffff", fill=pg.mkBrush("#1a1c24f0")
        )
        self.plot_item.addItem(self._swing_high_text, ignoreBounds=True)
        self.plot_item.addItem(self._swing_low_text, ignoreBounds=True)
        self._swing_high_text.setVisible(False)
        self._swing_low_text.setVisible(False)
        self._swing_level_high = None
        self._swing_level_low = None
        self._swing_reference_close: Optional[float] = None

        # Market structure labels (HH/HL/LH/LL/M) near confirmed pivots
        self._structure_items: List[pg.TextItem] = []
        self._structure_visible = True

        # Earnings event markers along the time axis
        self._earnings_items: List[Tuple[pg.TextItem, float]] = []
        self._earnings_events: List[EarningsEvent] = []
        self._earnings_symbol = ""
        self._earnings_company: Optional[str] = None
        self._earnings_tooltip = pg.TextItem(
            text="", anchor=(0.5, 1.2), color="#ffffff", fill=pg.mkBrush("#1a1c24f0")
        )
        self.plot_item.addItem(self._earnings_tooltip, ignoreBounds=True)
        self._earnings_tooltip.setVisible(False)

        # Forecast projection layer: dashed central path, translucent estimated
        # range fill, target marker and a top-right annotation. Renders in the
        # future time region beyond the last historical bar.
        self._forecast_pen = QPen(QColor(FORECAST_COLOR))
        self._forecast_pen.setWidthF(1.6)
        self._forecast_pen.setStyle(Qt.DashLine)
        self._forecast_pen.setCosmetic(True)
        self._forecast_band_pen = QPen(QColor(FORECAST_COLOR))
        self._forecast_band_pen.setWidthF(0.8)
        self._forecast_band_pen.setCosmetic(True)
        self._forecast_upper_curve = self.plot_item.plot(pen=self._forecast_band_pen)
        self._forecast_lower_curve = self.plot_item.plot(pen=self._forecast_band_pen)
        self._forecast_fill = pg.FillBetweenItem(
            self._forecast_upper_curve,
            self._forecast_lower_curve,
            brush=pg.mkBrush(QColor(0, 0, 0, 0)),
        )
        self.plot_item.addItem(self._forecast_fill, ignoreBounds=True)
        self._forecast_central_curve = self.plot_item.plot(pen=self._forecast_pen)
        self._forecast_target = pg.ScatterPlotItem(
            size=9,
            brush=pg.mkBrush(QColor(FORECAST_COLOR)),
            pen=pg.mkPen(QColor("#121318"), width=1.0),
        )
        self.plot_item.addItem(self._forecast_target, ignoreBounds=True)
        self._forecast_reference = pg.ScatterPlotItem(
            size=6,
            brush=pg.mkBrush(QColor(FORECAST_COLOR)),
            pen=pg.mkPen(QColor("#121318"), width=1.0),
        )
        self.plot_item.addItem(self._forecast_reference, ignoreBounds=True)
        self._forecast_annotation = ForecastAnnotationItem(
            text="",
            anchor=(1.0, 0.0),
            color="#ffffff",
            fill=pg.mkBrush("#1a1c24f0"),
            on_user_moved=self._on_forecast_annotation_user_moved,
            on_anchor_chosen=self._on_forecast_annotation_anchor_chosen,
        )
        self.plot_item.addItem(self._forecast_annotation, ignoreBounds=True)
        self._forecast_annotation.setZValue(100)
        self._forecast_upper_curve.setVisible(False)
        self._forecast_lower_curve.setVisible(False)
        self._forecast_fill.setVisible(False)
        self._forecast_central_curve.setVisible(False)
        self._forecast_target.setVisible(False)
        self._forecast_reference.setVisible(False)
        self._forecast_annotation.setVisible(False)
        self._forecast: Optional[Forecast] = None
        self._forecast_is_saved = False
        self._forecast_bounds: Optional[Tuple[float, float]] = None
        self._forecast_annotation_anchor = FORECAST_ANNOTATION_DEFAULT_ANCHOR
        self._forecast_annotation_user_moved = False
        self._forecast_annotation_setting_pos = False
        self._forecast_overlay_visible = True

        # Swing Overlay: zigzag line + pivot markers (Violet stroke)
        swing_color = QColor("#e040fb")
        self.swing_pen = QPen(swing_color)
        self.swing_pen.setWidthF(1.6)
        self.swing_pen.setCosmetic(True)
        self.swing_line = self.plot_item.plot(pen=self.swing_pen)
        self.swing_line.setVisible(False)

        self.swing_scatter = pg.ScatterPlotItem(
            size=7,
            brush=pg.mkBrush(swing_color),
            pen=pg.mkPen(QColor("#121318"), width=1.0),
        )
        self.plot_item.addItem(self.swing_scatter, ignoreBounds=True)
        self.swing_scatter.setVisible(False)

        self.swing_text = pg.TextItem(
            text="", anchor=(0, 0), color="#e040fb", fill=pg.mkBrush("#1a1c24f0")
        )
        self.plot_item.addItem(self.swing_text, ignoreBounds=True)
        self.swing_text.setVisible(False)

        # Yellow highlight bands marking each detected swing leg
        self._swing_bands: List[QGraphicsRectItem] = []

        # Sleek Crosshair lines (0.8px width)
        crosshair_pen = QPen(QColor("#454b61"))
        crosshair_pen.setWidthF(0.8)
        crosshair_pen.setStyle(Qt.DashLine)

        self.v_line = pg.InfiniteLine(angle=90, movable=False, pen=crosshair_pen)
        self.h_line = pg.InfiniteLine(angle=0, movable=False, pen=crosshair_pen)
        self.plot_item.addItem(self.v_line, ignoreBounds=True)
        self.plot_item.addItem(self.h_line, ignoreBounds=True)
        self.v_line.setVisible(False)
        self.h_line.setVisible(False)

        # Tooltip / Crosshair Label Text
        self.tooltip_text = pg.TextItem(text="", anchor=(0.5, 1.2), color="#ffffff", fill=pg.mkBrush("#1a1c24f0"))
        self.plot_item.addItem(self.tooltip_text, ignoreBounds=True)
        self.tooltip_text.setVisible(False)

        # Empty State Label
        self.empty_label = QLabel("No local data available.\nPress 'Update all tickers' to download historical prices.", self)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("font-size: 15px; color: #8b90a0; background-color: #121318;")
        self.layout.addWidget(self.empty_label)
        self.empty_label.hide()

        # Cached raw data for mouse hover lookups
        self._x_data: List[float] = []
        self._y_data: List[float] = []
        self._date_labels: List[str] = []

        # Cached overlay data
        self._overlay_x: List[float] = []
        self._overlay_y: List[float] = []
        self._forecast_filter_y: List[float] = []

        # Chart-type state and per-mode cached data
        self._chart_type: ChartType = ChartType.LINE
        self._candle_opens: List[Optional[float]] = []
        self._candle_highs: List[Optional[float]] = []
        self._candle_lows: List[Optional[float]] = []
        self._candle_price_bounds: Optional[Tuple[float, float]] = None
        self._baseline: Optional[float] = None

        # Currency symbol used by the Y-axis and hover tooltip (set per ticker)
        self._currency_symbol = "$"

        # Fit-view bounds (x_lo, x_hi, y_lo, y_hi) captured after each auto-fit
        self._view_bounds: Optional[Tuple[float, float, float, float]] = None

        # Connect mouse move event for crosshair
        self.plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)

        # Keep the swing parameter text anchored to the top-left of the visible view
        self.plot_item.vb.sigRangeChanged.connect(self._position_swing_text)
        # Swing level annotations stay pinned to the right edge; earnings markers
        # stay pinned just above the bottom of the price pane.
        self.plot_item.vb.sigRangeChanged.connect(self._position_level_texts)
        self.plot_item.vb.sigRangeChanged.connect(self._position_earnings_markers)
        self.plot_item.vb.sigRangeChanged.connect(self._position_forecast_annotation)

    def set_currency(self, currency_code: Optional[str]) -> None:
        """Sets the currency symbol used by the Y-axis, tooltip and volume panel."""
        self._currency_symbol = get_currency_symbol(currency_code)
        self.y_axis.set_symbol(self._currency_symbol)
        self.y_axis.picture = None
        self.y_axis.update()
        self.volume_chart.set_currency(currency_code)

    def set_data(
        self,
        timestamps: List[float],
        prices: List[float],
        date_labels: List[str],
        line_color: str = "#00e676",
        chart_type: ChartType = ChartType.LINE,
        ohlc: Optional[Tuple[List[float], List[float], List[float]]] = None,
    ) -> None:
        """Sets chart data and renders it with the requested chart type.

        ``ohlc`` is an optional ``(opens, highs, lows)`` tuple aligned
        bar-by-bar with ``timestamps``/``prices``; it is required for Candle
        mode and ignored by the other modes.
        """
        self._x_data = timestamps
        self._y_data = prices
        self._date_labels = date_labels
        self._chart_type = chart_type

        if not timestamps or not prices:
            self._view_bounds = None
            self._hide_candle_items()
            self._hide_baseline_items()
            self._clear_earnings_markers()
            self.show_empty_state(True)
            return

        self.show_empty_state(False)
        self._rebuild_earnings_markers()

        if chart_type == ChartType.CANDLE and self._render_candlestick(
            timestamps, prices, line_color, ohlc
        ):
            self._fit_view_to_data()
            return

        if chart_type == ChartType.BASELINE:
            self._render_baseline(timestamps, prices)
            self._fit_view_to_data()
            return

        self._render_line(timestamps, prices, line_color)
        self._fit_view_to_data()

    def _render_line(
        self,
        timestamps: List[float],
        prices: List[float],
        line_color: str,
    ) -> None:
        """Renders the default line chart with a soft fill down to the minimum price."""
        self._hide_candle_items()
        self._hide_baseline_items()

        pen_color = QColor(line_color)
        self.pen.setColor(pen_color)
        self.pen.setWidthF(1.2)
        self.curve.setPen(self.pen)

        fill_color = QColor(line_color)
        fill_color.setAlpha(20)
        min_y = min(prices)
        self.curve.setFillLevel(min_y)
        self.curve.setBrush(pg.mkBrush(fill_color))

        self.curve.setData(timestamps, prices)
        self.curve.setVisible(True)

    def _render_candlestick(
        self,
        timestamps: List[float],
        prices: List[float],
        line_color: str,
        ohlc: Optional[Tuple[List[float], List[float], List[float]]],
    ) -> bool:
        """Renders green/red candlesticks with wicks. Returns False to fall back to line mode."""
        self._hide_baseline_items()

        if not ohlc:
            logger.warning("Candle chart requested without OHLC data; falling back to line chart.")
            return False

        opens, highs, lows = ohlc
        kinds = classify_candles(opens, highs, lows, prices)
        if not any(kind is not None for kind in kinds):
            logger.warning("No valid OHLC candles for the current range; falling back to line chart.")
            self._hide_candle_items()
            return False

        count = min(len(timestamps), len(opens), len(highs), len(lows), len(prices))
        self._candle_opens: List[Optional[float]] = []
        self._candle_highs: List[Optional[float]] = []
        self._candle_lows: List[Optional[float]] = []
        for i in range(count):
            if kinds[i] is None:
                self._candle_opens.append(None)
                self._candle_highs.append(None)
                self._candle_lows.append(None)
            else:
                self._candle_opens.append(float(opens[i]))
                self._candle_highs.append(float(highs[i]))
                self._candle_lows.append(float(lows[i]))

        self._candle_price_bounds = candle_price_bounds(highs, lows, kinds)

        price_min = min(prices)
        price_max = max(prices)
        if self._candle_price_bounds:
            price_max = max(price_max, self._candle_price_bounds[0])
            price_min = min(price_min, self._candle_price_bounds[1])
        body_floor = max((price_max - price_min) * _MIN_BODY_HEIGHT_RATIO, _ABS_MIN_BODY_HEIGHT)

        bodies = build_candle_bodies(timestamps, opens, prices, kinds, min_body_height=body_floor)
        wicks = build_wick_series(timestamps, highs, lows, kinds)
        width = compute_bar_width(timestamps)

        bar_items = {
            CANDLE_BULLISH: self._candle_bull_bars,
            CANDLE_BEARISH: self._candle_bear_bars,
            CANDLE_NEUTRAL: self._candle_neutral_bars,
        }
        wick_items = {
            CANDLE_BULLISH: self._wick_bull_curve,
            CANDLE_BEARISH: self._wick_bear_curve,
            CANDLE_NEUTRAL: self._wick_neutral_curve,
        }
        for kind in _CANDLE_KINDS:
            xs, ys, hs = bodies[kind]
            bar_items[kind].setOpts(x=xs, y=ys, height=hs, width=width)
            bar_items[kind].setVisible(True)
            wick_xs, wick_ys = wicks[kind]
            wick_items[kind].setData(wick_xs, wick_ys)
            wick_items[kind].setVisible(True)

        self.curve.setVisible(False)
        return True

    def _render_baseline(self, timestamps: List[float], prices: List[float]) -> None:
        """Renders the close series relative to its first valid value with green/red fills."""
        self._hide_candle_items()

        baseline = next(
            (p for p in prices if p is not None and math.isfinite(p) and p > 0),
            None,
        )
        if baseline is None:
            logger.warning("Baseline chart requested without a valid baseline; hiding baseline items.")
            self._hide_baseline_items()
            return

        self._baseline = float(baseline)
        above_x, above_y, below_x, below_y = split_baseline_series(
            timestamps, prices, self._baseline
        )

        above_fill = QColor(BUY_COLOR)
        above_fill.setAlpha(24)
        below_fill = QColor(SELL_COLOR)
        below_fill.setAlpha(24)

        self._baseline_above_curve.setData(above_x, above_y)
        self._baseline_above_curve.setFillLevel(self._baseline)
        self._baseline_above_curve.setBrush(pg.mkBrush(above_fill))
        self._baseline_above_curve.setVisible(True)

        self._baseline_below_curve.setData(below_x, below_y)
        self._baseline_below_curve.setFillLevel(self._baseline)
        self._baseline_below_curve.setBrush(pg.mkBrush(below_fill))
        self._baseline_below_curve.setVisible(True)

        self._baseline_line.setPos(self._baseline)
        self._baseline_line.setVisible(True)

        self.curve.setVisible(False)

    def _hide_candle_items(self) -> None:
        for bars in (self._candle_bull_bars, self._candle_bear_bars, self._candle_neutral_bars):
            bars.setOpts(x=[], y=[], height=[], width=1.0)
            bars.setVisible(False)
        for wick_curve in (self._wick_bull_curve, self._wick_bear_curve, self._wick_neutral_curve):
            wick_curve.setData([], [])
            wick_curve.setVisible(False)
        self._candle_opens = []
        self._candle_highs = []
        self._candle_lows = []
        self._candle_price_bounds = None

    def _hide_baseline_items(self) -> None:
        self._baseline_above_curve.setData([], [])
        self._baseline_above_curve.setVisible(False)
        self._baseline_below_curve.setData([], [])
        self._baseline_below_curve.setVisible(False)
        self._baseline_line.setVisible(False)
        self._baseline = None

    def set_volume_data(
        self,
        timestamps: List[float],
        volumes: List[float],
        opens: List[float],
        closes: List[float],
        date_labels: List[str],
    ) -> None:
        """Renders the volume sub-chart aligned with the price chart time axis."""
        if self._x_data and len(timestamps) != len(self._x_data):
            logger.warning(
                "Volume timestamps (%d) do not match price series length (%d)",
                len(timestamps),
                len(self._x_data),
            )
        x_data = self._x_data if self._x_data else timestamps
        self.volume_chart.set_data(x_data, volumes, opens, closes, date_labels)

    def _fit_view_to_data(self) -> None:
        """Auto-fits the view to data bounds and locks zoom/pan limits to that fit view."""
        if not self._x_data or not self._y_data:
            return

        y_min, y_max = min(self._y_data), max(self._y_data)
        if self._candle_price_bounds:
            y_min = min(y_min, self._candle_price_bounds[1])
            y_max = max(y_max, self._candle_price_bounds[0])
        if self._overlay_y:
            y_min = min(y_min, min(self._overlay_y))
            y_max = max(y_max, max(self._overlay_y))
        if self._forecast_filter_y and self._forecast_overlay_visible:
            y_min = min(y_min, min(self._forecast_filter_y))
            y_max = max(y_max, max(self._forecast_filter_y))
        atr_upper_valid = [v for v in self._atr_upper if v is not None and math.isfinite(v)]
        atr_lower_valid = [v for v in self._atr_lower if v is not None and math.isfinite(v)]
        if atr_upper_valid:
            y_max = max(y_max, max(atr_upper_valid))
        if atr_lower_valid:
            y_min = min(y_min, min(atr_lower_valid))
        if self._forecast_bounds and self._forecast_overlay_visible:
            y_max = max(y_max, self._forecast_bounds[1])
            y_min = min(y_min, self._forecast_bounds[0])

        padding = (y_max - y_min) * 0.08 if y_max > y_min else y_max * 0.05

        vb = self.plot_item.vb
        vb.setLimits(xMin=None, xMax=None, yMin=None, yMax=None, maxXRange=None, maxYRange=None)
        self.plot_item.enableAutoRange(axis=pg.ViewBox.XYAxes, enable=True)
        self.plot_item.setYRange(y_min - padding, y_max + padding)
        vb.updateAutoRange()

        x_lo, x_hi = vb.viewRange()[0]
        y_lo, y_hi = vb.viewRange()[1]
        if x_hi <= x_lo or y_hi <= y_lo:
            return

        self._view_bounds = (x_lo, x_hi, y_lo, y_hi)
        vb.setLimits(
            xMin=x_lo,
            xMax=x_hi,
            maxXRange=x_hi - x_lo,
            yMin=y_lo,
            yMax=y_hi,
            maxYRange=y_hi - y_lo,
        )

    def set_overlay_data(
        self,
        timestamps: List[float],
        prices: List[float],
        color: str = "#ffab00",
        label: str = "Filtered",
    ) -> None:
        """Sets and displays a secondary overlay curve (noise-reduced or EMA)."""
        self._overlay_x = timestamps
        self._overlay_y = prices
        self._overlay_label = label

        if not timestamps or not prices:
            self.clear_overlay()
            self.clear_forecast_filter_curve()
            return

        pen_color = QColor(color)
        self.overlay_pen.setColor(pen_color)
        self.overlay_pen.setWidthF(1.8)
        self.overlay_curve.setPen(self.overlay_pen)
        self.overlay_curve.setData(timestamps, prices)
        self.overlay_curve.setVisible(True)
        self._fit_view_to_data()

    def clear_overlay(self) -> None:
        """Clears and hides the secondary overlay curve."""
        self._overlay_x = []
        self._overlay_y = []
        self._overlay_label = "Filtered"
        self.overlay_curve.setVisible(False)
        self.clear_forecast_filter_curve()
        self._fit_view_to_data()

    def set_forecast_filter_curve(
        self,
        timestamps: List[float],
        prices: List[float],
        color: str = "#ffab00",
    ) -> None:
        """Draws a dashed continuation of the active filter into the forecast region."""
        if not timestamps or not prices:
            self.clear_forecast_filter_curve()
            return
        self._forecast_filter_y = list(prices)
        self._forecast_filter_pen.setColor(QColor(color))
        self._forecast_filter_curve.setPen(self._forecast_filter_pen)
        self._forecast_filter_curve.setData(list(timestamps), list(prices))
        self._forecast_filter_curve.setVisible(self._forecast_overlay_visible)
        self._fit_view_to_data()

    def clear_forecast_filter_curve(self) -> None:
        """Clears and hides the forecast filter extension curve."""
        self._forecast_filter_y = []
        self._forecast_filter_curve.setData([], [])
        self._forecast_filter_curve.setVisible(False)

    def set_atr_overlay(
        self,
        timestamps: List[float],
        upper: List[Optional[float]],
        lower: List[Optional[float]],
        label: str,
        color: str,
    ) -> None:
        """Displays Close ± N×ATR14 volatility bands around the price series.

        ``upper``/``lower`` are aligned bar-by-bar with ``timestamps``; None
        entries render as gaps. The subtle fill between the bands marks the
        volatility range without obscuring the price series or other overlays.
        """
        if not timestamps or not upper or not lower:
            self.clear_atr_overlay()
            return

        count = min(len(timestamps), len(upper), len(lower))
        xs = [float(t) for t in timestamps[:count]]

        def _series(values: List[Optional[float]]) -> List[float]:
            out: List[float] = []
            for v in values[:count]:
                if v is None:
                    out.append(float("nan"))
                else:
                    try:
                        out.append(float(v))
                    except (TypeError, ValueError):
                        out.append(float("nan"))
            return out

        self._atr_upper = list(upper[:count])
        self._atr_lower = list(lower[:count])
        self._atr_label = label

        pen = QColor(color)
        self._atr_upper_pen.setColor(pen)
        self._atr_lower_pen.setColor(pen)
        self._atr_upper_curve.setPen(self._atr_upper_pen)
        self._atr_lower_curve.setPen(self._atr_lower_pen)
        self._atr_upper_curve.setData(xs, _series(upper))
        self._atr_lower_curve.setData(xs, _series(lower))
        self._atr_upper_curve.setVisible(True)
        self._atr_lower_curve.setVisible(True)

        fill_color = QColor(color)
        fill_color.setAlpha(22)
        self._atr_fill.setBrush(pg.mkBrush(fill_color))
        self._atr_fill.setVisible(True)
        self._fit_view_to_data()

    def clear_atr_overlay(self) -> None:
        """Clears and hides the ATR volatility band overlay."""
        self._atr_upper = []
        self._atr_lower = []
        self._atr_label = ""
        self._atr_upper_curve.setData([], [])
        self._atr_lower_curve.setData([], [])
        self._atr_upper_curve.setVisible(False)
        self._atr_lower_curve.setVisible(False)
        self._atr_fill.setBrush(pg.mkBrush(QColor(0, 0, 0, 0)))
        self._atr_fill.setVisible(False)
        self._fit_view_to_data()

    def set_structure_labels(
        self, placements: List[Tuple[float, float, str, str]]
    ) -> None:
        """Renders market-structure labels at precomputed (x, y, text, color) positions."""
        self.clear_structure_labels()
        for x, y, text, color in placements:
            item = pg.TextItem(
                text=text, anchor=(0.5, 0.5), color=color, fill=pg.mkBrush("#1a1c24f0")
            )
            item.setPos(float(x), float(y))
            item.setVisible(self._structure_visible)
            self.plot_item.addItem(item, ignoreBounds=True)
            self._structure_items.append(item)

    def set_structure_labels_visible(self, visible: bool) -> None:
        """Shows/hides structure labels without recomputing the swing structure."""
        self._structure_visible = bool(visible)
        for item in self._structure_items:
            item.setVisible(self._structure_visible)

    def clear_structure_labels(self) -> None:
        """Removes all market-structure label items from the plot."""
        for item in self._structure_items:
            try:
                self.plot_item.removeItem(item)
            except Exception:
                pass
        self._structure_items = []

    def set_earnings_events(
        self,
        events: List[EarningsEvent],
        symbol: str,
        company_name: Optional[str] = None,
    ) -> None:
        """Stores earnings events and renders markers for those in the visible range."""
        self._earnings_events = list(events) if events else []
        self._earnings_symbol = symbol
        self._earnings_company = company_name
        self._rebuild_earnings_markers()

    def clear_earnings_events(self) -> None:
        """Clears stored earnings events and removes their markers."""
        self._earnings_events = []
        self._earnings_symbol = ""
        self._earnings_company = None
        self._clear_earnings_markers()

    def _clear_earnings_markers(self) -> None:
        for item, _ in self._earnings_items:
            try:
                self.plot_item.removeItem(item)
            except Exception:
                pass
        self._earnings_items = []
        self._earnings_tooltip.setVisible(False)

    def _rebuild_earnings_markers(self) -> None:
        self._clear_earnings_markers()
        if not self._earnings_events or not self._x_data:
            return

        x_lo = min(self._x_data)
        x_hi = max(self._x_data)
        seen_epochs = set()
        for event in self._earnings_events:
            epoch = event.epoch
            if not math.isfinite(epoch) or epoch < x_lo or epoch > x_hi:
                continue
            if epoch in seen_epochs:
                continue
            seen_epochs.add(epoch)
            color = EARNINGS_ESTIMATED_COLOR if event.is_estimated else EARNINGS_CONFIRMED_COLOR
            item = pg.TextItem(text="E", anchor=(0.5, 0.5), color=color, fill=pg.mkBrush("#1a1c24f0"))
            self.plot_item.addItem(item, ignoreBounds=True)
            self._earnings_items.append((item, epoch))
        self._position_earnings_markers()

    def _position_earnings_markers(self, *args) -> None:
        if not self._earnings_items:
            return
        x_lo, x_hi = self.plot_item.vb.viewRange()[0]
        y_lo, y_hi = self.plot_item.vb.viewRange()[1]
        if x_hi <= x_lo or y_hi <= y_lo:
            return
        marker_y = y_lo + (y_hi - y_lo) * 0.05
        for item, epoch in self._earnings_items:
            item.setPos(epoch, marker_y)

    def set_swing_levels(
        self,
        high_level,
        low_level,
        reference_close: Optional[float],
    ) -> None:
        """Draws horizontal lines for the latest confirmed swing high/low.

        Line color reflects the level's position relative to ``reference_close``
        (green above, red below, neutral within tolerance — provided by the
        level's own ``color``); the line style is solid when the level has not
        been crossed since confirmation and dashed when it has. Levels use real
        price coordinates, so they render identically in Line, Candle and
        Baseline modes.
        """
        self._swing_level_high = high_level
        self._swing_level_low = low_level
        self._swing_reference_close = reference_close

        for level, line, text_item in (
            (high_level, self._swing_high_line, self._swing_high_text),
            (low_level, self._swing_low_line, self._swing_low_text),
        ):
            if level is None:
                line.setVisible(False)
                text_item.setVisible(False)
                continue
            pen = QPen(QColor(level.color))
            pen.setWidthF(1.2)
            pen.setStyle(Qt.DashLine if level.crossed else Qt.SolidLine)
            pen.setCosmetic(True)
            line.setPen(pen)
            line.setPos(level.price)
            line.setToolTip(level.annotation)
            line.setVisible(True)
            text_item.setText(level.annotation)
            text_item.setVisible(True)

        self._position_level_texts()

    def clear_swing_levels(self) -> None:
        """Hides the swing level lines and annotations."""
        self._swing_level_high = None
        self._swing_level_low = None
        self._swing_reference_close = None
        self._swing_high_line.setVisible(False)
        self._swing_low_line.setVisible(False)
        self._swing_high_text.setVisible(False)
        self._swing_low_text.setVisible(False)

    def _position_level_texts(self, *args) -> None:
        x_lo, x_hi = self.plot_item.vb.viewRange()[0]
        if x_hi <= x_lo:
            return
        right_x = x_hi - (x_hi - x_lo) * 0.015
        if self._swing_level_high is not None and self._swing_high_line.isVisible():
            self._swing_high_text.setPos(right_x, self._swing_level_high.price)
        if self._swing_level_low is not None and self._swing_low_line.isVisible():
            self._swing_low_text.setPos(right_x, self._swing_level_low.price)

    def set_forecast_overlay(self, forecast: Forecast, is_saved: bool = False) -> None:
        """Renders a forecast projection beyond the last historical bar.

        The historical series is untouched: the forecast is a separate layer
        with a dashed central path (an explicitly defined geometric projection
        from the model, not invented intermediate prices), a translucent
        estimated-range fill that widens with the square root of the horizon,
        and target/reference markers. Works in Line, Candle and Baseline modes
        because it uses real price coordinates.
        """
        self._forecast = forecast
        self._forecast_is_saved = bool(is_saved)

        xs = [float(x) for x in forecast.path_epochs]
        central = [float(y) for y in forecast.path_central]
        lower = [float(y) for y in forecast.path_lower]
        upper = [float(y) for y in forecast.path_upper]
        count = min(len(xs), len(central), len(lower), len(upper))
        if count < 2:
            self.clear_forecast_overlay()
            return
        xs = xs[:count]
        central = central[:count]
        lower = lower[:count]
        upper = upper[:count]

        self._forecast_central_curve.setData(xs, central)
        self._forecast_upper_curve.setData(xs, upper)
        self._forecast_lower_curve.setData(xs, lower)
        fill_color = QColor(FORECAST_COLOR)
        fill_color.setAlpha(28)
        self._forecast_fill.setBrush(pg.mkBrush(fill_color))
        self._forecast_target.setData([xs[-1]], [central[-1]])
        self._forecast_reference.setData([xs[0]], [central[0]])
        self._forecast_central_curve.setVisible(self._forecast_overlay_visible)
        self._forecast_upper_curve.setVisible(self._forecast_overlay_visible)
        self._forecast_lower_curve.setVisible(self._forecast_overlay_visible)
        self._forecast_fill.setVisible(self._forecast_overlay_visible)
        self._forecast_target.setVisible(self._forecast_overlay_visible)
        self._forecast_reference.setVisible(self._forecast_overlay_visible)

        self._forecast_bounds = (min(lower), max(upper))
        annotation = format_forecast_annotation_html(
            forecast, self._currency_symbol_for_forecast(), saved=is_saved
        )
        self._forecast_annotation.setHtml(annotation)
        # Pin the layout width to the box width so block alignment (the
        # centered drag-handle line) is honored by the text document.
        self._forecast_annotation.setTextWidth(
            self._forecast_annotation.boundingRect().width()
        )
        self._forecast_annotation.setColor(QColor("#e1e3ea"))
        self._forecast_annotation_user_moved = False
        if self._forecast_annotation_anchor == "hidden" or not self._forecast_overlay_visible:
            self._forecast_annotation.setVisible(False)
        else:
            self._forecast_annotation.setVisible(True)
            self._position_forecast_annotation()
        self._fit_view_to_data()

    def set_forecast_overlay_visible(self, visible: bool) -> None:
        """Shows or hides the forecast layer without clearing its data."""
        self._forecast_overlay_visible = bool(visible)
        show = self._forecast is not None and self._forecast_overlay_visible
        self._forecast_central_curve.setVisible(show)
        self._forecast_upper_curve.setVisible(show)
        self._forecast_lower_curve.setVisible(show)
        self._forecast_fill.setVisible(show)
        self._forecast_target.setVisible(show)
        self._forecast_reference.setVisible(show)
        anchor_hidden = self._forecast_annotation_anchor == "hidden"
        self._forecast_annotation.setVisible(show and not anchor_hidden)
        has_filter = bool(self._forecast_filter_y)
        self._forecast_filter_curve.setVisible(show and has_filter)
        self._fit_view_to_data()

    def _currency_symbol_for_forecast(self) -> Optional[str]:
        return self._currency_symbol

    def clear_forecast_overlay(self) -> None:
        """Clears and hides the forecast projection layer."""
        self._forecast = None
        self._forecast_is_saved = False
        self._forecast_bounds = None
        self._forecast_central_curve.setData([], [])
        self._forecast_upper_curve.setData([], [])
        self._forecast_lower_curve.setData([], [])
        self._forecast_fill.setBrush(pg.mkBrush(QColor(0, 0, 0, 0)))
        self._forecast_target.setData([], [])
        self._forecast_reference.setData([], [])
        self._forecast_central_curve.setVisible(False)
        self._forecast_upper_curve.setVisible(False)
        self._forecast_lower_curve.setVisible(False)
        self._forecast_fill.setVisible(False)
        self._forecast_target.setVisible(False)
        self._forecast_reference.setVisible(False)
        self._forecast_annotation.setVisible(False)
        self.clear_forecast_filter_curve()
        self._fit_view_to_data()

    def _position_forecast_annotation(self, *args) -> None:
        if not self._forecast_annotation.isVisible():
            return
        if self._forecast_annotation_user_moved:
            if self._forecast_annotation_in_view():
                return
            self._forecast_annotation_user_moved = False
        x_lo, x_hi = self.plot_item.vb.viewRange()[0]
        y_lo, y_hi = self.plot_item.vb.viewRange()[1]
        if x_hi <= x_lo or y_hi <= y_lo:
            return
        anchor = self._forecast_annotation_anchor
        anchor_point = _FORECAST_ANCHOR_POINTS.get(
            anchor, _FORECAST_ANCHOR_POINTS["top_right"]
        )
        self._forecast_annotation.setAnchor(anchor_point)
        x_pad = (x_hi - x_lo) * 0.015
        y_pad = (y_hi - y_lo) * 0.03
        if anchor in ("top_right", "bottom_right"):
            x = x_hi - x_pad
        else:
            x = x_lo + x_pad
        if anchor in ("top_right", "top_left"):
            y = y_hi - y_pad
        else:
            y = y_lo + y_pad
        x, y = self._forecast_annotation_pos_near_path(
            x, y, anchor, x_lo, x_hi, y_lo, y_hi, x_pad, y_pad
        )
        self._forecast_annotation_setting_pos = True
        try:
            self._forecast_annotation.setPos(x, y)
        finally:
            self._forecast_annotation_setting_pos = False

    def _forecast_annotation_in_view(self) -> bool:
        x_lo, x_hi = self.plot_item.vb.viewRange()[0]
        y_lo, y_hi = self.plot_item.vb.viewRange()[1]
        pos = self._forecast_annotation.pos()
        return x_lo <= pos.x() <= x_hi and y_lo <= pos.y() <= y_hi

    def _forecast_annotation_box_height(self, view_y_range: float) -> float:
        scene_height = self._forecast_annotation.sceneBoundingRect().height()
        vb_height = self.plot_item.vb.geometry().height()
        if vb_height <= 0 or view_y_range <= 0 or scene_height <= 0:
            return 0.0
        box_height = scene_height * view_y_range / vb_height
        if box_height <= 0 or box_height >= view_y_range:
            return 0.0
        return box_height

    def _forecast_annotation_pos_near_path(
        self,
        x: float,
        y: float,
        anchor: str,
        x_lo: float,
        x_hi: float,
        y_lo: float,
        y_hi: float,
        x_pad: float,
        y_pad: float,
    ) -> Tuple[float, float]:
        forecast = self._forecast
        if forecast is None or not forecast.path_epochs:
            return x, y
        xs = [float(v) for v in forecast.path_epochs]
        if anchor in ("top_right", "top_left"):
            bands = [float(v) for v in forecast.path_upper]
        else:
            bands = [float(v) for v in forecast.path_lower]
        px0, px1 = xs[0], xs[-1]
        if px1 <= x_lo or px0 >= x_hi:
            return x, y
        vx0, vx1 = max(px0, x_lo), min(px1, x_hi)
        target_x = vx0 + (vx1 - vx0) * 0.25
        idx = min(range(len(xs)), key=lambda i: abs(xs[i] - target_x))
        band = bands[idx]
        if band <= y_lo or band >= y_hi:
            return x, y
        box_h = self._forecast_annotation_box_height(y_hi - y_lo)
        if box_h <= 0:
            return x, y
        if anchor in ("top_right", "top_left"):
            lo_y = y_lo + y_pad + box_h
            hi_y = y_hi - y_pad
            if lo_y >= hi_y:
                return x, hi_y
            y = min(max(band + y_pad + box_h, lo_y), hi_y)
        else:
            lo_y = y_lo + y_pad
            hi_y = y_hi - y_pad - box_h
            if hi_y <= lo_y:
                return x, lo_y
            y = min(max(band - y_pad - box_h, lo_y), hi_y)
        return x, y

    def set_forecast_annotation_anchor(self, anchor: str) -> None:
        """Places the forecast info box at a corner, hides it, or keeps it as-is.

        Called with the persisted anchor on startup and whenever the user picks
        a new anchor from the info box's context menu. A subsequent manual
        drag takes precedence until the next forecast is displayed.
        """
        normalized = normalize_forecast_annotation_anchor(anchor)
        self._forecast_annotation_anchor = normalized
        self._forecast_annotation_user_moved = False
        if normalized == "hidden":
            self._forecast_annotation.setVisible(False)
            return
        if self._forecast is None:
            return
        self._forecast_annotation.setVisible(True)
        self._position_forecast_annotation()

    def _on_forecast_annotation_user_moved(self) -> None:
        if self._forecast_annotation_setting_pos:
            return
        self._forecast_annotation_user_moved = True

    def _on_forecast_annotation_anchor_chosen(self, anchor: str) -> None:
        self.set_forecast_annotation_anchor(anchor)
        self.forecast_annotation_anchor_changed.emit(self._forecast_annotation_anchor)

    def set_swing_overlay(
        self,
        timestamps: List[float],
        prices: List[float],
        pivots: List[int],
        title: str = "",
        details: str = "",
        legs: Optional[List[Tuple[int, int]]] = None,
    ) -> None:
        """Draws the detected swing pivots as a violet zigzag line with markers.

        ``legs`` are ``(start, end)`` pivot index pairs; each one is marked
        with a semi-transparent yellow band spanning its time range and price
        range. When omitted, every consecutive pivot pair forms a leg.
        ``title`` and ``details`` (typically the algorithm name, its
        configuration parameters and the swing range) are rendered as a boxed
        annotation in the top-left corner of the plot.
        """
        valid_pivots = [
            int(i) for i in pivots if 0 <= int(i) < len(timestamps) and int(i) < len(prices)
        ]
        if legs is None:
            legs = list(zip(valid_pivots, valid_pivots[1:]))
        valid_legs = [
            (int(a), int(b))
            for a, b in legs
            if 0 <= int(a) <= int(b) < len(timestamps) and int(b) < len(prices)
        ]

        if valid_legs:
            xs: List[float] = []
            ys: List[float] = []
            previous_end: Optional[int] = None
            for start, end in valid_legs:
                if previous_end is None:
                    xs.append(timestamps[start])
                    ys.append(prices[start])
                elif start != previous_end:
                    xs.append(float("nan"))
                    ys.append(float("nan"))
                    xs.append(timestamps[start])
                    ys.append(prices[start])
                xs.append(timestamps[end])
                ys.append(prices[end])
                previous_end = end
            self.swing_line.setData(xs, ys)
            self.swing_line.setVisible(True)
        else:
            self.swing_line.setVisible(False)
            self.swing_line.setData([], [])

        if valid_pivots:
            self.swing_scatter.setData(
                [timestamps[i] for i in valid_pivots],
                [prices[i] for i in valid_pivots],
            )
            self.swing_scatter.setVisible(True)
        else:
            self.swing_scatter.setVisible(False)
            self.swing_scatter.setData([], [])

        self._set_swing_bands(timestamps, prices, valid_legs)

        text = "\n".join(part for part in (title, details) if part)
        if text:
            self.swing_text.setText(text)
            self.swing_text.setVisible(True)
            self._position_swing_text()
        else:
            self.swing_text.setVisible(False)

    def _set_swing_bands(
        self,
        timestamps: List[float],
        prices: List[float],
        legs: List[Tuple[int, int]],
    ) -> None:
        self._clear_swing_bands()
        band_pen = QPen(QColor(255, 235, 59, 170))
        band_pen.setWidthF(0.8)
        band_pen.setCosmetic(True)
        band_brush = QBrush(QColor(255, 235, 59, 40))
        for start, end in legs:
            x0 = float(timestamps[start])
            x1 = float(timestamps[end])
            segment = prices[start: end + 1]
            if x1 <= x0 or not segment:
                continue
            y0 = float(min(segment))
            y1 = float(max(segment))
            if y1 <= y0:
                y1 = y0 + max(abs(y0) * 0.001, 0.01)
            band = QGraphicsRectItem(x0, y0, x1 - x0, y1 - y0)
            band.setPen(band_pen)
            band.setBrush(band_brush)
            band.setZValue(-4)
            self.plot_item.addItem(band, ignoreBounds=True)
            self._swing_bands.append(band)

    def _clear_swing_bands(self) -> None:
        for band in self._swing_bands:
            try:
                self.plot_item.removeItem(band)
            except Exception:
                pass
        self._swing_bands = []

    def clear_swing_overlay(self) -> None:
        """Clears and hides the swing overlay line, markers, bands and annotation."""
        self.swing_line.setVisible(False)
        self.swing_line.setData([], [])
        self.swing_scatter.setVisible(False)
        self.swing_scatter.setData([], [])
        self._clear_swing_bands()
        self.swing_text.setVisible(False)

    def _position_swing_text(self, *args) -> None:
        if not self.swing_text.isVisible():
            return
        x_lo, x_hi = self.plot_item.vb.viewRange()[0]
        y_lo, y_hi = self.plot_item.vb.viewRange()[1]
        if x_hi <= x_lo or y_hi <= y_lo:
            return
        self.swing_text.setPos(x_lo + (x_hi - x_lo) * 0.02, y_hi - (y_hi - y_lo) * 0.05)

    def show_empty_state(self, visible: bool, message: Optional[str] = None) -> None:
        """Toggles display between plot widgets and empty state message."""
        if visible:
            if message:
                self.empty_label.setText(message)
            self.volume_chart.clear()
            self.plot_widget.hide()
            self.volume_chart.hide()
            self.empty_label.show()
        else:
            self.empty_label.hide()
            self.plot_widget.show()
            self.volume_chart.show()

    def reset_view(self) -> None:
        """Resets zoom and pan to the captured fit view for the current range."""
        self.volume_chart.reset_view()
        if self._view_bounds is None:
            self._fit_view_to_data()
            return

        x_lo, x_hi, y_lo, y_hi = self._view_bounds
        self.plot_item.setXRange(x_lo, x_hi, padding=0)
        self.plot_item.setYRange(y_lo, y_hi, padding=0)

    def _on_mouse_moved(self, pos) -> None:
        if not self._x_data or not self._y_data:
            return

        mouse_point = self.plot_item.vb.mapSceneToView(pos)
        x_val = mouse_point.x()

        # Check bounds
        if x_val < min(self._x_data) or x_val > max(self._x_data):
            self.v_line.setVisible(False)
            self.h_line.setVisible(False)
            self.tooltip_text.setVisible(False)
            self.hover_left.emit()
            return

        # Find closest point via binary search
        import bisect
        idx = bisect.bisect_left(self._x_data, x_val)
        if idx >= len(self._x_data):
            idx = len(self._x_data) - 1
        elif idx > 0 and abs(self._x_data[idx - 1] - x_val) < abs(self._x_data[idx] - x_val):
            idx = idx - 1

        px = self._x_data[idx]
        py = self._y_data[idx]
        dt_str = self._date_labels[idx] if idx < len(self._date_labels) else ""

        detail_parts: List[str] = []
        sym = self._currency_symbol
        if self._chart_type == ChartType.CANDLE and idx < len(self._candle_opens):
            o = self._candle_opens[idx]
            h = self._candle_highs[idx]
            l = self._candle_lows[idx]
            if o is not None and h is not None and l is not None:
                detail_parts.append(f"O: {sym}{o:,.2f} H: {sym}{h:,.2f} L: {sym}{l:,.2f}")
        if self._chart_type == ChartType.BASELINE and self._baseline is not None:
            detail_parts.append(f"Base: {sym}{self._baseline:,.2f}")

        # Check if overlay has a point near this timestamp
        if self._overlay_x and self._overlay_y and self.overlay_curve.isVisible():
            o_idx = bisect.bisect_left(self._overlay_x, x_val)
            if o_idx >= len(self._overlay_x):
                o_idx = len(self._overlay_x) - 1
            elif o_idx > 0 and abs(self._overlay_x[o_idx - 1] - x_val) < abs(self._overlay_x[o_idx] - x_val):
                o_idx = o_idx - 1
            detail_parts.append(f"{self._overlay_label}: {sym}{self._overlay_y[o_idx]:,.2f}")

        # ATR volatility bands contribute their upper/lower values
        if self._atr_label and self._atr_upper_curve.isVisible() and idx < len(self._atr_upper):
            atr_upper = self._atr_upper[idx]
            atr_lower = self._atr_lower[idx] if idx < len(self._atr_lower) else None
            if atr_upper is not None and atr_lower is not None:
                detail_parts.append(
                    f"{self._atr_label}+: {sym}{atr_upper:,.2f} / {sym}{atr_lower:,.2f}"
                )

        # Update crosshair position
        self.v_line.setPos(px)
        self.h_line.setPos(py)
        self.v_line.setVisible(True)
        self.h_line.setVisible(True)

        # Earnings markers take over the tooltip when hovered near them
        if self._hover_earnings_marker(mouse_point.x(), mouse_point.y()):
            self.hover_changed.emit(dt_str, py)
            return

        # Update tooltip text and position
        details_str = f" | {' | '.join(detail_parts)}" if detail_parts else ""
        self.tooltip_text.setText(f" {dt_str} | Raw: {sym}{py:,.2f}{details_str} ")
        self.tooltip_text.setPos(px, py)
        self.tooltip_text.setVisible(True)

        # Emit hover signal so header card can show exact hovered date/price
        self.hover_changed.emit(dt_str, py)

    def _hover_earnings_marker(self, x_val: float, y_val: float) -> bool:
        """Shows the earnings tooltip when the cursor is near a marker.

        Proximity is measured in view pixels (~10px horizontally, ~10% of the
        pane height vertically around the marker row). Returns True when an
        earnings tooltip is displayed instead of the price tooltip.
        """
        if not self._earnings_items:
            self._earnings_tooltip.setVisible(False)
            return False

        vb = self.plot_item.vb
        x_lo, x_hi = vb.viewRange()[0]
        y_lo, y_hi = vb.viewRange()[1]
        if x_hi <= x_lo or y_hi <= y_lo:
            self._earnings_tooltip.setVisible(False)
            return False

        view_width_px = max(vb.width(), 1.0)
        x_tolerance = (x_hi - x_lo) * (10.0 / view_width_px)
        marker_y = y_lo + (y_hi - y_lo) * 0.05
        y_tolerance = (y_hi - y_lo) * 0.10

        if abs(y_val - marker_y) > y_tolerance:
            self._earnings_tooltip.setVisible(False)
            return False

        for item, epoch in self._earnings_items:
            if abs(x_val - epoch) > x_tolerance:
                continue
            event = next(
                (e for e in self._earnings_events if e.epoch == epoch), None
            )
            if event is None:
                continue
            self._earnings_tooltip.setText(
                " " + format_earnings_tooltip(event, self._earnings_company) + " "
            )
            self._earnings_tooltip.setPos(epoch, marker_y)
            self._earnings_tooltip.setVisible(True)
            self.tooltip_text.setVisible(False)
            return True

        self._earnings_tooltip.setVisible(False)
        return False
