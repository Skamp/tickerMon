import math
import unittest

import pandas as pd

from app.services.technical_indicators import (
    ATR_PERIOD,
    compute_atr,
    compute_atr_bands,
    compute_ema,
    compute_true_range,
)


class TestEMA(unittest.TestCase):
    def test_matches_pandas_ewm_reference(self):
        prices = [110.2, 111.5, 109.8, 112.4, 113.1, 111.9, 114.6, 115.2, 114.0, 116.5,
                  117.1, 115.8, 118.3, 119.0, 117.5, 120.1, 121.4, 120.2, 122.8, 123.5]
        expected = pd.Series(prices).ewm(span=20, adjust=False).mean().tolist()
        actual = compute_ema(prices, 20)
        self.assertEqual(len(actual), len(prices))
        for got, want in zip(actual, expected):
            self.assertAlmostEqual(got, want, places=10)

    def test_seeded_with_first_value(self):
        ema = compute_ema([50.0, 60.0, 70.0], 20)
        self.assertAlmostEqual(ema[0], 50.0)
        alpha = 2.0 / 21.0
        self.assertAlmostEqual(ema[1], alpha * 60.0 + (1 - alpha) * 50.0)

    def test_constant_series_stays_constant(self):
        ema = compute_ema([42.0] * 50, 20)
        for value in ema:
            self.assertAlmostEqual(value, 42.0, places=12)

    def test_short_series_returns_single_entry(self):
        ema = compute_ema([100.0], 20)
        self.assertEqual(len(ema), 1)
        self.assertAlmostEqual(ema[0], 100.0)

    def test_missing_values_carried_forward(self):
        ema = compute_ema([10.0, float("nan"), 20.0], 5)
        self.assertAlmostEqual(ema[0], 10.0)
        self.assertAlmostEqual(ema[1], 10.0)
        alpha = 2.0 / 6.0
        self.assertAlmostEqual(ema[2], alpha * 20.0 + (1 - alpha) * 10.0)

    def test_leading_none_before_first_valid_value(self):
        ema = compute_ema([float("nan"), 5.0, 7.0], 3)
        self.assertIsNone(ema[0])
        self.assertAlmostEqual(ema[1], 5.0)

    def test_invalid_period_returns_none_series(self):
        ema = compute_ema([1.0, 2.0, 3.0], 0)
        self.assertEqual(ema, [None, None, None])


class TestTrueRange(unittest.TestCase):
    def test_first_bar_is_high_minus_low(self):
        tr = compute_true_range([10.0], [8.0], [9.0])
        self.assertAlmostEqual(tr[0], 2.0)

    def test_gap_up_uses_previous_close(self):
        tr = compute_true_range([15.0, 20.0], [14.0, 18.0], [14.5, 19.0])
        self.assertAlmostEqual(tr[0], 1.0)
        self.assertAlmostEqual(tr[1], max(2.0, abs(20.0 - 14.5), abs(18.0 - 14.5)))

    def test_missing_values_yield_none(self):
        tr = compute_true_range([10.0, float("nan")], [9.0, 8.0], [9.5, 9.0])
        self.assertAlmostEqual(tr[0], 1.0)
        self.assertIsNone(tr[1])


class TestATR(unittest.TestCase):
    def setUp(self):
        self.highs = [10.0, 12.0, 14.0, 13.0, 15.0, 16.0]
        self.lows = [8.0, 9.0, 11.0, 10.0, 12.0, 13.0]
        self.closes = [9.0, 11.0, 13.0, 12.0, 14.0, 15.0]

    def test_wilder_smoothing_known_values(self):
        atr = compute_atr(self.highs, self.lows, self.closes, period=3)
        self.assertIsNone(atr[0])
        self.assertIsNone(atr[1])
        self.assertAlmostEqual(atr[2], 8.0 / 3.0, places=10)
        self.assertAlmostEqual(atr[3], 25.0 / 9.0, places=10)
        self.assertAlmostEqual(atr[4], 77.0 / 27.0, places=10)
        self.assertAlmostEqual(atr[5], 235.0 / 81.0, places=10)

    def test_default_period_is_14(self):
        self.assertEqual(ATR_PERIOD, 14)
        count = 40
        highs = [100.0 + (i % 5) for i in range(count)]
        lows = [97.0 + (i % 5) for i in range(count)]
        closes = [98.0 + (i % 5) for i in range(count)]
        atr = compute_atr(highs, lows, closes)
        for i in range(ATR_PERIOD - 1):
            self.assertIsNone(atr[i])
        self.assertIsNotNone(atr[ATR_PERIOD - 1])
        self.assertIsNotNone(atr[-1])

    def test_insufficient_history_returns_all_none(self):
        atr = compute_atr([10.0, 11.0], [9.0, 10.0], [9.5, 10.5], period=14)
        self.assertTrue(all(value is None for value in atr))

    def test_missing_values_skipped_but_series_continues(self):
        highs = [10.0, 11.0, float("nan"), 13.0, 14.0, 15.0]
        lows = [9.0, 10.0, 10.0, 11.0, 12.0, 13.0]
        closes = [9.5, 10.5, 11.5, 12.5, 13.5, 14.5]
        atr = compute_atr(highs, lows, closes, period=3)
        self.assertIsNone(atr[2])
        self.assertAlmostEqual(atr[3], 5.0 / 3.0, places=10)
        self.assertAlmostEqual(atr[4], 16.0 / 9.0, places=10)


class TestATRBands(unittest.TestCase):
    def test_band_values(self):
        closes = [14.0, 15.0]
        atr = [2.0, 2.5]
        upper2, lower2 = compute_atr_bands(closes, atr, 2.0)
        self.assertAlmostEqual(upper2[0], 18.0)
        self.assertAlmostEqual(lower2[0], 10.0)
        upper4, lower4 = compute_atr_bands(closes, atr, 4.0)
        self.assertAlmostEqual(upper4[0], 22.0)
        self.assertAlmostEqual(lower4[0], 6.0)

    def test_none_atr_yields_none_bands(self):
        upper, lower = compute_atr_bands([100.0], [None], 2.0)
        self.assertIsNone(upper[0])
        self.assertIsNone(lower[0])

    def test_result_lengths_match_shorter_input(self):
        upper, lower = compute_atr_bands([1.0, 2.0, 3.0], [1.0, 1.0], 2.0)
        self.assertEqual(len(upper), 2)
        self.assertEqual(len(lower), 2)


if __name__ == "__main__":
    unittest.main()
