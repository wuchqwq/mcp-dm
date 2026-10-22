# -*- coding: utf-8 -*-
"""Run manually inside DM Python. Creates two small synthetic images only.

No file access, existing-image edits, bridge injection or instrument commands.
Names include a run token. Copy the printed IDs/names into the local test sheet.
Keep this workspace open while testing; do not upload private session logs.
"""
import uuid
import numpy as np
import DigitalMicrograph as DM

_token = uuid.uuid4().hex[:8]
_y, _x = np.indices((48, 64), dtype=np.float32)
_other = np.full((48, 64), 777, dtype=np.float32)
_other[8:18, 40:54] = 2000
_other[28:40, 8:22] = 0
_d0_images, _d0_documents = [], []
for _label, _array in (("MCP_D0_RAMP", 100 * _y + _x),
                       ("MCP_D0_OTHER", _other)):
    _image = DM.CreateImage(np.array(_array, dtype=np.float32, copy=True, order="C"))
    if _image is None or not _image.IsValid():
        raise RuntimeError("Synthetic CreateImage failed; no real data were opened")
    _image.SetName(_label + "_" + _token)
    _image.SetDimensionCalibration(0, 1.25, -0.25, "nm", 0)
    _image.SetDimensionCalibration(1, -2.5, 0.5, "nm", 0)
    _document = _image.GetOrCreateImageDocument()
    _d0_images.append(_image)
    _d0_documents.append(_document)
    _document.Show()
    print("Synthetic only: name=%s id=%s" % (_image.GetName(), _image.GetID()))
print("Keep these two images open. DM dimension order is X,Y; NumPy shape is [48,64].")
