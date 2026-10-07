import unittest

from app.ui.volume_chart_widget import (
    classify_volume_pressure,
    compute_bar_width,
    format_volume,
    PRESSURE_BUYING,
    PRESSURE_NEUTRAL,
    PRESSURE_SELLING,
)


class TestVolumeChartHelpers(unittest.TestCase):
    def test_format_volume(self):
        self.assertEqual(format_volume(1200), "1.2K")
        self.assertEqual(format_volume(3500000), "3.5M")
        self.assertEqual(format_volume(12450000), "12.45M")
        self.assertEqual(format_volume(2100000000), "2.1B")
        self.assertEqual(format_volume(999), "999")
        self.assertEqual(format_volume(0), "0")
        self.assertEqual(format_volume(float("nan")), "0")
        self.assertEqual(format_volume(None), "0")

    def test_classify_volume_pressure(self):
        self.assertEqual(classify_volume_pressure(100.0, 101.0), PRESSURE_BUYING)
        self.assertEqual(classify_volume_pressure(101.0, 100.0), PRESSURE_SELLING)
        self.assertEqual(classify_volume_pressure(100.0, 100.0), PRESSURE_NEUTRAL)
        self.assertEqual(classify_volume_pressure(0.0, 100.0), PRESSURE_NEUTRAL)
        self.assertEqual(classify_volume_pressure(100.0, 0.0), PRESSURE_NEUTRAL)
        self.assertEqual(classify_volume_pressure(None, 100.0), PRESSURE_NEUTRAL)
        self.assertEqual(classify_volume_pressure(100.0, float("nan")), PRESSURE_NEUTRAL)

    def test_compute_bar_width(self):
        day = 86400.0
        timestamps = [day * i for i in range(5)]
        self.assertAlmostEqual(compute_bar_width(timestamps), day * 0.7)
        self.assertGreater(compute_bar_width([1.0]), 0.0)
        self.assertAlmostEqual(compute_bar_width([]), day * 0.7)


if __name__ == "__main__":
    unittest.main()
