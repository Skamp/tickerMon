import json
import sqlite3
import logging
from typing import List, Optional, Dict, Any, Tuple
import pandas as pd
from datetime import datetime

from app.database.database import Database
from app.models.price_data import PricePoint, PriceSeries
from app.models.earnings import EarningsEvent
from app.models.forecast import (
    EVALUATION_EVALUATED,
    EVALUATION_PENDING,
    EVALUATION_UNAVAILABLE,
    Forecast,
    SavedForecast,
    now_iso,
    rebuild_projection,
)

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

    def get_first_timestamp(self, symbol: str) -> Optional[str]:
        """Returns the earliest stored timestamp for a ticker symbol, if any."""
        clean_symbol = symbol.upper().strip()
        sql = "SELECT timestamp FROM prices WHERE symbol = ? ORDER BY timestamp ASC LIMIT 1;"
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, [clean_symbol])
                row = cursor.fetchone()
                if row:
                    return row["timestamp"]
        except Exception as e:
            logger.error(f"Error getting first timestamp for {clean_symbol}: {e}")
        return None

    def has_price_data(self, symbol: str) -> bool:
        """Returns True when at least one price row is stored for the ticker."""
        clean_symbol = symbol.upper().strip()
        sql = "SELECT 1 FROM prices WHERE symbol = ? LIMIT 1;"
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, [clean_symbol])
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking price data for {clean_symbol}: {e}")
            return False

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
        INSERT INTO ticker_metadata (symbol, company_name, currency, exchange, last_download, first_download, last_data_timestamp, status, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET
            company_name = COALESCE(excluded.company_name, ticker_metadata.company_name),
            currency = COALESCE(excluded.currency, ticker_metadata.currency),
            exchange = COALESCE(excluded.exchange, ticker_metadata.exchange),
            last_download = excluded.last_download,
            first_download = COALESCE(ticker_metadata.first_download, excluded.first_download),
            last_data_timestamp = COALESCE(excluded.last_data_timestamp, ticker_metadata.last_data_timestamp),
            status = excluded.status,
            error_message = excluded.error_message;
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, (
                    clean_symbol, company_name, currency, exchange, last_dl, now_str,
                    last_data_timestamp, status, error_message
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

    def replace_earnings(self, symbol: str, events: List[EarningsEvent]) -> None:
        """Replaces all cached earnings events for a symbol."""
        clean_symbol = symbol.upper().strip()
        records = [
            (
                clean_symbol,
                event.event_date,
                event.eps_estimate,
                event.reported_eps,
                event.surprise_pct,
                1 if event.is_estimated else 0,
                event.quarter,
                event.timing,
            )
            for event in events
        ]
        sql = """
        INSERT INTO earnings (symbol, event_date, eps_estimate, reported_eps, surprise_pct, is_estimated, quarter, timing)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM earnings WHERE symbol = ?;", [clean_symbol])
                if records:
                    cursor.executemany(sql, records)
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to replace earnings for {clean_symbol}: {e}")
            raise

    def get_earnings(self, symbol: str) -> List[EarningsEvent]:
        """Returns cached earnings events for a symbol, oldest first."""
        clean_symbol = symbol.upper().strip()
        sql = (
            "SELECT symbol, event_date, eps_estimate, reported_eps, surprise_pct, "
            "is_estimated, quarter, timing FROM earnings WHERE symbol = ? "
            "ORDER BY event_date ASC;"
        )
        results: List[EarningsEvent] = []
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, [clean_symbol])
                for row in cursor.fetchall():
                    results.append(EarningsEvent(
                        symbol=row["symbol"],
                        event_date=row["event_date"],
                        eps_estimate=row["eps_estimate"],
                        reported_eps=row["reported_eps"],
                        surprise_pct=row["surprise_pct"],
                        is_estimated=bool(row["is_estimated"]),
                        quarter=row["quarter"],
                        timing=row["timing"],
                    ))
        except Exception as e:
            logger.error(f"Error querying earnings for {clean_symbol}: {e}")
        return results

    def get_earnings_fetched_at(self, symbol: str) -> Optional[str]:
        """Returns the ISO timestamp of the last successful earnings fetch."""
        clean_symbol = symbol.upper().strip()
        sql = "SELECT fetched_at FROM earnings_meta WHERE symbol = ?;"
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, [clean_symbol])
                row = cursor.fetchone()
                return row["fetched_at"] if row else None
        except Exception as e:
            logger.error(f"Error reading earnings fetch time for {clean_symbol}: {e}")
            return None

    def set_earnings_fetched_at(self, symbol: str, fetched_at: str) -> None:
        """Upserts the last successful earnings fetch timestamp."""
        clean_symbol = symbol.upper().strip()
        sql = """
        INSERT INTO earnings_meta (symbol, fetched_at) VALUES (?, ?)
        ON CONFLICT(symbol) DO UPDATE SET fetched_at = excluded.fetched_at;
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, [clean_symbol, fetched_at])
                conn.commit()
        except Exception as e:
            logger.error(f"Error saving earnings fetch time for {clean_symbol}: {e}")


_FORECAST_COLUMNS = (
    "id, ticker, generated_at, reference_date, reference_close, target_date, "
    "horizon_months, directional_bias, central_estimate, lower_estimate, "
    "upper_estimate, expected_change_pct, model_version, input_snapshot_json, "
    "signal_summary_json, evaluation_status, actual_price, actual_date, "
    "actual_change_pct, absolute_error, percentage_error, evaluated_at"
)


def _row_to_saved_forecast(row: sqlite3.Row) -> SavedForecast:
    try:
        input_snapshot = json.loads(row["input_snapshot_json"] or "{}")
    except (TypeError, ValueError):
        input_snapshot = {}
    try:
        signal_summary = json.loads(row["signal_summary_json"] or "{}")
    except (TypeError, ValueError):
        signal_summary = {}

    forecast = Forecast(
        ticker=row["ticker"],
        generated_at=row["generated_at"],
        reference_date=row["reference_date"],
        reference_close=row["reference_close"],
        target_date=row["target_date"],
        horizon_months=row["horizon_months"],
        directional_bias=row["directional_bias"],
        central_estimate=row["central_estimate"],
        lower_estimate=row["lower_estimate"],
        upper_estimate=row["upper_estimate"],
        expected_change_pct=row["expected_change_pct"],
        model_version=row["model_version"],
        input_snapshot=input_snapshot,
        signal_summary=signal_summary,
    )
    rebuild_projection(forecast)
    return SavedForecast(
        id=row["id"],
        forecast=forecast,
        evaluation_status=row["evaluation_status"] or EVALUATION_PENDING,
        actual_price=row["actual_price"],
        actual_date=row["actual_date"],
        actual_change_pct=row["actual_change_pct"],
        absolute_error=row["absolute_error"],
        percentage_error=row["percentage_error"],
        evaluated_at=row["evaluated_at"],
    )


class ForecastRepository:
    """Persistence for immutable forecast snapshots and their evaluation fields.

    Prediction fields are written once at save time and never updated; only
    the dedicated evaluation columns change when an outcome is recorded.
    """

    def __init__(self, db: Database):
        self.db = db

    def save_forecast(self, forecast: Forecast) -> int:
        """Inserts a forecast snapshot; returns the new row id."""
        try:
            input_json = json.dumps(forecast.input_snapshot or {}, sort_keys=True)
            signal_json = json.dumps(forecast.signal_summary or {}, sort_keys=True)
        except (TypeError, ValueError) as e:
            logger.error(f"Forecast snapshot is not JSON-serializable: {e}")
            raise

        sql = f"""
        INSERT INTO forecasts (
            ticker, generated_at, reference_date, reference_close, target_date,
            horizon_months, directional_bias, central_estimate, lower_estimate,
            upper_estimate, expected_change_pct, model_version, input_snapshot_json,
            signal_summary_json, evaluation_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        params = (
            forecast.ticker.upper().strip(),
            forecast.generated_at,
            forecast.reference_date,
            forecast.reference_close,
            forecast.target_date,
            forecast.horizon_months,
            forecast.directional_bias,
            forecast.central_estimate,
            forecast.lower_estimate,
            forecast.upper_estimate,
            forecast.expected_change_pct,
            forecast.model_version,
            input_json,
            signal_json,
            EVALUATION_PENDING,
        )
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                conn.commit()
                return int(cursor.lastrowid)
        except Exception as e:
            logger.error(f"Failed to save forecast for {forecast.ticker}: {e}")
            raise

    def has_duplicate(self, forecast: Forecast) -> bool:
        """True when an identical snapshot (ticker, generation time, estimates) exists."""
        sql = """
        SELECT 1 FROM forecasts
        WHERE ticker = ? AND generated_at = ? AND central_estimate = ?
          AND target_date = ? AND model_version = ?
        LIMIT 1;
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, [
                    forecast.ticker.upper().strip(),
                    forecast.generated_at,
                    forecast.central_estimate,
                    forecast.target_date,
                    forecast.model_version,
                ])
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking duplicate forecast: {e}")
            return False

    def get_forecasts(
        self,
        ticker: Optional[str] = None,
        horizon_months: Optional[int] = None,
        evaluation_status: Optional[str] = None,
        order_by: str = "generated_desc",
        limit: Optional[int] = None,
    ) -> List[SavedForecast]:
        """Returns saved forecasts with optional filters, newest generation first."""
        sql = f"SELECT {_FORECAST_COLUMNS} FROM forecasts WHERE 1=1"
        params: List[Any] = []
        if ticker:
            sql += " AND ticker = ?"
            params.append(ticker.upper().strip())
        if horizon_months is not None:
            sql += " AND horizon_months = ?"
            params.append(int(horizon_months))
        if evaluation_status:
            sql += " AND evaluation_status = ?"
            params.append(evaluation_status)

        order_map = {
            "generated_desc": "generated_at DESC, id DESC",
            "generated_asc": "generated_at ASC, id ASC",
            "target_desc": "target_date DESC, id DESC",
            "target_asc": "target_date ASC, id ASC",
        }
        sql += f" ORDER BY {order_map.get(order_by, order_map['generated_desc'])}"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))

        results: List[SavedForecast] = []
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                for row in cursor.fetchall():
                    results.append(_row_to_saved_forecast(row))
        except Exception as e:
            logger.error(f"Error querying forecasts: {e}")
        return results

    def get_forecast(self, forecast_id: int) -> Optional[SavedForecast]:
        sql = f"SELECT {_FORECAST_COLUMNS} FROM forecasts WHERE id = ?;"
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, [int(forecast_id)])
                row = cursor.fetchone()
                return _row_to_saved_forecast(row) if row else None
        except Exception as e:
            logger.error(f"Error fetching forecast {forecast_id}: {e}")
            return None

    def get_pending_forecasts(self) -> List[SavedForecast]:
        return self.get_forecasts(evaluation_status=EVALUATION_PENDING, order_by="target_asc")

    def update_evaluation(
        self,
        forecast_id: int,
        actual_price: float,
        actual_date: str,
        actual_change_pct: float,
        absolute_error: float,
        percentage_error: Optional[float],
        evaluated_at: Optional[str] = None,
        status: str = EVALUATION_EVALUATED,
    ) -> None:
        """Records the outcome for a forecast; prediction columns are untouched."""
        sql = """
        UPDATE forecasts SET
            evaluation_status = ?, actual_price = ?, actual_date = ?,
            actual_change_pct = ?, absolute_error = ?, percentage_error = ?,
            evaluated_at = ?
        WHERE id = ?;
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, [
                    status,
                    actual_price,
                    actual_date,
                    actual_change_pct,
                    absolute_error,
                    percentage_error,
                    evaluated_at or now_iso(),
                    int(forecast_id),
                ])
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating evaluation for forecast {forecast_id}: {e}")
            raise

    def mark_unavailable(self, forecast_id: int) -> None:
        """Marks a forecast unavailable (retryable — status can be reset later)."""
        sql = "UPDATE forecasts SET evaluation_status = ? WHERE id = ?;"
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, [EVALUATION_UNAVAILABLE, int(forecast_id)])
                conn.commit()
        except Exception as e:
            logger.error(f"Error marking forecast {forecast_id} unavailable: {e}")
            raise

    def delete_forecasts(self, forecast_ids: List[int]) -> int:
        """Deletes the given forecasts in one transaction; returns rows removed."""
        ids = [int(i) for i in forecast_ids]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        sql = f"DELETE FROM forecasts WHERE id IN ({placeholders});"
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, ids)
                conn.commit()
                return cursor.rowcount
        except Exception as e:
            logger.error(f"Error deleting forecasts: {e}")
            raise

    def delete_forecasts_before(self, cutoff_date: str) -> int:
        """Deletes forecasts generated before ``cutoff_date`` (YYYY-MM-DD)."""
        sql = "DELETE FROM forecasts WHERE generated_at < ?;"
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, [f"{cutoff_date} 00:00:00"])
                conn.commit()
                return cursor.rowcount
        except Exception as e:
            logger.error(f"Error deleting forecasts before {cutoff_date}: {e}")
            raise

    def count_by_status(self) -> Dict[str, int]:
        counts = {EVALUATION_PENDING: 0, EVALUATION_EVALUATED: 0, EVALUATION_UNAVAILABLE: 0}
        sql = "SELECT evaluation_status, COUNT(*) AS n FROM forecasts GROUP BY evaluation_status;"
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql)
                for row in cursor.fetchall():
                    counts[row["evaluation_status"]] = row["n"]
        except Exception as e:
            logger.error(f"Error counting forecasts by status: {e}")
        return counts
