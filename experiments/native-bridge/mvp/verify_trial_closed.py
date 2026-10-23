# -*- coding: utf-8 -*-
"""One-shot oracle after STOP and normal closure of ONLY the delivered crop.

Run while DM still runs, after strict after_stop acceptance or a same-mode
legacy observation. An observation always remains UNVERIFIED.
Never closes an image/document, changes a source, or receives native requests.
"""
import hashlib
import json
import os
import re
import DigitalMicrograph as DM


def _protocol():
    mode = os.environ.get("DM_NATIVE_ORACLE_PROTOCOL", "NB2")
    if mode not in ("NB2", "NB1_LEGACY"):
        raise RuntimeError("Unsupported native oracle protocol mode")
    return "NB1" if mode == "NB1_LEGACY" else "NB2"


def _operation_identity(receipt, operation, args):
    if _protocol() == "NB1":
        return  # Explicit read-only historical validation; never a sender fallback.
    types = {"STATUS":"status", "DATASETS":"datasets", "INFO":"image_info", "MEAN":"native_mean",
             "SUMMARY":"native_summary", "CROP":"image_crop", "SHOW":"image_delivery", "STOP":"ipc_stop"}
    if (not isinstance(receipt, dict) or receipt.get("protocol") != "NB2" or receipt.get("original_operation") != operation
            or type(receipt.get("normalized_args")) is not list or receipt["normalized_args"] != args
            or any(type(value) is not int or not 0 <= value <= 0xffffffff for value in receipt["normalized_args"])
            or receipt.get("result_type") != types[operation]
            or type(receipt.get("result_version")) is not int or receipt["result_version"] != 1):
        raise RuntimeError("NB2 original operation/arguments/result schema mismatch")


def _load(_path, _strict_stop=False):
    def _unique(_pairs):
        _result = {}
        for _key, _value in _pairs:
            if _key in _result:
                raise RuntimeError("Ambiguous STOP JSON evidence: duplicate key")
            _result[_key] = _value
        return _result
    with open(_path, encoding="utf-8") as _file:
        return json.load(_file, object_pairs_hook=_unique) if _strict_stop else json.load(_file)


def _file_hash(_path):
    with open(_path, "rb") as _file:
        return hashlib.sha256(_file.read()).hexdigest()


def _verify_stop_request(_path, _stop, _host_pid, _observe):
    if not os.path.lexists(_path):
        if _observe:
            return False, None
        raise RuntimeError("UNVERIFIED: original pre-submission STOP request record is missing")
    if not os.path.isfile(_path):
        raise RuntimeError("Invalid original STOP request record")
    _request = _load(_path, True)
    if (not isinstance(_request, dict) or set(_request) != {
            "protocol", "session", "id", "op", "args", "host_pid", "wire"}
            or _request.get("protocol") != _protocol() or _request.get("op") != "STOP"
            or type(_request.get("args")) is not list or _request["args"] != []
            or not isinstance(_request.get("session"), str)
            or re.fullmatch(r"[0-9a-f]{32}", _request["session"]) is None
            or not isinstance(_request.get("id"), str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", _request["id"]) is None
            or type(_request.get("host_pid")) is not int or not 1 <= _request["host_pid"] <= 0xffffffff):
        raise RuntimeError("Invalid original STOP request record")
    if (_request["session"] != _stop["session"] or _request["id"] != _stop["id"]
            or _request["host_pid"] != _host_pid):
        raise RuntimeError("STOP request/receipt identity mismatch")
    if _request["wire"] != "%s %s %s STOP\n" % (_protocol(), _request["session"], _request["id"]):
        raise RuntimeError("STOP wire/request binding mismatch")
    return True, _file_hash(_path)


def verify():
    _mode = os.environ.get("DM_NATIVE_ORACLE_MODE", "strict")
    if _mode not in ("strict", "observe_legacy_stop"):
        raise RuntimeError("Unsupported native oracle mode")
    _observe = _mode == "observe_legacy_stop"
    _directory = os.environ["DM_NATIVE_EVIDENCE_DIR"]
    _truth_path = os.path.join(_directory, "trial-answers.json")
    _summary_path = os.path.join(_directory, "trial-acceptance", "summary.json")
    _truth = _load(_truth_path)
    _summary = _load(_summary_path)
    if (_truth["session"] != os.environ["DM_NATIVE_SESSION"] or _summary["status"] != "PASS"
            or _summary["session"] != _truth["session"]):
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
    if _host_pid != os.getpid():
        raise RuntimeError("Native host PID does not match this process")
    if _protocol() == "NB2":
        _ids = []
        for _output in (_status, _summary["crop"], _summary["delivery"], _summary["repeated_show"]):
            _receipt = _output.get("native_receipt", {})
            _id = _receipt.get("id")
            _timings = _receipt.get("timings_us")
            if (_output.get("backend") != "digitalmicrograph-native" or _receipt.get("protocol") != "NB2"
                    or _receipt.get("session") != _truth["session"] or _receipt.get("state") != "completed"
                    or not isinstance(_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", _id) is None
                    or _receipt.get("request_id") != _id
                    or any(type(_receipt.get(_key)) is not int for _key in ("host_pid", "worker_tid", "exec_tid"))
                    or (_receipt["host_pid"], _receipt["worker_tid"], _receipt["exec_tid"]) != (_host_pid, _worker_tid, _exec_tid)
                    or not isinstance(_timings, dict) or any(type(_timings.get(_key)) is not int
                        or not 0 <= _timings[_key] <= (1 << 53) - 1 for _key in ("queue", "execute"))
                    or any(_key in _receipt for _key in ("error", "code", "result"))):
                raise RuntimeError("NB2 closed native receipt correlation/state mismatch")
            _ids.append(_id)
        if len(set(_ids)) != len(_ids):
            raise RuntimeError("NB2 closed operation IDs must remain distinct")
    _source_for_identity = next(_item for _item in _truth["images"] if _item["label"] == "CAL")
    _operation_identity(_status["native_receipt"], "STATUS", [])
    _operation_identity(_summary["crop"]["native_receipt"], "CROP", [_source_for_identity["id"]] + _truth["crop_rect"])
    for _key in ("delivery", "repeated_show"):
        _operation_identity(_summary[_key]["native_receipt"], "SHOW", [_summary["crop"]["image_id"]])
    _stop_path = os.path.join(_directory, "stop-receipt.json")
    if not os.path.isfile(_stop_path):
        raise RuntimeError("Required STOP receipt is missing")
    _stop = _load(_stop_path, True)
    _stop_result = _stop.get("result")
    _timings = _stop.get("timings_us")
    if (_stop.get("protocol") != _protocol() or _stop.get("session") != _truth["session"]
            or not isinstance(_stop.get("id"), str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", _stop["id"]) is None
            or _stop.get("state") != "completed" or not isinstance(_stop_result, dict)
            or set(_stop_result) != {"ipc_stopped"} or _stop_result["ipc_stopped"] is not True
            or not isinstance(_timings, dict) or any(type(_timings.get(_field)) is not int
                or not 0 <= _timings[_field] <= (1 << 53) - 1 for _field in ("queue", "execute"))
            or "error" in _stop or "code" in _stop):
        raise RuntimeError("Invalid STOP receipt")
    if (any(type(_stop.get(_field)) is not int for _field in ("host_pid", "worker_tid", "exec_tid"))
            or (_stop["host_pid"], _stop["worker_tid"], _stop["exec_tid"]) != (_host_pid, _worker_tid, 0)):
        raise RuntimeError("STOP host/thread identity mismatch")
    _request_path = os.path.join(_directory, "stop-request.json")
    if not os.path.lexists(_request_path) and not _observe:
        raise RuntimeError("UNVERIFIED: original pre-submission STOP request record is missing")
    if os.path.lexists(_request_path) and not os.path.isfile(_request_path):
        raise RuntimeError("Invalid original STOP request record")
    _request_hash = _file_hash(_request_path) if os.path.isfile(_request_path) else None
    _post_path = os.path.join(_directory, ("trial-observation-" if _observe else "trial-independent-") + "after_stop.json")
    _post_error = ("Required same-session post-STOP observation is missing" if _observe
                   else "Required same-session post-STOP acceptance is missing")
    if not os.path.isfile(_post_path):
        raise RuntimeError(_post_error)
    _post = _load(_post_path)
    if (_post.get("status") != ("UNVERIFIED" if _observe else "PASS")
            or _post.get("oracle_mode") != _mode or _post.get("host_pid") != os.getpid()
            or _post.get("phase") != "after_stop" or _post.get("session") != _truth["session"]
            or _post.get("backend") != "digitalmicrograph-native"
            or any(_post.get(_field) is not True for _field in (
                "crop_all_pixels_equal", "crop_independent_memory", "ordinary_python_success"))
            or type(_post.get("matching_documents")) is not int or _post["matching_documents"] != 1
            or type(_post.get("total_documents")) is not int
            or _post["total_documents"] != _truth["initial_document_count"] + 1):
        raise RuntimeError(_post_error)
    if (_post.get("truth_sha256") != _file_hash(_truth_path)
            or _post.get("summary_sha256") != _file_hash(_summary_path)
            or _post.get("stop_receipt_sha256") != _file_hash(_stop_path)
            or _post.get("stop_request_sha256") != _request_hash):
        raise RuntimeError("Post-STOP evidence is not bound to the current trial records")
    _request_verified, _request_hash = _verify_stop_request(_request_path, _stop, _host_pid, _observe)
    if _post.get("stop_request_verified") is not _request_verified:
        raise RuntimeError("Post-STOP evidence is not bound to the current trial records")
    _operation_identity(_stop, "STOP", [])
    if _protocol() == "NB2" and (_post.get("protocol") != "NB2" or _post.get("protocol_mode") != "NB2"):
        raise RuntimeError("Post-STOP protocol mode mismatch")
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
    return {"status": "UNVERIFIED" if _observe else "PASS", "oracle_mode": _mode,
            "protocol": _protocol(), "protocol_mode": os.environ.get("DM_NATIVE_ORACLE_PROTOCOL", "NB2"),
            "host_pid": os.getpid(), "stop_request_verified": _request_verified,
            "stop_request_sha256": _request_hash, "truth_sha256": _file_hash(_truth_path),
            "summary_sha256": _file_hash(_summary_path), "stop_receipt_sha256": _file_hash(_stop_path),
            "phase": "after_close", "session": _truth["session"], "image_id": _output_id, "released_after_document_close": True,
            "other_synthetic_sources_unchanged": True, "ordinary_python_success": True}


_report = verify()
_prefix = "trial-observation-" if _report["oracle_mode"] == "observe_legacy_stop" else "trial-independent-"
with open(os.path.join(os.environ["DM_NATIVE_EVIDENCE_DIR"], _prefix + "after_close.json"),
          "x", encoding="utf-8") as _file:
    json.dump(_report, _file, indent=2, allow_nan=False)
if _report["status"] == "UNVERIFIED":
    print("UNVERIFIED: delivered-document closure observed; STOP qualification remains unavailable.")
else:
    print("PASS: only the normally closed delivered crop ID is released; other sources remain.")
