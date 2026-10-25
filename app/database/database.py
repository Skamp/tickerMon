import sqlite3
import logging
from pathlib import Path
from typing import Optional
from app.database.schema import (
    CREATE_PRICES_TABLE,
    CREATE_PRICES_INDEX,
    CREATE_METADATA_TABLE,
    ADD_FIRST_DOWNLOAD_COLUMN,
    FILL_FIRST_DOWNLOAD,
    CREATE_EARNINGS_TABLE,
    CREATE_EARNINGS_META_TABLE,
    CREATE_FORECASTS_TABLE,
    CREATE_FORECASTS_TICKER_INDEX,
    CREATE_FORECASTS_TARGET_INDEX,
    CREATE_FORECASTS_GENERATED_INDEX,
    CREATE_FORECASTS_STATUS_INDEX,
)

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_dir()
        self.initialize_schema()

    def _ensure_dir(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        # Enable Write-Ahead Logging for improved concurrency
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def initialize_schema(self) -> None:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(CREATE_PRICES_TABLE)
                cursor.execute(CREATE_PRICES_INDEX)
                cursor.execute(CREATE_METADATA_TABLE)
                cursor.execute(CREATE_EARNINGS_TABLE)
                cursor.execute(CREATE_EARNINGS_META_TABLE)
                cursor.execute(CREATE_FORECASTS_TABLE)
                cursor.execute(CREATE_FORECASTS_TICKER_INDEX)
                cursor.execute(CREATE_FORECASTS_TARGET_INDEX)
                cursor.execute(CREATE_FORECASTS_GENERATED_INDEX)
                cursor.execute(CREATE_FORECASTS_STATUS_INDEX)
                self._migrate_metadata_table(cursor)
                conn.commit()
            logger.info(f"Database schema initialized successfully at {self.db_path}")
        except Exception as e:
            logger.error(f"Error initializing database schema: {e}")
            raise

    @staticmethod
    def _migrate_metadata_table(cursor: sqlite3.Cursor) -> None:
        columns = {row["name"] for row in cursor.execute("PRAGMA table_info(ticker_metadata);")}
        if "first_download" not in columns:
            cursor.execute(ADD_FIRST_DOWNLOAD_COLUMN)
            cursor.execute(FILL_FIRST_DOWNLOAD)
            logger.info("Migrated ticker_metadata with first_download column.")
