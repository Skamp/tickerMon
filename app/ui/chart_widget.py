import logging
from datetime import datetime
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPen, QBrush, QLinearGradient
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

import pyqtgraph as pg

logger = logging.getLogger(__name__)

# Configure PyQtGraph global options for ultra-clean dark financial terminal
pg.setConfigOption("background", "#121318")
pg.setConfigOption("foreground", "#8b90a0")
pg.setConfigOption("antialias", True)


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
    """Custom Y-axis item to format price ticks with currency formatting ($)."""

    def tickStrings(self, values, scale, spacing):
        strings = []
        for v in values:
            if v >= 1000:
                strings.append(f"${v:,.0f}")
            else:
                strings.append(f"${v:,.2f}")
        return strings


class StockChartWidget(QWidget):
    hover_changed = Signal(str, float)  # Emits (date_string, hovered_price)
    hover_left = Signal()               # Emits when mouse exits chart bounds

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # Custom Axes
        self.x_axis = TimeAxisItem(orientation="bottom")
        self.y_axis = PriceAxisItem(orientation="right")

        self.plot_widget = pg.PlotWidget(axisItems={"bottom": self.x_axis, "right": self.y_axis})
        self.layout.addWidget(self.plot_widget)

        self.plot_item = self.plot_widget.getPlotItem()
        self.plot_item.showAxis("right", True)
        self.plot_item.hideAxis("left")
        self.plot_item.showGrid(x=True, y=True, alpha=0.10)
        self.plot_item.setMenuEnabled(True)

        # Raw Price Plot Curve Pen (1.2px width)
        self.pen = QPen(QColor("#00e676"))
        self.pen.setWidthF(1.2)
        self.pen.setCosmetic(True)
        self.curve = self.plot_item.plot(pen=self.pen)

        # Noise-Reduced Overlay Curve Pen (1.8px Amber Gold stroke)
        self.overlay_pen = QPen(QColor("#ffab00"))
        self.overlay_pen.setWidthF(1.8)
        self.overlay_pen.setCosmetic(True)
        self.overlay_curve = self.plot_item.plot(pen=self.overlay_pen)
        self.overlay_curve.setVisible(False)

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
        self.empty_label = QLabel("No local data available.\nPress 'Update Data' to download historical prices.", self)
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

        # Fit-view bounds (x_lo, x_hi, y_lo, y_hi) captured after each auto-fit
        self._view_bounds: Optional[Tuple[float, float, float, float]] = None

        # Connect mouse move event for crosshair
        self.plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)

    def set_data(
        self,
        timestamps: List[float],
        prices: List[float],
        date_labels: List[str],
        line_color: str = "#00e676",
    ) -> None:
        """Sets chart data points, line color, gradient fill, and updates plot view."""
        self._x_data = timestamps
        self._y_data = prices
        self._date_labels = date_labels

        if not timestamps or not prices:
            self._view_bounds = None
            self.show_empty_state(True)
            return

        self.show_empty_state(False)

        # Update curve color (thin 1.2px stroke)
        pen_color = QColor(line_color)
        self.pen.setColor(pen_color)
        self.pen.setWidthF(1.2)
        self.curve.setPen(self.pen)

        # Soft subtle fill underneath curve fading down to minimum price
        fill_color = QColor(line_color)
        fill_color.setAlpha(20)
        min_y = min(prices)
        self.curve.setFillLevel(min_y)
        self.curve.setBrush(pg.mkBrush(fill_color))

        # Set data to curve
        self.curve.setData(self._x_data, self._y_data)

        self._fit_view_to_data()

    def _fit_view_to_data(self) -> None:
        """Auto-fits the view to data bounds and locks zoom/pan limits to that fit view."""
        if not self._x_data or not self._y_data:
            return

        y_min, y_max = min(self._y_data), max(self._y_data)
        if self._overlay_y:
            y_min = min(y_min, min(self._overlay_y))
            y_max = max(y_max, max(self._overlay_y))

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

    def set_overlay_data(self, timestamps: List[float], prices: List[float]) -> None:
        """Sets and displays a secondary noise-reduced graph curve in Amber Gold."""
        self._overlay_x = timestamps
        self._overlay_y = prices

        if not timestamps or not prices:
            self.clear_overlay()
            return

        self.overlay_curve.setData(timestamps, prices)
        self.overlay_curve.setVisible(True)
        self._fit_view_to_data()

    def clear_overlay(self) -> None:
        """Clears and hides the secondary overlay curve."""
        self._overlay_x = []
        self._overlay_y = []
        self.overlay_curve.setVisible(False)
        self._fit_view_to_data()

    def show_empty_state(self, visible: bool, message: Optional[str] = None) -> None:
        """Toggles display between plot widget and empty state message."""
        if visible:
            if message:
                self.empty_label.setText(message)
            self.plot_widget.hide()
            self.empty_label.show()
        else:
            self.empty_label.hide()
            self.plot_widget.show()

    def reset_view(self) -> None:
        """Resets zoom and pan to the captured fit view for the current range."""
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

        # Check if overlay has a point near this timestamp
        overlay_val_str = ""
        if self._overlay_x and self._overlay_y and self.overlay_curve.isVisible():
            o_idx = bisect.bisect_left(self._overlay_x, x_val)
            if o_idx >= len(self._overlay_x):
                o_idx = len(self._overlay_x) - 1
            elif o_idx > 0 and abs(self._overlay_x[o_idx - 1] - x_val) < abs(self._overlay_x[o_idx] - x_val):
                o_idx = o_idx - 1
            overlay_val_str = f" | Filtered: ${self._overlay_y[o_idx]:,.2f}"

        # Update crosshair position
        self.v_line.setPos(px)
        self.h_line.setPos(py)
        self.v_line.setVisible(True)
        self.h_line.setVisible(True)

        # Update tooltip text and position
        self.tooltip_text.setText(f" {dt_str} | Raw: ${py:,.2f}{overlay_val_str} ")
        self.tooltip_text.setPos(px, py)
        self.tooltip_text.setVisible(True)

        # Emit hover signal so header card can show exact hovered date/price
        self.hover_changed.emit(dt_str, py)
