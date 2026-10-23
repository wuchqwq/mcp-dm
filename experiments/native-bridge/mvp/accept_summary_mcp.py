"""Independent strict stdio MCP acceptance for the limited native SUMMARY.

Use a new private summary-truth.json from a one-shot synthetic host fixture.
This client compares receipts/scalars/metadata, never proves live source pixels
unchanged: a separate read-only in-host oracle must check those postconditions.
Only this client's own stdio child is started/closed; DM is never controlled.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import uuid

from accept_mcp import (StdioClient, ROOT, finite, integer, require,
                        strict_json, validate_receipt)


OPERATORS = ["GMSImageProcessing::GetMinimum", "GMSImageProcessing::GetMaximum",
             "GMSImageProcessing::GetSum", "GMSImageProcessing::GetMean"]
SCALARS = ("minimum", "maximum", "sum", "mean")
LABELS = {"DEFAULT", "CALIBRATED_INTENSITY", "RAW_UNITS", "UINT16", "NONFINITE"}
CATALOG = {"dm_status", "dm_datasets", "dm_native_mean", "dm_native_summary",
           "dm_native_result", "dm_crop", "dm_native_show"}
BACKEND = "digitalmicrograph-native"
COORDINATE_RULE = "physical(i)=calibrated_value_at_pixel_zero+i*scale"


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_truth(truth, expected_pid):
    require(isinstance(truth, dict) and type(truth.get("schema")) is int and truth["schema"] == 1
            and truth.get("status") == "RECORDED" and truth.get("kind") == "synthetic-only"
            and truth.get("python_is_listener") is False, "Explicit one-shot synthetic SUMMARY truth required")
    require(isinstance(truth.get("session"), str) and re.fullmatch(r"[a-f0-9]{32}", truth["session"]) is not None,
            "Invalid SUMMARY truth session")
    require(integer(expected_pid, 1, 0xffffffff) and type(truth.get("host_pid")) is int
            and truth["host_pid"] == expected_pid, "SUMMARY truth/expected host PID mismatch")
    require(integer(truth.get("initial_document_count"), 0), "Invalid initial document count")
    images = truth.get("images")
    require(isinstance(images, list) and len(images) == len(LABELS)
            and all(isinstance(image, dict) for image in images)
            and {image.get("label") for image in images} == LABELS, "Wrong SUMMARY fixture labels")
    ids = set()
    for image in images:
        require(integer(image.get("id"), 0, 0xfffffffe) and image["id"] not in ids, "Invalid/duplicate SUMMARY fixture image ID")
        ids.add(image["id"])
        require(isinstance(image.get("name"), str) and image["name"] and image["name"].isascii(), "ASCII fixture names required")
        shape = image.get("shape")
        require(isinstance(shape, list) and len(shape) == 2 and all(integer(n, 1, 4194304) for n in shape)
                and shape[0] * shape[1] <= 4194304, "Invalid SUMMARY fixture shape")
        require(image.get("dtype") == ("uint16" if image["label"] == "UINT16" else "float32")
                and type(image.get("finite")) is bool
                and image["finite"] is (image["label"] != "NONFINITE"), "Wrong SUMMARY fixture dtype/finite scope")
        axes = image.get("calibration")
        require(isinstance(axes, list) and len(axes) == 2 and all(isinstance(axis, dict) for axis in axes)
                and {axis.get("dm_axis") for axis in axes} == {0, 1}, "Invalid SUMMARY fixture calibration axes")
        for axis in axes:
            require(type(axis.get("dm_axis")) is int
                    and all(finite(axis.get(key)) for key in ("origin", "raw_origin", "scale"))
                    and axis["scale"] != 0 and isinstance(axis.get("unit"), str), "Invalid SUMMARY fixture calibration")
            require(bool(axis["unit"]) is (image["label"] != "RAW_UNITS"), "Wrong fixture missing-unit scope")
        intensity = image.get("intensity_calibration")
        require(isinstance(intensity, dict) and finite(intensity.get("origin")) and finite(intensity.get("scale"))
                and intensity["scale"] != 0 and isinstance(intensity.get("unit"), str), "Missing independent intensity calibration")
        if image["label"] == "CALIBRATED_INTENSITY":
            require(intensity["origin"] != 0 or intensity["scale"] != 1, "Nontrivial intensity-calibration fixture required")
        supported = image["label"] in ("DEFAULT", "CALIBRATED_INTENSITY", "RAW_UNITS")
        expected_summary = image.get("expected_summary")
        require((isinstance(expected_summary, dict) and set(expected_summary) == set(SCALARS)
                 and all(finite(expected_summary[key]) for key in SCALARS)) if supported else "expected_summary" not in image,
                "Wrong SUMMARY truth scalar scope")
        require(isinstance(image.get("source_npy"), str) and image["source_npy"]
                and all(isinstance(image.get(key), str) and re.fullmatch(r"[a-f0-9]{64}", image[key]) is not None
                        for key in ("source_file_sha256", "pixel_sha256")), "Missing SUMMARY source fingerprints")
    return {image["label"]: image for image in images}


def validate_metadata(actual, truth):
    require(isinstance(actual, dict) and type(actual.get("id")) is int and actual["id"] == truth["id"]
            and actual.get("name") == truth["name"], "SUMMARY image identity/name mismatch")
    shape = truth["shape"]
    require(actual.get("shape") == shape and isinstance(actual.get("shape"), list)
            and all(integer(n, 1) for n in actual["shape"])
            and type(actual.get("ndim")) is int and actual["ndim"] == 2
            and type(actual.get("data_type_code")) is int and actual["data_type_code"] == 2
            and actual.get("dtype") == "float32" and actual.get("dm_dimensions") == list(reversed(shape))
            and integer(actual.get("pixels"), 1) and actual["pixels"] == shape[0] * shape[1]
            and actual.get("shape_order") == "numpy (last axis is X)", "SUMMARY image shape/dtype mismatch")
    require(actual.get("native_mean_supported") is True and actual.get("native_summary_supported") is True
            and actual.get("coordinate_rule") == COORDINATE_RULE, "SUMMARY metadata support/coordinate mismatch")
    calibrated = truth["label"] != "RAW_UNITS"
    require(actual.get("calibration_complete") is calibrated, "SUMMARY calibration completeness mismatch")
    axes = actual.get("calibration")
    require(isinstance(axes, list) and len(axes) == 2, "Missing SUMMARY calibration axes")
    for expected in truth["calibration"]:
        axis_id = expected["dm_axis"]
        matches = [axis for axis in axes if isinstance(axis, dict) and type(axis.get("dm_dimension")) is int
                   and axis["dm_dimension"] == axis_id]
        require(len(matches) == 1, "SUMMARY calibration axis identity mismatch")
        axis = matches[0]
        require(type(axis.get("numpy_axis")) is int and axis["numpy_axis"] == 1 - axis_id
                and integer(axis.get("size"), 1) and axis["size"] == shape[1 - axis_id]
                and axis.get("unit") == (expected["unit"] or None), "SUMMARY calibration axis/size/unit mismatch")
        for field, expected_field in (("origin", "raw_origin"), ("calibrated_value_at_pixel_zero", "origin"), ("scale", "scale")):
            require(finite(axis.get(field)) and axis[field] == expected[expected_field],
                    "SUMMARY calibration " + field + " mismatch")
        require(axis.get("usable") is calibrated and axis.get("issue") == (None if calibrated else "unknown_units"),
                "SUMMARY calibration usability/issue mismatch")


def validate_summary(output, truth):
    require(type(output.get("image_id")) is int and output["image_id"] == truth["id"], "SUMMARY output image ID mismatch")
    for field in SCALARS:
        # Small hand-known fixtures use binary-exact inputs/answers. No loose
        # tolerance should hide an applied intensity scale/offset or wrong sum.
        require(finite(output.get(field)) and output[field] == truth["expected_summary"][field],
                "SUMMARY " + field + " differs from independent raw fixture truth")
    require(output.get("operators") == OPERATORS and output.get("computation") == "DM native",
            "SUMMARY native operator identity mismatch")
    require(output.get("intensity_calibration_applied") is False
            and output.get("intensity_semantics") == "raw pixel intensity"
            and output.get("source_write_requested") is False and output.get("snapshot_atomic") is False,
            "SUMMARY raw intensity/source semantics mismatch")
    validate_metadata(output.get("image"), truth)


def receipt(output, request_id, session, pid, host_thread=None, worker_tid=None):
    value = validate_receipt(output, request_id, session, BACKEND, pid, host_thread)
    require(not any(key in value for key in ("error", "code", "result")), "Invalid SUMMARY completed receipt fields")
    if worker_tid is not None:
        require(value["worker_tid"] == worker_tid, "SUMMARY native worker identity changed")
    return value


def verify_fixture_files(truth):
    for image in truth["images"]:
        require(file_hash(image["source_npy"]) == image["source_file_sha256"], "SUMMARY source oracle file hash changed")


def run_acceptance(client, truth, report, request_log, build):
    pid, session = truth["host_pid"], truth["session"]
    images = {image["label"]: image for image in truth["images"]}
    initialized = client.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                              "clientInfo": {"name": "native-summary-independent-acceptance", "version": "1"}})
    require("error" not in initialized and initialized["result"].get("protocolVersion") == "2024-11-05"
            and initialized["result"].get("serverInfo") == {"name": "digitalmicrograph", "version": "0.6.0"}, "SUMMARY MCP initialization failed")
    client.notify("notifications/initialized")
    listed = client.rpc("tools/list", {})
    catalog = listed.get("result", {}).get("tools")
    require(isinstance(catalog, list) and all(isinstance(tool, dict) and isinstance(tool.get("name"), str) for tool in catalog)
            and len(catalog) == len(CATALOG) and {tool["name"] for tool in catalog} == CATALOG, "Unexpected SUMMARY native tool catalog")
    schema = next(tool.get("inputSchema", {}) for tool in catalog if tool["name"] == "dm_native_summary")
    require(schema.get("required") == ["image_id"] and schema.get("additionalProperties") is False
            and schema.get("properties", {}).get("image_id", {}).get("type") == "integer"
            and schema["properties"]["image_id"].get("minimum") == 0
            and schema["properties"]["image_id"].get("maximum") == 0xffffffff
            and schema["properties"].get("request_id", {}).get("type") == "string", "Wrong SUMMARY input schema")
    host_thread, worker_tid = None, None

    def save_request(tool, arguments, operation, native_args):
        saved_id = "summary-" + uuid.uuid4().hex
        params = dict(arguments, request_id=saved_id)
        record = {"protocol": "NB1", "session": session, "id": saved_id, "op": operation,
                  "args": native_args, "host_pid": pid, "tool": tool, "arguments": params,
                  "wire": "NB1 %s %s %s%s\n" % (session, saved_id, operation,
                            " " + " ".join(str(value) for value in native_args) if native_args else "")}
        request_log.write(json.dumps(record, allow_nan=False) + "\n")
        request_log.flush()
        os.fsync(request_log.fileno())
        return saved_id, params

    def call(tool, arguments, operation, native_args, label=None):
        request_id, params = save_request(tool, arguments, operation, native_args)
        output = client.tool(tool, params)
        native = receipt(output, request_id, session, pid, host_thread, worker_tid)
        report["checks"].append({"tool": tool, "arguments": params, "label": label, "output": output})
        return output, native

    status, anchor = call("dm_status", {}, "STATUS", [])
    host_thread, worker_tid = anchor["exec_tid"], anchor["worker_tid"]
    require(status.get("ready") is True and status.get("binary_gate") is True
            and status.get("supported_build") == build and type(status.get("host_pid")) is int and status["host_pid"] == pid
            and type(status.get("host_thread")) is int and status["host_thread"] == host_thread
            and status.get("build_error") is None and status.get("requires_idle_host") is True
            and status.get("resident_python_required") is False and status.get("arbitrary_script") is False
            and isinstance(status.get("capabilities"), list) and "summary_float32_2d" in status["capabilities"], "SUMMARY native status/build gate failed")
    report.update(host_thread=host_thread, worker_tid=worker_tid)
    datasets, unused = call("dm_datasets", {}, "DATASETS", [])
    require(isinstance(datasets.get("datasets"), list), "Missing SUMMARY native datasets")
    for label in ("DEFAULT", "CALIBRATED_INTENSITY", "RAW_UNITS"):
        expected = images[label]
        matches = [image for image in datasets["datasets"] if isinstance(image, dict) and image.get("id") == expected["id"]]
        require(len(matches) == 1, "SUMMARY fixture missing or ambiguous in datasets")
        validate_metadata(matches[0], expected)
        output, unused = call("dm_native_summary", {"image_id": expected["id"]}, "SUMMARY", [expected["id"]], label)
        validate_summary(output, expected)
        original_id = output["native_receipt"]["id"]
        recovered = client.tool("dm_native_result", {"request_id": original_id})
        receipt(recovered, original_id, session, pid, host_thread, worker_tid)
        validate_summary(recovered, expected)
        require(recovered == output, "SUMMARY QUERY changed original result/receipt")
        report["checks"].append({"tool": "dm_native_result", "arguments": {"request_id": original_id}, "label": label, "output": recovered})

    for label, image_id, expected_error in (("UINT16", images["UINT16"]["id"], "native_summary_requires_float32_2d"),
            ("NONFINITE", images["NONFINITE"]["id"], "native_summary_nonfinite_result"),
            ("MISSING", 0xffffffff, "image_not_found")):
        request_id, params = save_request("dm_native_summary", {"image_id": image_id}, "SUMMARY", [image_id])
        response = client.rpc("tools/call", {"name": "dm_native_summary", "arguments": params})
        require("error" not in response and isinstance(response.get("result"), dict)
                and response["result"].get("isError") is True, "SUMMARY expected native failure layer mismatch")
        content = response["result"].get("content")
        require(isinstance(content, list) and len(content) == 1 and content[0].get("type") == "text", "SUMMARY failure content mismatch")
        output = strict_json(content[0]["text"])
        failed = output.get("native_receipt", {})
        require(failed.get("protocol") == "NB1" and failed.get("session") == session
                and failed.get("id") == request_id and failed.get("request_id") == request_id
                and failed.get("state") == "failed" and failed.get("code") == "native_error"
                and failed.get("error") == expected_error and output.get("error") == expected_error
                and all(type(failed.get(key)) is int for key in ("host_pid", "worker_tid", "exec_tid"))
                and (failed["host_pid"], failed["worker_tid"], failed["exec_tid"]) == (pid, worker_tid, host_thread)
                and not any(key in failed for key in ("result",))
                and not any(key in output for key in SCALARS), "SUMMARY wrong failure identity/error; unknown is not rejection")
        timings = failed.get("timings_us")
        require(isinstance(timings, dict) and all(integer(timings.get(key)) for key in ("queue", "execute")), "SUMMARY failure timings mismatch")
        report["checks"].append({"tool": "dm_native_summary", "arguments": params, "label": label, "expected_error": expected_error, "output": output})
    # A safe failure must not leave the adapter unusable.
    output, unused = call("dm_native_summary", {"image_id": images["DEFAULT"]["id"]}, "SUMMARY", [images["DEFAULT"]["id"]], "DEFAULT_AFTER_ERRORS")
    validate_summary(output, images["DEFAULT"])
    report.update(same_session_query_recovery=True, valid_request_after_safe_errors=True,
                  nontrivial_intensity_calibration_compared=True, raw_units_limitation_checked=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--evidence-directory", type=Path, required=True)
    parser.add_argument("--expected-host-pid", type=int, required=True)
    parser.add_argument("--expected-build", default="3.53.4137.0-x64")
    parser.add_argument("--server", type=Path, default=ROOT / "server.mjs")
    parser.add_argument("--node", default=shutil.which("node") or "node")
    parser.add_argument("--timeout-seconds", type=float, default=5)
    args = parser.parse_args(argv)
    require(math.isfinite(args.timeout_seconds) and 1 <= args.timeout_seconds <= 30, "Timeout must be 1..30 seconds")
    truth = strict_json(args.truth.read_text(encoding="utf-8-sig"))
    validate_truth(truth, args.expected_host_pid)
    initial_truth_hash = file_hash(args.truth)
    evidence = args.evidence_directory.resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    report = {"status": "FAIL", "scope": "strict stdio MCP SUMMARY and independent fixture truth comparison; no source-invariance/UI proof",
              "fixture_kind": "synthetic-only", "session": truth["session"], "host_pid": truth["host_pid"],
              "backend": BACKEND, "truth_sha256": initial_truth_hash, "checks": [],
              "source_invariance": "NOT_TESTED_BY_CLIENT", "independent_source_oracle_required": True,
              "initial_document_count": truth["initial_document_count"]}
    client = None
    try:
        verify_fixture_files(truth)
        with (evidence / "stdio-events.jsonl").open("x", encoding="utf-8") as trace, (evidence / "requests.jsonl").open("x", encoding="utf-8") as requests:
            env = dict(os.environ, DM_MCP_BACKEND="native", DM_NATIVE_SESSION=truth["session"],
                       DM_MCP_TIMEOUT_MS=str(max(100, int((args.timeout_seconds - 0.5) * 1000))), DM_MCP_ALLOW_DMSCRIPT="0")
            client = StdioClient([args.node, str(args.server.resolve())], env, trace, args.timeout_seconds)
            run_acceptance(client, truth, report, requests, args.expected_build)
        require(file_hash(args.truth) == initial_truth_hash, "SUMMARY truth oracle file changed during acceptance")
        verify_fixture_files(truth)
        report.update(status="PASS", fixture_files_unchanged=True)
    except Exception as error:
        report.update(status="FAIL", error_type=type(error).__name__, error=str(error))
    finally:
        if client is not None:
            try:
                client.close()
                require(client.proc.returncode == 0, "Owned SUMMARY stdio child did not exit cleanly")
            except Exception as error:
                report.update(status="FAIL", error_type=type(error).__name__, error="SUMMARY client shutdown failed: " + str(error))
            (evidence / "node-stderr.txt").write_bytes(bytes(client.stderr))
            report["node_exit_code"] = client.proc.returncode
        with (evidence / "summary.json").open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2, ensure_ascii=True, allow_nan=False)
    print(json.dumps({"status": report["status"], "scope": report["scope"]}, ensure_ascii=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
