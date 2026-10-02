import logging
from typing import List, Optional

from PySide6.QtCore import Qt, Signal, QSize, QRect
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
    QWidget,
)

from app.models.ticker import TickerSummary

logger = logging.getLogger(__name__)


class TickerItemDelegate(QStyledItemDelegate):
    """Custom delegate for rendering ticker symbol, name, price, and daily change in the sidebar."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        painter.save()

        summary: Optional[TickerSummary] = index.data(Qt.UserRole)
        if not summary:
            painter.restore()
            super().paint(painter, option, index)
            return

        rect = option.rect

        # Background rendering
        is_selected = option.state & QStyle.State_Selected
        is_hovered = option.state & QStyle.State_MouseOver

        if is_selected:
            painter.fillRect(rect, QColor("#2a3147"))
            painter.setPen(QPen(QColor("#2962ff"), 2))
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
        elif is_hovered:
            painter.fillRect(rect, QColor("#252836"))
        else:
            painter.fillRect(rect, QColor("#1a1c24"))

        padding = 8
        content_rect = rect.adjusted(padding, padding, -padding, -padding)

        # Top row: Symbol (Left) & Price (Right)
        painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            QRect(content_rect.left(), content_rect.top(), 120, 20),
            Qt.AlignLeft | Qt.AlignVCenter,
            summary.symbol,
        )

        # Price
        if summary.current_price is not None:
            price_text = f"${summary.current_price:,.2f}"
            painter.drawText(
                QRect(content_rect.right() - 110, content_rect.top(), 110, 20),
                Qt.AlignRight | Qt.AlignVCenter,
                price_text,
            )

        # Bottom row: Company Name (Left) & Pct Change (Right)
        painter.setFont(QFont("Segoe UI", 9))
        painter.setPen(QColor("#8b90a0"))
        painter.drawText(
            QRect(content_rect.left(), content_rect.top() + 22, 130, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            summary.company_name[:18] + ("..." if len(summary.company_name) > 18 else ""),
        )

        # Pct Change
        if summary.pct_change is not None:
            change_text = f"{summary.pct_change:+.2f}%"
            if summary.pct_change > 0:
                painter.setPen(QColor("#00e676"))
            elif summary.pct_change < 0:
                painter.setPen(QColor("#ff5252"))
            else:
                painter.setPen(QColor("#8b90a0"))

            painter.drawText(
                QRect(content_rect.right() - 100, content_rect.top() + 22, 100, 18),
                Qt.AlignRight | Qt.AlignVCenter,
                change_text,
            )
        else:
            painter.setPen(QColor("#8b90a0"))
            painter.drawText(
                QRect(content_rect.right() - 100, content_rect.top() + 22, 100, 18),
                Qt.AlignRight | Qt.AlignVCenter,
                "--",
            )

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(220, 56)


class TickerListWidget(QListWidget):
    ticker_selected = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setItemDelegate(TickerItemDelegate(self))
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.currentItemChanged.connect(self._on_item_changed)

    def update_summaries(self, summaries: List[TickerSummary], select_symbol: Optional[str] = None) -> None:
        """Populates or updates list items with current summaries."""
        self.blockSignals(True)
        self.clear()

        selected_item = None
        target_sym = select_symbol.upper().strip() if select_symbol else None

        for summary in summaries:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, summary)
            item.setText(summary.symbol)  # For searching / default filtering
            self.addItem(item)

            if target_sym and summary.symbol.upper() == target_sym:
                selected_item = item

        self.blockSignals(False)

        if selected_item:
            self.setCurrentItem(selected_item)
        elif self.count() > 0:
            self.setCurrentRow(0)

    def select_ticker(self, symbol: str) -> None:
        clean_sym = symbol.upper().strip()
        for i in range(self.count()):
            item = self.item(i)
            summary: TickerSummary = item.data(Qt.UserRole)
            if summary and summary.symbol == clean_sym:
                self.setCurrentItem(item)
                break

    def get_selected_symbol(self) -> Optional[str]:
        current = self.currentItem()
        if current:
            summary: TickerSummary = current.data(Qt.UserRole)
            return summary.symbol if summary else None
        return None

    def select_first(self) -> None:
        if self.count() > 0:
            self.setCurrentRow(0)

    def select_last(self) -> None:
        if self.count() > 0:
            self.setCurrentRow(self.count() - 1)

    def _on_item_changed(self, current: Optional[QListWidgetItem], previous: Optional[QListWidgetItem]) -> None:
        if current:
            summary: TickerSummary = current.data(Qt.UserRole)
            if summary:
                self.ticker_selected.emit(summary.symbol)
