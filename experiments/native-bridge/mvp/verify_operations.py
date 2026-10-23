# -*- coding: utf-8 -*-
"""Historical prepared-v1 read-only oracle. Never a runtime fallback.

GetNumArray views are compared before copying and released by short helpers.
FFT/filter observations remain NOT_QUALIFIED pending numerical acceptance.
Current public Fourier v2 / READ qualification uses verify_handoff.py; the
separate verify_operations_math.py completes this historical v1 math evidence.
"""
import hashlib
import json
import math
import os
import re

from create_summary_fixture import require, spatial, intensity

LABEL_SHAPES = {"A": [4, 4], "B": [4, 4], "CONSTANT": [4, 4], "IMPULSE": [4, 8],
                "SINGLE_FREQUENCY": [4, 4], "NONFINITE": [4, 4], "UINT16": [4, 4],
                "FILTER_A": [8, 8]}
FOURIER_LABELS = ("CONSTANT", "IMPULSE", "SINGLE_FREQUENCY", "A")
TYPES = {"STATUS": "status", "DATASETS": "datasets", "UNARY": "native_image_operation",
         "BINARY": "native_image_operation", "FILTER": "native_image_operation",
         **{op: "native_fourier_operation" for op in
            ("FFT", "IFFT", "REAL", "IMAG", "VENDOR_ARG", "VENDOR_NORM")}}


def integer(value, minimum=0, maximum=0xffffffff):
    return type(value) is int and minimum <= value <= maximum


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(RuntimeError("Nonfinite JSON")))


def read_json(path):
    with open(path, "rb") as source:
        return strict_json(source.read())


def read_json_hashed(path):
    with open(path, "rb") as source:
        raw = source.read()
    return strict_json(raw), hashlib.sha256(raw).hexdigest()


def output_key(entry):
    labels = entry.get("source_labels")
    require(type(labels) is list and all(type(label) is str for label in labels), "Output source labels invalid")
    opcode = entry.get("opcode")
    require(opcode is None or integer(opcode, 1), "Output opcode type invalid")
    return entry.get("kind"), tuple(labels), opcode


def expected_cases(source_ids, outputs):
    cases = {"STATUS": ("STATUS", [], None), "DATASETS": ("DATASETS", [], None)}
    cases.update({
        "bad-unary-enum": ("UNARY", [source_ids["A"], 99], "native_unary_opcode_unsupported"),
        "unsupported-unary-dtype": ("UNARY", [source_ids["UINT16"], 1], "native_arithmetic_requires_float32_2d"),
        "nonfinite-unary": ("UNARY", [source_ids["NONFINITE"], 1], "native_arithmetic_source_nonfinite"),
        "invalid-source-id": ("UNARY", [0xffffffff, 1], "image_not_found"),
        "no-broadcast": ("BINARY", [source_ids["A"], source_ids["IMPULSE"], 1], "native_binary_shape_mismatch"),
        "nonfinite-fft": ("FFT", [source_ids["NONFINITE"]], "native_fft_nonfinite_source"),
        "unsupported-fft-dtype": ("FFT", [source_ids["UINT16"]], "native_fft_input_type_or_dimensions_unsupported"),
        "unsupported-filter-dtype": ("FILTER", [source_ids["UINT16"], 1], "native_filter_requires_float32_2d_ordinary_packing")})
    expected = set()
    for kind in ("UNARY", "BINARY"):
        labels = ("A",) if kind == "UNARY" else ("A", "B")
        expected.update((kind, labels, opcode) for opcode in (1, 2, 3))
    for label in FOURIER_LABELS:
        expected.update((kind, (label,), None) for kind in ("FFT", "REAL", "IMAG", "IFFT", "IFFT_REAL"))
    expected.update((kind, ("A",), None) for kind in ("VENDOR_ARG", "VENDOR_NORM"))
    expected.update(("FILTER", ("FILTER_A",), opcode) for opcode in (1, 2, 3, 4))
    require(type(outputs) is list and len(outputs) == 32, "Complete 32-output matrix required")
    by_key = {}
    for entry in outputs:
        require(type(entry) is dict, "Invalid output entry")
        key = output_key(entry)
        require(key in expected and key not in by_key, "Output matrix case missing/duplicate/unknown")
        by_key[key] = entry
    require(set(by_key) == expected, "Output matrix case missing/duplicate/unknown")
    labels_by_key = {}
    for key, entry in by_key.items():
        kind, labels, opcode = key
        op = "REAL" if kind == "IFFT_REAL" else kind
        if kind in ("UNARY", "BINARY", "FILTER"):
            args = [source_ids[label] for label in labels] + [opcode]
            label = kind.lower() + "-" + str(opcode)
        elif kind == "FFT":
            args, label = [source_ids[labels[0]]], "fft-" + labels[0]
        else:
            parent_kind = "IFFT" if kind == "IFFT_REAL" else "FFT"
            parent = by_key[(parent_kind, labels, None)]
            require(integer(entry.get("parent_image_id"), 1) and entry["parent_image_id"] == parent["image_id"],
                    "Derived result parent/lineage mismatch")
            args = [parent["image_id"]]
            label = ("ifft-real-" + labels[0] if kind == "IFFT_REAL" else
                     "ifft-" + labels[0] if kind == "IFFT" else
                     kind + "-" + labels[0] if kind in ("REAL", "IMAG") else kind)
        cases[label] = op, args, None
        labels_by_key[key] = label
    return cases, by_key, labels_by_key


def bind_evidence(truth, observed, records, actual_pid):
    require(integer(actual_pid, 1) and type(truth.get("host_pid")) is int and truth["host_pid"] == actual_pid and
            type(observed.get("host_pid")) is int and observed["host_pid"] == actual_pid,
            "Truth/receipt host is not executing oracle process")
    session = truth.get("session")
    require(type(session) is str and re.fullmatch(r"[a-f0-9]{32}", session) and
            truth.get("kind") == observed.get("kind") == "synthetic-only" and
            truth.get("status") == observed.get("status") == "RECORDED" and
            observed.get("session") == session and truth.get("python_is_listener") is False,
            "Invalid synthetic evidence/session")
    images = truth.get("images")
    require(type(images) is list and len(images) == len(LABEL_SHAPES) and
            {entry.get("label") for entry in images} == set(LABEL_SHAPES), "Complete unique fixture labels required")
    require(integer(truth.get("initial_document_count"), len(LABEL_SHAPES)), "Invalid fixture document count")
    source_ids = {}
    for entry in images:
        require(integer(entry.get("id"), 1) and entry["id"] != 0xffffffff and entry["id"] not in source_ids.values() and
                entry.get("shape") == LABEL_SHAPES[entry["label"]] and
                entry.get("dtype") == ("uint16" if entry["label"] == "UINT16" else "float32"),
                "Invalid source identity/type/shape")
        source_ids[entry["label"]] = entry["id"]
    cases, by_key, labels_by_key = expected_cases(source_ids, observed.get("outputs"))
    checks = observed.get("checks")
    require(type(checks) is list and len(checks) == len(cases) and
            {entry.get("label") for entry in checks} == set(cases), "Complete unique receipt matrix required")
    by_label = {entry["label"]: entry for entry in checks}
    require(len(by_label) == len(checks), "Complete unique receipt matrix required")
    status_receipt = by_label["STATUS"].get("receipt", {})
    status = status_receipt.get("result", {})
    require(type(status) is dict and status.get("backend") == "digitalmicrograph-native" and
            status.get("ready") is True and status.get("binary_gate") is True and
            status.get("candidate_execution_enabled") is True and status.get("supported_build") == "3.53.4137.0-x64" and
            integer(status.get("host_pid"), 1) and status["host_pid"] == actual_pid and
            integer(status.get("host_thread"), 1) and status["host_thread"] == status_receipt.get("exec_tid") and
            integer(status_receipt.get("worker_tid"), 1) and status_receipt["worker_tid"] != status["host_thread"],
            "STATUS host/build/readiness anchor mismatch")
    anchor = status["host_thread"], status_receipt["worker_tid"]
    ledger = {}
    for request in records:
        request_id = request.get("id")
        require(type(request_id) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_id) and request_id not in ledger and
                request.get("protocol") == "NB2" and integer(request.get("host_pid"), 1) and
                request["host_pid"] == actual_pid and request.get("session") == session,
                "Invalid/duplicate pre-submit identity")
        args = request.get("args")
        require(type(args) is list and all(integer(value) for value in args), "Invalid normalized arguments")
        wire = "NB2 %s %s %s%s\n" % (session, request_id, request["op"],
                                     " " + " ".join(str(value) for value in args) if args else "")
        require(request.get("wire") == wire, "Original submitted wire mismatch")
        ledger[request_id] = request
    seen, result_ids = set(), set()
    for label, check in by_label.items():
        op, args, failure = cases[label]
        request = ledger.get(check.get("id"))
        require(request is not None and check["id"] not in seen, "Unbound/duplicate receipt")
        seen.add(check["id"])
        receipt = check.get("receipt", {})
        require(check.get("op") == request.get("op") == op and type(check.get("args")) is list and
                all(integer(value) for value in check["args"]) and check["args"] == request.get("args") == args and
                type(check.get("expected_failure")) is bool and check["expected_failure"] == (failure is not None) and
                receipt.get("protocol") == "NB2" and receipt.get("session") == session and
                integer(receipt.get("host_pid"), 1) and receipt["host_pid"] == actual_pid and
                receipt.get("id") == check["id"] and receipt.get("original_operation") == op and
                type(receipt.get("normalized_args")) is list and receipt["normalized_args"] == args and
                all(integer(value) for value in receipt["normalized_args"]) and
                receipt.get("result_type") == TYPES[op] and integer(receipt.get("result_version"), 1, 1),
                "Receipt original identity mismatch")
        require(integer(receipt.get("exec_tid"), 1) and integer(receipt.get("worker_tid"), 1) and
                (receipt["exec_tid"], receipt["worker_tid"]) == anchor, "Native thread identity changed")
        require(receipt.get("state") == ("failed" if failure else "completed"), "Wrong completed/failed receipt state")
        if failure:
            require(receipt.get("code") == "native_error" and receipt.get("error") == failure and "result" not in receipt,
                    "Negative case failed for wrong domain or capacity")
            continue
        result = receipt.get("result", {})
        require(type(result) is dict and result.get("backend") == "digitalmicrograph-native" and
                "code" not in receipt and "error" not in receipt, "Wrong backend/completed error fields")
        if op not in ("STATUS", "DATASETS"):
            image_id = result.get("image_id")
            require(integer(image_id, 1) and image_id not in result_ids and image_id not in source_ids.values(),
                    "Missing/duplicate/source output image ID")
            require(result.get("source_write_requested") is False and result.get("snapshot_atomic") is False and
                    result.get("computation") == "DM native", "Wrong source/native execution semantics")
            result_ids.add(image_id)
    require(seen == set(ledger), "Ledger/receipt count mismatch")
    require({entry.get("image_id") for entry in observed["outputs"]} == result_ids,
            "Output list is not bound to operation receipts")
    for key, entry in by_key.items():
        check = by_label[labels_by_key[key]]
        require(integer(entry.get("image_id"), 1) and entry["image_id"] == check["receipt"]["result"]["image_id"],
                "Output matrix receipt identity mismatch")
    originals = {check["id"]: check["receipt"] for check in checks if check["receipt"]["state"] == "completed"}
    recoveries = observed.get("recovered")
    require(type(recoveries) is list and len(recoveries) == len(originals), "Missing fresh-client queries")
    recovered_ids = set()
    for receipt in recoveries:
        request_id = receipt.get("id")
        require(request_id in originals and request_id not in recovered_ids and receipt == originals[request_id],
                "Fresh-client recovery changed original result identity")
        recovered_ids.add(request_id)
    return by_key, by_label, labels_by_key


def bind_metadata(actual, image_id, observation):
    values, axes = observation["values"], observation["calibration"]
    shape, dtype = list(values.shape), str(values.dtype)
    expected_code = 2 if dtype == "float32" else 3 if dtype == "complex64" else None
    require(type(actual) is dict and integer(actual.get("id"), 1) and actual["id"] == image_id and
            actual.get("name") == observation["name"], "Receipt metadata identity/name mismatch")
    require(actual.get("shape") == shape and type(actual.get("shape")) is list and
            all(integer(value, 1) for value in actual["shape"]) and actual.get("dm_dimensions") == shape[::-1] and
            type(actual.get("dm_dimensions")) is list and all(integer(value, 1) for value in actual["dm_dimensions"]) and
            integer(actual.get("ndim"), 2, 2) and integer(actual.get("packing_style"), 1, 1) and
            integer(actual.get("pixels"), 1) and actual["pixels"] == values.size and
            actual.get("shape_order") == "numpy (last axis is X)" and integer(actual.get("data_type_code")) and
            (actual["data_type_code"] == expected_code if expected_code else actual["data_type_code"] not in (2, 3)) and
            actual.get("dtype") == (dtype if expected_code else None), "Receipt metadata type/shape/packing mismatch")
    require(actual.get("native_mean_supported") is (dtype == "float32") and
            actual.get("native_summary_supported") is (dtype == "float32") and
            actual.get("coordinate_rule") == "physical(i)=calibrated_value_at_pixel_zero+i*scale",
            "Receipt metadata reduction/coordinate semantics mismatch")
    require(type(actual.get("calibration")) is list and len(actual["calibration"]) == 2,
            "Receipt metadata calibration missing")
    complete = True
    for source in axes:
        axis_id = source["dm_axis"]
        matches = [axis for axis in actual["calibration"] if type(axis) is dict and
                   integer(axis.get("dm_dimension"), axis_id, axis_id)]
        require(len(matches) == 1, "Receipt metadata axis identity mismatch")
        axis = matches[0]
        usable = bool(source["unit"])
        complete = complete and usable
        require(integer(axis.get("numpy_axis"), 1-axis_id, 1-axis_id) and
                integer(axis.get("size"), shape[1-axis_id], shape[1-axis_id]) and
                axis.get("unit") == (source["unit"] or None) and axis.get("usable") is usable and
                axis.get("issue") == (None if usable else "unknown_units"), "Receipt metadata calibration units/axis mismatch")
        for field, key in (("origin", "raw_origin"), ("calibrated_value_at_pixel_zero", "origin"), ("scale", "scale")):
            require(finite(axis.get(field)) and axis[field] == source[key], "Receipt metadata calibration number mismatch")
    require(actual.get("calibration_complete") is complete, "Receipt metadata calibration completeness mismatch")


def detached_observation(DM, np, image_id, compare_ids=()):
    image = view = other = other_view = None
    try:
        image = DM.FindImageByID(image_id)
        require(image is not None and image.IsValid() and image.GetID() == image_id, "Image identity invalid")
        view = image.GetNumArray()
        require(isinstance(view, np.ndarray) and view.ndim == 2, "Raw NumPy view is not 2D")
        for other_id in compare_ids:
            try:
                other = DM.FindImageByID(other_id)
                require(other is not None and other.IsValid() and other.GetID() == other_id, "Comparison image identity invalid")
                other_view = other.GetNumArray()
                require(isinstance(other_view, np.ndarray), "Comparison did not return raw NumPy view")
                require(not np.shares_memory(view, other_view), "Source/output or output/output raw views share memory")
            finally:
                other_view = other = None
        return {"values": np.array(view, order="C", copy=True), "name": image.GetName(),
                "calibration": [spatial(image, axis) for axis in (0, 1)], "intensity_calibration": intensity(image)}
    finally:
        other_view = other = view = image = None


def verify_source(np, expected, actual):
    values = actual["values"]
    require(actual["name"] == expected["name"], "Source name changed")
    with open(expected["source_npy"], "rb") as source:
        require(hashlib.sha256(source.read()).hexdigest() == expected["source_file_sha256"], "Source oracle file changed")
    saved = np.load(expected["source_npy"], allow_pickle=False)
    require(str(saved.dtype) == expected["dtype"] and list(saved.shape) == expected["shape"] and
            hashlib.sha256(saved.tobytes(order="C")).hexdigest() == expected["pixel_sha256"],
            "Saved source oracle dtype/shape/pixels mismatch")
    require(values.dtype == saved.dtype and values.shape == saved.shape and
            hashlib.sha256(values.tobytes(order="C")).hexdigest() == expected["pixel_sha256"],
            "Source pixel/dtype/shape changed")
    require(actual["calibration"] == expected["calibration"] and
            actual["intensity_calibration"] == expected["intensity_calibration"], "Source calibration changed")
    return saved


def collect(report, truth, observed, directory):
    import numpy as np
    import DigitalMicrograph as DM

    source_ids = {entry["label"]: entry["id"] for entry in truth["images"]}
    unused_cases, by_key, labels_by_key = expected_cases(source_ids, observed["outputs"])
    by_label = {entry["label"]: entry for entry in observed["checks"]}
    observations, sources = {}, {}
    for expected in truth["images"]:
        actual = detached_observation(DM, np, expected["id"])
        sources[expected["label"]] = verify_source(np, expected, actual)
        observations[expected["id"]] = actual
    prior_ids = list(source_ids.values())
    for entry in observed["outputs"]:
        image_id = entry["image_id"]
        actual = detached_observation(DM, np, image_id, prior_ids)
        require(actual["values"].dtype in (np.dtype("float32"), np.dtype("complex64")) and
                np.isfinite(actual["values"]).all(), "Nonfinite or unsupported output dtype")
        observations[image_id] = actual
        prior_ids.append(image_id)
        filename = os.path.join(directory, "output_" + str(image_id) + ".npy")
        with open(filename, "xb") as output:
            np.save(output, actual["values"], allow_pickle=False)
        with open(filename, "rb") as output:
            snapshot_hash = hashlib.sha256(output.read()).hexdigest()
        report["outputs"].append({"kind": entry["kind"], "image_id": image_id, "status": "NOT_QUALIFIED",
                                  "dtype": str(actual["values"].dtype), "shape": list(actual["values"].shape),
                                  "calibration": actual["calibration"], "intensity_calibration": actual["intensity_calibration"],
                                  "snapshot": filename, "snapshot_file_sha256": snapshot_hash,
                                  "source_labels": entry["source_labels"], "opcode": entry.get("opcode"),
                                  "parent_image_id": entry.get("parent_image_id"),
                                  "request_id": by_label[labels_by_key[output_key(entry)]]["id"],
                                  "pixel_sha256": hashlib.sha256(actual["values"].tobytes(order="C")).hexdigest()})
    datasets = by_label["DATASETS"]["receipt"]["result"]
    entries = datasets.get("datasets")
    require(type(entries) is list and integer(datasets.get("count")) and datasets["count"] == len(entries) and
            datasets.get("complete") is True and datasets.get("snapshot_atomic") is False, "DATASETS completeness mismatch")
    require(all(type(entry) is dict and integer(entry.get("id"), 1) for entry in entries) and
            len({entry["id"] for entry in entries}) == len(entries), "DATASETS duplicate/invalid identity")
    dataset_map = {entry["id"]: entry for entry in entries}
    for image_id in source_ids.values():
        require(image_id in dataset_map, "DATASETS source missing")
        bind_metadata(dataset_map[image_id], image_id, observations[image_id])
    output_checks = {entry["image_id"]: entry for entry in report["outputs"]}
    arithmetic_passes = []
    for key, entry in by_key.items():
        check = by_label[labels_by_key[key]]
        result = check["receipt"]["result"]
        image_id, args, op = entry["image_id"], check["args"], check["op"]
        bind_metadata(result.get("image"), image_id, observations[image_id])
        source_values = observations[args[0]]["values"]
        actual_values = observations[image_id]["values"]
        require(actual_values.dtype == (np.dtype("complex64") if op in ("FFT", "IFFT") else np.dtype("float32")) and
                actual_values.shape == source_values.shape, "Operation output dtype/shape contract mismatch")
        if op in ("UNARY", "BINARY"):
            names = ("negate", "abs", "square") if op == "UNARY" else ("add", "subtract", "multiply")
            operators = ("Negate", "Abs", "Square") if op == "UNARY" else ("operator+", "operator-", "operator*")
            require(result.get("operation") == names[args[-1]-1] and integer(result.get("opcode"), args[-1], args[-1]) and
                    result.get("operator") == "GMSImageProcessing::" + operators[args[-1]-1] and
                    type(result.get("source_image_ids")) is list and all(integer(value, 1) for value in result["source_image_ids"]) and
                    result["source_image_ids"] == args[:-1] and type(result.get("sources")) is list and
                    len(result["sources"]) == len(args)-1 and result.get("intensity_calibration_applied") is False and
                    result.get("intensity_semantics") == "raw pixel intensity", "Arithmetic result operation/source semantics mismatch")
            for source_id, metadata in zip(args[:-1], result["sources"]):
                bind_metadata(metadata, source_id, observations[source_id])
        else:
            require(result.get("operation") == op and integer(result.get("source_image_id"), args[0], args[0]),
                    "Result operation/source identity mismatch")
            bind_metadata(result.get("source"), args[0], observations[args[0]])
            operators = {"FFT": "Real_FFT", "IFFT": "IFFT", "REAL": "Real", "IMAG": "Imag",
                         "VENDOR_ARG": "Arg", "VENDOR_NORM": "Norm"}
            operator = (("SmoothFilter", "SobelFilter", "LaplaceFilter", "SharpenFilter")[args[1]-1]
                        if op == "FILTER" else operators[op])
            require(result.get("operator") == "GMSImageProcessing::" + operator, "Result vendor operator mismatch")
            if op == "FILTER":
                require(integer(result.get("filter_kind"), args[1], args[1]) and result.get("kernel") == "vendor_defined" and
                        result.get("edge_behavior") == "vendor_defined", "Filter kind/semantics mismatch")
        actual = observations[image_id]
        source = sources[entry["source_labels"][0]]
        expected = None
        if op == "UNARY":
            expected = (-source, np.abs(source), source*source)[args[1]-1]
        elif op == "BINARY":
            rhs = sources[entry["source_labels"][1]]
            expected = (source+rhs, source-rhs, source*rhs)[args[2]-1]
        if expected is not None:
            require(actual["values"].dtype == np.float32 and actual["values"].shape == expected.shape and
                    np.array_equal(actual["values"], expected), "Native arithmetic differs from independent raw-pixel reference")
        if op in ("UNARY", "BINARY", "FILTER"):
            source_truth = next(value for value in truth["images"] if value["label"] == entry["source_labels"][0])
            require(actual["calibration"] == source_truth["calibration"] and
                    actual["intensity_calibration"] == source_truth["intensity_calibration"], "Result calibration changed")
        if expected is not None:
            arithmetic_passes.append(image_id)
        else:
            output_checks[image_id]["reason"] = "FFT/filter convention requires separate explicit mathematical acceptance"
    # No raw array view or wrapper escapes detached_observation.
    for expected in truth["images"]:
        verify_source(np, expected, detached_observation(DM, np, expected["id"]))
    count = DM.CountImageDocumentsOfAllWorkspaces()
    require(integer(count) and count == truth["initial_document_count"], "Hidden processing unexpectedly changed document count")
    for image_id in arithmetic_passes:
        output_checks[image_id]["status"] = "PASS"
    report.update(source_protection="PASS", independent_memory="PASS", document_count=count,
                  raw_views_and_wrappers_released=True, output_count=32)


def main():
    directory = os.environ["DM_NATIVE_EVIDENCE_DIR"]
    truth, truth_hash = read_json_hashed(os.path.join(directory, "operations-truth.json"))
    observed, observed_hash = read_json_hashed(os.environ.get("DM_NATIVE_OPERATIONS_REPORT", os.path.join(directory, "operations-report.json")))
    with open(os.environ.get("DM_NATIVE_OPERATIONS_LEDGER", os.path.join(directory, "operations-requests.jsonl")), "rb") as source:
        ledger_raw = source.read()
        records = [strict_json(line) for line in ledger_raw.splitlines() if line.strip()]
    filename = os.environ["DM_NATIVE_OPERATIONS_VERIFICATION"]
    with open(filename, "x", encoding="utf-8") as output:
        report = {"schema": 1, "status": "FAIL", "host_pid": os.getpid(), "session": truth.get("session"),
                  "truth_sha256": truth_hash, "operations_report_sha256": observed_hash,
                  "requests_sha256": hashlib.sha256(ledger_raw).hexdigest(),
                  "outputs": [], "source_protection": "NOT_TESTED", "fft_filters": "NOT_QUALIFIED"}
        try:
            bind_evidence(truth, observed, records, os.getpid())
            collect(report, truth, observed, directory)
            report["status"] = "RECORDED_PARTIAL_QUALIFICATION"
        except BaseException as error:
            report.update(error_type=type(error).__name__, error=str(error))
        json.dump(report, output, indent=2, ensure_ascii=True, allow_nan=False)
        output.write("\n")
    print("Native operations oracle " + report["status"])
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
