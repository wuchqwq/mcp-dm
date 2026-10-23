# -*- coding: utf-8 -*-
"""Independent SUMMARY oracle controls in isolated explicitly fake DM children.

No test imports the actual host module, contacts IPC or loads a vendor DLL.
The tiny hand-known truth and native receipts are constructed independently of
the fixture script, so source/receipt faults cannot be hidden by shared helpers.
"""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MVP = ROOT / "experiments" / "native-bridge" / "mvp"
CREATE = MVP / "create_summary_fixture.py"
VERIFY = MVP / "verify_summary.py"
SESSION = "0123456789abcdef0123456789abcdef"
LABELS = ("DEFAULT", "CALIBRATED_INTENSITY", "RAW_UNITS", "UINT16", "NONFINITE")
HAND = {"minimum": -9.5, "maximum": 8.0, "sum": 1.125, "mean": .1875}
OPERATORS = ["GMSImageProcessing::GetMinimum", "GMSImageProcessing::GetMaximum",
             "GMSImageProcessing::GetSum", "GMSImageProcessing::GetMean"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=True, allow_nan=False), encoding="utf-8")


def fake_child(script, state_path):
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    calls, images, documents = [], {}, []
    creating = Path(script).name == CREATE.name

    class Image:
        def __init__(self, image_id, values, entry=None):
            self.image_id, self.values = image_id, np.array(values, copy=True)
            self.entry = entry or {"label": LABELS[len(images)]}
            self.name = self.entry.get("name", "unset")
            self.axes = copy.deepcopy(self.entry.get("calibration", [
                {"dm_axis": 0, "origin": 0., "raw_origin": 11., "scale": 1., "unit": ""},
                {"dm_axis": 1, "origin": 0., "raw_origin": -7., "scale": 1., "unit": ""}]))
            self.intensity = copy.deepcopy(self.entry.get("intensity_calibration",
                                                       {"origin": 0., "scale": 1., "unit": ""}))

        def call(self, method):
            calls.append({"method": method, "id": self.image_id})
            fault = state.get("fault", {})
            if fault.get("label", self.entry["label"]) == self.entry["label"] and fault.get("method") == method:
                raise RuntimeError("fake injected " + method + " exception")

        def IsValid(self):
            self.call("IsValid")
            return True

        def GetID(self):
            self.call("GetID")
            return self.image_id

        def GetName(self):
            self.call("GetName")
            return self.name

        def GetNumArray(self):
            self.call("GetNumArray")
            actual = self.values.copy()
            if state.get("mutate_pixels") == self.entry["label"]:
                actual[0, 0] += 1
            return actual

        def SetName(self, name):
            if not creating:
                raise AssertionError("oracle must not set names")
            self.call("SetName")
            self.name = name

        def SetDimensionCalibration(self, axis, origin, scale, unit, style):
            if not creating or style != 0:
                raise AssertionError("unexpected spatial setter")
            self.call("SetDimensionCalibration")
            self.axes[axis].update(origin=origin, scale=scale, unit=unit)

        def GetDimensionCalibration(self, axis, style):
            self.call("GetDimensionCalibration")
            item = self.axes[axis]
            origin = item["origin" if style == 0 else "raw_origin"]
            if state.get("mutate_spatial") == self.entry["label"]:
                origin += .25
            if style == 1 and state.get("mutate_raw_origin") == self.entry["label"]:
                origin += .5
            unit = b"nm" if state.get("bytes_unit") else item["unit"]
            return origin, item["scale"], unit

        def SetIntensityOrigin(self, origin):
            if not creating:
                raise AssertionError("oracle must not set intensity")
            self.call("SetIntensityOrigin")
            self.intensity["origin"] = origin

        def SetIntensityScale(self, scale):
            if not creating:
                raise AssertionError("oracle must not set intensity")
            self.call("SetIntensityScale")
            if not state.get("ignore_intensity_setter"):
                self.intensity["scale"] = scale

        def SetIntensityUnitString(self, unit):
            if not creating:
                raise AssertionError("oracle must not set intensity")
            self.call("SetIntensityUnitString")
            self.intensity["unit"] = unit

        def GetIntensityOrigin(self):
            self.call("GetIntensityOrigin")
            return self.intensity["origin"]

        def GetIntensityScale(self):
            self.call("GetIntensityScale")
            return self.intensity["scale"] + (1 if state.get("mutate_intensity") == self.entry["label"] else 0)

        def GetIntensityUnitString(self):
            self.call("GetIntensityUnitString")
            return b"arb" if state.get("bytes_intensity_unit") else self.intensity["unit"]

        def GetOrCreateImageDocument(self):
            if not creating:
                raise AssertionError("oracle must not create documents")
            self.call("GetOrCreateImageDocument")
            return Document(self)

    class Document:
        def __init__(self, image):
            self.image = image

        def Show(self):
            self.image.call("Show")
            if self.image.image_id not in documents:
                documents.append(self.image.image_id)

    def count():
        calls.append({"method": "CountImageDocumentsOfAllWorkspaces"})
        return state.get("document_count", 2) + len(documents)

    def create(values):
        if not creating:
            raise AssertionError("oracle must not create images")
        image = Image(201 + len(images), values)
        images[image.image_id] = image
        image.call("CreateImage")
        return image

    def find(image_id):
        if creating:
            raise AssertionError("fixture may not access existing images")
        calls.append({"method": "FindImageByID", "id": image_id})
        return images.get(image_id)

    if not creating:
        for entry in state["images"]:
            with open(entry["source_npy"], "rb") as source:
                array = np.load(source, allow_pickle=False)
            images[entry["id"]] = Image(entry["id"], array, entry)
    fake = types.ModuleType("DigitalMicrograph")
    fake.CreateImage = create
    fake.FindImageByID = find
    fake.CountImageDocumentsOfAllWorkspaces = count
    sys.modules["DigitalMicrograph"] = fake
    try:
        # Production has no PID override; only this fake child patches the API.
        with mock.patch("os.getpid", return_value=state.get("process_pid", 101)):
            runpy.run_path(script, run_name="__main__")
    finally:
        dump(state["calls_path"], calls)


def make_metadata(entry):
    usable = entry["label"] != "RAW_UNITS"
    return {"id": entry["id"], "name": entry["name"], "ndim": 2,
            "data_type_code": 2, "dtype": "float32", "shape": [2, 3], "dm_dimensions": [3, 2],
            "shape_order": "numpy (last axis is X)", "pixels": 6,
            "native_mean_supported": True, "native_summary_supported": True,
            "coordinate_rule": "physical(i)=calibrated_value_at_pixel_zero+i*scale",
            "calibration_complete": usable,
            "calibration": [{"dm_dimension": axis["dm_axis"], "numpy_axis": 1 - axis["dm_axis"],
                             "size": [3, 2][axis["dm_axis"]], "origin": axis["raw_origin"],
                             "calibrated_value_at_pixel_zero": axis["origin"], "scale": axis["scale"],
                             "unit": axis["unit"] or None, "usable": usable,
                             "issue": None if usable else "unknown_units"} for axis in entry["calibration"]]}


class NativeSummaryOracleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="native-summary-fake-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.acceptance_dir = self.directory / "summary-acceptance"
        self.acceptance_dir.mkdir()
        self.truth_path = self.directory / "summary-truth.json"
        self.output = self.directory / "summary-independent.json"

    def prepare(self):
        base = np.array([[1.25, -2.5, 3.75], [8., -9.5, .125]], dtype=np.float32)
        arrays = [base.copy(), base.copy(), base.copy(),
                  np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint16), base.copy()]
        arrays[4][1, 1] = np.nan
        self.truth = {"schema": 1, "status": "RECORDED", "kind": "synthetic-only",
                      "python_is_listener": False, "session": SESSION, "host_pid": 101,
                      "initial_document_count": 7, "images": []}
        for index, (label, array) in enumerate(zip(LABELS, arrays)):
            path = self.directory / (label + ".npy")
            with path.open("xb") as source:
                np.save(source, array, allow_pickle=False)
            unit = "" if label == "RAW_UNITS" else "nm"
            entry = {"id": 201 + index, "label": label, "name": "SUMMARY_" + label,
                     "dtype": str(array.dtype), "shape": [2, 3], "finite": label != "NONFINITE",
                     "source_npy": str(path), "source_file_sha256": sha(path),
                     "pixel_sha256": hashlib.sha256(array.tobytes(order="C")).hexdigest(),
                     "calibration": [{"dm_axis": 0, "origin": 1.25, "raw_origin": 11., "scale": -.25, "unit": unit},
                                     {"dm_axis": 1, "origin": -2.5, "raw_origin": -7., "scale": .5, "unit": unit}],
                     "intensity_calibration": {"origin": 7.5, "scale": -2., "unit": "arb"}
                     if label == "CALIBRATED_INTENSITY" else {"origin": 0., "scale": 1., "unit": "counts"}}
            if index < 3:
                entry["expected_summary"] = dict(HAND)
            self.truth["images"].append(entry)
        dump(self.truth_path, self.truth)
        self.ledger = []
        self.acceptance = {"status": "PASS", "backend": "digitalmicrograph-native", "fixture_kind": "synthetic-only",
                           "session": SESSION, "host_pid": 101, "host_thread": 303, "worker_tid": 202,
                           "truth_sha256": sha(self.truth_path), "initial_document_count": 7,
                           "fixture_files_unchanged": True, "same_session_query_recovery": True,
                           "valid_request_after_safe_errors": True, "nontrivial_intensity_calibration_compared": True,
                           "raw_units_limitation_checked": True, "source_invariance": "NOT_TESTED_BY_CLIENT",
                           "independent_source_oracle_required": True, "node_exit_code": 0, "checks": []}

        def call(tool, label, op, args, output, error=None):
            request_id = "summary-%032x" % (len(self.ledger) + 1)
            arguments = {"request_id": request_id}
            if op == "SUMMARY":
                arguments["image_id"] = args[0]
            self.ledger.append({"protocol": "NB1", "session": SESSION, "id": request_id, "op": op,
                                "args": args, "host_pid": 101, "tool": tool, "arguments": arguments,
                                "wire": "NB1 %s %s %s%s\n" % (SESSION, request_id, op,
                                            " " + " ".join(str(value) for value in args) if args else "")})
            native = {"protocol": "NB1", "session": SESSION, "id": request_id, "request_id": request_id,
                      "state": "failed" if error else "completed", "host_pid": 101,
                      "worker_tid": 202, "exec_tid": 303, "timings_us": {"queue": 1, "execute": 2}}
            if error:
                native.update(code="native_error", error=error)
                output = {"error": error}
            else:
                output.update(backend="digitalmicrograph-native")
            output["native_receipt"] = native
            check = {"tool": tool, "label": label, "arguments": arguments, "output": output}
            if error:
                check["expected_error"] = error
            self.acceptance["checks"].append(check)
            return check

        call("dm_status", None, "STATUS", [], {"ready": True, "binary_gate": True, "host_pid": 101,
             "supported_build": "3.53.4137.0-x64",
             "host_thread": 303, "build_error": None, "requires_idle_host": True,
             "resident_python_required": False, "arbitrary_script": False, "capabilities": ["summary_float32_2d"]})
        call("dm_datasets", None, "DATASETS", [], {"datasets": [make_metadata(e) for e in self.truth["images"][:3]]})

        def result(entry):
            output = dict(HAND, image_id=entry["id"], image=make_metadata(entry), operators=OPERATORS,
                          computation="DM native", intensity_calibration_applied=False,
                          intensity_semantics="raw pixel intensity", source_write_requested=False, snapshot_atomic=False)
            return output

        for entry in self.truth["images"][:3]:
            check = call("dm_native_summary", entry["label"], "SUMMARY", [entry["id"]], result(entry))
            self.acceptance["checks"].append({"tool": "dm_native_result", "label": entry["label"],
                "arguments": {"request_id": check["arguments"]["request_id"]}, "output": copy.deepcopy(check["output"])})
        for label, image_id, error in (("UINT16", 204, "native_summary_requires_float32_2d"),
                                      ("NONFINITE", 205, "native_summary_nonfinite_result"),
                                      ("MISSING", 0xffffffff, "image_not_found")):
            call("dm_native_summary", label, "SUMMARY", [image_id], {}, error)
        call("dm_native_summary", "DEFAULT_AFTER_ERRORS", "SUMMARY", [201], result(self.truth["images"][0]))
        self.save_acceptance()
        return {"images": self.truth["images"], "document_count": 7}

    def save_acceptance(self):
        dump(self.acceptance_dir / "summary.json", self.acceptance)
        (self.acceptance_dir / "requests.jsonl").write_text(
            "".join(json.dumps(record) + "\n" for record in self.ledger), encoding="utf-8")

    def run_script(self, script=VERIFY, state=None, session=SESSION):
        state = dict(state or {})
        state["calls_path"] = str(self.directory / "fake-calls.json")
        state_path = self.directory / "fake-state.json"
        dump(state_path, state)
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.update(DM_NATIVE_SESSION=session, DM_NATIVE_EVIDENCE_DIR=str(self.directory),
                   PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
        for key in ("DM_NATIVE_SUMMARY_TRUTH", "DM_NATIVE_SUMMARY_ACCEPTANCE_DIR"):
            env.pop(key, None)
        child = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()),
                                "--run-summary-script", str(script), str(state_path)],
                               env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        path = self.truth_path if script == CREATE else self.output
        report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        calls = json.loads(Path(state["calls_path"]).read_text(encoding="utf-8"))
        return child, report, calls

    def assert_fail(self, child, report):
        self.assertNotEqual(child.returncode, 0, child.stderr)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("error", report)
        self.assertNotIn(b"oracle PASS", child.stdout)

    def test_fixture_records_actual_host_hand_known_truth_and_independent_files(self):
        child, report, calls = self.run_script(CREATE)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(report["status"], "RECORDED")
        self.assertEqual(report["host_pid"], 101)
        self.assertEqual(report["initial_document_count"], 7)
        self.assertIs(report["python_is_listener"], False)
        self.assertEqual([entry["label"] for entry in report["images"]], list(LABELS))
        for entry in report["images"]:
            self.assertEqual(sha(entry["source_npy"]), entry["source_file_sha256"])
            self.assertEqual(entry["calibration"][0]["raw_origin"], 11.)
            if entry["label"] in LABELS[:3]:
                self.assertEqual(entry["expected_summary"], HAND)
            else:
                self.assertNotIn("expected_summary", entry)
        self.assertEqual(report["images"][1]["intensity_calibration"], {"origin": 7.5, "scale": -2., "unit": "arb"})
        self.assertEqual(sum(c["method"] == "Show" for c in calls), 5)
        self.assertFalse(any(c["method"] == "FindImageByID" for c in calls))

    def test_fixture_intensity_api_errors_and_ignored_setter_preserve_fail_truth(self):
        for fault in ({"fault": {"method": "SetIntensityScale", "label": "CALIBRATED_INTENSITY"}},
                      {"ignore_intensity_setter": True}, {"bytes_intensity_unit": True}):
            with self.subTest(fault=fault):
                child, report, calls = self.run_script(CREATE, fault)
                self.assert_fail(child, report)
                self.assertNotEqual(report["status"], "PASS")
                for path in self.directory.glob("summary_*.npy"):
                    path.unlink()
                self.truth_path.unlink()

    def test_positive_oracle_checks_every_source_without_mutation_calls(self):
        state = self.prepare()
        before = {entry["source_npy"]: sha(entry["source_npy"]) for entry in self.truth["images"]}
        child, report, calls = self.run_script(state=state)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(len(report["sources"]), 5)
        self.assertEqual(report["truth_sha256"], sha(self.truth_path))
        self.assertEqual(report["ui_observation"], "NOT_TESTED")
        self.assertEqual(report["unicode_qualification"], "NOT_QUALIFIED")
        self.assertEqual(before, {path: sha(path) for path in before})
        self.assertFalse(any(c["method"].startswith("Set") or c["method"] in
                             ("CreateImage", "GetOrCreateImageDocument", "Show", "Close") for c in calls))
        self.assertEqual(sum(c["method"] == "GetDimensionCalibration" for c in calls), 20)

    def test_wrong_host_or_session_is_rejected_before_any_dm_access(self):
        state = self.prepare()
        state["process_pid"] = 999
        child, report, calls = self.run_script(state=state)
        self.assert_fail(child, report)
        self.assertEqual(calls, [])
        self.output.unlink()
        state["process_pid"] = 101
        child, report, calls = self.run_script(state=state, session="f" * 32)
        self.assert_fail(child, report)
        self.assertEqual(calls, [])

    def test_receipt_scalar_metadata_and_ledger_faults_cannot_pass(self):
        state = self.prepare()
        original, ledger = copy.deepcopy(self.acceptance), copy.deepcopy(self.ledger)
        faults = [
            lambda a, l: a["checks"][0]["output"].update(supported_build="wrong-build"),
            lambda a, l: a["checks"][2]["output"].update(sum=99.),
            lambda a, l: a["checks"][2]["output"]["native_receipt"].update(session="f" * 32),
            lambda a, l: a["checks"][2]["output"]["native_receipt"].update(host_pid=999),
            lambda a, l: a["checks"][2]["output"]["native_receipt"].update(state="unknown"),
            lambda a, l: a["checks"][2]["output"].update(image_id=999),
            lambda a, l: a["checks"][2]["output"]["image"]["calibration"][0].update(scale=.25),
            lambda a, l: a["checks"][3]["output"].update(mean=99.),
            lambda a, l: a.update(truth_sha256="f" * 64),
            lambda a, l: a.update(session="f" * 32),
            lambda a, l: a.update(status="FAIL"),
            lambda a, l: a["checks"][8]["output"]["native_receipt"].update(error="unknown"),
            lambda a, l: l[2].update(wire="NB1 wrong\n"),
            lambda a, l: l[2].update(host_pid=999),
            lambda a, l: l[2]["arguments"].update(image_id=999),
            lambda a, l: l.pop(),
        ]
        for index, fault in enumerate(faults):
            with self.subTest(fault=index):
                self.acceptance, self.ledger = copy.deepcopy(original), copy.deepcopy(ledger)
                fault(self.acceptance, self.ledger)
                self.save_acceptance()
                child, report, calls = self.run_script(state=state)
                self.assert_fail(child, report)
                self.assertEqual(calls, [])
                self.output.unlink()

    def test_live_pixels_spatial_intensity_documents_and_getter_errors_cannot_pass(self):
        original = self.prepare()
        faults = [{"mutate_pixels": "DEFAULT"}, {"mutate_spatial": "RAW_UNITS"},
                  {"mutate_raw_origin": "DEFAULT"},
                  {"mutate_intensity": "CALIBRATED_INTENSITY"}, {"document_count": 8},
                  {"fault": {"method": "GetIntensityScale", "label": "DEFAULT"}},
                  {"bytes_unit": True}, {"bytes_intensity_unit": True}]
        for fault in faults:
            with self.subTest(fault=fault):
                state = dict(original, **fault)
                child, report, calls = self.run_script(state=state)
                self.assert_fail(child, report)
                self.assertTrue(calls)
                self.output.unlink()

    def test_source_npy_tampering_and_duplicate_json_key_fail_before_dm(self):
        state = self.prepare()
        source = Path(self.truth["images"][0]["source_npy"])
        original = source.read_bytes()
        source.write_bytes(original + b"tampered")
        child, report, calls = self.run_script(state=state)
        self.assert_fail(child, report)
        self.assertIn("source file hash", report["error"])
        self.assertEqual(calls, [])
        self.output.unlink()
        source.write_bytes(original)
        path = self.acceptance_dir / "requests.jsonl"
        path.write_text(path.read_text(encoding="utf-8").replace('{"protocol":', '{"id":"duplicate","protocol":', 1), encoding="utf-8")
        child, report, calls = self.run_script(state=state)
        self.assert_fail(child, report)
        self.assertIn("Duplicate JSON key", report["error"])
        self.assertEqual(calls, [])

    def test_prior_fixture_or_oracle_evidence_is_never_overwritten_or_reexecuted(self):
        old = b'{"status":"FAIL","old":"must remain"}'
        self.truth_path.write_bytes(old)
        child, _, calls = self.run_script(CREATE)
        self.assertNotEqual(child.returncode, 0)
        self.assertEqual(self.truth_path.read_bytes(), old)
        self.assertEqual(calls, [])
        self.truth_path.unlink()
        state = self.prepare()
        self.output.write_bytes(old)
        child, _, calls = self.run_script(state=state)
        self.assertNotEqual(child.returncode, 0)
        self.assertEqual(self.output.read_bytes(), old)
        self.assertEqual(calls, [])

    def test_prior_source_npy_is_never_overwritten(self):
        path = self.directory / "summary_default.npy"
        old = b"old evidence must remain byte exact"
        path.write_bytes(old)
        child, report, calls = self.run_script(CREATE)
        self.assert_fail(child, report)
        self.assertEqual(path.read_bytes(), old)
        self.assertTrue(calls)

    def test_python37_syntax_and_no_runtime_reduction_fallback(self):
        for path in (CREATE, VERIFY):
            if sys.version_info >= (3, 8):
                ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 7))
            else:
                ast.parse(path.read_text(encoding="utf-8"))
            text = path.read_text(encoding="utf-8")
            for forbidden in ("np.mean(", "np.sum(", "np.min(", "np.max(", "GetIntensityCalibration("):
                self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--run-summary-script":
        fake_child(sys.argv[2], sys.argv[3])
    else:
        unittest.main()
