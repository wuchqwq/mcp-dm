# -*- coding: utf-8 -*-
"""Run explicitly once in DM after native calls, to verify source invariance.

Checks only IDs created by create_fixture.py in this private test session.
This is an independent Python oracle, not part of native request execution.
"""
import hashlib
import json
import os
import numpy as np
import DigitalMicrograph as DM

_directory = os.environ["DM_NATIVE_EVIDENCE_DIR"]
_fixture_file = "fixture-ascii.json" if os.path.exists(os.path.join(_directory, "fixture-ascii.json")) else "fixture.json"
with open(os.path.join(_directory, _fixture_file), encoding="utf-8") as _file:
    _truth = json.load(_file)
if _truth["session"] != os.environ["DM_NATIVE_SESSION"]:
    raise RuntimeError("Fixture session mismatch")
_checks = []
for _source in _truth["images"]:
    _image = DM.FindImageByID(_source["id"])
    if _image is None or not _image.IsValid() or _image.GetName() != _source["name"]:
        raise RuntimeError("Fixture image identity changed")
    _array = np.array(_image.GetNumArray(), copy=True)
    _calibration = []
    for _axis in range(2):
        _origin, _scale, _unit = _image.GetDimensionCalibration(_axis, 0)
        _calibration.append({"dm_axis": _axis, "origin": float(_origin),
                             "scale": float(_scale), "unit": _unit})
    _same = (list(_array.shape) == _source["shape"] and str(_array.dtype) == _source["dtype"]
        and hashlib.sha256(_array.tobytes(order="C")).hexdigest() == _source["pixel_sha256"]
        and _calibration == _source["calibration"])
    _checks.append({"image_id": _source["id"], "source_unchanged": _same,
                    "mean": float(np.mean(_array, dtype=np.float64))})
    if not _same:
        raise RuntimeError("Source pixels or calibration changed")
with open(os.path.join(_directory, "source-invariance.json"), "x", encoding="utf-8") as _file:
    json.dump({"status": "PASS", "checks": _checks,
               "ordinary_python_after_native": True}, _file, indent=2, allow_nan=False)
del _image
print("PASS: source pixels/calibration unchanged; ordinary Python completed.")
