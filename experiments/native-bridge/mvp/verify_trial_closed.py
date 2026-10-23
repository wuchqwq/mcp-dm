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


def verify():
    _directory = os.environ["DM_NATIVE_EVIDENCE_DIR"]
    _truth = _load(os.path.join(_directory, "trial-answers.json"))
    _summary = _load(os.path.join(_directory, "trial-acceptance", "summary.json"))
    _post = _load(os.path.join(_directory, "trial-independent-after_stop.json"))
    if (_truth["session"] != os.environ["DM_NATIVE_SESSION"] or _summary["status"] != "PASS"
            or _summary["session"] != _truth["session"] or _post["status"] != "PASS"
            or _post["phase"] != "after_stop" or _post["session"] != _truth["session"]):
        raise RuntimeError("Required same-session post-STOP acceptance is missing")
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
