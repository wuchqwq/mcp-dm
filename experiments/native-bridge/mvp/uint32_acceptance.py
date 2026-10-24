# -*- coding: utf-8 -*-
"""Fixed synthetic uint32 acceptance contract, never a runtime data engine."""
import base64
import math
import os
import re

from create_summary_fixture import require
from verify_handoff import Evidence, canonical, sha, bounded_npy, bit_equal
from verify_operations import integer, finite, strict_json
from verify_preview import decode_gray8_png, reference_preview, MAPPING, ORIENTATION, SAMPLING

CODE = 11  # Candidate mapping; fixture GetDataType and native READ must independently agree.
VALUES = ((0, 1, 16777215, 16777216), (16777217, 2147483647, 2147483648, 4294967294),
          (123456789, 3, 65537, 4294967295), (11, 29, 100000001, 4000000001))
RECT = [1, 1, 4, 3]
SOURCE_STATS = {"minimum": 0, "maximum": 4294967295, "sum": 17158755904, "mean": 1072422244.0}
CROP_STATS = {"minimum": 3, "maximum": 4294967295, "sum": 12884967424, "mean": 2147494570.6666665}
CAPABILITIES = ("native_uint32_mean", "native_uint32_statistics", "native_uint32_crop", "native_uint32_preview", "native_uint32_read")
OPERATORS = ["GMSImageProcessing::GetMinimum", "GMSImageProcessing::GetMaximum", "GMSImageProcessing::GetSum", "GMSImageProcessing::GetMean"]
MAPPING_POLICY = "logical ROI only; source_x=x0+roi_x; source_y=y0+roi_y; source unchanged"
PROVENANCE_SCOPE = "immutable creation record only; source image remains mutable"
INTEGER_REDUCTION = "exact Python integer sum checked against NumPy uint64; raw float64 mean = exact sum / count"
TYPES = {"STATUS": "status", "MEAN": "native_mean", "SUMMARY": "native_summary", "CROP": "image_crop", "PREVIEW": "native_preview",
         "READ": "native_data_snapshot", "UNARY": "native_image_operation", "BINARY": "native_image_operation", "FFT": "native_fourier_operation",
         "REAL": "native_fourier_operation", "FILTER": "native_image_operation"}
RID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def fixed_values():
    import numpy as np
    return np.array(VALUES, dtype=np.uint32)


def expected_axes(unit):
    return [{"dm_axis": 0, "origin": 1.25, "raw_origin": 5.0, "scale": -.25, "unit": unit},
            {"dm_axis": 1, "origin": -2.5, "raw_origin": 5.0, "scale": .5, "unit": unit}]


def load_truth(evidence, path, expected_pid):
    import numpy as np
    truth = evidence.json(path)
    require(truth.get("schema") == 1 and truth.get("status") == "RECORDED" and truth.get("kind") == "synthetic-only" and
            truth.get("python_is_listener") is False and integer(truth.get("host_pid"), expected_pid, expected_pid) and
            type(truth.get("session")) is str and re.fullmatch(r"[a-f0-9]{32}", truth["session"]), "uint32 truth/schema/actual PID/session mismatch")
    images = truth.get("images")
    require(type(images) is list and len(images) == 2 and {v.get("label") for v in images} == {"CALIBRATED", "RAW_UNITS"}, "uint32 fixed source labels required")
    sources, ids = {}, set()
    for entry in images:
        require(integer(entry.get("id"), 1, 0xfffffffe) and entry["id"] not in ids and type(entry.get("name")) is str and
                entry["name"].isascii() and bool(entry["name"]) and entry.get("dtype") == "uint32" and entry.get("shape") == [4, 4] and
                integer(entry.get("python_data_type_code"), CODE, CODE), "uint32 fixture identity/type/code mismatch")
        raw = evidence.raw(entry["source_npy"], 8192)
        values = bounded_npy(raw, [4, 4], "<u4")
        bit_equal(values, fixed_values(), "Fixed high-bit uint32 truth was truncated or signed/downcast")
        require(sha(raw) == entry.get("source_file_sha256") and sha(values.tobytes(order="C")) == entry.get("pixel_sha256"), "uint32 source NPY/pixel hash mismatch")
        unit = "nm" if entry["label"] == "CALIBRATED" else ""
        require(entry.get("calibration") == expected_axes(unit) and entry.get("intensity_calibration") == {"origin": 7.5, "scale": -2.0, "unit": "arb"} and
                entry.get("expected_summary") == SOURCE_STATS, "uint32 fixed source spatial/intensity/raw summary truth mismatch")
        sources[entry["label"]] = (entry, values)
        ids.add(entry["id"])
    require(integer(truth.get("document_count_before_fixture"), 0) and
            integer(truth.get("initial_document_count"), truth["document_count_before_fixture"]+2, truth["document_count_before_fixture"]+2),
            "uint32 fixture document count mismatch")
    return truth, sources


def metadata(actual, image_id, observation):
    values, axes = observation["values"], observation["calibration"]
    shape = list(values.shape)
    require(type(actual) is dict and integer(actual.get("id"), image_id, image_id) and actual.get("name") == observation["name"], "uint32 metadata ID/name mismatch")
    require(actual.get("dtype") == "uint32" and integer(actual.get("data_type_code"), CODE, CODE) and actual.get("is_integer") is True and
            actual.get("is_unsigned") is True and integer(actual.get("packing_style"), 1, 1) and integer(actual.get("ndim"), 2, 2) and
            actual.get("shape") == shape and all(integer(v, 1) for v in actual["shape"]) and actual.get("dm_dimensions") == shape[::-1] and
            all(integer(v, 1) for v in actual["dm_dimensions"]) and integer(actual.get("pixels"), values.size, values.size) and
            actual.get("shape_order") == "numpy (last axis is X)" and actual.get("coordinate_rule") == "physical(i)=calibrated_value_at_pixel_zero+i*scale",
            "uint32 metadata dtype/signedness/packing/axes mismatch")
    require(type(actual.get("native_mean_supported")) is bool and type(actual.get("native_summary_supported")) is bool,
            "uint32 reduction support flags missing")
    complete = all(bool(axis["unit"]) for axis in axes)
    require(actual.get("calibration_complete") is complete and type(actual.get("calibration")) is list and len(actual["calibration"]) == 2,
            "uint32 metadata calibration completeness mismatch")
    for expected in axes:
        dim = expected["dm_axis"]
        matches = [axis for axis in actual["calibration"] if type(axis) is dict and integer(axis.get("dm_dimension"), dim, dim)]
        require(len(matches) == 1, "uint32 metadata calibration axis identity mismatch")
        axis = matches[0]
        require(integer(axis.get("numpy_axis"), 1-dim, 1-dim) and integer(axis.get("size"), shape[1-dim], shape[1-dim]) and
                axis.get("unit") == (expected["unit"] or None) and axis.get("usable") is bool(expected["unit"]) and
                axis.get("issue") == (None if expected["unit"] else "unknown_units"), "uint32 calibration axis/unit/issue mismatch")
        for field, key in (("origin", "raw_origin"), ("calibrated_value_at_pixel_zero", "origin"), ("scale", "scale")):
            require(finite(axis.get(field)) and axis[field] == expected[key], "uint32 signed calibration number mismatch")


def decode(entry, preview=False, failed=False):
    response = entry.get("response", {})
    require(type(response) is dict and "error" not in response and response.get("isError") is (True if failed else response.get("isError")) and
            (response.get("isError") is True if failed else response.get("isError") is not True), "uint32 MCP tool error/success mismatch")
    content = response.get("content")
    require(type(content) is list and len(content) == (2 if preview else 1) and content[0].get("type") == "text" and type(content[0].get("text")) is str,
            "uint32 original MCP content framing mismatch")
    output = strict_json(content[0]["text"].encode("utf-8"))
    require(type(output) is dict and (failed or output.get("backend") == "digitalmicrograph-native"), "uint32 native backend mismatch")
    return output


def load_ledger(evidence, path, pid, session, duplicates=False):
    records, ids = [], set()
    for line in evidence.raw(path).splitlines():
        record = strict_json(line)
        request_id = record.get("id")
        require(set(record) == {"protocol", "session", "host_pid", "id", "op", "args", "wire"} and record.get("protocol") == "NB2" and
                record.get("session") == session and integer(record.get("host_pid"), pid, pid) and type(request_id) is str and RID.fullmatch(request_id) and
                (duplicates or request_id not in ids) and type(record.get("args")) is list and all(integer(v) for v in record["args"]) and
                record.get("op") in set(TYPES) | {"QUERY"}, "uint32 original ledger identity/arguments mismatch")
        wire = "NB2 %s %s %s%s\n" % (session, request_id, record["op"], " "+" ".join(map(str, record["args"])) if record["args"] else "")
        require(record.get("wire") == wire, "uint32 original wire mismatch")
        records.append(record);ids.add(request_id)
    return records


def bind(entry, tool, arguments, operation, args, context, failure=None):
    request, output = entry.get("request", {}), decode(entry, operation == "PREVIEW", failure is not None)
    request_id = request.get("id")
    require(request_id in context["ledger"] and request_id not in context["seen"] and request == context["ledger"][request_id] and
            entry.get("tool") == tool and entry.get("arguments") == dict(arguments, request_id=request_id) and
            request.get("op") == operation and request.get("args") == args, "uint32 tool/original request binding mismatch")
    receipt = output.get("native_receipt", {})
    require(receipt.get("protocol") == "NB2" and receipt.get("session") == context["session"] and
            receipt.get("id") == receipt.get("request_id") == request_id and integer(receipt.get("host_pid"), context["pid"], context["pid"]) and
            receipt.get("state") == ("failed" if failure else "completed") and receipt.get("original_operation") == operation and
            receipt.get("normalized_args") == args and type(receipt.get("normalized_args")) is list and all(integer(v) for v in receipt["normalized_args"]) and
            receipt.get("result_type") == TYPES[operation] and integer(receipt.get("result_version"), 2 if operation in ("FFT", "REAL") else 1,
                2 if operation in ("FFT", "REAL") else 1) and integer(receipt.get("exec_tid"), 1) and integer(receipt.get("worker_tid"), 1) and
            receipt["exec_tid"] != receipt["worker_tid"], "uint32 completed/failed receipt identity/type/thread mismatch")
    timings = receipt.get("timings_us")
    require(type(timings) is dict and set(timings) == {"queue", "execute"} and all(integer(timings[key], 0, 2**53-1) for key in timings), "uint32 receipt timings mismatch")
    if "threads" in context:
        require((receipt["exec_tid"],receipt["worker_tid"]) == context["threads"], "uint32 STATUS host thread anchor changed")
    require("result" not in receipt and (receipt.get("code") == "native_error" and receipt.get("error") == failure if failure else
            "code" not in receipt and "error" not in receipt), "uint32 failure domain or completed error fields mismatch")
    context["seen"].add(request_id)
    return output


def status_contract(status, mode, pid):
    require(status.get("ready") is True and status.get("binary_gate") is True and integer(status.get("host_pid"), pid, pid) and
            status.get("host_thread") == status["native_receipt"]["exec_tid"] and status.get("supported_build") == "3.53.4137.0-x64" and
            status.get("host_build") == "3.53.4137.0" and status.get("host_architecture") == "x64" and
            status.get("adapter_profile") == "gms-3.53.4137.0-windows-x64" and status.get("adapter_active") is True and
            status.get("compatibility",{}).get("state") == "SUPPORTED" and mode in ("prepared","production"), "uint32 host/profile/readiness/mode anchor mismatch")
    capabilities = status.get("native_capabilities")
    require(type(capabilities) is list, "uint32 native capability declarations missing")
    for name in CAPABILITIES:
        matches = [entry for entry in capabilities if entry.get("name") == name]
        require(len(matches) == 1 and type(matches[0].get("available")) is bool and matches[0].get("qualification") ==
                ("NOT_QUALIFIED" if mode == "prepared" else "LIMITED_REAL_HOST") and (mode == "prepared" or matches[0]["available"] is True),
                "uint32 subgroup qualification mismatch: "+name)
    require(status.get("prepared_uint32_execution_enabled") is True if mode == "prepared" else
            "prepared_uint32_execution_enabled" not in status, "uint32 prepared/production execution gate mismatch")


def summary(output, image_id, observation, expected, mean_only=False):
    require(integer(output.get("image_id"), image_id, image_id) and output.get("computation") == "DM native" and
            output.get("intensity_calibration_applied") is False and output.get("intensity_semantics") == "raw pixel intensity" and
            output.get("source_write_requested") is False and output.get("snapshot_atomic") is False, "uint32 reduction raw/native identity mismatch")
    for name in (("mean",) if mean_only else ("minimum","maximum","sum","mean")):
        require(finite(output.get(name)) and output[name] == expected[name], "uint32 native "+name+" differs from exact integer fixture oracle")
    require(output.get("operator") == "GMSImageProcessing::GetMean" if mean_only else output.get("operators") == OPERATORS,
            "uint32 reduction operator identity mismatch")
    metadata(output.get("image"),image_id,observation)
    require(output["image"]["native_mean_supported"] is True and output["image"]["native_summary_supported"] is True,
            "uint32 statistics support not available")


def read(output, image_id, rect, observation, provenance):
    expected = observation["values"][rect[1]:rect[3],rect[0]:rect[2]]
    require(output.get("operation") == "READ" and output.get("source_image_id") == image_id and output.get("requested_rect") == output.get("effective_rect") == rect and
            output.get("shape") == list(expected.shape) and output.get("dtype") == "uint32" and output.get("byte_order") == "little" and
            output.get("array_order") == "C" and output.get("axes") == ["y","x"] and output.get("data_encoding") == "base64" and
            integer(output.get("sample_count"),expected.size,expected.size) and integer(output.get("raw_bytes"),expected.nbytes,expected.nbytes),
            "uint32 READ dtype/axes/ROI/size mismatch")
    metadata(output.get("source"),image_id,observation)
    text = output.get("values_base64")
    require(type(text) is str,"uint32 READ base64 missing")
    raw = base64.b64decode(text.encode("ascii"),validate=True)
    require(base64.b64encode(raw).decode("ascii") == text and raw == expected.tobytes(order="C"), "uint32 READ high bits or signedness differ from exact source pixels")
    require(output.get("operator") == "GMS::Image::GetRealValue" and output.get("computation") == "DM native point reads; data handoff only" and
            output.get("intensity_calibration_applied") is False and output.get("intensity_semantics") == "raw pixel intensity" and
            output.get("source_write_requested") is False and output.get("snapshot_atomic") is False and
            output.get("source_provenance") == provenance and output.get("source_provenance_scope") == PROVENANCE_SCOPE and
            output.get("coordinate_mapping_policy") == MAPPING_POLICY and output.get("ownership") == "response-owned numeric snapshot; no native result image",
            "uint32 READ raw/lineage/ownership semantics mismatch")
    axes=[]
    for axis in output["source"]["calibration"]:
        dim=axis["dm_dimension"];offset=rect[dim]
        axes.append({"dm_dimension":dim,"numpy_axis":1-dim,"size":expected.shape[1-dim],"source_offset":offset,
            "source_origin":axis["origin"],"source_calibrated_value_at_pixel_zero":axis["calibrated_value_at_pixel_zero"],
            "origin":axis["origin"]-offset,"calibrated_value_at_pixel_zero":axis["calibrated_value_at_pixel_zero"]+offset*axis["scale"],
            "scale":axis["scale"],"unit":axis["unit"],"usable":axis["usable"],"issue":axis["issue"]})
    require(output.get("roi_calibration") == axes and output.get("calibration_complete") is all(axis["usable"] for axis in axes),
            "uint32 READ signed ROI calibration mismatch")
    return raw


def capture(evidence, entry, output):
    original = evidence.raw(entry["snapshot"])
    require(sha(original)==entry.get("snapshot_sha256") and decode({"response":strict_json(original)})==output,"uint32 saved original MCP bytes mismatch")
    receipt=output["native_receipt"];raw=base64.b64decode(output["values_base64"]);rh=sha(canonical(receipt))
    record=evidence.json(entry["request_record"]);cap=entry.get("receipt",{})
    require(record.get("schema_version")==1 and record.get("kind")=="native_snapshot_handoff_request" and record.get("state")=="CAPTURED" and
            cap.get("state")=="captured" and record.get("capture_receipt")==cap and record.get("capture_id")==cap.get("capture_id") and
            record.get("request_id")==cap.get("request_id") and record.get("native_receipt")==receipt and record.get("native_receipt_sha256")==rh,
            "uint32 capture journal/native state mismatch")
    p=record.get("parameters",{});directory=os.path.realpath(cap["capture_dir"])
    require(record.get("parameters_sha256")==sha(canonical(p)) and p.get("saved_snapshot_sha256")==sha(original) and
            p.get("native_receipt_sha256")==rh and p.get("native_values_sha256")==sha(raw) and p.get("session")==receipt["session"] and
            p.get("native_request_id")==receipt["id"] and p.get("operation")=="READ" and p.get("normalized_args")==receipt["normalized_args"] and
            os.path.realpath(p.get("snapshot_path",""))==os.path.realpath(entry["snapshot"]) and
            os.path.realpath(os.path.join(p.get("workspace",""),p.get("output","")))==directory,"uint32 immutable handoff parameters mismatch")
    files={name:evidence.raw(os.path.join(directory,name),512*1024) for name in ("input.npy","input.json","capture.json")}
    hashes={name:sha(value) for name,value in files.items()};info=strict_json(files["input.json"]);manifest=strict_json(files["capture.json"])
    require(cap.get("files_sha256")==hashes and info.get("schema_version")==manifest.get("schema_version")==1 and manifest.get("state")=="captured" and
            info.get("capture_id")==manifest.get("capture_id")==cap.get("capture_id") and info.get("native_receipt")==receipt and
            info.get("native_receipt_sha256")==manifest.get("native_receipt_sha256")==rh and
            info.get("saved_snapshot_sha256")==manifest.get("saved_snapshot_sha256")==sha(original) and
            info.get("input_sha256")==manifest.get("input_sha256")==cap.get("input_sha256")==hashes["input.npy"] and
            manifest.get("input_metadata_sha256")==sha(canonical(info)) and manifest.get("input_metadata_file_sha256")==hashes["input.json"],
            "uint32 capture manifest/native/file hash mismatch")
    sourcecal=[dict(axis,axis="x" if i==0 else "y") for i,axis in enumerate(output["source"]["calibration"])]
    workcal=[dict(axis,axis="x" if i==0 else "y") for i,axis in enumerate(output["roi_calibration"])]
    require(info.get("dtype")==cap.get("dtype")==manifest.get("source_dtype")=="uint32" and integer(manifest.get("source_data_type_code"),CODE,CODE) and
            info.get("shape_yx")==cap.get("shape_yx")==output["shape"] and info.get("source_image_id")==manifest.get("source_image_id")==output["source_image_id"] and
            info.get("source_rect_xyxy")==manifest.get("source_rect_xyxy")==cap.get("source_rect_xyxy")==output["effective_rect"] and
            info.get("source_shape_yx")==manifest.get("source_shape_yx")==output["source"]["shape"] and info.get("source_metadata")==output["source"] and
            info.get("source_calibration_dm")==manifest.get("calibration_before")==manifest.get("calibration_after")==sourcecal and
            info.get("working_calibration_xy")==workcal and info.get("native_source_provenance")==output["source_provenance"] and
            info.get("byte_order")=="little" and info.get("array_order")=="C" and info.get("axes")==["y","x"] and
            info.get("raw_bytes")==len(raw) and info.get("sample_count")==output["sample_count"] and
            info.get("pixel_sha256")==manifest.get("pixel_sha256")==sha(raw),"uint32 NPY metadata/type/calibration/provenance mismatch")
    for value in (info,manifest,cap):
        require(value.get("pixel_capture_atomic") is False and value.get("dm_file_save") is False,"uint32 handoff false atomic/SaveAs claim")
    require(info.get("intensity_calibration")=={"origin":None,"scale":None,"unit":None,"status":"NOT_READ"} and
            info.get("intensity_calibration_applied") is False and manifest.get("live_source_reobserved") is False and
            manifest.get("native_session")==cap.get("native_session")==receipt["session"] and
            manifest.get("native_request_id")==cap.get("native_request_id")==receipt["id"],"uint32 capture intensity/session semantics mismatch")
    values=bounded_npy(files["input.npy"],output["shape"],"<u4")
    require(values.tobytes(order="C")==raw,"uint32 NPY dtype/high-bit bytes changed")
    return {"values":values,"info":info,"hashes":hashes}


def external(evidence, entry, package):
    directory=entry["output_dir"];info=package["info"]
    run=evidence.json(os.path.join(directory,"run.json"));params=evidence.json(os.path.join(directory,"parameters.json"))
    result_raw=evidence.raw(os.path.join(directory,"results.json"));result=strict_json(result_raw)
    script=evidence.raw(os.path.join(directory,"native_handoff_mean.py"))
    expected_script=evidence.raw(os.path.join(os.path.dirname(__file__),"..","..","..","examples","native_handoff_mean.py"))
    require(script==expected_script,"uint32 external script provenance mismatch")
    values=package["values"];exact=sum(int(value) for value in values.flat);count=int(values.size);bound=count*4294967295
    require(bound <= 9007199254740991 and params.get("dtype")=="uint32" and params.get("capture_id")==info["capture_id"] and
            params.get("capture_files_sha256")==package["hashes"] and params.get("native_session")==info["native_receipt"]["session"] and
            params.get("native_request_id")==info["native_receipt"]["id"] and params.get("native_receipt_sha256")==info["native_receipt_sha256"] and
            params.get("source_image_id")==info["source_image_id"] and params.get("source_rect_xyxy")==info["source_rect_xyxy"] and
            params.get("source_calibration_dm")==info["source_calibration_dm"] and params.get("working_calibration_xy")==info["working_calibration_xy"] and
            params.get("script_sha256")==sha(script) and params.get("accumulator_dtype")=="uint64" and params.get("mean_dtype")=="float64" and
            params.get("integer_sum_bound")==bound and params.get("max_exact_float64_integer")==9007199254740991 and
            params.get("integer_reduction")==INTEGER_REDUCTION and params.get("dm_called") is False and params.get("result_returned_to_dm") is False,
            "uint32 external parameters/capture/exactness provenance mismatch")
    require(run.get("state")==result.get("state")=="complete" and run.get("results_sha256")==sha(result_raw) and
            result.get("capture_id")==info["capture_id"] and result.get("dtype")=="uint32" and integer(result.get("sum"),exact,exact) and result.get("sum_exact") is True and
            finite(result.get("mean")) and result["mean"]==exact/count and integer(result.get("sample_count"),count,count) and
            result.get("parameters_sha256")==sha(canonical(params)) and result.get("script_sha256")==sha(script) and result.get("input_sha256")==info["input_sha256"] and
            result.get("accumulator_dtype")=="uint64" and result.get("mean_dtype")=="float64" and result.get("integer_sum_bound")==bound and
            result.get("max_exact_float64_integer")==9007199254740991 and result.get("integer_reduction")==INTEGER_REDUCTION and
            result.get("intensity_calibration_applied") is False and result.get("intensity_unit") is None and result.get("intensity_calibration_status")=="NOT_READ" and
            result.get("dm_called") is False and result.get("result_returned_to_dm") is False,"uint32 external exact sum/mean/state mismatch")
    return {"status":"PASS","sum":exact,"mean":exact/count,"sample_count":count,"reference":"independent exact Python integers; no float32 conversion"}
