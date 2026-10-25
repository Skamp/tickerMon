"""Forecast History dialog: browse, inspect, evaluate and delete saved forecasts.

The table shows one row per saved forecast with its immutable prediction and
(when available) the recorded outcome. Selection loads the stored snapshot
into the detail pane — old forecasts are never silently regenerated. Showing a
forecast on the chart displays the stored snapshot, clearly marked as saved.
"""

import logging
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.models.forecast import (
    EVALUATION_EVALUATED,
    EVALUATION_PENDING,
    EVALUATION_UNAVAILABLE,
    DirectionalBias,
    ForecastHorizon,
    SavedForecast,
    format_evaluation_details,
)
from app.services.forecast_service import ForecastAccuracy, ForecastService
from app.utils.currency import get_currency_symbol

logger = logging.getLogger(__name__)

_STATUS_LABELS = {
    EVALUATION_PENDING: "Pending",
    EVALUATION_EVALUATED: "Evaluated",
    EVALUATION_UNAVAILABLE: "Unavailable",
}

_COLUMNS = (
    "Ticker",
    "Generated",
    "Horizon",
    "Ref Close",
    "Target",
    "Direction",
    "Central",
    "Range",
    "Actual",
    "Actual %",
    "Status",
)


def _fmt_price(value: Optional[float], symbol: str) -> str:
    if value is None:
        return "--"
    return f"{symbol}{value:,.2f}"


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "--"
    return f"{value:+.2f}%"


class ForecastHistoryDialog(QDialog):
    """Lists saved forecasts with filters, detail view and management actions."""

    show_forecast_requested = Signal(object)  # SavedForecast
    direction_filter_changed = Signal(str)  # DirectionalBias value, "" for All

    def __init__(
        self,
        forecast_service: ForecastService,
        parent: Optional[QWidget] = None,
        direction_filter: Optional[str] = None,
    ):
        super().__init__(parent)
        self.forecast_service = forecast_service
        self._records: List[SavedForecast] = []
        self.setWindowTitle("Forecast History")
        self.setMinimumSize(1080, 560)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        filter_row.addWidget(QLabel("Ticker:", self))
        self.combo_ticker = QComboBox(self)
        self.combo_ticker.setMinimumWidth(100)
        self.combo_ticker.currentIndexChanged.connect(self._refresh_table)
        filter_row.addWidget(self.combo_ticker)

        filter_row.addWidget(QLabel("Horizon:", self))
        self.combo_horizon = QComboBox(self)
        self.combo_horizon.addItem("All", None)
        for horizon in (ForecastHorizon.ONE_MONTH, ForecastHorizon.TWO_MONTHS, ForecastHorizon.THREE_MONTHS):
            self.combo_horizon.addItem(horizon.value, horizon.months)
        self.combo_horizon.currentIndexChanged.connect(self._refresh_table)
        filter_row.addWidget(self.combo_horizon)

        filter_row.addWidget(QLabel("Status:", self))
        self.combo_status = QComboBox(self)
        self.combo_status.addItem("All", None)
        self.combo_status.addItem("Pending", EVALUATION_PENDING)
        self.combo_status.addItem("Evaluated", EVALUATION_EVALUATED)
        self.combo_status.addItem("Unavailable", EVALUATION_UNAVAILABLE)
        self.combo_status.currentIndexChanged.connect(self._refresh_table)
        filter_row.addWidget(self.combo_status)

        filter_row.addWidget(QLabel("Direction:", self))
        self.combo_direction = QComboBox(self)
        self.combo_direction.addItem("All", None)
        for bias in DirectionalBias:
            self.combo_direction.addItem(bias.value, bias.value)
        if direction_filter:
            initial = self.combo_direction.findData(direction_filter)
            if initial >= 0:
                self.combo_direction.setCurrentIndex(initial)
        self.combo_direction.currentIndexChanged.connect(self._on_direction_changed)
        filter_row.addWidget(self.combo_direction)

        filter_row.addWidget(QLabel("Sort:", self))
        self.combo_sort = QComboBox(self)
        self.combo_sort.addItem("Generated (newest)", "generated_desc")
        self.combo_sort.addItem("Generated (oldest)", "generated_asc")
        self.combo_sort.addItem("Target (newest)", "target_desc")
        self.combo_sort.addItem("Target (oldest)", "target_asc")
        self.combo_sort.currentIndexChanged.connect(self._refresh_table)
        filter_row.addWidget(self.combo_sort)

        filter_row.addStretch()
        layout.addLayout(filter_row)

        self.table = QTableWidget(self)
        self.table.setColumnCount(len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, 3)

        self.detail = QTextEdit(self)
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(170)
        self.detail.setPlaceholderText("Select a forecast to inspect its stored snapshot and outcome.")
        layout.addWidget(self.detail, 1)

        stats_row = QHBoxLayout()
        self.lbl_stats = QLabel("", self)
        self.lbl_stats.setStyleSheet("color: #8b90a0;")
        self.lbl_stats.setWordWrap(True)
        stats_row.addWidget(self.lbl_stats, 1)
        layout.addLayout(stats_row)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        self.btn_show = QPushButton("Show on Chart", self)
        self.btn_show.setToolTip("Display the selected saved forecast on the price chart")
        self.btn_show.clicked.connect(self._on_show_forecast)
        button_row.addWidget(self.btn_show)

        self.btn_evaluate = QPushButton("Evaluate Now", self)
        self.btn_evaluate.setToolTip(
            "Evaluate pending forecasts whose target date has passed\n"
            "against locally stored closing prices."
        )
        self.btn_evaluate.clicked.connect(self._on_evaluate)
        button_row.addWidget(self.btn_evaluate)

        self.btn_walk_forward = QPushButton("Walk-Forward Test", self)
        self.btn_walk_forward.setToolTip(
            "Chronological validation for the selected ticker:\n"
            "forecast from each historical origin using only past data."
        )
        self.btn_walk_forward.clicked.connect(self._on_walk_forward)
        button_row.addWidget(self.btn_walk_forward)

        button_row.addStretch()

        self.btn_delete = QPushButton("Delete Selected", self)
        self.btn_delete.clicked.connect(self._on_delete_selected)
        button_row.addWidget(self.btn_delete)

        self.btn_delete_old = QPushButton("Delete Older Than…", self)
        self.btn_delete_old.clicked.connect(self._on_delete_older)
        button_row.addWidget(self.btn_delete_old)

        self.btn_close = QPushButton("Close", self)
        self.btn_close.clicked.connect(self.reject)
        button_row.addWidget(self.btn_close)

        layout.addLayout(button_row)

        self._reload()

    def _reload(self) -> None:
        records = self.forecast_service.load_saved()
        self._populate_ticker_filter(records)
        self._refresh_table()
        self._update_stats()

    def _populate_ticker_filter(self, records: List[SavedForecast]) -> None:
        current = self.combo_ticker.currentData()
        tickers = sorted({r.forecast.ticker for r in records})
        self.combo_ticker.blockSignals(True)
        self.combo_ticker.clear()
        self.combo_ticker.addItem("All", None)
        for ticker in tickers:
            self.combo_ticker.addItem(ticker, ticker)
        index = self.combo_ticker.findData(current)
        self.combo_ticker.setCurrentIndex(index if index >= 0 else 0)
        self.combo_ticker.blockSignals(False)

    def _current_filters(self):
        return (
            self.combo_ticker.currentData(),
            self.combo_horizon.currentData(),
            self.combo_status.currentData(),
            self.combo_direction.currentData(),
            self.combo_sort.currentData() or "generated_desc",
        )

    def _on_direction_changed(self, index: int) -> None:
        self.direction_filter_changed.emit(self.combo_direction.currentData() or "")
        self._refresh_table()

    def _refresh_table(self) -> None:
        ticker, horizon, status, direction, order_by = self._current_filters()
        self._records = self.forecast_service.load_saved(
            ticker=ticker, horizon_months=horizon, evaluation_status=status, order_by=order_by
        )
        if direction:
            self._records = [
                record
                for record in self._records
                if DirectionalBias.from_str(record.forecast.directional_bias).value
                == direction
            ]
        symbol = get_currency_symbol(None)
        self.table.setRowCount(len(self._records))
        for row, record in enumerate(self._records):
            forecast = record.forecast
            values = [
                forecast.ticker,
                forecast.generated_at,
                forecast.horizon_label,
                _fmt_price(forecast.reference_close, symbol),
                forecast.target_date,
                forecast.directional_bias,
                _fmt_price(forecast.central_estimate, symbol),
                f"{_fmt_price(forecast.lower_estimate, symbol)} – {_fmt_price(forecast.upper_estimate, symbol)}",
                _fmt_price(record.actual_price, symbol),
                _fmt_pct(record.actual_change_pct),
                _STATUS_LABELS.get(record.evaluation_status, record.evaluation_status),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, record.id)
                self.table.setItem(row, col, item)
        self.detail.clear()
        self.btn_show.setEnabled(False)

    def _selected_records(self) -> List[SavedForecast]:
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        return [self._records[row] for row in rows if 0 <= row < len(self._records)]

    def _on_selection_changed(self) -> None:
        records = self._selected_records()
        self.btn_show.setEnabled(len(records) == 1)
        if not records:
            self.detail.clear()
            return
        record = records[0]
        self.detail.setPlainText(format_evaluation_details(record))

    def _on_show_forecast(self) -> None:
        records = self._selected_records()
        if len(records) != 1:
            QMessageBox.information(self, "Show Forecast", "Select exactly one forecast to display.")
            return
        self.show_forecast_requested.emit(records[0])

    def _on_evaluate(self) -> None:
        evaluated, unavailable, pending = self.forecast_service.evaluate_pending()
        self._reload()
        QMessageBox.information(
            self,
            "Evaluate Forecasts",
            f"Evaluated: {evaluated}\nMarked unavailable: {unavailable}\nStill pending: {pending}",
        )

    def _on_walk_forward(self) -> None:
        ticker = self.combo_ticker.currentData()
        if not ticker:
            records = self._selected_records()
            ticker = records[0].forecast.ticker if records else None
        if not ticker:
            QMessageBox.information(
                self, "Walk-Forward Test", "Select a ticker filter or a forecast row first."
            )
            return

        horizon = ForecastHorizon.ONE_MONTH
        selected = self._selected_records()
        if selected:
            months = selected[0].forecast.horizon_months
            for candidate in ForecastHorizon:
                if candidate.months == months:
                    horizon = candidate
                    break

        result = self.forecast_service.walk_forward_validate(ticker, horizon)
        lines = [
            f"Walk-forward validation: {result.ticker} ({horizon.value})",
            f"Origins evaluated: {result.n_origins}",
        ]
        if result.mean_absolute_error is not None:
            lines.append(f"Mean absolute error: {result.mean_absolute_error:,.2f}")
        if result.mape is not None:
            lines.append(f"MAPE: {result.mape:.2f}%")
        if result.directional_accuracy is not None:
            lines.append(
                f"Directional accuracy: {result.directional_accuracy:.1f}% "
                f"(n={result.directional_sample})"
            )
        else:
            lines.append(
                f"Directional accuracy: n/a (sample {result.directional_sample} "
                f"< minimum for a meaningful rate)"
            )
        if result.errors:
            lines.append("")
            lines.append("Notes:")
            for error in result.errors[:5]:
                lines.append(f"- {error}")
        lines.append("")
        lines.append("Origins use only data available at that time (no look-ahead).")
        QMessageBox.information(self, "Walk-Forward Test", "\n".join(lines))

    def _on_delete_selected(self) -> None:
        records = self._selected_records()
        if not records:
            QMessageBox.information(self, "Delete Forecasts", "Select one or more forecasts first.")
            return
        answer = QMessageBox.question(
            self,
            "Delete Forecasts",
            f"Delete {len(records)} forecast(s)?\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        deleted = self.forecast_service.delete([r.id for r in records])
        self._reload()
        QMessageBox.information(self, "Delete Forecasts", f"Deleted {deleted} forecast(s).")

    def _on_delete_older(self) -> None:
        days, ok = QInputDialog.getInt(
            self,
            "Delete Older Forecasts",
            "Delete forecasts generated more than N days ago:",
            90,
            1,
            3650,
            1,
        )
        if not ok:
            return
        answer = QMessageBox.question(
            self,
            "Delete Older Forecasts",
            f"Delete forecasts generated more than {days} days ago?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        deleted = self.forecast_service.delete_older_than(days)
        self._reload()
        QMessageBox.information(self, "Delete Forecasts", f"Deleted {deleted} forecast(s).")

    def _update_stats(self) -> None:
        stats: ForecastAccuracy = self.forecast_service.accuracy_stats()
        overall = stats.overall
        parts = [
            f"Evaluated: {overall.n_evaluated}",
            f"Pending: {overall.n_pending}",
        ]
        if overall.n_evaluated > 0:
            if overall.mean_absolute_error is not None:
                parts.append(f"Avg abs error: {overall.mean_absolute_error:,.2f}")
            if overall.mape is not None:
                parts.append(f"MAPE: {overall.mape:.2f}%")
            if overall.directional_accuracy is not None:
                parts.append(
                    f"Directional: {overall.directional_accuracy:.1f}% (n={overall.directional_sample})"
                )
            else:
                parts.append(
                    f"Directional: n/a (sample {overall.directional_sample} too small)"
                )
        if stats.by_horizon:
            horizon_bits = []
            for months, bucket in stats.by_horizon.items():
                if bucket.n_evaluated > 0:
                    acc = (
                        f"{bucket.directional_accuracy:.0f}%"
                        if bucket.directional_accuracy is not None
                        else "n/a"
                    )
                    horizon_bits.append(f"{months}M: n={bucket.n_evaluated}, dir {acc}")
            if horizon_bits:
                parts.append("By horizon — " + "; ".join(horizon_bits))
        self.lbl_stats.setText(" | ".join(parts))
