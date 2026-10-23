# -*- coding: utf-8 -*-
"""Separate one-shot legacy Python name/unit probe on NEW synthetic images.

Requested names are not a Unicode truth oracle. Keep Python read-back, native
GetUnicodeName and actual UI observations separate; never guess a conversion.
Run after all native operations have finished in a prepared test session.
"""
import json
import os
import numpy as np
import DigitalMicrograph as DM

def _points(_text):
    return ["U+%04X" % ord(_char) for _char in _text]

_out = os.path.join(os.environ["DM_NATIVE_EVIDENCE_DIR"], "unicode-python.json")
if os.path.exists(_out):
    raise RuntimeError("Probe evidence already exists")
_observations = []
for _requested in ("Short", "Long_ASCII_name_over_inline_storage",
                   u"中文", u"原生名称测试_较长名称_Ω_é_中",
                   u"µm_Å_Ω_é_😀"):
    _image = DM.CreateImage(np.array([[1.25, -2], [3, 4.5]], dtype=np.float32))
    _image.SetName(_requested)
    _image.SetDimensionCalibration(0, 1.25, -0.25, u"µm", 0)
    _image.SetDimensionCalibration(1, -2.5, 0.5, u"Å", 0)
    _document = _image.GetOrCreateImageDocument()
    _document.Show()
    _readback = _image.GetName()
    _entry = {"id": int(_image.GetID()), "python_requested": _requested,
              "python_requested_codepoints": _points(_requested),
              "python_readback": _readback, "python_readback_codepoints": _points(_readback),
              "python_units": []}
    for _axis in range(2):
        _zero, _scale, _unit = _image.GetDimensionCalibration(_axis, 0)
        _entry["python_units"].append({"axis": _axis, "unit": _unit, "codepoints": _points(_unit)})
    _observations.append(_entry)
    del _image, _document
with open(_out, "x", encoding="utf-8") as _file:
    json.dump({"scope": "legacy Python setter/readback only; no UI or native truth claim",
               "session": os.environ["DM_NATIVE_SESSION"], "images": _observations},
              _file, ensure_ascii=True, indent=2)
print("Separate Unicode Python probe saved. UI and native observations remain independent.")
