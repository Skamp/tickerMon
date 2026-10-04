import tempfile
import unittest
from pathlib import Path
from app.config.config_manager import ConfigManager
from app.services.ticker_service import TickerService
from app.services.noise_reduction import NoiseReductionAlgorithm
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

    def test_filter_settings_default_all_enabled(self):
        self.assertIsNone(self.config_manager.load_enabled_filters())

        service = TickerService(self.config_manager)
        expected = [algorithm.value for algorithm in NoiseReductionAlgorithm if algorithm != NoiseReductionAlgorithm.NONE]
        self.assertEqual(service.get_enabled_filters(), expected)

    def test_filter_settings_roundtrip(self):
        service = TickerService(self.config_manager)
        enabled = [NoiseReductionAlgorithm.EMA.value, NoiseReductionAlgorithm.KALMAN.value]
        self.assertTrue(service.set_enabled_filters(enabled))

        reloaded = TickerService(self.config_manager)
        self.assertEqual(reloaded.get_enabled_filters(), enabled)

    def test_filter_settings_survive_ticker_save(self):
        service = TickerService(self.config_manager)
        enabled = [NoiseReductionAlgorithm.EMA50.value, NoiseReductionAlgorithm.RPD1.value]
        service.set_enabled_filters(enabled)

        ok, _ = service.add_ticker("IBM", "International Business Machines")
        self.assertTrue(ok)

        self.assertEqual(self.config_manager.load_enabled_filters(), enabled)

        tickers, _, _ = self.config_manager.load_config()
        self.assertTrue(any(t.symbol == "IBM" for t in tickers))

    def test_filter_settings_ignores_unknown_values(self):
        service = TickerService(self.config_manager)
        service.set_enabled_filters(["NOT A REAL FILTER", NoiseReductionAlgorithm.HMA.value])

        reloaded = TickerService(self.config_manager)
        self.assertEqual(reloaded.get_enabled_filters(), [NoiseReductionAlgorithm.HMA.value])

    def test_filter_settings_empty_list_disables_all(self):
        service = TickerService(self.config_manager)
        service.set_enabled_filters([])

        reloaded = TickerService(self.config_manager)
        self.assertEqual(reloaded.get_enabled_filters(), [])


if __name__ == "__main__":
    unittest.main()
