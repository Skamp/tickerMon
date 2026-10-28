import sys
import logging
from pathlib import Path

from app.ui.scaling import (
    apply_scaling_env,
    consume_debug_flag,
    print_diagnostics,
    scaling_summary,
    setup_display_scaling,
)

ROOT_DIR = Path(__file__).resolve().parent

# Qt reads its DPI/scale environment variables when QApplication is created,
# so the scaling policy must be pinned BEFORE PySide6 is imported.
DEBUG_DPI = consume_debug_flag(sys.argv)
apply_scaling_env(ROOT_DIR / "config" / "tickers.json")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon, QPalette, QColor
from PySide6.QtCore import Qt

from app.config.config_manager import ConfigManager
from app.database.database import Database
from app.database.repositories import ForecastRepository, MarketDataRepository
from app.services.yahoo_service import YahooService
from app.services.market_data_service import MarketDataService
from app.services.ticker_service import TickerService
from app.services.sync_service import SyncService
from app.services.earnings_service import EarningsService
from app.services.forecast_service import ForecastService
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
    root_dir = ROOT_DIR
    config_path = root_dir / "config" / "tickers.json"
    db_path = root_dir / "data" / "market_data.db"
    logs_dir = root_dir / "logs"

    # Setup Logging
    setup_logging(logs_dir)
    logging.info("Display scaling policy: %s", scaling_summary())

    # Initialize Qt Application
    app = QApplication(sys.argv)
    app.setApplicationName("tickerMon")
    app.setStyle("Fusion")

    # Apply Dark Theme QSS
    app.setStyleSheet(DARK_THEME_QSS)

    # Pin the application-wide default font before any widget is created
    setup_display_scaling(app)
    if DEBUG_DPI:
        print_diagnostics(app)

    # Initialize Core Application Layer
    try:
        config_manager = ConfigManager(config_path)
        database = Database(db_path)
        repo = MarketDataRepository(database)
        forecast_repo = ForecastRepository(database)

        yahoo_service = YahooService()
        market_data_service = MarketDataService(repo)
        ticker_service = TickerService(config_manager)
        sync_service = SyncService(yahoo_service, repo)
        earnings_service = EarningsService(yahoo_service, repo)
        forecast_service = ForecastService(
            market_data_service, ticker_service, forecast_repo, price_repo=repo
        )

        # Launch Main Window
        window = MainWindow(
            ticker_service=ticker_service,
            market_data_service=market_data_service,
            sync_service=sync_service,
            earnings_service=earnings_service,
            forecast_service=forecast_service,
        )
        window.show()

        sys.exit(app.exec())
    except Exception as e:
        logging.critical(f"Unhandled exception during application startup: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
