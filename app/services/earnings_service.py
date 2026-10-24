"""Earnings events: parsing, SQLite caching and expiry-aware refresh.

Data source: Yahoo Finance via ``YahooService.fetch_earnings_dates``
(``yfinance`` ``Ticker.get_earnings_dates``). That table mixes confirmed
historical rows (Reported EPS present) with estimated future rows (Reported
EPS missing); estimated dates are never treated as confirmed.

Events are cached in the local SQLite database with a simple expiry policy
(``EARNINGS_TTL_HOURS``, default 7 days). Chart redraws, range changes and
chart-type switches only read the cache — network refreshes happen on an
explicit ``refresh`` call (driven by a background worker in the UI).
"""

import logging
import math
from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd

from app.database.repositories import MarketDataRepository
from app.models.earnings import EarningsEvent
from app.services.yahoo_service import YahooService

logger = logging.getLogger(__name__)

EARNINGS_TTL_HOURS = 24 * 7


def _opt_float(row, names) -> Optional[float]:
    for name in names:
        if name not in row.index:
            continue
        value = row[name]
        if value is None or (isinstance(value, float) and math.isnan(value)):
            continue
        if pd.isna(value):
            continue
        try:
            result = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(result):
            return result
    return None


def _opt_str(row, names) -> Optional[str]:
    for name in names:
        if name not in row.index:
            continue
        value = row[name]
        if value is None or (isinstance(value, float) and math.isnan(value)):
            continue
        if pd.isna(value):
            continue
        text = str(value).strip()
        if text and text.lower() not in ("nan", "none"):
            return text
    return None


def parse_earnings_dates(df: pd.DataFrame, symbol: str) -> List[EarningsEvent]:
    """Parses a yfinance earnings-dates DataFrame into EarningsEvents.

    Timezone handling: aware timestamps are converted to their exchange-local
    wall-clock time via ``tz_localize(None)``, keeping the same naive
    exchange-local convention as the stored price series so markers align with
    the chart's time axis without day shifts. Rows without Reported EPS are
    marked as estimated; duplicate event dates keep the row carrying reported
    EPS data.
    """
    if df is None or getattr(df, "empty", True):
        return []

    clean_symbol = symbol.upper().strip()
    by_date = {}

    try:
        rows = list(df.iterrows())
    except Exception as e:
        logger.warning(f"Could not iterate earnings dates for {clean_symbol}: {e}")
        return []

    for idx, row in rows:
        try:
            ts = pd.Timestamp(idx)
            if ts.tzinfo is not None:
                ts = ts.tz_localize(None)
            event_date = ts.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            continue

        reported = _opt_float(row, ["Reported EPS", "ReportedEPS", "Actual EPS"])
        event = EarningsEvent(
            symbol=clean_symbol,
            event_date=event_date,
            eps_estimate=_opt_float(row, ["EPS Estimate", "EPS Est.", "Estimate"]),
            reported_eps=reported,
            surprise_pct=_opt_float(row, ["Surprise(%)", "Surprise(%)", "Surprise", "Surprise %"]),
            is_estimated=reported is None,
            quarter=_opt_str(row, ["Quarter", "Period"]),
            timing=_opt_str(row, ["Timing", "Time", "Announcement Time"]),
        )

        existing = by_date.get(event_date)
        if existing is None or (existing.is_estimated and not event.is_estimated):
            by_date[event_date] = event

    return sorted(by_date.values(), key=lambda e: e.event_date)


class EarningsService:
    def __init__(self, yahoo_service: YahooService, repo: MarketDataRepository):
        self.yahoo_service = yahoo_service
        self.repo = repo

    def get_events(self, symbol: str) -> List[EarningsEvent]:
        """Returns the cached earnings events for a symbol (no network)."""
        return self.repo.get_earnings(symbol)

    def is_stale(self, symbol: str) -> bool:
        """True when the cached earnings data is missing or older than the TTL."""
        fetched_at = self.repo.get_earnings_fetched_at(symbol)
        if not fetched_at:
            return True
        try:
            fetched = datetime.strptime(fetched_at, "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return True
        return datetime.now() - fetched > timedelta(hours=EARNINGS_TTL_HOURS)

    def refresh(self, symbol: str) -> List[EarningsEvent]:
        """Fetches fresh earnings dates from Yahoo Finance and replaces the cache.

        On a failed fetch the existing cache is left untouched and the last
        successful fetch time is not updated, so the data stays marked stale.
        """
        clean_symbol = symbol.upper().strip()
        try:
            df = self.yahoo_service.fetch_earnings_dates(clean_symbol)
        except Exception as e:
            logger.warning(f"Earnings fetch failed for {clean_symbol}: {e}")
            return self.repo.get_earnings(clean_symbol)

        events = parse_earnings_dates(df, clean_symbol)
        try:
            self.repo.replace_earnings(clean_symbol, events)
            self.repo.set_earnings_fetched_at(
                clean_symbol, datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        except Exception as e:
            logger.warning(f"Could not cache earnings for {clean_symbol}: {e}")
        return events
