# -*- coding: utf-8 -*-
"""One-shot NEW bounded measurement sources; never a listener or native fallback.

Run in the explicitly launched idle synthetic-only host. Uses only fixture APIs,
records immutable independent arrays and source GUI/calibration observations,
and never edits or closes an existing image/document. Fixture ROIs are API-made;
they do not prove a human manually drew a selection.
"""
import json
import os
import re

from verify_line_profile import require, sha


def fixed_arrays():
    import numpy as np
    # Exactly representable endpoints, inner half-unit bin boundaries, repeated
    # edges, fractional values and both signs. Independent bins=8 and 64 cases
    # exercise bins greater than source pixels without changing input values.
    edges = np.array([[-2, -1.5, -1, -.5, 0, .5],
                      [1, 1.5, 2, -2, -.25, .25],
                      [-1.75, -1.25, -.75, .75, 1.25, 1.75],
                      [2, -1, 0, .5, 1, 2]], dtype=np.float32)
    y, x = np.indices((4, 6))
    high = (2 ** 31 + x * 31 + y * y * 17 + (x * y) % 11).astype(np.uint32)
    # Positive source values admit independently predeclared positive AND
    # negative lower-edge ranges; its intensity transform is identity so a
    # physical-unit axis never mislabels untransformed raw intensities.
    identity = (edges + np.float32(2.25)).astype(np.float32)
    return {"float_edges": edges, "uint32_high": high, "float_identity": identity}


def source_intensity(label):
    return {"origin": 0., "scale": 1., "unit": "arb"} if label == "float_identity" else {"origin": 7.5, "scale": -2., "unit": "arb"}


def geometries():
    return {"horizontal": (0., 1., 5., 1.), "vertical": (2., 0., 2., 3.),
            "reversed": (5., 2., 0., 2.)}


def create_fixture(directory=None):
    from verify_gui_roi import load
    directory = os.path.abspath(directory or os.environ["DM_NATIVE_EVIDENCE_DIR"])
    session = os.environ["DM_NATIVE_SESSION"]
    require(re.fullmatch(r"[0-9a-f]{32}", session) is not None, "Explicit session required")
    require(load(os.path.join(directory, "launch-event.json"))["pid"] == os.getpid(),
            "Fixture must run in the originally launched host PID")
    target = os.path.join(directory, "measurement-fixture.json")
    report = {"schema": 1, "status": "FAIL", "host_pid": os.getpid(), "session": session,
              "kind": "new_synthetic_native_measurement_fixture_only", "python_is_listener": False,
              "fixture_revision": 2, "roi_creation": "fixture_API_not_manual_GUI_drawing", "images": {}}
    with open(target, "x", encoding="utf-8") as output:
        try:
            import numpy as np
            import DigitalMicrograph as DM
            from create_gui_roi_fixture import new_roi
            from verify_gui_roi import all_documents, image_observation
            before = all_documents(DM)
            require(not before, "A fresh empty synthetic-only host is required")
            report["documents_before_fixture"] = before
            key = "_MCP_NATIVE_MEASUREMENT_SYNTHETIC_" + session
            require(not hasattr(DM, key), "Never recreate a fixture in the same session")
            keep = {"images": [], "documents": [], "rois": [], "synthetic_only": True}
            setattr(DM, key, keep)
            report["fixture_keepalive_key"] = key
            for label, values in fixed_arrays().items():
                image = DM.CreateImage(np.array(values, copy=True, order="C"))
                require(image is not None and image.IsValid(), "New measurement source invalid")
                keep["images"].append(image)
                image.SetName("NATIVE_MEASUREMENT_" + label + "_" + session[:8])
                scale = -.25 if label == "float_edges" else .25
                for dimension, zero in enumerate((1.25, -2.5)):
                    image.SetDimensionCalibration(dimension, zero, scale, "nm", 0)
                intensity = source_intensity(label)
                image.SetIntensityOrigin(intensity["origin"])
                image.SetIntensityScale(intensity["scale"])
                image.SetIntensityUnitString(intensity["unit"])
                document = image.GetOrCreateImageDocument()
                require(document is not None and document.IsValid(), "New source document invalid")
                keep["documents"].append(document)
                document.Show()
                window = document.GetWindow()
                require(window is not None and window.IsValid(), "New source document window missing")
                window.SetContentSize(640, 480)
                window = None
                display = image.GetImageDisplay(0)
                require(display.GetImage().GetID() == image.GetID(), "Wrong source display")
                for name, endpoints in geometries().items():
                    keep["rois"].append(new_roi(DM, display, name, endpoints, "line"))
                keep["rois"].append(new_roi(DM, display, "rectangle", (0., 1., 4., 5.)))
                name = label + ".npy"
                with open(os.path.join(directory, name), "xb") as saved:
                    np.save(saved, values, allow_pickle=False)
                    saved.flush(); os.fsync(saved.fileno())
                with open(os.path.join(directory, name), "rb") as saved:
                    file_hash = sha(saved.read())
                observed = image_observation(DM, image)
                require(observed["pixel_sha256"] == sha(values.tobytes(order="C")),
                        "Created source differs from independent fixed array")
                observed.update(label=label, source_file=name, source_file_sha256=file_hash,
                                expected_lines={name: list(coords) for name, coords in geometries().items()})
                report["images"][label] = observed
                image = document = display = None
            report["documents"] = all_documents(DM)
            require(len(report["documents"]) == len(fixed_arrays()), "Unexpected fixture documents")
            report["status"] = "RECORDED_SYNTHETIC_NATIVE_MEASUREMENT_FIXTURE"
        except BaseException as error:
            report.update(error_type=type(error).__name__, error=str(error))
        json.dump(report, output, ensure_ascii=True, indent=2, allow_nan=False)
        output.write("\n"); output.flush(); os.fsync(output.fileno())
    return report


if __name__ == "__main__":
    observed = create_fixture()
    print(observed["status"] + ": fixture API only, not qualification")
    raise SystemExit(0 if observed["status"].startswith("RECORDED_") else 1)
