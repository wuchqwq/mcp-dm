# -*- coding: utf-8 -*-
"""Independent line/profile acceptance oracle, never a DM runtime fallback.

Manifest schema 1: host_pid, session, fixture_file, status_request_file,
status_result_file, cases[{label,source_label,request_file,result_file,
capture_directory, optional rois_result_file/recovered_result_file}]. The
fixture uses create_line_profile_fixture.py's saved image observations/arrays.
after-release also needs release_records[{request_file,result_file}]; after-stop
needs stop_request_file/stop_result_file. Run host phases in separate one-shot
scripts after return to an idle host, never on the cleanup call's own stack.
--phase files reopens saved evidence externally and makes no fresh-host claim.
Only a new output JSON is written. No native requests, edits, shows or closes.
"""
import argparse
import base64
import hashlib
import io
import json
import math
import os
import re

from verify_gui_roi import load, all_documents, image_observation, normalized_mapping


RID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
SESSION = re.compile(r"[a-f0-9]{32}\Z")
TYPES = {"STATUS": "status", "PROFILE": "native_line_profile", "STOP": "ipc_stop",
         "RELEASE": "native_result_release", "ROIS": "native_gui_rois"}
AXES = ["native_profile_axis"]
MAX_SAMPLES = 4096


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, low=0, high=0xffffffff):
    return type(value) is int and low <= value <= high


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


class Evidence:
    def __init__(self, directory):
        self.directory = os.path.realpath(directory)
        self.original = {}

    def path(self, name):
        require(type(name) is str and name and not os.path.isabs(name), "Relative evidence path required")
        path = os.path.abspath(os.path.join(self.directory, name))
        require(os.path.commonpath([self.directory, path]) == self.directory and os.path.realpath(path) == path and not os.path.islink(path),
                "Evidence path escapes its directory or follows a link")
        return path

    def raw(self, name, limit=4 * 1024 * 1024):
        path = self.path(name)
        require(os.path.isfile(path) and os.path.getsize(path) <= limit, "Evidence file absent/over budget")
        with open(path, "rb") as source: raw = source.read(limit + 1)
        require(len(raw) <= limit and (path not in self.original or self.original[path] == raw), "Original evidence changed")
        self.original[path] = raw
        return raw

    def json(self, name):
        raw = self.raw(name)
        # Reuse strict duplicate/nonfinite JSON checks without reopening a
        # filename between hash validation and parsing.
        def pairs(values):
            result = {}
            for key, value in values:
                require(key not in result, "Duplicate evidence key")
                result[key] = value
            return result
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))

    def unchanged(self):
        for path, raw in self.original.items():
            with open(path, "rb") as source:
                require(source.read(len(raw) + 1) == raw, "Evidence changed during verification")


def request_identity(request, session, host_pid, operation=None, args=None):
    require(type(request) is dict and set(request) == {"protocol", "session", "host_pid", "id", "op", "args", "wire"} and
            request.get("protocol") == "NB2" and request.get("session") == session and request.get("host_pid") == host_pid and
            integer(host_pid, 1) and type(session) is str and SESSION.fullmatch(session) and type(request.get("id")) is str and RID.fullmatch(request["id"]) and
            request.get("op") in TYPES and type(request.get("args")) is list and all(integer(value) for value in request["args"]), "Original saved request identity invalid")
    require((operation is None or request["op"] == operation) and (args is None or request["args"] == args), "Original request operation/arguments differ")
    wire = "NB2 " + session + " " + request["id"] + " " + request["op"] + "".join(" " + str(value) for value in request["args"]) + "\n"
    require(request["wire"] == wire, "Original saved wire does not match request")


def unpack_result(value, request=None):
    if type(value) is dict and "output" in value:
        require(value.get("status") == "RECORDED_COMPLETED_NATIVE_CALL" and type(value.get("output")) is dict and
                (request is None or value.get("request") == request), "Saved MCP wrapper/request mismatch")
        return value["output"]
    require(type(value) is dict, "Parsed native result object required")
    return value


def receipt_identity(result, request, session, host_pid, threads=None):
    request_identity(request, session, host_pid)
    receipt = result.get("native_receipt", result if result.get("protocol") == "NB2" else None)
    require(type(receipt) is dict and receipt.get("protocol") == "NB2" and receipt.get("state") == "completed" and
            receipt.get("session") == session and receipt.get("host_pid") == host_pid and receipt.get("id") == request["id"] and
            receipt.get("request_id", receipt.get("id")) == request["id"] and receipt.get("original_operation") == request["op"] and
            receipt.get("normalized_args") == request["args"] and receipt.get("result_type") == TYPES[request["op"]] and
            receipt.get("result_version") == (2 if request["op"] == "ROIS" else 1), "Native receipt does not match original request/PID/session/schema")
    observed = (receipt.get("exec_tid"), receipt.get("worker_tid"))
    if request["op"] == "STOP":
        # Core acknowledges STOP on its worker without host execution. Its
        # exec_tid is exactly zero, not the STATUS/PROFILE host callback TID.
        # Keep the original worker anchor and all original request identity
        # checks; this exception applies to no scientific operation.
        require(type(threads) in (tuple, list) and len(threads) == 2 and all(integer(value, 1) for value in threads) and threads[0] != threads[1] and
                integer(observed[0], 0, 0) and integer(observed[1], 1) and observed[1] == threads[1], "STOP worker/zero-execution thread identity mismatch")
        payload = receipt.get("result") if result.get("protocol") == "NB2" else result
        require(type(payload) is dict and payload.get("ipc_stopped") is True, "STOP did not acknowledge ipc_stopped:true")
    else:
        require(all(integer(value, 1) for value in observed) and observed[0] != observed[1] and (threads is None or observed == threads), "Native execution thread mismatch")
    return observed


def expected_profile(source, source_values, args):
    """Independent integer-centre samples, both ordered endpoints included."""
    import numpy as np
    require(type(args) is list and len(args) == 9 and all(integer(v) for v in args) and args[0] == source["id"] and
            all(integer(v, 0, 0x7fffffff) for v in args[1:4]) and args[8] == 1, "Explicit line identity/width-one arguments required")
    require(type(source_values) is np.ndarray and source_values.ndim == 2 and source_values.dtype in (np.dtype("float32"), np.dtype("uint32")) and
            list(source_values.shape) == source["shape"] and 0 < source_values.size <= 65536 and np.isfinite(source_values).all(), "Bounded finite 2D source required")
    x0, y0, x1, y1 = args[4:8]; height, width = source_values.shape
    require(x0 < width and x1 < width and y0 < height and y1 < height and ((x0 == x1) != (y0 == y1)), "Only nonempty in-bounds integer horizontal/vertical lines qualify")
    count = abs(x1 - x0) + abs(y1 - y0) + 1
    require(2 <= count <= MAX_SAMPLES, "Profile sample count exceeds bound")
    step = [0 if x0 == x1 else (1 if x1 > x0 else -1), 0 if y0 == y1 else (1 if y1 > y0 else -1)]
    values = np.array([float(source_values[y0 + i * step[1], x0 + i * step[0]]) for i in range(count)], dtype="<f8")
    cal = source["calibration"]
    require(type(cal) is list and len(cal) == 2 and all(type(axis) is dict and finite(axis.get("scale")) and axis["scale"] != 0 and
            type(axis.get("unit")) is str and axis["unit"] and finite(axis.get("raw_origin")) and finite(axis.get("origin")) for axis in cal) and
            cal[0]["scale"] == cal[1]["scale"] and cal[0]["unit"] == cal[1]["unit"], "Isotropic signed spatial calibration required")
    # Native profile calibration is deliberately NOT a fabricated positive
    # distance axis and does not encode reversed line order.
    return values, step, {"origin": 0, "calibrated_value_at_pixel_zero": 0, "scale": cal[0]["scale"], "unit": cal[0]["unit"]}


def find_source_line(source, args):
    wanted = args[1:4]
    matches = []
    for display in source.get("displays", []):
        if [display.get("document_id"), display.get("display_id")] != wanted[:2]: continue
        for roi in display.get("rois", []):
            if roi.get("roi_id") == wanted[2]: matches.append(roi)
    require(len(matches) == 1 and matches[0].get("oracle_kind") == "line" and matches[0].get("rotation_degrees") == 0 and
            matches[0].get("raw_line_xyxy") == args[4:8], "Exact composite source line/geometry is not independently recorded")
    return matches[0]


def bind_source_metadata(meta, source):
    require(type(meta) is dict and meta.get("id") == source["id"] and meta.get("name") == source["name"] and meta.get("ndim") == 2 and
            meta.get("shape") == source["shape"] and meta.get("dm_dimensions") == source["shape"][::-1] and meta.get("dtype") == source["dtype"] and
            meta.get("data_type_code") == {"float32": 2, "uint32": 11}[source["dtype"]] and meta.get("packing_style") == 1, "Source native identity/dtype/rank differs")
    axes = meta.get("calibration")
    require(type(axes) is list and len(axes) == 2, "Source calibration axes absent")
    for dim, actual in enumerate(axes):
        expected = source["calibration"][dim]
        require(actual.get("dm_dimension") == dim and actual.get("numpy_axis") == 1 - dim and actual.get("size") == source["shape"][1 - dim] and
                actual.get("origin") == expected["raw_origin"] and actual.get("calibrated_value_at_pixel_zero") == expected["origin"] and
                actual.get("scale") == expected["scale"] and actual.get("unit") == expected["unit"] and actual.get("usable") is True and actual.get("issue") is None,
                "Source raw origin/physical zero/signed calibration differs")


def verify_profile_payload(result, request, source, source_values, session, host_pid, threads=None):
    import numpy as np
    request_identity(request, session, host_pid, "PROFILE")
    observed_threads = receipt_identity(result, request, session, host_pid, threads)
    args = request["args"]; expected, step, cal = expected_profile(source, source_values, args); find_source_line(source, args)
    bind_source_metadata(result.get("source"), source)
    require(result.get("backend") == "digitalmicrograph-native" and result.get("operation") == "PROFILE" and result.get("source_image_id") == source["id"] and
            integer(result.get("image_id"), 1) and result["image_id"] != source["id"], "PROFILE source/output identity mismatch")
    retention = result.get("retention")
    require(type(retention) is dict and integer(retention.get("token"), 1) and retention.get("creation_request_id") == request["id"],
            "PROFILE result retention identity differs from original creation request")
    line = result.get("source_gui_line")
    require(type(line) is dict and [line.get("document_id"), line.get("display_id"), line.get("roi_id")] == args[1:4] and
            line.get("raw_line") == dict(zip(("x0", "y0", "x1", "y1"), args[4:8])) and line.get("effective_line") == args[4:8] and
            line.get("rotation_degrees") == 0 and line.get("source_layout") == "direct_image_canonical_xy" and line.get("slice_ids") == [0] and
            line.get("coordinate_mapping") == normalized_mapping(source["shape"]), "PROFILE line identity/geometry/layout/mapping mismatch")
    shape = [len(expected)]; meta = result.get("image")
    require(type(meta) is dict and meta.get("id") == result["image_id"] and integer(meta.get("ndim"), 1, 1) and meta.get("data_type_code") == 12 and
            meta.get("dtype") == "float64" and meta.get("shape") == shape and meta.get("dm_dimensions") == shape and meta.get("packing_style") == 1 and
            meta.get("shape_order") == "one-dimensional native profile samples", "Output must be true rank-one native float64, not a row image")
    axes = meta.get("calibration")
    require(type(axes) is list and len(axes) == 1 and axes[0].get("dm_dimension") == 0 and axes[0].get("numpy_axis") == 0 and axes[0].get("size") == len(expected) and
            all(axes[0].get(key) == value for key, value in cal.items()) and axes[0].get("usable") is True and axes[0].get("issue") is None, "Output native calibration differs")
    source_intensity = source["intensity_calibration"]
    expected_intensity = {"origin": source_intensity["origin"], "scale": source_intensity["scale"], "unit": source_intensity["unit"] or None}
    require(result.get("source_intensity_calibration") == result.get("intensity_calibration") == expected_intensity and
            result.get("intensity_calibration_applied") is False and result.get("intensity_semantics") == "raw pixel intensity", "Intensity metadata copied/applied semantics differ")
    require(result.get("width") == 1 and result.get("shape") == shape and result.get("dtype") == "float64" and result.get("axes") == AXES and
            result.get("byte_order") == "little" and result.get("array_order") == "C" and result.get("data_encoding") == "base64" and
            result.get("sample_count") == len(expected) and result.get("raw_bytes") == result.get("output_bytes") == expected.nbytes and
            result.get("source_sample_start_xy") == args[4:6] and result.get("source_sample_end_xy") == args[6:8] and result.get("source_sample_step_xy") == step and
            result.get("distance_step") == abs(cal["scale"]) and result.get("distance_zero") == 0 and result.get("distance_unit") == cal["unit"] and
            result.get("calibration_complete") is True and result.get("operator") == "LiveProfile_ExtractLineProfile" and result.get("computation") == "DM native" and
            result.get("source_write_requested") is False and result.get("snapshot_atomic") is False, "PROFILE sampling/format/scientific semantics mismatch")
    encoded = result.get("values_base64")
    require(type(encoded) is str and len(encoded) <= 4 * ((MAX_SAMPLES * 8 + 2) // 3), "PROFILE encoded bytes exceed budget")
    raw = base64.b64decode(encoded, validate=True)
    require(base64.b64encode(raw).decode("ascii") == encoded and len(raw) == expected.nbytes and raw == expected.tobytes(order="C"),
            "Native profile differs from independently indexed endpoint-inclusive raw pixels")
    actual = np.frombuffer(raw, dtype="<f8")
    require(np.isfinite(actual).all(), "Nonfinite profile")
    return {"values": expected, "raw": raw, "native_calibration": cal, "threads": observed_threads,
            "image_id": result["image_id"], "source_image_id": source["id"], "sample_step_xy": step}


def verify_npy(raw, expected):
    """Header and full byte budget checked before NumPy allocation."""
    import numpy as np
    require(type(raw) is bytes and len(raw) <= MAX_SAMPLES * 8 + 4096, "NPY byte budget exceeded")
    stream = io.BytesIO(raw); version = np.lib.format.read_magic(stream)
    require(version in ((1, 0), (2, 0)), "Unsupported NPY header version")
    shape, fortran, dtype = (np.lib.format.read_array_header_1_0(stream) if version == (1, 0) else np.lib.format.read_array_header_2_0(stream))
    require(tuple(shape) == expected.shape and len(shape) == 1 and fortran is False and dtype == np.dtype("<f8") and
            stream.tell() + expected.nbytes == len(raw), "NPY must be exact bounded rank-one little-endian float64")
    require(raw[stream.tell():] == expected.tobytes(order="C"), "Saved NPY numeric bytes differ")
    values = np.load(io.BytesIO(raw), allow_pickle=False)
    require(values.ndim == 1 and values.dtype == np.dtype("<f8") and values.tobytes() == expected.tobytes(), "Independent reopened NPY differs")
    return values


def verify_package(evidence, directory, result, checked):
    prefix = directory.rstrip("/\\") + "/"
    raw = evidence.raw(prefix + "input.npy", MAX_SAMPLES * 8 + 4096)
    verify_npy(raw, checked["values"])
    info = evidence.json(prefix + "input.json"); capture = evidence.json(prefix + "capture.json")
    receipt = result["native_receipt"]; payload = dict(result); del payload["native_receipt"]
    shape = [len(checked["values"])]; capture_id = info.get("capture_id")
    require(info.get("schema_version") == 1 and type(capture_id) is str and SESSION.fullmatch(capture_id) and
            info.get("capture_mode") == "native_profile" and info.get("shape") == shape and "shape_yx" not in info and
            info.get("dtype") == "float64" and info.get("byte_order") == "little" and info.get("array_order") == "C" and info.get("axes") == AXES and
            info.get("axis_roles") == [{"numpy_axis": 0, "dm_dimension": 0, "role": "native_profile_axis"}], "Profile sidecar rank/axes/dtype invalid")
    fields = {"source_image_id": result["source_image_id"], "source_shape_yx": result["source"]["shape"],
              "source_line_xyxy": result["source_gui_line"]["effective_line"], "source_gui_line": result["source_gui_line"],
              "source_calibration_dm": result["source"]["calibration"], "profile_calibration": result["image"]["calibration"],
              "source_metadata": result["source"], "profile_metadata": result["image"], "native_profile_result": payload,
              "source_intensity_calibration": result["source_intensity_calibration"], "intensity_calibration": result["intensity_calibration"],
              "source_sample_start_xy": result["source_sample_start_xy"], "source_sample_end_xy": result["source_sample_end_xy"],
              "source_sample_step_xy": result["source_sample_step_xy"], "distance_zero": result["distance_zero"],
              "distance_step": result["distance_step"], "distance_unit": result["distance_unit"], "native_receipt": receipt,
              "native_receipt_sha256": sha(canonical(receipt)), "input_sha256": sha(raw), "input_file_bytes": len(raw),
              "raw_bytes": len(checked["raw"]), "sample_count": shape[0], "pixel_sha256": sha(checked["raw"]),
              "intensity_calibration_applied": False, "intensity_semantics": "raw pixel intensity", "width": 1,
              "computation": "DM native", "operator": result["operator"], "calibration_complete": True, "source_path_included": False,
              "input_file": "input.npy", "pixel_capture_atomic": False, "dm_file_save": False, "external_saved_response_encoding": True}
    require(all(key in info and info[key] == value for key, value in fields.items()), "Profile sidecar pixels/calibration/provenance/receipt differ")
    require(capture.get("schema_version") == 1 and capture.get("state") == "captured" and capture.get("capture_id") == capture_id and
            capture.get("capture_mode") == "native_profile" and capture.get("shape") == shape and "shape_yx" not in capture and capture.get("axes") == AXES and
            capture.get("source_image_id") == result["source_image_id"] and capture.get("source_line_xyxy") == fields["source_line_xyxy"] and
            capture.get("source_dtype") == result["source"]["dtype"] and capture.get("output_dtype") == "float64" and
            capture.get("operation") == "bounded 1D native profile capture" and capture.get("capture_backend") == "saved digitalmicrograph-native PROFILE numeric snapshot" and
            capture.get("external_saved_response_encoding") is True and
            capture.get("calibration_before") == capture.get("calibration_after") == fields["source_calibration_dm"] and
            capture.get("input_sha256") == sha(raw) and capture.get("pixel_sha256") == sha(checked["raw"]) and
            capture.get("input_metadata_sha256") == sha(canonical(info)) and capture.get("input_metadata_file_sha256") == sha(evidence.raw(prefix + "input.json")) and
            capture.get("native_session") == receipt["session"] and capture.get("native_request_id") == receipt["id"] and
            capture.get("native_receipt_sha256") == fields["native_receipt_sha256"] and capture.get("saved_snapshot_sha256") == info.get("saved_snapshot_sha256") and
            capture.get("pixel_capture_atomic") is False and capture.get("dm_file_save") is False and capture.get("live_source_reobserved") is False,
            "Profile capture receipt incomplete or bound to different data")
    return {"capture_id": capture_id, "input_sha256": sha(raw), "pixel_sha256": sha(checked["raw"]), "samples": shape[0]}


def load_context(manifest_path):
    import numpy as np
    from create_line_profile_fixture import fixed_arrays
    evidence = Evidence(os.path.dirname(os.path.abspath(manifest_path)))
    manifest = evidence.json(os.path.basename(manifest_path)); session = manifest.get("session"); host_pid = manifest.get("host_pid")
    require(manifest.get("schema") == 1 and integer(host_pid, 1) and type(session) is str and SESSION.fullmatch(session), "Manifest host/session/schema invalid")
    fixture = evidence.json(manifest.get("fixture_file", "line-profile-fixture.json"))
    require(fixture.get("status") == "RECORDED_SYNTHETIC_LINE_PROFILE_FIXTURE" and fixture.get("host_pid") == host_pid and fixture.get("session") == session and
            fixture.get("python_is_listener") is False and set(fixture.get("images", {})) == set(fixed_arrays()), "Original synthetic fixture/PID/session incomplete")
    sources = {}; ids = set()
    for label, expected in fixed_arrays().items():
        source = fixture["images"][label]
        require(integer(source.get("id"), 1) and source["id"] not in ids and source.get("dtype") == str(expected.dtype) and source.get("shape") == list(expected.shape), "Original source matrix identity/type/shape changed")
        ids.add(source["id"])
        raw = evidence.raw(source["source_file"], expected.nbytes + 4096)
        require(sha(raw) == source.get("source_file_sha256") and source.get("pixel_sha256") == sha(expected.tobytes(order="C")), "Original source/file hash mismatch")
        stream = io.BytesIO(raw); version = np.lib.format.read_magic(stream)
        require(version == (1, 0), "Fixed source requires canonical version-one NPY")
        shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
        require(tuple(shape) == expected.shape and dtype == expected.dtype and not fortran and stream.tell() + expected.nbytes == len(raw) and raw[stream.tell():] == expected.tobytes(order="C"), "Original source NPY header/values differ from independent fixed array")
        sources[label] = (source, expected)
    status_request = evidence.json(manifest["status_request_file"])
    request_identity(status_request, session, host_pid, "STATUS", [])
    status = unpack_result(evidence.json(manifest["status_result_file"]), status_request)
    threads = receipt_identity(status, status_request, session, host_pid)
    require(status.get("backend") == "digitalmicrograph-native" and status.get("ready") is True and status.get("binary_gate") is True and
            status.get("compatibility", {}).get("state") == "SUPPORTED" and status.get("host_pid") == host_pid and
            status.get("host_thread") == threads[0], "Actual status/readiness/build gate not verified")
    cases = manifest.get("cases"); require(type(cases) is list and 0 < len(cases) <= 24, "Bounded nonempty PROFILE case matrix required")
    entries = []; requests = {status_request["id"]}; outputs = set(); labels = set()
    for case in cases:
        require(type(case.get("label")) is str and case["label"] not in labels and case.get("source_label") in sources, "Unique case label and known source required")
        labels.add(case["label"]); source, values = sources[case["source_label"]]
        request = evidence.json(case["request_file"]); result = unpack_result(evidence.json(case["result_file"]), request)
        require(request.get("id") not in requests, "Operation ID reused across distinct accepted requests")
        requests.add(request["id"])
        checked = verify_profile_payload(result, request, source, values, session, host_pid, threads)
        require(checked["image_id"] not in ids | outputs, "Profile output aliases a source or earlier result")
        outputs.add(checked["image_id"])
        package = verify_package(evidence, case["capture_directory"], result, checked)
        if "rois_result_file" in case:
            saved = evidence.json(case["rois_result_file"]); rois = unpack_result(saved)
            receipt = rois["native_receipt"]
            require(receipt.get("protocol") == "NB2" and receipt.get("state") == "completed" and receipt.get("session") == session and receipt.get("host_pid") == host_pid and
                    receipt.get("original_operation") == "ROIS" and receipt.get("normalized_args") == [source["id"]] and receipt.get("result_type") == TYPES["ROIS"] and receipt.get("result_version") == 2 and
                    (receipt.get("exec_tid"), receipt.get("worker_tid")) == threads, "Saved ROIS frame identity/version mismatch")
            matching = [roi for display in rois.get("displays", []) if [display.get("document_id"), display.get("display_id")] == request["args"][1:3]
                        for roi in display.get("rois", []) if roi.get("roi_id") == request["args"][3]]
            require(len(matching) == 1 and matching[0].get("type") == "line" and matching[0].get("line") == request["args"][4:8] and
                    matching[0].get("analysis_eligible") is True and matching[0].get("issue") is None, "ROIS frame did not identify this eligible line")
        if "recovered_result_file" in case:
            recovered = unpack_result(evidence.json(case["recovered_result_file"]))
            require(recovered == result, "Recovered original PROFILE record changed")
        entries.append({"case": case, "request": request, "result": result, "checked": checked, "package": package})
    evidence.unchanged()
    return {"manifest": manifest, "fixture": fixture, "evidence": evidence, "sources": sources,
            "entries": entries, "threads": threads, "session": session, "host_pid": host_pid}


def validate_actual_host(host_pid, session):
    require(integer(host_pid, 1) and os.getpid() == host_pid and type(session) is str and SESSION.fullmatch(session) and os.environ.get("DM_NATIVE_SESSION") == session,
            "Oracle must run in the actual prepared host PID/session")


def verify_fixture_baseline(fixture_path):
    """Read-only independent post-return baseline BEFORE any MCP submission.

    No manifest or request records exist yet. A mismatch is a fixture baseline
    FAIL, never a reason to rewrite the original geometry or acceptance answer.
    The caller may save the returned report to a NEW private file; exceptions
    must likewise be preserved by its one-shot wrapper.
    """
    import numpy as np
    fixture = load(fixture_path)
    validate_actual_host(fixture.get("host_pid"), fixture.get("session"))
    import DigitalMicrograph as DM
    from create_line_profile_fixture import fixed_arrays
    from verify_gui_roi import load_fixed_source
    evidence = Evidence(os.path.dirname(os.path.abspath(fixture_path)))
    require(evidence.json(os.path.basename(fixture_path)) == fixture and
            fixture.get("status") == "RECORDED_SYNTHETIC_LINE_PROFILE_FIXTURE" and fixture.get("python_is_listener") is False and
            set(fixture.get("images", {})) == set(fixed_arrays()), "Original line fixture incomplete or changed")
    require(all_documents(DM) == fixture["documents"], "Post-return fixture document inventory differs before MCP")
    keys = {"id", "name", "dtype", "shape", "pixel_sha256", "calibration", "intensity_calibration", "displays"}
    observations = {}
    for label, expected in fixed_arrays().items():
        source = fixture["images"][label]
        require(source.get("shape") == list(expected.shape) and source.get("dtype") == str(expected.dtype) and
                source.get("pixel_sha256") == sha(expected.tobytes(order="C")), "Fixture source differs from independent fixed array")
        path = evidence.path(source["source_file"])
        load_fixed_source(path, expected, source["source_file_sha256"])
        evidence.raw(source["source_file"], expected.nbytes + 4096)
        image = raw = None
        try:
            image = DM.FindImageByID(source["id"])
            observed = image_observation(DM, image)
            require(set(observed) == keys and observed == {key: source[key] for key in keys},
                    "Post-return fixture source/name/calibration/GUI geometry differs before MCP: " + label)
            raw = image.GetNumArray()
            require(type(raw) is np.ndarray and raw.dtype == expected.dtype and raw.shape == expected.shape and
                    raw.tobytes(order="C") == expected.tobytes(order="C"), "Post-return full source pixels differ before MCP")
            observations[label] = observed
        finally: image = raw = None
    require(all_documents(DM) == fixture["documents"], "Document inventory changed during fixture baseline")
    evidence.unchanged()
    return {"schema": 1, "status": "PASS_LINE_PROFILE_FIXTURE_BASELINE", "phase": "before_any_MCP_submission",
            "host_pid": os.getpid(), "session": fixture["session"], "source_observations": observations,
            "documents": fixture["documents"], "source_pixels_calibration_names_and_GUI_unchanged": True,
            "native_operations_submitted": 0, "python_is_listener": False, "model_client_acceptance": "NOT_TESTED",
            "evidence_files_sha256": {path: sha(raw) for path, raw in evidence.original.items()}}


def verify_host(manifest_path, phase="before"):
    import numpy as np
    require(phase in ("before", "after-release", "after-stop"), "Unknown host phase")
    # Check the actual PID before importing DM, not just self-consistent saved
    # records from a different host.
    manifest = load(manifest_path); validate_actual_host(manifest.get("host_pid"), manifest.get("session"))
    import DigitalMicrograph as DM
    from create_summary_fixture import spatial, intensity
    context = load_context(manifest_path); fixture = context["fixture"]
    require(all_documents(DM) == fixture["documents"], "Unrelated/source document inventory changed")
    for source, values in context["sources"].values():
        image = raw = None
        try:
            image = DM.FindImageByID(source["id"])
            observation = image_observation(DM, image)
            for key in ("id", "name", "dtype", "shape", "pixel_sha256", "calibration", "intensity_calibration", "displays"):
                require(observation[key] == source[key], "Complete source pixel/calibration/name/display/ROI state changed: " + key)
            raw = image.GetNumArray()
            require(raw.dtype == values.dtype and raw.shape == values.shape and raw.tobytes(order="C") == values.tobytes(order="C"), "Full source array differs from independent fixture")
        finally: image = raw = None
    if phase == "after-release":
        records = context["manifest"].get("release_records")
        require(type(records) is list and len(records) == len(context["entries"]), "Original complete release request records required")
        releases = {}
        for record in records:
            request = context["evidence"].json(record["request_file"])
            result = unpack_result(context["evidence"].json(record["result_file"]), request)
            request_identity(request, context["session"], context["host_pid"], "RELEASE")
            receipt_identity(result, request, context["session"], context["host_pid"], context["threads"])
            require(len(request["args"]) == 2 and request["args"][0] not in releases and result.get("image_id") == request["args"][0] and
                    result.get("retention_token") == request["args"][1] and result.get("plugin_retained") is False and result.get("released") is True,
                    "Original release identity/state invalid")
            releases[request["args"][0]] = request["args"][1]
        require(releases == {entry["result"]["image_id"]: entry["result"]["retention"]["token"] for entry in context["entries"]}, "Release did not bind exact original creation retention tokens")
    if phase == "after-stop":
        require("stop_request_file" in context["manifest"] and "stop_result_file" in context["manifest"],
                "UNVERIFIED: original pre-submission STOP request and receipt required")
        request = context["evidence"].json(context["manifest"]["stop_request_file"])
        request_identity(request, context["session"], context["host_pid"], "STOP", [])
        receipt = unpack_result(context["evidence"].json(context["manifest"]["stop_result_file"]), request)
        receipt_identity(receipt, request, context["session"], context["host_pid"], context["threads"])
    for entry in context["entries"]:
        image = raw = None
        try:
            identifier = entry["result"]["image_id"]; image = DM.FindImageByID(identifier)
            if phase != "before":
                require(image is None or not image.IsValid(), "Unshown profile still valid after independent idle-phase release/STOP observation")
                continue
            require(image is not None and image.IsValid() and image.GetID() == identifier and image.GetDataType() == 12 and image.GetNumDimensions() == 1 and
                    image.GetDimensionSize(0) == len(entry["checked"]["values"]) and image.GetName() == entry["result"]["image"]["name"],
                    "Exact native profile output identity/name/type/rank/shape changed")
            raw = image.GetNumArray(); expected = entry["checked"]["values"]
            require(type(raw) is np.ndarray and raw.ndim == 1 and raw.shape == expected.shape and raw.dtype == np.dtype("float64") and raw.tobytes(order="C") == expected.tobytes(order="C"),
                    "Actual native output is not exact true-rank-one float64 endpoint-inclusive raw profile")
            axis = spatial(image, 0); expected_cal = entry["checked"]["native_calibration"]
            require(axis == {"dm_axis": 0, "origin": 0., "raw_origin": 0., "scale": expected_cal["scale"], "unit": expected_cal["unit"]} and
                    intensity(image) == context["sources"][entry["case"]["source_label"]][0]["intensity_calibration"], "Actual profile spatial/intensity calibration differs")
        finally: image = raw = None
    require(all_documents(DM) == fixture["documents"], "Document set changed during independent observation")
    context["evidence"].unchanged()
    return {"schema": 1, "status": "PASS_LINE_PROFILE_SAME_HOST" if phase == "before" else "PASS_LINE_PROFILE_" + phase.upper().replace("-", "_") + "_IDLE_OBSERVATION",
            "phase": phase, "host_pid": os.getpid(), "session": context["session"], "source_pixels_calibration_names_and_GUI_unchanged": True,
            "document_inventory_unchanged": True, "profile_count": len(context["entries"]), "true_rank_one_float64": True,
            "snapshot_atomic": False, "python_is_listener": False, "model_client_acceptance": "NOT_TESTED",
            "evidence_files_sha256": {path: sha(raw) for path, raw in context["evidence"].original.items()}}


def verify_files(manifest_path):
    context = load_context(manifest_path); context["evidence"].unchanged()
    return {"schema": 1, "status": "PASS_LINE_PROFILE_SAVED_FILES", "scope": "OFFLINE_SAVED_EVIDENCE_ONLY_NOT_FRESH_HOST",
            "host_pid_from_saved_evidence": context["host_pid"], "session": context["session"], "cases": [entry["package"] for entry in context["entries"]],
            "model_client_acceptance": "NOT_TESTED"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--phase", choices=("before", "after-release", "after-stop", "files"), default="before")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv); report = {"schema": 1, "status": "FAIL", "phase": args.phase}
    # Reserve a fresh report first. Never overwrite a failed old observation.
    with open(args.output, "x", encoding="utf-8") as output:
        try: report = verify_files(args.manifest) if args.phase == "files" else verify_host(args.manifest, args.phase)
        except BaseException as error: report.update(error_type=type(error).__name__, error=str(error))
        json.dump(report, output, indent=2, ensure_ascii=True, allow_nan=False); output.write("\n"); output.flush(); os.fsync(output.fileno())
    print(report["status"])
    return 0 if report["status"].startswith("PASS_") else 1


if __name__ == "__main__": raise SystemExit(main())
