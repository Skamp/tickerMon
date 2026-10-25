import unittest
from unittest.mock import MagicMock

from app.models.forecast import Forecast
from app.services.noise_reduction import NoiseReductionAlgorithm
from app.ui.main_window import MainWindow


class DummyForecast:
    def __init__(self, path_epochs, path_central):
        self.path_epochs = path_epochs
        self.path_central = path_central


class TestForecastFilterExtension(unittest.TestCase):
    def setUp(self):
        self.win = MagicMock()
        self.win.chart_widget = MagicMock()
        self.win._compute_warmup_indicator = lambda ts, prices, fn: fn(prices)
        self.win._chart_timestamps = [100.0 * i for i in range(50)]
        self.win._chart_prices = [10.0 + i * 0.1 for i in range(50)]

    def test_no_forecast_clears_filter_extension(self):
        self.win._active_forecast = None
        self.win._active_noise_algo = NoiseReductionAlgorithm.EMA50
        MainWindow._apply_forecast_filter_extension(self.win)
        self.win.chart_widget.clear_forecast_filter_curve.assert_called_once()

    def test_none_algorithm_clears_filter_extension(self):
        self.win._active_forecast = DummyForecast(
            path_epochs=[5000.0, 5100.0, 5200.0],
            path_central=[15.0, 15.1, 15.2],
        )
        self.win._active_noise_algo = NoiseReductionAlgorithm.NONE
        MainWindow._apply_forecast_filter_extension(self.win)
        self.win.chart_widget.clear_forecast_filter_curve.assert_called_once()

    def test_atr_algorithms_clear_filter_extension(self):
        self.win._active_forecast = DummyForecast(
            path_epochs=[5000.0, 5100.0, 5200.0],
            path_central=[15.0, 15.1, 15.2],
        )
        for algo in (NoiseReductionAlgorithm.ATR2, NoiseReductionAlgorithm.ATR4):
            self.win.chart_widget.reset_mock()
            self.win._active_noise_algo = algo
            MainWindow._apply_forecast_filter_extension(self.win)
            self.win.chart_widget.clear_forecast_filter_curve.assert_called_once()

    def test_ema20_filter_extension_computes_and_sets_curve(self):
        fc_epochs = [5000.0, 5100.0, 5200.0]
        fc_central = [15.0, 15.1, 15.2]
        self.win._active_forecast = DummyForecast(path_epochs=fc_epochs, path_central=fc_central)
        self.win._active_noise_algo = NoiseReductionAlgorithm.EMA20
        self.win.chart_widget._overlay_y = [14.0, 14.5, 14.8]

        MainWindow._apply_forecast_filter_extension(self.win)

        self.win.chart_widget.set_forecast_filter_curve.assert_called_once()
        args, kwargs = self.win.chart_widget.set_forecast_filter_curve.call_args
        ts, prices = args
        self.assertEqual(ts, fc_epochs)
        self.assertEqual(len(prices), len(fc_epochs))
        self.assertEqual(kwargs.get("color"), "#26c6da")
        self.assertAlmostEqual(prices[0], 14.8)
        alpha = 2.0 / 21.0
        expected_p1 = alpha * 15.1 + (1.0 - alpha) * 14.8
        self.assertAlmostEqual(prices[1], expected_p1)

    def test_standard_noise_algorithm_filter_extension(self):
        fc_epochs = [5000.0, 5100.0, 5200.0]
        fc_central = [15.0, 15.1, 15.2]
        self.win._active_forecast = DummyForecast(path_epochs=fc_epochs, path_central=fc_central)
        self.win._active_noise_algo = NoiseReductionAlgorithm.EMA50

        MainWindow._apply_forecast_filter_extension(self.win)

        self.win.chart_widget.set_forecast_filter_curve.assert_called_once()
        args, kwargs = self.win.chart_widget.set_forecast_filter_curve.call_args
        ts, prices = args
        self.assertEqual(ts, fc_epochs)
        self.assertEqual(len(prices), len(fc_epochs))
        self.assertEqual(kwargs.get("color"), "#ffab00")


if __name__ == "__main__":
    unittest.main()
