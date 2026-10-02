import gc
import tempfile
import unittest
from pathlib import Path
import pandas as pd

from app.database.database import Database
from app.database.repositories import MarketDataRepository


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "data" / "test_market_data.db"
        self.db = Database(self.db_path)
        self.repo = MarketDataRepository(self.db)

    def tearDown(self):
        gc.collect()
        self.temp_dir.cleanup()

    def test_schema_initialization(self):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        self.assertIn("prices", tables)
        self.assertIn("ticker_metadata", tables)

    def test_upsert_and_query_prices(self):
        dates = pd.date_range("2026-01-01", periods=5, freq="D")
        df = pd.DataFrame({
            "Open": [150.0, 152.0, 151.0, 153.0, 155.0],
            "High": [153.0, 154.0, 153.0, 156.0, 158.0],
            "Low": [149.0, 150.0, 149.5, 152.0, 154.0],
            "Close": [152.0, 151.0, 153.0, 155.0, 157.0],
            "Adj Close": [152.0, 151.0, 153.0, 155.0, 157.0],
            "Volume": [1000, 1200, 1100, 1300, 1500],
        }, index=dates)

        count = self.repo.upsert_price_data("AAPL", df)
        self.assertEqual(count, 5)

        # Query back
        points = self.repo.get_prices("AAPL")
        self.assertEqual(len(points), 5)
        self.assertEqual(points[0].close, 152.0)
        self.assertEqual(points[-1].close, 157.0)

        # Test duplicate prevention / update on conflict
        df_update = pd.DataFrame({
            "Open": [150.0],
            "High": [155.0],
            "Low": [149.0],
            "Close": [154.0],
            "Adj Close": [154.0],
            "Volume": [2000],
        }, index=[dates[0]])

        self.repo.upsert_price_data("AAPL", df_update)
        updated_points = self.repo.get_prices("AAPL")
        self.assertEqual(len(updated_points), 5)  # Should still be 5
        self.assertEqual(updated_points[0].close, 154.0)

    def test_metadata_tracking(self):
        self.repo.update_ticker_metadata(
            symbol="MSFT",
            company_name="Microsoft Corporation",
            currency="USD",
            exchange="NASDAQ",
            status="OK",
        )

        meta = self.repo.get_ticker_metadata("MSFT")
        self.assertIsNotNone(meta)
        self.assertEqual(meta["company_name"], "Microsoft Corporation")
        self.assertEqual(meta["status"], "OK")


if __name__ == "__main__":
    unittest.main()
