# -*- coding: utf-8 -*-
"""One-shot same-host synthetic direct-DM/native-MCP precision comparison.

Run create() in the explicitly prepared idle GMS host, then submit FFT, IFFT,
REAL and READ through the actual native MCP. Save each parsed result (including
native_receipt) to native-map.json keyed by the six fixture labels, with keys
fft/ifft/real/read. Run observe() once in that same host. This uses the fixed
DM-Script RealFFT -> IFFT path only as an independent operator control.
No listener, production fallback, guessed address or source-image write.
"""
import base64
import hashlib
import json
import os
import re

from create_summary_fixture import require, spatial, intensity
from fft_precision_fixture import arrays, POLICY


def validate_host_identity(session, expected_pid):
    require(type(expected_pid) is int and expected_pid > 0 and os.getpid() == expected_pid and
            type(session) is str and re.fullmatch(r"[a-f0-9]{32}", session) and os.environ.get("DM_NATIVE_SESSION") == session,
            "Actual host PID and prepared environment session must match")


def write_json(path, value):
    with open(path, "x", encoding="utf-8") as output:
        json.dump(value, output, indent=2, allow_nan=False)
        output.write("\n"); output.flush(); os.fsync(output.fileno())


def save_array(directory, label, values):
    import numpy as np
    filename = label + ".npy"
    path = os.path.join(directory, filename)
    with open(path, "xb") as output:
        np.save(output, values, allow_pickle=False)
        output.flush(); os.fsync(output.fileno())
    with open(path, "rb") as source:
        digest = hashlib.sha256(source.read()).hexdigest()
    return {"file": filename, "sha256": digest, "shape": list(values.shape), "dtype": str(values.dtype)}


def snapshot(DM, image_id, dtype, shape):
    import numpy as np
    image = view = None
    try:
        require(type(image_id) is int and 0 < image_id < 0xffffffff, "Exact image ID required")
        require(shape in ([8, 8], [128, 128]), "Snapshot budget/shape invalid")
        image = DM.FindImageByID(image_id)
        require(image is not None and image.IsValid() and image.GetID() == image_id, "Image ID invalid")
        require(image.GetDataType() == {"uint32": 11, "float32": 2, "complex64": 3}[dtype], "Native type differs; packed complex is not full complex")
        view = image.GetNumArray()
        require(type(view) is np.ndarray and str(view.dtype) == dtype and list(view.shape) == shape and np.isfinite(view).all(), "Raw view dtype/shape/finiteness mismatch")
        return np.array(view, copy=True, order="C")
    finally:
        image = view = None


def create(directory, session, expected_pid):
    validate_host_identity(session, expected_pid)
    import numpy as np
    import DigitalMicrograph as DM
    report = {"schema": 1, "status": "FAIL", "kind": "synthetic-only", "host_pid": os.getpid(), "session": session,
              "python_is_listener": False, "policy": POLICY, "images": {}, "document_count_before": DM.CountImageDocumentsOfAllWorkspaces()}
    report_path = os.path.join(directory, "fixture.json")
    require(not os.path.exists(report_path), "Fixture evidence already exists")
    try:
        for label, values in arrays().items():
            image = DM.CreateImage(values.copy(order="C"))
            image.SetName("PRECISION_" + label + "_" + session[:8])
            for dim, (zero, scale) in enumerate(((1.25, -.25), (-2.5, .5))):
                image.SetDimensionCalibration(dim, zero, scale, "nm", 0)
            image.SetIntensityOrigin(7.5); image.SetIntensityScale(-2.); image.SetIntensityUnitString("arb")
            image_id = image.GetID()
            actual = snapshot(DM, image_id, str(values.dtype), list(values.shape))
            require(actual.tobytes() == values.tobytes(), "Fixture initial bytes changed")
            entry = save_array(directory, "source-" + label, actual)
            entry.update(id=image_id, name=image.GetName(), calibration=[spatial(image, dim) for dim in (0, 1)], intensity_calibration=intensity(image))
            report["images"][label] = entry
            image.GetOrCreateImageDocument().Show(); image = None
        # A NEW dedicated fixture anchor holds ID handoffs. No source tag is
        # modified and no persistent application tags are used.
        anchor = DM.CreateImage(np.zeros((4, 4), dtype=np.float32))
        anchor.SetName("PRECISION_CONTROL_" + session[:8])
        report["anchor_id"] = anchor.GetID(); anchor.GetOrCreateImageDocument().Show(); anchor = None
        report["document_count_after"] = DM.CountImageDocumentsOfAllWorkspaces()
        require(report["document_count_after"] == report["document_count_before"] + 7, "Fixture document ownership mismatch")
        report["status"] = "RECORDED_SYNTHETIC_FIXTURE"
    except BaseException as error:
        report.update(error_type=type(error).__name__, error=str(error)); raise
    finally:
        write_json(report_path, report)
    return report


def direct_script(source_id, anchor_id, label):
    require(type(source_id) is int and 0 < source_id < 0xffffffff and type(anchor_id) is int and 0 < anchor_id < 0xffffffff,
            "Integer exact IDs only")
    require(label in arrays(), "Unknown fixed synthetic case")
    # RealFFT is the full-complex real-source transform; RealIFFT/PackedIFFT
    # are deliberately absent. Actual native type 3 is checked before reading.
    return ('image source := FindImageByID(%d)\n'
            'image control := FindImageByID(%d)\n'
            'TagGroup handoff = control.ImageGetTagGroup()\n'
            'image spectrum := RealFFT(source)\n'
            'image inverse := IFFT(spectrum)\n'
            'handoff.TagGroupSetTagAsLong("%s_fft", GetImageID(spectrum))\n'
            'handoff.TagGroupSetTagAsLong("%s_ifft", GetImageID(inverse))\n'
            'SetName(spectrum, "PRECISION_DIRECT_%s_FFT")\n'
            'SetName(inverse, "PRECISION_DIRECT_%s_IFFT")\n'
            'ShowImage(spectrum)\n'
            'ShowImage(inverse)\n') % (source_id, anchor_id, label, label, label, label)


def observe(directory, expected_pid):
    with open(os.path.join(directory, "fixture.json"), "r", encoding="utf-8") as source: fixture = json.load(source)
    validate_host_identity(fixture["session"], expected_pid)
    import DigitalMicrograph as DM
    import numpy as np
    with open(os.path.join(directory, "native-map.json"), "r", encoding="utf-8") as source: native = json.load(source)
    require(os.getpid() == expected_pid == fixture["host_pid"] and fixture["status"] == "RECORDED_SYNTHETIC_FIXTURE" and fixture["policy"] == POLICY,
            "Actual host PID/original fixed policy mismatch")
    require(set(native) == set(arrays()) and set(fixture["images"]) == set(arrays()), "Complete fixed matrix required")
    target = os.path.join(directory, "observation.json")
    require(not os.path.exists(target), "Observation already exists; do not overwrite/replay direct operations")
    report = {"schema": 1, "status": "FAIL", "host_pid": os.getpid(), "session": fixture["session"], "policy": POLICY,
              "kind": "synthetic-only", "cases": {}, "owned_direct_image_ids": [], "python_is_listener": False}
    try:
        require(DM.CountImageDocumentsOfAllWorkspaces() == fixture["document_count_after"], "Unexpected document edits before precision observer")
        threads = None
        for label, expected in arrays().items():
            entry = fixture["images"][label]; shape = entry["shape"]
            source_values = snapshot(DM, entry["id"], entry["dtype"], shape)
            require(source_values.tobytes() == expected.tobytes(), "Source differs from fixed fixture")
            source = DM.FindImageByID(entry["id"])
            require(source.GetName() == entry["name"] and [spatial(source, d) for d in (0, 1)] == entry["calibration"] and intensity(source) == entry["intensity_calibration"], "Source metadata changed")
            source = None
            row = {"source_id": entry["id"], "snapshots": {}, "direct_ids": {}, "native": native[label]}; ids = {}
            for kind, op, dtype in (("fft", "FFT", "complex64"), ("ifft", "IFFT", "complex64"), ("real", "REAL", "float32"), ("read", "READ", "float32")):
                result = native[label][kind]; receipt = result["native_receipt"]
                args = [entry["id"]] if kind == "fft" else [ids["fft"]] if kind == "ifft" else [ids["ifft"]] if kind == "real" else [ids["real"], 0, 0, shape[1], shape[0]]
                require(receipt["state"] == "completed" and receipt["session"] == fixture["session"] and receipt["host_pid"] == os.getpid() and receipt["original_operation"] == op and receipt["normalized_args"] == args,
                        "Original MCP operation/session/PID/args mismatch")
                current_threads = (receipt["exec_tid"], receipt["worker_tid"])
                require(all(type(v) is int and v > 0 for v in current_threads) and current_threads[0] != current_threads[1] and
                        (threads is None or threads == current_threads), "MCP host/worker thread mismatch")
                threads = current_threads
                if kind == "read":
                    raw = base64.b64decode(result["values_base64"], validate=True)
                    require(result["dtype"] == "float32" and result["shape"] == shape and raw == native_values.tobytes(), "READ introduces pixel/dtype/axis differences")
                    continue
                image_id = result["image_id"]
                require(image_id != entry["id"] and image_id not in ids.values(), "Native output aliases source/previous result")
                ids[kind] = image_id
                native_values = snapshot(DM, ids[kind], dtype, shape)
                row["snapshots"]["bridge_" + kind] = save_array(directory, label + "-bridge-" + kind, native_values)
            # This exact source ID is handed to the independent DM-Script.
            script = direct_script(entry["id"], fixture["anchor_id"], label)
            script_file = label + "-direct.s"
            with open(os.path.join(directory, script_file), "x", encoding="utf-8") as output: output.write(script)
            row["direct_script_file"] = script_file
            DM.ExecuteScriptString(script)
            anchor = DM.FindImageByID(fixture["anchor_id"]); tags = anchor.GetTagGroup()
            for kind in ("fft", "ifft"):
                ok, image_id = tags.GetTagAsLong(label + "_" + kind)
                require(ok and type(image_id) is int and image_id > 0 and image_id not in ids.values() and image_id not in report["owned_direct_image_ids"], "Exact direct operator ID handoff invalid")
                report["owned_direct_image_ids"].append(image_id)
                row["direct_ids"][kind] = image_id
                values = snapshot(DM, image_id, "complex64", shape)
                row["snapshots"]["direct_" + kind] = save_array(directory, label + "-direct-" + kind, values)
            anchor = tags = None
            require(snapshot(DM, entry["id"], entry["dtype"], shape).tobytes() == source_values.tobytes(), "Direct operation mutated source")
            report["cases"][label] = row
        for label, expected in arrays().items():
            entry = fixture["images"][label]; source = DM.FindImageByID(entry["id"])
            require(snapshot(DM, entry["id"], entry["dtype"], entry["shape"]).tobytes() == expected.tobytes() and source.GetName() == entry["name"] and
                    [spatial(source, d) for d in (0, 1)] == entry["calibration"] and intensity(source) == entry["intensity_calibration"], "Final source pixels/metadata changed")
            source = None
        require(DM.CountImageDocumentsOfAllWorkspaces() == fixture["document_count_after"] + 12, "Direct document ownership/count mismatch")
        report.update(status="RECORDED_SAME_HOST_PRECISION_COMPARISON", source_pixels_unchanged=True,
                      document_count=DM.CountImageDocumentsOfAllWorkspaces(), numeric_qualification="NOT_QUALIFIED_UNTIL_EXTERNAL_VERIFY")
    except BaseException as error:
        report.update(error_type=type(error).__name__, error=str(error)); raise
    finally:
        write_json(target, report)
    return report
