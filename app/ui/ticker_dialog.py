import logging
from typing import List, Optional

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QBrush, QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QMessageBox,
    QCheckBox,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
    QWidget,
)

from app.services.ticker_service import TickerService
from app.models.ticker import TickerConfig

logger = logging.getLogger(__name__)

ROW_PADDING = 2


class TickerRowDelegate(QStyledItemDelegate):
    """Paints one continuous selection/hover band spanning all three columns."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        view = option.widget
        opt = QStyleOptionViewItem(option)
        selected = bool(opt.state & QStyle.State_Selected)
        hovered = False
        if view is not None:
            hover_index = view.indexAt(view.mapFromGlobal(QCursor.pos()))
            hovered = hover_index.isValid() and hover_index.row() == index.row()
        opt.state &= ~(QStyle.State_Selected | QStyle.State_MouseOver)

        if view is not None and index.column() == 0 and (selected or hovered):
            last_index = index.model().index(index.row(), index.model().columnCount() - 1)
            row_rect = QRect(opt.rect)
            row_rect.setRight(view.visualRect(last_index).right())
            row_rect.adjust(ROW_PADDING, ROW_PADDING, -ROW_PADDING, -ROW_PADDING)
            painter.save()
            if selected:
                painter.fillRect(row_rect, QColor("#2a3147"))
                painter.setPen(QPen(QColor("#2962ff"), 1))
                painter.drawRoundedRect(row_rect, 4, 4)
            else:
                painter.fillRect(row_rect, QColor("#252836"))
            painter.restore()

        super().paint(painter, opt, index)


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
        self.list_widget = QTreeWidget(self)
        self.list_widget.setColumnCount(3)
        self.list_widget.setHeaderHidden(True)
        self.list_widget.setRootIsDecorated(False)
        self.list_widget.setUniformRowHeights(True)
        self.list_widget.setAllColumnsShowFocus(True)
        self.list_widget.setEditTriggers(QTreeWidget.NoEditTriggers)
        self.list_widget.setSelectionMode(QTreeWidget.SingleSelection)
        header = self.list_widget.header()
        header.setSectionsClickable(False)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.list_widget.setItemDelegate(TickerRowDelegate(self.list_widget))
        self.list_widget.entered.connect(lambda *_: self.list_widget.viewport().update())
        self.list_widget.viewportEntered.connect(lambda: self.list_widget.viewport().update())
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
        tickers = self.ticker_service.get_all_tickers()
        for t in tickers:
            item = QTreeWidgetItem()
            item.setText(0, t.symbol)
            item.setText(1, "[Enabled]" if t.enabled else "[Disabled]")
            item.setText(2, t.name)
            item.setData(0, Qt.UserRole, t.symbol)
            if not t.enabled:
                for col in range(3):
                    item.setForeground(col, QBrush(Qt.darkGray))
            self.list_widget.addTopLevelItem(item)
        self._update_column_widths(tickers)

    def _update_column_widths(self, tickers: List[TickerConfig]) -> None:
        fm = self.list_widget.fontMetrics()
        symbol_width = max([fm.horizontalAdvance(t.symbol) for t in tickers] or [0])
        status_width = max(
            fm.horizontalAdvance("[Enabled]"),
            fm.horizontalAdvance("[Disabled]"),
        )
        self.list_widget.setColumnWidth(0, max(symbol_width + 24, 90))
        self.list_widget.setColumnWidth(1, max(status_width + 24, 96))

    def _current_row(self) -> int:
        item = self.list_widget.currentItem()
        if item is None:
            return -1
        return self.list_widget.indexOfTopLevelItem(item)

    def _set_current_row(self, row: int) -> None:
        item = self.list_widget.topLevelItem(row)
        if item is not None:
            self.list_widget.setCurrentItem(item)

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

    def _on_item_selected(self, current: Optional[QTreeWidgetItem], previous: Optional[QTreeWidgetItem]) -> None:
        has_sel = current is not None
        self.up_btn.setEnabled(has_sel)
        self.down_btn.setEnabled(has_sel)
        self.toggle_btn.setEnabled(has_sel)
        self.delete_btn.setEnabled(has_sel)

    def _on_toggle_enable(self) -> None:
        row = self._current_row()
        if row < 0:
            return
        item = self.list_widget.topLevelItem(row)
        sym = item.data(0, Qt.UserRole)
        for t in self.ticker_service.get_all_tickers():
            if t.symbol == sym:
                self.ticker_service.update_ticker(sym, t.name, not t.enabled)
                break
        self.refresh_list()
        self._set_current_row(row)

    def _on_move_up(self) -> None:
        row = self._current_row()
        if row <= 0:
            return
        tickers = self.ticker_service.get_all_tickers()
        symbols = [t.symbol for t in tickers]
        symbols[row - 1], symbols[row] = symbols[row], symbols[row - 1]
        self.ticker_service.reorder_tickers(symbols)
        self.refresh_list()
        self._set_current_row(row - 1)

    def _on_move_down(self) -> None:
        row = self._current_row()
        tickers = self.ticker_service.get_all_tickers()
        if row < 0 or row >= len(tickers) - 1:
            return
        symbols = [t.symbol for t in tickers]
        symbols[row + 1], symbols[row] = symbols[row], symbols[row + 1]
        self.ticker_service.reorder_tickers(symbols)
        self.refresh_list()
        self._set_current_row(row + 1)

    def _on_delete(self) -> None:
        row = self._current_row()
        if row < 0:
            return
        item = self.list_widget.topLevelItem(row)
        sym = item.data(0, Qt.UserRole)

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to remove ticker '{sym}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.ticker_service.delete_ticker(sym)
            self.refresh_list()
