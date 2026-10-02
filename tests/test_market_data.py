import gc
import tempfile
import unittest
from unittest.mock import MagicMock
from pathlib import Path
import pandas as pd

from app.database.database import Database
from app.database.repositories import MarketDataRepository
from app.services.market_data_service import MarketDataService
from app.services.sync_service import SyncService
from app.services.yahoo_service import YahooService
from app.models.ticker import TickerConfig
from app.models.time_range import TimeRange


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


if __name__ == "__main__":
    unittest.main()
