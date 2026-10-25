import math
import unittest
from datetime import date

from app.models.forecast import (
    FORECAST_ANNOTATION_DEFAULT_ANCHOR,
    FORECAST_DRAG_HANDLE,
    Forecast,
    ForecastHorizon,
    format_forecast_annotation_html,
    normalize_forecast_annotation_anchor,
    rebuild_projection,
)
from app.services.forecast_engine import (
    BAND_Z,
    FORECAST_MODEL_VERSION,
    MIN_SESSIONS,
    SESSIONS_PER_MONTH,
    ForecastError,
    add_months,
    generate_forecast,
)
from app.services.noise_reduction import NoiseReductionAlgorithm
from app.services.swing_detection import SwingAlgorithm


def make_series(n=300, start_price=100.0, drift=0.0008, base_epoch=1_700_000_000.0):
    """Deterministic synthetic daily series: exponential drift + sine wave."""
    timestamps = [base_epoch + i * 86400.0 for i in range(n)]
    closes = [
        start_price * math.exp(drift * i) * (1.0 + 0.02 * math.sin(i / 7.0))
        for i in range(n)
    ]
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    return timestamps, closes, highs, lows


class TestAddMonths(unittest.TestCase):
    def test_normal_month(self):
        self.assertEqual(add_months(date(2026, 1, 15), 1), date(2026, 2, 15))

    def test_year_rollover(self):
        self.assertEqual(add_months(date(2026, 11, 10), 3), date(2027, 2, 10))

    def test_month_end_clamp(self):
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))

    def test_three_months(self):
        self.assertEqual(add_months(date(2026, 6, 15), 3), date(2026, 9, 15))


class TestGenerateForecast(unittest.TestCase):
    def test_off_horizon_rejected(self):
        ts, closes, _, _ = make_series()
        with self.assertRaises(ForecastError):
            generate_forecast("TEST", ts, closes, horizon=ForecastHorizon.OFF)

    def test_insufficient_history_rejected(self):
        ts, closes, _, _ = make_series(n=MIN_SESSIONS - 1)
        with self.assertRaises(ForecastError):
            generate_forecast("TEST", ts, closes, horizon=ForecastHorizon.ONE_MONTH)

    def test_deterministic_output(self):
        ts, closes, highs, lows = make_series()
        kwargs = dict(
            highs=highs,
            lows=lows,
            horizon=ForecastHorizon.ONE_MONTH,
            filter_algorithm=NoiseReductionAlgorithm.EMA20,
            swing_algorithm=SwingAlgorithm.RANGE,
            swing_params={"min_swing_pct": 10.0},
            generated_at="2026-10-24 12:00:00",
        )
        first = generate_forecast("TEST", ts, closes, **kwargs)
        second = generate_forecast("TEST", ts, closes, **kwargs)
        self.assertEqual(first.central_estimate, second.central_estimate)
        self.assertEqual(first.lower_estimate, second.lower_estimate)
        self.assertEqual(first.upper_estimate, second.upper_estimate)
        self.assertEqual(first.expected_change_pct, second.expected_change_pct)
        self.assertEqual(first.path_central, second.path_central)
        self.assertEqual(first.model_version, FORECAST_MODEL_VERSION)

    def test_no_look_ahead_truncation_prefix_consistent(self):
        """A forecast on a truncated series only sees the prefix (deterministic)."""
        ts, closes, highs, lows = make_series(n=300)
        cutoff = 200
        first = generate_forecast(
            "TEST", ts[:cutoff], closes[:cutoff],
            highs=highs[:cutoff], lows=lows[:cutoff],
            horizon=ForecastHorizon.ONE_MONTH,
            generated_at="2026-01-01 00:00:00",
        )
        second = generate_forecast(
            "TEST", ts[:cutoff], closes[:cutoff],
            highs=highs[:cutoff], lows=lows[:cutoff],
            horizon=ForecastHorizon.ONE_MONTH,
            generated_at="2026-01-01 00:00:00",
        )
        self.assertEqual(first.central_estimate, second.central_estimate)
        self.assertEqual(first.reference_close, closes[cutoff - 1])

    def test_target_date_is_calendar_month_ahead(self):
        ts, closes, _, _ = make_series(n=300)
        forecast = generate_forecast("TEST", ts, closes, horizon=ForecastHorizon.ONE_MONTH)
        ref = date.fromisoformat(forecast.reference_date)
        target = date.fromisoformat(forecast.target_date)
        self.assertEqual(target.month, (ref.month % 12) + 1)
        self.assertEqual(target.day, ref.day)

    def test_horizon_session_counts(self):
        ts, closes, _, _ = make_series()
        one = generate_forecast("TEST", ts, closes, horizon=ForecastHorizon.ONE_MONTH)
        three = generate_forecast("TEST", ts, closes, horizon=ForecastHorizon.THREE_MONTHS)
        self.assertEqual(len(one.path_epochs) - 1, SESSIONS_PER_MONTH)
        self.assertEqual(len(three.path_epochs) - 1, 3 * SESSIONS_PER_MONTH)

    def test_uncertainty_band_widens_with_horizon(self):
        ts, closes, _, _ = make_series()
        forecast = generate_forecast("TEST", ts, closes, horizon=ForecastHorizon.THREE_MONTHS)
        widths = [
            hi - lo
            for hi, lo in zip(forecast.path_upper, forecast.path_lower)
        ]
        self.assertTrue(all(widths[i] <= widths[i + 1] + 1e-9 for i in range(len(widths) - 1)))
        self.assertGreater(widths[-1], widths[1])

    def test_band_z_applied_at_target(self):
        ts, closes, _, _ = make_series()
        forecast = generate_forecast("TEST", ts, closes, horizon=ForecastHorizon.ONE_MONTH)
        sigma = forecast.input_snapshot["sigma_daily"]
        n = forecast.input_snapshot["n_sessions"]
        expected_ratio = math.exp(BAND_Z * sigma * math.sqrt(n))
        ratio = forecast.upper_estimate / forecast.central_estimate
        self.assertAlmostEqual(ratio, expected_ratio, places=9)
        inverse = forecast.lower_estimate / forecast.central_estimate
        self.assertAlmostEqual(inverse, 1.0 / expected_ratio, places=9)

    def test_reference_close_is_last_valid_close(self):
        ts, closes, _, _ = make_series()
        forecast = generate_forecast("TEST", ts, closes, horizon=ForecastHorizon.ONE_MONTH)
        self.assertEqual(forecast.reference_close, closes[-1])

    def test_bias_is_valid_enum_value(self):
        ts, closes, _, _ = make_series()
        forecast = generate_forecast("TEST", ts, closes, horizon=ForecastHorizon.ONE_MONTH)
        self.assertIn(forecast.directional_bias, ("Bullish", "Bearish", "Neutral"))

    def test_uptrend_series_tends_bullish(self):
        ts, closes, _, _ = make_series(n=300, drift=0.004)
        forecast = generate_forecast(
            "TEST", ts, closes, horizon=ForecastHorizon.ONE_MONTH,
            swing_params={"min_swing_pct": 5.0},
        )
        self.assertEqual(forecast.directional_bias, "Bullish")
        self.assertGreater(forecast.central_estimate, forecast.reference_close)

    def test_downtrend_series_tends_bearish(self):
        ts, closes, _, _ = make_series(n=300, drift=-0.004)
        forecast = generate_forecast(
            "TEST", ts, closes, horizon=ForecastHorizon.ONE_MONTH,
            swing_params={"min_swing_pct": 5.0},
        )
        self.assertEqual(forecast.directional_bias, "Bearish")
        self.assertLess(forecast.central_estimate, forecast.reference_close)

    def test_input_snapshot_records_configuration(self):
        ts, closes, highs, lows = make_series()
        forecast = generate_forecast(
            "TEST", ts, closes, highs=highs, lows=lows,
            horizon=ForecastHorizon.TWO_MONTHS,
            filter_algorithm=NoiseReductionAlgorithm.ATR2,
            swing_algorithm=SwingAlgorithm.ZIGZAG,
            swing_params={"min_swing_pct": 7.5},
            swing_range_settings={"mode": "Lookback window", "value": 12},
        )
        snapshot = forecast.input_snapshot
        self.assertEqual(snapshot["filter"], "ATR14 x 2")
        self.assertEqual(snapshot["swing_algorithm"], "ZigZag")
        self.assertEqual(snapshot["swing_params"]["min_swing_pct"], 7.5)
        self.assertEqual(snapshot["swing_range_settings"]["value"], 12)
        self.assertEqual(snapshot["price_basis"], "adjusted_close")
        self.assertEqual(snapshot["n_sessions"], 2 * SESSIONS_PER_MONTH)
        self.assertIn("mu_daily", snapshot)
        self.assertIn("sigma_daily", snapshot)
        self.assertIn("supporting", forecast.signal_summary)
        self.assertIn("assumptions", forecast.signal_summary)

    def test_atr_filter_contributes_volatility_not_direction(self):
        ts, closes, highs, lows = make_series()
        forecast = generate_forecast(
            "TEST", ts, closes, highs=highs, lows=lows,
            horizon=ForecastHorizon.ONE_MONTH,
            filter_algorithm=NoiseReductionAlgorithm.ATR2,
        )
        filter_details = forecast.signal_summary["filter_details"]
        self.assertIn("atr_pct", filter_details)
        components = forecast.signal_summary["components"]
        self.assertNotIn("filter", components)

    def test_invalid_prices_skipped(self):
        ts, closes, _, _ = make_series(n=300)
        closes = list(closes)
        closes[10] = float("nan")
        closes[11] = -5.0
        forecast = generate_forecast("TEST", ts, closes, horizon=ForecastHorizon.ONE_MONTH)
        self.assertGreater(forecast.reference_close, 0)

    def test_rebuild_projection_matches_original_path(self):
        ts, closes, _, _ = make_series()
        forecast = generate_forecast("TEST", ts, closes, horizon=ForecastHorizon.ONE_MONTH)
        original = list(forecast.path_central)
        forecast.path_central = []
        forecast.path_epochs = []
        rebuild_projection(forecast)
        self.assertEqual(len(forecast.path_central), len(original))
        for a, b in zip(forecast.path_central, original):
            self.assertAlmostEqual(a, b, places=9)


class TestAnnotationAnchor(unittest.TestCase):
    def test_valid_keys_pass_through(self):
        for key in ("top_right", "top_left", "bottom_right", "bottom_left", "hidden"):
            self.assertEqual(normalize_forecast_annotation_anchor(key), key)

    def test_case_and_separator_insensitive(self):
        self.assertEqual(normalize_forecast_annotation_anchor("Top Left"), "top_left")
        self.assertEqual(normalize_forecast_annotation_anchor("bottom-right"), "bottom_right")
        self.assertEqual(normalize_forecast_annotation_anchor("HIDDEN"), "hidden")

    def test_invalid_values_default(self):
        self.assertEqual(
            normalize_forecast_annotation_anchor("middle"), FORECAST_ANNOTATION_DEFAULT_ANCHOR
        )
        self.assertEqual(normalize_forecast_annotation_anchor(None), FORECAST_ANNOTATION_DEFAULT_ANCHOR)
        self.assertEqual(normalize_forecast_annotation_anchor(42), FORECAST_ANNOTATION_DEFAULT_ANCHOR)
        self.assertEqual(
            normalize_forecast_annotation_anchor(object()), FORECAST_ANNOTATION_DEFAULT_ANCHOR
        )


class TestAnnotationDragHandle(unittest.TestCase):
    def make_forecast(self) -> Forecast:
        return Forecast(
            ticker="AAPL",
            generated_at="2026-10-24 10:00:00",
            reference_date="2026-10-23",
            reference_close=250.0,
            target_date="2026-11-23",
            horizon_months=1,
            directional_bias="Bullish",
            central_estimate=260.0,
            lower_estimate=242.0,
            upper_estimate=278.0,
            expected_change_pct=4.0,
            model_version="baseline_v1",
            input_snapshot={},
            signal_summary={},
            currency_code="USD",
        )

    def test_drag_handle_line_is_last_and_centered(self):
        html = format_forecast_annotation_html(self.make_forecast())
        self.assertIn(f"[ {FORECAST_DRAG_HANDLE} drag box ]", html)
        self.assertIn("align='center'", html)
        handle_pos = html.find(FORECAST_DRAG_HANDLE)
        change_pos = html.find("Expected change:")
        self.assertLess(change_pos, handle_pos)
        self.assertNotIn("align='right'", html)
        self.assertNotIn("width='100%'", html)

    def test_drag_handle_is_triple_bar(self):
        self.assertEqual(FORECAST_DRAG_HANDLE, "\u2261")

    def test_html_includes_all_annotation_lines(self):
        html = format_forecast_annotation_html(self.make_forecast())
        for fragment in (
            "Forecast: 1 Month (baseline_v1)",
            "Generated: 2026-10-23 | Target: 2026-11-23",
            "Bias: Bullish",
            "$260.00",
            "+4.00%",
        ):
            self.assertIn(fragment, html)

    def test_saved_prefix_added(self):
        html = format_forecast_annotation_html(self.make_forecast(), saved=True)
        self.assertIn("Saved forecast", html)
        plain = format_forecast_annotation_html(self.make_forecast())
        self.assertNotIn("Saved forecast", plain)


if __name__ == "__main__":
    unittest.main()
