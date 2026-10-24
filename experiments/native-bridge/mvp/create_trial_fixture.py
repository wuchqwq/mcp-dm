# -*- coding: utf-8 -*-
"""One-shot synthetic inputs for the native client trial, never a listener.

Operator: run once inside an empty prepared DM, before native image requests.
Use a NEW private DM_NATIVE_EVIDENCE_DIR and DM_NATIVE_SESSION. The generated
trial-answers.json stores independent pixel/calibration truth for verification.
No existing image or file is read, renamed or modified.
"""
import hashlib
import json
import os
import numpy as np
import DigitalMicrograph as DM

_directory = os.environ["DM_NATIVE_EVIDENCE_DIR"]
_answers_path = os.path.join(_directory, "trial-answers.json")
if os.path.exists(_answers_path):
    raise RuntimeError("Trial answers already exist; use a fresh session directory")
_session = os.environ["DM_NATIVE_SESSION"]
_y, _x = np.indices((7, 11), dtype=np.float32)
_ramp = np.asarray(-30.125 + _x * 0.25 + _y * 1.5, dtype=np.float32)
_inputs = [
    ("CAL", _ramp, "nm"),
    ("RAW", np.asarray(_ramp * -0.5 + 0.125, dtype=np.float32), ""),
    ("UINT16", np.arange(35, dtype=np.uint16).reshape(5, 7), "nm"),
    ("NONFINITE", np.array([[1, -2.5, 3], [4.5, np.nan, -6]], dtype=np.float32), "nm"),
]
_answers = {"session": _session, "kind": "synthetic-only",
            "python_is_listener": False, "images": [], "crop_rect": [2, 1, 8, 6]}
for _label, _values, _unit in _inputs:
    _image = DM.CreateImage(np.array(_values, order="C", copy=True))
    if _image is None or not _image.IsValid():
        raise RuntimeError("CreateImage failed")
    _image.SetName("NATIVE_TRIAL_" + _label + "_" + _session[:8])
    _image.SetDimensionCalibration(0, 1.25, -0.25, _unit, 0)
    _image.SetDimensionCalibration(1, -2.5, 0.5, _unit, 0)
    _document = _image.GetOrCreateImageDocument()
    _document.Show()
    _actual = np.array(_image.GetNumArray(), copy=True)
    if (_actual.dtype != _values.dtype or _actual.shape != _values.shape
            or not np.array_equal(np.isnan(_actual), np.isnan(_values))
            or not np.array_equal(np.isposinf(_actual), np.isposinf(_values))
            or not np.array_equal(np.isneginf(_actual), np.isneginf(_values))
            or not np.array_equal(_actual[np.isfinite(_values)], _values[np.isfinite(_values)])):
        raise RuntimeError("Synthetic input round-trip mismatch")
    _source_path = os.path.join(_directory, "trial_" + _label.lower() + ".npy")
    with open(_source_path, "xb") as _file:
        np.save(_file, _actual, allow_pickle=False)
    with open(_source_path, "rb") as _file:
        _source_file_hash = hashlib.sha256(_file.read()).hexdigest()
    _calibration = []
    for _axis in range(2):
        _zero, _scale, _read_unit = _image.GetDimensionCalibration(_axis, 0)
        _raw_origin, _raw_scale, _raw_unit = _image.GetDimensionCalibration(_axis, 1)
        _calibration.append({"dm_axis": _axis, "origin": float(_zero),
                             "raw_origin": float(_raw_origin),
                             "scale": float(_scale), "unit": _read_unit})
    _entry = {"label": _label, "id": int(_image.GetID()), "name": _image.GetName(),
              "shape": list(_actual.shape), "dtype": str(_actual.dtype),
              "source_npy": _source_path, "calibration": _calibration,
              "source_file_sha256": _source_file_hash,
              "pixel_sha256": hashlib.sha256(_actual.tobytes(order="C")).hexdigest(),
              "finite": bool(np.isfinite(_actual).all())}
    if _label == "NONFINITE" and _entry["finite"]:
        raise RuntimeError("Nonfinite synthetic input lost its nonfinite value")
    if _entry["finite"]:
        _entry["mean"] = float(np.mean(_actual, dtype=np.float64))
    if _label == "CAL":
        _roi = _actual[1:6, 2:8].copy()
        _entry["crop_mean"] = float(np.mean(_roi, dtype=np.float64))
        _entry["crop_pixel_sha256"] = hashlib.sha256(_roi.tobytes(order="C")).hexdigest()
    _answers["images"].append(_entry)
    del _actual, _image, _document
_answers["initial_document_count"] = int(DM.CountImageDocumentsOfAllWorkspaces())
with open(_answers_path, "x", encoding="utf-8") as _file:
    json.dump(_answers, _file, ensure_ascii=False, indent=2, allow_nan=False)
del _inputs[:]
print("Native trial synthetic inputs ready; private answers saved. No listener runs.")
