# -*- coding: utf-8 -*-
"""Explicit one-shot NEW synthetic line inputs, never a bridge or listener.

Run inside a fresh idle test host with DM_NATIVE_EVIDENCE_DIR and
DM_NATIVE_SESSION. The launch-event.json PID must be this process. All output
files are exclusive. No existing image/document is edited or closed.
"""
import hashlib
import json
import os
import re

from create_summary_fixture import require


def fixed_arrays():
    import numpy as np
    y, x = np.indices((18, 24))
    return {
        "float_plane": (x * .25 - y * 2. + .125).astype(np.float32),
        "float_nonlinear": (x * x * .125 - y * y * .5 + (x * y) % 7).astype(np.float32),
        "uint32_high": (2 ** 31 + x * 31 + y * y * 17 + (x * y) % 11).astype(np.uint32),
        "float_negative_scale": (x * .5 - y * 3. + .375).astype(np.float32),
        "float_anisotropic": (x - y * 2.).astype(np.float32),
    }


def geometries():
    # Ordered XY pixel centres: both endpoint samples are expected. Interior
    # and exact border controls independently check the admitted pixel bounds.
    return {
        "horizontal": (2., 4., 17., 4.),
        "vertical": (8., 2., 8., 13.),
        "reversed": (19., 9., 3., 9.),
        "edge_horizontal": (0., 0., 23., 0.),
        "edge_vertical": (23., 0., 23., 17.),
        "edge_reversed": (23., 17., 0., 17.),
        "diagonal_rejected": (2., 2., 12., 10.),
        "point_rejected": (6., 6., 6., 6.),
    }


def main():
    import numpy as np
    import DigitalMicrograph as DM
    from verify_gui_roi import all_documents, image_observation, load
    from create_gui_roi_fixture import new_roi
    directory = os.path.abspath(os.environ["DM_NATIVE_EVIDENCE_DIR"])
    session = os.environ["DM_NATIVE_SESSION"]
    require(re.fullmatch(r"[0-9a-f]{32}", session) is not None, "Explicit session required")
    require(load(os.path.join(directory, "launch-event.json"))["pid"] == os.getpid(),
            "Fixture must run in the originally launched host")
    target = os.path.join(directory, "line-profile-fixture.json")
    report = {"schema": 1, "status": "FAIL", "host_pid": os.getpid(), "session": session,
              "kind": "new_synthetic_line_profile_fixture_only", "python_is_listener": False,
              "images": {}}
    with open(target, "x", encoding="utf-8") as output:
        try:
            before = all_documents(DM)
            require(not before, "A fresh empty synthetic-only host is required")
            report["documents_before_fixture"] = before
            key = "_MCP_LINE_PROFILE_SYNTHETIC_" + session
            require(not hasattr(DM, key), "Do not recreate the fixture in this session")
            keep = {"images": [], "documents": [], "rois": [], "synthetic_only": True}
            setattr(DM, key, keep)
            report["fixture_keepalive_key"] = key
            for label, values in fixed_arrays().items():
                image = DM.CreateImage(np.array(values, order="C", copy=True))
                require(image is not None and image.IsValid(), "New fixture image invalid")
                keep["images"].append(image)
                image.SetName("NATIVE_LINE_" + label + "_" + session[:8])
                sx = -.25 if label == "float_negative_scale" else .25
                sy = .5 if label == "float_anisotropic" else sx
                for axis, cal in enumerate(((1.25, sx), (-2.5, sy))):
                    image.SetDimensionCalibration(axis, cal[0], cal[1], "nm", 0)
                # A native result must remain raw even with nontrivial source
                # intensity calibration. This is a scientific acceptance control.
                image.SetIntensityOrigin(7.5)
                image.SetIntensityScale(-2.)
                image.SetIntensityUnitString("arb")
                document = image.GetOrCreateImageDocument()
                keep["documents"].append(document)
                document.Show()
                display = image.GetImageDisplay(0)
                require(display.GetImage().GetID() == image.GetID(), "Wrong fixture display")
                for roi_label, coordinates in geometries().items():
                    keep["rois"].append(new_roi(DM, display, roi_label, coordinates, "line"))
                # Preserve a rectangle to prove ROIS v2 did not lose v1 semantics.
                keep["rois"].append(new_roi(DM, display, "rectangle_control", (3., 4., 12., 18.)))
                with open(os.path.join(directory, label + ".npy"), "xb") as saved:
                    np.save(saved, values, allow_pickle=False); saved.flush(); os.fsync(saved.fileno())
                with open(os.path.join(directory, label + ".npy"), "rb") as saved:
                    file_sha = hashlib.sha256(saved.read()).hexdigest()
                observed = image_observation(DM, image)
                require(observed["pixel_sha256"] == hashlib.sha256(values.tobytes(order="C")).hexdigest(),
                        "Source pixels differ from independently specified array")
                observed.update(label=label, source_file=label + ".npy", source_file_sha256=file_sha,
                                expected_lines={name: list(coords) for name, coords in geometries().items()})
                report["images"][label] = observed
                image = document = display = None
            report["documents"] = all_documents(DM)
            require(len(report["documents"]) == len(fixed_arrays()), "Unexpected document count")
            report["status"] = "RECORDED_SYNTHETIC_LINE_PROFILE_FIXTURE"
        except BaseException as error:
            report.update(error_type=type(error).__name__, error=str(error))
        json.dump(report, output, indent=2, ensure_ascii=True, allow_nan=False)
        output.write("\n"); output.flush(); os.fsync(output.fileno())
    print(report["status"] + ": fixture only; not native qualification")
    return 0 if report["status"].startswith("RECORDED_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
