#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Reproducible DmBackend contract/numerical tests, with no DigitalMicrograph.

Run with GMS Python 3.7: python -B -m unittest discover -s tests -p test_analysis.py -v
Only synthetic arrays and temporary output files are used. Native DM file
writers are explicitly fakes. Scientific TIFF is checked with a separate small
uncompressed-TIFF reader below; native DM acceptance remains a separate gate.
No test starts DigitalMicrograph, starts the bridge, or binds a socket.
"""

import builtins
import hashlib
import importlib.util
import json
import math
import os
import re
import struct
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np

sys.dont_write_bytecode = True
BRIDGE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bridge", "dm_bridge.py"))


def load_bridge():
    spec = importlib.util.spec_from_file_location("dm_bridge_test_subject", BRIDGE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bridge = load_bridge()


class FakeTagGroup(object):
    """Matches documented native dict/list and introspection signatures.

    GetTagType requires BOTH index and type_index; IsList takes no argument.
    Group access uses string labels and list access uses numeric indices.
    """

    def __init__(self, value):
        self.value = value
        self.type_calls = []
        self.reader_calls = []
        self.group_reads = []

    def CountTags(self):
        return len(self.value)

    def IsList(self):
        return isinstance(self.value, list)

    def GetTagLabel(self, index):
        if self.IsList():
            raise AssertionError("list entries must be accessed by index")
        return list(self.value)[index]

    def _value_at_index(self, index):
        return self.value[index] if self.IsList() else self.value[list(self.value)[index]]

    def GetTagTypeLength(self, index):
        return len(self._descriptor(index))

    def _descriptor(self, index):
        value = self._value_at_index(index)
        if isinstance(value, FakeTagGroup):
            return []
        if isinstance(value, (str, bytes)):
            return [20, 4, len(value)]
        if isinstance(value, (bool, np.bool_)):
            return [8]
        if isinstance(value, np.int16):
            return [2]
        if isinstance(value, np.uint16):
            return [4]
        if isinstance(value, np.uint32):
            return [5]
        if isinstance(value, np.float32):
            return [6]
        if isinstance(value, (float, np.float64)):
            return [7]
        if isinstance(value, (complex, np.complex128)):
            return [15, 0, 2, 0, 7, 0, 7]
        if isinstance(value, (np.int64, int)):
            return [11] if abs(int(value)) > 2 ** 31 - 1 else [3]
        if isinstance(value, np.uint64):
            return [12]
        return [999]

    def GetTagType(self, index, type_index):
        self.type_calls.append((index, type_index))
        return self._descriptor(index)[type_index]

    def GetTagSize(self, index):
        descriptor = self._descriptor(index)
        if not descriptor:
            return 0
        if descriptor[:2] == [20, 4]:
            return descriptor[2] * 2
        return {2: 2, 3: 4, 4: 2, 5: 4, 6: 4, 7: 8, 8: 1, 11: 8, 12: 8, 15: 16}.get(descriptor[0], 8)

    def __getitem__(self, key):
        raise AssertionError("real GMS tg[key] coerces numeric values to lossy strings; use typed indexed getters")

    def GetIndexedTagAsTagGroup(self, index, subgroup):
        self.group_reads.append(index)
        if self._descriptor(index) not in ([], [3]) or self.GetTagSize(index) != 0:
            raise AssertionError("native group getters must never probe scalar/unknown descriptors")
        value = self._value_at_index(index)
        if not isinstance(value, FakeTagGroup):
            return False
        subgroup.value = value.value
        return True

    def _numeric(self, index, conversion, reader):
        self.reader_calls.append((index, reader))
        value = self._value_at_index(index)
        if isinstance(value, (str, bytes, FakeTagGroup)):
            return False, conversion(0)
        return True, conversion(value)

    def GetIndexedTagAsShort(self, index):
        return self._numeric(index, int, "GetIndexedTagAsShort")

    def GetIndexedTagAsLong(self, index):
        return self._numeric(index, int, "GetIndexedTagAsLong")

    def GetIndexedTagAsUInt16(self, index):
        return self._numeric(index, int, "GetIndexedTagAsUInt16")

    def GetIndexedTagAsUInt32(self, index):
        return self._numeric(index, int, "GetIndexedTagAsUInt32")

    def GetIndexedTagAsFloat(self, index):
        return self._numeric(index, float, "GetIndexedTagAsFloat")

    def GetIndexedTagAsDouble(self, index):
        return self._numeric(index, float, "GetIndexedTagAsDouble")

    def GetIndexedTagAsBoolean(self, index):
        return self._numeric(index, bool, "GetIndexedTagAsBoolean")

    def GetIndexedTagAsSInt64(self, index):
        return self._numeric(index, int, "GetIndexedTagAsSInt64")

    def GetIndexedTagAsUInt64(self, index):
        return self._numeric(index, int, "GetIndexedTagAsUInt64")

    def GetIndexedTagAsDoubleComplex(self, index):
        return self._numeric(index, complex, "GetIndexedTagAsDoubleComplex")

    def GetIndexedTagAsString(self, index):
        value = self._value_at_index(index)
        if not isinstance(value, (str, bytes)):
            raise AssertionError("numeric tags must not use lossy string getters")
        return True, value


class FakeDocument(object):
    def __init__(self, image):
        self.image = image
        self.calls = []
        self.current_file = "source_file.dm4"

    def IsValid(self):
        return True

    def CountImages(self):
        return 1

    def GetImage(self, index):
        if index != 0:
            raise IndexError(index)
        return self.image

    def GetName(self):
        return self.image.name + ".dm4"

    def GetWorkspace(self):
        return 0

    def Show(self):
        pass

    def SaveToFile(self, handler, path):
        self.calls.append((handler, path))
        version = 4 if handler == "Gatan Format" else 3
        # Only a fake native writer. Header checks verify adapter selection;
        # scientific correctness of native DM formats needs real DM acceptance.
        with open(path + ".dm%d" % version, "wb") as stream:
            stream.write(b"\x00\x00\x00" + bytes([version]) + self.image.array.tobytes())


class FakeImage(object):
    def __init__(self, array, image_id=1, name="synthetic", sx=0.1, sy=0.3):
        self.array = np.asarray(array)
        self.image_id = image_id
        self.name = name
        self.scales = [sx, sy]
        self.origins = [2.0, 3.0]  # Calibrated values at pixel zero (format 0).
        self.units = ["nm", "nm"]
        self.document = FakeDocument(self)
        self.tags = FakeTagGroup({
            "Instrument": FakeTagGroup({"Voltage": 200000, "Active": True, "Name": "TEM"}),
            "List": FakeTagGroup([1, 2, FakeTagGroup({"value": 3})]),
            "EmptyList": FakeTagGroup([]), "EmptyGroup": FakeTagGroup({}),
        })

    def IsValid(self):
        return True

    def GetNumDimensions(self):
        return self.array.ndim

    def GetDimensionSize(self, dimension):
        return self.array.shape[::-1][dimension]

    def GetNumArray(self):
        return self.array

    def GetID(self):
        return self.image_id

    def GetName(self):
        return self.name

    def GetTagGroup(self):
        return self.tags

    def GetDimensionScale(self, dimension):
        return self.scales[dimension]

    def GetDimensionOrigin(self, dimension):
        return self.origins[dimension]

    def GetDimensionUnitString(self, dimension):
        return self.units[dimension]

    def GetDimensionCalibration(self, dimension, calibration_format):
        if calibration_format != 0:
            raise AssertionError("test fixture defines format 0 explicitly")
        return self.origins[dimension], self.scales[dimension], self.units[dimension]

    def SetDimensionCalibration(self, dimension, origin, scale, unit, calibration_format):
        if calibration_format != 0:
            raise AssertionError("test fixture defines format 0 explicitly")
        self.origins[dimension], self.scales[dimension], self.units[dimension] = origin, scale, unit

    def GetImgWidth(self):
        return self.array.shape[-1]

    def GetImgHeight(self):
        return self.array.shape[-2]

    def GetIntensityOrigin(self):
        return 0.0

    def GetIntensityScale(self):
        return 1.0

    def GetIntensityUnitString(self):
        return "counts"

    def GetDataType(self):
        return 2

    def GetOrCreateImageDocument(self):
        return self.document


class FakeDM(object):
    def __init__(self, image):
        self.images = [image]
        self.scripts = []

    def NewTagGroup(self):
        return FakeTagGroup({})

    def OpenImage(self, path):
        return self.images[0]

    def NewImageDocumentFromFile(self, path):
        raise AssertionError("successful OpenImage must not attempt document fallback")

    def ExecuteScriptString(self, script):
        self.scripts.append(script)
        if "TIFF Format" in script:
            path = re.search(r'TIFF Format", "([^\"]+)", 1', script).group(1)
            with open(path + ".tif", "wb") as stream:
                stream.write(b"II*\x00" + b"FAKE native TIFF writer; not a scientific TIFF")
            return
        crop = re.search(r"src\[(\d+), (\d+), (\d+), (\d+)\]", script)
        if crop:
            top, left, bottom, right = map(int, crop.groups())
            name = re.search(r'SetName\(dst, "([^\"]+)"', script).group(1)
            # Native rectangular subareas exclude bottom and right.
            array = self.images[0].array[top:bottom, left:right].copy()
            self.images.append(FakeImage(array, len(self.images) + 1, name))


def backend_for(image):
    dm = FakeDM(image)
    backend = bridge.DmBackend(dm)
    backend._resolve = lambda unused: dm.images[0]
    backend._iter_images = lambda: iter((0, image.document, "synthetic", item) for item in dm.images)
    return backend


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.image = FakeImage(np.zeros((3, 5)))
        self.backend = backend_for(self.image)

    def test_typed_native_getters_retain_nested_scalars_and_lists(self):
        result = self.backend.metadata(1, 8, None)
        self.assertTrue(result["complete"])
        self.assertEqual(result["tags"]["Instrument"], {"Voltage": 200000, "Active": True, "Name": "TEM"})
        self.assertEqual(result["tags"]["List"], [1, 2, {"value": 3}])
        self.assertEqual(result["tags"]["EmptyList"], [])
        self.assertEqual(result["tags"]["EmptyGroup"], {})
        self.assertTrue(all(type_index == 0 for _, type_index in self.image.tags.type_calls))

    def test_type_descriptors_and_escaped_paths(self):
        self.image.tags = FakeTagGroup({"a/b~c": 4})
        result = self.backend.metadata(1, 8, None)
        self.assertEqual(result["tag_types"]["/a~1b~0c"]["dm_type"], [3])
        self.assertEqual(result["tags"]["a/b~c"], 4)

    def test_depth_limit_is_explicit(self):
        result = self.backend.metadata(1, 0, None)
        self.assertFalse(result["complete"])
        self.assertTrue(any(issue["reason"] == "depth_limit" for issue in result["issues"]))

    def test_node_budget_is_explicit(self):
        with mock.patch.object(bridge, "MAX_TAG_NODES", 2):
            result = self.backend.metadata(1, 8, None)
        self.assertFalse(result["complete"])
        self.assertTrue(any(issue["reason"] == "node_budget" for issue in result["issues"]))

    def test_large_integer_survives_javascript_json_transport(self):
        self.image.tags = FakeTagGroup({"large": np.int64(2 ** 63 - 1)})
        result = self.backend.metadata(1, 8, None)
        value = json.loads(json.dumps(result))["tags"]["large"]
        self.assertEqual(value, {"__type__": "integer", "decimal": "9223372036854775807"})

    def test_read_failure_is_not_reported_as_null_or_complete(self):
        class Unreadable(FakeTagGroup):
            def GetIndexedTagAsLong(self, index):
                raise RuntimeError("synthetic unreadable tag")
        self.image.tags = Unreadable({"bad": 1})
        result = self.backend.metadata(1, 8, None)
        self.assertFalse(result["complete"])
        self.assertEqual(result["tags"]["bad"]["__unavailable__"], "read_error")

    def test_descriptor_dispatch_keeps_types_precision_and_unsigned_ranges(self):
        self.image.tags = FakeTagGroup({
            "short": np.int16(-1234), "long": -1234567,
            "uint16": np.uint16(45678), "uint32": np.uint32(4000000001),
            "float": np.float32(1.23456789), "double": 1.2345678901234567,
            "boolean": True, "complex": 1.25 - 2.5j,
            "uint64": np.uint64(2 ** 64 - 1), "sint64": np.int64(-2 ** 63 + 1),
        })
        result = self.backend.metadata(1, 8, None)
        self.assertTrue(result["complete"])
        tags = result["tags"]
        self.assertIs(tags["boolean"], True)
        self.assertIsInstance(tags["long"], int)
        self.assertEqual(tags["uint32"], 4000000001)
        self.assertEqual(tags["double"], 1.2345678901234567)
        self.assertEqual(tags["float"], float(np.float32(1.23456789)))
        self.assertEqual(tags["complex"], {"__type__": "complex", "real": 1.25, "imag": -2.5})
        self.assertEqual(tags["uint64"]["decimal"], "18446744073709551615")
        self.assertEqual(tags["sint64"]["decimal"], "-9223372036854775807")
        self.assertEqual(result["tag_types"]["/double"]["reader"], "GetIndexedTagAsDouble")
        self.assertEqual(result["tag_types"]["/boolean"]["reader"], "GetIndexedTagAsBoolean")
        self.assertEqual(self.image.tags.group_reads, [])

    def test_legacy_byte_label_is_decoded_without_using_it_as_native_path(self):
        raw_label = b"Emission Current (\xb5A)"
        self.image.tags = FakeTagGroup({raw_label: 0.12345678901234566})
        result = self.backend.metadata(1, 8, None)
        key = "Emission Current (\u00b5A)"
        self.assertTrue(result["complete"])
        self.assertEqual(result["tags"][key], 0.12345678901234566)
        self.assertEqual(result["tag_types"]["/" + key]["label_encoding"], "cp1252")
        self.assertEqual(result["tag_types"]["/" + key]["label_bytes_hex"], raw_label.hex())

    def test_unknown_descriptor_is_explicitly_unsupported(self):
        self.image.tags = FakeTagGroup({"opaque": object()})
        result = self.backend.metadata(1, 8, None)
        self.assertFalse(result["complete"])
        self.assertEqual(result["tags"]["opaque"]["__unavailable__"], "unsupported_dm_type")
        self.assertEqual(result["tag_types"]["/opaque"]["dm_type"], [999])
        self.assertEqual(self.image.tags.group_reads, [])

    def test_legacy_group_descriptor_three_size_zero_is_container(self):
        class RecordedFileGroup(FakeTagGroup):
            # Synthetic legacy DM4 descriptor fixture, unlike new synthetic groups.
            def _descriptor(self, index):
                if isinstance(self._value_at_index(index), FakeTagGroup):
                    return [3]
                return super(RecordedFileGroup, self)._descriptor(index)
            def GetTagSize(self, index):
                if isinstance(self._value_at_index(index), FakeTagGroup):
                    return 0
                return super(RecordedFileGroup, self).GetTagSize(index)
        self.image.tags = RecordedFileGroup({
            "Group": FakeTagGroup({"Voltage": 300000.0, "EmptyString": ""}),
            "ScalarLong": 1234,
        })
        result = self.backend.metadata(1, 8, None)
        self.assertTrue(result["complete"], result["issues"])
        self.assertEqual(result["tags"]["Group"], {"Voltage": 300000.0, "EmptyString": ""})
        self.assertEqual(result["tag_types"]["/Group"]["dm_type"], [3])
        self.assertEqual(result["tag_types"]["/Group"]["tag_size"], 0)
        self.assertEqual(result["tag_types"]["/Group"]["reader"], "GetIndexedTagAsTagGroup")
        self.assertEqual(result["tag_types"]["/ScalarLong"]["reader"], "GetIndexedTagAsLong")
        self.assertEqual(self.image.tags.group_reads, [0])


class CropTests(unittest.TestCase):
    def test_exclusive_crop_dimensions_and_physical_origin(self):
        image = FakeImage(np.arange(120, dtype=np.float32).reshape(10, 12))
        original = image.array.copy()
        backend = backend_for(image)
        result = backend.crop(1, [2, 1, 7, 5], "crop")
        cropped = backend.DM.images[-1]
        self.assertEqual(result["new_image"]["shape"], [4, 5])
        np.testing.assert_array_equal(cropped.array, original[1:5, 2:7])
        np.testing.assert_allclose(cropped.origins, [2.2, 3.3], rtol=0, atol=1e-14)
        self.assertEqual(image.origins, [2.0, 3.0])
        np.testing.assert_array_equal(image.array, original)

    def test_single_pixel_and_clamped_crop(self):
        image = FakeImage(np.arange(120).reshape(10, 12))
        backend = backend_for(image)
        result = backend.crop(1, [11, 9, 12, 10], "one_pixel")
        self.assertEqual(result["new_image"]["shape"], [1, 1])
        self.assertEqual(backend.DM.images[-1].array[0, 0], 119)
        result = backend.crop(1, [-2, -3, 4, 5], "clamped")
        self.assertEqual(result["requested_rect"], [0, 0, 4, 5])
        self.assertEqual(result["new_image"]["shape"], [5, 4])


class FFTTests(unittest.TestCase):
    @staticmethod
    def sinusoid(sx=0.2, sy=0.5):
        y, x = np.indices((48, 80), dtype=float)
        image = FakeImage(np.cos(2 * np.pi * (10 * x / 80 + 6 * y / 48)), sx=sx, sy=sy)
        return image, backend_for(image)

    def test_non_square_fft_bins_and_cycles_per_pixel(self):
        image, backend = self.sinusoid()
        original = image.array.copy()
        result = backend.fft(1, None, 2)
        self.assertEqual(result["shape"], [48, 80])
        self.assertEqual(len(result["peaks"]), 2)
        for peak in result["peaks"]:
            self.assertEqual(abs(peak["dx"]), 10)
            self.assertEqual(abs(peak["dy"]), 6)
            self.assertAlmostEqual(abs(peak["fx_cycles_per_pixel"]), 0.125)
            self.assertAlmostEqual(abs(peak["fy_cycles_per_pixel"]), 0.125)
            self.assertAlmostEqual(peak["d_pix"], math.sqrt(136))
        np.testing.assert_array_equal(image.array, original)

    def test_anisotropic_frequency_and_spacing(self):
        _, backend = self.sinusoid()
        expected_frequency = math.hypot(0.125 / 0.2, 0.125 / 0.5)
        for peak in backend.fft(1, None, 2)["peaks"]:
            self.assertAlmostEqual(abs(peak["fx"]), 0.625)
            self.assertAlmostEqual(abs(peak["fy"]), 0.25)
            self.assertAlmostEqual(peak["frequency"], expected_frequency)
            self.assertAlmostEqual(peak["spacing"], 1.0 / expected_frequency)
            self.assertEqual(peak["spacing_unit"], "nm")

    def test_negative_scale_changes_signed_axis_frequency(self):
        _, backend = self.sinusoid(sx=-0.2)
        for peak in backend.fft(1, None, 2)["peaks"]:
            self.assertAlmostEqual(peak["fx"], -5 * peak["fx_cycles_per_pixel"])
            self.assertGreater(peak["spacing"], 0)

    def test_mixed_axis_units_have_no_unsupported_radial_spacing(self):
        image, backend = self.sinusoid()
        image.units[1] = "eV"
        for peak in backend.fft(1, None, 2)["peaks"]:
            self.assertIsNone(peak["frequency"])
            self.assertIsNone(peak["spacing"])
            self.assertEqual(peak["fx_unit"], "1/(nm)")
            self.assertEqual(peak["fy_unit"], "1/(eV)")

    def test_nonfinite_input_requires_explicit_preprocessing(self):
        backend = backend_for(FakeImage(np.array([[1.0, np.nan], [3.0, 4.0]])))
        with self.assertRaises(ValueError):
            backend.fft(1, None, 2)


class ProfileTests(unittest.TestCase):
    def test_perpendicular_strip_does_not_smooth_along_line(self):
        image = FakeImage(np.tile(np.arange(12, dtype=float) ** 2, (12, 1)))
        result = backend_for(image).profile(1, 5, 5, 7, 5, 3)
        self.assertEqual(result["values"], [25.0, 36.0, 49.0])

    def test_fractional_diagonal_bilinear_sampling_of_analytic_plane(self):
        y, x = np.indices((14, 15), dtype=float)
        backend = backend_for(FakeImage(2 * x + 3 * y))
        result = backend.profile(1, 3.25, 4.5, 9.75, 8.25, 4)
        expected = [2 * px + 3 * py for px, py in result["sampled_coordinates"]]
        np.testing.assert_allclose(result["values"], expected, rtol=0, atol=2e-14)
        self.assertEqual(result["width_offsets"], [-1.5, -0.5, 0.5, 1.5])
        self.assertTrue(all(count == 4 for count in result["finite_samples_per_point"]))

    def test_even_width_at_boundary_omits_and_renormalizes(self):
        y, _ = np.indices((8, 10), dtype=float)
        result = backend_for(FakeImage(y ** 2)).profile(1, 3, 0, 5, 0, 4)
        self.assertEqual(result["finite_samples_per_point"], [2, 2, 2])
        # Bilinear values at y=.5 and y=1.5 are .5 and 2.5.
        self.assertEqual(result["values"], [1.5, 1.5, 1.5])

    def test_anisotropic_distance_and_negative_scale(self):
        image = FakeImage(np.ones((12, 12)), sx=-0.1, sy=0.3)
        backend = backend_for(image)
        self.assertAlmostEqual(backend.profile(1, 3, 0, 3, 10, 1)["distance"][-1], 3.0)
        self.assertAlmostEqual(backend.profile(1, 0, 0, 10, 10, 1)["distance"][-1], math.hypot(1, 3))

    def test_outside_endpoints_and_coincident_points_are_rejected(self):
        backend = backend_for(FakeImage(np.ones((8, 10))))
        for endpoints in ((-1, 0, 3, 0), (0, 0, 10, 0), (2, 2, 2, 2)):
            with self.subTest(endpoints=endpoints):
                with self.assertRaises(ValueError):
                    backend.profile(1, *endpoints, width=1)

    def test_zero_weight_nan_neighbor_does_not_poison_exact_sample(self):
        array = np.ones((4, 5))
        array[2, 1:4] = np.nan
        result = backend_for(FakeImage(array)).profile(1, 1, 1, 3, 1, 1)
        self.assertEqual(result["values"], [1.0, 1.0, 1.0])


class StatsTests(unittest.TestCase):
    def test_counts_finite_nan_inf_and_population_stddev(self):
        array = np.array([[1, np.nan, 3], [np.inf, 5, 6]], dtype=np.float32)
        result = backend_for(FakeImage(array)).stats(1, None)
        self.assertEqual((result["total_count"], result["finite_count"], result["nan_count"], result["inf_count"]), (6, 4, 1, 1))
        self.assertEqual(result["invalid_count"], 2)
        self.assertAlmostEqual(result["mean"], 3.75)
        self.assertAlmostEqual(result["stddev"], np.std([1.0, 3.0, 5.0, 6.0]))

    def test_roi_guard_applies_to_selection_and_preserves_source(self):
        image = FakeImage(np.arange(120, dtype=np.float32).reshape(10, 12))
        original = image.array.copy()
        backend = backend_for(image)
        with mock.patch.object(bridge, "MAX_TRANSFER_PIXELS", 4):
            result = backend.stats(1, [2, 1, 4, 3])
            self.assertEqual(result["shape"], [2, 2])
            self.assertAlmostEqual(result["mean"], 20.5)
            with self.assertRaises(RuntimeError):
                backend.stats(1, None)
        np.testing.assert_array_equal(image.array, original)

    def test_non_2d_and_complex_are_rejected(self):
        for array in (np.ones(4), np.ones((2, 3, 4)), np.ones((2, 3), dtype=complex)):
            with self.subTest(shape=array.shape, dtype=str(array.dtype)):
                with self.assertRaises(RuntimeError):
                    backend_for(FakeImage(array)).stats(1, None)

    def test_all_invalid_region_has_no_invented_numeric_statistics(self):
        with self.assertRaises(RuntimeError):
            backend_for(FakeImage(np.array([[np.nan, np.inf]]))).stats(1, None)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dm_analysis_test_")
        self.addCleanup(self.temp.cleanup)
        self.image = FakeImage(np.array([[np.pi, np.nextafter(1.0, 2.0)], [1e-200, -1e200]], dtype=np.float64))
        self.backend = backend_for(self.image)

    def path(self, suffix):
        return os.path.join(self.temp.name, "export." + suffix)

    def assert_sidecar(self, result):
        with open(result["metadata_path"], encoding="utf-8") as stream:
            metadata = json.load(stream)
        with open(result["actual_path"], "rb") as stream:
            self.assertEqual(metadata["sha256"], hashlib.sha256(stream.read()).hexdigest())
        self.assertEqual(metadata["calibration"][1]["scale"], 0.3)
        self.assertEqual(metadata["intensity_calibration"]["unit"], "counts")

    def test_npy_preserves_dtype_shape_and_raw_values(self):
        original = self.image.array.copy()
        result = self.backend.export(1, self.path("npy"), "npy")
        actual = np.load(result["actual_path"], allow_pickle=False)
        self.assertEqual(actual.dtype, self.image.array.dtype)
        self.assertEqual(actual.shape, self.image.array.shape)
        np.testing.assert_array_equal(actual, original)
        np.testing.assert_array_equal(self.image.array, original)
        self.assert_sidecar(result)

    def test_csv_and_txt_roundtrip_float64_precision(self):
        for fmt, delimiter in (("csv", ","), ("txt", "\t")):
            with self.subTest(fmt=fmt):
                result = self.backend.export(1, self.path(fmt), fmt)
                np.testing.assert_array_equal(np.loadtxt(result["actual_path"], delimiter=delimiter), self.image.array)
                self.assert_sidecar(result)

    def test_csv_keeps_integer_decimal_precision(self):
        image = FakeImage(np.array([[2 ** 63 + 1, 2 ** 64 - 1]], dtype=np.uint64))
        result = backend_for(image).export(1, self.path("csv"), "csv")
        with open(result["actual_path"]) as stream:
            values = [int(v) for v in stream.read().strip().split(",")]
        self.assertEqual(values, [2 ** 63 + 1, 2 ** 64 - 1])

    def test_existing_data_or_sidecar_are_never_overwritten(self):
        result = self.backend.export(1, self.path("npy"), "npy")
        with open(result["actual_path"], "rb") as stream:
            original_bytes = stream.read()
        with self.assertRaises(FileExistsError):
            self.backend.export(1, self.path("npy"), "npy")
        with open(result["actual_path"], "rb") as stream:
            self.assertEqual(stream.read(), original_bytes)
        sidecar_only = self.path("csv") + ".metadata.json"
        with open(sidecar_only, "w") as stream:
            stream.write("existing")
        with self.assertRaises(FileExistsError):
            self.backend.export(1, self.path("csv"), "csv")
        self.assertFalse(os.path.exists(self.path("csv")))

    def test_native_dm_writer_selection_uses_explicit_handlers(self):
        for fmt in ("dm4", "dm3"):
            with self.subTest(fmt=fmt):
                result = self.backend.export(1, self.path(fmt), fmt)
                self.assert_sidecar(result)
        self.assertEqual([call[0] for call in self.image.document.calls], ["Gatan Format", "Gatan 3 Format"])
        self.assertEqual(self.image.document.current_file, "source_file.dm4")

    def test_scientific_tiff_preserves_uint32_without_native_downcast(self):
        image = FakeImage(np.array([[0, 65536], [16777217, 2 ** 32 - 1]], dtype=np.uint32))
        backend = backend_for(image)
        result = backend.export(1, self.path("tif"), "tif")
        with open(result["actual_path"], "rb") as stream:
            content = stream.read()
        self.assertEqual(content[:4], b"II*\x00")
        ifd = struct.unpack_from("<I", content, 4)[0]
        count = struct.unpack_from("<H", content, ifd)[0]
        tags = {}
        for i in range(count):
            code, kind, size, value = struct.unpack_from("<HHII", content, ifd + 2 + 12 * i)
            tags[code] = (kind, size, value)
        self.assertEqual(tags[258][2], 32)  # BitsPerSample
        self.assertEqual(tags[259][2], 1)  # Compression: uncompressed
        self.assertEqual(tags[339][2], 1)  # SampleFormat: unsigned integer
        raw = content[tags[273][2]:tags[273][2] + tags[279][2]]
        actual = np.frombuffer(raw, dtype="<u4").reshape(tags[257][2], tags[256][2])
        np.testing.assert_array_equal(actual, image.array)
        self.assertEqual(backend.DM.scripts, [])
        self.assertEqual(image.document.calls, [])
        self.assertIn("dm_mcp.lossless_tiff", result["writer"])
        self.assertAlmostEqual(struct.unpack_from("<d", content, tags[65009][2])[0], 0.1)
        self.assertAlmostEqual(struct.unpack_from("<d", content, tags[65010][2])[0], 0.3)
        self.assert_sidecar(result)

    def test_unknown_or_mismatched_format_is_rejected(self):
        for path, fmt in ((self.path("png"), "png"), (self.path("tif"), "npy")):
            with self.subTest(fmt=fmt):
                with self.assertRaises(ValueError):
                    self.backend.export(1, path, fmt)
                self.assertFalse(os.path.exists(path))


class LifecycleTests(unittest.TestCase):
    def test_missing_dm_import_does_not_fall_back_to_mock(self):
        real_import = builtins.__import__
        def missing_dm(name, *args, **kwargs):
            if name == "DigitalMicrograph":
                raise ImportError("synthetic missing DM host")
            return real_import(name, *args, **kwargs)
        with mock.patch.object(bridge, "MOCK", False), mock.patch.object(bridge, "serve") as serve:
            with mock.patch("builtins.__import__", side_effect=missing_dm):
                with self.assertRaises(ImportError):
                    bridge.main()
            serve.assert_not_called()

    def test_mock_requires_explicit_environment_flag(self):
        with mock.patch.dict(os.environ, {"DM_BRIDGE_MOCK": "0"}):
            self.assertFalse(load_bridge().MOCK)
        with mock.patch.dict(os.environ, {"DM_BRIDGE_MOCK": "1"}):
            subject = load_bridge()
        with mock.patch.object(subject, "serve") as serve:
            subject.main()
        self.assertEqual(serve.call_args[0][0].backend.name, "mock")

    def test_foreground_bridge_is_rejected_before_serving(self):
        fake_dm = types.ModuleType("DigitalMicrograph")
        fake_dm.IsScriptOnMainThread = lambda: True
        with mock.patch.object(bridge, "MOCK", False), mock.patch.dict(sys.modules, {"DigitalMicrograph": fake_dm}):
            with mock.patch.object(bridge, "serve") as serve:
                with self.assertRaises(RuntimeError):
                    bridge.main()
            serve.assert_not_called()

    def test_script_gate_is_enforced_in_dispatcher_and_backend(self):
        backend = backend_for(FakeImage(np.ones((3, 5))))
        with mock.patch.dict(os.environ, {"DM_MCP_ALLOW_DMSCRIPT": "0"}):
            with self.assertRaises(PermissionError):
                backend.run_script("test", False)
            with self.assertRaises(PermissionError):
                bridge.Dispatcher(backend).handle({"op": "run_script", "args": {"script": "test"}})
        self.assertEqual(backend.DM.scripts, [])

    def test_enabled_script_reports_invocation_without_claiming_result_success(self):
        backend = backend_for(FakeImage(np.ones((3, 5))))
        with mock.patch.dict(os.environ, {"DM_MCP_ALLOW_DMSCRIPT": "1"}):
            result = backend.run_script("test", False)
        self.assertTrue(result["executed"])
        self.assertFalse(result["success_verified"])
        self.assertEqual(backend.DM.scripts, ["test"])

    def test_shutdown_and_non_loopback_rejection_need_no_socket(self):
        dispatcher = bridge.Dispatcher(backend_for(FakeImage(np.ones((3, 5)))))
        self.assertTrue(dispatcher.handle({"op": "shutdown"})["stopping"])
        self.assertTrue(dispatcher.stopping)
        with mock.patch.object(bridge, "HOST", "0.0.0.0"):
            with mock.patch.object(bridge.socket, "socket") as socket_constructor:
                with self.assertRaises(ValueError):
                    bridge.serve(dispatcher)
            socket_constructor.assert_not_called()


class OpenPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dm_open_test_")
        self.addCleanup(self.temp.cleanup)
        self.path = os.path.join(self.temp.name, "source.dm4")
        with open(self.path, "wb") as stream:
            stream.write(b"synthetic input file; FakeDM supplies the image")
        self.image = FakeImage(np.arange(120, dtype=np.uint32).reshape(10, 12))

    def test_verified_open_records_original_source_in_export_sidecar(self):
        backend = backend_for(self.image)
        result = backend.open_file(self.path, True)
        self.assertEqual(result["image_ids"], [1])
        self.assertEqual(result["images"][0]["shape"], [10, 12])
        self.assertEqual(result["path"], self.path)
        self.assertEqual(result["opened_path"], self.path)
        self.assertEqual(result["path_resolution"], "original")
        self.assertTrue(result["source_file"]["same_file_verified"])
        out = backend.export(1, os.path.join(self.temp.name, "data.npy"), "npy")
        with open(out["metadata_path"], encoding="utf-8") as stream:
            metadata = json.load(stream)
        self.assertEqual(metadata["source_file"]["path"], self.path)
        self.assertEqual(metadata["source_file"]["mtime_ns"], str(os.stat(self.path).st_mtime_ns))

    @unittest.skipUnless(os.name == "nt", "Windows short path fallback")
    def test_non_ascii_fallback_uses_same_file_and_preserves_provenance(self):
        source = os.path.join(self.temp.name, "source_\u00b5.dm4")
        short_path = os.path.join(self.temp.name, "ascii_alias.dm4")
        os.rename(self.path, source)
        os.link(source, short_path)
        class LegacyDM(FakeDM):
            def OpenImage(self, path):
                if path != short_path:
                    raise RuntimeError("synthetic legacy Unicode failure")
                return self.images[0]
            def NewImageDocumentFromFile(self, path):
                raise RuntimeError("synthetic document opener failure")
        backend = backend_for(self.image)
        backend.DM = LegacyDM(self.image)
        with mock.patch.object(backend, "_windows_short_path", return_value=short_path) as resolve:
            result = backend.open_file(source, True)
        resolve.assert_called_once_with(source)
        self.assertEqual(result["path"], source)
        self.assertEqual(result["opened_path"], short_path)
        self.assertEqual(result["path_resolution"], "windows_short_path")
        self.assertTrue(result["source_file"]["same_file_verified"])
        self.assertEqual(len(result["open_attempt_errors"]), 2)
        out = backend.export(1, os.path.join(self.temp.name, "data.npy"), "npy")
        with open(out["metadata_path"], encoding="utf-8") as stream:
            metadata = json.load(stream)
        self.assertEqual(metadata["source_file"]["path"], source)
        self.assertEqual(metadata["source_file"]["opened_path"], short_path)

    def test_crop_export_tracks_original_file_and_processing_rect(self):
        backend = backend_for(self.image)
        backend.open_file(self.path, True)
        result = backend.crop(1, [2, 1, 7, 5], "crop")
        crop_id = result["new_image"]["id"]
        backend._resolve = lambda image_id: next(item for item in backend.DM.images if item.GetID() == int(image_id))
        out = backend.export(crop_id, os.path.join(self.temp.name, "crop.npy"), "npy")
        with open(out["metadata_path"], encoding="utf-8") as stream:
            metadata = json.load(stream)
        self.assertEqual(metadata["source_file"]["path"], self.path)
        self.assertEqual(metadata["source_file"]["processing_history"], [{
            "operation": "crop", "source_image_id": 1, "rect": [2, 1, 7, 5],
            "rect_convention": "right/bottom excluded"}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
