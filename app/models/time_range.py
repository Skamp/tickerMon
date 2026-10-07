from enum import Enum
from datetime import datetime, timedelta
from typing import Tuple, Optional


class TimeRange(Enum):
    ONE_WEEK = "1W"
    TWO_WEEKS = "2W"
    THREE_WEEKS = "3W"
    ONE_MONTH = "1M"
    SIX_MONTHS = "6M"
    ONE_YEAR = "1Y"
    FIVE_YEARS = "5Y"

    @classmethod
    def from_str(cls, val: str) -> "TimeRange":
        for item in cls:
            if item.value == val:
                return item
        return cls.ONE_YEAR

    @property
    def display_name(self) -> str:
        names = {
            TimeRange.ONE_WEEK: "1 Week",
            TimeRange.TWO_WEEKS: "2 Weeks",
            TimeRange.THREE_WEEKS: "3 Weeks",
            TimeRange.ONE_MONTH: "1 Month",
            TimeRange.SIX_MONTHS: "6 Months",
            TimeRange.ONE_YEAR: "1 Year",
            TimeRange.FIVE_YEARS: "5 Years",
        }
        return names.get(self, "1 Year")

    def get_start_date(self, ref_date: Optional[datetime] = None) -> datetime:
        ref = ref_date or datetime.now()
        if self == TimeRange.ONE_WEEK:
            return ref - timedelta(days=7)
        elif self == TimeRange.TWO_WEEKS:
            return ref - timedelta(days=14)
        elif self == TimeRange.THREE_WEEKS:
            return ref - timedelta(days=21)
        elif self == TimeRange.ONE_MONTH:
            return ref - timedelta(days=30)
        elif self == TimeRange.SIX_MONTHS:
            return ref - timedelta(days=180)
        elif self == TimeRange.ONE_YEAR:
            return ref - timedelta(days=365)
        elif self == TimeRange.FIVE_YEARS:
            return ref - timedelta(days=1825)
        return ref - timedelta(days=365)

    def yfinance_params(self) -> Tuple[str, str]:
        """Returns tuple of (period, interval) suitable for yfinance download."""
        if self == TimeRange.ONE_WEEK:
            return ("5d", "15m")
        elif self == TimeRange.TWO_WEEKS:
            return ("2wk", "1d")
        elif self == TimeRange.THREE_WEEKS:
            return ("3wk", "1d")
        elif self == TimeRange.ONE_MONTH:
            return ("1mo", "1d")
        elif self == TimeRange.SIX_MONTHS:
            return ("6mo", "1d")
        elif self == TimeRange.ONE_YEAR:
            return ("1y", "1d")
        elif self == TimeRange.FIVE_YEARS:
            return ("5y", "1d")
        return ("1y", "1d")
