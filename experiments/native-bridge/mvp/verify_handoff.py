# -*- coding: utf-8 -*-
"""Explicit same-host, read-only synthetic READ/NPY/external-mean oracle.

Run manually inside the prepared host after all original evidence is durable.
This script creates only a new evidence JSON. It is never a runtime fallback,
DM SaveAs implementation, atomic capture, GUI test or model-viewing assertion.
"""
import base64
from fractions import Fraction
import hashlib
import io
import json
import math
import os
import re

from create_summary_fixture import require, spatial, intensity
from verify_operations import (LABEL_SHAPES, bind_metadata,
                               integer, strict_json)
from verify_operations_math import quarter_turn_dft, verify_filter
from verify_preview import (MAPPING, ORIENTATION, SAMPLING, decode_gray8_png,
                            reference_preview)

MAPPING_POLICY = "logical ROI only; source_x=x0+roi_x; source_y=y0+roi_y; source unchanged"
PROVENANCE_SCOPE = "immutable creation record only; source image remains mutable"
ARITHMETIC_SEMANTICS = "DM native raw pixel arithmetic; intensity/spatial metadata copied from first input"
FOURIER_INTENSITY_POLICY = "DM Fourier outputs reset intensity calibration to origin 0, scale 1, empty unit; components inherit parent calibration"
ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
TYPES = {"STATUS": "status", "CROP": "image_crop", "UNARY": "native_image_operation",
         "READ": "native_data_snapshot", "PREVIEW": "native_preview", "FILTER": "native_image_operation",
         "FFT": "native_fourier_operation", "IFFT": "native_fourier_operation", "REAL": "native_fourier_operation"}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    # Same schema-1 canonical JSON used by the explicit external encoder.
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


class Evidence:
    """Retain original bytes and refuse changed evidence at the final boundary."""
    def __init__(self):
        self.original = {}

    def raw(self, path, limit=4*1024*1024):
        path = os.path.realpath(path)
        with open(path, "rb") as source:
            raw = source.read(limit+1)
        require(len(raw) <= limit, "Evidence file exceeds bounded size")
        if path in self.original:
            require(raw == self.original[path], "Original evidence changed during oracle")
        self.original[path] = raw
        return raw

    def json(self, path):
        return strict_json(self.raw(path))

    def unchanged(self):
        for path, expected in self.original.items():
            with open(path, "rb") as source:
                require(source.read(len(expected)+1) == expected, "Original evidence changed during oracle")


def bounded_npy(raw, shape, dtype):
    import numpy as np
    stream = io.BytesIO(raw)
    version = np.lib.format.read_magic(stream)
    require(version in ((1, 0), (2, 0)), "Unsupported NPY version")
    header_shape, fortran, actual_dtype = (np.lib.format.read_array_header_1_0(stream) if version == (1, 0)
                                         else np.lib.format.read_array_header_2_0(stream))
    require(type(shape) is list and len(shape) == 2 and all(integer(v, 1, 256) for v in shape) and
            list(header_shape) == shape and not fortran and actual_dtype == np.dtype(dtype) and
            len(raw)-stream.tell() == shape[0]*shape[1]*actual_dtype.itemsize,
            "Bounded NPY header/shape/dtype/order/byte count mismatch")
    result = np.load(io.BytesIO(raw), allow_pickle=False)
    require(type(result) is np.ndarray and result.flags.c_contiguous, "NPY is not a C array")
    return result


def bit_equal(actual, expected, message):
    require(actual.dtype == expected.dtype and actual.shape == expected.shape and
            actual.tobytes(order="C") == expected.tobytes(order="C"), message)


def observe(DM, np, image_id, shape, dtype, compare_ids=()):
    """Check the raw descriptor before copying; never let a wrapper/view escape."""
    image = view = other = other_view = None
    try:
        image = DM.FindImageByID(image_id)
        require(image is not None and image.IsValid() and integer(image.GetID(), image_id, image_id),
                "Independent image identity invalid")
        view = image.GetNumArray()
        require(type(view) is np.ndarray and list(view.shape) == list(shape) and view.dtype == np.dtype(dtype) and
                view.ndim == 2 and all(integer(v, 1, 256) for v in view.shape),
                "Raw host view shape/dtype exceeds expected bounded descriptor")
        for other_id in compare_ids:
            try:
                other = DM.FindImageByID(other_id)
                require(other is not None and other.IsValid() and integer(other.GetID(), other_id, other_id),
                        "Independent comparison image identity invalid")
                other_view = other.GetNumArray()
                require(type(other_view) is np.ndarray and other_view.ndim == 2 and
                        all(integer(v, 1, 256) for v in other_view.shape), "Comparison raw view exceeds bounded descriptor")
                require(not np.shares_memory(view, other_view), "Source/output or output/output raw views share memory")
            finally:
                other_view = other = None
        return {"values": np.array(view, order="C", copy=True), "name": image.GetName(),
                "calibration": [spatial(image, axis) for axis in (0, 1)], "intensity_calibration": intensity(image)}
    finally:
        other_view = other = view = image = None


def payload(entry, images=False):
    response = entry.get("response", {})
    require(type(response) is dict and response.get("isError") is not True and "error" not in response,
            "MCP error is not completed evidence")
    content = response.get("content")
    require(type(content) is list and len(content) == (2 if images else 1) and
            content[0].get("type") == "text" and type(content[0].get("text")) is str,
            "Successful original MCP text/image framing required")
    result = strict_json(content[0]["text"].encode("utf-8"))
    require(type(result) is dict and result.get("backend") == "digitalmicrograph-native", "MCP native backend mismatch")
    return result


def bind_call(entry, tool, arguments, operation, args, context, images=False):
    request, output = entry.get("request", {}), payload(entry, images)
    receipt = output.get("native_receipt", {})
    request_id = request.get("id")
    require(type(request_id) is str and ID.fullmatch(request_id) is not None and
            request_id in context["ledger"] and request_id not in context["seen"] and
            request == context["ledger"][request_id], "Unbound/duplicate original native request")
    require(entry.get("tool") == tool and entry.get("arguments") == dict(arguments, request_id=request_id) and
            request.get("op") == operation and request.get("args") == args and
            type(request.get("args")) is list and all(integer(v) for v in args), "Tool/original operation/arguments mismatch")
    require(type(receipt) is dict and receipt.get("protocol") == "NB2" and
            receipt.get("session") == context["session"] and receipt.get("id") == receipt.get("request_id") == request_id and
            receipt.get("state") == "completed" and integer(receipt.get("host_pid"), context["pid"], context["pid"]) and
            receipt.get("original_operation") == operation and receipt.get("normalized_args") == args and
            type(receipt.get("normalized_args")) is list and all(integer(v) for v in receipt["normalized_args"]) and
            receipt.get("result_type") == TYPES[operation] and
            integer(receipt.get("result_version"), 2 if operation in ("FFT", "IFFT", "REAL") else 1,
                    2 if operation in ("FFT", "IFFT", "REAL") else 1) and
            not any(key in receipt for key in ("error", "code", "result")), "Completed native receipt identity/type/version mismatch")
    require(integer(receipt.get("exec_tid"), 1) and integer(receipt.get("worker_tid"), 1) and
            receipt["exec_tid"] != receipt["worker_tid"], "Native execution thread identity invalid")
    timings = receipt.get("timings_us")
    require(type(timings) is dict and set(timings) == {"queue", "execute"} and
            all(integer(timings[v], 0, 2**53-1) for v in timings), "Native timing fields invalid")
    if "threads" in context:
        require((receipt["exec_tid"], receipt["worker_tid"]) == context["threads"], "Native STATUS thread anchor changed")
    context["seen"].add(request_id)
    return output


def observation_expected(entry, values):
    return {"values": values, "name": entry["name"], "calibration": entry["calibration"],
            "intensity_calibration": entry["intensity_calibration"]}


def prepare(evidence, truth_path, report_path, ledger_path, actual_pid):
    import numpy as np
    truth, report = evidence.json(truth_path), evidence.json(report_path)
    require(integer(actual_pid, 1) and integer(truth.get("host_pid"), actual_pid, actual_pid) and
            integer(report.get("host_pid"), actual_pid, actual_pid), "Truth/report host is not actual oracle PID")
    session = truth.get("session")
    require(truth.get("schema") == report.get("schema") == 1 and truth.get("kind") == "synthetic-only" and
            truth.get("status") == report.get("status") == "RECORDED" and truth.get("python_is_listener") is False and
            type(session) is str and re.fullmatch(r"[a-f0-9]{32}", session) is not None and report.get("session") == session and
            report.get("truth_sha256") == sha(evidence.raw(truth_path)), "Prepared synthetic truth/report/session/hash mismatch")
    require(report.get("source_label") == "READ_BITS" and report.get("crop_rect") == [1, 1, 4, 4] and
            report.get("read_rect") == [0, 0, 3, 3] and report.get("source_read_rect") == [0, 0, 4, 4],
            "Fixed handoff source/ROI matrix mismatch")
    shapes = dict(LABEL_SHAPES, READ_BITS=[4, 4])
    images = truth.get("images")
    require(type(images) is list and len(images) == len(shapes) and
            {value.get("label") for value in images} == set(shapes), "Complete unique handoff source matrix required")
    sources, source_ids = {}, set()
    for entry in images:
        require(integer(entry.get("id"), 1, 0xfffffffe) and entry["id"] not in source_ids and
                entry.get("shape") == shapes[entry["label"]] and entry.get("dtype") ==
                ("uint16" if entry["label"] == "UINT16" else "float32"), "Source fixture identity/type/shape mismatch")
        raw = evidence.raw(entry["source_npy"], 512*1024)
        values = bounded_npy(raw, entry["shape"], entry["dtype"])
        require(sha(raw) == entry.get("source_file_sha256") and
                sha(values.tobytes(order="C")) == entry.get("pixel_sha256"), "Original source NPY/pixel hash mismatch")
        sources[entry["label"]] = (entry, values)
        source_ids.add(entry["id"])
    require(sources["READ_BITS"][1].view("<u4")[0].tolist() == [0x80000000, 0, 1, 0x80000001],
            "READ_BITS fixture did not preserve predetermined signed-zero/subnormal bits")
    require(integer(truth.get("initial_document_count"), len(shapes)), "Initial fixture document count invalid")
    ledger = {}
    for line in evidence.raw(ledger_path).splitlines():
        request = strict_json(line)
        request_id = request.get("id")
        require(set(request) == {"protocol", "session", "host_pid", "id", "op", "args", "wire"} and
                type(request_id) is str and ID.fullmatch(request_id) is not None and request_id not in ledger and
                request.get("protocol") == "NB2" and request.get("session") == session and
                integer(request.get("host_pid"), actual_pid, actual_pid) and type(request.get("op")) is str and
                type(request.get("args")) is list and all(integer(v) for v in request["args"]), "Original ledger identity/shape invalid")
        wire = "NB2 %s %s %s%s\n" % (session, request_id, request["op"],
                                     " " + " ".join(map(str, request["args"])) if request["args"] else "")
        require(request.get("wire") == wire, "Original ledger wire mismatch")
        ledger[request_id] = request
    context = {"pid": actual_pid, "session": session, "ledger": ledger, "seen": set(),
               "sources": sources, "source_ids": source_ids, "truth": truth, "report": report}
    checks = report.get("checks")
    require(type(checks) is list and len(checks) == 5 and {value.get("label") for value in checks} ==
            {"status", "crop", "square", "read_source", "read"}, "Fixed five-check handoff matrix required")
    context["checks"] = {value["label"]: value for value in checks}
    status = bind_call(context["checks"]["status"], "dm_status", {}, "STATUS", [], context)
    require(status.get("ready") is True and status.get("binary_gate") is True and status.get("host_pid") == actual_pid and
            status.get("host_thread") == status["native_receipt"]["exec_tid"] and
            status.get("supported_build") == "3.53.4137.0-x64" and status.get("host_build") == "3.53.4137.0" and
            status.get("host_architecture") == "x64" and status.get("adapter_profile") == "gms-3.53.4137.0-windows-x64" and
            status.get("adapter_active") is True and status.get("compatibility", {}).get("state") == "SUPPORTED",
            "STATUS readiness/profile/host anchor mismatch")
    mode = report.get("qualification_mode")
    if mode is None:
        # Historical host-v2 records have this explicit prepared-mode marker.
        require(status.get("candidate_execution_enabled") is True,
                "Unspecified qualification mode requires explicit prepared STATUS marker")
        mode = "prepared"
    require(mode in ("prepared", "production"), "Unknown qualification mode")
    if mode == "prepared":
        require(status.get("candidate_execution_enabled") is True, "Prepared qualification mode is not enabled")
    else:
        require("candidate_execution_enabled" not in status and "candidate_capabilities" not in status,
                "Production qualification must not contain a candidate execution bypass")
        capabilities = status.get("native_capabilities")
        require(type(capabilities) is list, "Production native capabilities missing")
        for name in ("native_image_arithmetic", "native_fft", "native_filters", "native_preview", "native_read"):
            matches = [value for value in capabilities if type(value) is dict and value.get("name") == name]
            require(len(matches) == 1 and matches[0].get("available") is True and
                    matches[0].get("qualification") == "LIMITED_REAL_HOST",
                    "Production operation unavailable or not qualified: "+name)
    context["qualification_mode"] = mode
    context["threads"] = (status["native_receipt"]["exec_tid"], status["native_receipt"]["worker_tid"])
    return context


def bind_pipeline(context):
    checks, report = context["checks"], context["report"]
    source_id = context["sources"]["READ_BITS"][0]["id"]
    crop = bind_call(checks["crop"], "dm_crop", {"image_id": source_id, "rect": report["crop_rect"]},
                     "CROP", [source_id]+report["crop_rect"], context)
    crop_id = crop.get("image_id")
    require(integer(crop_id, 1) and crop_id not in context["source_ids"] and crop.get("source_image_id") == source_id and
            crop.get("requested_rect") == crop.get("effective_rect") == report["crop_rect"] and
            crop.get("operator") == "GMS::Image::GetSubSliceAsImage", "CROP output identity/ROI/operator mismatch")
    square = bind_call(checks["square"], "dm_native_unary", {"image_id": crop_id, "operation": "square"},
                       "UNARY", [crop_id, 3], context)
    square_id = square.get("image_id")
    require(integer(square_id, 1) and square_id not in context["source_ids"] | {crop_id} and square.get("operation") == "square" and
            square.get("opcode") == 3 and square.get("source_image_ids") == [crop_id] and
            square.get("operator") == "GMSImageProcessing::Square" and square.get("computation") == "DM native" and
            square.get("intensity_calibration_applied") is False and square.get("intensity_semantics") == "raw pixel intensity",
            "Square output/native raw operator identity mismatch")
    for value in (crop, square):
        require(value.get("source_write_requested") is False and value.get("snapshot_atomic") is False and
                type(value.get("ownership")) is str and bool(value["ownership"]), "Native output ownership/source semantics mismatch")
    context.update(crop=crop, square=square, crop_id=crop_id, square_id=square_id)
    reads = {}
    for label, image_id, rect in (("read_source", source_id, report["source_read_rect"]), ("read", square_id, report["read_rect"])):
        reads[label] = bind_call(checks[label], "dm_native_read", {"image_id": image_id, "rect": rect},
                                 "READ", [image_id]+rect, context)
    context["reads"] = reads


def validate_read(output, image_id, rect, observation, provenance):
    import numpy as np
    require(output.get("operation") == "READ" and output.get("source_image_id") == image_id and
            output.get("requested_rect") == output.get("effective_rect") == rect and
            output.get("shape") == [rect[3]-rect[1], rect[2]-rect[0]] and
            output.get("dtype") == "float32" and output.get("byte_order") == "little" and output.get("axes") == ["y", "x"] and
            output.get("array_order") == "C" and output.get("data_encoding") == "base64", "READ identity/ROI/numeric layout mismatch")
    require(output.get("operator") == "GMS::Image::GetRealValue" and output.get("computation") == "DM native point reads; data handoff only" and
            output.get("intensity_calibration_applied") is False and output.get("intensity_semantics") == "raw pixel intensity" and
            output.get("source_write_requested") is False and output.get("snapshot_atomic") is False and
            output.get("ownership") == "response-owned numeric snapshot; no native result image" and
            output.get("coordinate_mapping_policy") == MAPPING_POLICY and output.get("source_provenance_scope") == PROVENANCE_SCOPE and
            output.get("source_provenance") == provenance, "READ raw/provenance/snapshot semantics mismatch")
    bind_metadata(output.get("source"), image_id, observation)
    expected = observation["values"][rect[1]:rect[3], rect[0]:rect[2]]
    require(expected.dtype == np.float32 and bool(np.isfinite(expected).all()) and expected.size <= 16384 and
            integer(output.get("sample_count"), expected.size, expected.size) and integer(output.get("raw_bytes"), expected.nbytes, expected.nbytes),
            "READ sample/byte budget mismatch")
    text = output.get("values_base64")
    require(type(text) is str, "READ canonical base64 missing")
    try:
        raw = base64.b64decode(text.encode("ascii"), validate=True)
    except (ValueError, UnicodeError):
        raise RuntimeError("READ canonical base64 invalid")
    require(base64.b64encode(raw).decode("ascii") == text and raw == expected.tobytes(order="C"),
            "READ raw pixels differ bitwise, including signed-zero/subnormal")
    expected_axes = []
    for axis in output["source"]["calibration"]:
        dim = axis["dm_dimension"]
        offset = rect[dim]
        expected_axes.append({"dm_dimension": dim, "numpy_axis": 1-dim, "size": expected.shape[1-dim],
            "source_offset": offset, "source_origin": axis["origin"],
            "source_calibrated_value_at_pixel_zero": axis["calibrated_value_at_pixel_zero"],
            "origin": axis["origin"]-offset,
            "calibrated_value_at_pixel_zero": axis["calibrated_value_at_pixel_zero"]+offset*axis["scale"],
            "scale": axis["scale"], "unit": axis["unit"], "usable": axis["usable"], "issue": axis["issue"]})
    require(output.get("roi_calibration") == expected_axes and output.get("calibration_complete") is True,
            "READ signed ROI calibration/coordinate mapping mismatch")
    return raw


def validate_capture(evidence, entry, output):
    snapshot_raw = evidence.raw(entry["snapshot"])
    require(sha(snapshot_raw) == entry.get("snapshot_sha256"), "Saved original MCP snapshot hash mismatch")
    saved = strict_json(snapshot_raw)
    actual = payload({"response": saved}) if "content" in saved else saved
    require(actual == output, "Saved snapshot differs from original MCP READ response")
    receipt, raw = output["native_receipt"], base64.b64decode(output["values_base64"])
    record, capture_receipt = evidence.json(entry["request_record"]), entry.get("receipt", {})
    require(record.get("schema_version") == 1 and record.get("kind") == "native_snapshot_handoff_request" and
            record.get("state") == "CAPTURED" and record.get("capture_receipt") == capture_receipt and
            capture_receipt.get("state") == "captured" and record.get("capture_id") == capture_receipt.get("capture_id") and
            record.get("request_id") == capture_receipt.get("request_id") and
            type(record.get("request_id")) is str and ID.fullmatch(record["request_id"]) is not None,
            "Handoff journal/capture is incomplete or identity mismatched")
    receipt_hash = sha(canonical(receipt))
    require(record.get("native_receipt") == receipt and record.get("native_receipt_sha256") == receipt_hash,
            "Handoff original native receipt mismatch")
    params = record.get("parameters", {})
    target = os.path.realpath(capture_receipt["capture_dir"])
    require(record.get("parameters_sha256") == sha(canonical(params)) and
            params.get("saved_snapshot_sha256") == sha(snapshot_raw) and params.get("native_receipt_sha256") == receipt_hash and
            params.get("native_values_sha256") == sha(raw) and params.get("session") == receipt["session"] and
            params.get("native_request_id") == receipt["id"] and params.get("operation") == "READ" and
            params.get("normalized_args") == receipt["normalized_args"] and
            os.path.realpath(params.get("snapshot_path", "")) == os.path.realpath(entry["snapshot"]) and
            os.path.realpath(os.path.join(params.get("workspace", ""), params.get("output", ""))) == target,
            "Immutable handoff parameters/path/receipt hash mismatch")
    files = {name: evidence.raw(os.path.join(target, name), 512*1024) for name in ("input.npy", "input.json", "capture.json")}
    hashes = {name: sha(value) for name, value in files.items()}
    require(capture_receipt.get("files_sha256") == hashes, "Capture original files hash mismatch")
    info, manifest = strict_json(files["input.json"]), strict_json(files["capture.json"])
    source_cal = [dict(axis, axis="x" if index == 0 else "y") for index, axis in enumerate(output["source"]["calibration"])]
    work_cal = [dict(axis, axis="x" if index == 0 else "y") for index, axis in enumerate(output["roi_calibration"])]
    require(info.get("schema_version") == manifest.get("schema_version") == 1 and manifest.get("state") == "captured" and
            info.get("capture_id") == manifest.get("capture_id") == capture_receipt["capture_id"] and
            info.get("native_receipt") == receipt and info.get("native_receipt_sha256") == manifest.get("native_receipt_sha256") == receipt_hash and
            info.get("saved_snapshot_sha256") == manifest.get("saved_snapshot_sha256") == sha(snapshot_raw) and
            info.get("input_sha256") == manifest.get("input_sha256") == capture_receipt.get("input_sha256") == hashes["input.npy"] and
            manifest.get("input_metadata_sha256") == sha(canonical(info)) and
            manifest.get("input_metadata_file_sha256") == hashes["input.json"], "Captured manifest/native/file identity mismatch")
    require(info.get("source_metadata") == output["source"] and info.get("source_image_id") == manifest.get("source_image_id") == output["source_image_id"] and
            info.get("source_shape_yx") == manifest.get("source_shape_yx") == output["source"]["shape"] and
            info.get("source_rect_xyxy") == manifest.get("source_rect_xyxy") == capture_receipt.get("source_rect_xyxy") == output["effective_rect"] and
            info.get("source_calibration_dm") == manifest.get("calibration_before") == manifest.get("calibration_after") == source_cal and
            info.get("working_calibration_xy") == work_cal and info.get("native_source_provenance") == output["source_provenance"] and
            info.get("native_source_provenance_scope") == PROVENANCE_SCOPE and info.get("coordinate_mapping_policy") == MAPPING_POLICY,
            "Captured source/ROI/calibration/provenance mismatch")
    require(info.get("source_rect_convention") == manifest.get("source_rect_convention") == "zero-based half-open [x0,y0,x1,y1]" and
            info.get("pixel_coordinate_model") == "pixel centers at integer x,y; physical value = calibrated_value_at_pixel_zero + index*scale" and
            info.get("calibration_complete") is output["calibration_complete"] and info.get("source_path_included") is False and
            info.get("snapshot_identity_scope") == "immutable stored numeric bytes; source image ID and live pixels remain mutable" and
            manifest.get("operation") == "bounded 2D capture" and
            manifest.get("capture_backend") == "saved digitalmicrograph-native READ numeric snapshot" and
            manifest.get("memory_estimate_bytes") == len(files["input.npy"])+len(raw) and
            manifest.get("memory_budget_bytes") == 256*1024 and
            manifest.get("descriptor_evidence") == "native READ metadata-before/after contract; no atomic pixel claim",
            "Captured coordinate/ownership/budget policy mismatch")
    require(info.get("dtype") == capture_receipt.get("dtype") == manifest.get("source_dtype") == "float32" and
            manifest.get("source_data_type_code") == 2 and info.get("shape_yx") == capture_receipt.get("shape_yx") == output["shape"] and
            info.get("byte_order") == "little" and info.get("array_order") == "C" and info.get("axes") == ["y", "x"] and
            info.get("axis_roles") == [{"numpy_axis": 0, "dm_dimension": 1, "role": "y"}, {"numpy_axis": 1, "dm_dimension": 0, "role": "x"}] and
            info.get("intensity_calibration") == {"origin": None, "scale": None, "unit": None, "status": "NOT_READ"} and
            info.get("intensity_calibration_applied") is False and info.get("raw_bytes") == output["raw_bytes"] and
            info.get("sample_count") == output["sample_count"] and info.get("input_file_bytes") == len(files["input.npy"]) and
            info.get("input_file") == "input.npy" and info.get("pixel_sha256") == manifest.get("pixel_sha256") == sha(raw),
            "Captured numerical layout/pixel hash/raw intensity mismatch")
    for value in (info, manifest, capture_receipt):
        require(value.get("pixel_capture_atomic") is False and value.get("dm_file_save") is False,
                "Capture falsely claims atomic capture or DM SaveAs")
    require(info.get("external_saved_response_encoding") is True and manifest.get("external_saved_response_encoding") is True and
            manifest.get("live_source_reobserved") is False and manifest.get("descriptor_unchanged") is True and
            manifest.get("native_session") == capture_receipt.get("native_session") == receipt["session"] and
            manifest.get("native_request_id") == capture_receipt.get("native_request_id") == receipt["id"] and
            manifest.get("handoff_request_id") == capture_receipt["request_id"], "Capture handoff state/session semantics mismatch")
    values = bounded_npy(files["input.npy"], output["shape"], "<f4")
    require(values.tobytes(order="C") == raw, "Encoded NPY differs bitwise from original native READ")
    return {"info": info, "hashes": hashes, "values": values, "directory": target}


def validate_external(evidence, entry, capture):
    require(entry.get("capture_label") == "processed", "External mean must bind processed capture")
    directory = entry["output_dir"]
    run = evidence.json(os.path.join(directory, "run.json"))
    params = evidence.json(os.path.join(directory, "parameters.json"))
    result_raw = evidence.raw(os.path.join(directory, "results.json"))
    result = strict_json(result_raw)
    script = evidence.raw(os.path.join(directory, "native_handoff_mean.py"))
    expected_script = evidence.raw(os.path.join(os.path.dirname(__file__), "..", "..", "..", "examples", "native_handoff_mean.py"))
    require(script == expected_script, "External executed script copy differs from explicit example")
    info = capture["info"]
    expected = {"schema_version": 1, "operation": "raw mean", "execution": "explicit external NumPy example",
        "capture_id": info["capture_id"], "capture_files_sha256": capture["hashes"], "dtype": "float32", "accumulator_dtype": "float64",
        "shape_yx": info["shape_yx"], "source_image_id": info["source_image_id"], "source_rect_xyxy": info["source_rect_xyxy"],
        "native_session": info["native_receipt"]["session"], "native_request_id": info["native_receipt"]["id"],
        "native_receipt_sha256": info["native_receipt_sha256"], "intensity_calibration_applied": False,
        "source_calibration_dm": info["source_calibration_dm"], "working_calibration_xy": info["working_calibration_xy"],
        "dm_called": False, "result_returned_to_dm": False, "script_sha256": sha(script)}
    require(all(params.get(key) == value for key, value in expected.items()) and
            all(type(params.get(key)) is str and bool(params[key]) for key in ("python_version", "numpy_version", "platform")),
            "External original parameters/capture/script hash mismatch")
    values = capture["values"]
    exact = sum((Fraction.from_float(float(value)) for value in values.flat), Fraction(0)) / int(values.size)
    expected_mean = float(exact)
    require(run.get("schema_version") == result.get("schema_version") == 1 and run.get("state") == result.get("state") == "complete" and
            run.get("scope") == "explicit external raw mean only" and run.get("results_sha256") == sha(result_raw) and
            result.get("scope") == "explicit external NumPy raw mean only" and result.get("capture_id") == info["capture_id"] and
            type(result.get("mean")) in (int, float) and math.isfinite(result["mean"]) and result["mean"] == expected_mean and
            integer(result.get("sample_count"), int(values.size), int(values.size)) and result.get("accumulator_dtype") == "float64" and
            result.get("parameters_sha256") == sha(canonical(params)) and result.get("script_sha256") == sha(script) and
            result.get("input_sha256") == info["input_sha256"] and result.get("intensity_calibration_applied") is False and
            result.get("intensity_unit") is None and result.get("intensity_calibration_status") == "NOT_READ" and
            result.get("dm_called") is False and result.get("result_returned_to_dm") is False, "External mean/state/hash/raw-scope mismatch")
    return {"status": "PASS", "mean": expected_mean, "sample_count": int(values.size),
            "reference": "exact rational sum of represented float32 values, rounded once to binary64", "dm_called": False}


def check_source(entry, saved, actual):
    bit_equal(actual["values"], saved, "Live original source pixels/dtype/shape changed")
    require(actual["name"] == entry["name"] and actual["calibration"] == entry["calibration"] and
            actual["intensity_calibration"] == entry["intensity_calibration"], "Live source name/spatial/intensity calibration changed")


def check_output(value, image_id, observation, source_id, source_observation):
    bind_metadata(value.get("image"), image_id, observation)
    if "sources" in value:
        require(type(value["sources"]) is list and len(value["sources"]) == 1, "Unary source metadata missing")
        bind_metadata(value["sources"][0], source_id, source_observation)
    else:
        bind_metadata(value.get("source"), source_id, source_observation)


def check_preview(context, evidence, source):
    entries = context["report"].get("previews")
    require(type(entries) is list and len(entries) == 1, "Exactly one original source preview required")
    entry = entries[0]
    source_id = context["sources"]["READ_BITS"][0]["id"]
    out = bind_call(entry, "dm_native_preview", {"image_id": source_id}, "PREVIEW", [source_id, 128, 128], context, True)
    require(out.get("operation") == "PREVIEW" and out.get("image_id") == source_id and
            out.get("operator") == "GMS::Image::GetRealValue" and out.get("quantitative") is False and
            out.get("source_write_requested") is False and out.get("snapshot_atomic") is False and
            out.get("mapping") == MAPPING and out.get("orientation") == ORIENTATION and out.get("sampling") == SAMPLING and
            out.get("range_source") == "sampled native point values" and out.get("constant_range_gray8") == 0,
            "Preview display/coordinate semantics mismatch")
    bind_metadata(out.get("source"), source_id, source)
    width, height, low, high, gray, coordinates, unused_samples = reference_preview(source["values"], 128, 128)
    require(out.get("width") == width and out.get("height") == height and out.get("sample_count") == width*height and
            out.get("sampled_minimum") == low and out.get("sampled_maximum") == high,
            "Preview raw sample range/no-upscale mismatch")
    # The MCP facade intentionally strips raw gray8_hex from its text output.
    if "gray8_hex" in out:
        require(out["gray8_hex"] == gray.hex(), "Preview raw grayscale mapping mismatch")
    image = entry["response"]["content"][1]
    require(image.get("type") == "image" and image.get("mimeType") == "image/png", "MCP PNG image block missing")
    png = evidence.raw(entry["png"], 2*1024*1024)
    require(sha(png) == entry.get("png_sha256") and base64.b64decode(image["data"], validate=True) == png,
            "Original PNG/file/MCP byte hash mismatch")
    require(decode_gray8_png(png) == (width, height, gray), "PNG decoded pixels/axes differ from raw floor/sample/half-up mapping")
    return {"status": "PASS_DISPLAY_SAMPLE_MAPPING", "png_sha256": sha(png), "sample_coordinates_xy": coordinates,
            "scientific_export": False, "model_viewing": "NOT_TESTED"}


def collect_extras(context, DM, np, compare_ids):
    entries = context["report"].get("extra_checks")
    labels = {"fft", "ifft", "inverse_real", "smooth", "sobel", "laplace", "sharpen"}
    require(type(entries) is list and len(entries) == 7 and {v.get("label") for v in entries} == labels,
            "Fixed Fourier-v2/filter additional matrix required")
    entries = {v["label"]: v for v in entries}
    source_id = context["sources"]["A"][0]["id"]
    a_entry, a_values = context["sources"]["A"]
    source = observation_expected(a_entry, a_values)
    output, results = {}, []
    forward = quarter_turn_dft(a_values)
    for label, op, tool, extra, expected in (
            ("fft", "FFT", "dm_native_fft", {"direction": "forward"}, forward),
            ("ifft", "IFFT", "dm_native_fft", {"direction": "inverse"}, a_values.astype(np.complex64)),
            ("inverse_real", "REAL", "dm_native_complex", {"component": "real"}, a_values)):
        value = bind_call(entries[label], tool, dict(extra, image_id=source_id), op, [source_id], context)
        image_id = value.get("image_id")
        require(integer(image_id, 1) and image_id not in compare_ids and value.get("operation") == op and
                value.get("source_image_id") == source_id and value.get("operator") ==
                "GMSImageProcessing::"+{"FFT": "Real_FFT", "IFFT": "IFFT", "REAL": "Real"}[op] and
                value.get("source_write_requested") is False and value.get("snapshot_atomic") is False and
                value.get("intensity_calibration_applied") is False and value.get("computation") == "DM native",
                "Fourier-v2 additional operation identity/raw semantics mismatch")
        require(value.get("representation") == ("real_component" if op == "REAL" else "full_complex") and
                value.get("normalization") == {"FFT": "none", "IFFT": "1/(width*height)", "REAL": "inherited_parent_transform"}[op] and
                value.get("centering") == ("fftshift_data" if op == "FFT" else "spatial_origin_zero") and
                value.get("phase_units") == "not_applicable" and value.get("transform_signs") == {"forward": "+", "inverse": "-"} and
                value.get("input_index_origin") == "zero-based pixel indices" and value.get("source_spatial_origin_used") is False and
                value.get("inverse_restores_source_origin") is False and value.get("intensity_calibration_policy") == FOURIER_INTENSITY_POLICY,
                "Fourier-v2 declared normalization/origin/calibration contract mismatch")
        actual = observe(DM, np, image_id, expected.shape, expected.dtype, compare_ids)
        require(actual["values"].dtype == expected.dtype and actual["values"].shape == expected.shape and
                np.array_equal(actual["values"], expected), "Fourier-v2 differs from predetermined DFT/normalized inverse")
        expected_cal = []
        for axis in a_entry["calibration"]:
            dim = axis["dm_axis"]
            scale = 1.0/(a_values.shape[1-dim]*axis["scale"]) if op == "FFT" else axis["scale"]
            raw_origin = (a_values.shape[1-dim]+1)/2.0 if op == "FFT" else 0.0
            expected_cal.append({"dm_axis": dim, "origin": -raw_origin*scale if op == "FFT" else 0.0,
                                 "raw_origin": raw_origin, "scale": scale, "unit": "1/nm" if op == "FFT" else "nm"})
        require(actual["calibration"] == expected_cal and actual["intensity_calibration"] == {"origin": 0.0, "scale": 1.0, "unit": ""},
                "Fourier-v2 signed frequency/inverse/intensity calibration mismatch")
        grid = None
        if op == "FFT":
            axes = []
            for axis in expected_cal:
                dim, step, zero = axis["dm_axis"], axis["scale"], axis["origin"]
                length = a_values.shape[1-dim]
                dc = length//2
                axes.append({"dm_dimension": dim, "size": length, "dc_index": dc, "cycles_per_pixel_step": 1.0/length,
                             "physical_frequency_step": step, "unit": axis["unit"], "frequency_at_index_zero": -dc*step,
                             "native_calibrated_value_at_pixel_zero": zero, "native_calibration_dc_value": zero+dc*step,
                             "coordinate_rule": "f(i)=(i-dc_index)*physical_frequency_step"})
            grid = {"native_calibration_has_half_bin_offset": True, "axes": axes}
        require(value.get("frequency_grid") == grid, "Fourier-v2 frequency grid/DC coordinate contract mismatch")
        check_output(value, image_id, actual, source_id, source)
        results.append({"label": label, "image_id": image_id, "request_id": value["native_receipt"]["id"],
                        "status": "PASS_PREDETERMINED_FIXTURE_ONLY", "pixel_sha256": sha(actual["values"].tobytes(order="C"))})
        output[label] = actual
        compare_ids.append(image_id)
        source_id, source = image_id, actual
    source_entry, filter_values = context["sources"]["FILTER_A"]
    source = observation_expected(source_entry, filter_values)
    for code, label in enumerate(("smooth", "sobel", "laplace", "sharpen"), 1):
        source_id = source_entry["id"]
        value = bind_call(entries[label], "dm_native_filter", {"image_id": source_id, "operation": label},
                          "FILTER", [source_id, code], context)
        image_id = value.get("image_id")
        require(integer(image_id, 1) and image_id not in compare_ids and value.get("operation") == "FILTER" and
                value.get("source_image_id") == source_id and value.get("filter_kind") == code and
                value.get("operator") == "GMSImageProcessing::"+("SmoothFilter", "SobelFilter", "LaplaceFilter", "SharpenFilter")[code-1] and
                value.get("source_write_requested") is False and value.get("snapshot_atomic") is False and
                value.get("computation") == "DM native" and value.get("kernel") == value.get("edge_behavior") == "vendor_defined",
                "FILTER additional operation identity/kernel semantics mismatch")
        actual = observe(DM, np, image_id, filter_values.shape, np.float32, compare_ids)
        math_result = verify_filter(filter_values, actual["values"], code)
        require(actual["calibration"] == source_entry["calibration"] and
                actual["intensity_calibration"] == source_entry["intensity_calibration"], "FILTER source calibration copy mismatch")
        check_output(value, image_id, actual, source_id, source)
        results.append(dict(math_result, label=label, image_id=image_id, request_id=value["native_receipt"]["id"], status="PASS_PREDETERMINED_FIXTURE_ONLY"))
        compare_ids.append(image_id)
    return results


def collect(report, truth_path, report_path, ledger_path):
    import numpy as np
    evidence = Evidence()
    context = prepare(evidence, truth_path, report_path, ledger_path, os.getpid())
    bind_pipeline(context)
    report.update(host_pid=os.getpid(), session=context["session"], qualification_mode=context["qualification_mode"],
                  truth_sha256=sha(evidence.raw(truth_path)),
                  mcp_report_sha256=sha(evidence.raw(report_path)), ledger_sha256=sha(evidence.raw(ledger_path)))
    # Preload and validate all existing capture/external files before DM access.
    captures = context["report"].get("captures")
    require(type(captures) is list and len(captures) == 2 and {v.get("label") for v in captures} == {"source", "processed"},
            "Both original source/processed captures required")
    packaged = {entry["label"]: validate_capture(evidence, entry, context["reads"]["read_source" if entry["label"] == "source" else "read"])
                for entry in captures}
    external = validate_external(evidence, context["report"]["external"], packaged["processed"])
    for preview_entry in context["report"].get("previews", []):
        evidence.raw(preview_entry["png"], 2*1024*1024)
    import DigitalMicrograph as DM
    require(DM.CountImageDocumentsOfAllWorkspaces() == context["truth"]["initial_document_count"], "Handoff unexpectedly created visible documents")
    source_ids = list(context["source_ids"])
    before = {}
    for label, (entry, saved) in context["sources"].items():
        actual = observe(DM, np, entry["id"], saved.shape, saved.dtype, [v for v in source_ids if v != entry["id"]])
        check_source(entry, saved, actual)
        before[label] = actual
    source = before["READ_BITS"]
    crop = observe(DM, np, context["crop_id"], [3, 3], np.float32, source_ids)
    square = observe(DM, np, context["square_id"], [3, 3], np.float32, source_ids+[context["crop_id"]])
    expected_crop = np.array(source["values"][1:4, 1:4], order="C", copy=True)
    bit_equal(crop["values"], expected_crop, "Native crop pixels/axes differ from source ROI")
    expected_square = np.array([[np.float32(float(v)*float(v)) for v in row] for row in expected_crop], dtype=np.float32)
    bit_equal(square["values"], expected_square, "Native square differs from independently enumerated raw arithmetic")
    expected_cal = [dict(axis, raw_origin=axis["raw_origin"]-1, origin=axis["origin"]+axis["scale"]) for axis in source["calibration"]]
    require(crop["calibration"] == square["calibration"] == expected_cal and
            crop["intensity_calibration"] == square["intensity_calibration"] == source["intensity_calibration"],
            "Crop/square signed spatial or intensity calibration mismatch")
    check_output(context["crop"], context["crop_id"], crop, context["sources"]["READ_BITS"][0]["id"], source)
    check_output(context["square"], context["square_id"], square, context["crop_id"], crop)
    provenance = {"operation": "UNARY", "request_id": context["square"]["native_receipt"]["id"],
                  "source_image_ids": [context["crop_id"]], "semantics": ARITHMETIC_SEMANTICS}
    validate_read(context["reads"]["read_source"], context["sources"]["READ_BITS"][0]["id"], [0, 0, 4, 4], source, None)
    validate_read(context["reads"]["read"], context["square_id"], [0, 0, 3, 3], square, provenance)
    preview = check_preview(context, evidence, source)
    extras = collect_extras(context, DM, np, source_ids+[context["crop_id"], context["square_id"]])
    for label, (entry, saved) in context["sources"].items():
        check_source(entry, saved, observe(DM, np, entry["id"], saved.shape, saved.dtype))
    for image_id, original in ((context["crop_id"], crop), (context["square_id"], square)):
        final = observe(DM, np, image_id, original["values"].shape, original["values"].dtype)
        bit_equal(final["values"], original["values"], "Pipeline result changed during independent oracle")
        require(final["name"] == original["name"] and final["calibration"] == original["calibration"] and
                final["intensity_calibration"] == original["intensity_calibration"], "Pipeline result metadata changed during independent oracle")
    require(DM.CountImageDocumentsOfAllWorkspaces() == context["truth"]["initial_document_count"], "Document count changed during oracle")
    require(context["seen"] == set(context["ledger"]), "Original ledger/observed calls are not one-to-one")
    evidence.unchanged()
    report.update(status="PASS_BOUNDED_SYNTHETIC_HANDOFF", source_protection="PASS", independent_memory="PASS",
                  raw_views_and_wrappers_released=True, numeric_handoff="PASS_BITWISE_FLOAT32", signed_zero_and_subnormal="PASS",
                  crop_id=context["crop_id"], processed_id=context["square_id"], preview=preview, external_mean=external,
                  additional_operations=extras, document_count=context["truth"]["initial_document_count"],
                  sources=[{"label": label, "image_id": entry["id"], "pixel_sha256": entry["pixel_sha256"],
                            "source_file_sha256": entry["source_file_sha256"], "spatial_and_intensity_preserved": True}
                           for label, (entry, saved) in context["sources"].items()],
                  pipeline=[{"operation": name, "image_id": image_id, "shape": list(value["values"].shape),
                             "dtype": str(value["values"].dtype), "pixel_sha256": sha(value["values"].tobytes(order="C")),
                             "calibration": value["calibration"], "intensity_calibration": value["intensity_calibration"]}
                            for name, image_id, value in (("source", context["sources"]["READ_BITS"][0]["id"], source),
                                                         ("crop", context["crop_id"], crop), ("square", context["square_id"], square))],
                  captures=[{"label": label, "capture_id": value["info"]["capture_id"], "files_sha256": value["hashes"],
                             "pixel_sha256": value["info"]["pixel_sha256"], "native_request_id": value["info"]["native_receipt"]["id"]}
                            for label, value in packaged.items()],
                  evidence_files_sha256={path: sha(raw) for path, raw in evidence.original.items()})


def main():
    directory = os.environ["DM_NATIVE_EVIDENCE_DIR"]
    truth = os.environ.get("DM_NATIVE_HANDOFF_TRUTH", os.path.join(directory, "operations-truth.json"))
    source_report = os.environ.get("DM_NATIVE_HANDOFF_REPORT", os.path.join(directory, "mcp-handoff-report.json"))
    ledger = os.environ.get("DM_NATIVE_HANDOFF_LEDGER", os.path.join(directory, "mcp-handoff-requests.jsonl"))
    target = os.environ.get("DM_NATIVE_HANDOFF_OUTPUT", os.path.join(directory, "independent-handoff.json"))
    with open(target, "x", encoding="utf-8") as output:
        report = {"schema": 1, "status": "FAIL", "kind": "synthetic-only", "scope": "bounded prepared same-host numeric handoff",
                  "runtime_fallback": False, "dm_file_save": False, "pixel_capture_atomic": False,
                  "model_viewing": "NOT_TESTED", "ui_visibility": "NOT_TESTED", "lifecycle": "NOT_TESTED_BY_THIS_SCRIPT"}
        try:
            collect(report, truth, source_report, ledger)
        except BaseException as error:
            report.update(status="FAIL", error_type=type(error).__name__, error=str(error))
        json.dump(report, output, ensure_ascii=True, allow_nan=False, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    print(report["status"]+": bounded synthetic handoff; no SaveAs/model-viewing/lifecycle claim")
    return 0 if report["status"] == "PASS_BOUNDED_SYNTHETIC_HANDOFF" else 1


if __name__ == "__main__":
    raise SystemExit(main())
