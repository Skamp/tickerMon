import tempfile
import unittest
from pathlib import Path
from app.config.config_manager import ConfigManager
from app.services.ticker_service import TickerService
from app.models.ticker import TickerConfig


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "config" / "tickers.json"
        self.config_manager = ConfigManager(self.config_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_load_default_config(self):
        tickers, sel_ticker, sel_range = self.config_manager.load_config()
        self.assertTrue(len(tickers) > 0)
        self.assertEqual(sel_ticker, "AAPL")
        self.assertEqual(sel_range, "1Y")

    def test_add_and_remove_ticker(self):
        service = TickerService(self.config_manager)
        ok, msg = service.add_ticker("SAP.DE", "SAP SE")
        self.assertTrue(ok)

        tickers = service.get_all_tickers()
        self.assertTrue(any(t.symbol == "SAP.DE" for t in tickers))

        # Try duplicate
        ok_dup, _ = service.add_ticker("SAP.DE", "SAP SE")
        self.assertFalse(ok_dup)

        # Remove
        removed = service.delete_ticker("SAP.DE")
        self.assertTrue(removed)
        self.assertFalse(any(t.symbol == "SAP.DE" for t in service.get_all_tickers()))

    def test_validate_symbol(self):
        service = TickerService(self.config_manager)
        self.assertTrue(service.validate_ticker_symbol("AAPL"))
        self.assertTrue(service.validate_ticker_symbol("SAP.DE"))
        self.assertTrue(service.validate_ticker_symbol("^GSPC"))
        self.assertTrue(service.validate_ticker_symbol("EURUSD=X"))
        self.assertFalse(service.validate_ticker_symbol("INVALID SYMBOL WITH SPACES"))


if __name__ == "__main__":
    unittest.main()
