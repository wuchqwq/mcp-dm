# -*- coding: utf-8 -*-
"""One-shot oracle after STOP and normal closure of ONLY the delivered crop.

Run while the prepared DM still runs, after verify_trial.py after_stop passed.
Never closes an image/document, changes a source, or receives native requests.
"""
import hashlib
import json
import os
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
    _post = _load(os.path.join(_directory, "trial-independent-after_stop.json"))
    if (_truth["session"] != os.environ["DM_NATIVE_SESSION"] or _summary["status"] != "PASS"
            or _summary["session"] != _truth["session"] or _post["status"] != "PASS"
            or _post["phase"] != "after_stop" or _post["session"] != _truth["session"]
            or _post.get("backend") != "digitalmicrograph-native"
            or any(_post.get(_field) is not True for _field in (
                "crop_all_pixels_equal", "crop_independent_memory", "ordinary_python_success"))
            or type(_post.get("matching_documents")) is not int or _post["matching_documents"] != 1
            or type(_post.get("total_documents")) is not int
            or _post["total_documents"] != _truth["initial_document_count"] + 1):
        raise RuntimeError("Required same-session post-STOP acceptance is missing")
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
    _stop_path = os.path.join(_directory, "stop-receipt.json")
    if not os.path.isfile(_stop_path):
        raise RuntimeError("Required STOP receipt is missing")
    _stop = _load(_stop_path)
    _stop_result = _stop.get("result")
    if (_stop.get("protocol") != "NB1" or _stop.get("session") != _truth["session"]
            or _stop.get("state") != "completed" or not isinstance(_stop_result, dict)
            or set(_stop_result) != {"ipc_stopped"} or _stop_result["ipc_stopped"] is not True):
        raise RuntimeError("Invalid STOP receipt")
    if (any(type(_stop.get(_field)) is not int for _field in ("host_pid", "worker_tid", "exec_tid"))
            or (_stop["host_pid"], _stop["worker_tid"], _stop["exec_tid"]) != (_host_pid, _worker_tid, 0)):
        raise RuntimeError("STOP host/thread identity mismatch")
    if (_post.get("truth_sha256") != _file_hash(_truth_path)
            or _post.get("summary_sha256") != _file_hash(_summary_path)
            or _post.get("stop_receipt_sha256") != _file_hash(_stop_path)):
        raise RuntimeError("Post-STOP evidence is not bound to the current trial records")
    _output_id = _summary["crop"]["image_id"]
    if _post["image_id"] != _output_id:
        raise RuntimeError("Wrong post-STOP output identity")
    _image = DM.FindImageByID(_output_id)
    if _image is not None and _image.IsValid():
        raise RuntimeError("Closed crop still has a live owner; do not claim final release")
    if int(DM.CountImageDocumentsOfAllWorkspaces()) != _truth["initial_document_count"]:
        raise RuntimeError("Unrelated documents changed or delivered document still exists")
    for _entry in _truth["images"]:
        _source = DM.FindImageByID(_entry["id"])
        if _source is None or not _source.IsValid() or int(_source.GetID()) != _entry["id"]:
            raise RuntimeError("Unrelated synthetic source was closed")
        _view = _source.GetNumArray()
        if (list(_view.shape) != _entry["shape"] or str(_view.dtype) != _entry["dtype"]
                or hashlib.sha256(_view.tobytes(order="C")).hexdigest() != _entry["pixel_sha256"]):
            raise RuntimeError("Synthetic source changed")
        for _axis, _expected in enumerate(_entry["calibration"]):
            _zero, _scale, _unit = _source.GetDimensionCalibration(_axis, 0)
            if (_zero != _expected["origin"] or _scale != _expected["scale"] or _unit != _expected["unit"]):
                raise RuntimeError("Synthetic source calibration changed")
    return {"status": "PASS", "session": _truth["session"], "image_id": _output_id, "released_after_document_close": True,
            "other_synthetic_sources_unchanged": True, "ordinary_python_success": True}


_report = verify()
with open(os.path.join(os.environ["DM_NATIVE_EVIDENCE_DIR"], "trial-independent-after_close.json"),
          "x", encoding="utf-8") as _file:
    json.dump(_report, _file, indent=2, allow_nan=False)
print("PASS: only the normally closed delivered crop ID is released; other sources remain.")
