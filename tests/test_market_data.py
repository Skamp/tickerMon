import gc
import tempfile
import unittest
from unittest.mock import MagicMock
from pathlib import Path
import pandas as pd

from app.database.database import Database
from app.database.repositories import MarketDataRepository
from app.services.market_data_service import (
    MarketDataService,
    classify_price_series,
    count_trend_buckets,
    is_swing_series,
)
from app.services.sync_service import SyncService
from app.services.yahoo_service import YahooService
from app.models.ticker import TickerConfig
from app.models.time_range import TimeRange
from app.models.trend import TrendBucket


class TestMarketData(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "data" / "test_market_data.db"
        self.db = Database(self.db_path)
        self.repo = MarketDataRepository(self.db)
        self.market_data_service = MarketDataService(self.repo)

    def tearDown(self):
        gc.collect()
        self.temp_dir.cleanup()

    def test_empty_chart_data(self):
        ts, prices, labels = self.market_data_service.get_chart_data("AAPL", TimeRange.ONE_YEAR)
        self.assertEqual(ts, [])
        self.assertEqual(prices, [])
        self.assertEqual(labels, [])

    def test_summary_calculation(self):
        dates = pd.date_range("2026-01-01", periods=2, freq="D")
        df = pd.DataFrame({
            "Open": [100.0, 105.0],
            "High": [105.0, 110.0],
            "Low": [99.0, 104.0],
            "Close": [100.0, 110.0],
            "Adj Close": [100.0, 110.0],
            "Volume": [1000, 1500],
        }, index=dates)

        self.repo.upsert_price_data("NVDA", df)
        cfg = TickerConfig("NVDA", "NVIDIA Corporation", True)

        summary = self.market_data_service.get_ticker_summary(cfg)
        self.assertEqual(summary.current_price, 110.0)
        self.assertEqual(summary.price_change, 10.0)
        self.assertEqual(summary.pct_change, 10.0)

    def test_mocked_sync_service(self):
        mock_yahoo = MagicMock(spec=YahooService)
        dates = pd.date_range("2026-01-01", periods=3, freq="D")
        df_fake = pd.DataFrame({
            "Open": [200.0, 202.0, 204.0],
            "High": [205.0, 206.0, 208.0],
            "Low": [199.0, 201.0, 203.0],
            "Close": [202.0, 205.0, 207.0],
            "Adj Close": [202.0, 205.0, 207.0],
            "Volume": [5000, 5500, 6000],
        }, index=dates)

        mock_yahoo.fetch_ticker_data.return_value = (df_fake, {
            "symbol": "GOOGL",
            "company_name": "Alphabet Inc.",
            "currency": "USD",
            "exchange": "NASDAQ",
        })

        sync = SyncService(mock_yahoo, self.repo)
        ok, msg, count = sync.sync_ticker("GOOGL")

        self.assertTrue(ok)
        self.assertEqual(count, 3)

        points = self.repo.get_prices("GOOGL")
        self.assertEqual(len(points), 3)

    def test_classify_price_series(self):
        self.assertEqual(classify_price_series([]), TrendBucket.UNSURE)
        self.assertEqual(classify_price_series([100.0]), TrendBucket.UNSURE)
        self.assertEqual(classify_price_series([100.0, 105.0]), TrendBucket.RISE)
        self.assertEqual(classify_price_series([100.0, 102.0]), TrendBucket.RISE)
        self.assertEqual(classify_price_series([100.0, 98.0]), TrendBucket.DOWN)
        self.assertEqual(classify_price_series([100.0, 98.1]), TrendBucket.LATERAL)
        self.assertEqual(classify_price_series([100.0, 101.9]), TrendBucket.LATERAL)

    def test_count_trend_buckets(self):
        trends = {
            "AAA": TrendBucket.RISE,
            "BBB": TrendBucket.RISE,
            "CCC": TrendBucket.DOWN,
            "DDD": TrendBucket.UNSURE,
        }
        counts = count_trend_buckets(trends)
        self.assertEqual(counts[TrendBucket.RISE], 2)
        self.assertEqual(counts[TrendBucket.DOWN], 1)
        self.assertEqual(counts[TrendBucket.LATERAL], 0)
        self.assertEqual(counts[TrendBucket.UNSURE], 1)

    def test_is_swing_series(self):
        self.assertFalse(is_swing_series([]))
        self.assertFalse(is_swing_series([100.0]))
        self.assertTrue(is_swing_series([100.0, 110.0]))
        self.assertFalse(is_swing_series([100.0, 109.9]))
        self.assertTrue(is_swing_series([110.0, 100.0]))
        self.assertFalse(is_swing_series([100.0, 105.0, 100.0]))
        self.assertTrue(is_swing_series([110.0, 99.0, 110.0]))

    def _seed_series(self, symbol: str, start_price: float, end_price: float, end_days_ago: int = 0, periods: int = 30) -> None:
        end_date = pd.Timestamp.now().normalize() - pd.Timedelta(days=end_days_ago)
        dates = pd.date_range(end=end_date, periods=periods, freq="D")
        closes = [start_price + (end_price - start_price) * i / (periods - 1) for i in range(periods)]
        df = pd.DataFrame({
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1000] * periods,
        }, index=dates)
        self.repo.upsert_price_data(symbol, df)

    def test_get_trend_buckets(self):
        self._seed_series("AAA", 100.0, 130.0)
        self._seed_series("BBB", 100.0, 60.0)
        self._seed_series("CCC", 100.0, 100.0)
        self._seed_series("EEE", 100.0, 130.0, end_days_ago=70)

        configs = [
            TickerConfig("AAA", "Rising", True),
            TickerConfig("BBB", "Falling", True),
            TickerConfig("CCC", "Flat", True),
            TickerConfig("DDD", "No Data", True),
            TickerConfig("EEE", "Old Data", True),
        ]

        buckets = self.market_data_service.get_trend_buckets(configs, TimeRange.ONE_YEAR)
        self.assertEqual(buckets["AAA"], TrendBucket.RISE)
        self.assertEqual(buckets["BBB"], TrendBucket.DOWN)
        self.assertEqual(buckets["CCC"], TrendBucket.LATERAL)
        self.assertEqual(buckets["DDD"], TrendBucket.UNSURE)
        self.assertEqual(buckets["EEE"], TrendBucket.RISE)

        month_buckets = self.market_data_service.get_trend_buckets(configs, TimeRange.ONE_MONTH)
        self.assertEqual(month_buckets["EEE"], TrendBucket.UNSURE)
        self.assertEqual(month_buckets["AAA"], TrendBucket.RISE)

    def test_get_swing_symbols(self):
        self._seed_series("SWG", 100.0, 140.0)
        self._seed_series("FLAT", 100.0, 100.0)
        self._seed_series("MILD", 100.0, 105.0)

        configs = [
            TickerConfig("SWG", "Wide", True),
            TickerConfig("FLAT", "Flat", True),
            TickerConfig("MILD", "Mild", True),
            TickerConfig("NONE", "No Data", True),
        ]

        swings = self.market_data_service.get_swing_symbols(configs, TimeRange.ONE_YEAR)
        self.assertEqual(swings, {"SWG"})

        buckets = self.market_data_service.get_trend_buckets(configs, TimeRange.ONE_YEAR)
        self.assertEqual(buckets["SWG"], TrendBucket.RISE, "swing overlaps with trend buckets")


if __name__ == "__main__":
    unittest.main()
