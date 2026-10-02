import unittest
from datetime import datetime, timedelta
from app.models.time_range import TimeRange


class TestTimeRanges(unittest.TestCase):
    def test_enum_parsing(self):
        self.assertEqual(TimeRange.from_str("1W"), TimeRange.ONE_WEEK)
        self.assertEqual(TimeRange.from_str("1M"), TimeRange.ONE_MONTH)
        self.assertEqual(TimeRange.from_str("6M"), TimeRange.SIX_MONTHS)
        self.assertEqual(TimeRange.from_str("1Y"), TimeRange.ONE_YEAR)
        self.assertEqual(TimeRange.from_str("UNKNOWN"), TimeRange.ONE_YEAR)

    def test_start_date_calculations(self):
        ref = datetime(2026, 10, 1)
        start_1w = TimeRange.ONE_WEEK.get_start_date(ref)
        self.assertEqual(start_1w, ref - timedelta(days=7))

        start_1y = TimeRange.ONE_YEAR.get_start_date(ref)
        self.assertEqual(start_1y, ref - timedelta(days=365))

    def test_yfinance_params(self):
        period, interval = TimeRange.ONE_WEEK.yfinance_params()
        self.assertEqual(period, "5d")
        self.assertEqual(interval, "15m")

        period_1y, interval_1y = TimeRange.ONE_YEAR.yfinance_params()
        self.assertEqual(period_1y, "1y")
        self.assertEqual(interval_1y, "1d")


if __name__ == "__main__":
    unittest.main()
