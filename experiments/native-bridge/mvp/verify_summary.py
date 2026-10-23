# -*- coding: utf-8 -*-
"""Read-only one-shot SUMMARY oracle, explicitly run inside the same idle host.

Bind independent synthetic truth to strict MCP receipts and the pre-submit
ledger, then inspect every original pixel and both calibrations. No listener,
native processing fallback, image setters, document creation or closing exists.
Each invocation requires a NEW output file, including failed diagnostics.
"""
import hashlib
import json
import math
import os
import re


SCALARS = ("minimum", "maximum", "sum", "mean")
HAND = {"minimum": -9.5, "maximum": 8.0, "sum": 1.125, "mean": .1875}
LABELS = ("DEFAULT", "CALIBRATED_INTENSITY", "RAW_UNITS", "UINT16", "NONFINITE")
OPERATORS = ["GMSImageProcessing::GetMinimum", "GMSImageProcessing::GetMaximum",
             "GMSImageProcessing::GetSum", "GMSImageProcessing::GetMean"]
BACKEND = "digitalmicrograph-native"


def _protocol():
    mode = os.environ.get("DM_NATIVE_ORACLE_PROTOCOL", "NB2")
    if mode not in ("NB2", "NB1_LEGACY"):
        raise RuntimeError("Unsupported native oracle protocol mode")
    return "NB1" if mode == "NB1_LEGACY" else "NB2"


def _operation_identity(receipt, operation, args):
    if _protocol() == "NB1":
        return  # Explicit read-only historical validation; never a sender fallback.
    types = {"STATUS":"status", "DATASETS":"datasets", "INFO":"image_info", "MEAN":"native_mean",
             "SUMMARY":"native_summary", "CROP":"image_crop", "SHOW":"image_delivery", "STOP":"ipc_stop"}
    if (not isinstance(receipt, dict) or receipt.get("protocol") != "NB2" or receipt.get("original_operation") != operation
            or type(receipt.get("normalized_args")) is not list or receipt["normalized_args"] != args
            or any(type(value) is not int or not 0 <= value <= 0xffffffff for value in receipt["normalized_args"])
            or receipt.get("result_type") != types[operation]
            or type(receipt.get("result_version")) is not int or receipt["result_version"] != 1):
        raise RuntimeError("NB2 original operation/arguments/result schema mismatch")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def integer(value, minimum=0, maximum=0xffffffff):
    return type(value) is int and minimum <= value <= maximum


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    with open(path, "rb") as source:
        return source.read()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key: " + key)
            result[key] = value
        return result

    def constant(value):
        raise RuntimeError("Nonfinite JSON constant: " + value)

    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs,
                      parse_constant=constant)


def metadata(actual, expected):
    require(isinstance(actual, dict) and integer(actual.get("id"))
            and actual["id"] == expected["id"] and actual.get("name") == expected["name"],
            "SUMMARY metadata identity/name mismatch")
    shape = expected["shape"]
    require(actual.get("shape") == shape and type(actual.get("shape")) is list
            and all(integer(value, 1) for value in actual["shape"])
            and actual.get("dm_dimensions") == shape[::-1]
            and type(actual.get("dm_dimensions")) is list
            and all(integer(value, 1) for value in actual["dm_dimensions"])
            and type(actual.get("ndim")) is int and actual["ndim"] == 2
            and type(actual.get("data_type_code")) is int and actual["data_type_code"] == 2
            and actual.get("dtype") == "float32" and integer(actual.get("pixels"), 1)
            and actual["pixels"] == 6 and actual.get("shape_order") == "numpy (last axis is X)"
            and actual.get("native_mean_supported") is True
            and actual.get("native_summary_supported") is True
            and actual.get("coordinate_rule") ==
            "physical(i)=calibrated_value_at_pixel_zero+i*scale", "SUMMARY metadata type/shape mismatch")
    usable = expected["label"] != "RAW_UNITS"
    require(actual.get("calibration_complete") is usable, "SUMMARY calibration completeness mismatch")
    axes = actual.get("calibration")
    require(isinstance(axes, list) and len(axes) == 2, "SUMMARY metadata calibration missing")
    for source in expected["calibration"]:
        axis_id = source["dm_axis"]
        matches = [axis for axis in axes if isinstance(axis, dict)
                   and type(axis.get("dm_dimension")) is int and axis["dm_dimension"] == axis_id]
        require(len(matches) == 1, "SUMMARY metadata axis identity mismatch")
        axis = matches[0]
        require(type(axis.get("numpy_axis")) is int and axis["numpy_axis"] == 1 - axis_id
                and integer(axis.get("size"), 1) and axis["size"] == shape[1 - axis_id]
                and axis.get("unit") == (source["unit"] or None)
                and axis.get("usable") is usable
                and axis.get("issue") == (None if usable else "unknown_units"),
                "SUMMARY metadata calibration units/axis mismatch")
        for field, key in (("origin", "raw_origin"), ("calibrated_value_at_pixel_zero", "origin"),
                           ("scale", "scale")):
            require(finite(axis.get(field)) and axis[field] == source[key],
                    "SUMMARY metadata calibration number mismatch")


def receipt(output, request_id, report, state="completed", operation=None, args=None):
    require(isinstance(output, dict), "Invalid SUMMARY output")
    value = output.get("native_receipt")
    require(isinstance(value, dict) and value.get("protocol") == _protocol()
            and value.get("session") == report["session"] and value.get("id") == request_id
            and value.get("request_id") == request_id and value.get("state") == state
            and type(value.get("host_pid")) is int and value["host_pid"] == os.getpid()
            and type(value.get("exec_tid")) is int and value["exec_tid"] == report["host_thread"]
            and type(value.get("worker_tid")) is int and value["worker_tid"] == report["worker_tid"],
            "SUMMARY receipt session/request/host/thread/state mismatch")
    timings = value.get("timings_us")
    require(isinstance(timings, dict) and all(integer(timings.get(k), 0, 2**53 - 1)
            for k in ("queue", "execute")), "SUMMARY receipt timings invalid")
    require("result" not in value, "Nested receipt result is invalid")
    if state == "completed":
        require(output.get("backend") == BACKEND and not any(k in value for k in ("error", "code")),
                "SUMMARY completed backend/error mismatch")
    if operation is not None:
        _operation_identity(value, operation, args)
    return value


def summary(output, expected):
    require(integer(output.get("image_id")) and output["image_id"] == expected["id"],
            "SUMMARY scalar image identity mismatch")
    require(all(finite(output.get(key)) and output[key] == HAND[key] for key in SCALARS),
            "SUMMARY four raw scalar values mismatch")
    require(output.get("operators") == OPERATORS and output.get("computation") == "DM native"
            and output.get("intensity_calibration_applied") is False
            and output.get("intensity_semantics") == "raw pixel intensity"
            and output.get("source_write_requested") is False and output.get("snapshot_atomic") is False,
            "SUMMARY raw/native/source contract mismatch")
    metadata(output.get("image"), expected)


def evidence(truth, acceptance, records):
    require(acceptance.get("status") == "PASS" and acceptance.get("backend") == BACKEND
            and acceptance.get("fixture_kind") == "synthetic-only"
            and acceptance.get("session") == truth["session"]
            and type(acceptance.get("host_pid")) is int and acceptance["host_pid"] == os.getpid()
            and integer(acceptance.get("host_thread"), 1)
            and integer(acceptance.get("worker_tid"), 1)
            and acceptance["host_thread"] != acceptance["worker_tid"]
            and acceptance.get("initial_document_count") == truth["initial_document_count"]
            and acceptance.get("fixture_files_unchanged") is True
            and acceptance.get("same_session_query_recovery") is True
            and acceptance.get("valid_request_after_safe_errors") is True
            and acceptance.get("nontrivial_intensity_calibration_compared") is True
            and acceptance.get("raw_units_limitation_checked") is True
            and acceptance.get("source_invariance") == "NOT_TESTED_BY_CLIENT"
            and acceptance.get("independent_source_oracle_required") is True
            and type(acceptance.get("node_exit_code")) is int and acceptance["node_exit_code"] == 0,
            "SUMMARY acceptance host/session/scope mismatch")
    images = {item["label"]: item for item in truth["images"]}
    sequence = [("dm_status", None, "STATUS", []), ("dm_datasets", None, "DATASETS", [])]
    for label in LABELS[:3]:
        sequence += [("dm_native_summary", label, "SUMMARY", [images[label]["id"]]),
                     ("dm_native_result", label, None, None)]
    for label, image_id in (("UINT16", images["UINT16"]["id"]),
                            ("NONFINITE", images["NONFINITE"]["id"]), ("MISSING", 0xffffffff)):
        sequence.append(("dm_native_summary", label, "SUMMARY", [image_id]))
    sequence.append(("dm_native_summary", "DEFAULT_AFTER_ERRORS", "SUMMARY", [images["DEFAULT"]["id"]]))
    checks = acceptance.get("checks")
    require(isinstance(checks, list) and len(checks) == len(sequence) and len(records) == 9,
            "SUMMARY checks/request ledger count mismatch")
    used, position, recovered = set(), 0, {}
    errors = {"UINT16": "native_summary_requires_float32_2d",
              "NONFINITE": "native_summary_nonfinite_result", "MISSING": "image_not_found"}
    for check, (tool, label, op, args) in zip(checks, sequence):
        require(isinstance(check, dict) and check.get("tool") == tool and check.get("label") == label,
                "SUMMARY checks operation/label mismatch")
        arguments, output = check.get("arguments"), check.get("output")
        require(isinstance(arguments, dict) and isinstance(arguments.get("request_id"), str)
                and re.fullmatch(r"summary-[a-f0-9]{32}", arguments["request_id"]) is not None,
                "SUMMARY request ID missing/invalid")
        request_id = arguments["request_id"]
        if op is None:
            require(set(arguments) == {"request_id"} and label in recovered
                    and output == recovered[label] and request_id == output["native_receipt"]["id"],
                    "SUMMARY QUERY not identical to original submission")
            receipt(output, request_id, acceptance, operation="SUMMARY", args=[images[label]["id"]])
            summary(output, images[label])
            continue
        require(request_id not in used, "SUMMARY duplicate submitted request ID")
        used.add(request_id)
        record = records[position]
        position += 1
        expected_arguments = {"request_id": request_id}
        if op == "SUMMARY":
            expected_arguments["image_id"] = args[0]
        wire = "%s %s %s %s%s\n" % (_protocol(), truth["session"], request_id, op,
                " " + " ".join(str(value) for value in args) if args else "")
        require((op != "SUMMARY" or integer(arguments.get("image_id")))
                and isinstance(record, dict) and type(record.get("host_pid")) is int
                and type(record.get("args")) is list
                and all(integer(value) for value in record["args"])
                and isinstance(record.get("arguments"), dict)
                and (op != "SUMMARY" or integer(record["arguments"].get("image_id")))
                and arguments == expected_arguments and record == {
            "protocol": _protocol(), "session": truth["session"], "id": request_id, "op": op,
            "args": args, "host_pid": os.getpid(), "tool": tool,
            "arguments": expected_arguments, "wire": wire}, "SUMMARY pre-submit ledger binding mismatch")
        if label in errors:
            native = receipt(output, request_id, acceptance, "failed", op, args)
            require(check.get("expected_error") == errors[label]
                    and native.get("code") == "native_error" and native.get("error") == errors[label]
                    and output.get("error") == errors[label] and not any(k in output for k in SCALARS),
                    "SUMMARY expected failure mismatch")
        else:
            receipt(output, request_id, acceptance, operation=op, args=args)
            if op == "STATUS":
                require(output.get("ready") is True and output.get("binary_gate") is True
                        and output.get("supported_build") == "3.53.4137.0-x64"
                        and type(output.get("host_pid")) is int
                        and output.get("host_pid") == os.getpid()
                        and type(output.get("host_thread")) is int
                        and output.get("host_thread") == acceptance["host_thread"]
                        and output.get("build_error") is None and output.get("requires_idle_host") is True
                        and output.get("resident_python_required") is False
                        and output.get("arbitrary_script") is False
                        and "summary_float32_2d" in output.get("capabilities", []),
                        "SUMMARY status anchor mismatch")
            elif op == "DATASETS":
                datasets = output.get("datasets")
                require(isinstance(datasets, list), "SUMMARY datasets missing")
                for supported in LABELS[:3]:
                    matches = [item for item in datasets if isinstance(item, dict)
                               and item.get("id") == images[supported]["id"]]
                    require(len(matches) == 1, "SUMMARY datasets identity ambiguous/missing")
                    metadata(matches[0], images[supported])
            else:
                summary(output, images["DEFAULT" if label == "DEFAULT_AFTER_ERRORS" else label])
                recovered[label] = output


def verify(report, truth_path, acceptance_directory):
    import numpy as np

    summary_path = os.path.join(acceptance_directory, "summary.json")
    ledger_path = os.path.join(acceptance_directory, "requests.jsonl")
    paths = (truth_path, summary_path, ledger_path)
    raw = [read(path) for path in paths]
    truth, acceptance = strict_json(raw[0]), strict_json(raw[1])
    records = [strict_json(line) for line in raw[2].splitlines()]
    require(isinstance(truth, dict) and type(truth.get("schema")) is int
            and truth["schema"] == 1 and truth.get("status") == "RECORDED"
            and truth.get("kind") == "synthetic-only" and truth.get("python_is_listener") is False
            and type(truth.get("host_pid")) is int and truth["host_pid"] == os.getpid()
            and truth.get("session") == report["session"]
            and type(truth.get("session")) is str and re.fullmatch(r"[a-f0-9]{32}", truth["session"]) is not None
            and integer(truth.get("initial_document_count")), "SUMMARY truth host/session/scope mismatch")
    require(isinstance(acceptance, dict) and acceptance.get("truth_sha256") == digest(raw[0]),
            "SUMMARY original truth hash mismatch")
    images = truth.get("images")
    require(isinstance(images, list) and len(images) == 5 and all(isinstance(item, dict) for item in images)
            and {item.get("label") for item in images} == set(LABELS), "SUMMARY truth labels mismatch")
    ids = set()
    originals = []
    for entry in images:
        label = entry["label"]
        require(integer(entry.get("id"), 0, 0xfffffffe) and entry["id"] not in ids
                and type(entry.get("name")) is str and entry["name"] and entry["name"].isascii(),
                "SUMMARY source identity/name invalid")
        ids.add(entry["id"])
        require(entry.get("shape") == [2, 3] and type(entry.get("shape")) is list
                and all(integer(value, 1) for value in entry["shape"])
                and entry.get("dtype") == ("uint16" if label == "UINT16" else "float32")
                and entry.get("finite") is (label != "NONFINITE"), "SUMMARY source shape/type scope mismatch")
        if label in LABELS[:3]:
            require(isinstance(entry.get("expected_summary"), dict)
                    and set(entry["expected_summary"]) == set(HAND)
                    and all(finite(entry["expected_summary"][key])
                            and entry["expected_summary"][key] == HAND[key] for key in HAND),
                    "SUMMARY hand-known scalar truth mismatch")
        else:
            require("expected_summary" not in entry, "Unsupported SUMMARY fixture has scalar truth")
        require(type(entry.get("source_npy")) is str, "SUMMARY source file path missing")
        source_raw = read(entry["source_npy"])
        require(digest(source_raw) == entry.get("source_file_sha256"), "SUMMARY source file hash changed")
        with open(entry["source_npy"], "rb") as source:
            original = np.load(source, allow_pickle=False)
        require(str(original.dtype) == entry["dtype"] and list(original.shape) == entry["shape"]
                and digest(original.tobytes(order="C")) == entry.get("pixel_sha256"),
                "SUMMARY source NPY pixel hash/type/shape mismatch")
        base = np.array([[1.25, -2.5, 3.75], [8, -9.5, .125]], dtype=np.float32)
        if label in LABELS[:3]:
            require(np.array_equal(original, base), "SUMMARY hand-known source pixels mismatch")
        elif label == "UINT16":
            require(np.array_equal(original, np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint16)),
                    "SUMMARY UINT16 synthetic control pixels mismatch")
        else:
            expected = base.copy()
            expected[1, 1] = np.nan
            require(np.array_equal(np.isnan(original), np.isnan(expected))
                    and np.array_equal(original[np.isfinite(expected)], expected[np.isfinite(expected)]),
                    "SUMMARY NONFINITE synthetic control pixels mismatch")
        require(bool(np.isfinite(original).all()) is entry["finite"], "SUMMARY source finite scope mismatch")
        axes = entry.get("calibration")
        require(isinstance(axes, list) and len(axes) == 2 and all(isinstance(axis, dict) for axis in axes)
                and {axis.get("dm_axis") for axis in axes} == {0, 1}, "SUMMARY source calibration axes invalid")
        for axis in axes:
            require(type(axis.get("dm_axis")) is int
                    and all(finite(axis.get(k)) for k in ("origin", "raw_origin", "scale"))
                    and axis["scale"] != 0 and type(axis.get("unit")) is str
                    and bool(axis["unit"]) is (label != "RAW_UNITS"), "SUMMARY source calibration invalid")
        calibration = entry.get("intensity_calibration")
        require(isinstance(calibration, dict) and all(finite(calibration.get(k)) for k in ("origin", "scale"))
                and calibration["scale"] != 0 and type(calibration.get("unit")) is str,
                "SUMMARY source intensity calibration invalid")
        if label == "CALIBRATED_INTENSITY":
            require(calibration == {"origin": 7.5, "scale": -2.0, "unit": "arb"},
                    "SUMMARY nontrivial intensity control missing")
        originals.append((entry, original, digest(source_raw)))
    evidence(truth, acceptance, records)
    report.update(truth_sha256=digest(raw[0]), acceptance_sha256=digest(raw[1]),
                  request_ledger_sha256=digest(raw[2]), host_pid=os.getpid())
    # All external evidence is validated before any host API access.
    import DigitalMicrograph as DM
    count = DM.CountImageDocumentsOfAllWorkspaces()
    require(type(count) is int and count == truth["initial_document_count"], "SUMMARY document count changed")
    for entry, original, source_hash in originals:
        image = None
        try:
            image = DM.FindImageByID(entry["id"])
            require(image is not None and image.IsValid() and type(image.GetID()) is int
                    and image.GetID() == entry["id"] and image.GetName() == entry["name"],
                    "SUMMARY live source identity/name changed")
            actual = np.array(image.GetNumArray(), order="C", copy=True)
            require(actual.dtype == original.dtype and actual.shape == original.shape
                    and np.array_equal(np.isnan(actual), np.isnan(original))
                    and np.array_equal(np.isposinf(actual), np.isposinf(original))
                    and np.array_equal(np.isneginf(actual), np.isneginf(original))
                    and np.array_equal(actual[np.isfinite(original)], original[np.isfinite(original)])
                    and digest(actual.tobytes(order="C")) == entry["pixel_sha256"],
                    "SUMMARY source pixels/dtype/shape changed")
            for axis in entry["calibration"]:
                for style, origin in ((0, "origin"), (1, "raw_origin")):
                    zero, scale, unit = image.GetDimensionCalibration(axis["dm_axis"], style)
                    require(finite(zero) and finite(scale) and type(unit) is str
                            and (zero, scale, unit) == (axis[origin], axis["scale"], axis["unit"]),
                            "SUMMARY source spatial calibration changed")
            origin, scale, unit = (image.GetIntensityOrigin(), image.GetIntensityScale(),
                                   image.GetIntensityUnitString())
            expected = entry["intensity_calibration"]
            require(finite(origin) and finite(scale) and type(unit) is str
                    and (origin, scale, unit) == (expected["origin"], expected["scale"], expected["unit"]),
                    "SUMMARY source intensity calibration changed")
            require(digest(read(entry["source_npy"])) == source_hash,
                    "SUMMARY source NPY changed during verification")
            report["sources"].append({"label": entry["label"], "image_id": entry["id"],
                                      "all_pixels_unchanged": True, "source_file_unchanged": True,
                                      "spatial_calibration_unchanged": True,
                                      "intensity_calibration_unchanged": True})
        finally:
            image = None
    final_count = DM.CountImageDocumentsOfAllWorkspaces()
    require(type(final_count) is int and final_count == count, "SUMMARY document count changed during oracle")
    require(all(read(path) == original for path, original in zip(paths, raw)),
            "SUMMARY evidence changed during verification")
    require(all(digest(read(entry["source_npy"])) == source_hash
                for entry, original, source_hash in originals),
            "SUMMARY source NPY changed before oracle completion")
    report.update(total_documents=final_count, document_count_unchanged=True,
                  four_raw_scalars_verified=True, nontrivial_intensity_control_verified=True,
                  ordinary_python_success=True, status="PASS")


def main():
    directory = os.environ["DM_NATIVE_EVIDENCE_DIR"]
    truth = os.environ.get("DM_NATIVE_SUMMARY_TRUTH", os.path.join(directory, "summary-truth.json"))
    acceptance = os.environ.get("DM_NATIVE_SUMMARY_ACCEPTANCE_DIR", os.path.join(directory, "summary-acceptance"))
    path = os.path.join(directory, "summary-independent.json")
    with open(path, "x", encoding="utf-8") as output:
        report = {"schema": 1, "status": "FAIL", "session": os.environ.get("DM_NATIVE_SESSION"),
                  "protocol": _protocol(), "protocol_mode": os.environ.get("DM_NATIVE_ORACLE_PROTOCOL", "NB2"),
                  "host_pid": os.getpid(),
                  "kind": "synthetic-only", "python_is_listener": False, "backend": BACKEND,
                  "scope": "same-host SUMMARY receipts, raw scalars and all-source invariance",
                  "sources": [], "ui_observation": "NOT_TESTED", "unicode_qualification": "NOT_QUALIFIED",
                  "snapshot_atomic": False, "source_write_requested": False}
        try:
            verify(report, truth, acceptance)
        except BaseException as error:
            report.update(status="FAIL", error_type=type(error).__name__, error=str(error))
        json.dump(report, output, ensure_ascii=True, allow_nan=False, indent=2)
        output.write("\n")
    print("SUMMARY independent oracle " + report["status"] + "; UI NOT_TESTED.")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
