import logging
from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Optional, Callable
import pandas as pd

from app.database.repositories import MarketDataRepository
from app.services.yahoo_service import YahooService
from app.models.ticker import TickerConfig

logger = logging.getLogger(__name__)


class SyncService:
    def __init__(self, yahoo_service: YahooService, repo: MarketDataRepository):
        self.yahoo_service = yahoo_service
        self.repo = repo

    def sync_ticker(self, symbol: str, force_full: bool = False) -> Tuple[bool, str, int]:
        """
        Synchronizes a single ticker.
        Returns tuple of (success_bool, message_str, inserted_record_count).
        """
        clean_symbol = symbol.upper().strip()
        last_ts = self.repo.get_last_timestamp(clean_symbol)

        period = "2y"
        start_date = None

        if not force_full and last_ts:
            try:
                # If we have existing data, request data starting 5 days prior to last timestamp
                # to catch any recent revisions or split adjustments safely.
                if " " in last_ts:
                    dt = datetime.strptime(last_ts, "%Y-%m-%d %H:%M:%S")
                else:
                    dt = datetime.strptime(last_ts[:10], "%Y-%m-%d")

                fetch_start = dt - timedelta(days=5)
                start_date = fetch_start.strftime("%Y-%m-%d")
            except Exception as e:
                logger.warning(f"Error parsing last timestamp '{last_ts}' for {clean_symbol}: {e}")
                start_date = None

        try:
            df, info = self.yahoo_service.fetch_ticker_data(
                symbol=clean_symbol,
                period=period if not start_date else "1y",
                interval="1d",
                start_date=start_date,
            )

            if df is None or df.empty:
                # Check if we already had data locally
                if last_ts:
                    msg = "No new data returned; local data up-to-date."
                    self.repo.update_ticker_metadata(
                        symbol=clean_symbol,
                        company_name=info.get("company_name"),
                        currency=info.get("currency"),
                        exchange=info.get("exchange"),
                        last_data_timestamp=last_ts,
                        status="OK",
                        error_message="",
                    )
                    return True, msg, 0
                else:
                    msg = "No data available from Yahoo Finance (invalid ticker or delisted)."
                    self.repo.update_ticker_metadata(
                        symbol=clean_symbol,
                        company_name=clean_symbol,
                        status="ERROR",
                        error_message=msg,
                    )
                    return False, msg, 0

            inserted_count = self.repo.upsert_price_data(clean_symbol, df)
            latest_local_ts = self.repo.get_last_timestamp(clean_symbol)

            self.repo.update_ticker_metadata(
                symbol=clean_symbol,
                company_name=info.get("company_name"),
                currency=info.get("currency"),
                exchange=info.get("exchange"),
                last_data_timestamp=latest_local_ts,
                status="OK",
                error_message="",
            )

            return True, f"Updated {inserted_count} records", inserted_count

        except Exception as e:
            err_msg = str(e)
            logger.error(f"Error syncing {clean_symbol}: {err_msg}")
            self.repo.update_ticker_metadata(
                symbol=clean_symbol,
                status="ERROR",
                error_message=err_msg,
            )
            return False, err_msg, 0

    def sync_all_enabled(
        self,
        enabled_tickers: List[TickerConfig],
        progress_callback: Optional[Callable[[str, str, str], None]] = None,
    ) -> Tuple[int, int, Dict[str, str]]:
        """
        Synchronizes all enabled tickers one by one.
        progress_callback signature: fn(symbol: str, status: str, message: str)
        Returns tuple of (success_count, fail_count, status_dict).
        """
        success_count = 0
        fail_count = 0
        results: Dict[str, str] = {}

        for cfg in enabled_tickers:
            sym = cfg.symbol
            if progress_callback:
                progress_callback(sym, "UPDATING", "Fetching data...")

            ok, msg, count = self.sync_ticker(sym)
            if ok:
                success_count += 1
                status_str = "OK"
                results[sym] = f"OK ({count} records)"
            else:
                fail_count += 1
                status_str = "ERROR"
                results[sym] = f"ERROR: {msg}"

            if progress_callback:
                progress_callback(sym, status_str, msg)

        return success_count, fail_count, results
