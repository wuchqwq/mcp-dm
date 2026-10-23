# -*- coding: utf-8 -*-
"""One-shot synthetic-output ownership check after explicit native STOP."""
import json
import os
import DigitalMicrograph as DM

_directory = os.environ["DM_NATIVE_EVIDENCE_DIR"]
with open(os.path.join(_directory, "crop-acceptance", "summary.json"), encoding="utf-8") as _file:
    _summary = json.load(_file)
if _summary["crop"]["native_receipt"]["session"] != os.environ["DM_NATIVE_SESSION"]:
    raise RuntimeError("Session mismatch")
_id = _summary["crop"]["image_id"]
_image = DM.FindImageByID(_id)
if _image is not None and _image.IsValid():
    raise RuntimeError("Stopped plugin still retains the hidden cropped image")
with open(os.path.join(_directory, "stopped-output-ownership.json"), "x", encoding="utf-8") as _file:
    json.dump({"status": "PASS", "image_id": _id, "output_released": True,
               "ordinary_python_after_stop": True}, _file, indent=2)
del _image
print("PASS: STOP released the plugin-owned crop; ordinary Python still runs.")
