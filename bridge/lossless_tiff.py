"""Uncompressed, single-channel scientific TIFF; stdlib + NumPy, Python 3.7.

This writer retains the numeric dtype without display-driven downcasting.
Calibration is recorded in JSON and Gatan-compatible calibration tags.
It writes a new staging file only; publication/overwrite policy is the caller's.
"""
import json
import math
import struct

import numpy as np


def write_tiff(path, array, metadata):
    a = np.asarray(array)
    if a.ndim != 2 or a.size == 0:
        raise ValueError("TIFF requires one nonempty 2D scalar image")
    if a.dtype.kind not in "iuf" or a.dtype.itemsize not in (1, 2, 4, 8):
        raise ValueError("Unsupported scientific TIFF dtype: %s" % a.dtype)
    h, w = a.shape
    data = np.ascontiguousarray(a, dtype=a.dtype.newbyteorder("<"))
    description = json.dumps({"shape": [h, w], "axes": "YX", "dm_mcp": metadata},
                             ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    entries = {}

    def tag(code, kind, count, payload):
        entries[code] = (kind, count, payload)

    def short(code, value):
        tag(code, 3, 1, struct.pack("<H", value))

    def long(code, value):
        tag(code, 4, 1, struct.pack("<I", value))

    def text(code, value):
        # The full Unicode value is preserved in JSON; legacy DM calibration
        # tags require ASCII. Refuse unsupported units rather than mislabel them.
        raw = str(value).encode("ascii") + b"\0"
        tag(code, 2, len(raw), raw)

    def double(code, value):
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("Nonfinite TIFF calibration")
        tag(code, 12, 1, struct.pack("<d", value))

    long(256, w)
    long(257, h)
    short(258, 8 * a.dtype.itemsize)
    short(259, 1)  # no compression
    short(262, 1)  # black is zero; raw samples are never display-scaled
    text(270, description)
    long(273, 0)  # strip offset is filled after IFD/extras are laid out
    short(277, 1)
    long(278, h)
    if data.nbytes >= 2 ** 32:
        raise ValueError("Classic TIFF output exceeds 4 GiB; use NPY/DM4")
    long(279, data.nbytes)
    short(284, 1)
    short(296, 1)  # no implied inch/centimetre calibration
    short(339, {"u": 1, "i": 2, "f": 3}[a.dtype.kind])
    calibration = metadata.get("calibration", [])
    if len(calibration) >= 2:
        for axis, unit_tag, origin_tag, scale_tag in ((0, 65003, 65006, 65009),
                                                      (1, 65004, 65007, 65010)):
            c = calibration[axis]
            if c.get("unit") is not None:
                text(unit_tag, c["unit"])
            if c.get("scale") is not None:
                double(scale_tag, c["scale"])
            value_at_zero = c.get("calibrated_value_at_pixel_zero")
            if value_at_zero is not None:
                double(origin_tag, value_at_zero)
    intensity = metadata.get("intensity_calibration", {})
    if intensity.get("origin") is not None:
        double(65024, intensity["origin"])
    if intensity.get("scale") is not None:
        double(65025, intensity["scale"])

    def align(value):
        return (value + 7) // 8 * 8

    extra_start = align(8 + 2 + 12 * len(entries) + 4)
    extra = bytearray()
    ifd = []
    for code, (kind, count, payload) in sorted(entries.items()):
        if len(payload) <= 4:
            slot = payload.ljust(4, b"\0")
        else:
            extra.extend(b"\0" * (align(len(extra)) - len(extra)))
            slot = struct.pack("<I", extra_start + len(extra))
            extra.extend(payload)
        ifd.append((code, kind, count, slot))
    data_start = align(extra_start + len(extra))
    if data_start + data.nbytes >= 2 ** 32:
        raise ValueError("Classic TIFF offsets exceed 4 GiB; use NPY/DM4")
    with open(path, "xb") as stream:
        stream.write(b"II*\x00" + struct.pack("<I", 8))
        stream.write(struct.pack("<H", len(ifd)))
        for code, kind, count, slot in ifd:
            if code == 273:
                slot = struct.pack("<I", data_start)
            stream.write(struct.pack("<HHI", code, kind, count) + slot)
        stream.write(struct.pack("<I", 0))
        stream.write(b"\0" * (extra_start - stream.tell()))
        stream.write(extra)
        stream.write(b"\0" * (data_start - stream.tell()))
        stream.write(memoryview(data).cast("B"))
    return {"dtype": str(a.dtype), "compression": "none", "bits_per_sample": a.dtype.itemsize * 8,
            "calibration_storage": "ImageDescription JSON + Gatan axis calibration tags + metadata sidecar"}
