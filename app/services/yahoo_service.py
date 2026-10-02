import logging
from typing import Tuple, Dict, List, Optional, Any
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class YahooService:
    def __init__(self):
        pass

    def fetch_ticker_info(self, symbol: str) -> dict:
        """
        Retrieves basic info for a ticker such as shortName, longName, currency, exchange.
        Returns empty dict on failure without raising exceptions.
        """
        clean_symbol = symbol.upper().strip()
        try:
            ticker = yf.Ticker(clean_symbol)
            info = ticker.info or {}
            company_name = info.get("shortName") or info.get("longName") or clean_symbol
            currency = info.get("currency") or "USD"
            exchange = info.get("exchange") or ""
            return {
                "symbol": clean_symbol,
                "company_name": company_name,
                "currency": currency,
                "exchange": exchange,
            }
        except Exception as e:
            logger.warning(f"Could not retrieve ticker info for {clean_symbol}: {e}")
            return {
                "symbol": clean_symbol,
                "company_name": clean_symbol,
                "currency": "USD",
                "exchange": "",
            }

    def fetch_ticker_data(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
        start_date: Optional[str] = None,
    ) -> Tuple[pd.DataFrame, dict]:
        """
        Downloads historical price data for a single ticker.
        Returns tuple of (DataFrame, info_dict).
        DataFrame columns are normalized to: Open, High, Low, Close, Adj Close, Volume, Dividends, Stock Splits.
        """
        clean_symbol = symbol.upper().strip()
        info = self.fetch_ticker_info(clean_symbol)
        try:
            ticker = yf.Ticker(clean_symbol)
            if start_date:
                df = ticker.history(start=start_date, interval=interval, auto_adjust=False)
            else:
                df = ticker.history(period=period, interval=interval, auto_adjust=False)

            if df is None or df.empty:
                logger.warning(f"No historical data returned from Yahoo Finance for {clean_symbol}")
                return pd.DataFrame(), info

            df = self._normalize_dataframe(df)
            return df, info
        except Exception as e:
            logger.error(f"Error fetching Yahoo Finance data for {clean_symbol}: {e}")
            return pd.DataFrame(), info

    def batch_fetch_tickers(
        self,
        symbols: List[str],
        period: str = "1y",
        interval: str = "1d",
    ) -> Dict[str, pd.DataFrame]:
        """
        Downloads historical price data for multiple tickers.
        Falls back to individual downloads if batch processing produces ambiguous or incomplete structures.
        """
        if not symbols:
            return {}

        clean_symbols = [s.upper().strip() for s in symbols]
        results: Dict[str, pd.DataFrame] = {}

        try:
            # yf.download with group_by='ticker'
            data = yf.download(
                tickers=clean_symbols,
                period=period,
                interval=interval,
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=True,
            )

            if data is not None and not data.empty:
                if len(clean_symbols) == 1:
                    sym = clean_symbols[0]
                    norm_df = self._normalize_dataframe(data)
                    if not norm_df.empty:
                        results[sym] = norm_df
                else:
                    for sym in clean_symbols:
                        try:
                            if sym in data.columns.levels[0]:
                                sub_df = data[sym].dropna(how="all")
                                norm_df = self._normalize_dataframe(sub_df)
                                if not norm_df.empty:
                                    results[sym] = norm_df
                        except Exception as e:
                            logger.warning(f"Error parsing batch entry for {sym}: {e}")

        except Exception as e:
            logger.warning(f"Batch fetch failed: {e}. Falling back to single ticker downloads.")

        # Fallback for any symbols that failed or were missing from batch
        for sym in clean_symbols:
            if sym not in results or results[sym].empty:
                df, _ = self.fetch_ticker_data(sym, period=period, interval=interval)
                if not df.empty:
                    results[sym] = df

        return results

    def _normalize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensures consistent column names and index handling."""
        if df.empty:
            return df

        df = df.copy()

        # Handle multi-level columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(-1)

        # Standard column mapping
        rename_map = {}
        for col in df.columns:
            str_col = str(col).strip()
            if str_col.lower() in ["open"]:
                rename_map[col] = "Open"
            elif str_col.lower() in ["high"]:
                rename_map[col] = "High"
            elif str_col.lower() in ["low"]:
                rename_map[col] = "Low"
            elif str_col.lower() in ["close"]:
                rename_map[col] = "Close"
            elif str_col.lower() in ["adj close", "adjclose"]:
                rename_map[col] = "Adj Close"
            elif str_col.lower() in ["volume"]:
                rename_map[col] = "Volume"
            elif str_col.lower() in ["dividends"]:
                rename_map[col] = "Dividends"
            elif str_col.lower() in ["stock splits", "stock splits"]:
                rename_map[col] = "Stock Splits"

        df = df.rename(columns=rename_map)

        if "Adj Close" not in df.columns and "Close" in df.columns:
            df["Adj Close"] = df["Close"]

        # Drop rows where Close is NaN
        if "Close" in df.columns:
            df = df.dropna(subset=["Close"])

        return df
