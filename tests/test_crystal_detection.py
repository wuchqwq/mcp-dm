"""Independent sparse-pattern truth; no DM, indexing or phase confirmation."""
import json
import unittest

import numpy as np

from crystallography.detection import MAX_ARRAY_BYTES, detect_spots


def pattern(shape, points, heights=None, noise=0., seed=12):
    y, x = np.indices(shape, dtype=np.float64)
    values = np.zeros(shape, dtype=np.float64) + 2.
    for (px, py), height in zip(points, heights or [20.]*len(points)):
        values += height * np.exp(-((x-px)**2+(y-py)**2)/(2*.65**2))
    if noise:
        values += np.random.default_rng(seed).normal(0, noise, shape)
    return values.astype("float32")


def prescribed_power(modes, dc=1e4, reflection=1.):
    """Independent known bins, not a detector-generated Fourier reference."""
    values = np.zeros((256, 256), dtype="float32")
    values[128, 128] = dc
    points = []
    for x, y in modes:
        for sign in (-1, 1):
            px, py = 128+sign*x, 128+sign*y
            values[py, px] = reflection
            points.append([px, py])
    return values, np.asarray(points)


class CrystalDetection(unittest.TestCase):
    center = np.array([34.25, 28.5])
    offsets = np.array([[11., 3.], [-4., 12.], [14., -9.], [-11., -3.], [4., -12.], [-14., 9.]])

    def points(self, center=None):
        return self.offsets + (self.center if center is None else center)

    def assert_points(self, result, expected, tolerance=.18):
        actual = np.asarray([point["xy"] for point in result["spots"]])
        self.assertEqual(len(actual), len(expected))
        for point in expected:
            self.assertLess(float(np.min(np.linalg.norm(actual-point, axis=1))), tolerance)

    def test_sparse_symmetric_pattern_estimates_non_midpoint_center_and_all_spots(self):
        expected = self.points()
        array = pattern((64, 80), expected.tolist())
        before = array.tobytes()
        result = detect_spots(array)
        self.assertEqual(result["status"], "READY", result["diagnostics"])
        np.testing.assert_allclose(result["center_xy"], self.center, atol=.12)
        self.assert_points(result, expected)
        self.assertEqual(result["diagnostics"]["center_evidence"]["independent_opposite_pairs"], 3)
        self.assertTrue(all(point["sigma_px"] is None for point in result["spots"]))
        self.assertIsNone(result["diagnostics"]["center_evidence"]["sigma_px"])
        self.assertEqual(array.tobytes(), before)
        exclusion = result["diagnostics"]["prelocalization_center_exclusion"]
        self.assertFalse(exclusion["applied"])
        self.assertEqual(exclusion["reason"], "NO_EXPLICIT_CENTER")
        self.assertIsNone(exclusion["center_xy"])

    def test_optional_bright_beam_does_not_set_threshold_or_count_as_reflection(self):
        expected = self.points()
        points = expected.tolist() + [self.center.tolist()]
        array = pattern((64, 80), points, [20, 30, 15, 18, 28, 14, 2000])
        result = detect_spots(array)
        self.assertEqual(result["status"], "READY", result["diagnostics"])
        np.testing.assert_allclose(result["center_xy"], self.center, atol=.12)
        self.assert_points(result, expected)
        self.assertEqual(result["diagnostics"]["excluded_radius_candidates"], 1)

    def test_noise_and_unequal_opposite_intensities_keep_limited_center_truth(self):
        expected = self.points()
        array = pattern((64, 80), expected.tolist(), [20, 30, 15, 10, 16, 25], noise=.3)
        result = detect_spots(array)
        self.assertEqual(result["status"], "READY", result["diagnostics"])
        np.testing.assert_allclose(result["center_xy"], self.center, atol=.2)
        self.assert_points(result, expected, tolerance=.3)

    def test_asymmetric_missing_pair_does_not_invent_center(self):
        result = detect_spots(pattern((64, 80), self.points()[:-1].tolist()))
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertIsNone(result["center_xy"])
        self.assertEqual(result["spots"], [])

    def test_collinear_three_pairs_cannot_determine_qualified_auto_center(self):
        points = [[15, 25], [25, 25], [35, 25], [45, 25], [55, 25], [65, 25]]
        result = detect_spots(pattern((60, 80), points))
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertIsNone(result["center_xy"])

    def test_two_disconnected_symmetric_patterns_are_not_one_trusted_center(self):
        points = np.concatenate([self.points([25, 30]), self.points([85, 30])])
        result = detect_spots(pattern((70, 120), points.tolist()))
        self.assertEqual(result["status"], "NEEDS_REVIEW", result["diagnostics"])
        self.assertIsNone(result["center_xy"])

    def test_translated_competing_centers_with_strong_partial_coverage_require_review(self):
        # Four-by-two spots support 4 pairs at [40,24] and 3 independent pairs
        # at each neighbouring centre [32,24], [48,24]. Geometry is ambiguous.
        points = [[x, y] for x in (16., 32., 48., 64.) for y in (16., 32.)]
        result = detect_spots(pattern((50, 80), points))
        self.assertEqual(result["status"], "NEEDS_REVIEW", result["diagnostics"])
        self.assertIsNone(result["center_xy"])
        self.assertIn("AMBIGUOUS_FRIEDEL_CENTERS", result["diagnostics"]["reasons"])

    def test_cropped_pattern_can_use_declared_center_outside_array(self):
        expected = np.array([[8.2, 7.], [15.5, 11.25], [20., 4.5]])
        array = pattern((24, 30), expected.tolist())
        result = detect_spots(array, center_xy=[-6., 3.])
        self.assertEqual(result["status"], "READY", result["diagnostics"])
        self.assertEqual(result["center_xy"], [-6., 3.])
        self.assert_points(result, expected)
        exclusion = result["diagnostics"]["prelocalization_center_exclusion"]
        self.assertFalse(exclusion["applied"])
        self.assertEqual(exclusion["masked_pixels"], 0)
        self.assertEqual(exclusion["reason"], "DISK_OUTSIDE_CAPTURE")
        automatic = detect_spots(array)
        self.assertEqual(automatic["status"], "NEEDS_REVIEW")

    def test_provided_center_is_preserved_and_brightest_offcenter_spot_is_not_beam(self):
        expected = self.points()
        array = pattern((64, 80), expected.tolist(), [2000, 30, 15, 10, 16, 25])
        result = detect_spots(array, center_xy=self.center.tolist())
        self.assertEqual(result["status"], "READY", result["diagnostics"])
        self.assertEqual(result["center_xy"], self.center.tolist())
        self.assert_points(result, expected)

    def test_known_dc_mask_recovers_prescribed_near_dc_bins(self):
        array, expected = prescribed_power([(3, 0), (0, 4), (3, 4)])
        before = array.tobytes()
        # These neighbours are three pixels apart: one-pixel localization
        # patches resolve them independently of the DC-removal test.
        result = detect_spots(array, center_xy=[128., 128.], min_distance=1)
        self.assertEqual(result["status"], "READY", result["diagnostics"])
        self.assert_points(result, expected, tolerance=.02)
        self.assertEqual(array.tobytes(), before)
        exclusion = result["diagnostics"]["prelocalization_center_exclusion"]
        self.assertTrue(exclusion["applied"])
        self.assertEqual(exclusion["center_xy"], [128., 128.])
        self.assertEqual(exclusion["radius_px"], 2)
        self.assertEqual(exclusion["masked_pixels"], 13)
        self.assertEqual(exclusion["replacement_normalized"], 0.)
        self.assertIn("working copy only", exclusion["scope"])
        self.assertIn("explicit-centre disk", result["method"])

    def test_known_dc_mask_preserves_far_bins_at_default_resolution(self):
        array, expected = prescribed_power([(13, 0), (0, 17), (9, 11)], dc=1e10)
        result = detect_spots(array, center_xy=[128., 128.])
        self.assertEqual(result["status"], "READY", result["diagnostics"])
        self.assert_points(result, expected, tolerance=1e-8)

    def test_normalization_uses_faint_surviving_pixels_not_huge_excluded_dc(self):
        array, expected = prescribed_power([(13, 0), (0, 17), (9, 11)], dc=1e30, reflection=1e-20)
        before = array.tobytes(); array.flags.writeable = False
        result = detect_spots(array, center_xy=[128., 128.])
        self.assertEqual(result["status"], "READY", result["diagnostics"])
        self.assert_points(result, expected, tolerance=1e-8)
        self.assertEqual(result["diagnostics"]["working_intensity_scale"], float(np.float32(1e-20)))
        self.assertEqual(array.tobytes(), before)
        self.assertFalse(array.flags.writeable)
        self.assertFalse(result["diagnostics"]["original_pixels_changed"])
        json.dumps(result, allow_nan=False)

    def test_signed_float64_source_and_view_are_never_modified_by_mask(self):
        expected = self.points()
        backing = np.asarray(pattern((64, 80), expected.tolist()), dtype="float64")-9.
        backing[29, 34] = -1e300
        array = backing.view(); before = backing.tobytes()
        result = detect_spots(array, center_xy=self.center.tolist())
        self.assertEqual(result["status"], "READY", result["diagnostics"])
        self.assert_points(result, expected)
        self.assertEqual(backing.tobytes(), before)
        self.assertEqual(array.tobytes(), before)
        self.assertEqual(array.dtype, np.dtype("float64"))
        self.assertTrue(result["diagnostics"]["prelocalization_center_exclusion"]["applied"])

    def test_entire_capture_excluded_returns_review_without_invented_spots(self):
        array = np.ones((4, 4), dtype="float32"); before = array.tobytes()
        result = detect_spots(array, center_xy=[1.5, 1.5], exclude_radius=10)
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertEqual(result["spots"], [])
        self.assertIn("NO_UNMASKED_LOCALIZATION_PIXELS", result["diagnostics"]["reasons"])
        self.assertEqual(result["diagnostics"]["prelocalization_center_exclusion"]["masked_pixels"], 16)
        self.assertEqual(array.tobytes(), before)

    def test_zero_surviving_power_returns_review_not_dc_reflection(self):
        array = np.zeros((32, 32), dtype="float32"); array[16, 16] = 1e30
        before = array.tobytes()
        result = detect_spots(array, center_xy=[16, 16])
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertEqual(result["spots"], [])
        self.assertIn("NO_POSITIVE_PEAK_CONTRAST", result["diagnostics"]["reasons"])
        self.assertEqual(result["diagnostics"]["working_intensity_scale"], 0.)
        self.assertEqual(array.tobytes(), before)

    def test_output_budget_keeps_complete_pairs(self):
        result = detect_spots(pattern((64, 80), self.points().tolist()), max_spots=5)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(len(result["spots"]), 4)
        points = np.asarray([point["xy"] for point in result["spots"]])
        center = np.asarray(result["center_xy"])
        for point in points:
            self.assertLess(float(np.min(np.linalg.norm(points-(2*center-point), axis=1))), .2)

    def test_readonly_uint32_and_large_finite_float64_are_not_modified_or_nonfinite(self):
        array = np.rint(pattern((64, 80), self.points().tolist())*10000000).astype("uint32")
        before = array.tobytes(); array.flags.writeable = False
        result = detect_spots(array)
        self.assertEqual(result["status"], "READY", result["diagnostics"])
        self.assertEqual(array.tobytes(), before)
        large = pattern((64, 80), self.points().tolist()).astype("float64")*1e306
        result = detect_spots(large)
        self.assertEqual(result["status"], "READY", result["diagnostics"])
        json.dumps(result, allow_nan=False)

    def test_constant_noise_edge_and_unresolved_plateau_return_review(self):
        arrays = [np.ones((32, 32), dtype="float32"),
                  np.random.default_rng(7).normal(size=(32, 32)).astype("float32"),
                  pattern((32, 32), [[0, 0], [31, 31], [1, 20], [20, 1]])]
        for array in arrays:
            with self.subTest(array=str(array.shape)):
                result = detect_spots(array)
                self.assertEqual(result["status"], "NEEDS_REVIEW")
                self.assertIsNone(result["center_xy"])

    def test_malformed_arrays_and_options_fail_without_success(self):
        array = pattern((64, 80), self.points().tolist())
        for bad in (array[0], array.astype("complex64"), np.array([[np.nan]], dtype="float32"),
                    np.zeros((MAX_ARRAY_BYTES//4+1, 1), dtype="float32")):
            with self.subTest(shape=bad.shape), self.assertRaises(ValueError):
                detect_spots(bad)
        for options in ({"max_spots": True}, {"max_spots": 33}, {"min_distance": 0}, {"threshold_rel": 0},
                        {"threshold_rel": float("nan")}, {"exclude_radius": -1},
                        {"center_tolerance_px": 0}, {"center_xy": [True, 2]}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                detect_spots(array, **options)


if __name__ == "__main__":
    unittest.main()
