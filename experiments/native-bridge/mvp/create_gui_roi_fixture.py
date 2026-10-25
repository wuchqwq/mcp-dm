# -*- coding: utf-8 -*-
"""One-shot NEW synthetic GUI ROI fixture; never a listener/runtime backend.

Run only inside a prepared idle test host. Required environment:
DM_NATIVE_EVIDENCE_DIR, DM_NATIVE_SESSION, DM_NATIVE_HOST_PID. Existing files,
images and documents are never modified or closed. The hidden source is held
by a uniquely named fixture-only module reference until the test host exits.
"""
import hashlib
import json
import os
import re

from create_summary_fixture import require, spatial, intensity


def fixed_arrays():
    import numpy as np
    y, x = np.indices((24, 32))
    a = (x * .125 - y * .5 + (x * y) % 7).astype(np.float32)
    a[0, 0] = np.float32(-0.)
    y, x = np.indices((20, 28), dtype=np.uint32)
    b = (np.uint32(2 ** 31) + x * 17 + y * 43 + (x * y) % 13).astype(np.uint32)
    hidden = np.arange(12 * 16, dtype=np.float32).reshape(12, 16) - np.float32(72.25)
    return {"float_primary": a, "uint32_empty": b, "hidden": hidden}


def new_roi(DM, display, label, coordinates, kind="rectangle", rotation=0.):
    roi = DM.NewROI()
    require(roi is not None, "New synthetic ROI failed")
    if kind == "line":
        roi.SetLine(*coordinates)
    else:
        roi.SetRectangle(*coordinates)
        roi.SetRotationAngle(rotation)
    roi.SetName(label)
    display.AddROI(roi)
    require(type(roi.GetID()) is int and roi.GetID() >= 0, "Synthetic ROI identity missing")
    return roi


def collect(report, directory):
    import numpy as np
    import DigitalMicrograph as DM
    from verify_gui_roi import all_documents, image_observation

    key = "_MCP_GUI_ROI_SYNTHETIC_" + report["session"]
    require(not hasattr(DM, key), "This session already has a fixture; do not recreate it")
    before = all_documents(DM)
    require(not before, "A fresh empty synthetic-only host is required")
    report["documents_before_fixture"] = before
    keep = {"images": [], "documents": [], "rois": [], "synthetic_only": True}
    # Deliberate fixture ownership, not a Python receiver or plugin lifetime test.
    setattr(DM, key, keep)
    report["fixture_keepalive_key"] = key
    for label, values in fixed_arrays().items():
        image = DM.CreateImage(np.array(values, order="C", copy=True))
        require(image is not None and image.IsValid(), "CreateImage failed")
        keep["images"].append(image)
        image.SetName("NATIVE_GUI_ROI_" + label + "_" + report["session"][:8])
        for axis, values_cal in enumerate(((1.25, -.25), (-2.5, .5))):
            image.SetDimensionCalibration(axis, values_cal[0], values_cal[1], "nm", 0)
        image.SetIntensityOrigin(7.5)
        image.SetIntensityScale(-2.)
        image.SetIntensityUnitString("arb")
        source_id = image.GetID()
        require(type(source_id) is int and source_id > 0, "Invalid fixture image ID")
        entry = {"id": source_id, "label": label}
        report["images"][label] = entry
        if label != "hidden":
            document = image.GetOrCreateImageDocument()
            require(document is not None, "Fixture document missing")
            keep["documents"].append(document)
            document.Show()
            display = image.GetImageDisplay(0)
            require(display is not None and display.IsValid() and display.GetImage().GetID() == source_id,
                    "Fixture display source mismatch")
            if label == "float_primary":
                for name, geometry, kind, rotation in (
                        ("integer", (3., 5., 13., 21.), "rectangle", 0.),
                        ("fractional", (2.5, 1.25, 17.75, 24.5), "rectangle", 0.),
                        ("line", (2., 4., 22., 18.), "line", 0.),
                        ("rotated", (5., 9., 15., 25.), "rectangle", 30.)):
                    keep["rois"].append(new_roi(DM, display, name, geometry, kind, rotation))
                second = DM.NewImageDocument("NATIVE_GUI_ROI_SECOND_" + report["session"][:8])
                require(second is not None, "Second fixture document missing")
                keep["documents"].append(second)
                second_display = second.AddImageDisplay(image, 1)
                require(second_display is not None and second_display.IsValid(), "Second exact-source display failed")
                keep["rois"].append(new_roi(DM, second_display, "second_document_rectangle", (1., 2., 8., 15.)))
                second.Show()
                # Only owned fixture windows are resized for later manual GUI drawing.
                for owned_doc in (document, second):
                    window = owned_doc.GetWindow()
                    require(window is not None and window.IsValid(), "Owned fixture window unavailable")
                    window.SetContentSize(640, 480)
                    window = None
        observed = image.GetNumArray()
        require(type(observed) is np.ndarray and observed.dtype == values.dtype and observed.shape == values.shape and
                observed.tobytes(order="C") == values.tobytes(order="C"), "Synthetic source bytes differ")
        name = label + ".npy"
        with open(os.path.join(directory, name), "xb") as output:
            np.save(output, np.array(observed, order="C", copy=True), allow_pickle=False)
            output.flush(); os.fsync(output.fileno())
        with open(os.path.join(directory, name), "rb") as source:
            file_sha = hashlib.sha256(source.read()).hexdigest()
        entry.update(image_observation(DM, image))
        entry.update(source_file=name, source_file_sha256=file_sha)
        require(entry["calibration"] == [spatial(image, axis) for axis in (0, 1)] and
                entry["intensity_calibration"] == intensity(image), "Fixture calibration changed")
        observed = image = document = display = None
    report["documents"] = all_documents(DM)
    require(len(report["documents"]) == len(before) + 3, "Fixture document count not exactly three new documents")
    primary = report["images"]["float_primary"]
    require(len(primary["displays"]) == 2 and sorted(len(item["rois"]) for item in primary["displays"]) == [1, 4],
            "Primary image must own exactly the prepared two display/ROI sets")
    require(len(report["images"]["uint32_empty"]["displays"]) == 1 and
            not report["images"]["uint32_empty"]["displays"][0]["rois"], "Zero-ROI control not empty")
    require(not report["images"]["hidden"]["displays"], "Hidden control unexpectedly has a display")
    # Capturing every source again checks document enumeration did not alter it.
    for label, image in zip(fixed_arrays(), keep["images"]):
        current = image_observation(DM, image)
        for field in ("id", "name", "dtype", "shape", "pixel_sha256", "calibration", "intensity_calibration", "displays"):
            require(current[field] == report["images"][label][field], "Fixture changed during preparation")


def main(expected_pid=None):
    directory = os.path.abspath(os.environ["DM_NATIVE_EVIDENCE_DIR"])
    target = os.path.join(directory, "gui-roi-fixture.json")
    require(os.path.isdir(directory), "An existing private evidence directory is required")
    with open(target, "x", encoding="utf-8") as output:
        report = {"schema": 1, "status": "FAIL", "kind": "new_synthetic_gui_roi_fixture_only",
                  "host_pid": os.getpid(), "session": os.environ.get("DM_NATIVE_SESSION"),
                  "python_is_listener": False, "native_qualification": "NOT_QUALIFIED", "images": {}}
        try:
            if expected_pid is None:
                if os.environ.get("DM_NATIVE_HOST_PID"):
                    expected_pid = int(os.environ["DM_NATIVE_HOST_PID"])
                else:
                    from verify_gui_roi import load
                    expected_pid = load(os.path.join(directory, "launch-event.json"))["pid"]
            require(type(expected_pid) is int and expected_pid == os.getpid(), "Fixture actual host PID differs from preparation")
            require(type(report["session"]) is str and re.fullmatch(r"[0-9a-f]{32}", report["session"]), "Explicit native session required")
            collect(report, directory)
            report["status"] = "RECORDED_SYNTHETIC_GUI_ROI_FIXTURE"
        except BaseException as error:
            report.update(error_type=type(error).__name__, error=str(error))
        json.dump(report, output, indent=2, ensure_ascii=True, allow_nan=False)
        output.write("\n"); output.flush(); os.fsync(output.fileno())
    print(report["status"] + ": one-shot fixture only; no native qualification")
    return 0 if report["status"].startswith("RECORDED_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
