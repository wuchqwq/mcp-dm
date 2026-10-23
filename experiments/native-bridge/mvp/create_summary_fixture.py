# -*- coding: utf-8 -*-
"""Explicit one-shot SUMMARY inputs: NEW synthetic images, never a listener.

Run manually inside a prepared idle host. Reserve a fresh private truth file
before importing DM. This records fixture creation only, not native/UI acceptance.
No existing image, document or evidence file is changed or closed.
"""
import hashlib
import json
import math
import os
import re


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def spatial(image, axis):
    zero, scale, unit = image.GetDimensionCalibration(axis, 0)
    raw_origin, raw_scale, raw_unit = image.GetDimensionCalibration(axis, 1)
    require(all(number(value) for value in (zero, scale, raw_origin, raw_scale))
            and scale != 0 and raw_scale == scale and type(unit) is str
            and unit == raw_unit, "Invalid spatial calibration readback")
    return {"dm_axis": axis, "origin": float(zero), "raw_origin": float(raw_origin),
            "scale": float(scale), "unit": unit}


def intensity(image):
    origin, scale, unit = (image.GetIntensityOrigin(), image.GetIntensityScale(),
                           image.GetIntensityUnitString())
    require(number(origin) and number(scale) and scale != 0 and type(unit) is str,
            "Invalid intensity calibration readback")
    return {"origin": float(origin), "scale": float(scale), "unit": unit}


def collect(report, directory):
    import numpy as np
    import DigitalMicrograph as DM

    before = DM.CountImageDocumentsOfAllWorkspaces()
    require(type(before) is int and before >= 0, "Invalid document count")
    report["document_count_before_fixture"] = before
    base = np.array([[1.25, -2.5, 3.75], [8, -9.5, .125]], dtype=np.float32)
    nonfinite = base.copy()
    nonfinite[1, 1] = np.nan
    inputs = [(label, base.copy()) for label in
              ("DEFAULT", "CALIBRATED_INTENSITY", "RAW_UNITS")]
    inputs += [("UINT16", np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint16)),
               ("NONFINITE", nonfinite)]
    ids = set()
    for label, values in inputs:
        entry = {"label": label}
        report["images"].append(entry)
        image = document = None
        try:
            image = DM.CreateImage(np.array(values, order="C", copy=True))
            require(image is not None and image.IsValid(), "CreateImage failed")
            image_id = image.GetID()
            require(type(image_id) is int and 0 <= image_id < 0xffffffff
                    and image_id not in ids, "Invalid/duplicate new image ID")
            ids.add(image_id)
            name = "NATIVE_SUMMARY_" + label + "_" + report["session"][:8]
            entry.update(id=image_id, name=name)
            image.SetName(name)
            require(type(image.GetName()) is str and image.GetName() == name,
                    "ASCII name round-trip mismatch")
            unit = "" if label == "RAW_UNITS" else "nm"
            requested = [(1.25, -.25, unit), (-2.5, .5, unit)]
            for axis, (zero, scale, axis_unit) in enumerate(requested):
                image.SetDimensionCalibration(axis, zero, scale, axis_unit, 0)
            if label == "CALIBRATED_INTENSITY":
                image.SetIntensityOrigin(7.5)
                image.SetIntensityScale(-2.0)
                image.SetIntensityUnitString("arb")
            entry["calibration"] = [spatial(image, axis) for axis in (0, 1)]
            for actual, expected in zip(entry["calibration"], requested):
                require((actual["origin"], actual["scale"], actual["unit"]) == expected,
                        "Requested spatial calibration did not round-trip")
            entry["intensity_calibration"] = intensity(image)
            if label == "CALIBRATED_INTENSITY":
                require(entry["intensity_calibration"] ==
                        {"origin": 7.5, "scale": -2.0, "unit": "arb"},
                        "Requested intensity calibration did not round-trip")
            document = image.GetOrCreateImageDocument()
            require(document is not None, "New fixture document missing")
            document.Show()
            actual = np.array(image.GetNumArray(), order="C", copy=True)
            require(actual.dtype == values.dtype and actual.shape == values.shape
                    and np.array_equal(np.isnan(actual), np.isnan(values))
                    and np.array_equal(actual[np.isfinite(values)], values[np.isfinite(values)]),
                    "Synthetic pixel/dtype/shape round-trip mismatch")
            path = os.path.abspath(os.path.join(directory, "summary_" + label.lower() + ".npy"))
            with open(path, "xb") as output:
                np.save(output, actual, allow_pickle=False)
            with open(path, "rb") as source:
                source_hash = hashlib.sha256(source.read()).hexdigest()
            entry.update(dtype=str(actual.dtype), shape=list(actual.shape),
                         finite=bool(np.isfinite(actual).all()), source_npy=path,
                         source_file_sha256=source_hash,
                         pixel_sha256=hashlib.sha256(actual.tobytes(order="C")).hexdigest())
            if label in ("DEFAULT", "CALIBRATED_INTENSITY", "RAW_UNITS"):
                # Independently hand-enumerated binary-exact values; not a runtime algorithm.
                entry["expected_summary"] = {"minimum": -9.5, "maximum": 8.0,
                                             "sum": 1.125, "mean": .1875}
                entry["expected_summary_basis"] = "hand-enumerated six raw pixel values"
        finally:
            # Documents own these new inputs. Leave no Python reference retaining them.
            image = document = None
    count = DM.CountImageDocumentsOfAllWorkspaces()
    require(type(count) is int and count == before + len(inputs),
            "Fixture must create exactly one document per new input")
    report["initial_document_count"] = count


def main():
    directory = os.environ["DM_NATIVE_EVIDENCE_DIR"]
    path = os.environ.get("DM_NATIVE_SUMMARY_TRUTH", os.path.join(directory, "summary-truth.json"))
    with open(path, "x", encoding="utf-8") as output:
        report = {"schema": 1, "status": "FAIL", "kind": "synthetic-only",
                  "python_is_listener": False, "host_pid": os.getpid(),
                  "session": os.environ.get("DM_NATIVE_SESSION"), "images": [],
                  "scope": "new synthetic inputs and legacy Python readback only",
                  "native_observation": "NOT_TESTED", "ui_observation": "NOT_TESTED"}
        try:
            require(type(report["session"]) is str and
                    re.fullmatch(r"[a-f0-9]{32}", report["session"]) is not None,
                    "DM_NATIVE_SESSION must be 32 lowercase hexadecimal characters")
            collect(report, directory)
            report["status"] = "RECORDED"
        except BaseException as error:
            report.update(error_type=type(error).__name__, error=str(error))
        json.dump(report, output, indent=2, ensure_ascii=True, allow_nan=False)
        output.write("\n")
    print("SUMMARY synthetic fixture " + report["status"] + "; native/UI NOT_TESTED.")
    return 0 if report["status"] == "RECORDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
