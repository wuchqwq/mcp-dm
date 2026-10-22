#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Synthetic-only explicit-axis, bounded-memory 4D-STEM arithmetic tests."""

import importlib.util
import itertools
import os
import tempfile
import unittest

import numpy as np


PATH = os.path.join(os.path.dirname(__file__), "..", "bridge", "fourdstem.py")
SPEC = importlib.util.spec_from_file_location("fourdstem_test_subject", PATH)
fourdstem = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fourdstem)


def calibration(shape, scales=(0.4, 0.2, 1.0, 1.0), zeros=(2., 3., -2., -2.)):
    return [{"numpy_axis": axis, "size": size, "scale": scales[axis],
             "calibrated_value_at_pixel_zero": zeros[axis],
             "unit": "nm" if axis < 2 else "1/nm"}
            for axis, size in enumerate(shape)]


DETECTORS = [{"label": "BF", "center_q": [0., 0.], "r_inner": 0., "r_outer": 1.},
             {"label": "ADF", "center_q": [0., 0.], "r_inner": 1., "r_outer": 2.}]


class GuardedArray(object):
    """A source provider which fails on whole-cube conversion or large reads."""
    def __init__(self, array, max_patterns):
        self.array = array
        self.shape = array.shape
        self.dtype = array.dtype
        self.max_patterns = max_patterns
        self.reads = []

    def __array__(self, *args, **kwargs):
        raise AssertionError("whole source conversion is forbidden")

    def __getitem__(self, selectors):
        if len(selectors) != 4 or sum(isinstance(value, int) for value in selectors) != 1:
            raise AssertionError("source reads must fix exactly one scan-row axis")
        selected = self.array[selectors]
        patterns = selected.size // 25
        if patterns > self.max_patterns:
            raise AssertionError("source read exceeds chunk pattern limit")
        self.reads.append((selectors, selected.nbytes))
        return selected


class FourDSTEMTests(unittest.TestCase):
    def setUp(self):
        self.array = np.arange(3 * 4 * 5 * 5, dtype=np.uint16).reshape(3, 4, 5, 5)
        self.cal = calibration(self.array.shape)

    def calculate(self, array=None, cal=None, bounds=None, detectors=None, **kwargs):
        return fourdstem.virtual_detectors(
            self.array if array is None else array, self.cal if cal is None else cal,
            [0, 1], [2, 3], bounds, DETECTORS if detectors is None else detectors, **kwargs)

    def test_hand_enumerated_masks(self):
        result = self.calculate(bounds=[[1, 3], [1, 4]], chunk_patterns=2)
        # BF selects only centre (2,2); ADF selects its eight neighbours.
        source = self.array[1:3, 1:4]
        expected_bf = np.array([[137, 162, 187], [237, 262, 287]], dtype=np.uint64)
        expected_adf = np.array([[1096, 1296, 1496], [1896, 2096, 2296]], dtype=np.uint64)
        np.testing.assert_array_equal(result["maps"]["BF"], expected_bf)
        np.testing.assert_array_equal(result["maps"]["ADF"], expected_adf)
        np.testing.assert_array_equal(result["total_counts"], source.sum(axis=(2, 3), dtype=np.uint64))
        np.testing.assert_array_equal(result["mean_dp"], source.mean(axis=(0, 1)))
        self.assertEqual([item["selected_pixels"] for item in result["detector_metadata"]], [1, 8])
        self.assertEqual(result["maps"]["BF"].dtype, np.dtype("uint64"))

    def test_all_axis_permutations_and_requested_scan_order(self):
        expected = self.calculate(bounds=[[0, 2], [1, 4]])
        for permutation in itertools.permutations(range(4)):
            source = self.array.transpose(permutation)
            records = []
            for new_axis, old_axis in enumerate(permutation):
                record = dict(self.cal[old_axis])
                record["numpy_axis"] = new_axis
                records.append(record)
            axes = [permutation.index(axis) for axis in range(4)]
            actual = fourdstem.virtual_detectors(source, records, axes[:2], axes[2:],
                                                 [[0, 2], [1, 4]], DETECTORS, chunk_patterns=2)
            for label in ("BF", "ADF"):
                np.testing.assert_array_equal(actual["maps"][label], expected["maps"][label])
            np.testing.assert_array_equal(actual["mean_dp"], expected["mean_dp"])

    def test_scan_axes_reversed(self):
        result = fourdstem.virtual_detectors(self.array, self.cal, [1, 0], [2, 3],
                                             [[1, 4], [0, 2]], DETECTORS)
        normal = self.calculate(bounds=[[0, 2], [1, 4]])
        np.testing.assert_array_equal(result["maps"]["BF"], normal["maps"]["BF"].T)
        self.assertEqual(result["scan_shape"], [3, 2])

    def test_anisotropic_negative_q_and_scan_scale(self):
        shape = (2, 3, 5, 7)
        source = np.ones(shape, dtype=np.uint8)
        cal = calibration(shape, scales=(-.2, .3, -.5, 1.), zeros=(4., 5., 1., -3.))
        detectors = [{"label": "elliptical_in_pixels", "center_q": [0., 0.], "r_inner": 0., "r_outer": 1.2}]
        result = self.calculate(source, cal, [[1, 2], [1, 3]], detectors)
        # qx=0 has five qy centres; qx=+-1 adds three each => 11.
        np.testing.assert_array_equal(result["maps"]["elliptical_in_pixels"], [[11, 11]])
        self.assertAlmostEqual(result["scan_calibration"][0]["calibrated_value_at_pixel_zero"], 3.8)
        self.assertAlmostEqual(result["scan_calibration"][1]["calibrated_value_at_pixel_zero"], 5.3)

    def test_disjoint_detectors_plus_outside_conserve_counts(self):
        result = self.calculate()
        outside = np.ones((5, 5), dtype=bool)
        outside[1:4, 1:4] = False
        expected_outside = self.array[:, :, outside].sum(axis=2, dtype=np.uint64)
        np.testing.assert_array_equal(result["maps"]["BF"] + result["maps"]["ADF"] + expected_outside,
                                      result["total_counts"])

    def test_source_invariant_and_chunk_guard(self):
        source = self.array.copy()
        source.flags.writeable = False
        guard = GuardedArray(source, 2)
        result = self.calculate(guard, chunk_patterns=2)
        np.testing.assert_array_equal(source, self.array)
        self.assertEqual(result["chunking"]["read_count"], 6)
        self.assertEqual(max(size for _, size in guard.reads), 2 * 25 * 2)

    def test_memory_budget_reduces_chunk_before_source_reads(self):
        probe = self.calculate(chunk_patterns=1)
        fixed = probe["chunking"]["estimated_fixed_bytes"]
        budget = fixed + 2 * 25 * 2 + 64
        guard = GuardedArray(self.array, 1)
        actual = self.calculate(guard, chunk_patterns=99999, max_chunk_bytes=budget)
        self.assertEqual(actual["chunking"]["effective_max_patterns"], 1)
        self.assertLessEqual(actual["chunking"]["estimated_max_working_bytes"], budget)
        guard = GuardedArray(self.array, 0)
        with self.assertRaisesRegex(ValueError, "Memory budget"):
            self.calculate(guard, max_chunk_bytes=fixed)
        self.assertEqual(guard.reads, [])

    def test_memmap_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "source.dat")
            self.array.tofile(path)
            with open(path, "rb") as stream:
                before = stream.read()
            source = np.memmap(path, mode="r", dtype=self.array.dtype, shape=self.array.shape)
            actual = self.calculate(source, chunk_patterns=2)
            expected = self.calculate()
            np.testing.assert_array_equal(actual["maps"]["ADF"], expected["maps"]["ADF"])
            del source
            with open(path, "rb") as stream:
                self.assertEqual(stream.read(), before)

    def test_floating_sums_and_mean(self):
        source = self.array.astype(np.float32) / 7
        result = self.calculate(source, chunk_patterns=1)
        self.assertEqual(result["maps"]["BF"].dtype, np.dtype("float64"))
        np.testing.assert_allclose(result["mean_dp"], source.astype(np.float64).mean(axis=(0, 1)), rtol=1e-14)
        np.testing.assert_array_equal(result["maps"]["BF"], source[:, :, 2, 2])

    def test_nan_outside_scan_roi_ignored_inside_rejected(self):
        source = self.array.astype(np.float64)
        source[0, 0, 0, 0] = np.nan
        self.calculate(source, bounds=[[1, 3], [1, 4]])
        with self.assertRaisesRegex(ValueError, "NaN"):
            self.calculate(source)

    def test_signed_negative_rejected(self):
        source = self.array.astype(np.int16)
        source[0, 0, 0, 0] = -1
        with self.assertRaisesRegex(ValueError, "Negative"):
            self.calculate(source)

    def test_uint64_overflow_bound_checked_before_read(self):
        guard = GuardedArray(self.array.astype(np.uint64), 0)
        with self.assertRaisesRegex(ValueError, "overflow"):
            self.calculate(guard)
        self.assertEqual(guard.reads, [])

    def test_invalid_axes(self):
        for scan, detector in (([0, 0], [2, 3]), ([0, 1], [1, 3]), ([-1, 1], [2, 3]),
                               ([0., 1], [2, 3]), ([True, 1], [2, 3]), ([0], [2, 3])):
            with self.assertRaises(ValueError):
                fourdstem.info(self.array.shape, self.cal, scan, detector)

    def test_missing_and_invalid_calibration(self):
        for field, value in (("scale", 0), ("scale", float("nan")),
                             ("calibrated_value_at_pixel_zero", None), ("unit", "mrad"), ("size", 8)):
            cal = [dict(record) for record in self.cal]
            cal[2][field] = value
            with self.assertRaises(ValueError):
                self.calculate(cal=cal)
        with self.assertRaises(ValueError):
            self.calculate(cal=self.cal[:-1])
        with self.assertRaises(ValueError):
            self.calculate(cal=self.cal + [dict(self.cal[0])])

    def test_mismatching_q_units(self):
        cal = [dict(record) for record in self.cal]
        cal[3]["unit"] = "1/angstrom"
        with self.assertRaisesRegex(ValueError, "matching"):
            self.calculate(cal=cal)

    def test_reciprocal_aliases_without_unit_conversion(self):
        cal = [dict(record) for record in self.cal]
        cal[3]["unit"] = "nm^-1"
        result = self.calculate(cal=cal)
        self.assertEqual(result["q_unit"], "1/nm")

    def test_invalid_bounds(self):
        for bounds in ([[0, 0], [0, 4]], [[-1, 2], [0, 4]], [[0, 4], [0, 4]],
                       [[0., 2], [0, 4]], [[0, 2]], [0, 2, 0, 4]):
            with self.assertRaises(ValueError):
                self.calculate(bounds=bounds)

    def test_partial_outer_circle_rejected(self):
        for centre, outer in (([1., 0.], 2.), ([0., 0.], 2.50001)):
            detector = [{"label": "clipped", "center_q": centre, "r_inner": 0., "r_outer": outer}]
            with self.assertRaisesRegex(ValueError, "clipped"):
                self.calculate(detectors=detector)

    def test_circle_can_touch_pixel_edge(self):
        result = self.calculate(detectors=[{"label": "edge", "center_q": [0., 0.], "r_inner": 0., "r_outer": 2.5}])
        self.assertEqual(result["detector_metadata"][0]["selected_pixels"], 21)

    def test_empty_mask_and_invalid_detectors(self):
        invalid = [[], DETECTORS + [dict(DETECTORS[0])],
                   [{"label": "zero", "center_q": [0., 0.], "r_inner": 1.1, "r_outer": 1.2}],
                   [{"label": "bad", "center_q": [0., 0.], "r_inner": -1., "r_outer": 1.}],
                   [{"label": "bad", "center_q": [0., 0.], "r_inner": 1., "r_outer": 1.}],
                   [{"label": "bad", "center_q": [float("nan"), 0.], "r_inner": 0., "r_outer": 1.}]]
        for detectors in invalid:
            with self.assertRaises(ValueError):
                self.calculate(detectors=detectors)

    def test_info_reads_no_source_and_reports_coordinate_convention(self):
        result = fourdstem.info(self.array.shape, self.cal, [0, 1], [2, 3])
        self.assertEqual(result["scan_shape"], [3, 4])
        self.assertEqual(result["detector_shape"], [5, 5])
        self.assertEqual(result["detector_calibration"][0]["pixel_edge_bounds"], [-2.5, 2.5])

    def test_native_reader_matches_array_and_requests_bounded_original_indices(self):
        reads = []
        def reader(sy, x0, x1):
            self.assertLessEqual(x1 - x0, 2)
            reads.append((sy, x0, x1))
            return self.array[sy, x0:x1]
        actual = fourdstem.virtual_detectors_from_reader(
            self.array.shape, self.array.dtype, reader, self.cal, [0, 1], [2, 3],
            [[1, 3], [1, 4]], DETECTORS, chunk_patterns=2)
        expected = self.calculate(bounds=[[1, 3], [1, 4]], chunk_patterns=2)
        self.assertEqual(reads, [(1, 1, 3), (1, 3, 4), (2, 1, 3), (2, 3, 4)])
        for label in ("BF", "ADF"):
            np.testing.assert_array_equal(actual["maps"][label], expected["maps"][label])
        np.testing.assert_array_equal(actual["total_counts"], expected["total_counts"])
        np.testing.assert_array_equal(actual["mean_dp"], expected["mean_dp"])

    def test_native_reader_shape_dtype_and_canonical_axes_checked(self):
        wrong_readers = [lambda sy, x0, x1: self.array[sy, x0:x1].astype(np.uint8),
                         lambda sy, x0, x1: self.array[sy, x0:x1, :, :4]]
        for reader in wrong_readers:
            with self.assertRaisesRegex(ValueError, "shape or dtype"):
                fourdstem.virtual_detectors_from_reader(self.array.shape, self.array.dtype, reader,
                    self.cal, [0, 1], [2, 3], None, DETECTORS)
        with self.assertRaisesRegex(ValueError, "canonical"):
            fourdstem.virtual_detectors_from_reader(self.array.shape, self.array.dtype,
                lambda sy, x0, x1: None, self.cal, [1, 0], [2, 3], None, DETECTORS)

    def test_native_reader_not_called_when_budget_impossible(self):
        reads = []
        with self.assertRaisesRegex(ValueError, "Memory budget"):
            fourdstem.virtual_detectors_from_reader(self.array.shape, self.array.dtype,
                lambda sy, x0, x1: reads.append((sy, x0, x1)), self.cal,
                [0, 1], [2, 3], None, DETECTORS, max_chunk_bytes=1)
        self.assertEqual(reads, [])


if __name__ == "__main__":
    unittest.main()
