import logging
from typing import Dict, List, Optional, Set

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
from app.models.trend import TrendBucket
from app.utils.currency import format_price

logger = logging.getLogger(__name__)

SORT_BY_TICKER = "ticker"
SORT_BY_DATE = "date"
SORT_BY_NAME = "name"
SORT_BY_PRICE = "price"
SORT_BY_PERF = "perf"

SORT_CRITERIA = (
    SORT_BY_TICKER,
    SORT_BY_DATE,
    SORT_BY_NAME,
    SORT_BY_PRICE,
    SORT_BY_PERF,
)

# Legacy constants kept for backward compatibility
SORT_BY_DATE_ASC = "date_asc"
SORT_BY_DATE_DESC = "date_desc"
SORT_BY_PRICE_ASC = "price_asc"
SORT_BY_PRICE_DESC = "price_desc"
SORT_BY_PERF_ASC = "perf_asc"
SORT_BY_PERF_DESC = "perf_desc"

SORT_MODES = (
    SORT_BY_TICKER,
    SORT_BY_DATE,
    SORT_BY_NAME,
    SORT_BY_PRICE,
    SORT_BY_PERF,
    SORT_BY_DATE_ASC,
    SORT_BY_DATE_DESC,
    SORT_BY_PRICE_ASC,
    SORT_BY_PRICE_DESC,
    SORT_BY_PERF_ASC,
    SORT_BY_PERF_DESC,
)


def _numeric_sort_key(value: Optional[float], reverse: bool):
    if value is None:
        return (1, 0.0)
    return (0, -value if reverse else value)


def sort_ticker_summaries(
    summaries: List[TickerSummary],
    criterion: str = SORT_BY_TICKER,
    ascending: bool = True,
) -> List[TickerSummary]:
    """Returns summaries ordered by symbol, added date, company name, price or daily performance."""
    # Backward compatibility for legacy combined mode strings
    if criterion == SORT_BY_DATE_ASC:
        criterion, ascending = SORT_BY_DATE, True
    elif criterion == SORT_BY_DATE_DESC:
        criterion, ascending = SORT_BY_DATE, False
    elif criterion == SORT_BY_PRICE_ASC:
        criterion, ascending = SORT_BY_PRICE, True
    elif criterion == SORT_BY_PRICE_DESC:
        criterion, ascending = SORT_BY_PRICE, False
    elif criterion == SORT_BY_PERF_ASC:
        criterion, ascending = SORT_BY_PERF, True
    elif criterion == SORT_BY_PERF_DESC:
        criterion, ascending = SORT_BY_PERF, False

    items = list(summaries)
    reverse = not bool(ascending)

    if criterion == SORT_BY_DATE:
        items.sort(key=lambda s: s.symbol.upper())
        items.sort(key=lambda s: s.added_at or "", reverse=reverse)
    elif criterion == SORT_BY_NAME:
        items.sort(key=lambda s: s.symbol.upper())
        items.sort(key=lambda s: (s.company_name or "").casefold(), reverse=reverse)
    elif criterion == SORT_BY_PRICE:
        items.sort(key=lambda s: s.symbol.upper())
        items.sort(key=lambda s: _numeric_sort_key(s.current_price, reverse))
    elif criterion == SORT_BY_PERF:
        items.sort(key=lambda s: s.symbol.upper())
        items.sort(key=lambda s: _numeric_sort_key(s.pct_change, reverse))
    else:
        items.sort(key=lambda s: s.symbol.upper(), reverse=reverse)

    return items


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
        # Family comes from the view/app font (pinned in setup_display_scaling)
        # so the sidebar matches the rest of the UI on every platform.
        symbol_font = QFont(option.font)
        symbol_font.setPointSize(11)
        symbol_font.setBold(True)
        painter.setFont(symbol_font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            QRect(content_rect.left(), content_rect.top(), 120, 20),
            Qt.AlignLeft | Qt.AlignVCenter,
            summary.symbol,
        )

        # Price
        if summary.current_price is not None:
            price_text = format_price(summary.current_price, summary.currency)
            painter.drawText(
                QRect(content_rect.right() - 110, content_rect.top(), 110, 20),
                Qt.AlignRight | Qt.AlignVCenter,
                price_text,
            )

        # Bottom row: Company Name (Left) & Pct Change (Right)
        name_font = QFont(option.font)
        name_font.setPointSize(9)
        painter.setFont(name_font)
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

        self._summaries: List[TickerSummary] = []
        self._trends: Dict[str, TrendBucket] = {}
        self._swing_symbols: Set[str] = set()
        self._active_buckets: Set[TrendBucket] = set()
        self._swing_active: bool = False
        self._forecast_filter_active: bool = False
        self._forecast_symbols: Set[str] = set()
        self._sort_criterion: str = SORT_BY_TICKER
        self._sort_ascending: bool = True

        self.currentItemChanged.connect(self._on_item_changed)

    def set_sort(self, criterion: str, ascending: bool = True) -> None:
        """Reorders the list using the requested sort criterion and direction."""
        if criterion not in SORT_CRITERIA:
            criterion = SORT_BY_TICKER
        asc = bool(ascending)
        if criterion == self._sort_criterion and asc == self._sort_ascending:
            return
        self._sort_criterion = criterion
        self._sort_ascending = asc
        self._repopulate(self.get_selected_symbol())

    def set_sort_mode(self, mode: str) -> None:
        """Legacy helper: reorders using legacy combined mode string."""
        if mode in (SORT_BY_DATE_DESC, SORT_BY_PRICE_DESC, SORT_BY_PERF_DESC):
            crit = {
                SORT_BY_DATE_DESC: SORT_BY_DATE,
                SORT_BY_PRICE_DESC: SORT_BY_PRICE,
                SORT_BY_PERF_DESC: SORT_BY_PERF,
            }.get(mode, SORT_BY_TICKER)
            self.set_sort(crit, ascending=False)
        else:
            crit = {
                SORT_BY_DATE_ASC: SORT_BY_DATE,
                SORT_BY_NAME: SORT_BY_NAME,
                SORT_BY_PRICE_ASC: SORT_BY_PRICE,
                SORT_BY_PERF_ASC: SORT_BY_PERF,
            }.get(mode, SORT_BY_TICKER)
            self.set_sort(crit, ascending=True)

    @property
    def sort_criterion(self) -> str:
        return self._sort_criterion

    @property
    def sort_ascending(self) -> bool:
        return self._sort_ascending

    @property
    def _sort_mode(self) -> str:
        """Legacy property accessor for compatibility."""
        if self._sort_criterion == SORT_BY_DATE:
            return SORT_BY_DATE_ASC if self._sort_ascending else SORT_BY_DATE_DESC
        if self._sort_criterion == SORT_BY_PRICE:
            return SORT_BY_PRICE_ASC if self._sort_ascending else SORT_BY_PRICE_DESC
        if self._sort_criterion == SORT_BY_PERF:
            return SORT_BY_PERF_ASC if self._sort_ascending else SORT_BY_PERF_DESC
        if self._sort_criterion == SORT_BY_NAME:
            return SORT_BY_NAME
        return SORT_BY_TICKER

    def update_summaries(
        self,
        summaries: List[TickerSummary],
        select_symbol: Optional[str] = None,
        trends: Optional[Dict[str, TrendBucket]] = None,
        swing_symbols: Optional[Set[str]] = None,
    ) -> None:
        """Populates or updates list items with current summaries."""
        self._summaries = list(summaries)
        if trends is not None:
            self._trends = dict(trends)
        if swing_symbols is not None:
            self._swing_symbols = set(swing_symbols)
        self._repopulate(select_symbol)

    def set_trend_filter(self, buckets: Set[TrendBucket], include_swing: bool = False) -> None:
        """Shows tickers matching any active bucket or the swing flag; nothing active shows all."""
        self._active_buckets = set(buckets)
        self._swing_active = include_swing
        self._repopulate(None)

    def set_forecast_filter(
        self, active: bool, symbols: Optional[Set[str]] = None
    ) -> None:
        """ANDs a forecast filter: only tickers in ``symbols`` stay visible.

        ``active=False`` disables the criterion entirely (an active filter
        with an empty symbol set hides every ticker).
        """
        new_symbols = set(symbols) if symbols else set()
        if active == self._forecast_filter_active and new_symbols == self._forecast_symbols:
            return
        self._forecast_filter_active = active
        self._forecast_symbols = new_symbols
        self._repopulate(None)

    def _repopulate(self, select_symbol: Optional[str]) -> None:
        prev_symbol = self.get_selected_symbol()
        target_sym = select_symbol.upper().strip() if select_symbol else prev_symbol
        filtered = bool(self._active_buckets) or self._swing_active
        ordered = sort_ticker_summaries(self._summaries, self._sort_criterion, self._sort_ascending)

        self.blockSignals(True)
        self.clear()

        selected_item = None
        first_item = None
        for summary in ordered:
            if filtered:
                in_trend = self._trends.get(summary.symbol) in self._active_buckets
                in_swing = self._swing_active and summary.symbol in self._swing_symbols
                if not (in_trend or in_swing):
                    continue
            if self._forecast_filter_active and summary.symbol not in self._forecast_symbols:
                continue

            item = QListWidgetItem()
            item.setData(Qt.UserRole, summary)
            item.setText(summary.symbol)
            item.setToolTip(
                f"{summary.symbol}\nAdded: {summary.added_at}" if summary.added_at
                else f"{summary.symbol}\nAdded: unknown"
            )
            self.addItem(item)

            if first_item is None:
                first_item = item
            if target_sym and summary.symbol.upper() == target_sym:
                selected_item = item

        chosen = selected_item or first_item
        if chosen:
            self.setCurrentItem(chosen)
        self.blockSignals(False)

        new_symbol = self.get_selected_symbol()
        if new_symbol and new_symbol != prev_symbol:
            self.ticker_selected.emit(new_symbol)

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
