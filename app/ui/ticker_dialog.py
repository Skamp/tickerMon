import logging
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QCheckBox,
    QWidget,
)

from app.services.ticker_service import TickerService
from app.models.ticker import TickerConfig

logger = logging.getLogger(__name__)


class TickerAdminDialog(QDialog):
    def __init__(self, ticker_service: TickerService, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.ticker_service = ticker_service
        self.setWindowTitle("Manage Tickers")
        self.setMinimumSize(480, 420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(12)
        self.layout.setContentsMargins(16, 16, 16, 16)

        # Top section: Add new ticker input fields
        add_box = QHBoxLayout()
        self.sym_input = QLineEdit(self)
        self.sym_input.setPlaceholderText("Symbol (e.g. AAPL, SAP.DE)")
        self.sym_input.setFixedWidth(140)

        self.name_input = QLineEdit(self)
        self.name_input.setPlaceholderText("Company Name (optional)")

        self.add_btn = QPushButton("Add", self)
        self.add_btn.clicked.connect(self._on_add_ticker)

        add_box.addWidget(self.sym_input)
        add_box.addWidget(self.name_input)
        add_box.addWidget(self.add_btn)
        self.layout.addLayout(add_box)

        # Middle section: Ticker List + Side Action Buttons
        mid_layout = QHBoxLayout()
        self.list_widget = QListWidget(self)
        self.list_widget.currentItemChanged.connect(self._on_item_selected)
        mid_layout.addWidget(self.list_widget)

        # Action Buttons
        btn_box = QVBoxLayout()
        btn_box.setSpacing(6)

        self.up_btn = QPushButton("Move Up", self)
        self.up_btn.clicked.connect(self._on_move_up)

        self.down_btn = QPushButton("Move Down", self)
        self.down_btn.clicked.connect(self._on_move_down)

        self.toggle_btn = QPushButton("Toggle Enable", self)
        self.toggle_btn.clicked.connect(self._on_toggle_enable)

        self.delete_btn = QPushButton("Remove", self)
        self.delete_btn.setStyleSheet("QPushButton { color: #ff5252; }")
        self.delete_btn.clicked.connect(self._on_delete)

        btn_box.addWidget(self.up_btn)
        btn_box.addWidget(self.down_btn)
        btn_box.addWidget(self.toggle_btn)
        btn_box.addWidget(self.delete_btn)
        btn_box.addStretch()

        mid_layout.addLayout(btn_box)
        self.layout.addLayout(mid_layout)

        # Bottom section: Close Button
        bottom_box = QHBoxLayout()
        bottom_box.addStretch()
        self.close_btn = QPushButton("Done", self)
        self.close_btn.clicked.connect(self.accept)
        bottom_box.addWidget(self.close_btn)
        self.layout.addLayout(bottom_box)

        self.refresh_list()

    def refresh_list(self) -> None:
        self.list_widget.clear()
        for t in self.ticker_service.get_all_tickers():
            status_str = "[Enabled]" if t.enabled else "[Disabled]"
            label = f"{t.symbol:<10} {status_str:<12} {t.name}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, t.symbol)
            if not t.enabled:
                item.setForeground(Qt.darkGray)
            self.list_widget.addItem(item)

    def _on_add_ticker(self) -> None:
        sym = self.sym_input.text().strip()
        name = self.name_input.text().strip()

        ok, msg = self.ticker_service.add_ticker(sym, name)
        if not ok:
            QMessageBox.warning(self, "Invalid Ticker", msg)
            return

        self.sym_input.clear()
        self.name_input.clear()
        self.refresh_list()

    def _on_item_selected(self, current: Optional[QListWidgetItem], previous: Optional[QListWidgetItem]) -> None:
        has_sel = current is not None
        self.up_btn.setEnabled(has_sel)
        self.down_btn.setEnabled(has_sel)
        self.toggle_btn.setEnabled(has_sel)
        self.delete_btn.setEnabled(has_sel)

    def _on_toggle_enable(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0:
            return
        item = self.list_widget.item(row)
        sym = item.data(Qt.UserRole)
        for t in self.ticker_service.get_all_tickers():
            if t.symbol == sym:
                self.ticker_service.update_ticker(sym, t.name, not t.enabled)
                break
        self.refresh_list()
        self.list_widget.setCurrentRow(row)

    def _on_move_up(self) -> None:
        row = self.list_widget.currentRow()
        if row <= 0:
            return
        tickers = self.ticker_service.get_all_tickers()
        symbols = [t.symbol for t in tickers]
        symbols[row - 1], symbols[row] = symbols[row], symbols[row - 1]
        self.ticker_service.reorder_tickers(symbols)
        self.refresh_list()
        self.list_widget.setCurrentRow(row - 1)

    def _on_move_down(self) -> None:
        row = self.list_widget.currentRow()
        tickers = self.ticker_service.get_all_tickers()
        if row < 0 or row >= len(tickers) - 1:
            return
        symbols = [t.symbol for t in tickers]
        symbols[row + 1], symbols[row] = symbols[row], symbols[row + 1]
        self.ticker_service.reorder_tickers(symbols)
        self.refresh_list()
        self.list_widget.setCurrentRow(row + 1)

    def _on_delete(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0:
            return
        item = self.list_widget.item(row)
        sym = item.data(Qt.UserRole)

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to remove ticker '{sym}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.ticker_service.delete_ticker(sym)
            self.refresh_list()
