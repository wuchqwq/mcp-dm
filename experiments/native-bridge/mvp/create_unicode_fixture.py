# -*- coding: utf-8 -*-
"""One-shot legacy Python observations on NEW synthetic images only.

Run explicitly in a prepared host after native work has finished. This records
Python values, not UI/native correctness or Unicode qualification. In particular,
bytes remain bytes: no encoding is inferred, even when they happen to be UTF-8.
"""
import json
import math
import os


def _type_name(value):
    cls = type(value)
    return cls.__module__ + "." + cls.__name__


def _safe_repr(value):
    try:
        return repr(value)
    except BaseException as error:
        return "<repr failed: " + _type_name(error) + ">"


def _exception(error):
    try:
        message = str(error)
    except BaseException as nested:
        message = "<str failed: " + _type_name(nested) + ">"
    observation = {"type": _type_name(error), "message": message,
                   "repr": _safe_repr(error)}
    if isinstance(error, (UnicodeEncodeError, UnicodeDecodeError, UnicodeTranslateError)):
        observation["unicode_error"] = {
            "object": _raw(error.object), "start": error.start, "end": error.end,
            "reason": error.reason}
        if hasattr(error, "encoding"):
            observation["unicode_error"]["encoding"] = error.encoding
    return observation


def _raw(value):
    """JSON-safe observation; text/bytes are lossless and never interconverted."""
    if type(value) is str:
        indices = [index for index, char in enumerate(value)
                   if 0xD800 <= ord(char) <= 0xDFFF]
        return {"type": "str", "value": value,
                "codepoints": ["U+%04X" % ord(char) for char in value],
                "contains_surrogates": bool(indices), "surrogate_indices": indices}
    if type(value) is bytes:
        return {"type": "bytes", "hex": value.hex(), "length": len(value),
                "decoding": "NOT_ATTEMPTED"}
    if type(value) in (tuple, list):
        return {"type": type(value).__name__, "items": [_raw(item) for item in value]}
    if value is None or type(value) in (bool, int):
        return {"type": type(value).__name__, "value": value}
    if type(value) is float:
        return {"type": "float", "value": value if math.isfinite(value) else repr(value)}
    return {"type": _type_name(value), "repr": _safe_repr(value)}


def _issue(report, entry, step, code, detail=None):
    issue = {"case": entry["case"], "step": step, "code": code}
    if detail is not None:
        issue["detail"] = detail
    entry["errors"].append(issue)
    report["errors"].append(issue)


def _call(report, entry, step, function):
    try:
        return True, function()
    except Exception as error:
        observation = {"type": "exception", "exception": _exception(error)}
        _issue(report, entry, step, "call_exception", observation["exception"])
        return False, observation


def _text(report, entry, step, value):
    observation = _raw(value)
    if type(value) not in (str, bytes):
        _issue(report, entry, step, "unexpected_text_type", observation)
    elif type(value) is str and observation["contains_surrogates"]:
        _issue(report, entry, step, "surrogate_codepoint", {
            "indices": observation["surrogate_indices"]})
    return observation


def _collect(report):
    # Evidence was exclusively created before importing the host or creating data.
    import numpy as np
    import DigitalMicrograph as DM

    requested_names = ("Short", "Long_ASCII_name_over_inline_storage", u"中文",
                       u"原生名称测试_较长名称_Ω_é_中", u"µm_Å_Ω_é_😀")
    requested_axes = ((1.25, -0.25, u"µm"), (-2.5, 0.5, u"Å"))
    for case, requested in enumerate(requested_names):
        entry = {"case": case, "python_requested": _raw(requested),
                 "python_units": [], "errors": []}
        report["images"].append(entry)
        image = document = None
        try:
            ok, image = _call(report, entry, "CreateImage", lambda: DM.CreateImage(
                np.array([[1.25, -2], [3, 4.5]], dtype=np.float32)))
            if not ok:
                entry["creation"] = image
                continue
            ok, value = _call(report, entry, "GetID", image.GetID)
            entry["id_observation"] = _raw(value) if ok else value
            if ok and type(value) is int and 0 < value <= 0xFFFFFFFF:
                entry["id"] = value
            elif ok:
                _issue(report, entry, "GetID", "unexpected_image_id", _raw(value))
            _call(report, entry, "SetName", lambda: image.SetName(requested))
            for axis, (zero, scale, unit) in enumerate(requested_axes):
                _call(report, entry, "SetDimensionCalibration[%d]" % axis,
                      lambda: image.SetDimensionCalibration(axis, zero, scale, unit, 0))
            ok, document = _call(report, entry, "GetOrCreateImageDocument",
                                 image.GetOrCreateImageDocument)
            if ok:
                _call(report, entry, "Show", document.Show)
            ok, value = _call(report, entry, "GetName", image.GetName)
            entry["python_readback"] = _text(report, entry, "GetName", value) if ok else value
            for axis, (zero, scale, unit) in enumerate(requested_axes):
                step = "GetDimensionCalibration[%d]" % axis
                axis_entry = {"axis": axis, "style": 0, "requested": {
                    "zero": zero, "scale": scale, "unit": _raw(unit)}}
                entry["python_units"].append(axis_entry)
                ok, value = _call(report, entry, step,
                                  lambda: image.GetDimensionCalibration(axis, 0))
                axis_entry["raw_return"] = _raw(value) if ok else value
                if not ok:
                    continue
                if type(value) not in (tuple, list) or len(value) != 3:
                    _issue(report, entry, step, "unexpected_calibration_return",
                           axis_entry["raw_return"])
                    continue
                got_zero, got_scale, got_unit = value
                axis_entry["unit"] = _text(report, entry, step + ".unit", got_unit)
                for label, number in (("zero", got_zero), ("scale", got_scale)):
                    if type(number) not in (int, float) or not math.isfinite(number):
                        _issue(report, entry, step + "." + label,
                               "invalid_calibration_number", _raw(number))
        except Exception as error:
            # Attribute/return-shape errors also retain every observation made so far.
            _issue(report, entry, "image_probe", "probe_exception", _exception(error))
        finally:
            # Do not close documents. Only references to newly created objects exist here.
            image = document = None


def main():
    out = os.path.join(os.environ["DM_NATIVE_EVIDENCE_DIR"], "unicode-python.json")
    # Exclusive creation comes before all host imports/calls and is never retried.
    with open(out, "x", encoding="utf-8") as evidence:
        report = {"schema": 1, "probe": "legacy_python_name_unit", "status": "FAIL",
                  "qualification": "NOT_QUALIFIED", "ui_observation": "NOT_TESTED",
                  "native_observation": "NOT_TESTED",
                  "scope": "new synthetic images; legacy Python setter/readback only",
                  "session": os.environ.get("DM_NATIVE_SESSION"), "images": [], "errors": []}
        try:
            if not report["session"]:
                raise ValueError("DM_NATIVE_SESSION must be set")
            _collect(report)
        except BaseException as error:
            report["errors"].append({"step": "probe", "code": "probe_exception",
                                     "detail": _exception(error)})
        report["status"] = "FAIL" if report["errors"] else "RECORDED"
        # ASCII escapes preserve lone surrogates without invoking an output codec.
        json.dump(report, evidence, ensure_ascii=True, allow_nan=False, indent=2)
        evidence.write("\n")
    print("Legacy Python diagnostic " + report["status"] + "; Unicode NOT_QUALIFIED.")
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
