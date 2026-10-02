import logging
from typing import List
from PySide6.QtCore import QThread, Signal

from app.services.sync_service import SyncService
from app.models.ticker import TickerConfig

logger = logging.getLogger(__name__)


class UpdateWorker(QThread):
    ticker_started = Signal(str)
    ticker_finished = Signal(str, str, str)  # symbol, status, message
    overall_completed = Signal(int, int)    # success_count, fail_count

    def __init__(self, sync_service: SyncService, tickers: List[TickerConfig]):
        super().__init__()
        self.sync_service = sync_service
        self.tickers = tickers

    def run(self) -> None:
        logger.info(f"Starting background market data update for {len(self.tickers)} tickers.")

        def callback(symbol: str, status: str, message: str):
            if status == "UPDATING":
                self.ticker_started.emit(symbol)
            else:
                self.ticker_finished.emit(symbol, status, message)

        success_count, fail_count, _ = self.sync_service.sync_all_enabled(
            enabled_tickers=self.tickers,
            progress_callback=callback,
        )

        logger.info(f"Completed update task. Success: {success_count}, Failed: {fail_count}")
        self.overall_completed.emit(success_count, fail_count)
