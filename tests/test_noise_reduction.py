import math
import unittest
from app.services.noise_reduction import (
    NoiseReductionAlgorithm,
    reduce_noise,
    apply_quadtree_reduction,
    apply_ema_reduction,
    apply_savitzky_golay_reduction,
    apply_rdp_reduction,
    apply_dema_reduction,
    apply_tema_reduction,
    apply_hma_reduction,
    apply_kalman_filter,
    apply_pass_band_filter,
    apply_decycler_oscillator,
    apply_universal_oscillator,
    apply_reflex,
    apply_trendflex,
    apply_fisher_transform,
    apply_price_deviation_oscillator,
)

OSCILLATOR_ALGORITHMS = (
    NoiseReductionAlgorithm.PPD_FAST,
    NoiseReductionAlgorithm.PPD_SLOW,
    NoiseReductionAlgorithm.PASS_BAND,
    NoiseReductionAlgorithm.DECYCLER_OSC,
    NoiseReductionAlgorithm.UNIVERSAL_OSC,
    NoiseReductionAlgorithm.REFLEX,
    NoiseReductionAlgorithm.TRENDFLEX,
    NoiseReductionAlgorithm.FISHER,
)


class TestNoiseReduction(unittest.TestCase):
    def setUp(self):
        self.timestamps = [float(i * 86400) for i in range(20)]
        self.prices = [100.0 + (i % 3) * 2.0 + (i * 0.5) for i in range(20)]

    def test_enum_from_str(self):
        self.assertEqual(NoiseReductionAlgorithm.from_str("QuadTree Reduction"), NoiseReductionAlgorithm.QUADTREE)
        self.assertEqual(NoiseReductionAlgorithm.from_str("Exponential Moving Average (EMA)"), NoiseReductionAlgorithm.EMA)
        self.assertEqual(NoiseReductionAlgorithm.from_str("INVALID"), NoiseReductionAlgorithm.NONE)

    def test_enum_from_str_new_algorithms(self):
        self.assertEqual(NoiseReductionAlgorithm.from_str("Exponential MA (EMA 50)"), NoiseReductionAlgorithm.EMA50)
        self.assertEqual(NoiseReductionAlgorithm.from_str("Exponential MA (EMA 200)"), NoiseReductionAlgorithm.EMA200)
        self.assertEqual(NoiseReductionAlgorithm.from_str("Ramer-Douglas-Peucker (Loose)"), NoiseReductionAlgorithm.RPD1)
        self.assertEqual(NoiseReductionAlgorithm.from_str("Ramer-Douglas-Peucker (Tight)"), NoiseReductionAlgorithm.RPD2)
        self.assertEqual(NoiseReductionAlgorithm.from_str("Price Deviation % (Fast)"), NoiseReductionAlgorithm.PPD_FAST)
        self.assertEqual(NoiseReductionAlgorithm.from_str("Price Deviation % (Slow)"), NoiseReductionAlgorithm.PPD_SLOW)
        self.assertEqual(NoiseReductionAlgorithm.from_str("Double EMA (DEMA)"), NoiseReductionAlgorithm.DEMA)
        self.assertEqual(NoiseReductionAlgorithm.from_str("Triple EMA (TEMA)"), NoiseReductionAlgorithm.TEMA)
        self.assertEqual(NoiseReductionAlgorithm.from_str("Hull Moving Average (HMA)"), NoiseReductionAlgorithm.HMA)
        self.assertEqual(NoiseReductionAlgorithm.from_str("Kalman Filter"), NoiseReductionAlgorithm.KALMAN)
        self.assertEqual(NoiseReductionAlgorithm.from_str("Pass-Band Filter (Ehlers)"), NoiseReductionAlgorithm.PASS_BAND)
        self.assertEqual(NoiseReductionAlgorithm.from_str("Ehlers Decycler Oscillator"), NoiseReductionAlgorithm.DECYCLER_OSC)
        self.assertEqual(NoiseReductionAlgorithm.from_str("Ehlers Universal Oscillator"), NoiseReductionAlgorithm.UNIVERSAL_OSC)
        self.assertEqual(NoiseReductionAlgorithm.from_str("Ehlers Reflex"), NoiseReductionAlgorithm.REFLEX)
        self.assertEqual(NoiseReductionAlgorithm.from_str("Ehlers Trendflex"), NoiseReductionAlgorithm.TRENDFLEX)
        self.assertEqual(NoiseReductionAlgorithm.from_str("Ehlers Fisher Transform"), NoiseReductionAlgorithm.FISHER)

    def test_quadtree_reduction(self):
        tx, py = apply_quadtree_reduction(self.timestamps, self.prices)
        self.assertTrue(len(py) > 0)
        self.assertTrue(len(py) <= len(self.prices))

    def test_ema_reduction(self):
        tx, py = apply_ema_reduction(self.timestamps, self.prices, span=5)
        self.assertEqual(len(py), len(self.prices))
        self.assertEqual(tx, self.timestamps)

    def test_ema50_and_ema200(self):
        for algorithm in (NoiseReductionAlgorithm.EMA50, NoiseReductionAlgorithm.EMA200):
            tx, py = reduce_noise(algorithm, self.timestamps, self.prices)
            self.assertEqual(len(py), len(self.prices))
            self.assertEqual(tx, self.timestamps)
            self.assertTrue(all(math.isfinite(v) for v in py))

    def test_savitzky_golay_reduction(self):
        tx, py = apply_savitzky_golay_reduction(self.timestamps, self.prices)
        self.assertEqual(len(py), len(self.prices))

    def test_rdp_reduction(self):
        tx, py = apply_rdp_reduction(self.timestamps, self.prices)
        self.assertTrue(len(py) > 0)
        self.assertTrue(len(py) <= len(self.prices))

    def test_rdp_tolerance_presets(self):
        timestamps = [float(i) for i in range(300)]
        prices = [100.0 + 5.0 * math.sin(i / 5.0) + 0.4 * ((i * 37) % 11 - 5) for i in range(300)]

        _, loose = reduce_noise(NoiseReductionAlgorithm.RPD1, timestamps, prices)
        _, tight = reduce_noise(NoiseReductionAlgorithm.RPD2, timestamps, prices)
        _, default_rdp = reduce_noise(NoiseReductionAlgorithm.DOUGLAS_PEUCKER, timestamps, prices)

        self.assertTrue(len(loose) <= len(default_rdp))
        self.assertTrue(len(default_rdp) <= len(tight))
        self.assertTrue(len(tight) < len(prices))
        for value in loose + tight:
            self.assertIn(value, prices)

    def test_price_deviation_oscillator(self):
        for span in (10, 50):
            tx, py = apply_price_deviation_oscillator(self.timestamps, self.prices, span=span)
            self.assertEqual(len(py), len(self.prices))
            self.assertEqual(tx, self.timestamps)
            self.assertTrue(all(math.isfinite(v) for v in py))

    def test_dema_reduction(self):
        tx, py = apply_dema_reduction(self.timestamps, self.prices, span=5)
        self.assertEqual(len(py), len(self.prices))
        self.assertEqual(tx, self.timestamps)
        self.assertTrue(all(math.isfinite(v) for v in py))

    def test_tema_reduction(self):
        tx, py = apply_tema_reduction(self.timestamps, self.prices, span=5)
        self.assertEqual(len(py), len(self.prices))
        self.assertEqual(tx, self.timestamps)
        self.assertTrue(all(math.isfinite(v) for v in py))

    def test_hma_reduction(self):
        tx, py = apply_hma_reduction(self.timestamps, self.prices, period=8)
        self.assertEqual(len(py), len(self.prices))
        self.assertEqual(tx, self.timestamps)
        self.assertTrue(all(math.isfinite(v) for v in py))

    def test_kalman_filter(self):
        tx, py = apply_kalman_filter(self.timestamps, self.prices)
        self.assertEqual(len(py), len(self.prices))
        self.assertEqual(tx, self.timestamps)
        self.assertTrue(all(math.isfinite(v) for v in py))

    def test_pass_band_filter(self):
        tx, py = apply_pass_band_filter(self.timestamps, self.prices, period=8, bandwidth=0.5)
        self.assertEqual(len(py), len(self.prices))
        self.assertEqual(tx, self.timestamps)
        self.assertTrue(all(math.isfinite(v) for v in py))

    def test_decycler_oscillator(self):
        tx, py = apply_decycler_oscillator(self.timestamps, self.prices, hp_period=25)
        self.assertEqual(len(py), len(self.prices))
        self.assertEqual(tx, self.timestamps)
        self.assertTrue(all(math.isfinite(v) for v in py))

    def test_universal_oscillator(self):
        tx, py = apply_universal_oscillator(self.timestamps, self.prices, band_edge=8)
        self.assertEqual(len(py), len(self.prices))
        self.assertEqual(tx, self.timestamps)
        self.assertTrue(all(math.isfinite(v) for v in py))

    def test_reflex(self):
        tx, py = apply_reflex(self.timestamps, self.prices, length=10)
        self.assertEqual(len(py), len(self.prices))
        self.assertEqual(tx, self.timestamps)
        self.assertTrue(all(math.isfinite(v) for v in py))

    def test_trendflex(self):
        tx, py = apply_trendflex(self.timestamps, self.prices, length=10)
        self.assertEqual(len(py), len(self.prices))
        self.assertEqual(tx, self.timestamps)
        self.assertTrue(all(math.isfinite(v) for v in py))

    def test_fisher_transform(self):
        tx, py = apply_fisher_transform(self.timestamps, self.prices, length=5)
        self.assertEqual(len(py), len(self.prices))
        self.assertEqual(tx, self.timestamps)
        self.assertTrue(all(math.isfinite(v) for v in py))

    def test_oscillators_stay_on_price_scale(self):
        price_range = max(self.prices) - min(self.prices)
        for algorithm in OSCILLATOR_ALGORITHMS:
            tx, py = reduce_noise(algorithm, self.timestamps, self.prices)
            self.assertEqual(len(py), len(self.prices))
            self.assertGreaterEqual(min(py), min(self.prices) - 0.25 * price_range)
            self.assertLessEqual(max(py), max(self.prices) + 0.25 * price_range)

    def test_dispatcher_covers_all_algorithms(self):
        for algorithm in NoiseReductionAlgorithm:
            tx, py = reduce_noise(algorithm, self.timestamps, self.prices)
            self.assertTrue(len(py) > 0)
            self.assertTrue(all(math.isfinite(v) for v in py))

    def test_constant_series_output_is_constant(self):
        timestamps = [float(i) for i in range(40)]
        prices = [100.0] * 40
        for algorithm in NoiseReductionAlgorithm:
            tx, py = reduce_noise(algorithm, timestamps, prices)
            for value in py:
                self.assertAlmostEqual(value, 100.0, places=6)

    def test_short_series_output_is_finite(self):
        timestamps = [float(i) for i in range(5)]
        prices = [100.0 + i for i in range(5)]
        for algorithm in NoiseReductionAlgorithm:
            tx, py = reduce_noise(algorithm, timestamps, prices)
            self.assertTrue(len(py) > 0)
            self.assertTrue(all(math.isfinite(v) for v in py))

    def test_reduce_noise_dispatcher(self):
        tx, py = reduce_noise(NoiseReductionAlgorithm.QUADTREE, self.timestamps, self.prices)
        self.assertTrue(len(py) > 0)

        tx_none, py_none = reduce_noise(NoiseReductionAlgorithm.NONE, self.timestamps, self.prices)
        self.assertEqual(py_none, self.prices)


if __name__ == "__main__":
    unittest.main()
