# -*- coding: utf-8 -*-
"""One-shot DM Python fixture creation; never a request listener.

Run explicitly in an empty test session, before any native image request.
Set DM_NATIVE_EVIDENCE_DIR to a fresh private directory before launching DM.
Only small synthetic images are created. No hardware or existing data access.
"""
import hashlib
import json
import os
import numpy as np
import DigitalMicrograph as DM

_directory = os.environ["DM_NATIVE_EVIDENCE_DIR"]
_truth_path = os.path.join(_directory, "fixture.json")
if os.path.exists(_truth_path):
    raise RuntimeError("Fixture truth already exists; use a fresh test directory")
_token = os.environ["DM_NATIVE_SESSION"][:8]
_yy, _xx = np.indices((7, 11), dtype=np.float32)
_values = -30.125 + _xx * 0.25 + _yy * 1.5
_native_fixture_images, _native_fixture_documents = [], []
_truth = {"session": os.environ["DM_NATIVE_SESSION"], "images": [],
          "kind": "synthetic-only", "python_is_listener": False}
for _label, _array in (("SIGNED", _values),
                       ("DISTRACTOR", np.full((5, 9), 93.375, dtype=np.float32))):
    _array = np.array(_array, dtype=np.float32, order="C", copy=True)
    _image = DM.CreateImage(_array)
    if _image is None or not _image.IsValid():
        raise RuntimeError("CreateImage failed")
    # Keep fixture naming independent of GMS Python's legacy ANSI/UTF-8 binding.
    # Native Unicode-name compatibility needs a separate qualified oracle.
    _image.SetName("NATIVE_MVP_" + _label + "_" + _token)
    _image.SetDimensionCalibration(0, 1.25, -0.25, "nm", 0)
    _image.SetDimensionCalibration(1, -2.5, 0.5, "nm", 0)
    _document = _image.GetOrCreateImageDocument()
    _document.Show()
    _native_fixture_images.append(_image)
    _native_fixture_documents.append(_document)
    _actual = np.array(_image.GetNumArray(), copy=True)
    if not np.array_equal(_actual, _array):
        raise RuntimeError("Fixture pixels did not round-trip through DM")
    _path = os.path.join(_directory, "source_" + _label.lower() + ".npy")
    with open(_path, "xb") as _file:
        np.save(_file, _actual, allow_pickle=False)
    _calibration = []
    for _axis in range(2):
        _origin, _scale, _unit = _image.GetDimensionCalibration(_axis, 0)
        _calibration.append({"dm_axis": _axis, "origin": float(_origin),
                             "scale": float(_scale), "unit": _unit})
    _truth["images"].append({"id": int(_image.GetID()), "name": _image.GetName(),
        "shape": list(_actual.shape), "dtype": str(_actual.dtype),
        "pixel_sha256": hashlib.sha256(_actual.tobytes(order="C")).hexdigest(),
        "mean": float(np.mean(_actual, dtype=np.float64)), "calibration": _calibration,
        "source_npy": _path})
with open(_truth_path, "x", encoding="utf-8") as _file:
    json.dump(_truth, _file, ensure_ascii=False, indent=2, allow_nan=False)
# Shown native documents now own the images. Do not let the test script itself
# keep a closed image alive and invalidate the stale-ID acceptance condition.
del _native_fixture_images[:]
del _native_fixture_documents[:]
del _image, _document
print("Native MVP synthetic fixture ready. One-shot Python script finished.")
