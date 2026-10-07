import unittest
from datetime import datetime, timedelta
from app.models.time_range import TimeRange


class TestTimeRanges(unittest.TestCase):
    def test_enum_parsing(self):
        self.assertEqual(TimeRange.from_str("1W"), TimeRange.ONE_WEEK)
        self.assertEqual(TimeRange.from_str("2W"), TimeRange.TWO_WEEKS)
        self.assertEqual(TimeRange.from_str("3W"), TimeRange.THREE_WEEKS)
        self.assertEqual(TimeRange.from_str("1M"), TimeRange.ONE_MONTH)
        self.assertEqual(TimeRange.from_str("6M"), TimeRange.SIX_MONTHS)
        self.assertEqual(TimeRange.from_str("1Y"), TimeRange.ONE_YEAR)
        self.assertEqual(TimeRange.from_str("5Y"), TimeRange.FIVE_YEARS)
        self.assertEqual(TimeRange.from_str("UNKNOWN"), TimeRange.ONE_YEAR)

    def test_start_date_calculations(self):
        ref = datetime(2026, 10, 1)
        start_1w = TimeRange.ONE_WEEK.get_start_date(ref)
        self.assertEqual(start_1w, ref - timedelta(days=7))

        start_2w = TimeRange.TWO_WEEKS.get_start_date(ref)
        self.assertEqual(start_2w, ref - timedelta(days=14))

        start_3w = TimeRange.THREE_WEEKS.get_start_date(ref)
        self.assertEqual(start_3w, ref - timedelta(days=21))

        start_1y = TimeRange.ONE_YEAR.get_start_date(ref)
        self.assertEqual(start_1y, ref - timedelta(days=365))

        start_5y = TimeRange.FIVE_YEARS.get_start_date(ref)
        self.assertEqual(start_5y, ref - timedelta(days=1825))

    def test_yfinance_params(self):
        period, interval = TimeRange.ONE_WEEK.yfinance_params()
        self.assertEqual(period, "5d")
        self.assertEqual(interval, "15m")

        period_2w, interval_2w = TimeRange.TWO_WEEKS.yfinance_params()
        self.assertEqual(period_2w, "2wk")
        self.assertEqual(interval_2w, "1d")

        period_3w, interval_3w = TimeRange.THREE_WEEKS.yfinance_params()
        self.assertEqual(period_3w, "3wk")
        self.assertEqual(interval_3w, "1d")

        period_1y, interval_1y = TimeRange.ONE_YEAR.yfinance_params()
        self.assertEqual(period_1y, "1y")
        self.assertEqual(interval_1y, "1d")

        period_5y, interval_5y = TimeRange.FIVE_YEARS.yfinance_params()
        self.assertEqual(period_5y, "5y")
        self.assertEqual(interval_5y, "1d")

    def test_display_names(self):
        self.assertEqual(TimeRange.TWO_WEEKS.display_name, "2 Weeks")
        self.assertEqual(TimeRange.THREE_WEEKS.display_name, "3 Weeks")
        self.assertEqual(TimeRange.FIVE_YEARS.display_name, "5 Years")


if __name__ == "__main__":
    unittest.main()
