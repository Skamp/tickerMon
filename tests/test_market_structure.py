import unittest

from app.services.market_structure import (
    EQUITY_TOLERANCE_PCT,
    LABEL_HH,
    LABEL_HL,
    LABEL_LL,
    LABEL_LH,
    STRUCTURE_HIGH,
    STRUCTURE_LOW,
    StructurePoint,
    classify_structure,
    compute_label_positions,
    pivot_kinds,
)


def labels(points):
    return [p.label for p in points]


class TestPivotKinds(unittest.TestCase):
    def test_alternating_high_low(self):
        prices = [100.0, 95.0, 90.0, 92.0, 110.0, 100.0, 95.0, 90.0, 105.0]
        pivots = [0, 2, 4, 6, 8]
        kinds = pivot_kinds(pivots, prices)
        self.assertEqual(kinds, [
            STRUCTURE_HIGH, STRUCTURE_LOW, STRUCTURE_HIGH, STRUCTURE_LOW, STRUCTURE_HIGH,
        ])

    def test_empty_pivots(self):
        self.assertEqual(pivot_kinds([], [1.0, 2.0]), [])

    def test_single_pivot_is_high(self):
        self.assertEqual(pivot_kinds([0], [5.0]), [STRUCTURE_HIGH])

    def test_out_of_range_pair_defaults_to_high(self):
        self.assertEqual(pivot_kinds([0, 99], [5.0, 6.0, 7.0])[0], STRUCTURE_HIGH)


class TestClassifyStructure(unittest.TestCase):
    def setUp(self):
        self.prices = [100.0, 95.0, 90.0, 92.0, 110.0, 100.0, 95.0, 90.0, 105.0]
        self.pivots = [0, 2, 4, 6, 8]

    def test_hh_hl_lh_sequence(self):
        points = classify_structure(self.pivots, self.prices, macro_threshold_pct=1e9)
        self.assertEqual(labels(points), [LABEL_HH, LABEL_HL, LABEL_LH])

    def test_first_of_each_kind_is_unlabeled(self):
        points = classify_structure(self.pivots, self.prices, macro_threshold_pct=1e9)
        self.assertNotIn(0, [p.index for p in points])
        self.assertNotIn(2, [p.index for p in points])

    def test_ll_sequence(self):
        prices = [50.0, 60.0, 45.0, 55.0, 40.0, 50.0, 35.0]
        pivots = [0, 1, 2, 3, 4, 5, 6]
        points = classify_structure(pivots, prices, macro_threshold_pct=1e9)
        self.assertEqual(labels(points), [LABEL_LL, LABEL_LH, LABEL_LL, LABEL_LH, LABEL_LL])

    def test_equality_within_tolerance_gets_no_label(self):
        prices = [100.0, 100.05, 90.0, 95.0, 100.07]
        pivots = [0, 1, 2, 3, 4]
        points = classify_structure(pivots, prices, macro_threshold_pct=1e9)
        self.assertNotIn(LABEL_HH, labels(points))
        self.assertNotIn(LABEL_LH, labels(points))

    def test_difference_beyond_tolerance_gets_label(self):
        prices = [100.0, 100.5, 90.0, 95.0, 101.0]
        pivots = [0, 1, 2, 3, 4]
        points = classify_structure(pivots, prices, macro_threshold_pct=1e9)
        self.assertIn(LABEL_HH, labels(points))

    def test_macro_flag_uses_threshold(self):
        prices = [100.0, 95.0, 90.0, 92.0, 110.0, 100.0, 95.0, 90.0, 105.0]
        pivots = [0, 2, 4, 6, 8]

        small = classify_structure(pivots, prices, macro_threshold_pct=1e9)
        self.assertFalse(any(p.is_macro for p in small))

        large = classify_structure(pivots, prices, macro_threshold_pct=10.0)
        macro_points = {p.index: p for p in large}
        self.assertTrue(macro_points[4].is_macro)
        self.assertTrue(macro_points[6].is_macro)
        self.assertTrue(macro_points[8].is_macro)

    def test_macro_text_combination(self):
        point = StructurePoint(index=4, kind=STRUCTURE_HIGH, label=LABEL_HH, is_macro=True)
        self.assertEqual(point.text, "HH · M")
        normal = StructurePoint(index=4, kind=STRUCTURE_HIGH, label=LABEL_HH, is_macro=False)
        self.assertEqual(normal.text, "HH")

    def test_structural_colors(self):
        bullish = StructurePoint(index=1, kind=STRUCTURE_HIGH, label=LABEL_HH, is_macro=False)
        bearish = StructurePoint(index=2, kind=STRUCTURE_HIGH, label=LABEL_LH, is_macro=False)
        self.assertEqual(bullish.color, "#26c6da")
        self.assertEqual(bearish.color, "#ff7043")

    def test_no_look_ahead_in_prefix(self):
        prices = [100.0, 95.0, 90.0, 92.0, 110.0, 100.0, 95.0, 90.0, 105.0]
        pivots = [0, 2, 4, 6, 8]
        prefix_labels = labels(classify_structure(pivots[:4], prices, macro_threshold_pct=1e9))
        full_labels = labels(classify_structure(pivots, prices, macro_threshold_pct=1e9))
        self.assertEqual(prefix_labels, full_labels[:len(prefix_labels)])

    def test_tolerance_boundary_is_inclusive(self):
        second_high = 100.0 + 100.0 * EQUITY_TOLERANCE_PCT / 100.0
        prices = [100.0, 95.0, second_high, 96.0, 102.0]
        pivots = [0, 1, 2, 3, 4]
        points = classify_structure(pivots, prices, macro_threshold_pct=1e9)
        high_labels = [p.label for p in points if p.kind == STRUCTURE_HIGH]
        self.assertEqual(high_labels, [LABEL_HH])


class TestLabelPositions(unittest.TestCase):
    def setUp(self):
        self.timestamps = [float(i * 86400) for i in range(10)]
        self.prices = [100.0, 99.0, 95.0, 97.0, 105.0, 103.0, 101.0, 98.0, 104.0, 102.0]

    def test_placement_count_matches_points(self):
        points = classify_structure([0, 2, 4, 6, 8], self.prices, macro_threshold_pct=1e9)
        placements = compute_label_positions(points, self.timestamps, self.prices)
        self.assertEqual(len(placements), len(points))

    def test_high_labels_above_and_low_labels_below(self):
        points = classify_structure([0, 2, 4, 6, 8], self.prices, macro_threshold_pct=1e9)
        placements = compute_label_positions(points, self.timestamps, self.prices)
        for (x, y, text, color), point in zip(placements, points):
            pivot_price = self.prices[point.index]
            if point.kind == STRUCTURE_HIGH:
                self.assertGreater(y, pivot_price, text)
            else:
                self.assertLess(y, pivot_price, text)

    def test_empty_points_returns_empty(self):
        self.assertEqual(compute_label_positions([], self.timestamps, self.prices), [])

    def test_out_of_range_points_filtered(self):
        bad = [StructurePoint(index=999, kind=STRUCTURE_HIGH, label=LABEL_HH, is_macro=False)]
        self.assertEqual(compute_label_positions(bad, self.timestamps, self.prices), [])


if __name__ == "__main__":
    unittest.main()
