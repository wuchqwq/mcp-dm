# -*- coding: utf-8 -*-
"""Synthetic contract tests for native_stream; no DM, source data, or sockets.

The fake only models documented binary-stream postconditions. Passing these
tests does not verify native Gatan script execution or real DM4 interpretation.
"""

import importlib.util
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

sys.dont_write_bytecode = True
MODULE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bridge", "native_stream.py"))
SPEC = importlib.util.spec_from_file_location("native_stream_test_subject", MODULE)
native_stream = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native_stream)
NativePatternReader = native_stream.NativePatternReader


class FakeImage(object):
    def __init__(self, identifier, array):
        self.identifier = identifier
        self.array = array.copy(order="C")
        self.valid = True

    def IsValid(self):
        return self.valid

    def GetID(self):
        return self.identifier

    def GetNumDimensions(self):
        return self.array.ndim

    def GetDimensionSize(self, axis):
        return self.array.shape[-1 - axis]

    def GetNumArray(self):
        return self.array


class FakeDM(object):
    def __init__(self, payload):
        self.payload = payload
        self.images = {}
        self.next_id = 1
        self.scripts = []
        self.created = []
        self.deleted = []
        self.mode = "normal"
        self.virtual_size = None

    def CreateImage(self, array):
        image = FakeImage(self.next_id, array)
        self.next_id += 1
        self.images[image.GetID()] = image
        self.created.append((image.GetID(), array.shape, array.dtype))
        return image

    def DeleteImage(self, image):
        image.valid = False
        self.deleted.append(image.GetID())
        del self.images[image.GetID()]

    def ExecuteScriptString(self, script):
        self.scripts.append(script)
        if self.mode == "silent_script_error":
            return
        if self.mode == "python_exception":
            raise RuntimeError("synthetic native-call exception")
        self.assert_read_only_script(script)
        ids = [int(v) for v in re.findall(r'FindImageByID\((\d+)\)', script)]
        tile, status = [self.images[i] for i in ids]
        offset = int(re.search(r'StreamSetPos\(0, (\d+)\)', script).group(1))
        size = self.virtual_size if self.virtual_size is not None else len(self.payload)
        status.array[0, 0] = size + (1 if self.mode == "wrong_size" else 0)
        if self.mode == "wrong_size":
            return
        status.array[0, 1] = offset + (1 if self.mode == "wrong_seek" else 0)
        if self.mode == "wrong_seek":
            return
        count = tile.array.size
        if self.virtual_size is None:
            block = np.frombuffer(self.payload[offset:offset + count], dtype=np.uint8)
        else:
            block = ((np.arange(count, dtype=np.uint64) + offset) % 251).astype(np.uint8)
        tile.array[...] = block.reshape(tile.array.shape)
        status.array[0, 2] = offset + count - (1 if self.mode == "short_read" else 0)

    @staticmethod
    def assert_read_only_script(script):
        if "OpenFileForReading(" not in script or "NewStreamFromFileReference(fileID, 1)" not in script:
            raise AssertionError("script must use scoped read-only native stream")
        for forbidden in ("OpenImage", "ShowImage", "CreateFile", "Writing", "WriteImage"):
            if forbidden in script:
                raise AssertionError("forbidden operation: " + forbidden)


class NativeStreamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dm_native_stream_")
        self.path = os.path.join(self.temp.name, "synthetic.bin")
        self.offset = 37
        self.data = np.arange(3 * 5 * 2 * 4, dtype=np.uint8).reshape(3, 5, 2, 4)
        self.payload = b"x" * self.offset + self.data.tobytes() + b"TAIL"
        with open(self.path, "wb") as stream:
            stream.write(self.payload)
        self.dm = FakeDM(self.payload)
        self.readers = []

    def tearDown(self):
        for reader in self.readers:
            reader.close()
        self.temp.cleanup()

    def reader(self, **overrides):
        kwargs = dict(dm=self.dm, path=self.path, data_offset=self.offset,
                      shape=self.data.shape, dtype="uint8")
        kwargs.update(overrides)
        result = NativePatternReader(**kwargs)
        self.readers.append(result)
        return result

    def test_exact_small_read_with_native_postconditions_and_no_full_cube(self):
        reader = self.reader()
        result = reader.read_patterns(1, 1, 4)
        np.testing.assert_array_equal(result, self.data[1, 1:4])
        self.assertTrue(result.flags.c_contiguous)
        evidence = reader.last_read_evidence
        self.assertTrue(evidence["native_postconditions_verified"])
        self.assertEqual(evidence["seek_offset_bytes"], self.offset + 6 * 8)
        self.assertEqual(evidence["read_end_offset_bytes"], self.offset + 9 * 8)
        self.assertEqual([x[1] for x in self.dm.created], [(3, 2, 4), (1, 3)])
        self.assertLessEqual(evidence["conservative_working_bytes"], reader.max_chunk_bytes)

    def test_return_is_detached_and_one_tile_is_reused(self):
        reader = self.reader()
        first = reader.read_patterns(0, 0, 2)
        first.fill(255)
        second = reader.read_patterns(2, 3, 5)
        np.testing.assert_array_equal(second, self.data[2, 3:5])
        self.assertEqual(len(self.dm.created), 2)
        self.assertFalse(np.shares_memory(second, reader._tile.GetNumArray()))

    def test_size_change_releases_previous_tile_before_new_allocation(self):
        reader = self.reader()
        reader.read_patterns(0, 0, 2)
        old_id = reader._tile.GetID()
        reader.read_patterns(0, 0, 3)
        self.assertIn(old_id, self.dm.deleted)
        self.assertEqual(len(self.dm.images), 2)

    def test_close_releases_both_images_and_rejects_further_read(self):
        reader = self.reader()
        reader.read_patterns(0, 0, 1)
        reader.close()
        reader.close()
        self.assertEqual(self.dm.images, {})
        with self.assertRaises(RuntimeError):
            reader.read_patterns(0, 0, 1)

    def test_source_payload_and_mtime_unchanged(self):
        before = os.stat(self.path)
        reader = self.reader()
        reader.read_patterns(2, 4, 5)
        after = os.stat(self.path)
        with open(self.path, "rb") as stream:
            self.assertEqual(stream.read(), self.payload)
        self.assertEqual((before.st_size, before.st_mtime_ns), (after.st_size, after.st_mtime_ns))

    def test_bad_ranges_rejected_before_native_image_creation(self):
        reader = self.reader()
        for arguments in [(-1, 0, 1), (3, 0, 1), (0, 1, 1), (0, 0, 6),
                          (0, 0, 1.5), (True, 0, 1)]:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                reader.read_patterns(*arguments)
        self.assertEqual(self.dm.created, [])

    def test_budget_includes_native_and_copy_buffers(self):
        reader = self.reader(max_chunk_bytes=3 * 8 * 2 + 96)
        self.assertEqual(reader.max_patterns, 2)
        reader.read_patterns(0, 0, 2)
        self.assertEqual(reader.last_read_evidence["conservative_working_bytes"], reader.max_chunk_bytes)
        with self.assertRaises(ValueError):
            reader.read_patterns(0, 0, 3)

    def test_constructor_guards_dtype_shape_offset_and_budget(self):
        for overrides in [dict(dtype="uint16"), dict(shape=(3, 5, 8)),
                          dict(shape=(3, True, 2, 4)), dict(data_offset=-1),
                          dict(data_offset=99999), dict(max_chunk_bytes=1)]:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.reader(**overrides)

    def test_unsafe_paths_rejected(self):
        for path in ['a"b', "a'b", "a\nb", "中文", "a\x7fb"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.reader(path=path)

    def test_source_changed_before_read_rejected(self):
        reader = self.reader()
        with open(self.path, "ab") as stream:
            stream.write(b"!")
        with self.assertRaisesRegex(RuntimeError, "changed"):
            reader.read_patterns(0, 0, 1)
        self.assertEqual(self.dm.created, [])

    def test_silent_native_error_never_marks_success(self):
        reader = self.reader()
        for mode in ["silent_script_error", "wrong_size", "wrong_seek", "short_read"]:
            self.dm.mode = mode
            with self.subTest(mode=mode), self.assertRaisesRegex(RuntimeError, "postcondition"):
                reader.read_patterns(0, 0, 1)
            self.assertIsNone(reader.last_read_evidence)
        self.assertFalse(reader.info["runtime_verified"])

    def test_native_exception_propagates_and_buffers_close(self):
        reader = self.reader()
        self.dm.mode = "python_exception"
        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            reader.read_patterns(0, 0, 1)
        self.assertIsNone(reader.last_read_evidence)
        reader.close()
        self.assertEqual(self.dm.images, {})

    def test_exact_large_offset_contract_without_creating_large_fixture(self):
        # Synthetic numeric/serialization contract only, not a native >4GB pass.
        large_offset = 2 ** 32 + 123
        identity = (large_offset + self.data.size + 4, 1234, 1, 2)
        self.dm.virtual_size = identity[0]
        with mock.patch.object(NativePatternReader, "_stat_identity", return_value=identity):
            reader = self.reader(data_offset=large_offset)
            result = reader.read_patterns(2, 4, 5)
        offset = large_offset + 14 * 8
        expected = ((np.arange(8, dtype=np.uint64) + offset) % 251).astype(np.uint8).reshape(1, 2, 4)
        np.testing.assert_array_equal(result, expected)
        self.assertEqual(reader.last_read_evidence["seek_offset_bytes"], offset)
        self.assertTrue(reader.last_read_evidence["offset_above_uint32"])
        self.assertIn("StreamSetPos(0, %d)" % offset, self.dm.scripts[-1])

    def test_float64_inexact_file_size_rejected(self):
        with mock.patch.object(NativePatternReader, "_stat_identity", return_value=(2 ** 53 + 1, 1, 1, 1)):
            with self.assertRaisesRegex(ValueError, "exact"):
                self.reader()


if __name__ == "__main__":
    unittest.main()
