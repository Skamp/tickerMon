import unittest
from app.services.noise_reduction import (
    NoiseReductionAlgorithm,
    reduce_noise,
    apply_quadtree_reduction,
    apply_ema_reduction,
    apply_savitzky_golay_reduction,
    apply_rdp_reduction,
)


class TestNoiseReduction(unittest.TestCase):
    def setUp(self):
        self.timestamps = [float(i * 86400) for i in range(20)]
        self.prices = [100.0 + (i % 3) * 2.0 + (i * 0.5) for i in range(20)]

    def test_enum_from_str(self):
        self.assertEqual(NoiseReductionAlgorithm.from_str("QuadTree Reduction"), NoiseReductionAlgorithm.QUADTREE)
        self.assertEqual(NoiseReductionAlgorithm.from_str("Exponential Moving Average (EMA)"), NoiseReductionAlgorithm.EMA)
        self.assertEqual(NoiseReductionAlgorithm.from_str("INVALID"), NoiseReductionAlgorithm.NONE)

    def test_quadtree_reduction(self):
        tx, py = apply_quadtree_reduction(self.timestamps, self.prices)
        self.assertTrue(len(py) > 0)
        self.assertTrue(len(py) <= len(self.prices))

    def test_ema_reduction(self):
        tx, py = apply_ema_reduction(self.timestamps, self.prices, span=5)
        self.assertEqual(len(py), len(self.prices))
        self.assertEqual(tx, self.timestamps)

    def test_savitzky_golay_reduction(self):
        tx, py = apply_savitzky_golay_reduction(self.timestamps, self.prices)
        self.assertEqual(len(py), len(self.prices))

    def test_rdp_reduction(self):
        tx, py = apply_rdp_reduction(self.timestamps, self.prices)
        self.assertTrue(len(py) > 0)
        self.assertTrue(len(py) <= len(self.prices))

    def test_reduce_noise_dispatcher(self):
        tx, py = reduce_noise(NoiseReductionAlgorithm.QUADTREE, self.timestamps, self.prices)
        self.assertTrue(len(py) > 0)

        tx_none, py_none = reduce_noise(NoiseReductionAlgorithm.NONE, self.timestamps, self.prices)
        self.assertEqual(py_none, self.prices)


if __name__ == "__main__":
    unittest.main()
