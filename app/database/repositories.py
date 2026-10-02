import sqlite3
import logging
from typing import List, Optional, Dict, Any, Tuple
import pandas as pd
from datetime import datetime

from app.database.database import Database
from app.models.price_data import PricePoint, PriceSeries

logger = logging.getLogger(__name__)


class MarketDataRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert_price_data(self, symbol: str, df: pd.DataFrame) -> int:
        """
        Inserts or updates price records from a DataFrame.
        DataFrame is expected to have timestamp index or column, and columns:
        Open, High, Low, Close, Adj Close, Volume, Dividends, Stock Splits.
        """
        if df.empty:
            return 0

        # Ensure timestamp is a column
        df = df.copy()
        if "Timestamp" in df.columns:
            df["timestamp_str"] = pd.to_datetime(df["Timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(df.index, pd.DatetimeIndex):
            df["timestamp_str"] = df.index.strftime("%Y-%m-%d %H:%M:%S")
        elif "timestamp" in df.columns:
            df["timestamp_str"] = pd.to_datetime(df["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            logger.error("DataFrame lacks recognizable timestamp column or DatetimeIndex")
            return 0

        # Normalize column names
        col_map = {
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
            "Dividends": "dividends",
            "Stock Splits": "stock_splits",
        }
        df = df.rename(columns=col_map)

        # Fallback if adj_close missing
        if "adj_close" not in df.columns and "close" in df.columns:
            df["adj_close"] = df["close"]

        # Default optional columns
        for col in ["dividends", "stock_splits"]:
            if col not in df.columns:
                df[col] = 0.0

        records = []
        clean_symbol = symbol.upper().strip()
        for _, row in df.iterrows():
            ts = str(row["timestamp_str"])
            records.append((
                clean_symbol,
                ts,
                float(row["open"]) if pd.notnull(row["open"]) else None,
                float(row["high"]) if pd.notnull(row["high"]) else None,
                float(row["low"]) if pd.notnull(row["low"]) else None,
                float(row["close"]) if pd.notnull(row["close"]) else None,
                float(row["adj_close"]) if pd.notnull(row["adj_close"]) else None,
                int(row["volume"]) if pd.notnull(row["volume"]) else 0,
                float(row["dividends"]) if pd.notnull(row.get("dividends")) else 0.0,
                float(row["stock_splits"]) if pd.notnull(row.get("stock_splits")) else 0.0,
            ))

        sql = """
        INSERT INTO prices (symbol, timestamp, open, high, low, close, adj_close, volume, dividends, stock_splits)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, timestamp) DO UPDATE SET
            open=excluded.open,
            high=excluded.high,
            low=excluded.low,
            close=excluded.close,
            adj_close=excluded.adj_close,
            volume=excluded.volume,
            dividends=excluded.dividends,
            stock_splits=excluded.stock_splits;
        """

        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.executemany(sql, records)
                conn.commit()
                row_count = cursor.rowcount
            logger.debug(f"Upserted {len(records)} records for {clean_symbol}")
            return len(records)
        except Exception as e:
            logger.error(f"Failed to upsert price data for {clean_symbol}: {e}")
            raise

    def get_prices(self, symbol: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[PricePoint]:
        """Queries stored price points for a symbol sorted chronologically."""
        clean_symbol = symbol.upper().strip()
        sql = "SELECT symbol, timestamp, open, high, low, close, adj_close, volume, dividends, stock_splits FROM prices WHERE symbol = ?"
        params: List[Any] = [clean_symbol]

        if start_date:
            sql += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND timestamp <= ?"
            params.append(end_date)

        sql += " ORDER BY timestamp ASC;"

        results: List[PricePoint] = []
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                for row in cursor.fetchall():
                    results.append(PricePoint(
                        symbol=row["symbol"],
                        timestamp=row["timestamp"],
                        open=row["open"] or 0.0,
                        high=row["high"] or 0.0,
                        low=row["low"] or 0.0,
                        close=row["close"] or 0.0,
                        adj_close=row["adj_close"] if row["adj_close"] is not None else (row["close"] or 0.0),
                        volume=row["volume"] or 0,
                        dividends=row["dividends"] or 0.0,
                        stock_splits=row["stock_splits"] or 0.0,
                    ))
        except Exception as e:
            logger.error(f"Error querying prices for {clean_symbol}: {e}")

        return results

    def get_latest_price_point(self, symbol: str) -> Optional[PricePoint]:
        """Retrieves the single most recent price point for a symbol."""
        clean_symbol = symbol.upper().strip()
        sql = """
        SELECT symbol, timestamp, open, high, low, close, adj_close, volume, dividends, stock_splits
        FROM prices
        WHERE symbol = ?
        ORDER BY timestamp DESC
        LIMIT 1;
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, [clean_symbol])
                row = cursor.fetchone()
                if row:
                    return PricePoint(
                        symbol=row["symbol"],
                        timestamp=row["timestamp"],
                        open=row["open"] or 0.0,
                        high=row["high"] or 0.0,
                        low=row["low"] or 0.0,
                        close=row["close"] or 0.0,
                        adj_close=row["adj_close"] if row["adj_close"] is not None else (row["close"] or 0.0),
                        volume=row["volume"] or 0,
                        dividends=row["dividends"] or 0.0,
                        stock_splits=row["stock_splits"] or 0.0,
                    )
        except Exception as e:
            logger.error(f"Error getting latest price point for {clean_symbol}: {e}")
        return None

    def get_last_timestamp(self, symbol: str) -> Optional[str]:
        """Returns the latest stored timestamp for a ticker symbol, if any."""
        point = self.get_latest_price_point(symbol)
        return point.timestamp if point else None

    def update_ticker_metadata(
        self,
        symbol: str,
        company_name: Optional[str] = None,
        currency: Optional[str] = None,
        exchange: Optional[str] = None,
        last_download: Optional[str] = None,
        last_data_timestamp: Optional[str] = None,
        status: str = "OK",
        error_message: Optional[str] = None,
    ) -> None:
        """Upserts metadata records for a ticker symbol."""
        clean_symbol = symbol.upper().strip()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        last_dl = last_download or now_str

        sql = """
        INSERT INTO ticker_metadata (symbol, company_name, currency, exchange, last_download, last_data_timestamp, status, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET
            company_name = COALESCE(excluded.company_name, ticker_metadata.company_name),
            currency = COALESCE(excluded.currency, ticker_metadata.currency),
            exchange = COALESCE(excluded.exchange, ticker_metadata.exchange),
            last_download = excluded.last_download,
            last_data_timestamp = COALESCE(excluded.last_data_timestamp, ticker_metadata.last_data_timestamp),
            status = excluded.status,
            error_message = excluded.error_message;
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (
                    clean_symbol, company_name, currency, exchange, last_dl, last_data_timestamp, status, error_message
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating metadata for {clean_symbol}: {e}")

    def get_ticker_metadata(self, symbol: str) -> Optional[dict]:
        clean_symbol = symbol.upper().strip()
        sql = "SELECT * FROM ticker_metadata WHERE symbol = ?"
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, [clean_symbol])
                row = cursor.fetchone()
                if row:
                    return dict(row)
        except Exception as e:
            logger.error(f"Error fetching metadata for {clean_symbol}: {e}")
        return None

    def get_all_metadata(self) -> Dict[str, dict]:
        sql = "SELECT * FROM ticker_metadata"
        meta_dict = {}
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql)
                for row in cursor.fetchall():
                    d = dict(row)
                    meta_dict[d["symbol"]] = d
        except Exception as e:
            logger.error(f"Error fetching all metadata: {e}")
        return meta_dict
