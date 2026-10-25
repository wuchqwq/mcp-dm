# -*- coding: utf-8 -*-
"""Read-only same-host PROFILE/HISTOGRAM/SHOW and saved-file oracle.

Manifest schema 1: host_pid, session, fixture_file, status_request_file,
status_result_file, cases[{label,source_label,request_file,result_file,
optional capture_directory/recovered_result_file}], optional
show_records[{case_label,request_file,result_file}], release_records with the
same fields, stop_request_file and stop_result_file. Original request JSON is
persisted before first submission, never reconstructed from replies.

Call verify_baseline(fixture_path) before MCP. Call verify_measurements(manifest,
phase) in separate idle-host one-shots. This module never submits, edits, shows,
closes or waits for a native operation. Files phase makes no fresh-host claim.
"""
import argparse
import base64
import io
import json
import math
import os
import struct

import verify_line_profile as profile
from verify_gui_roi import load, all_documents, image_observation, load_fixed_source

require, integer, finite = profile.require, profile.integer, profile.finite
sha, canonical, Evidence = profile.sha, profile.canonical, profile.Evidence
TYPES = dict(profile.TYPES, HISTOGRAM="native_histogram", SHOW="image_delivery")
SOURCE_KEYS = ("id", "name", "dtype", "shape", "pixel_sha256", "calibration", "intensity_calibration", "displays")
AXIS_NUMBERS = ("axis_zero_requested", "axis_zero_observed", "axis_scale_observed", "axis_roundtrip_error", "axis_roundtrip_bound", "axis_max_coordinate_error")
AXIS_POLICY = "binary32_local_ulp_v1"
LEGACY_AXIS_POLICY = "binary32 divide/multiply round trip: 8 ulp of max(|origin|,|scale|,1)"
AXIS_REASONS = {"source_intensity_calibration_not_identity", "source_intensity_units_unavailable", "axis_entrypoint_unavailable", "binary32_axis_not_resolved"}
STYLE_SCOPE = "host line-plot presentation only; no scientific claim; reversible in the DM UI"
STYLE_REASONS = {"style_entrypoints_unavailable", "display_resolution_unavailable", "document_has_no_display", "display_count_over_budget",
                 "display_holder_missing", "display_is_not_a_line_plot", "style_flag_did_not_read_back", "display_for_image_not_found", "style_not_qualified"}


def binary32(value):
    try: return struct.unpack("<f", struct.pack("<f", value))[0]
    except OverflowError: return math.copysign(float("inf"), value)


def local_binary32_ulp(value):
    """Exact adjacent-value spacing from IEEE bit patterns, not a unit floor."""
    require(finite(value) and binary32(value) == value, "Finite binary32 value required for local spacing")
    value = abs(value)
    if value == 0: return 2. ** -149
    bits = struct.unpack("<I", struct.pack("<f", value))[0]
    lower = struct.unpack("<f", struct.pack("<I", bits - 1))[0]
    higher = struct.unpack("<f", struct.pack("<I", bits + 1))[0]
    require(math.isfinite(higher), "Adjacent binary32 value is not finite; axis resolution is unqualified")
    return max(value - lower, higher - value)


def histogram_axis_plan(requested, bins):
    """Predeclared binary32 write/read arithmetic, independently bit-derived.

    This oracle predicts the index origin and physical-zero readback exactly;
    a reported tolerance cannot excuse a different native axis or data values.
    """
    width = (requested[1] - requested[0]) / bins
    stored_width = binary32(width)
    require(math.isfinite(stored_width) and stored_width >= 2. ** -126, "Histogram axis scale is not positive normal binary32")
    quotient = binary32(requested[0] / stored_width)
    reconstructed = binary32(quotient * stored_width)
    require(all(math.isfinite(v) and (v == 0 or abs(v) >= 2. ** -126) for v in (quotient, reconstructed)),
            "Histogram axis quotient/zero is nonfinite or subnormal")
    require(requested[0] == 0 or quotient != 0 and reconstructed != 0, "Nonzero histogram axis origin underflows its native representation")
    bound = local_binary32_ulp(quotient) * abs(stored_width) + local_binary32_ulp(reconstructed)
    grid_drift = abs(stored_width - width) * (bins - 1)
    maximum_error = bound + grid_drift
    require(math.isfinite(maximum_error) and maximum_error < width / 4., "Histogram native-axis error budget is unsafe relative to bin width")
    return {"zero_requested": requested[0], "zero_observed": reconstructed, "raw_origin": -quotient, "scale_observed": stored_width,
            "roundtrip_error": abs(reconstructed - requested[0]), "roundtrip_bound": bound,
            "max_coordinate_error": maximum_error, "grid_drift": grid_drift}


def verify_histogram_axis(result, source, requested, bins):
    meta = result["image"]; axes = meta.get("calibration")
    require(type(axes) is list and len(axes) == 1 and axes[0].get("dm_dimension") == axes[0].get("numpy_axis") == 0 and axes[0].get("size") == bins,
            "Histogram axis identity/rank differs")
    axis = axes[0]; mode = result.get("axis_mode")
    require(all(finite(axis.get(key)) for key in ("origin", "calibrated_value_at_pixel_zero", "scale")), "Native histogram axis numbers must be finite, not booleans")
    has_context = any(key in result for key in AXIS_NUMBERS + ("axis_tolerance", "axis_unavailable_reason"))
    if mode == "bin_index":
        require(meta.get("calibration_complete") is False and result.get("axis_calibration_is_bin_left_edge") is False and
                axis.get("origin") == axis.get("calibrated_value_at_pixel_zero") == 0 and axis.get("scale") == 1 and
                axis.get("unit") is None and axis.get("usable") is False and axis.get("issue") == "unknown_units",
                "Histogram native bin index must remain uncalibrated, not a fabricated intensity axis")
        if has_context:
            if result.get("axis_tolerance") == LEGACY_AXIS_POLICY:
                require(all(key in result and finite(result[key]) and result[key] == 0 for key in AXIS_NUMBERS[:4]) and
                        not any(key in result for key in AXIS_NUMBERS[4:] + ("axis_unavailable_reason",)),
                        "Historical bin-index diagnostics cannot assert a physical axis or new numeric bounds")
            else:
                require(all(key in result and result[key] is None for key in AXIS_NUMBERS) and result.get("axis_tolerance") == AXIS_POLICY and
                        result.get("axis_unavailable_reason") in AXIS_REASONS,
                        "Unavailable histogram axis must carry complete null numeric evidence and a known reason")
                intensity = source["intensity_calibration"]
                reason = result["axis_unavailable_reason"]
                if intensity.get("origin") != 0 or intensity.get("scale") != 1:
                    require(reason == "source_intensity_calibration_not_identity", "Histogram axis fallback reason hides nonidentity intensity calibration")
                elif not intensity.get("unit"):
                    require(reason == "source_intensity_units_unavailable", "Histogram axis fallback reason invents source units")
                else:
                    require(reason in ("axis_entrypoint_unavailable", "binary32_axis_not_resolved"), "Histogram axis fallback reason contradicts identity source calibration")
                    if reason == "binary32_axis_not_resolved":
                        try: histogram_axis_plan(requested, bins)
                        except ValueError: pass
                        else: raise ValueError("Histogram axis claims unresolved arithmetic despite a safe independently derived plan")
        return {"mode": mode, "context_present": has_context, "calibration": axis}
    require(mode == "source_intensity_units", "Unknown native histogram axis mode")
    intensity = source["intensity_calibration"]
    require(finite(intensity.get("origin")) and finite(intensity.get("scale")) and intensity["origin"] == 0 and intensity["scale"] == 1 and type(intensity.get("unit")) is str and intensity["unit"],
            "Raw histogram bins cannot be labelled with nonidentity source intensity units")
    plan = histogram_axis_plan(requested, bins)
    expected = {"origin": plan["raw_origin"], "calibrated_value_at_pixel_zero": plan["zero_observed"], "scale": plan["scale_observed"],
                "unit": intensity["unit"], "usable": True, "issue": None}
    require(meta.get("calibration_complete") is True and result.get("axis_calibration_is_bin_left_edge") is True and
            all(axis.get(key) == value for key, value in expected.items()), "Histogram native axis differs from independent binary32 divide/multiply reconstruction")
    fields = {"axis_zero_requested": plan["zero_requested"], "axis_zero_observed": plan["zero_observed"], "axis_scale_observed": plan["scale_observed"],
              "axis_roundtrip_error": plan["roundtrip_error"], "axis_roundtrip_bound": plan["roundtrip_bound"], "axis_max_coordinate_error": plan["max_coordinate_error"],
              "axis_tolerance": AXIS_POLICY, "axis_unavailable_reason": None}
    require(all(finite(result.get(key)) for key in AXIS_NUMBERS) and all(key in result and result[key] == value for key, value in fields.items()),
            "Histogram requested/observed axis, local ULP policy or numeric bound differs")
    require(plan["roundtrip_error"] <= plan["roundtrip_bound"], "Native zero roundtrip exceeds predeclared local bound")
    return {"mode": mode, "context_present": True, "calibration": axis, "expected": plan}


def histogram_axis_context(creation):
    keys = ("axis_mode", "requested_range", "bins", "bin_width", "bin_left_edge", "source_intensity_calibration", "axis_calibration_is_bin_left_edge") + AXIS_NUMBERS + ("axis_tolerance", "axis_unavailable_reason")
    return {key: creation[key] for key in keys if key in creation}


def verify_show_style(result):
    keys = ("display_style", "display_style_scope", "display_style_reason")
    if not any(key in result for key in keys): return None
    require(result.get("retained_operation") == "HISTOGRAM" and result.get("display_style") in ("histogram", "default") and
            result.get("display_style_scope") == STYLE_SCOPE, "Unqualified/mislabelled 1D presentation style")
    if result["display_style"] == "histogram": require("display_style_reason" not in result, "Successful histogram style cannot carry a fallback reason")
    else: require(result.get("display_style_reason") in STYLE_REASONS, "Unknown/missing default-style fallback reason")
    return {key: result[key] for key in keys if key in result}


def request_identity(request, session, host_pid, operation=None, args=None):
    require(type(request) is dict and set(request) == {"protocol", "session", "host_pid", "id", "op", "args", "wire"} and
            request.get("protocol") == "NB2" and request.get("session") == session and request.get("host_pid") == host_pid and
            integer(host_pid, 1) and type(session) is str and profile.SESSION.fullmatch(session) and
            type(request.get("id")) is str and profile.RID.fullmatch(request["id"]) and
            request.get("op") in TYPES and type(request.get("args")) is list and all(integer(v) for v in request["args"]),
            "Original saved request identity invalid")
    require((operation is None or request["op"] == operation) and (args is None or request["args"] == args), "Original request operation/arguments differ")
    expected = "NB2 " + session + " " + request["id"] + " " + request["op"] + "".join(" " + str(v) for v in request["args"]) + "\n"
    require(request["wire"] == expected, "Original saved wire differs")


def receipt_identity(result, request, session, host_pid, threads=None):
    request_identity(request, session, host_pid)
    if request["op"] in profile.TYPES:
        return profile.receipt_identity(result, request, session, host_pid, threads)
    receipt = result.get("native_receipt")
    require(type(receipt) is dict and receipt.get("protocol") == "NB2" and receipt.get("state") == "completed" and
            receipt.get("session") == session and receipt.get("host_pid") == host_pid and receipt.get("id") == request["id"] and
            receipt.get("request_id") == request["id"] and receipt.get("original_operation") == request["op"] and
            receipt.get("normalized_args") == request["args"] and receipt.get("result_type") == TYPES[request["op"]] and
            type(receipt.get("result_version")) is int and receipt["result_version"] == 1,
            "Native receipt differs from original request/PID/session/schema")
    observed = (receipt.get("exec_tid"), receipt.get("worker_tid"))
    require(all(integer(v, 1) for v in observed) and observed[0] != observed[1] and (threads is None or observed == threads),
            "Native execution thread mismatch")
    return observed


def expected_histogram(source_values, args):
    """Independent NumPy oracle only, never part of a bridge operation."""
    import numpy as np
    require(type(args) is list and len(args) == 4 and all(integer(v) for v in args) and 2 <= args[1] <= 4096,
            "Explicit HISTOGRAM source/bins/binary32 range required")
    require(type(source_values) is np.ndarray and source_values.ndim == 2 and source_values.dtype == np.dtype("float32") and
            0 < source_values.size <= 1536 and np.isfinite(source_values).all(), "Bounded finite float32 source required")
    lower, upper = (struct.unpack("<f", struct.pack("<I", v))[0] for v in args[2:])
    require(math.isfinite(lower) and math.isfinite(upper) and lower < upper and
            lower <= float(source_values.min()) <= float(source_values.max()) <= upper, "Complete finite caller range required")
    # Predeclared expected edge semantics: interior [left,right), final upper
    # boundary included. A live DM disagreement stays FAIL, not a changed oracle.
    counts, edges = np.histogram(source_values.astype(np.float64), bins=args[1], range=(lower, upper))
    require(int(counts.sum()) == source_values.size, "Independent count total differs")
    return counts.astype("<u4"), edges, [lower, upper]


def verify_histogram_payload(result, request, source, values, session, host_pid, threads=None):
    import numpy as np
    request_identity(request, session, host_pid, "HISTOGRAM")
    observed = receipt_identity(result, request, session, host_pid, threads)
    args = request["args"]
    expected, edges, requested = expected_histogram(values, args)
    bins = len(expected)
    require(args[0] == source["id"] and result.get("backend") == "digitalmicrograph-native" and result.get("operation") == "HISTOGRAM" and
            result.get("source_image_id") == source["id"] and integer(result.get("image_id"), 1) and result["image_id"] != source["id"],
            "HISTOGRAM source/output identity differs")
    profile.bind_source_metadata(result.get("source"), source)
    retention = result.get("retention")
    require(type(retention) is dict and set(retention) == {"token", "creation_request_id", "state_at_creation", "identity_scope"} and
            integer(retention.get("token"), 1) and retention.get("creation_request_id") == request["id"] and
            retention.get("state_at_creation") == "plugin_retained" and retention.get("identity_scope") == "bridge token in this native session, not a host image ID",
            "HISTOGRAM retention token/creation identity differs")
    meta = result.get("image")
    require(type(meta) is dict and meta.get("id") == result["image_id"] and meta.get("ndim") == 1 and
            meta.get("dtype") == "uint32" and meta.get("data_type_code") == 11 and meta.get("is_integer") is True and meta.get("is_unsigned") is True and meta.get("packing_style") == 1 and
            meta.get("shape") == meta.get("dm_dimensions") == [bins] and
            meta.get("shape_order") == "one-dimensional native histogram bins", "Native histogram must be true 1D uint32 counts")
    axis_checked = verify_histogram_axis(result, source, requested, bins)
    fields = {"source_pixels": int(values.size), "source_min": float(values.min()), "source_max": float(values.max()),
              "requested_range": requested, "range_covers_source": True, "bins": bins, "bin_width": (requested[1] - requested[0]) / bins,
              "bin_left_edge": requested[0], "counts_sum": int(values.size), "counts_complete": True, "shape": [bins], "dtype": "uint32",
              "axes": ["intensity_bin"], "counts_encoding": "exact uint32 counts little-endian binary64 payload",
              "raw_bytes": bins * 8, "output_bytes": bins * 4,
              "operator": "GMSImageProcessing::CalcHistogram", "computation": "DM native", "source_write_requested": False,
              "snapshot_atomic": False, "intensity_calibration_applied": False, "intensity_semantics": "raw pixel intensity counts per bin"}
    require(all(key in result and result[key] == value for key, value in fields.items()), "Histogram bin/count/dtype/axis/scientific semantics differ")
    require(result.get("source_intensity_calibration") == source["intensity_calibration"], "Source intensity calibration context differs")
    require(result.get("binning") == "uniform linear bins over the caller range; the range must cover the complete native source minimum/maximum" and
            result.get("bin_edge_rule") == "left edge at range_min, width = (max-min)/bins", "Histogram declared bin geometry differs")
    encoded = result.get("values_base64")
    require(type(encoded) is str and len(encoded) <= 4 * ((4096 * 8 + 2) // 3), "Histogram wire payload over budget")
    raw = base64.b64decode(encoded, validate=True)
    require(base64.b64encode(raw).decode("ascii") == encoded and len(raw) == bins * 8, "Histogram canonical binary64 payload required")
    counts = np.frombuffer(raw, dtype="<f8")
    require(np.isfinite(counts).all() and (counts >= 0).all() and (counts <= values.size).all() and
            np.equal(counts, np.floor(counts)).all() and np.array_equal(counts, expected.astype(np.float64)),
            "Native histogram disagrees with independent exact-edge count oracle")
    return {"values": expected, "raw": expected.tobytes(), "wire_raw": raw, "edges": edges, "threads": observed,
            "image_id": result["image_id"], "source_image_id": source["id"], "native_calibration": axis_checked["calibration"], "axis_checked": axis_checked}


def verify_show_payload(result, request, creation, session, host_pid, threads):
    request_identity(request, session, host_pid, "SHOW", [creation["image_id"]])
    receipt_identity(result, request, session, host_pid, threads)
    require(result.get("backend") == "digitalmicrograph-native" and result.get("image_id") == creation["image_id"] and
            result.get("delivery") == "visible_dm_document" and result.get("document_visible") is True and
            result.get("rank") == 1 and result.get("display_family") == "native_1d_image_document" and result.get("display_class") == "host_selected" and
            result.get("retained_operation") == creation["operation"] and result.get("one_dimensional_display") == creation["image"] and "image" not in result and
            result.get("operator") == "ImageGetOrCreateImageDocument + ImageDocumentShow" and result.get("source_write_requested") is False and
            result.get("snapshot_atomic") is False and result.get("file_saved") is False and result.get("model_visual_verification") is False,
            "1D SHOW identity/descriptor/delivery contract differs")
    if creation["operation"] == "HISTOGRAM":
        context = histogram_axis_context(creation)
        if "histogram_axis_context" in result or creation["axis_mode"] == "source_intensity_units" or all(key in creation for key in AXIS_NUMBERS):
            require(result.get("histogram_axis_context") == context, "SHOW histogram axis context differs from original creation record")
    else: require("histogram_axis_context" not in result, "PROFILE cannot acquire a histogram scientific context")
    verify_show_style(result)


def observe_show_style(DM, display, show_result):
    expected = verify_show_style(show_result)
    if expected is None: return {"status": "NOT_REQUESTED", "scope": "no style claim in the original SHOW receipt"}
    if expected["display_style"] == "default":
        return {"status": "NOT_APPLIED", "reason": expected["display_style_reason"], "current_flag": "NOT_INFERRED"}
    getter = getattr(DM, "LinePlotImageDisplayGetHistogramStyle", None)
    require(callable(getter), "UNVERIFIED: independent documented Python histogram-style getter unavailable")
    observed = getter(display)
    require(type(observed) is bool and observed is True, "Native SHOW histogram-style claim differs from independent host getter")
    return {"status": "PASS_INDEPENDENT_STYLE_GETTER", "getter": "DigitalMicrograph.LinePlotImageDisplayGetHistogramStyle", "observed": observed}


def verify_native_npy(raw, expected):
    import numpy as np
    require(type(raw) is bytes and len(raw) <= 4096 * 8 + 4096, "NPY byte budget exceeded")
    stream = io.BytesIO(raw); version = np.lib.format.read_magic(stream)
    require(version in ((1, 0), (2, 0)), "Unsupported NPY version")
    shape, fortran, dtype = (np.lib.format.read_array_header_1_0(stream) if version == (1, 0) else np.lib.format.read_array_header_2_0(stream))
    require(tuple(shape) == expected.shape and len(shape) == 1 and fortran is False and dtype == expected.dtype and
            stream.tell() + expected.nbytes == len(raw) and raw[stream.tell():] == expected.tobytes(), "NPY must preserve exact native rank-one dtype/count bytes")
    actual = np.load(io.BytesIO(raw), allow_pickle=False)
    require(actual.dtype == expected.dtype and actual.shape == expected.shape and actual.tobytes() == expected.tobytes(), "Reopened NPY differs")
    return actual


def verify_histogram_package(evidence, directory, result, checked):
    prefix = directory.rstrip("/\\") + "/"
    raw = evidence.raw(prefix + "input.npy", 4096 * 4 + 4096)
    verify_native_npy(raw, checked["values"])
    info = evidence.json(prefix + "input.json"); capture = evidence.json(prefix + "capture.json")
    receipt = result["native_receipt"]; payload = dict(result); del payload["native_receipt"]
    cid = info.get("capture_id"); bins = len(checked["values"])
    require(type(cid) is str and profile.SESSION.fullmatch(cid), "Histogram capture identity invalid")
    role = "intensity_bin" if result["axis_mode"] == "source_intensity_units" else "bin_index"
    fields = {"schema_version": 1, "capture_mode": "native_histogram", "shape": [bins], "dtype": "uint32", "native_storage_dtype": "uint32",
              "axes": [role], "axis_roles": [{"numpy_axis": 0, "dm_dimension": 0, "role": role}],
              "byte_order": "little", "array_order": "C", "source_image_id": result["source_image_id"], "source_shape_yx": result["source"]["shape"],
              "source_metadata": result["source"], "source_calibration_dm": result["source"]["calibration"], "histogram_metadata": result["image"],
              "histogram_calibration": result["image"]["calibration"], "source_intensity_calibration": result["source_intensity_calibration"],
              "native_histogram_result": payload, "native_receipt": receipt, "native_receipt_sha256": sha(canonical(receipt)),
              "input_file": "input.npy", "input_sha256": sha(raw), "input_file_bytes": len(raw), "pixel_sha256": sha(checked["raw"]),
              "raw_bytes": bins * 4, "native_storage_bytes": bins * 4, "wire_raw_bytes": bins * 8,
              "wire_scalar_dtype": "float64", "wire_byte_order": "little", "wire_encoding": result["counts_encoding"], "wire_values_sha256": sha(checked["wire_raw"]),
              "calibration_complete": result["image"]["calibration_complete"], "intensity_calibration_applied": False, "external_saved_response_encoding": True,
              "dm_file_save": False, "pixel_capture_atomic": False}
    for key in ("requested_range", "bin_left_edge", "bin_width", "binning", "bin_edge_rule", "source_min", "source_max", "source_pixels", "counts_sum", "counts_complete", "axis_mode", "axis_calibration_is_bin_left_edge"):
        fields[key] = result[key]
    for key in AXIS_NUMBERS + ("axis_tolerance", "axis_unavailable_reason"):
        if key in result: fields[key] = result[key]
        else: require(key not in info, "Sidecar fabricated axis evidence absent from the original histogram result")
    require("shape_yx" not in info and all(key in info and info[key] == value for key, value in fields.items()),
            "Histogram sidecar changed counts/bin geometry/native-vs-wire dtype/provenance")
    require(capture.get("schema_version") == 1 and capture.get("capture_id") == cid and capture.get("state") == "captured" and
            capture.get("capture_mode") == "native_histogram" and capture.get("shape") == [bins] and capture.get("axes") == [role] and
            capture.get("source_image_id") == result["source_image_id"] and capture.get("source_dtype") == "float32" and capture.get("output_dtype") == "uint32" and
            capture.get("input_sha256") == sha(raw) and capture.get("pixel_sha256") == sha(checked["raw"]) and
            capture.get("input_metadata_sha256") == sha(canonical(info)) and capture.get("input_metadata_file_sha256") == sha(evidence.raw(prefix + "input.json")) and
            capture.get("native_session") == receipt["session"] and capture.get("native_request_id") == receipt["id"] and
            capture.get("native_receipt_sha256") == fields["native_receipt_sha256"] and capture.get("external_saved_response_encoding") is True and
            capture.get("dm_file_save") is False and capture.get("live_source_reobserved") is False,
            "Histogram capture manifest differs from original numeric/receipt identity")
    return {"capture_id": cid, "input_sha256": sha(raw), "pixel_sha256": sha(checked["raw"]), "bins": bins, "dtype": "uint32"}


def source_context(fixture_path):
    from create_measurement_fixture import fixed_arrays, source_intensity
    evidence = Evidence(os.path.dirname(os.path.abspath(fixture_path)))
    fixture = evidence.json(os.path.basename(fixture_path))
    require(fixture.get("schema") == 1 and fixture.get("status") == "RECORDED_SYNTHETIC_NATIVE_MEASUREMENT_FIXTURE" and
            fixture.get("python_is_listener") is False and integer(fixture.get("host_pid"), 1) and
            type(fixture.get("session")) is str and profile.SESSION.fullmatch(fixture["session"]) and
            (set(fixture.get("images", {})) == set(fixed_arrays()) if fixture.get("fixture_revision") == 2 else
             set(fixture.get("images", {})) in ({"float_edges", "uint32_high"}, set(fixed_arrays()))), "Original synthetic measurement fixture incomplete")
    sources = {}; ids = set()
    for label, expected in fixed_arrays().items():
        if label not in fixture["images"]: continue  # Historical two-source fixture is immutable evidence.
        source = fixture["images"][label]
        require(integer(source.get("id"), 1) and source["id"] not in ids and source.get("shape") == list(expected.shape) and
                source.get("dtype") == str(expected.dtype) and source.get("pixel_sha256") == sha(expected.tobytes()), "Source fixed identity/type/shape/pixels differ")
        scale = -.25 if label == "float_edges" else .25
        expected_calibration = [{"dm_axis": dimension, "origin": zero, "raw_origin": -zero / scale, "scale": scale, "unit": "nm"}
                                for dimension, zero in enumerate((1.25, -2.5))]
        require(source.get("intensity_calibration") == source_intensity(label) and source.get("calibration") == expected_calibration,
                "Source fixture intensity/spatial calibration differs from independent preparation contract")
        ids.add(source["id"])
        load_fixed_source(evidence.path(source["source_file"]), expected, source["source_file_sha256"])
        require(sha(evidence.raw(source["source_file"], expected.nbytes + 4096)) == source["source_file_sha256"], "Source NPY changed while loading evidence")
        sources[label] = (source, expected)
    return evidence, fixture, sources


def observe_sources(DM, fixture, sources):
    import numpy as np
    observed = {}
    for label, (source, values) in sources.items():
        image = raw = None
        try:
            image = DM.FindImageByID(source["id"])
            snapshot = image_observation(DM, image)
            require(snapshot == {key: source[key] for key in SOURCE_KEYS}, "Source name/pixels/calibration/GUI state changed: " + label)
            raw = image.GetNumArray()
            require(type(raw) is np.ndarray and raw.shape == values.shape and raw.dtype == values.dtype and raw.tobytes() == values.tobytes(), "Full source numeric bytes changed")
            observed[label] = snapshot
        finally: image = raw = None
    return observed


def verify_baseline(fixture_path):
    fixture = load(fixture_path)
    profile.validate_actual_host(fixture.get("host_pid"), fixture.get("session"))
    import DigitalMicrograph as DM
    evidence, fixture, sources = source_context(fixture_path)
    require(all_documents(DM) == fixture["documents"], "Fixture documents changed before MCP")
    observations = observe_sources(DM, fixture, sources)
    require(all_documents(DM) == fixture["documents"], "Fixture documents changed during baseline")
    evidence.unchanged()
    return {"schema": 1, "status": "PASS_NATIVE_MEASUREMENT_FIXTURE_BASELINE", "host_pid": os.getpid(), "session": fixture["session"],
            "native_operations_submitted": 0, "python_is_listener": False, "roi_creation": fixture["roi_creation"], "sources": observations,
            "baseline_scope": fixture.get("baseline_scope", "before_any_MCP_submission")}


def verify_manual_additions(original, current):
    """Added ROIs, selection flags and explicit user viewport size may differ.

    Viewport preparation does not alter scientific coordinates; the manual
    freeze records old/new sizes separately and later observations are strict.
    """
    require(all(current.get(key) == original.get(key) for key in SOURCE_KEYS if key != "displays"),
            "Manual selection changed source pixels/name/dtype/shape/calibration")
    before = {(row["document_id"], row["display_id"]): row for row in original["displays"]}
    after = {(row["document_id"], row["display_id"]): row for row in current["displays"]}
    require(len(before) == len(original["displays"]) and len(after) == len(current["displays"]) and set(before) == set(after),
            "Manual selection changed source document/display identity")
    additions = []
    for key, old_display in before.items():
        new_display = after[key]
        require({name: value for name, value in old_display.items() if name not in ("rois", "window_content_size")} ==
                {name: value for name, value in new_display.items() if name not in ("rois", "window_content_size")}, "Manual selection changed source display context")
        for size in (old_display.get("window_content_size"), new_display.get("window_content_size")):
            require(size is None or type(size) is list and len(size) == 2 and all(integer(v, 1, 32768) for v in size), "Manual viewport size observation invalid")
        old_rois = {roi["roi_id"]: roi for roi in old_display["rois"]}
        new_rois = {roi["roi_id"]: roi for roi in new_display["rois"]}
        require(len(old_rois) == len(old_display["rois"]) and len(new_rois) == len(new_display["rois"]) and set(old_rois) <= set(new_rois),
                "Manual selection removed/replaced an existing ROI")
        for identifier, old_roi in old_rois.items():
            require({name: value for name, value in old_roi.items() if name != "selected"} ==
                    {name: value for name, value in new_rois[identifier].items() if name != "selected"},
                    "Manual selection edited pre-existing ROI geometry/identity")
        for identifier in sorted(set(new_rois) - set(old_rois)):
            roi = new_rois[identifier]
            require(roi.get("oracle_kind") in ("line", "rectangle") and roi.get("rotation_degrees") == 0,
                    "Only an explicit unrotated manual line/rectangle is admitted as a new baseline")
            additions.append({"document_id": key[0], "display_id": key[1], "roi": roi})
    return additions


def freeze_manual_baseline(original_fixture_path, new_path, verified_previous_report_path=None):
    """Explicit read-only freeze of intentional user-added GUI selections.

    Never overwrites the original fixture or relaxes source/old-ROI invariants.
    If native result windows already exist, the previous successful same-host
    oracle report must bind their exact inventory. This is before processing
    the NEW manual ROI, not retroactive proof of the earlier API fixture.
    """
    original_fixture_path = os.path.abspath(original_fixture_path)
    new_path = os.path.abspath(new_path)
    require(os.path.dirname(new_path) == os.path.dirname(original_fixture_path) and new_path != original_fixture_path,
            "New manual baseline must be a distinct file beside the original fixture")
    fixture = load(original_fixture_path)
    profile.validate_actual_host(fixture.get("host_pid"), fixture.get("session"))
    import DigitalMicrograph as DM
    evidence, fixture, sources = source_context(original_fixture_path)
    previous_documents = fixture["documents"]
    previous_hash = None
    if verified_previous_report_path is not None:
        verified_previous_report_path = os.path.abspath(verified_previous_report_path)
        require(os.path.dirname(verified_previous_report_path) == evidence.directory, "Previous host observation must stay beside the original evidence")
        previous_name = os.path.basename(verified_previous_report_path)
        previous = evidence.json(previous_name)
        previous_hash = sha(evidence.raw(previous_name))
        require(type(previous.get("status")) is str and previous["status"].startswith("PASS_NATIVE_MEASUREMENT_") and
                previous.get("host_pid") == os.getpid() and previous.get("session") == fixture["session"] and
                previous.get("source_pixels_calibration_names_and_GUI_unchanged") is True and previous.get("source_documents_unchanged") is True and
                type(previous.get("document_inventory")) is list, "Previous successful same-host source/document observation required")
        previous_documents = previous["document_inventory"]
    documents = all_documents(DM)
    before = {row["document_id"]: row for row in previous_documents}
    after = {row["document_id"]: row for row in documents}
    source_ids = {source["id"] for source, values in sources.values()}
    require(len(before) == len(previous_documents) and len(after) == len(documents) and set(before) == set(after),
            "Manual baseline changed document inventory")
    for identifier, row in before.items():
        old = {key: value for key, value in row.items() if key != "lookup_signature"}
        new = {key: value for key, value in after[identifier].items() if key != "lookup_signature"}
        require(old == new and (set(row["image_ids"]) & source_ids or after[identifier] == row),
                "Manual baseline changed unrelated documents or source ownership")
    updated = dict(fixture); updated["images"] = {}; additions = []; viewport_changes = []
    for label, (source, values) in sources.items():
        image = raw = None
        try:
            image = DM.FindImageByID(source["id"])
            observation = image_observation(DM, image)
            changed = verify_manual_additions(source, observation)
            additions.extend(dict(row, source_label=label, source_image_id=source["id"]) for row in changed)
            old_displays = {(row["document_id"], row["display_id"]): row for row in source["displays"]}
            for row in observation["displays"]:
                old_size = old_displays[(row["document_id"], row["display_id"])].get("window_content_size")
                if old_size != row.get("window_content_size"):
                    viewport_changes.append({"source_label": label, "source_image_id": source["id"], "document_id": row["document_id"],
                                             "display_id": row["display_id"], "old_window_content_size": old_size,
                                             "new_window_content_size": row.get("window_content_size"), "source": "explicit_user_viewport_preparation"})
            raw = image.GetNumArray()
            require(raw.dtype == values.dtype and raw.shape == values.shape and raw.tobytes() == values.tobytes(), "Manual baseline source numeric bytes changed")
            updated["images"][label] = dict(source, **observation)
        finally: image = raw = None
    require(additions, "No new user-drawn ROI was observed; do not invent a manual baseline")
    require(all_documents(DM) == documents, "Documents changed during manual baseline freeze")
    evidence.unchanged()
    updated.update(documents=documents, roi_creation="user_manual_new_GUI_ROI_baseline", baseline_scope="before_processing_new_manual_ROI",
                   manual_gui_baseline={"source_of_roi": "user_manual", "original_fixture_file": os.path.basename(original_fixture_path),
                                        "original_fixture_sha256": sha(evidence.raw(os.path.basename(original_fixture_path))), "added_rois": additions,
                                        "viewport_changes": viewport_changes,
                                        "source_pixels_name_calibration_and_existing_ROIs_unchanged": True,
                                        "previous_observation_file": os.path.basename(verified_previous_report_path) if verified_previous_report_path else None,
                                        "previous_observation_sha256": previous_hash})
    with open(new_path, "x", encoding="utf-8") as output:
        json.dump(updated, output, ensure_ascii=True, indent=2, allow_nan=False)
        output.write("\n"); output.flush(); os.fsync(output.fileno())
    return updated


def load_context(manifest_path):
    directory = os.path.dirname(os.path.abspath(manifest_path)); evidence = Evidence(directory)
    manifest = evidence.json(os.path.basename(manifest_path))
    require(manifest.get("schema") == 1, "Manifest schema invalid")
    host_pid, session = manifest.get("host_pid"), manifest.get("session")
    _, fixture, sources = source_context(evidence.path(manifest["fixture_file"]))
    require(host_pid == fixture["host_pid"] and session == fixture["session"], "Manifest fixture host/session differ")
    # Read and hash the fixture/source files through this same evidence owner.
    evidence.raw(manifest["fixture_file"])
    for source, values in sources.values(): evidence.raw(source["source_file"], values.nbytes + 4096)
    status_request = evidence.json(manifest["status_request_file"])
    request_identity(status_request, session, host_pid, "STATUS", [])
    status = profile.unpack_result(evidence.json(manifest["status_result_file"]), status_request)
    threads = receipt_identity(status, status_request, session, host_pid)
    require(status.get("backend") == "digitalmicrograph-native" and status.get("ready") is True and status.get("binary_gate") is True and
            status.get("compatibility", {}).get("state") == "SUPPORTED" and status.get("host_pid") == host_pid and status.get("host_thread") == threads[0],
            "Actual native status/build gate not verified")
    cases = manifest.get("cases")
    require(type(cases) is list and 0 < len(cases) <= 16, "Bounded measurement cases required")
    ids = {source["id"] for source, values in sources.values()}; requests = {status_request["id"]}; entries = {}
    for case in cases:
        label = case.get("label")
        require(type(label) is str and label and label not in entries and case.get("source_label") in sources, "Unique known source case required")
        source, values = sources[case["source_label"]]
        request = evidence.json(case["request_file"])
        require(request.get("id") not in requests, "Distinct original operation IDs required")
        requests.add(request["id"])
        result = profile.unpack_result(evidence.json(case["result_file"]), request)
        require(request.get("op") in ("PROFILE", "HISTOGRAM"), "Only PROFILE/HISTOGRAM measurement cases admitted")
        checked = (profile.verify_profile_payload if request["op"] == "PROFILE" else verify_histogram_payload)(result, request, source, values, session, host_pid, threads)
        require(checked["image_id"] not in ids, "New result aliases source or earlier result")
        ids.add(checked["image_id"])
        package = None
        if "capture_directory" in case:
            package = (profile.verify_package if request["op"] == "PROFILE" else verify_histogram_package)(evidence, case["capture_directory"], result, checked)
        if "recovered_result_file" in case:
            require(profile.unpack_result(evidence.json(case["recovered_result_file"])) == result, "Original recovered record changed/recreated")
        entries[label] = {"case": case, "request": request, "result": result, "checked": checked, "package": package}
    shown = set(); released = set(); show_results = {}
    for field, operation in (("show_records", "SHOW"), ("release_records", "RELEASE")):
        records = manifest.get(field, [])
        require(type(records) is list and len(records) <= 32, "Bounded display/release records required")
        for record in records:
            require(record.get("case_label") in entries, "Display/release original case missing")
            entry = entries[record["case_label"]]; creation = entry["result"]
            request = evidence.json(record["request_file"])
            require(request.get("id") not in requests, "Display/release original ID reused")
            requests.add(request["id"])
            result = profile.unpack_result(evidence.json(record["result_file"]), request)
            if operation == "SHOW":
                verify_show_payload(result, request, creation, session, host_pid, threads)
                shown.add(creation["image_id"])
                show_results[creation["image_id"]] = result
            else:
                request_identity(request, session, host_pid, "RELEASE", [creation["image_id"], creation["retention"]["token"]])
                receipt_identity(result, request, session, host_pid, threads)
                require(result.get("image_id") == creation["image_id"] and result.get("retention_token") == creation["retention"]["token"] and
                        result.get("released") is True and result.get("plugin_retained") is False, "Release token/identity/state differs")
                released.add(creation["image_id"])
    evidence.unchanged()
    return {"manifest": manifest, "fixture": fixture, "sources": sources, "evidence": evidence,
            "host_pid": host_pid, "session": session, "threads": threads, "entries": entries, "shown": shown, "released": released, "show_results": show_results}


def verify_stop(context):
    manifest, evidence = context["manifest"], context["evidence"]
    require("stop_request_file" in manifest and "stop_result_file" in manifest, "UNVERIFIED: original pre-submission STOP record required")
    request = evidence.json(manifest["stop_request_file"])
    request_identity(request, context["session"], context["host_pid"], "STOP", [])
    result = profile.unpack_result(evidence.json(manifest["stop_result_file"]), request)
    receipt_identity(result, request, context["session"], context["host_pid"], context["threads"])


def verify_document_inventory(documents, original, shown_ids):
    require(type(documents) is list and type(original) is list and type(shown_ids) is set, "Document observations required")
    baseline = {doc["document_id"]: doc for doc in original}
    current = {doc["document_id"]: doc for doc in documents}
    require(len(current) == len(documents) and len(baseline) == len(original) and all(current.get(key) == row for key, row in baseline.items()),
            "Source/unrelated document inventory or ROI state changed")
    extras = [doc for key, doc in current.items() if key not in baseline]
    require(len(extras) == len(shown_ids) and {doc["image_ids"][0] for doc in extras if len(doc.get("image_ids", [])) == 1} == shown_ids,
            "Shown document set does not hold exact original outputs one-to-one")
    return {doc["image_ids"][0]: doc for doc in extras}


def verify_measurements(manifest_path, phase="before"):
    import numpy as np
    require(phase in ("before", "after-release", "after-stop", "after-close", "files"), "Unknown measurement phase")
    if phase != "files":
        manifest = load(manifest_path)
        profile.validate_actual_host(manifest.get("host_pid"), manifest.get("session"))
    context = load_context(manifest_path)
    if phase == "files":
        require(all(entry["package"] is not None for entry in context["entries"].values()), "Saved-file phase requires a package for every measurement")
        return {"schema": 1, "status": "PASS_NATIVE_MEASUREMENT_SAVED_FILES", "scope": "OFFLINE_SAVED_EVIDENCE_ONLY_NOT_FRESH_HOST",
                "cases": [entry["package"] for entry in context["entries"].values()], "model_client_acceptance": "NOT_TESTED"}
    import DigitalMicrograph as DM
    from create_summary_fixture import spatial
    fixture = context["fixture"]
    if phase in ("after-stop", "after-close"): verify_stop(context)
    if phase == "after-release": require(context["released"], "After-release observation requires original release records")
    expected_shown = set() if phase == "after-close" else context["shown"]
    documents = all_documents(DM)
    bindings = verify_document_inventory(documents, fixture["documents"], expected_shown)
    observe_sources(DM, fixture, context["sources"])
    outputs = []
    for entry in context["entries"].values():
        result, checked = entry["result"], entry["checked"]
        identifier = result["image_id"]
        should_live = phase != "after-close" and (identifier in context["shown"] or
                      (phase != "after-stop" and identifier not in context["released"]))
        image = raw = None
        try:
            image = DM.FindImageByID(identifier)
            if not should_live:
                require(image is None or not image.IsValid(), "Output remains valid after independently observed release/STOP/document close")
                outputs.append({"image_id": identifier, "valid": False})
                continue
            require(image is not None and image.IsValid() and image.GetID() == identifier and image.GetNumDimensions() == 1 and image.GetDataType() == result["image"]["data_type_code"] and
                    image.GetDimensionSize(0) == len(checked["values"]) and image.GetName() == result["image"]["name"], "Live output identity/name/rank/shape differs")
            raw = image.GetNumArray(); expected = checked["values"]
            require(type(raw) is np.ndarray and raw.ndim == 1 and raw.shape == expected.shape and raw.dtype == expected.dtype and raw.tobytes() == expected.tobytes(),
                    "Live native 1D output values/dtype differ")
            expected_axis = result["image"]["calibration"][0]
            require(spatial(image, 0) == {"dm_axis": 0, "origin": expected_axis["calibrated_value_at_pixel_zero"],
                    "raw_origin": expected_axis["origin"], "scale": expected_axis["scale"], "unit": expected_axis["unit"] or ""}, "Live 1D native axis differs")
            display_rows = []
            if identifier in expected_shown:
                require(image.CountImageDisplays() == 1 and identifier in bindings, "Shown output has extra/missing display ownership")
                display = image.GetImageDisplay(0)
                require(display is not None and display.IsValid() and display.GetImage().GetID() == identifier,
                        "Shown display holds another image")
                document = DM.GetImageDocumentByID(bindings[identifier]["document_id"])
                scoped = image.GetImageDisplayInImageDocument(document, 0)
                require(scoped is not None and scoped.IsValid() and scoped.GetID() == display.GetID() and
                        scoped.GetImage().GetID() == identifier, "Exact shown document/display/image identity differs")
                window = document.GetWindow()
                require(window is not None and window.IsValid(), "Shown document has no valid window")
                display_type = display.GetDisplayType()
                require(type(display_type) is int and display_type == 3, "Exact rank-one output is not independently observed as a native line plot")
                style = observe_show_style(DM, display, context["show_results"][identifier]) if identifier in context.get("show_results", {}) else {"status": "NOT_REQUESTED"}
                display_rows.append({"document_id": bindings[identifier]["document_id"], "display_id": display.GetID(), "display_type": display_type,
                                     "style_observation": style})
                display = document = scoped = window = None
            else: require(image.CountImageDisplays() == 0, "Unshown output acquired an unexpected document/display")
            outputs.append({"image_id": identifier, "valid": True, "dtype": str(raw.dtype), "shape": list(raw.shape), "displays": display_rows})
        finally: image = raw = None
    require(all_documents(DM) == documents, "Document inventory changed during independent observation")
    context["evidence"].unchanged()
    return {"schema": 1, "status": "PASS_NATIVE_MEASUREMENT_" + phase.upper().replace("-", "_"), "phase": phase,
            "host_pid": os.getpid(), "session": context["session"], "source_pixels_calibration_names_and_GUI_unchanged": True,
            "source_documents_unchanged": True, "output_observations": outputs, "document_inventory": documents,
            "snapshot_atomic": False, "python_is_listener": False, "model_client_acceptance": "NOT_TESTED"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--phase", choices=("before", "after-release", "after-stop", "after-close", "files"), default="before")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    report = {"schema": 1, "status": "FAIL", "phase": args.phase}
    with open(args.output, "x", encoding="utf-8") as output:
        try: report = verify_measurements(args.manifest, args.phase)
        except BaseException as error: report.update(error_type=type(error).__name__, error=str(error))
        json.dump(report, output, ensure_ascii=True, indent=2, allow_nan=False)
        output.write("\n"); output.flush(); os.fsync(output.fileno())
    print(report["status"])
    return 0 if report["status"].startswith("PASS_") else 1


if __name__ == "__main__": raise SystemExit(main())
