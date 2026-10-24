"""Offline mutation tests for the real SUMMARY acceptance client.

Every case executes the actual client/StdioClient against an owned, explicitly
synthetic Python stdio peer. No real DM, named pipe, GUI or vendor DLL is used.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
ACCEPT = ROOT / "experiments" / "native-bridge" / "mvp" / "accept_summary_mcp.py"
SESSION = "0123456789abcdef0123456789abcdef"
HOST_PID = 101

FAKE_MCP = r'''
import json, os, pathlib, sys
truth_path = pathlib.Path(os.environ["SUMMARY_TEST_TRUTH"])
truth = json.loads(truth_path.read_text(encoding="utf-8"))
mode = os.environ["SUMMARY_TEST_MODE"]
evidence = pathlib.Path(os.environ["SUMMARY_TEST_EVIDENCE"])
images = {image["id"]: image for image in truth["images"]}
records = {}
summary_calls = 0

def image_metadata(image):
    axes = [{"dm_dimension": axis["dm_axis"], "numpy_axis": 1-axis["dm_axis"],
        "size": image["shape"][1-axis["dm_axis"]], "origin": axis["raw_origin"],
        "calibrated_value_at_pixel_zero": axis["origin"], "scale": axis["scale"],
        "unit": axis["unit"] or None, "usable": bool(axis["unit"]),
        "issue": None if axis["unit"] else "unknown_units"} for axis in image["calibration"]]
    return {"id": image["id"], "name": image["name"], "dtype": image["dtype"],
        "ndim": 2, "data_type_code": 2, "shape": image["shape"],
        "dm_dimensions": list(reversed(image["shape"])), "pixels": image["shape"][0]*image["shape"][1],
        "shape_order": "numpy (last axis is X)", "calibration": axes,
        "calibration_complete": all(axis["usable"] for axis in axes),
        "native_mean_supported": True, "native_summary_supported": True,
        "coordinate_rule": "physical(i)=calibrated_value_at_pixel_zero+i*scale"}

def native_receipt(request_id, failed=False):
    result = {"protocol": "NB2", "session": truth["session"], "id": request_id,
        "original_operation": operation, "normalized_args": native_args,
        "result_type": {"STATUS":"status", "DATASETS":"datasets", "SUMMARY":"native_summary"}[operation], "result_version":1,
        "request_id": request_id, "state": "failed" if failed else "completed", "host_pid": truth["host_pid"],
        "worker_tid": 202, "exec_tid": 203, "timings_us": {"queue": 0, "execute": 1}}
    if mode == "wrong_pid": result["host_pid"] += 1
    if mode == "wrong_session": result["session"] = "f"*32
    if mode == "wrong_request_id": result["id"] = "unrelated"
    return result

def summary(image, request_id):
    output = {"backend": "digitalmicrograph-native", "image_id": image["id"],
        "image": image_metadata(image), "operators": ["GMSImageProcessing::GetMinimum", "GMSImageProcessing::GetMaximum",
        "GMSImageProcessing::GetSum", "GMSImageProcessing::GetMean"], "computation": "DM native",
        "intensity_calibration_applied": False, "intensity_semantics": "raw pixel intensity",
        "source_write_requested": False, "snapshot_atomic": False,
        "native_receipt": native_receipt(request_id)}
    output.update(image["expected_summary"])
    if mode in ("bad_minimum", "bad_maximum", "bad_sum", "bad_mean"): output[mode[4:]] += 0.125
    if mode == "mean_bool": output["mean"] = True
    if mode == "mean_missing": del output["mean"]
    if mode == "bad_image_id": output["image_id"] += 99
    if mode == "bad_metadata_id": output["image"]["id"] += 99
    if mode == "bad_shape": output["image"]["shape"] = [3, 2]
    if mode == "bad_dtype": output["image"]["dtype"] = "float64"
    if mode == "bad_data_type_code": output["image"]["data_type_code"] = 1
    if mode == "bad_raw_origin": output["image"]["calibration"][0]["origin"] += 0.25
    if mode == "bad_physical_zero": output["image"]["calibration"][0]["calibrated_value_at_pixel_zero"] += 0.25
    if mode == "bad_signed_scale": output["image"]["calibration"][0]["scale"] *= -1
    if mode == "bad_unit": output["image"]["calibration"][0]["unit"] = "eV"
    if mode == "bad_axis": output["image"]["calibration"][0]["numpy_axis"] = 0
    if mode == "bad_operators": output["operators"].reverse()
    if mode == "bad_computation": output["computation"] = "NumPy"
    if mode == "bad_intensity_flag": output["intensity_calibration_applied"] = True
    if mode == "bad_intensity_semantics": output["intensity_semantics"] = "calibrated intensity"
    if mode == "bad_source_write": output["source_write_requested"] = True
    if mode == "bad_atomic": output["snapshot_atomic"] = True
    if mode == "bad_backend": output["backend"] = "synthetic_mock"
    if mode == "bad_worker": output["native_receipt"]["worker_tid"] = 299
    if mode == "bad_exec": output["native_receipt"]["exec_tid"] = 298
    if mode == "bad_completed_state": output["native_receipt"]["state"] = "running"
    if mode == "bad_completed_error": output["native_receipt"]["error"] = "stray error"
    if mode == "bad_original_operation": output["native_receipt"]["original_operation"] = "MEAN"
    if mode == "bad_normalized_args": output["native_receipt"]["normalized_args"] = [999]
    if mode == "bad_result_type": output["native_receipt"]["result_type"] = "native_mean"
    if mode == "bad_result_version": output["native_receipt"]["result_version"] = 2
    if mode == "after_errors_bad" and summary_calls == 7: output["sum"] += 1
    if mode == "bad_raw_units" and image["label"] == "RAW_UNITS":
        output["image"]["calibration"][0]["issue"] = "missing"
    if mode == "calibrated_values" and image["label"] == "CALIBRATED_INTENSITY":
        for field in ("minimum", "maximum", "sum", "mean"): output[field] = output[field]*3 + 5
    return output

def text_output(output, is_error=False):
    text = json.dumps(output, allow_nan=False)
    if mode == "duplicate_scalar" and "minimum" in output:
        text = text.replace('"minimum":', '"minimum": 0, "minimum":', 1)
    if mode == "overflow_scalar" and "minimum" in output:
        text = text.replace('"minimum": -9.5', '"minimum": 1e400')
    return {"content": [{"type": "text", "text": text}], **({"isError": True} if is_error else {})}

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request: continue
    method, params = request["method"], request.get("params", {})
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "serverInfo": {"name": "digitalmicrograph", "version": "0.6.0"}}
    elif method == "tools/list":
        names = ["dm_status", "dm_datasets", "dm_native_mean", "dm_native_summary", "dm_native_result", "dm_crop", "dm_native_show",
                 "dm_native_unary", "dm_native_binary", "dm_native_fft", "dm_native_complex", "dm_native_filter", "dm_native_preview", "dm_native_read", "dm_native_result_info", "dm_native_release", "dm_native_rois"]
        schema = {"type": "object", "additionalProperties": False, "required": ["image_id"],
            "properties": {"image_id": {"type": "integer", "minimum": 0, "maximum": 4294967295}, "request_id": {"type": "string"}}}
        if mode == "bad_schema": schema["required"] = []
        if mode == "bad_catalog": names.append("dm_preview")
        result = {"tools": [{"name": name, "inputSchema": schema if name == "dm_native_summary" else {}} for name in names]}
    else:
        assert method == "tools/call"
        tool, arguments = params["name"], params["arguments"]
        request_id = arguments["request_id"]
        saved = [json.loads(item) for item in (evidence/"requests.jsonl").read_text(encoding="utf-8").splitlines()]
        if tool == "dm_native_result":
            assert any(item["id"] == request_id and item["op"] == "SUMMARY" for item in saved)
            output = json.loads(json.dumps(records[request_id]))
            if mode == "bad_query": output["mean"] += 1
            result = text_output(output)
        else:
            record = saved[-1]
            operation = {"dm_status": "STATUS", "dm_datasets": "DATASETS", "dm_native_summary": "SUMMARY"}[tool]
            native_args = [arguments["image_id"]] if operation == "SUMMARY" else []
            assert record["id"] == request_id and record["op"] == operation and record["args"] == native_args
            assert record["session"] == truth["session"] and record["host_pid"] == truth["host_pid"]
            expected_wire = "NB2 %s %s %s%s\n" % (truth["session"], request_id, operation, " "+" ".join(map(str,native_args)) if native_args else "")
            assert record["wire"] == expected_wire
            with (evidence/"peer-ledger-checks.jsonl").open("a", encoding="utf-8") as log: log.write(json.dumps(record)+"\n")
            if tool == "dm_status":
                output = {"backend": "digitalmicrograph-native", "ready": True, "binary_gate": True,
                    "supported_build": "3.53.4137.0-x64", "host_pid": truth["host_pid"]+(1 if mode=="wrong_pid" else 0),
                    "host_thread": 203, "build_error": None, "requires_idle_host": True,
                    "resident_python_required": False, "arbitrary_script": False,
                    "capabilities": ["summary_float32_2d"], "native_receipt": native_receipt(request_id)}
                if mode == "bad_gate": output["binary_gate"] = False
                result = text_output(output)
            elif tool == "dm_datasets":
                result = text_output({"backend": "digitalmicrograph-native", "datasets": [image_metadata(image) for image in images.values()],
                    "native_receipt": native_receipt(request_id)})
            else:
                summary_calls += 1
                image = images.get(arguments["image_id"])
                if image is None or image["label"] in ("UINT16", "NONFINITE"):
                    error = "image_not_found" if image is None else "native_summary_requires_float32_2d" if image["label"]=="UINT16" else "native_summary_nonfinite_result"
                    failed = native_receipt(request_id, True)
                    failed.update(code="native_error", error=error)
                    if mode == "bad_failure_state":
                        failed.update(state="unknown", exec_tid=0, original_operation=None, normalized_args=None, result_type=None, result_version=None)
                        failed.pop("code"); failed.pop("error")
                    if mode == "bad_failure_pid": failed["host_pid"] += 1
                    if mode == "bad_failure_error": failed["error"] = "different_error"
                    result = text_output({"error": error, "native_receipt": failed}, True)
                else:
                    output = summary(image, request_id)
                    records[request_id] = output
                    if mode == "source_file_change" and summary_calls == 1:
                        pathlib.Path(image["source_npy"]).write_bytes(b"changed independent oracle file")
                    if mode == "truth_file_change" and summary_calls == 1:
                        with truth_path.open("a", encoding="utf-8") as changed: changed.write(" ")
                    result = text_output(output)
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}, allow_nan=False), flush=True)
'''


class NativeSummaryAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-summary-acceptance-offline-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fake = self.root / "synthetic_stdio.py"
        self.fake.write_text(FAKE_MCP, encoding="utf-8")

    def fixture(self):
        directory = self.root / uuid.uuid4().hex
        directory.mkdir()
        truth = {"schema": 1, "status": "RECORDED", "session": SESSION, "host_pid": HOST_PID, "kind": "synthetic-only",
                 "python_is_listener": False, "initial_document_count": 5, "images": []}
        for index, label in enumerate(("DEFAULT", "CALIBRATED_INTENSITY", "RAW_UNITS", "UINT16", "NONFINITE")):
            source = directory / (label.lower() + ".npy")
            # This transport/acceptance test never parses array storage or claims
            # pixel truth. Separate fixture/oracle tests cover actual NPY data.
            source.write_bytes(b"independent file artifact " + label.encode("ascii"))
            unit = "" if label == "RAW_UNITS" else "nm"
            image = {"label": label, "id": 77+index, "name": "synthetic_"+label, "dtype": "uint16" if label=="UINT16" else "float32",
                "finite": label != "NONFINITE", "shape": [2, 3], "source_npy": str(source),
                "source_file_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "pixel_sha256": "a"*64,
                "calibration": [{"dm_axis": 0, "origin": 0.5, "raw_origin": 2.0, "scale": -0.25, "unit": unit},
                                {"dm_axis": 1, "origin": -1.0, "raw_origin": 2.0, "scale": 0.5, "unit": unit}],
                "intensity_calibration": {"origin": 5.0, "scale": 3.0, "unit": "counts"} if label=="CALIBRATED_INTENSITY" else {"origin": 0.0, "scale": 1.0, "unit": ""}}
            if label not in ("UINT16", "NONFINITE"):
                image["expected_summary"] = {"minimum": -9.5, "maximum": 8.0, "sum": 1.125, "mean": 0.1875}
            truth["images"].append(image)
        path = directory / "summary-truth.json"
        path.write_text(json.dumps(truth, allow_nan=False), encoding="utf-8")
        return truth, path, directory / "acceptance"

    def run_case(self, mode="good", expected_error=None, mutate_truth=None):
        truth, path, evidence = self.fixture()
        if mutate_truth:
            mutate_truth(truth)
            path.write_text(json.dumps(truth, allow_nan=False), encoding="utf-8")
        env = dict(os.environ, SUMMARY_TEST_TRUTH=str(path), SUMMARY_TEST_MODE=mode, SUMMARY_TEST_EVIDENCE=str(evidence))
        result = subprocess.run([sys.executable, "-B", str(ACCEPT), "--truth", str(path), "--evidence-directory", str(evidence),
            "--expected-host-pid", str(HOST_PID), "--node", sys.executable, "--server", str(self.fake)],
            cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        report_path = evidence / "summary.json"
        if expected_error is None:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
        else:
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertNotIn(b'"status": "PASS"', result.stdout)
            if report_path.exists():
                report = json.loads(report_path.read_text(encoding="utf-8"))
                self.assertEqual(report["status"], "FAIL")
                self.assertEqual(report["error_type"], "ValueError")
                self.assertIn(expected_error, report["error"])
                self.assertEqual(report["node_exit_code"], 0, "peer shutdown must not mask the target failure")
            else:
                report = None
                self.assertIn(expected_error, result.stderr.decode("utf-8"))
        return truth, evidence, report

    def test_positive_scope_identity_query_and_saved_request_ledger(self):
        truth, evidence, report = self.run_case()
        self.assertEqual(report["source_invariance"], "NOT_TESTED_BY_CLIENT")
        self.assertTrue(report["independent_source_oracle_required"])
        self.assertTrue(report["same_session_query_recovery"])
        self.assertTrue(report["valid_request_after_safe_errors"])
        self.assertEqual(report["host_pid"], HOST_PID)
        self.assertEqual(report["host_thread"], 203)
        self.assertEqual(report["worker_tid"], 202)
        ledger = [json.loads(line) for line in (evidence / "requests.jsonl").read_text(encoding="utf-8").splitlines()]
        peer = [json.loads(line) for line in (evidence / "peer-ledger-checks.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(ledger, peer, "every native request was already saved when the peer received it")
        self.assertEqual([record["op"] for record in ledger], ["STATUS", "DATASETS"] + ["SUMMARY"]*7)
        self.assertEqual(len({record["id"] for record in ledger}), len(ledger))
        self.assertEqual(report["truth_sha256"], hashlib.sha256((evidence.parent/"summary-truth.json").read_bytes()).hexdigest())

    def test_wrong_four_values_and_calibrated_intensity_cannot_pass(self):
        for field in ("minimum", "maximum", "sum", "mean"):
            with self.subTest(field=field):
                self.run_case("bad_"+field, "SUMMARY "+field+" differs from independent raw fixture truth")
        for mode in ("mean_bool", "mean_missing"):
            with self.subTest(mode=mode): self.run_case(mode, "SUMMARY mean differs from independent raw fixture truth")
        self.run_case("calibrated_values", "SUMMARY minimum differs from independent raw fixture truth")

    def test_wrong_image_shape_and_dtype_cannot_pass(self):
        for mode, error in (("bad_image_id", "SUMMARY output image ID mismatch"),
                ("bad_metadata_id", "SUMMARY image identity/name mismatch"),
                ("bad_shape", "SUMMARY image shape/dtype mismatch"), ("bad_dtype", "SUMMARY image shape/dtype mismatch"),
                ("bad_data_type_code", "SUMMARY image shape/dtype mismatch")):
            with self.subTest(mode=mode): self.run_case(mode, error)

    def test_wrong_spatial_calibration_cannot_pass(self):
        for mode, error in (("bad_raw_origin", "SUMMARY calibration origin mismatch"),
                ("bad_physical_zero", "SUMMARY calibration calibrated_value_at_pixel_zero mismatch"),
                ("bad_signed_scale", "SUMMARY calibration scale mismatch"), ("bad_unit", "SUMMARY calibration axis/size/unit mismatch"),
                ("bad_axis", "SUMMARY calibration axis/size/unit mismatch"), ("bad_raw_units", "SUMMARY calibration usability/issue mismatch")):
            with self.subTest(mode=mode): self.run_case(mode, error)

    def test_wrong_operation_and_raw_provenance_cannot_pass(self):
        for mode in ("bad_operators", "bad_computation"):
            with self.subTest(mode=mode): self.run_case(mode, "SUMMARY native operator identity mismatch")
        for mode in ("bad_intensity_flag", "bad_intensity_semantics", "bad_source_write", "bad_atomic"):
            with self.subTest(mode=mode): self.run_case(mode, "SUMMARY raw intensity/source semantics mismatch")

    def test_wrong_receipt_and_self_consistent_foreign_host_cannot_pass(self):
        for mode, error in (("wrong_pid", "Native host PID changed"), ("wrong_session", "Native receipt correlation/state mismatch"),
                ("wrong_request_id", "Native receipt correlation/state mismatch"), ("bad_completed_state", "Native receipt correlation/state mismatch"),
                ("bad_backend", "Native backend mismatch"), ("bad_worker", "SUMMARY native worker identity changed"),
                ("bad_exec", "Native execution did not use the bound host thread"),
                ("bad_completed_error", "Invalid SUMMARY completed receipt fields")):
            with self.subTest(mode=mode): self.run_case(mode, error)

    def test_wrong_catalog_gate_and_schema_cannot_pass(self):
        for mode, error in (("bad_catalog", "Unexpected SUMMARY native tool catalog"),
                ("bad_schema", "Wrong SUMMARY input schema"), ("bad_gate", "SUMMARY native status/build gate failed")):
            with self.subTest(mode=mode): self.run_case(mode, error)

    def test_query_and_post_error_request_are_independently_checked(self):
        self.run_case("bad_query", "SUMMARY mean differs from independent raw fixture truth")
        self.run_case("after_errors_bad", "SUMMARY sum differs from independent raw fixture truth")
        for mode in ("bad_failure_state", "bad_failure_pid", "bad_failure_error"):
            with self.subTest(mode=mode): self.run_case(mode, "SUMMARY wrong failure identity/error; unknown is not rejection")

    def test_ambiguous_and_nonfinite_json_cannot_pass(self):
        self.run_case("duplicate_scalar", "Duplicate JSON key: minimum")
        self.run_case("overflow_scalar", "Nonfinite JSON number")

    def test_truth_and_oracle_file_changes_cannot_pass(self):
        self.run_case("truth_file_change", "SUMMARY truth oracle file changed during acceptance")
        self.run_case("source_file_change", "SUMMARY source oracle file hash changed")

    def test_truth_scope_errors_fail_before_starting_a_client(self):
        for mutation, error in ((lambda truth: truth.update(host_pid=HOST_PID+1), "SUMMARY truth/expected host PID mismatch"),
                (lambda truth: truth.update(status="FAIL"), "Explicit one-shot synthetic SUMMARY truth required"),
                (lambda truth: truth["images"][1]["intensity_calibration"].update(origin=0, scale=1), "Nontrivial intensity-calibration fixture required"),
                (lambda truth: truth["images"][0]["expected_summary"].update(mean=True), "Wrong SUMMARY truth scalar scope")):
            with self.subTest(error=error):
                unused, evidence, report = self.run_case(expected_error=error, mutate_truth=mutation)
                self.assertIsNone(report)
                self.assertFalse(evidence.exists())

    def test_nb2_operation_args_and_schema_are_bound_before_scalar_acceptance(self):
        for mode, error in (("bad_original_operation", "NB2 operation/result schema identity mismatch"),
                ("bad_normalized_args", "NB2 original operation/arguments differ from submitted request"),
                ("bad_result_type", "NB2 operation/result schema identity mismatch"),
                ("bad_result_version", "NB2 operation/result schema identity mismatch")):
            with self.subTest(mode=mode): self.run_case(mode, error)


if __name__ == "__main__":
    unittest.main()
