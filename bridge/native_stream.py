# -*- coding: utf-8 -*-
"""Bounded, read-only native Gatan byte-range reads for canonical 4D-STEM.

This module does not open a whole DM4 document. A separately validated header
reader supplies the uncompressed uint8 payload offset and canonical NumPy shape
``(scan_y, scan_x, detector_y, detector_x)``. Gatan's native binary stream reader
loads only the requested consecutive diffraction patterns into a small image.

GMS Python 3.7 / NumPy 1.18 compatible. No sockets, hardware, or arbitrary script
entry point. Runtime acceptance is separate from fake-DM contract tests.
"""

import math
import os

import numpy as np


_STATUS_BYTES = 3 * np.dtype("float64").itemsize
# Conservative allowance for source zeros + native image + caller copy, and
# status zeros/native/view snapshot. Caller-retained older outputs are external.
_FIXED_WORKING_BYTES = 4 * _STATUS_BYTES
_EXACT_NUMBER_LIMIT = 2 ** 53


def _integer(value, label, minimum=0):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise ValueError("%s must be an integer" % label)
    value = int(value)
    if value < minimum:
        raise ValueError("%s must be >= %d" % (label, minimum))
    return value


class NativePatternReader(object):
    """Read one bounded contiguous scan-row interval through native Gatan I/O.

    ``max_chunk_bytes`` is a conservative per-call helper allocation bound,
    including native buffers and the returned array. It does not include arrays
    retained by the caller or other DM documents. This object is not thread-safe;
    use it on the existing serialized DM execution path and call ``close()``.
    """

    def __init__(self, dm, path, data_offset, shape, dtype,
                 max_chunk_bytes=33554432):
        self.dm = dm
        self.path = os.fspath(path)
        if not isinstance(self.path, str):
            raise ValueError("path must be an ASCII string")
        if (not self.path or any(ord(c) < 32 or ord(c) > 126 for c in self.path)
                or '"' in self.path or "'" in self.path):
            raise ValueError("native stream path must be ASCII without controls or quotes")
        self.path = os.path.abspath(self.path)
        self._script_path = self.path.replace("\\", "/")
        if len(shape) != 4:
            raise ValueError("shape must be canonical [scan_y,scan_x,detector_y,detector_x]")
        self.shape = tuple(_integer(v, "shape[%d]" % i, 1) for i, v in enumerate(shape))
        self.dtype = np.dtype(dtype)
        if self.dtype != np.dtype("uint8"):
            raise ValueError("native pattern reader currently supports uint8 only")
        self.data_offset = _integer(data_offset, "data_offset")
        self.max_chunk_bytes = _integer(max_chunk_bytes, "max_chunk_bytes", 1)
        self.pattern_bytes = self.shape[2] * self.shape[3]
        self.data_bytes = math.prod(self.shape) if hasattr(math, "prod") else (
            self.shape[0] * self.shape[1] * self.shape[2] * self.shape[3])
        self.data_end = self.data_offset + self.data_bytes
        self._source_stat = self._stat_identity()
        self.file_size = self._source_stat[0]
        if self.data_end > self.file_size:
            raise ValueError("payload extends beyond the source file")
        if self.file_size > _EXACT_NUMBER_LIMIT or self.data_end > _EXACT_NUMBER_LIMIT:
            raise ValueError("source offsets exceed exact Gatan Number/float64 integer range")
        self.max_patterns = max(0, (self.max_chunk_bytes - _FIXED_WORKING_BYTES)
                                // (3 * self.pattern_bytes))
        if self.max_patterns < 1:
            raise ValueError("max_chunk_bytes cannot hold one pattern and native/copy buffers")
        self.max_patterns = min(self.shape[1], self.max_patterns)
        self._tile = None
        self._tile_shape = None
        self._status = None
        self._closed = False
        self.last_read_evidence = None
        self.info = {
            "method": "gatan_native_read_only_binary_stream",
            "whole_document_opened": False,
            "dm4_header_parser": "external validated descriptor required",
            "canonical_shape": list(self.shape),
            "dtype": "uint8",
            "data_offset": self.data_offset,
            "data_bytes": self.data_bytes,
            "file_size_bytes": self.file_size,
            "max_chunk_bytes": self.max_chunk_bytes,
            "max_patterns": self.max_patterns,
            "buffer_budget": "3 * requested_data_bytes + 96; caller retained arrays excluded",
            "source_access": "OpenFileForReading only",
            "native_api": ["CreateImage", "FindImageByID", "OpenFileForReading",
                           "NewStreamFromFileReference", "StreamSetPos",
                           "ImageReadImageDataFromStream", "StreamGetPos", "StreamGetSize"],
            "runtime_verified": False,
        }

    def _stat_identity(self):
        stat = os.stat(self.path)
        if not os.path.isfile(self.path):
            raise ValueError("source must be a regular file")
        return (int(stat.st_size), int(stat.st_mtime_ns), int(stat.st_dev), int(stat.st_ino))

    def _delete(self, image):
        if image is not None:
            self.dm.DeleteImage(image)

    def _ensure_images(self, n):
        wanted = (n, self.shape[2], self.shape[3])
        if self._tile is not None and self._tile_shape != wanted:
            old, self._tile = self._tile, None
            self._tile_shape = None
            self._delete(old)
            del old
        if self._tile is None:
            zeros = np.zeros(wanted, dtype=np.uint8, order="C")
            try:
                self._tile = self.dm.CreateImage(zeros)
            finally:
                del zeros
            self._tile_shape = wanted
        if self._status is None:
            zeros = np.zeros((1, 3), dtype=np.float64)
            try:
                self._status = self.dm.CreateImage(zeros)
            finally:
                del zeros
        self._check_native_image(self._tile, wanted, np.dtype("uint8"))
        self._check_native_image(self._status, (1, 3), np.dtype("float64"))

    @staticmethod
    def _check_native_image(image, shape, dtype):
        if not bool(image.IsValid()):
            raise RuntimeError("native temporary image is invalid")
        if int(image.GetNumDimensions()) != len(shape):
            raise RuntimeError("native temporary image dimensionality differs")
        dimensions = [int(image.GetDimensionSize(i)) for i in range(len(shape))]
        if dimensions != list(reversed(shape)):
            raise RuntimeError("native temporary image dimensions differ: %s" % dimensions)
        array = image.GetNumArray()
        try:
            if array.shape != shape or array.dtype != dtype or not array.flags.c_contiguous:
                raise RuntimeError("native temporary image array layout/type differs")
        finally:
            del array

    def read_patterns(self, scan_y, x0, x1):
        if self._closed:
            raise RuntimeError("native pattern reader is closed")
        self.last_read_evidence = None
        scan_y = _integer(scan_y, "scan_y")
        x0 = _integer(x0, "x0")
        x1 = _integer(x1, "x1")
        if scan_y >= self.shape[0] or x1 <= x0 or x1 > self.shape[1]:
            raise ValueError("requested scan row/interval is out of bounds")
        n = x1 - x0
        if n > self.max_patterns:
            raise ValueError("requested %d patterns exceeds bounded limit %d"
                             % (n, self.max_patterns))
        nbytes = n * self.pattern_bytes
        budget = 3 * nbytes + _FIXED_WORKING_BYTES
        offset = self.data_offset + (scan_y * self.shape[1] + x0) * self.pattern_bytes
        end = offset + nbytes
        if offset < self.data_offset or end > self.data_end or end > self.file_size:
            raise ValueError("requested byte interval is outside the payload")
        if self._stat_identity() != self._source_stat:
            raise RuntimeError("source identity/size/mtime changed since reader construction")
        self._ensure_images(n)
        status = self._status.GetNumArray()
        status.fill(np.nan)
        tile_id = _integer(self._tile.GetID(), "tile image ID", 1)
        status_id = _integer(self._status.GetID(), "status image ID", 1)
        # All substituted values are validated integers or an ASCII, quote-free
        # pathname. Source open mode is fixed and cannot be changed by callers.
        script = (
            'void dm_mcp_native_pattern_read()\n{\n'
            ' image tile := FindImageByID(%d)\n'
            ' image evidence := FindImageByID(%d)\n'
            ' number fileID = OpenFileForReading("%s")\n'
            ' object inputStream = NewStreamFromFileReference(fileID, 1)\n'
            ' number sourceSize = inputStream.StreamGetSize()\n'
            ' evidence.SetPixel(0, 0, sourceSize)\n'
            ' if (sourceSize != %d) Throw("Native stream source size differs")\n'
            ' inputStream.StreamSetPos(0, %d)\n'
            ' number actualStart = inputStream.StreamGetPos()\n'
            ' evidence.SetPixel(1, 0, actualStart)\n'
            ' if (actualStart != %d) Throw("Native stream seek failed")\n'
            ' tile.ImageReadImageDataFromStream(inputStream, 2)\n'
            ' number actualEnd = inputStream.StreamGetPos()\n'
            ' evidence.SetPixel(2, 0, actualEnd)\n'
            ' if (actualEnd != %d) Throw("Native stream read length differs")\n'
            '}\n'
            'dm_mcp_native_pattern_read()\n'
        ) % (tile_id, status_id, self._script_path, self.file_size,
             offset, offset, end)
        try:
            self.dm.ExecuteScriptString(script)
            observed = np.array(status, dtype=np.float64, copy=True).reshape(3)
        finally:
            del status
        expected = np.array([self.file_size, offset, end], dtype=np.float64)
        if not np.array_equal(observed, expected):
            raise RuntimeError("native read postcondition failed: expected %s, got %s; "
                               "inspect DM Results for a script error"
                               % (expected.tolist(), observed.tolist()))
        if self._stat_identity() != self._source_stat:
            raise RuntimeError("source identity/size/mtime changed during native read")
        self._check_native_image(self._tile, (n, self.shape[2], self.shape[3]), self.dtype)
        data = self._tile.GetNumArray()
        try:
            output = data.copy(order="C")
        finally:
            del data
        self.last_read_evidence = {
            "method": self.info["method"],
            "native_postconditions_verified": True,
            "file_size_bytes": int(observed[0]),
            "seek_offset_bytes": int(observed[1]),
            "read_end_offset_bytes": int(observed[2]),
            "offset_above_uint32": offset > 2 ** 32 - 1,
            "source_interval": [scan_y, x0, x1],
            "shape": list(output.shape),
            "dm_dimensions": list(reversed(output.shape)),
            "dtype": str(output.dtype),
            "data_bytes": nbytes,
            "conservative_working_bytes": budget,
            "max_chunk_bytes": self.max_chunk_bytes,
            "source_stat_unchanged": True,
            "source_access": "read_only",
        }
        self.info["runtime_verified"] = True
        return output

    def close(self):
        if self._closed:
            return
        self._closed = True
        errors = []
        for name in ("_tile", "_status"):
            image = getattr(self, name)
            setattr(self, name, None)
            try:
                self._delete(image)
            except Exception as exc:
                errors.append(str(exc))
            finally:
                del image
        self._tile_shape = None
        if errors:
            raise RuntimeError("failed to release native temporary image(s): " + "; ".join(errors))

    def __enter__(self):
        if self._closed:
            raise RuntimeError("native pattern reader is closed")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            self.close()
        except Exception:
            if exc_type is None:
                raise
        return False
