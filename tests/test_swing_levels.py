import unittest

from app.services.market_structure import STRUCTURE_HIGH, STRUCTURE_LOW
from app.services.swing_levels import (
    NEUTRAL_TOLERANCE_PCT,
    confirmed_pivot_indices,
    compute_swing_levels,
    format_level_annotation,
    is_level_crossed,
    level_color,
)


class TestConfirmedPivots(unittest.TestCase):
    def test_trailing_bar_anchor_excluded(self):
        self.assertEqual(confirmed_pivot_indices([0, 5, 9], 10), [0, 5])

    def test_no_pivots_at_trailing_bar(self):
        self.assertEqual(confirmed_pivot_indices([0, 5], 10), [0, 5])

    def test_all_pivots_trailing(self):
        self.assertEqual(confirmed_pivot_indices([9], 10), [])

    def test_empty(self):
        self.assertEqual(confirmed_pivot_indices([], 10), [])


class TestCrossing(unittest.TestCase):
    def test_high_not_crossed_by_later_lower_bars(self):
        highs = [10.0, 11.0, 12.0, 11.5, 11.8]
        self.assertFalse(is_level_crossed(12.0, STRUCTURE_HIGH, 2, highs=highs))

    def test_high_crossed_when_later_high_exceeds_level(self):
        highs = [10.0, 11.0, 12.0, 11.5, 12.5]
        self.assertTrue(is_level_crossed(12.0, STRUCTURE_HIGH, 2, highs=highs))

    def test_low_crossed_when_later_low_below_level(self):
        lows = [10.0, 9.5, 9.0, 9.4, 8.8]
        self.assertTrue(is_level_crossed(9.0, STRUCTURE_LOW, 2, lows=lows))

    def test_low_not_crossed(self):
        lows = [10.0, 9.5, 9.0, 9.4, 9.2]
        self.assertFalse(is_level_crossed(9.0, STRUCTURE_LOW, 2, lows=lows))

    def test_crossing_at_pivot_bar_itself_does_not_count(self):
        highs = [10.0, 15.0, 11.0]
        self.assertFalse(is_level_crossed(15.0, STRUCTURE_HIGH, 1, highs=highs))

    def test_close_fallback_when_high_missing(self):
        highs = [10.0, 11.0, 12.0, None]
        closes = [10.5, 10.8, 11.9, 12.4]
        self.assertTrue(is_level_crossed(12.0, STRUCTURE_HIGH, 2, highs=highs, closes=closes))

    def test_no_crossing_without_bar_data(self):
        self.assertFalse(is_level_crossed(100.0, STRUCTURE_HIGH, 2))


class TestLevelColor(unittest.TestCase):
    def test_above_reference_is_green(self):
        self.assertEqual(level_color(105.0, 100.0), "#00e676")

    def test_below_reference_is_red(self):
        self.assertEqual(level_color(95.0, 100.0), "#ff5252")

    def test_within_tolerance_is_neutral(self):
        offset = 100.0 * NEUTRAL_TOLERANCE_PCT / 100.0
        self.assertEqual(level_color(100.0 + offset, 100.0), "#8b90a0")
        self.assertEqual(level_color(100.0 - offset, 100.0), "#8b90a0")

    def test_invalid_reference_is_neutral(self):
        self.assertEqual(level_color(105.0, 0.0), "#8b90a0")


class TestAnnotation(unittest.TestCase):
    def test_high_annotation_content(self):
        text = format_level_annotation(STRUCTURE_HIGH, 150.0, 140.0)
        self.assertIn("Last Confirmed High", text)
        self.assertIn("150.00", text)
        self.assertIn("+10.00", text)
        self.assertIn("+7.14%", text)

    def test_low_annotation_negative_distance(self):
        text = format_level_annotation(STRUCTURE_LOW, 130.0, 140.0, currency_code="EUR")
        self.assertIn("Last Confirmed Low", text)
        self.assertIn("-10.00", text)
        self.assertIn("-7.14%", text)


class TestComputeSwingLevels(unittest.TestCase):
    def setUp(self):
        self.prices = [100.0, 102.0, 98.0, 104.0, 110.0, 105.0, 101.0, 103.0, 108.0, 106.0]
        self.pivots = [0, 2, 4, 6, 8, 9]

    def test_returns_latest_confirmed_high_and_low(self):
        highs = list(self.prices)
        lows = list(self.prices)
        high_level, low_level = compute_swing_levels(
            self.pivots, self.prices, reference_close=106.0,
            highs=highs, lows=lows, closes=self.prices,
        )
        self.assertIsNotNone(high_level)
        self.assertIsNotNone(low_level)
        self.assertEqual(high_level.price, 108.0)
        self.assertEqual(low_level.price, 101.0)

    def test_trailing_anchor_ignored_even_when_extreme(self):
        prices = [100.0, 108.0, 100.0, 102.0, 100.0, 90.0]
        pivots = [1, 3, 5]
        high_level, low_level = compute_swing_levels(pivots, prices, reference_close=100.0)
        self.assertIsNotNone(high_level)
        self.assertEqual(high_level.index, 3)
        self.assertIsNone(low_level)

    def test_distances_measured_from_reference_close(self):
        high_level, low_level = compute_swing_levels(
            self.pivots, self.prices, reference_close=106.0
        )
        self.assertAlmostEqual(high_level.distance, 108.0 - 106.0)
        self.assertAlmostEqual(high_level.distance_pct, (108.0 - 106.0) / 106.0 * 100.0)
        self.assertAlmostEqual(low_level.distance, 101.0 - 106.0)
        self.assertLess(low_level.distance, 0.0)

    def test_no_confirmed_pivots_returns_none(self):
        high_level, low_level = compute_swing_levels([9], self.prices, reference_close=106.0)
        self.assertIsNone(high_level)
        self.assertIsNone(low_level)

    def test_colors_and_crossing_status(self):
        highs = [104.0, 105.0, 103.0, 106.0, 112.0, 107.0, 103.0, 104.0, 108.0, 109.0]
        lows = [99.0, 101.0, 97.0, 103.0, 109.0, 104.0, 99.5, 102.0, 107.0, 100.0]
        high_level, low_level = compute_swing_levels(
            self.pivots, self.prices, reference_close=106.0,
            highs=highs, lows=lows, closes=self.prices,
        )
        self.assertEqual(high_level.color, "#00e676")
        self.assertEqual(low_level.color, "#ff5252")
        self.assertTrue(high_level.crossed)
        self.assertTrue(low_level.crossed)

    def test_annotation_contains_level_name(self):
        high_level, _ = compute_swing_levels(
            self.pivots, self.prices, reference_close=106.0, currency_code="USD"
        )
        self.assertIn("Last Confirmed High", high_level.annotation)

    def test_single_kind_pivot(self):
        prices = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
        pivots = [0, 5]
        high_level, low_level = compute_swing_levels(pivots, prices, reference_close=105.0)
        self.assertIsNone(high_level)
        self.assertIsNotNone(low_level)
        self.assertEqual(low_level.kind, STRUCTURE_LOW)


if __name__ == "__main__":
    unittest.main()
