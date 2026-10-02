import logging
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QHeaderView,
    QWidget,
)

from app.models.ticker import TickerConfig

logger = logging.getLogger(__name__)


class UpdateProgressDialog(QDialog):
    def __init__(self, tickers: List[TickerConfig], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.tickers = tickers
        self.setWindowTitle("Updating Market Data")
        self.setMinimumSize(520, 360)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(12)
        self.layout.setContentsMargins(16, 16, 16, 16)

        # Header Title
        self.title_label = QLabel("Syncing tickers with Yahoo Finance...", self)
        self.title_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #ffffff;")
        self.layout.addWidget(self.title_label)

        # Progress Bar
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, max(1, len(tickers)))
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #282b36;
                border-radius: 4px;
                background-color: #1a1c24;
                text-align: center;
                color: #ffffff;
            }
            QProgressBar::chunk {
                background-color: #2962ff;
                border-radius: 3px;
            }
        """)
        self.layout.addWidget(self.progress_bar)

        # Table Widget
        self.table = QTableWidget(len(tickers), 3, self)
        self.table.setHorizontalHeaderLabels(["Symbol", "Status", "Details"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 90)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 90)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)

        # Populate rows
        self._symbol_row_map = {}
        for row, cfg in enumerate(tickers):
            sym = cfg.symbol
            self._symbol_row_map[sym] = row

            item_sym = QTableWidgetItem(sym)
            item_sym.setTextAlignment(Qt.AlignCenter)
            item_sym.setForeground(QColor("#ffffff"))

            item_status = QTableWidgetItem("Queued")
            item_status.setTextAlignment(Qt.AlignCenter)
            item_status.setForeground(QColor("#8b90a0"))

            item_msg = QTableWidgetItem("Waiting...")
            item_msg.setForeground(QColor("#8b90a0"))

            self.table.setItem(row, 0, item_sym)
            self.table.setItem(row, 1, item_status)
            self.table.setItem(row, 2, item_msg)

        self.layout.addWidget(self.table)

        # Bottom Row: Summary & Close Button
        bottom_layout = QHBoxLayout()
        self.summary_label = QLabel("Syncing in progress...", self)
        self.summary_label.setStyleSheet("color: #8b90a0;")
        bottom_layout.addWidget(self.summary_label)

        bottom_layout.addStretch()
        self.close_btn = QPushButton("Cancel", self)
        self.close_btn.clicked.connect(self.accept)
        bottom_layout.addWidget(self.close_btn)

        self.layout.addLayout(bottom_layout)
        self._completed_count = 0

    def on_ticker_started(self, symbol: str) -> None:
        if symbol in self._symbol_row_map:
            row = self._symbol_row_map[symbol]
            item_status = self.table.item(row, 1)
            item_msg = self.table.item(row, 2)
            if item_status and item_msg:
                item_status.setText("Updating...")
                item_status.setForeground(QColor("#2962ff"))
                item_msg.setText("Downloading historical data...")

    def on_ticker_finished(self, symbol: str, status: str, message: str) -> None:
        if symbol in self._symbol_row_map:
            row = self._symbol_row_map[symbol]
            item_status = self.table.item(row, 1)
            item_msg = self.table.item(row, 2)
            if item_status and item_msg:
                item_status.setText(status)
                if status == "OK":
                    item_status.setForeground(QColor("#00e676"))
                else:
                    item_status.setForeground(QColor("#ff5252"))
                item_msg.setText(message)

        self._completed_count += 1
        self.progress_bar.setValue(self._completed_count)

    def on_overall_completed(self, success_count: int, fail_count: int) -> None:
        self.title_label.setText("Market Data Update Completed")
        self.summary_label.setText(f"Completed: {success_count} successful, {fail_count} failed.")
        self.close_btn.setText("Close")
        self.close_btn.setEnabled(True)
