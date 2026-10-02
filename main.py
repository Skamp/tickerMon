import sys
import logging
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon, QPalette, QColor
from PySide6.QtCore import Qt

from app.config.config_manager import ConfigManager
from app.database.database import Database
from app.database.repositories import MarketDataRepository
from app.services.yahoo_service import YahooService
from app.services.market_data_service import MarketDataService
from app.services.ticker_service import TickerService
from app.services.sync_service import SyncService
from app.ui.styles import DARK_THEME_QSS
from app.ui.main_window import MainWindow


def setup_logging(logs_dir: Path) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "app.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logging.info("Starting tickerMon Stock Monitoring Application...")


def main() -> None:
    # Root directory definition
    root_dir = Path(__file__).resolve().parent
    config_path = root_dir / "config" / "tickers.json"
    db_path = root_dir / "data" / "market_data.db"
    logs_dir = root_dir / "logs"

    # Setup Logging
    setup_logging(logs_dir)

    # Initialize Qt Application
    app = QApplication(sys.argv)
    app.setApplicationName("tickerMon")
    app.setStyle("Fusion")

    # Apply Dark Theme QSS
    app.setStyleSheet(DARK_THEME_QSS)

    # Initialize Core Application Layer
    try:
        config_manager = ConfigManager(config_path)
        database = Database(db_path)
        repo = MarketDataRepository(database)

        yahoo_service = YahooService()
        market_data_service = MarketDataService(repo)
        ticker_service = TickerService(config_manager)
        sync_service = SyncService(yahoo_service, repo)

        # Launch Main Window
        window = MainWindow(
            ticker_service=ticker_service,
            market_data_service=market_data_service,
            sync_service=sync_service,
        )
        window.show()

        sys.exit(app.exec())
    except Exception as e:
        logging.critical(f"Unhandled exception during application startup: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
