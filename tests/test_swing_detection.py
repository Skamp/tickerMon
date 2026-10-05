import math
import unittest

from app.services.market_data_service import is_swing_series
from app.services.swing_detection import (
    SWING_ALGORITHM_DESCRIPTIONS,
    SWING_ALGORITHM_PARAMS,
    SwingAlgorithm,
    SwingRangeMode,
    _cusum_breakpoints,
    _detect_pivot_window,
    _detect_williams_fractals,
    _detect_zigzag,
    _resolve_ohlc,
    default_swing_params,
    describe_swing_range,
    detect_swings,
    format_swing_params,
    has_significant_swing,
    normalize_swing_params,
    restrict_swing_pivots,
)

ALL_ALGORITHMS = tuple(SwingAlgorithm)


def sine_series(n: int = 200, amplitude: float = 25.0, period: float = 12.0, noise: float = 0.0) -> list:
    series = []
    for i in range(n):
        value = 100.0 + amplitude * math.sin(i / period)
        if noise:
            value += noise * ((i * 37) % 11 - 5)
        series.append(value)
    return series


def ramp_series(n: int = 200, start: float = 100.0, end: float = 130.0) -> list:
    return [start + (end - start) * i / (n - 1) for i in range(n)]


class TestSwingDetection(unittest.TestCase):
    def test_enum_from_str(self):
        self.assertEqual(SwingAlgorithm.from_str("ZigZag"), SwingAlgorithm.ZIGZAG)
        self.assertEqual(SwingAlgorithm.from_str("Williams Fractals"), SwingAlgorithm.WILLIAMS_FRACTALS)
        self.assertEqual(SwingAlgorithm.from_str("Min-Max Range (10%)"), SwingAlgorithm.RANGE)
        self.assertEqual(SwingAlgorithm.from_str("RANGE"), SwingAlgorithm.RANGE)
        self.assertEqual(SwingAlgorithm.from_str("HMM"), SwingAlgorithm.HMM)
        self.assertEqual(SwingAlgorithm.from_str("INVALID"), SwingAlgorithm.RANGE)

    def test_descriptions_cover_all_algorithms(self):
        for algorithm in ALL_ALGORITHMS:
            self.assertIn(algorithm, SWING_ALGORITHM_DESCRIPTIONS)
            self.assertTrue(SWING_ALGORITHM_DESCRIPTIONS[algorithm])

    def test_dispatcher_covers_all_algorithms(self):
        series = sine_series()
        n = len(series)
        for algorithm in ALL_ALGORITHMS:
            pivots = detect_swings(algorithm, series)
            self.assertEqual(pivots, sorted(set(pivots)), algorithm)
            self.assertTrue(all(0 <= i < n for i in pivots), algorithm)
            self.assertGreaterEqual(len(pivots), 2, algorithm)
            self.assertTrue(has_significant_swing(algorithm, series), algorithm)

    def test_flat_series_is_never_a_swing(self):
        series = [100.0] * 60
        for algorithm in ALL_ALGORITHMS:
            self.assertFalse(has_significant_swing(algorithm, series), algorithm)

    def test_monotonic_series_is_a_swing(self):
        series = ramp_series()
        for algorithm in ALL_ALGORITHMS:
            self.assertTrue(has_significant_swing(algorithm, series), algorithm)

    def test_small_moves_are_never_a_swing(self):
        series = sine_series(amplitude=2.0, period=5.0)
        for algorithm in ALL_ALGORITHMS:
            self.assertFalse(has_significant_swing(algorithm, series), algorithm)

    def test_no_algorithm_is_more_sensitive_than_range(self):
        series = sine_series(n=120, amplitude=13.0, period=7.0, noise=1.6)
        legacy = has_significant_swing(SwingAlgorithm.RANGE, series)
        for algorithm in ALL_ALGORITHMS:
            result = has_significant_swing(algorithm, series)
            if result:
                self.assertTrue(legacy, algorithm)

    def test_empty_and_single_point_series(self):
        for algorithm in ALL_ALGORITHMS:
            self.assertFalse(has_significant_swing(algorithm, []))
            self.assertFalse(has_significant_swing(algorithm, [100.0]))
            self.assertEqual(detect_swings(algorithm, []), [])
            self.assertEqual(detect_swings(algorithm, [100.0]), [0])

    def test_short_series_are_safe(self):
        for length in range(2, 8):
            series = [100.0 + i for i in range(length)]
            for algorithm in ALL_ALGORITHMS:
                pivots = detect_swings(algorithm, series)
                self.assertEqual(pivots, sorted(set(pivots)), algorithm)
                self.assertTrue(all(0 <= i < length for i in pivots), algorithm)

    def test_pivot_legs_alternate_direction(self):
        for algorithm in (SwingAlgorithm.ZIGZAG, SwingAlgorithm.WILLIAMS_FRACTALS, SwingAlgorithm.PIVOT_WINDOW):
            series = sine_series()
            pivots = detect_swings(algorithm, series)
            legs = []
            for a, b in zip(pivots, pivots[1:]):
                change = series[b] - series[a]
                if change != 0:
                    legs.append(change > 0)
            for previous, current in zip(legs, legs[1:]):
                self.assertNotEqual(previous, current, algorithm)

    def test_legacy_range_behavior_unchanged(self):
        self.assertFalse(is_swing_series([]))
        self.assertFalse(is_swing_series([100.0]))
        self.assertTrue(is_swing_series([100.0, 110.0]))
        self.assertFalse(is_swing_series([100.0, 109.9]))
        self.assertTrue(is_swing_series([110.0, 100.0]))
        self.assertFalse(is_swing_series([100.0, 105.0, 100.0]))
        self.assertTrue(is_swing_series([110.0, 99.0, 110.0]))

    def test_zigzag_filters_small_moves(self):
        quiet = [100.0 + 1.5 * math.sin(i / 3.0) for i in range(60)]
        pivots = _detect_zigzag(quiet)
        self.assertEqual(pivots, [])

        swinging = sine_series(n=60, amplitude=20.0, period=15.0)
        pivots = _detect_zigzag(swinging)
        self.assertGreater(len(pivots), 0)

    def test_zigzag_atr_mode(self):
        import numpy as np
        from app.services.swing_detection import _atr

        close = np.asarray(sine_series(n=80, amplitude=18.0, period=14.0))
        high = close.copy()
        low = close.copy()
        atr = _atr(high, low, close, period=14)

        pivots_pct = _detect_zigzag(close, threshold_pct=5.0)
        pivots_atr = _detect_zigzag(close, atr=atr, atr_multiple=1.0)
        pivots_wide = _detect_zigzag(close, atr=atr, atr_multiple=10.0)

        self.assertTrue(all(0 <= i < len(close) for i in pivots_pct))
        self.assertTrue(all(0 <= i < len(close) for i in pivots_atr))
        self.assertTrue(all(0 <= i < len(close) for i in pivots_wide))
        self.assertLessEqual(len(pivots_wide), len(pivots_atr))

    def test_williams_fractals_detects_known_extrema(self):
        import numpy as np

        series = [100.0, 101.0, 104.0, 110.0, 104.0, 98.0, 95.0, 100.0, 102.0]
        close = np.asarray(series)
        opens, highs, lows = _resolve_ohlc(close, None)
        pivots = _detect_williams_fractals(close, highs, lows, order=2)
        self.assertIn(3, pivots)
        self.assertIn(6, pivots)

    def test_pivot_window_detects_known_peaks(self):
        import numpy as np

        close = np.asarray(sine_series(n=100, amplitude=20.0, period=20.0))
        pivots = _detect_pivot_window(close, window=5, prominence_ratio=0.05)
        self.assertGreater(len(pivots), 0)
        for index in pivots:
            self.assertTrue(0 < index < len(close) - 1)

    def test_cusum_finds_level_shift(self):
        import numpy as np

        series = np.concatenate([np.full(50, 100.0), np.full(50, 120.0)])
        breakpoints = _cusum_breakpoints(series)
        self.assertGreater(len(breakpoints), 0)
        self.assertTrue(any(40 <= b <= 60 for b in breakpoints))

    def test_ohlc_is_optional_for_every_algorithm(self):
        series = sine_series(n=150, amplitude=20.0, period=10.0, noise=1.0)
        import numpy as np

        close = np.asarray(series)
        opens, highs, lows = _resolve_ohlc(close, None)
        explicit_ohlc = (opens.tolist(), highs.tolist(), lows.tolist())

        for algorithm in ALL_ALGORITHMS:
            without_ohlc = detect_swings(algorithm, series)
            with_ohlc = detect_swings(algorithm, series, explicit_ohlc)
            self.assertEqual(without_ohlc, with_ohlc, algorithm)
            self.assertEqual(without_ohlc, sorted(set(with_ohlc)), algorithm)

    def test_mismatched_ohlc_falls_back_to_close(self):
        series = sine_series(n=40, amplitude=15.0)
        pivots = detect_swings(SwingAlgorithm.PARABOLIC_SAR, series, ([1.0], [2.0], [0.5]))
        self.assertTrue(all(0 <= i < len(series) for i in pivots))

    def test_detector_parameters_do_not_crash(self):
        series = sine_series(n=90, amplitude=18.0, period=9.0)
        for algorithm in ALL_ALGORITHMS:
            for threshold in (1.0, 10.0, 50.0):
                result = has_significant_swing(algorithm, series, threshold_pct=threshold)
                self.assertIsInstance(result, bool)

    def test_change_point_and_hmm_run_on_long_series(self):
        series = sine_series(n=260, amplitude=22.0, period=17.0, noise=1.2)
        for algorithm in (SwingAlgorithm.CHANGE_POINT, SwingAlgorithm.HMM, SwingAlgorithm.HILBERT, SwingAlgorithm.WAVELETS):
            pivots = detect_swings(algorithm, series)
            self.assertGreater(len(pivots), 2, algorithm)
            self.assertTrue(has_significant_swing(algorithm, series), algorithm)


class TestSwingParams(unittest.TestCase):
    def test_param_specs_cover_all_algorithms(self):
        for algorithm in ALL_ALGORITHMS:
            self.assertIn(algorithm, SWING_ALGORITHM_PARAMS)
            specs = SWING_ALGORITHM_PARAMS[algorithm]
            self.assertGreaterEqual(len(specs), 1, algorithm)
            self.assertEqual(specs[0].key, "min_swing_pct", algorithm)
            keys = [spec.key for spec in specs]
            self.assertEqual(len(keys), len(set(keys)), algorithm)
            for spec in specs:
                self.assertIn(spec.kind, ("int", "float"), algorithm)
                self.assertLessEqual(spec.minimum, spec.default, algorithm)
                self.assertLessEqual(spec.default, spec.maximum, algorithm)

    def test_default_swing_params_returns_spec_defaults(self):
        for algorithm in ALL_ALGORITHMS:
            params = default_swing_params(algorithm)
            for spec in SWING_ALGORITHM_PARAMS[algorithm]:
                self.assertEqual(params[spec.key], spec.default, algorithm)

    def test_normalize_clamps_out_of_range_values(self):
        params = {"min_swing_pct": -50.0, "period": 99999.0}
        normalized = normalize_swing_params(SwingAlgorithm.SUPERTREND, params)
        self.assertEqual(normalized["min_swing_pct"], 0.1)
        self.assertEqual(normalized["period"], 100.0)

    def test_normalize_rejects_invalid_values(self):
        params = {"period": "not a number", "mult": None}
        normalized = normalize_swing_params(SwingAlgorithm.SUPERTREND, params)
        self.assertEqual(normalized["period"], 10.0)
        self.assertEqual(normalized["mult"], 3.0)

        nan_params = {"period": float("nan")}
        normalized = normalize_swing_params(SwingAlgorithm.SUPERTREND, nan_params)
        self.assertEqual(normalized["period"], 10.0)

    def test_normalize_int_params_are_integers(self):
        normalized = normalize_swing_params(SwingAlgorithm.RSI, {"period": 14.6})
        self.assertEqual(normalized["period"], 15.0)
        self.assertIsInstance(normalized["period"], float)

    def test_normalize_fixes_cross_field_constraints(self):
        macd = normalize_swing_params(SwingAlgorithm.MACD, {"fast": 50.0, "slow": 10.0})
        self.assertLess(macd["fast"], macd["slow"])

        rsi = normalize_swing_params(SwingAlgorithm.RSI, {"upper": 30.0, "lower": 70.0})
        self.assertLess(rsi["lower"], rsi["upper"])

        savgol = normalize_swing_params(SwingAlgorithm.SAVITZKY_GOLAY, {"window_size": 6.0, "polyorder": 9.0})
        self.assertEqual(savgol["window_size"] % 2, 1)
        self.assertLess(savgol["polyorder"], savgol["window_size"])

    def test_format_swing_params_covers_all_algorithms(self):
        for algorithm in ALL_ALGORITHMS:
            text = format_swing_params(algorithm)
            self.assertTrue(text, algorithm)
            self.assertIn("Min swing size (%)", text, algorithm)
            for spec in SWING_ALGORITHM_PARAMS[algorithm]:
                if spec.key != "min_swing_pct":
                    self.assertIn(spec.label, text, algorithm)

    def test_format_swing_params_reflects_custom_values(self):
        text = format_swing_params(SwingAlgorithm.RANGE, {"min_swing_pct": 12.5})
        self.assertIn("12.5", text)

        text = format_swing_params(SwingAlgorithm.RSI, {"period": 21.0, "upper": 65.0})
        self.assertIn("RSI period: 21", text)
        self.assertNotIn("RSI period: 21.0", text)
        self.assertIn("Overbought level: 65", text)

    def test_format_swing_params_handles_garbage(self):
        text = format_swing_params(SwingAlgorithm.ZIGZAG, {"threshold_pct": "bad", "min_swing_pct": None})
        defaults = default_swing_params(SwingAlgorithm.ZIGZAG)
        self.assertIn(f"Reversal threshold (%): {defaults['threshold_pct']:g}", text)

    def test_min_swing_pct_params_change_classification(self):
        series = [100.0, 109.9]
        self.assertFalse(is_swing_series(series, params={"min_swing_pct": 10.0}))
        self.assertTrue(is_swing_series(series, params={"min_swing_pct": 5.0}))

        self.assertFalse(has_significant_swing(SwingAlgorithm.RANGE, series, params={"min_swing_pct": 15.0}))
        self.assertTrue(has_significant_swing(SwingAlgorithm.RANGE, series, params={"min_swing_pct": 9.0}))

    def test_params_override_threshold_pct(self):
        series = [100.0, 109.9]
        result = has_significant_swing(
            SwingAlgorithm.RANGE, series, threshold_pct=50.0, params={"min_swing_pct": 5.0}
        )
        self.assertTrue(result)

    def test_detect_swings_accepts_params_for_all_algorithms(self):
        series = sine_series(n=120, amplitude=18.0, period=9.0)
        for algorithm in ALL_ALGORITHMS:
            defaults = default_swing_params(algorithm)
            with_defaults = detect_swings(algorithm, series, params=defaults)
            without_params = detect_swings(algorithm, series)
            self.assertEqual(with_defaults, without_params, algorithm)

            tweaked = dict(defaults)
            tweaked["min_swing_pct"] = 25.0
            pivots = detect_swings(algorithm, series, params=tweaked)
            self.assertEqual(pivots, sorted(set(pivots)), algorithm)
            self.assertTrue(all(0 <= i < len(series) for i in pivots), algorithm)

    def test_detect_swings_tolerates_garbage_params(self):
        series = sine_series(n=60, amplitude=15.0, period=8.0)
        garbage = {"period": "abc", "min_swing_pct": None, "mult": [], "unknown_key": 1.0}
        for algorithm in ALL_ALGORITHMS:
            pivots = detect_swings(algorithm, series, params=garbage)
            self.assertEqual(pivots, sorted(set(pivots)), algorithm)

    def test_zigzag_threshold_param_filters_moves(self):
        series = sine_series(n=100, amplitude=18.0, period=12.0)
        loose = detect_swings(SwingAlgorithm.ZIGZAG, series, params={"threshold_pct": 40.0})
        strict = detect_swings(SwingAlgorithm.ZIGZAG, series, params={"threshold_pct": 2.0})
        self.assertLessEqual(len(loose), len(strict))

    def test_detector_specific_params_reach_detectors(self):
        series = sine_series(n=150, amplitude=20.0, period=11.0, noise=1.0)
        cases = [
            (SwingAlgorithm.WILLIAMS_FRACTALS, {"order": 4}),
            (SwingAlgorithm.PIVOT_WINDOW, {"window": 9, "prominence_ratio": 0.2}),
            (SwingAlgorithm.PARABOLIC_SAR, {"af_step": 0.05, "af_max": 0.4}),
            (SwingAlgorithm.SUPERTREND, {"period": 20, "mult": 4.0}),
            (SwingAlgorithm.RSI, {"period": 21, "upper": 60.0, "lower": 40.0}),
            (SwingAlgorithm.STOCHASTIC, {"period": 9, "smooth": 5, "upper": 70.0, "lower": 30.0}),
            (SwingAlgorithm.MACD, {"fast": 5, "slow": 35, "signal": 5}),
            (SwingAlgorithm.CCI, {"period": 10, "upper": 150.0, "lower": -150.0}),
            (SwingAlgorithm.BOLLINGER, {"period": 30, "mult": 3.0}),
            (SwingAlgorithm.KELTNER, {"period": 30, "mult": 3.0, "atr_period": 5}),
            (SwingAlgorithm.CHANGE_POINT, {"min_size": 8, "penalty_factor": 10.0, "cusum_threshold": 0.0}),
            (SwingAlgorithm.KALMAN, {"process_noise": 0.01, "measurement_noise": 5.0}),
            (SwingAlgorithm.SAVITZKY_GOLAY, {"window_size": 11.0, "polyorder": 3.0}),
            (SwingAlgorithm.WAVELETS, {"level": 2.0}),
            (SwingAlgorithm.HMM, {"n_states": 4.0, "iterations": 3.0}),
            (SwingAlgorithm.SWING_INDEX, {"limit_factor": 10.0}),
            (SwingAlgorithm.DONCHIAN, {"period": 40.0}),
            (SwingAlgorithm.CHANDELIER_EXIT, {"period": 40.0, "mult": 5.0}),
            (SwingAlgorithm.HEIKIN_ASHI, {"order": 4.0}),
        ]
        for algorithm, params in cases:
            merged = {**default_swing_params(algorithm), **params}
            pivots = detect_swings(algorithm, series, params=merged)
            self.assertEqual(pivots, sorted(set(pivots)), algorithm)
            self.assertTrue(all(0 <= i < len(series) for i in pivots), algorithm)
            self.assertIsInstance(
                has_significant_swing(algorithm, series, params=merged), bool, algorithm
            )


class TestSwingRange(unittest.TestCase):
    DAY = 86400.0

    def setUp(self):
        # Pivots at day 0, 20, 40, 60 -> legs of 20 days (~2.86 weeks)
        self.timestamps = [0.0, 20 * self.DAY, 40 * self.DAY, 60 * self.DAY]
        self.pivots = [0, 1, 2, 3]

    def test_range_mode_from_str(self):
        self.assertEqual(SwingRangeMode.from_str("Minimum duration"), SwingRangeMode.MIN_DURATION)
        self.assertEqual(SwingRangeMode.from_str("LOOKBACK"), SwingRangeMode.LOOKBACK)
        self.assertEqual(SwingRangeMode.from_str("Duration window"), SwingRangeMode.DURATION_WINDOW)
        self.assertEqual(SwingRangeMode.from_str("lookback"), SwingRangeMode.LOOKBACK)
        self.assertEqual(SwingRangeMode.from_str("invalid"), SwingRangeMode.MIN_DURATION)
        self.assertEqual(SwingRangeMode.from_str(""), SwingRangeMode.MIN_DURATION)

    def test_disabled_range_keeps_everything(self):
        for settings in (None, {}, {"value": 0, "mode": "Minimum duration", "unit": "weeks"}):
            kept, legs = restrict_swing_pivots(self.pivots, self.timestamps, settings)
            self.assertEqual(kept, self.pivots, settings)
            self.assertEqual(len(legs), 3, settings)

    def test_min_duration_filters_short_legs(self):
        short = {"mode": "Minimum duration", "value": 3, "unit": "weeks"}
        kept, legs = restrict_swing_pivots(self.pivots, self.timestamps, short)
        self.assertEqual(legs, [])
        self.assertEqual(kept, [])

        long = {"mode": "Minimum duration", "value": 2, "unit": "weeks"}
        kept, legs = restrict_swing_pivots(self.pivots, self.timestamps, long)
        self.assertEqual(len(legs), 3)
        self.assertEqual(kept, self.pivots)

    def test_max_duration_filters_long_legs(self):
        tight = {"mode": "Maximum duration", "value": 2, "unit": "weeks"}
        kept, legs = restrict_swing_pivots(self.pivots, self.timestamps, tight)
        self.assertEqual(legs, [])

        loose = {"mode": "Maximum duration", "value": 4, "unit": "weeks"}
        kept, legs = restrict_swing_pivots(self.pivots, self.timestamps, loose)
        self.assertEqual(len(legs), 3)

    def test_lookback_window_drops_old_pivots(self):
        settings = {"mode": "Lookback window", "value": 3, "unit": "weeks"}
        kept, legs = restrict_swing_pivots(self.pivots, self.timestamps, settings)
        # cutoff = day 60 - 21 = day 39 -> pivots at day 40 and 60 remain
        self.assertEqual(kept, [2, 3])
        self.assertEqual(legs, [(2, 3)])

    def test_duration_window_keeps_both_bounds(self):
        outside = {"mode": "Duration window", "value": 3, "value_max": 4, "unit": "weeks"}
        kept, legs = restrict_swing_pivots(self.pivots, self.timestamps, outside)
        self.assertEqual(legs, [])

        inside = {"mode": "Duration window", "value": 2, "value_max": 4, "unit": "weeks"}
        kept, legs = restrict_swing_pivots(self.pivots, self.timestamps, inside)
        self.assertEqual(len(legs), 3)
        self.assertEqual(kept, self.pivots)

    def test_months_unit_conversion(self):
        min_month = {"mode": "Minimum duration", "value": 1, "unit": "months"}
        _, legs = restrict_swing_pivots(self.pivots, self.timestamps, min_month)
        self.assertEqual(legs, [])  # 20 days < 30.44 days

        max_month = {"mode": "Maximum duration", "value": 1, "unit": "months"}
        _, legs = restrict_swing_pivots(self.pivots, self.timestamps, max_month)
        self.assertEqual(len(legs), 3)

    def test_garbage_settings_are_safe(self):
        for settings in (None, [], "x", {"value": "abc", "mode": 5}, {"value": -10}):
            kept, legs = restrict_swing_pivots(self.pivots, self.timestamps, settings)
            self.assertEqual(kept, self.pivots, settings)
            self.assertEqual(len(legs), 3, settings)

    def test_mismatched_timestamps_fall_back_to_unfiltered(self):
        kept, legs = restrict_swing_pivots([0, 1, 2], [0.0], {"mode": "Minimum duration", "value": 52, "unit": "weeks"})
        self.assertEqual(kept, [0, 1, 2])
        self.assertEqual(len(legs), 2)

    def test_describe_swing_range(self):
        self.assertEqual(describe_swing_range(None), "off")
        self.assertEqual(describe_swing_range({"value": 0}), "off")
        self.assertEqual(
            describe_swing_range({"mode": "Minimum duration", "value": 4, "unit": "weeks"}),
            ">= 4 weeks",
        )
        self.assertEqual(
            describe_swing_range({"mode": "Minimum duration", "value": 1, "unit": "weeks"}),
            ">= 1 week",
        )
        self.assertEqual(
            describe_swing_range({"mode": "Maximum duration", "value": 2, "unit": "months"}),
            "<= 2 months",
        )
        self.assertEqual(
            describe_swing_range({"mode": "Lookback window", "value": 3, "unit": "weeks"}),
            "last 3 weeks",
        )
        self.assertEqual(
            describe_swing_range(
                {"mode": "Duration window", "value": 2, "value_max": 6, "unit": "weeks"}
            ),
            "2 weeks to 6 weeks",
        )


if __name__ == "__main__":
    unittest.main()
