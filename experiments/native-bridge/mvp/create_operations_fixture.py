# -*- coding: utf-8 -*-
"""One-shot NEW synthetic operation inputs; only run in a prepared idle DM.

This is an independent qualification fixture, never the native runtime path.
Existing documents/images/files are neither edited nor closed. Exclusive truth
and pixel snapshots preserve every failed attempt instead of rewriting evidence.
"""
import hashlib
import json
import os
import re

from create_summary_fixture import require, spatial, intensity


def collect(report, directory):
    import numpy as np
    import DigitalMicrograph as DM

    report["document_count_before_fixture"] = DM.CountImageDocumentsOfAllWorkspaces()
    a = np.array([[1.25, -2.5, 3.75, 4], [-5, 6, 7, -8],
                  [9.25, 10, -11, 12], [13, 14.5, 15, -16]], dtype=np.float32)
    impulse = np.zeros((4, 8), dtype=np.float32)
    impulse[1, 2] = 1
    # Binary-exact single frequency at x=1 and y=1, with a phase-bearing sine.
    cosine = np.array([[1, 0, -1, 0], [2, 1, 0, 1],
                       [1, 0, -1, 0], [0, -1, -2, -1]], dtype=np.float32)
    nonfinite = a.copy(); nonfinite[1, 2] = np.nan
    filter_values = np.array([[(x*x + 3*x*y + 2*y*y) % 17 - 8 for x in range(8)]
                              for y in range(8)], dtype=np.float32)
    bits = a.copy()
    bits[0] = np.array([0x80000000, 0, 1, 0x80000001], dtype=np.uint32).view(np.float32)
    inputs = [("A", a), ("B", np.full((4, 4), 2, dtype=np.float32)),
              ("CONSTANT", np.full((4, 4), 3.25, dtype=np.float32)),
              ("IMPULSE", impulse), ("SINGLE_FREQUENCY", cosine), ("FILTER_A", filter_values),
              ("NONFINITE", nonfinite), ("UINT16", np.arange(16, dtype=np.uint16).reshape(4, 4))]
    # Preserve the original eight-image qualification fixture. The separate
    # bounded-handoff procedure explicitly opts into its additional bit oracle.
    if os.environ.get("DM_NATIVE_INCLUDE_READ_BITS") == "1":
        inputs.append(("READ_BITS", bits))
    ids = set()
    for label, values in inputs:
        entry = {"label": label}
        report["images"].append(entry)
        image = document = None
        try:
            image = DM.CreateImage(np.array(values, order="C", copy=True))
            require(image is not None and image.IsValid(), "Synthetic creation failed")
            image_id = image.GetID()
            require(type(image_id) is int and 0 <= image_id < 0xffffffff and image_id not in ids,
                    "Invalid/duplicate synthetic ID")
            ids.add(image_id)
            name = "NATIVE_OP_" + label + "_" + report["session"][:8]
            image.SetName(name)
            require(type(image.GetName()) is str and image.GetName() == name, "ASCII identity readback mismatch")
            for axis, (zero, scale) in enumerate(((1.25, -.25), (-2.5, .5))):
                image.SetDimensionCalibration(axis, zero, scale, "nm", 0)
            # Native operations must process raw pixels while preserving intensity
            # calibration as metadata. This makes accidental application detectable.
            image.SetIntensityOrigin(7.5)
            image.SetIntensityScale(-2.0)
            image.SetIntensityUnitString("arb")
            entry.update(id=image_id, name=name,
                         calibration=[spatial(image, axis) for axis in (0, 1)],
                         intensity_calibration=intensity(image))
            for axis, (zero, scale) in enumerate(((1.25, -.25), (-2.5, .5))):
                actual_axis = entry["calibration"][axis]
                require((actual_axis["origin"], actual_axis["scale"], actual_axis["unit"]) == (zero, scale, "nm"),
                        "Requested signed spatial calibration did not roundtrip")
            require(entry["intensity_calibration"] == {"origin": 7.5, "scale": -2.0, "unit": "arb"},
                    "Requested nontrivial intensity calibration did not roundtrip")
            document = image.GetOrCreateImageDocument()
            document.Show()
            actual = np.array(image.GetNumArray(), order="C", copy=True)
            require(actual.dtype == values.dtype and actual.shape == values.shape and
                    np.array_equal(np.isnan(actual), np.isnan(values)) and
                    np.array_equal(actual[np.isfinite(values)], values[np.isfinite(values)]),
                    "Synthetic roundtrip changed raw pixels")
            if label == "READ_BITS":
                require(actual.tobytes(order="C") == values.tobytes(order="C"),
                        "Synthetic bit-pattern roundtrip changed float32 values")
            filename = os.path.abspath(os.path.join(directory, "operations_" + label.lower() + ".npy"))
            with open(filename, "xb") as output: np.save(output, actual, allow_pickle=False)
            with open(filename, "rb") as source: file_hash = hashlib.sha256(source.read()).hexdigest()
            entry.update(dtype=str(actual.dtype), shape=list(actual.shape),
                         source_npy=filename, source_file_sha256=file_hash,
                         pixel_sha256=hashlib.sha256(actual.tobytes(order="C")).hexdigest(),
                         finite=bool(np.isfinite(actual).all()))
        finally:
            image = document = None
    report["initial_document_count"] = DM.CountImageDocumentsOfAllWorkspaces()
    require(report["initial_document_count"] == report["document_count_before_fixture"] + len(inputs),
            "Unexpected fixture document count")


def main():
    directory = os.environ["DM_NATIVE_EVIDENCE_DIR"]
    filename = os.environ.get("DM_NATIVE_OPERATIONS_TRUTH", os.path.join(directory, "operations-truth.json"))
    with open(filename, "x", encoding="utf-8") as output:
        report = {"schema": 1, "status": "FAIL", "kind": "synthetic-only",
                  "python_is_listener": False, "host_pid": os.getpid(),
                  "session": os.environ.get("DM_NATIVE_SESSION"), "images": [],
                  "native_observation": "NOT_TESTED"}
        try:
            require(type(report["session"]) is str and re.fullmatch(r"[a-f0-9]{32}", report["session"]),
                    "Explicit native session required")
            collect(report, directory)
            report["status"] = "RECORDED"
        except BaseException as error:
            report.update(error_type=type(error).__name__, error=str(error))
        json.dump(report, output, indent=2, ensure_ascii=True, allow_nan=False)
        output.write("\n")
    print("New synthetic operations fixture " + report["status"] + "; native results NOT_TESTED")
    return 0 if report["status"] == "RECORDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
