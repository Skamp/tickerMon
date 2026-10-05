import tempfile
import unittest
from pathlib import Path
from app.config.config_manager import ConfigManager
from app.services.ticker_service import TickerService
from app.services.noise_reduction import NoiseReductionAlgorithm
from app.services.swing_detection import SwingAlgorithm, SwingRangeMode, default_swing_params
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

    def test_swing_settings_default_all_enabled(self):
        self.assertIsNone(self.config_manager.load_enabled_swing_algorithms())

        service = TickerService(self.config_manager)
        expected = [algorithm.value for algorithm in SwingAlgorithm]
        self.assertEqual(service.get_enabled_swing_algorithms(), expected)

    def test_swing_settings_roundtrip(self):
        service = TickerService(self.config_manager)
        enabled = [SwingAlgorithm.RANGE.value, SwingAlgorithm.ZIGZAG.value, SwingAlgorithm.RSI.value]
        self.assertTrue(service.set_enabled_swing_algorithms(enabled))

        reloaded = TickerService(self.config_manager)
        self.assertEqual(reloaded.get_enabled_swing_algorithms(), enabled)

    def test_swing_settings_survive_ticker_save(self):
        service = TickerService(self.config_manager)
        enabled = [SwingAlgorithm.MACD.value, SwingAlgorithm.HMM.value]
        service.set_enabled_swing_algorithms(enabled)

        ok, _ = service.add_ticker("IBM", "International Business Machines")
        self.assertTrue(ok)

        self.assertEqual(self.config_manager.load_enabled_swing_algorithms(), enabled)

        tickers, _, _ = self.config_manager.load_config()
        self.assertTrue(any(t.symbol == "IBM" for t in tickers))

    def test_swing_settings_ignores_unknown_values(self):
        service = TickerService(self.config_manager)
        service.set_enabled_swing_algorithms(["NOT A REAL ALGORITHM", SwingAlgorithm.ZIGZAG.value])

        reloaded = TickerService(self.config_manager)
        self.assertEqual(reloaded.get_enabled_swing_algorithms(), [SwingAlgorithm.ZIGZAG.value])

    def test_swing_settings_empty_list_falls_back_to_range(self):
        service = TickerService(self.config_manager)
        service.set_enabled_swing_algorithms([])

        reloaded = TickerService(self.config_manager)
        self.assertEqual(reloaded.get_enabled_swing_algorithms(), [SwingAlgorithm.RANGE.value])

    def test_swing_params_defaults_when_unset(self):
        service = TickerService(self.config_manager)
        self.assertIsNone(self.config_manager.load_swing_params())

        for algorithm in SwingAlgorithm:
            self.assertEqual(service.get_swing_params(algorithm), default_swing_params(algorithm))

    def test_swing_params_roundtrip(self):
        service = TickerService(self.config_manager)
        params = {
            SwingAlgorithm.RANGE.value: {"min_swing_pct": 12.5},
            SwingAlgorithm.RSI.value: {"min_swing_pct": 8.0, "period": 21.0},
            SwingAlgorithm.ZIGZAG.value: {"threshold_pct": 7.5},
        }
        self.assertTrue(service.set_swing_params(params))

        reloaded = TickerService(self.config_manager)
        self.assertEqual(reloaded.get_swing_params(SwingAlgorithm.RANGE)["min_swing_pct"], 12.5)
        self.assertEqual(reloaded.get_swing_params(SwingAlgorithm.RSI)["period"], 21.0)
        self.assertEqual(reloaded.get_swing_params(SwingAlgorithm.ZIGZAG)["threshold_pct"], 7.5)

        untouched = reloaded.get_swing_params(SwingAlgorithm.HMM)
        self.assertEqual(untouched, default_swing_params(SwingAlgorithm.HMM))

    def test_swing_params_normalize_on_save(self):
        service = TickerService(self.config_manager)
        params = {
            SwingAlgorithm.SUPERTREND.value: {"min_swing_pct": -5.0, "period": 9999.0, "mult": 100.0},
            SwingAlgorithm.MACD.value: {"fast": 50.0, "slow": 5.0},
        }
        self.assertTrue(service.set_swing_params(params))

        reloaded = TickerService(self.config_manager)
        supertrend = reloaded.get_swing_params(SwingAlgorithm.SUPERTREND)
        self.assertEqual(supertrend["min_swing_pct"], 0.1)
        self.assertEqual(supertrend["period"], 100.0)
        self.assertEqual(supertrend["mult"], 10.0)

        macd = reloaded.get_swing_params(SwingAlgorithm.MACD)
        self.assertLess(macd["fast"], macd["slow"])

    def test_swing_params_survive_ticker_save(self):
        service = TickerService(self.config_manager)
        service.set_swing_params({SwingAlgorithm.RSI.value: {"min_swing_pct": 15.0}})

        ok, _ = service.add_ticker("ORCL", "Oracle Corporation")
        self.assertTrue(ok)

        reloaded = TickerService(self.config_manager)
        self.assertEqual(reloaded.get_swing_params(SwingAlgorithm.RSI)["min_swing_pct"], 15.0)

    def test_get_all_swing_params_covers_all_algorithms(self):
        service = TickerService(self.config_manager)
        all_params = service.get_all_swing_params()
        self.assertEqual(set(all_params.keys()), {algorithm.value for algorithm in SwingAlgorithm})
        for value, params in all_params.items():
            self.assertIn("min_swing_pct", params, value)

    def test_swing_range_settings_default_when_unset(self):
        self.assertIsNone(self.config_manager.load_swing_range_settings())

        service = TickerService(self.config_manager)
        settings = service.get_swing_range_settings()
        self.assertEqual(settings["mode"], SwingRangeMode.MIN_DURATION.value)
        self.assertEqual(settings["value"], 0)
        self.assertEqual(settings["value_max"], 0)
        self.assertEqual(settings["unit"], "weeks")

    def test_swing_range_settings_forces_weeks_unit(self):
        service = TickerService(self.config_manager)
        settings = {
            "mode": SwingRangeMode.LOOKBACK.value,
            "value": 6,
            "value_max": 0,
            "unit": "months",
        }
        self.assertTrue(service.set_swing_range_settings(settings))

        reloaded = TickerService(self.config_manager)
        stored = reloaded.get_swing_range_settings()
        self.assertEqual(stored["mode"], SwingRangeMode.LOOKBACK.value)
        self.assertEqual(stored["value"], 6)
        self.assertEqual(stored["unit"], "weeks")

    def test_swing_range_settings_normalizes_garbage(self):
        service = TickerService(self.config_manager)
        service.set_swing_range_settings({
            "mode": "Not A Mode",
            "value": -50,
            "value_max": 9999,
            "unit": "centuries",
        })

        settings = service.get_swing_range_settings()
        self.assertEqual(settings["mode"], SwingRangeMode.MIN_DURATION.value)
        self.assertEqual(settings["value"], 0)
        self.assertEqual(settings["value_max"], 520)
        self.assertEqual(settings["unit"], "weeks")

    def test_swing_range_window_swaps_inverted_bounds(self):
        service = TickerService(self.config_manager)
        service.set_swing_range_settings({
            "mode": SwingRangeMode.DURATION_WINDOW.value,
            "value": 12,
            "value_max": 4,
            "unit": "weeks",
        })

        settings = service.get_swing_range_settings()
        self.assertEqual(settings["value"], 4)
        self.assertEqual(settings["value_max"], 12)

    def test_swing_range_settings_survive_ticker_save(self):
        service = TickerService(self.config_manager)
        settings = {
            "mode": SwingRangeMode.MAX_DURATION.value,
            "value": 3,
            "value_max": 0,
            "unit": "weeks",
        }
        service.set_swing_range_settings(settings)

        ok, _ = service.add_ticker("IBM", "International Business Machines")
        self.assertTrue(ok)

        reloaded = TickerService(self.config_manager)
        self.assertEqual(reloaded.get_swing_range_settings(), settings)


if __name__ == "__main__":
    unittest.main()
