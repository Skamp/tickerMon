import sqlite3
import logging
from pathlib import Path
from typing import Optional
from app.database.schema import CREATE_PRICES_TABLE, CREATE_PRICES_INDEX, CREATE_METADATA_TABLE

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
                conn.commit()
            logger.info(f"Database schema initialized successfully at {self.db_path}")
        except Exception as e:
            logger.error(f"Error initializing database schema: {e}")
            raise
