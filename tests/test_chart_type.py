import math
import unittest

from app.models.chart_type import ChartType
from app.ui.chart_widget import (
    CANDLE_BEARISH,
    CANDLE_BULLISH,
    CANDLE_NEUTRAL,
    build_candle_bodies,
    build_wick_series,
    candle_price_bounds,
    classify_candles,
    split_baseline_series,
)


class TestChartType(unittest.TestCase):
    def test_from_str_known_values(self):
        self.assertEqual(ChartType.from_str("Line"), ChartType.LINE)
        self.assertEqual(ChartType.from_str("Candle"), ChartType.CANDLE)
        self.assertEqual(ChartType.from_str("Baseline"), ChartType.BASELINE)

    def test_from_str_accepts_member_names(self):
        self.assertEqual(ChartType.from_str("LINE"), ChartType.LINE)
        self.assertEqual(ChartType.from_str("CANDLE"), ChartType.CANDLE)

    def test_from_str_falls_back_to_line(self):
        self.assertEqual(ChartType.from_str("Unknown"), ChartType.LINE)
        self.assertEqual(ChartType.from_str(""), ChartType.LINE)


class TestClassifyCandles(unittest.TestCase):
    def test_bullish_bearish_neutral(self):
        opens = [10.0, 20.0, 30.0]
        highs = [12.0, 22.0, 31.0]
        lows = [9.0, 18.0, 29.0]
        closes = [11.0, 19.0, 30.0]
        self.assertEqual(
            classify_candles(opens, highs, lows, closes),
            [CANDLE_BULLISH, CANDLE_BEARISH, CANDLE_NEUTRAL],
        )

    def test_invalid_rows_return_none(self):
        opens = [10.0, 0.0, 10.0, None]
        highs = [12.0, 15.0, 9.0, 12.0]
        lows = [9.0, 8.0, 11.0, 9.0]
        closes = [11.0, 12.0, 10.0, 11.0]
        kinds = classify_candles(opens, highs, lows, closes)
        self.assertEqual(kinds[0], CANDLE_BULLISH)
        self.assertIsNone(kinds[1])
        self.assertIsNone(kinds[2])
        self.assertIsNone(kinds[3])

    def test_short_arrays_truncate_to_common_length(self):
        kinds = classify_candles([10.0, 11.0], [12.0], [9.0], [11.0, 12.0])
        self.assertEqual(len(kinds), 1)
        self.assertEqual(kinds[0], CANDLE_BULLISH)


class TestBuildCandleBodies(unittest.TestCase):
    def test_body_center_and_height(self):
        timestamps = [1.0, 2.0]
        opens = [10.0, 20.0]
        closes = [12.0, 18.0]
        kinds = [CANDLE_BULLISH, CANDLE_BEARISH]
        bodies = build_candle_bodies(timestamps, opens, closes, kinds)

        bull_x, bull_y, bull_h = bodies[CANDLE_BULLISH]
        self.assertEqual(bull_x, [1.0])
        self.assertEqual(bull_y, [11.0])
        self.assertEqual(bull_h, [2.0])

        bear_x, bear_y, bear_h = bodies[CANDLE_BEARISH]
        self.assertEqual(bear_x, [2.0])
        self.assertEqual(bear_y, [19.0])
        self.assertEqual(bear_h, [2.0])

    def test_neutral_body_gets_minimum_height(self):
        bodies = build_candle_bodies(
            [1.0], [10.0], [10.0], [CANDLE_NEUTRAL], min_body_height=0.5
        )
        _, ys, hs = bodies[CANDLE_NEUTRAL]
        self.assertEqual(ys, [10.0])
        self.assertEqual(hs, [0.5])

    def test_invalid_and_mismatched_rows_skipped(self):
        bodies = build_candle_bodies(
            [1.0, 2.0, 3.0],
            [10.0, 10.0, 10.0],
            [11.0, 11.0, 11.0],
            [CANDLE_BULLISH, None],
        )
        xs, _, _ = bodies[CANDLE_BULLISH]
        self.assertEqual(xs, [1.0])


class TestBuildWickSeries(unittest.TestCase):
    def test_wick_connects_high_to_low_with_nan_separation(self):
        timestamps = [1.0, 2.0, 5.0]
        highs = [12.0, 22.0, 12.0]
        lows = [9.0, 18.0, 9.0]
        kinds = [CANDLE_BULLISH, CANDLE_BULLISH, CANDLE_BEARISH]

        wicks = build_wick_series(timestamps, highs, lows, kinds)
        bull_x, bull_y = wicks[CANDLE_BULLISH]
        self.assertEqual(len(bull_x), 5)
        self.assertEqual(bull_x[:2], [1.0, 1.0])
        self.assertTrue(math.isnan(bull_x[2]))
        self.assertEqual(bull_x[3:], [2.0, 2.0])
        self.assertEqual(bull_y[:2], [12.0, 9.0])
        self.assertTrue(math.isnan(bull_y[2]))
        self.assertEqual(bull_y[3:], [22.0, 18.0])

        bear_x, bear_y = wicks[CANDLE_BEARISH]
        self.assertEqual(bear_x, [5.0, 5.0])
        self.assertEqual(bear_y, [12.0, 9.0])

    def test_invalid_rows_produce_no_wicks(self):
        wicks = build_wick_series([1.0], [12.0], [9.0], [None])
        for kind in (CANDLE_BULLISH, CANDLE_BEARISH, CANDLE_NEUTRAL):
            self.assertEqual(wicks[kind], ([], []))


class TestCandlePriceBounds(unittest.TestCase):
    def test_bounds_over_valid_candles_only(self):
        highs = [12.0, 30.0, 15.0]
        lows = [9.0, 25.0, 8.0]
        kinds = [CANDLE_BULLISH, None, CANDLE_BEARISH]
        self.assertEqual(candle_price_bounds(highs, lows, kinds), (15.0, 8.0))

    def test_no_valid_candles_returns_none(self):
        self.assertIsNone(candle_price_bounds([12.0], [9.0], [None]))


class TestSplitBaselineSeries(unittest.TestCase):
    def test_all_above_baseline(self):
        above_x, above_y, below_x, below_y = split_baseline_series(
            [1.0, 2.0, 3.0], [110.0, 120.0, 130.0], 100.0
        )
        self.assertEqual(above_x, [1.0, 2.0, 3.0])
        self.assertEqual(above_y, [110.0, 120.0, 130.0])
        self.assertEqual(below_x, [])
        self.assertEqual(below_y, [])

    def test_all_below_baseline(self):
        above_x, above_y, below_x, below_y = split_baseline_series(
            [1.0, 2.0], [90.0, 80.0], 100.0
        )
        self.assertEqual(above_x, [])
        self.assertEqual(below_x, [1.0, 2.0])
        self.assertEqual(below_y, [90.0, 80.0])

    def test_single_crossing_interpolates_on_baseline(self):
        above_x, above_y, below_x, below_y = split_baseline_series(
            [1.0, 2.0], [90.0, 110.0], 100.0
        )
        self.assertEqual(above_x, [1.5, 2.0])
        self.assertEqual(above_y, [100.0, 110.0])
        self.assertEqual(below_x, [1.0, 1.5])
        self.assertEqual(below_y, [90.0, 100.0])

    def test_multiple_crossings_split_into_segments(self):
        timestamps = [1.0, 2.0, 3.0, 4.0]
        prices = [110.0, 90.0, 110.0, 90.0]
        above_x, above_y, below_x, below_y = split_baseline_series(
            timestamps, prices, 100.0
        )

        # Each crossing point terminates one segment and starts the next, so
        # it appears on both sides of the baseline; disjoint segments of the
        # same side are separated by NaN.
        self.assertTrue(math.isnan(above_x[2]))
        self.assertTrue(math.isnan(below_x[3]))
        self.assertEqual(above_y[:2], [110.0, 100.0])
        self.assertEqual(above_y[3:], [100.0, 110.0, 100.0])
        self.assertEqual(below_y[:3], [100.0, 90.0, 100.0])
        self.assertEqual(below_y[4:], [100.0, 90.0])

        real_above = [y for y in above_y if not math.isnan(y) and y != 100.0]
        real_below = [y for y in below_y if not math.isnan(y) and y != 100.0]
        self.assertEqual(real_above, [110.0, 110.0])
        self.assertEqual(real_below, [90.0, 90.0])

    def test_baseline_equal_to_first_price(self):
        above_x, above_y, below_x, below_y = split_baseline_series(
            [1.0, 2.0], [100.0, 105.0], 100.0
        )
        self.assertEqual(above_x, [1.0, 2.0])
        self.assertEqual(above_y, [100.0, 105.0])
        self.assertEqual(below_x, [])

    def test_empty_and_invalid_inputs(self):
        self.assertEqual(split_baseline_series([], [], 100.0), ([], [], [], []))
        self.assertEqual(
            split_baseline_series([1.0], [100.0], float("nan")), ([], [], [], [])
        )

    def test_invalid_price_gaps_break_segments(self):
        above_x, above_y, below_x, below_y = split_baseline_series(
            [1.0, 2.0, 3.0], [110.0, float("nan"), 120.0], 100.0
        )
        self.assertEqual(len(above_x), 3)
        self.assertEqual(above_x[0], 1.0)
        self.assertTrue(math.isnan(above_x[1]))
        self.assertEqual(above_x[2], 3.0)
        self.assertEqual(above_y[0], 110.0)
        self.assertTrue(math.isnan(above_y[1]))
        self.assertEqual(above_y[2], 120.0)
        self.assertEqual(below_x, [])
        self.assertEqual(below_y, [])


if __name__ == "__main__":
    unittest.main()
