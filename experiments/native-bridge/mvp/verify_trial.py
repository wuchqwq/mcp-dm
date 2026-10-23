# -*- coding: utf-8 -*-
"""One-shot independent synthetic oracle, run before and after native STOP.

Uses only the current session's private answers and accepted result IDs. It
does not create/show/close any document or receive native requests. All host
references are local to verify() and released before writing the result.
"""
import hashlib
import json
import os
import numpy as np
import DigitalMicrograph as DM


def _load(_path):
    with open(_path, encoding="utf-8") as _file:
        return json.load(_file)


def verify():
    _directory = os.environ["DM_NATIVE_EVIDENCE_DIR"]
    _truth = _load(os.path.join(_directory, "trial-answers.json"))
    _summary = _load(os.path.join(_directory, "trial-acceptance", "summary.json"))
    if (_truth["session"] != os.environ["DM_NATIVE_SESSION"]
            or _summary["session"] != _truth["session"] or _summary["status"] != "PASS"):
        raise RuntimeError("Session or actual-MCP acceptance mismatch")
    _after = os.path.exists(os.path.join(_directory, "stop-receipt.json"))
    if _after:
        _stop = _load(os.path.join(_directory, "stop-receipt.json"))
        if (_stop["session"] != _truth["session"] or _stop["state"] != "completed"
                or _stop["result"] != {"ipc_stopped": True}):
            raise RuntimeError("Invalid STOP receipt")
    _checks = []
    for _entry in _truth["images"]:
        _image = DM.FindImageByID(_entry["id"])
        if _image is None or not _image.IsValid() or int(_image.GetID()) != _entry["id"]:
            raise RuntimeError("Synthetic source identity lost")
        _actual = np.array(_image.GetNumArray(), copy=True)
        with open(_entry["source_npy"], "rb") as _file:
            if hashlib.sha256(_file.read()).hexdigest() != _entry["source_file_sha256"]:
                raise RuntimeError("Independent oracle file changed")
        _original = np.load(_entry["source_npy"], allow_pickle=False)
        if (_actual.shape != _original.shape or _actual.dtype != _original.dtype
                or list(_actual.shape) != _entry["shape"] or str(_actual.dtype) != _entry["dtype"]
                or hashlib.sha256(_actual.tobytes(order="C")).hexdigest() != _entry["pixel_sha256"]
                or hashlib.sha256(_original.tobytes(order="C")).hexdigest() != _entry["pixel_sha256"]):
            raise RuntimeError("Source pixel/shape/dtype changed")
        for _axis, _expected in enumerate(_entry["calibration"]):
            _zero, _scale, _unit = _image.GetDimensionCalibration(_axis, 0)
            if (_zero != _expected["origin"] or _scale != _expected["scale"]
                    or _unit != _expected["unit"]):
                raise RuntimeError("Source calibration changed")
        _checks.append({"image_id": _entry["id"], "pixels_calibration_and_file_unchanged": True})
    _result = _summary["crop"]
    _source_truth = next(_item for _item in _truth["images"] if _item["label"] == "CAL")
    _source = DM.FindImageByID(_source_truth["id"])
    _crop = DM.FindImageByID(_result["image_id"])
    if _crop is None or not _crop.IsValid() or int(_crop.GetID()) != _result["image_id"]:
        raise RuntimeError("Delivered crop no longer exists")
    _source_view = _source.GetNumArray()
    _crop_view = _crop.GetNumArray()
    _x0, _y0, _x1, _y1 = _truth["crop_rect"]
    _expected = np.load(_source_truth["source_npy"], allow_pickle=False)[_y0:_y1, _x0:_x1]
    if (_crop_view.dtype != _expected.dtype or _crop_view.shape != _expected.shape
            or not np.array_equal(_crop_view, _expected)
            or np.shares_memory(_source_view, _crop_view)):
        raise RuntimeError("Delivered crop pixels/dtype/shape/independent memory mismatch")
    _calibration = []
    for _axis, _offset in ((0, _x0), (1, _y0)):
        _zero, _scale, _unit = _crop.GetDimensionCalibration(_axis, 0)
        _expected_axis = _source_truth["calibration"][_axis]
        if (_zero != _expected_axis["origin"] + _offset * _expected_axis["scale"]
                or _scale != _expected_axis["scale"] or _unit != _expected_axis["unit"]):
            raise RuntimeError("Delivered crop physical calibration mismatch")
        _calibration.append({"axis": _axis, "zero": float(_zero), "scale": float(_scale), "unit": _unit})
    _documents = int(DM.CountImageDocumentsOfAllWorkspaces())
    _matching_documents = 0
    for _position in range(_documents):
        _doc = DM.GetImageDocumentOfAllWorkspaces(_position)
        _contains = False
        for _index in range(int(_doc.CountImages())):
            _candidate = _doc.GetImage(_index)
            if int(_candidate.GetID()) == _result["image_id"]:
                _contains = True
        if _contains:
            _matching_documents += 1
    if _matching_documents != 1 or _documents != _truth["initial_document_count"] + 1:
        raise RuntimeError("SHOW did not reuse exactly one document for the explicit crop ID")
    if not _after:
        with open(os.path.join(_directory, "trial-crop.npy"), "xb") as _file:
            np.save(_file, np.array(_crop_view, copy=True), allow_pickle=False)
    return {"status": "PASS", "session": _truth["session"], "phase": "after_stop" if _after else "before_stop",
            "image_id": _result["image_id"], "sources": _checks,
            "crop_all_pixels_equal": True, "crop_independent_memory": True,
            "crop_shape": list(_crop_view.shape), "crop_dtype": str(_crop_view.dtype),
            "crop_calibration": _calibration, "matching_documents": _matching_documents,
            "total_documents": _documents, "ordinary_python_success": True,
            "model_visual_acceptance": "NOT_TESTED", "file_persistence": "NOT_IMPLEMENTED"}


_report = verify()
with open(os.path.join(os.environ["DM_NATIVE_EVIDENCE_DIR"],
          "trial-independent-" + _report["phase"] + ".json"), "x", encoding="utf-8") as _file:
    json.dump(_report, _file, indent=2, allow_nan=False)
print("PASS: exact delivered crop document, pixels, dtype, calibration and source invariance (" +
      _report["phase"] + ").")
