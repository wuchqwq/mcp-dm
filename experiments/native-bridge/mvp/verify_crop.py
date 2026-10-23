# -*- coding: utf-8 -*-
"""One-shot independent DM Python oracle after accept_crop_mcp.py finishes.

No requests are received here. Only this session's synthetic source/output IDs
are read, with all wrapper and shared-array references released on completion.
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
with open(os.path.join(_directory, "crop-acceptance", "summary.json"), encoding="utf-8") as _file:
    _summary = json.load(_file)
if _summary["status"] != "PASS":
    raise RuntimeError("MCP crop acceptance did not pass")
_result = _summary["crop"]
if _result["native_receipt"]["session"] != os.environ["DM_NATIVE_SESSION"] or _truth["session"] != os.environ["DM_NATIVE_SESSION"]:
    raise RuntimeError("Session mismatch")
_source_truth = next(item for item in _truth["images"] if item["id"] == _result["source_image_id"])
_source = DM.FindImageByID(_source_truth["id"])
_crop = DM.FindImageByID(_result["image_id"])
if (not _source.IsValid() or not _crop.IsValid() or _source.GetName() != _source_truth["name"]
        or int(_source.GetID()) != _source_truth["id"] or int(_crop.GetID()) != _result["image_id"]):
    raise RuntimeError("Source/output identity mismatch")
_source_view = _source.GetNumArray()
_crop_view = _crop.GetNumArray()
_original = np.load(_source_truth["source_npy"], allow_pickle=False)
if (list(_source_view.shape) != _source_truth["shape"] or str(_source_view.dtype) != _source_truth["dtype"]
        or list(_original.shape) != _source_truth["shape"] or str(_original.dtype) != _source_truth["dtype"]
        or hashlib.sha256(_original.tobytes(order="C")).hexdigest() != _source_truth["pixel_sha256"]):
    raise RuntimeError("Source or independent oracle shape/dtype/hash changed")
_x0, _y0, _x1, _y1 = _result["effective_rect"]
_expected = _original[_y0:_y1, _x0:_x1]
if _crop_view.dtype != np.float32 or not np.array_equal(_crop_view, _expected):
    raise RuntimeError("Native cropped values or dtype differ from independent oracle")
if np.shares_memory(_source_view, _crop_view):
    raise RuntimeError("Crop is a shared source view, not independent data")
if hashlib.sha256(_source_view.tobytes(order="C")).hexdigest() != _source_truth["pixel_sha256"]:
    raise RuntimeError("Original source pixels changed")
_calibration = []
for _axis, _offset in ((0, _x0), (1, _y0)):
    _zero, _scale, _unit = _crop.GetDimensionCalibration(_axis, 0)
    _expected_axis = _source_truth["calibration"][_axis]
    if (_zero != _expected_axis["origin"] + _offset * _expected_axis["scale"]
            or _scale != _expected_axis["scale"] or _unit != _expected_axis["unit"]):
        raise RuntimeError("Crop axis calibration mismatch")
    _source_zero, _source_scale, _source_unit = _source.GetDimensionCalibration(_axis, 0)
    if (_source_zero != _expected_axis["origin"] or _source_scale != _expected_axis["scale"]
            or _source_unit != _expected_axis["unit"]):
        raise RuntimeError("Original source calibration changed")
    _calibration.append({"dm_axis": _axis, "zero": float(_zero), "scale": float(_scale), "unit": _unit})
with open(os.path.join(_directory, "crop-pixels.npy"), "xb") as _file:
    np.save(_file, np.array(_crop_view, copy=True), allow_pickle=False)
with open(os.path.join(_directory, "crop-independent-review.json"), "x", encoding="utf-8") as _file:
    json.dump({"status": "PASS", "image_id": _result["image_id"],
        "fixture_truth": _fixture_file,
        "all_pixels_equal": True, "independent_memory": True, "source_unchanged": True,
        "shape": list(_crop_view.shape), "dtype": str(_crop_view.dtype),
        "calibration": _calibration, "ordinary_python_after_crop": True}, _file, indent=2, allow_nan=False)
del _source_view, _crop_view, _source, _crop
print("PASS: independent native crop pixels, calibration, memory and unchanged source.")
