#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Synthetic DmBackend/Dispatcher spectroscopy integration tests.

No DigitalMicrograph process, socket, native detector or experimental spectrum
is used. An independent fake image API exercises the actual DmBackend adapter
and its lazy pixel reads. Passing these tests does not validate real EDS/EELS/SI.
Compatible with the GMS Python 3.7 / NumPy 1.18 runtime.
"""

import csv
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

sys.dont_write_bytecode = True
BRIDGE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bridge", "dm_bridge.py"))
SPEC = importlib.util.spec_from_file_location("spectroscopy_bridge_integration_subject", BRIDGE_PATH)
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


def file_hash(path):
    with open(path, "rb") as stream:
        return hashlib.sha256(stream.read()).hexdigest()


def array_hash(array):
    return hashlib.sha256(array.tobytes(order="C")).hexdigest()


class FakeImageAPI(object):
    """Image dimensions/calibration are independent of access to pixel memory.

    Axis specifications are passed in NumPy order; the public getters expose
    native DM's reverse order. Raw origins deliberately disagree with physical
    zeros so substituting GetDimensionOrigin for format-0 calibration fails.
    """

    def __init__(self, array, axes, image_id=71, intensity_unit=None, data_type=2):
        self.array = array
        self.axes = list(axes)
        self.image_id = image_id
        self.intensity_unit = intensity_unit
        self.data_type = data_type
        self.pixel_reads = 0
        self.calibration_calls = []
        self.declared_shape = tuple(array.shape)

    def IsValid(self):
        return True

    def GetID(self):
        return self.image_id

    def GetName(self):
        return "SYNTHETIC independent FakeImageAPI"

    def GetNumDimensions(self):
        return len(self.declared_shape)

    def GetDimensionSize(self, dimension):
        return self.declared_shape[::-1][dimension]

    def GetDimensionScale(self, dimension):
        return self.axes[::-1][dimension][0]

    def GetDimensionUnitString(self, dimension):
        return self.axes[::-1][dimension][1]

    def GetDimensionOrigin(self, dimension):
        return 987.0 + dimension

    def GetDimensionCalibration(self, dimension, calibration_format):
        if calibration_format != 0:
            raise AssertionError("Expected native format-0 calibration tuple")
        self.calibration_calls.append((dimension, calibration_format))
        scale, unit, physical_zero = self.axes[::-1][dimension]
        return physical_zero, scale, unit

    def GetNumArray(self):
        self.pixel_reads += 1
        return self.array

    def GetDataType(self):
        return self.data_type

    def GetIntensityUnitString(self):
        return self.intensity_unit

    def GetIntensityOrigin(self):
        return 0.0

    def GetIntensityScale(self):
        return 1.0


class FakeDMAPI(object):
    def __init__(self, image):
        self.image = image
        self.resolved = []

    def FindImageByID(self, image_id):
        self.resolved.append(image_id)
        return self.image if image_id == self.image.image_id else None

    def GetFrontImage(self):
        raise AssertionError("Explicit spectrum tools must never resolve the front window")

    def CountImageDocuments(self):
        return 0


def backend_for(image):
    return bridge.DmBackend(FakeDMAPI(image))


def make_cube(energy_axis):
    # Canonical array [energy,y,x], non-square spatial dimensions. All expected
    # reductions below are calculated with plain Python loops, not the helper.
    canonical = np.empty((8, 3, 5), dtype=np.uint32)
    for energy in range(8):
        for y in range(3):
            for x in range(5):
                canonical[energy, y, x] = 1000000 + 100 * energy + 10 * y + x
    orders = {0: (0, 1, 2), 1: (1, 0, 2), 2: (1, 2, 0)}
    order = orders[energy_axis]
    source_axes = [(0.25, "keV", -0.5), (0.3, "nm", -1.2), (0.2, "nm", 4.2)]
    return FakeImageAPI(canonical.transpose(order), [source_axes[index] for index in order])


class DmBackendSpectroscopyTests(unittest.TestCase):
    def assert_unverified(self, result):
        self.assertTrue(result["experimental"])
        self.assertEqual(result["validation_scope"]["real_eds"], "NOT_TESTED")
        self.assertEqual(result["validation_scope"]["real_eels"], "NOT_TESTED")
        self.assertEqual(result["validation_scope"]["real_si"], "NOT_TESTED")
        self.assertEqual(result["validation_scope"]["synthetic_arithmetic"], "TESTED")
        if "no_quantification_performed" in result:
            self.assertTrue(result["no_quantification_performed"])

    def test_live_status_contract_reports_helper_hash_and_unverified_real_spectroscopy(self):
        image = make_cube(2)
        status = backend_for(image).ping()
        helper_path = os.path.join(os.path.dirname(BRIDGE_PATH), "spectroscopy.py")
        self.assertEqual(status["spectroscopy_code_sha256"], file_hash(helper_path))
        self.assertEqual(status["bridge_code_sha256"], file_hash(BRIDGE_PATH))
        self.assertEqual(status["bridge_version"], "0.6.0")
        for technique in ("real_eds", "real_eels", "real_si"):
            self.assertEqual(status["spectroscopy_validation"][technique], "NOT_TESTED")
        self.assertEqual(image.pixel_reads, 0)

    def test_info_uses_native_dimension_order_and_calibration_tuple_without_pixels(self):
        image = make_cube(1)
        backend = backend_for(image)
        info = backend.spectrum_info(71, 1, [[1, 3], [1, 4]])
        self.assertEqual(image.pixel_reads, 0)
        self.assertEqual(info["source_shape"], [3, 8, 5])
        self.assertEqual(info["energy_calibration"]["dm_dimension"], 1)
        self.assertEqual(info["energy_calibration"]["pixel_zero_eV"], -500.0)
        self.assertEqual(info["energy_calibration"]["scale_eV"], 250.0)
        self.assertEqual(info["energy_calibration"]["last_center_eV"], 1250.0)
        self.assertEqual(info["selected_shape"], [2, 8, 3])
        self.assertEqual(info["spatial_sample_count"], 6)
        self.assertEqual(info["source_intensity_unit"], None)
        self.assertEqual(info["backend"], "digitalmicrograph")
        # The adapter name identifies code under test, never native validation.
        self.assert_unverified(info)
        self.assertIn("no EDS/EELS identity inferred", info["technique"])
        self.assertTrue(all(fmt == 0 for unused, fmt in image.calibration_calls))
        self.assertEqual(backend.DM.resolved, [71])
        json.dumps(info, allow_nan=False)

    def test_nm_reciprocal_and_unknown_energy_axes_reject_before_pixel_access(self):
        for unit in ("nm", "1/nm", "mrad", "", None):
            with self.subTest(unit=unit):
                image = FakeImageAPI(np.zeros((3, 8), dtype=np.uint32), [(0.3, "nm", 0), (0.5, unit, 0)])
                backend = backend_for(image)
                with self.assertRaises(ValueError):
                    backend.spectrum_info(71, 1)
                with self.assertRaises(ValueError):
                    backend.spectrum(71, 1)
                with self.assertRaises(ValueError):
                    backend.spectrum_integrate(71, 1, [0, 1])
                self.assertEqual(image.pixel_reads, 0)

    def test_four_dimensional_diffraction_rejected_before_pixel_access_even_if_energy_labelled(self):
        image = FakeImageAPI(np.zeros((2, 3, 4, 5), dtype=np.uint32),
                             [(1.0, "nm", 0), (1.0, "nm", 0), (0.1, "1/nm", 0), (0.5, "eV", 0)])
        backend = backend_for(image)
        with self.assertRaisesRegex(ValueError, "4D diffraction"):
            backend.spectrum(71, 3)
        self.assertEqual(image.pixel_reads, 0)

    def test_explicit_dataset_id_and_invalid_spatial_selection_reject_without_pixels(self):
        image = make_cube(2)
        backend = backend_for(image)
        for image_id in (None, "front", "71", True, -1, 71.0):
            with self.subTest(image_id=image_id):
                with self.assertRaises(ValueError):
                    backend.spectrum_info(image_id, 2)
        self.assertEqual(backend.DM.resolved, [])
        for bounds in ([], [[0, 1]], [[0, 4], [0, 5]], [[0, 3], [0, 6]], [[2, 2], [0, 5]]):
            with self.subTest(bounds=bounds):
                with self.assertRaises(ValueError):
                    backend.spectrum(71, 2, bounds)
        self.assertEqual(image.pixel_reads, 0)

    def test_energy_first_middle_and_last_non_square_roi_reductions_and_map_calibration(self):
        for axis in (0, 1, 2):
            with self.subTest(energy_axis=axis):
                image = make_cube(axis)
                before = array_hash(image.array)
                original = image.array.copy()
                backend = backend_for(image)
                bounds, window = [[1, 3], [1, 4]], [-250.0, 750.0]
                expected_sum = [float(sum(1000000 + 100*energy + 10*y + x
                    for y in range(1, 3) for x in range(1, 4))) for energy in range(1, 5)]
                expected_map = [[float(sum(1000000 + 100*energy + 10*y + x
                    for energy in range(1, 5))) for x in range(1, 4)] for y in range(1, 3)]
                summed = backend.spectrum(71, axis, bounds, "sum", window)
                averaged = backend.spectrum(71, axis, bounds, "mean", window)
                integrated = backend.spectrum_integrate(71, axis, window, bounds)
                self.assertEqual(summed["channel_indices"], [1, 2, 3, 4])
                self.assertEqual(summed["energy_eV"], [-250.0, 0.0, 250.0, 500.0])
                self.assertEqual(summed["intensity"], expected_sum)
                self.assertEqual(averaged["intensity"], [value/6.0 for value in expected_sum])
                self.assertEqual(integrated["integrated_values"], expected_map)
                self.assertEqual(integrated["output_shape"], [2, 3])
                self.assertAlmostEqual(integrated["output_axes"][0]["calibrated_value_at_pixel_zero"], -0.9)
                self.assertAlmostEqual(integrated["output_axes"][1]["calibrated_value_at_pixel_zero"], 4.4)
                self.assertEqual([record["source_numpy_axis"] for record in integrated["output_axes"]], [n for n in range(3) if n != axis])
                self.assertEqual(integrated["selected_channel_indices"], [1, 2, 3, 4])
                self.assertEqual(image.pixel_reads, 3)
                self.assertEqual(array_hash(image.array), before)
                np.testing.assert_array_equal(image.array, original)
                for result in (summed, averaged, integrated):
                    self.assert_unverified(result)
                    self.assertEqual(result["source_intensity_unit"], None)
                    json.dumps(result, allow_nan=False)

    def test_one_dimensional_spectrum_and_descending_energy_keep_channel_order(self):
        image = FakeImageAPI(np.array([2, 4, 10, 4, 2, 0], dtype=np.uint32), [(-0.5, "eV", 1.5)])
        backend = backend_for(image)
        extracted = backend.spectrum(71, 0, [], "mean", [-0.5, 1.0])
        self.assertEqual(extracted["channel_indices"], [2, 3, 4])
        self.assertEqual(extracted["energy_eV"], [0.5, 0.0, -0.5])
        self.assertEqual(extracted["intensity"], [10.0, 4.0, 2.0])
        integrated = backend.spectrum_integrate(71, 0, [-0.5, 1.0], [])
        self.assertEqual(integrated["output_shape"], [])
        self.assertEqual(integrated["integrated_values"], 16.0)
        self.assertEqual(integrated["output_axes"], [])

    def test_metadata_array_shape_disagreement_is_explicit(self):
        image = make_cube(2)
        image.declared_shape = (3, 5, 7)
        backend = backend_for(image)
        with self.assertRaisesRegex(RuntimeError, "轴序/尺寸"):
            backend.spectrum(71, 2)
        self.assertEqual(image.pixel_reads, 1)

    def test_structured_rgb_values_are_not_treated_as_numeric_spectra(self):
        rgb = np.zeros((3, 8), dtype=[("r", "u1"), ("g", "u1"), ("b", "u1")])
        image = FakeImageAPI(rgb, [(0.3, "nm", 0), (0.5, "eV", 0)])
        backend = backend_for(image)
        with self.assertRaisesRegex(ValueError, "RGB/structured"):
            backend.spectrum(71, 1)
        # Structured dtype is only discoverable from this fake's pixel array.
        # A native RGB-code preflight, if present, is tested separately.
        self.assertEqual(image.pixel_reads, 1)

    def test_native_rgb_packed_complex_and_unknown_types_reject_before_pixel_read(self):
        for native_code in (3, 4, 5, 8, 13, 23, 999):
            with self.subTest(native_type=native_code):
                image = FakeImageAPI(np.zeros((3, 8), dtype=np.uint32),
                    [(0.3, "nm", 0), (0.5, "eV", 0)], data_type=native_code)
                backend = backend_for(image)
                with self.assertRaises(ValueError):
                    backend.spectrum(71, 1)
                self.assertEqual(image.pixel_reads, 0)

    def test_csv_roundtrip_float64_energy_sidecar_hash_and_source_file_unchanged(self):
        array = np.array([1.0000000000000002, 2.5, 10000000000.125, 0.0], dtype=np.float64)
        image = FakeImageAPI(array, [(0.25, "eV", -0.5)])
        backend = backend_for(image)
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "original.npy")
            np.save(source, array, allow_pickle=False)
            before_file, before_array = file_hash(source), array_hash(array)
            backend._source_files[71] = source
            target = os.path.join(directory, "derived", "spectrum.csv")
            output = backend.spectrum_export(71, 0, target)
            with open(target, "r", encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(reader.fieldnames, ["energy_eV", "intensity"])
                rows = list(reader)
            self.assertEqual([float(row["energy_eV"]) for row in rows], [-0.5, -0.25, 0.0, 0.25])
            self.assertEqual([float(row["intensity"]) for row in rows], array.tolist())
            with open(output["metadata_path"], "r", encoding="utf-8") as stream:
                metadata = json.load(stream)
            self.assertEqual(metadata["columns"], ["energy_eV", "intensity"])
            self.assertEqual(metadata["sha256"], file_hash(target))
            self.assertEqual(output["sha256"], file_hash(target))
            self.assertEqual(metadata["source_file"], source)
            self.assertEqual(metadata["source_intensity_unit"], None)
            self.assertEqual(metadata["reduction"], "sum")
            self.assertEqual(metadata["energy_calibration"]["pixel_zero_eV"], -0.5)
            self.assertEqual(metadata["energy_calibration"]["scale_eV"], 0.25)
            self.assert_unverified(metadata)
            self.assert_unverified(output)
            self.assertEqual(file_hash(source), before_file)
            self.assertEqual(array_hash(image.array), before_array)
            self.assertEqual(sorted(os.listdir(os.path.dirname(target))), ["spectrum.csv", "spectrum.csv.metadata.json"])

    def test_existing_csv_or_sidecar_refuses_without_pixel_read_or_file_changes(self):
        for existing in ("csv", "sidecar"):
            with self.subTest(existing=existing):
                image = make_cube(2)
                backend = backend_for(image)
                with tempfile.TemporaryDirectory() as directory:
                    path = os.path.join(directory, "spectrum.csv")
                    preserve = path if existing == "csv" else path + ".metadata.json"
                    with open(preserve, "wb") as stream:
                        stream.write(b"must remain byte-for-byte unchanged")
                    before = file_hash(preserve)
                    with self.assertRaises(FileExistsError):
                        backend.spectrum_export(71, 2, path)
                    self.assertEqual(image.pixel_reads, 0)
                    self.assertEqual(file_hash(preserve), before)
                    self.assertEqual(os.listdir(directory), [os.path.basename(preserve)])

    def test_publish_failure_removes_own_sidecar_and_staging_only(self):
        backend = backend_for(make_cube(2))
        with tempfile.TemporaryDirectory() as directory:
            unrelated = os.path.join(directory, "existing-result.csv")
            with open(unrelated, "wb") as stream:
                stream.write(b"prior scientific result")
            before = file_hash(unrelated)
            path = os.path.join(directory, "failed.csv")
            with mock.patch.object(backend, "_publish_spectral_file", side_effect=RuntimeError("synthetic publication failure")):
                with self.assertRaisesRegex(RuntimeError, "synthetic publication failure"):
                    backend.spectrum_export(71, 2, path)
            self.assertEqual(os.listdir(directory), ["existing-result.csv"])
            self.assertEqual(file_hash(unrelated), before)

    def test_racing_csv_is_preserved_and_new_sidecar_rolled_back(self):
        backend = backend_for(make_cube(2))
        publisher = backend._publish_spectral_file
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "raced.csv")
            def publish_after_another_client(source, destination):
                with open(destination, "xb") as stream:
                    stream.write(b"another client's existing result")
                publisher(source, destination)
            with mock.patch.object(backend, "_publish_spectral_file", side_effect=publish_after_another_client):
                with self.assertRaises(FileExistsError):
                    backend.spectrum_export(71, 2, path)
            with open(path, "rb") as stream:
                self.assertEqual(stream.read(), b"another client's existing result")
            self.assertEqual(os.listdir(directory), ["raced.csv"])

    def test_copy_failure_removes_partial_csv_and_own_sidecar(self):
        backend = backend_for(make_cube(2))
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "partial.csv")
            def fail_after_partial_copy(source, destination):
                destination.write(b"partial")
                raise OSError("synthetic disk failure")
            with mock.patch.object(bridge.shutil, "copyfileobj", side_effect=fail_after_partial_copy):
                with self.assertRaisesRegex(OSError, "synthetic disk failure"):
                    backend.spectrum_export(71, 2, path)
            self.assertEqual(os.listdir(directory), [])

    def test_dispatcher_four_operations_preserve_selection_and_default_sum(self):
        image = make_cube(2)
        dispatcher = bridge.Dispatcher(backend_for(image))
        base = {"image_id": 71, "energy_axis": 2, "spatial_bounds": [[1, 3], [1, 4]]}
        info = dispatcher.handle({"op": "spectrum_info", "args": base})
        self.assertEqual(info["spatial_sample_count"], 6)
        self.assertEqual(image.pixel_reads, 0)
        selected = dict(base, energy_window_eV=[-250.0, 250.0])
        spectrum = dispatcher.handle({"op": "spectrum", "args": selected})
        self.assertEqual(spectrum["reduction"], "sum")
        self.assertEqual(spectrum["channel_indices"], [1, 2])
        integrated = dispatcher.handle({"op": "spectrum_integrate", "args": selected})
        self.assertEqual(integrated["selected_channel_indices"], [1, 2])
        with tempfile.TemporaryDirectory() as directory:
            exported = dispatcher.handle({"op": "spectrum_export", "args": dict(selected, path=os.path.join(directory, "dispatch.csv"), reduction="mean")})
            with open(exported["metadata_path"], "r", encoding="utf-8") as stream:
                self.assertEqual(json.load(stream)["reduction"], "mean")
            self.assertTrue(os.path.isfile(exported["path"]))

    def test_generic_npy_export_preserves_1d_and_3d_raw_shape_dtype_and_calibration(self):
        images = [FakeImageAPI(np.array([0, 65536, 4294967295], dtype=np.uint32), [(0.5, "eV", -1)]), make_cube(1)]
        for image in images:
            with self.subTest(shape=image.array.shape):
                backend = backend_for(image)
                before = array_hash(image.array)
                with tempfile.TemporaryDirectory() as directory:
                    output = backend.export(71, os.path.join(directory, "raw.npy"), "npy")
                    restored = np.load(output["path"], allow_pickle=False)
                    self.assertEqual(restored.dtype, image.array.dtype)
                    self.assertEqual(restored.shape, image.array.shape)
                    np.testing.assert_array_equal(restored, image.array)
                    with open(output["metadata_path"], "r", encoding="utf-8") as stream:
                        metadata = json.load(stream)
                    self.assertEqual(metadata["sha256"], file_hash(output["path"]))
                    self.assertEqual(metadata["shape"], list(image.array.shape))
                    for record in metadata["calibration"]:
                        axis = record["numpy_axis"]
                        self.assertEqual(record["scale"], image.axes[axis][0])
                        self.assertEqual(record["unit"], image.axes[axis][1])
                        self.assertEqual(record["calibrated_value_at_pixel_zero"], image.axes[axis][2])
                    self.assertEqual(array_hash(image.array), before)


class SyntheticFixtureTests(unittest.TestCase):
    def test_mock_1d_and_si_fixture_values_are_explicitly_synthetic_and_unverified(self):
        backend = bridge.MockBackend()
        spectrum = backend.spectrum(1002, 0)
        self.assertTrue(spectrum["synthetic"])
        self.assertEqual(spectrum["energy_eV"], [-1.0, -0.5, 0.0, 0.5, 1.0, 1.5])
        self.assertEqual(spectrum["intensity"], [2.0, 4.0, 10.0, 4.0, 2.0, 0.0])
        integrated = backend.spectrum_integrate(1002, 0, [-0.5, 1.0])
        self.assertEqual(integrated["integrated_values"], 18.0)
        si = backend.spectrum(1003, 2)
        self.assertEqual(si["energy_eV"], [250.0 * i for i in range(8)])
        self.assertEqual(si["intensity"], [360.0 + 6*i for i in range(8)])
        self.assertTrue(si["synthetic"])
        self.assertEqual(si["source_intensity_unit"], "a.u. (synthetic)")
        for result in (spectrum, integrated, si):
            self.assertEqual(result["validation_scope"]["real_eds"], "NOT_TESTED")
            self.assertEqual(result["validation_scope"]["real_eels"], "NOT_TESTED")
            self.assertEqual(result["validation_scope"]["real_si"], "NOT_TESTED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
