import logging

from PySide6.QtCore import QThread, Signal

from app.services.earnings_service import EarningsService

logger = logging.getLogger(__name__)


class EarningsWorker(QThread):
    """Background thread that refreshes earnings events for a single ticker."""

    finished_events = Signal(str, object)

    def __init__(self, earnings_service: EarningsService, symbol: str, parent=None):
        super().__init__(parent)
        self.earnings_service = earnings_service
        self.symbol = symbol

    def run(self) -> None:
        events = []
        try:
            events = self.earnings_service.refresh(self.symbol)
        except Exception as e:
            logger.warning(f"Earnings refresh worker failed for {self.symbol}: {e}")
        self.finished_events.emit(self.symbol, events if isinstance(events, list) else [])
