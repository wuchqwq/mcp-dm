#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Hand-checkable synthetic spectroscopy tests; no DM, socket or real data."""

import importlib.util
import json
import os
import unittest
from unittest import mock

import numpy as np


PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bridge", "spectroscopy.py"))
spec = importlib.util.spec_from_file_location("spectroscopy_core_test_subject", PATH)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


def calibration(shape, energy_axis, zero=-2.0, step=0.5, unit="eV"):
    records = []
    for axis, size in enumerate(shape):
        records.append({"numpy_axis": axis, "dm_dimension": len(shape) - 1 - axis,
                        "axis": "axis%d" % axis, "size": size,
                        "unit": unit if axis == energy_axis else "nm",
                        "scale": step if axis == energy_axis else 0.25,
                        "origin": 999,  # Deliberately not the physical zero.
                        "calibrated_value_at_pixel_zero": zero if axis == energy_axis else 10.0 + axis})
    return records


class SpectroscopyCoreTests(unittest.TestCase):
    def test_offset_energy_and_raw_channels(self):
        a = np.array([1, 3, 7, 9], dtype=np.uint32)
        r = core.extract_spectrum(a, calibration(a.shape, 0), 0)
        self.assertEqual(r["energy_eV"], [-2.0, -1.5, -1.0, -0.5])
        self.assertEqual(r["intensity"], [1.0, 3.0, 7.0, 9.0])
        self.assertEqual(r["channel_indices"], [0, 1, 2, 3])
        self.assertTrue(r["experimental"])
        self.assertTrue(r["no_quantification_performed"])
        self.assertEqual(r["validation_scope"]["real_eds"], "NOT_TESTED")
        self.assertEqual(r["validation_scope"]["real_eels"], "NOT_TESTED")
        self.assertEqual(r["validation_scope"]["real_si"], "NOT_TESTED")
        json.dumps(r, allow_nan=False)

    def test_kev_conversion_negative_step_order(self):
        a = np.array([10, 20, 30, 40], dtype=np.int32)
        # Binary-exact inputs keep strict center-boundary assertions distinct
        # from decimal-to-float representation error.
        c = calibration(a.shape, 0, zero=1.0, step=-0.125, unit="keV")
        r = core.extract_spectrum(a, c, 0, energy_window_eV=[625, 875])
        self.assertEqual(r["channel_indices"], [2, 3])
        np.testing.assert_allclose(r["energy_eV"], [750, 625], rtol=0, atol=0)
        self.assertEqual(r["intensity"], [30, 40])
        self.assertEqual(core.integrate_window(a, c, 0, [625, 1125])["integrated_values"], 100)

    def test_channel_center_half_open_and_no_binwidth_factor(self):
        a = np.array([2, 5, 11, 17], dtype=np.float32)
        c = calibration(a.shape, 0, zero=10, step=2)
        r = core.integrate_window(a, c, 0, [12, 16])
        self.assertEqual(r["selected_channel_indices"], [1, 2])
        self.assertEqual(r["selected_energy_eV"], [12, 14])
        self.assertEqual(r["integrated_values"], 16)
        self.assertEqual(r["output_shape"], [])
        self.assertEqual(r["output_axes"], [])
        self.assertEqual(core.integrate_window(a, c, 0, [16, 18])["integrated_values"], 17)

    def test_non_square_spatial_roi_sum_mean_and_source_invariance(self):
        a = np.arange(3 * 5 * 4, dtype=np.uint32).reshape(3, 5, 4)
        before = a.copy()
        c = calibration(a.shape, 2, zero=100, step=1)
        r = core.extract_spectrum(a, c, 2, [[1, 3], [1, 4]])
        self.assertEqual(r["intensity"], [228, 234, 240, 246])
        self.assertEqual(r["selected_shape"], [2, 3, 4])
        self.assertEqual(r["selected_elements"], 24)
        mean = core.extract_spectrum(a, c, 2, [[1, 3], [1, 4]], "mean")
        self.assertEqual(mean["intensity"], [38, 39, 40, 41])
        integrated = core.integrate_window(a, c, 2, [101, 103], [[1, 3], [1, 4]])
        self.assertEqual(integrated["integrated_values"], [[51, 59, 67], [91, 99, 107]])
        self.assertEqual(integrated["output_shape"], [2, 3])
        self.assertEqual(integrated["output_axes"][0]["calibrated_value_at_pixel_zero"], 10.25)
        self.assertEqual(integrated["output_axes"][1]["calibrated_value_at_pixel_zero"], 11.25)
        self.assertNotIn("origin", integrated["output_axes"][0])
        np.testing.assert_array_equal(a, before)

    def test_explicit_energy_axis_all_transposes(self):
        source = np.arange(2 * 3 * 5, dtype=np.int16).reshape(2, 3, 5)
        expected = source.sum(axis=(0, 1)).tolist()
        expected_map = source[..., 1:4].sum(axis=2)
        for axis in (0, 1, 2):
            a = np.moveaxis(source, 2, axis)
            c = calibration(a.shape, axis, zero=0, step=1)
            r = core.extract_spectrum(a, c, axis)
            self.assertEqual(r["intensity"], expected)
            got = core.integrate_window(a, c, axis, [1, 4])
            np.testing.assert_array_equal(got["integrated_values"], expected_map)
            self.assertEqual([v["source_numpy_axis"] for v in got["output_axes"]], [v for v in range(3) if v != axis])

    def test_line_spectra(self):
        a = np.array([[2, 4, 8], [10, 20, 30]], dtype=np.float32)
        c = calibration(a.shape, 1, zero=0, step=1)
        self.assertEqual(core.extract_spectrum(a, c, 1)["intensity"], [12, 24, 38])
        self.assertEqual(core.integrate_window(a, c, 1, [0, 2])["integrated_values"], [6, 30])

    def test_info_never_allocates_pixels_and_exposes_over_limit(self):
        shape = (100000, 100000, 4096)
        r = core.spectrum_info(shape, calibration(shape, 2), 2, max_elements=10)
        self.assertEqual(r["selected_elements"], 40960000000000)
        self.assertFalse(r["within_work_limit"])
        self.assertEqual(len(r["source_axes"]), 3)
        self.assertEqual(r["source_axes"][2]["role"], "energy")

    def test_shape_only_selection_rejects_huge_work_without_source_or_vectors(self):
        shape = (100000, 100000, 4096)
        with mock.patch.object(core.np, "arange", side_effect=AssertionError("coordinate vector allocated")), \
                mock.patch.object(core.np, "asarray", side_effect=AssertionError("source array allocated")):
            with self.assertRaisesRegex(ValueError, "Selected work"):
                core.validate_selection(shape, calibration(shape, 2), 2)
            # A huge source is usable when the explicit selection is small.
            r = core.validate_selection(shape, calibration(shape, 2, zero=0, step=1), 2,
                                        spatial_bounds=[[100, 102], [200, 203]],
                                        energy_window_eV=[10, 15], max_elements=30)
        self.assertEqual(r["selected_shape"], [2, 3, 5])
        self.assertEqual(r["selected_elements"], 30)
        self.assertEqual(r["selected_channel_range"], [10, 15])
        self.assertEqual(r["validation_scope"]["real_si"], "NOT_TESTED")

    def test_shape_only_selection_uses_window_before_work_guard(self):
        shape = (1000, 1000, 10000)
        c = calibration(shape, 2, zero=0, step=1)
        with self.assertRaisesRegex(ValueError, "Selected work"):
            core.validate_selection(shape, c, 2, max_elements=1000000)
        r = core.validate_selection(shape, c, 2, energy_window_eV=[25, 26], max_elements=1000000)
        self.assertEqual(r["selected_shape"], [1000, 1000, 1])
        self.assertEqual(r["selected_elements"], 1000000)

    def test_shape_only_output_limits_match_pixel_functions(self):
        shape = (16385,)
        c = calibration(shape, 0, zero=0, step=1)
        for kind in ("spectrum", "map"):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "16384 channels"):
                core.validate_selection(shape, c, 0, energy_window_eV=[0, 16385], output_kind=kind)
        shape = (513, 512, 1)
        with self.assertRaisesRegex(ValueError, "262144 map"):
            core.validate_selection(shape, calibration(shape, 2), 2,
                                    energy_window_eV=[-2, -1.5], output_kind="map")
        with self.assertRaisesRegex(ValueError, "explicit energy_window"):
            core.validate_selection((3,), calibration((3,), 0), 0, output_kind="map")
        with self.assertRaisesRegex(ValueError, "output_kind"):
            core.validate_selection((3,), calibration((3,), 0), 0, output_kind="image")

    def test_four_dimensional_diffraction_refused(self):
        with self.assertRaisesRegex(ValueError, "4D diffraction"):
            core.spectrum_info((2, 3, 4, 5), calibration((2, 3, 4, 5), 3), 3)

    def test_axis_and_shape_validation(self):
        for axis in (-1, 2, True, 1.0, "1", None):
            with self.subTest(axis=axis), self.assertRaises(ValueError):
                core.spectrum_info((2, 3), calibration((2, 3), 1), axis)
        for shape in ((), (0,), (2.0,), (True,), (1, 1, 1, 1)):
            with self.subTest(shape=shape), self.assertRaises(ValueError):
                core.spectrum_info(shape, [], 0)

    def test_energy_calibration_never_guessed(self):
        a = np.ones((2, 3))
        c = calibration(a.shape, 1)
        invalid = []
        for field, value in (("unit", "nm"), ("unit", "EV"), ("unit", None), ("scale", 0),
                             ("scale", float("nan")), ("scale", float("inf")),
                             ("calibrated_value_at_pixel_zero", None), ("calibrated_value_at_pixel_zero", float("nan"))):
            copied = [dict(v) for v in c]
            copied[1][field] = value
            invalid.append(copied)
        invalid.append(c[:1])
        invalid.append(c + [dict(c[1])])
        wrong_size = [dict(v) for v in c]
        wrong_size[1]["size"] = 4
        invalid.append(wrong_size)
        for record in invalid:
            with self.subTest(calibration=record), self.assertRaises(ValueError):
                core.extract_spectrum(a, record, 1)

    def test_missing_spatial_calibration_explicitly_unknown(self):
        a = np.ones((2, 3))
        c = calibration(a.shape, 1)[1:]
        r = core.integrate_window(a, c, 1, [-2, -0.5])
        self.assertFalse(r["output_axes"][0]["available"])
        self.assertIn("No calibration", r["output_axes"][0]["reason"])

    def test_bounds_are_strict_and_never_clamped(self):
        a = np.ones((3, 5, 4))
        c = calibration(a.shape, 2)
        for bounds in ([[0, 3]], [[-1, 2], [0, 5]], [[0, 4], [0, 5]],
                       [[2, 2], [0, 5]], [[0, 3.0], [0, 5]], [[0, True], [0, 5]],
                       [[0, 3], [5, 4]], [[0, 3], [0, 5], [0, 4]]):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                core.extract_spectrum(a, c, 2, bounds)

    def test_window_bounds_and_empty_channels(self):
        a = np.ones(4)
        c = calibration(a.shape, 0, zero=10, step=2)
        for window in ([9, 12], [10, 18.01], [12, 12], [14, 12], [10.1, 11.9],
                       [float("nan"), 12], [10, float("inf")], [True, 12], [10], "10,12"):
            with self.subTest(window=window), self.assertRaises(ValueError):
                core.integrate_window(a, c, 0, window)
        with self.assertRaises(ValueError):
            core.integrate_window(a, c, 0, None)

    def test_selected_finite_only_and_no_source_mutation(self):
        a = np.array([[1, 2, 3], [float("nan"), 4, 5]], dtype=np.float64)
        c = calibration(a.shape, 1)
        self.assertEqual(core.extract_spectrum(a, c, 1, [[0, 1]])["intensity"], [1, 2, 3])
        self.assertEqual(core.extract_spectrum(a, c, 1, energy_window_eV=[-1.5, -0.5])["intensity"], [6, 8])
        with self.assertRaisesRegex(ValueError, "NaN or Inf"):
            core.extract_spectrum(a, c, 1)
        self.assertTrue(np.isnan(a[1, 0]))
        for dtype in (np.complex64, object, np.bool_, np.dtype([("r", "u1"), ("g", "u1"), ("b", "u1")])):
            source = np.zeros(3, dtype=dtype)
            with self.subTest(dtype=dtype), self.assertRaises(ValueError):
                core.extract_spectrum(source, calibration(source.shape, 0), 0)

    def test_guards_before_copy_or_reduction(self):
        a = np.zeros((3, 5, 4), dtype=np.uint32)
        c = calibration(a.shape, 2)
        with self.assertRaisesRegex(ValueError, "Selected work"):
            core.extract_spectrum(a, c, 2, max_elements=59)
        # Narrow windows reduce selected work before the limit is checked.
        self.assertEqual(core.extract_spectrum(a, c, 2, energy_window_eV=[-2, -1.5], max_elements=15)["selected_elements"], 15)
        long = np.zeros(16385, dtype=np.uint8)
        with self.assertRaisesRegex(ValueError, "16384 channels"):
            core.extract_spectrum(long, calibration(long.shape, 0), 0)
        with self.assertRaisesRegex(ValueError, "16384 channels"):
            core.integrate_window(long, calibration(long.shape, 0), 0, [-2, 8190.5])
        bigmap = np.zeros((513, 512, 1), dtype=np.uint8)
        with self.assertRaisesRegex(ValueError, "262144 map"):
            core.integrate_window(bigmap, calibration(bigmap.shape, 2), 2, [-2, -1.5])

    def test_integer_exactness_guards(self):
        safe = np.array([2 ** 53], dtype=np.uint64)
        self.assertEqual(core.extract_spectrum(safe, calibration(safe.shape, 0), 0)["intensity"], [float(2 ** 53)])
        too_large = np.array([2 ** 53 + 1], dtype=np.uint64)
        with self.assertRaisesRegex(ValueError, "Integer source magnitude"):
            core.extract_spectrum(too_large, calibration(too_large.shape, 0), 0)
        sum_large = np.full((2, 3), 2 ** 52 + 1, dtype=np.int64)
        with self.assertRaisesRegex(ValueError, "Integer accumulation"):
            core.extract_spectrum(sum_large, calibration(sum_large.shape, 1), 1)
        with self.assertRaisesRegex(ValueError, "Integer accumulation"):
            core.extract_spectrum(sum_large, calibration(sum_large.shape, 1), 1, reduction="mean")
        with self.assertRaisesRegex(ValueError, "Integer accumulation"):
            core.integrate_window(sum_large, calibration(sum_large.shape, 1), 1, [-2, -0.5])

    def test_nonfinite_float_accumulation_refused(self):
        a = np.full((2, 3), 1e308, dtype=np.float64)
        with self.assertRaisesRegex(ValueError, "reduction overflowed"):
            core.extract_spectrum(a, calibration(a.shape, 1), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
