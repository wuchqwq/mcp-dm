# -*- coding: utf-8 -*-
"""Explicit one-shot repair of this session's synthetic *names* only.

Use only after retaining a failed Unicode-name probe. No pixels or calibration
are written, and the original fixture truth is preserved rather than replaced.
"""
import json
import os
import DigitalMicrograph as DM

_directory = os.environ["DM_NATIVE_EVIDENCE_DIR"]
with open(os.path.join(_directory, "fixture.json"), encoding="utf-8") as _file:
    _truth = json.load(_file)
if _truth["session"] != os.environ["DM_NATIVE_SESSION"] or _truth["kind"] != "synthetic-only":
    raise RuntimeError("Not this session's synthetic fixture")
_out = os.path.join(_directory, "fixture-ascii.json")
if os.path.exists(_out):
    raise RuntimeError("Qualified fixture already exists")
_changes = []
for _index, _entry in enumerate(_truth["images"]):
    _image = DM.FindImageByID(_entry["id"])
    if not _image.IsValid() or _image.GetName() != _entry["name"]:
        raise RuntimeError("Synthetic fixture identity mismatch")
    _old_name = _entry["name"]
    _name = "NATIVE_MVP_ASCII_%d_%s" % (_index, _truth["session"][:8])
    _image.SetName(_name)
    if _image.GetName() != _name:
        raise RuntimeError("ASCII fixture naming failed")
    _entry["name"] = _name
    _changes.append({"id": _entry["id"], "old_python_name": _old_name, "ascii_name": _name})
_truth["name_qualification"] = {"scope": "ASCII synthetic names only",
    "unicode_name_probe": "FAIL; original fixture.json retained", "changes": _changes}
with open(_out, "x", encoding="utf-8") as _file:
    json.dump(_truth, _file, ensure_ascii=False, indent=2, allow_nan=False)
del _image
print("ASCII synthetic names qualified; original name-probe evidence retained.")
