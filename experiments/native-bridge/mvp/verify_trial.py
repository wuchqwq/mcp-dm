# -*- coding: utf-8 -*-
"""One-shot independent synthetic oracle, run before and after native STOP.

Uses only the current session's private answers and accepted result IDs. It
does not create/show/close any document or receive native requests. All host
references are local to verify() and released before writing the result.
"""
import hashlib
import json
import os
import re
import numpy as np
import DigitalMicrograph as DM


def _load(_path):
    with open(_path, encoding="utf-8") as _file:
        return json.load(_file)


def _file_hash(_path):
    with open(_path, "rb") as _file:
        return hashlib.sha256(_file.read()).hexdigest()


def verify():
    _directory = os.environ["DM_NATIVE_EVIDENCE_DIR"]
    _truth_path = os.path.join(_directory, "trial-answers.json")
    _summary_path = os.path.join(_directory, "trial-acceptance", "summary.json")
    _truth = _load(_truth_path)
    _summary = _load(_summary_path)
    if (_truth["session"] != os.environ["DM_NATIVE_SESSION"]
            or _summary["session"] != _truth["session"] or _summary["status"] != "PASS"):
        raise RuntimeError("Session or actual-MCP acceptance mismatch")
    _statuses = [_item["output"] for _item in _summary.get("checks", []) if _item.get("tool") == "dm_status"]
    if len(_statuses) != 1:
        raise RuntimeError("Invalid native host status anchor")
    _status = _statuses[0]
    _host_pid, _exec_tid = _status.get("host_pid"), _status.get("host_thread")
    _worker_tid = _status.get("native_receipt", {}).get("worker_tid")
    if (_status.get("backend") != "digitalmicrograph-native" or _status.get("ready") is not True
            or _status.get("binary_gate") is not True
            or any(type(_value) is not int or not 1 <= _value <= 0xffffffff
                   for _value in (_host_pid, _worker_tid, _exec_tid)) or _worker_tid == _exec_tid):
        raise RuntimeError("Invalid native host status anchor")
    _request_ids = []
    for _label, _output in (("status", _status), ("crop", _summary["crop"]),
                            ("delivery", _summary["delivery"]), ("repeated_show", _summary["repeated_show"])):
        if _output.get("backend") != "digitalmicrograph-native":
            raise RuntimeError("Native backend mismatch")
        _receipt = _output["native_receipt"]
        _request_id = _receipt.get("id")
        if (_receipt.get("protocol") != "NB1" or _receipt.get("session") != _truth["session"]
                or _receipt.get("state") != "completed" or not isinstance(_request_id, str)
                or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", _request_id) is None
                or _receipt.get("request_id") != _request_id):
            raise RuntimeError("Invalid " + _label + " native receipt")
        if (any(type(_receipt.get(_field)) is not int for _field in ("host_pid", "worker_tid", "exec_tid"))
                or (_receipt["host_pid"], _receipt["worker_tid"], _receipt["exec_tid"])
                != (_host_pid, _worker_tid, _exec_tid)):
            raise RuntimeError("Native receipt host/thread identity mismatch")
        _request_ids.append(_request_id)
    if len(set(_request_ids)) != len(_request_ids):
        raise RuntimeError("Crop and distinct Show requests reused an operation ID")
    _source_truth = next(_item for _item in _truth["images"] if _item["label"] == "CAL")
    _result = _summary["crop"]
    if (_result.get("source_image_id") != _source_truth["id"]
            or _result.get("effective_rect", _result.get("rect")) != _truth["crop_rect"]
            or any(_field in _result and _result[_field] != _truth["crop_rect"]
                   for _field in ("rect", "requested_rect"))
            or type(_result.get("image_id")) is not int or not 0 <= _result["image_id"] <= 0xffffffff
            or _result["image_id"] == _source_truth["id"]
            or _result["image"]["id"] != _result["image_id"]):
        raise RuntimeError("Crop source/rectangle binding mismatch")
    for _label in ("delivery", "repeated_show"):
        _show = _summary[_label]
        if (_show.get("image_id") != _result["image_id"]
                or _show.get("delivery") != "visible_dm_document"
                or _show.get("document_visible") is not True or _show.get("file_saved") is not False
                or _show.get("model_visual_verification") is not False):
            raise RuntimeError("Show delivery/image binding mismatch")
    _stop_path = os.path.join(_directory, "stop-receipt.json")
    _after = os.path.exists(_stop_path)
    if _after:
        _stop = _load(_stop_path)
        _stop_result = _stop.get("result")
        if (_stop.get("protocol") != "NB1" or _stop.get("session") != _truth["session"]
                or _stop.get("state") != "completed" or not isinstance(_stop_result, dict)
                or set(_stop_result) != {"ipc_stopped"} or _stop_result["ipc_stopped"] is not True):
            raise RuntimeError("Invalid STOP receipt")
        if (any(type(_stop.get(_field)) is not int for _field in ("host_pid", "worker_tid", "exec_tid"))
                or (_stop["host_pid"], _stop["worker_tid"], _stop["exec_tid"]) != (_host_pid, _worker_tid, 0)):
            raise RuntimeError("STOP host/thread identity mismatch")
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
            "backend": "digitalmicrograph-native",
            "truth_sha256": _file_hash(_truth_path), "summary_sha256": _file_hash(_summary_path),
            "stop_receipt_sha256": _file_hash(_stop_path) if _after else None,
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
