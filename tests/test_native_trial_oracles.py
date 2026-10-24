"""Offline fault injection for the actual one-shot native trial scripts.

Every target runs in a fresh Python subprocess with an explicitly installed
fake DigitalMicrograph module. No real host module, process, pipe or GUI is
accessed. Oracle inputs are independently constructed arrays and temp records,
not outputs of the fixture creator or native mean/crop implementation.
"""
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
SCRIPTS = ROOT / "experiments" / "native-bridge" / "mvp"
SESSION = "0123456789abcdef0123456789abcdef"
OTHER_SESSION = "fedcba9876543210fedcba9876543210"
CROP_ID = 901


def _dump(path, record):
    Path(path).write_text(json.dumps(record, allow_nan=False), encoding="utf-8")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _run_fake_host(script, state_path):
    """Child-only fake; install it before runpy can import the host module."""
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    calls = []
    images = {}
    documents = []
    creator = state.get("mode") == "creator"

    def forbidden(name):
        calls.append("FORBIDDEN:" + name)
        raise AssertionError("READ_ONLY_ORACLE_CALLED_MUTATION:" + name)

    class Image:
        def __init__(self, image_id, array, calibration=None, valid=True, returned_id=None):
            self.image_id = image_id
            self.array = array
            self.calibration = calibration or [[0.0, 1.0, ""], [0.0, 1.0, ""]]
            self.valid = valid
            self.returned_id = image_id if returned_id is None else returned_id
            self.name = "synthetic"

        def IsValid(self):
            return self.valid

        def GetID(self):
            return self.returned_id

        def GetNumArray(self):
            return self.array

        def GetDimensionCalibration(self, axis, style):
            zero, scale, unit = self.calibration[axis]
            if style == 1:
                return -zero / scale, scale, unit
            return zero, scale, unit

        def SetDimensionCalibration(self, axis, zero, scale, unit, style):
            if not creator:
                return forbidden("SetDimensionCalibration")
            self.calibration[axis] = [zero, scale, unit]

        def SetName(self, name):
            if not creator:
                return forbidden("SetName")
            self.name = name

        def GetName(self):
            return self.name

        def GetOrCreateImageDocument(self):
            if not creator:
                return forbidden("GetOrCreateImageDocument")
            document = Document([self])
            documents.append(document)
            return document

        def Show(self):
            return forbidden("Image.Show")

        def Close(self):
            return forbidden("Image.Close")

    class Document:
        def __init__(self, members):
            self.members = members

        def CountImages(self):
            return len(self.members)

        def GetImage(self, position):
            return self.members[position]

        def Show(self):
            if not creator:
                return forbidden("Document.Show")
            calls.append("creator.Show")

        def Close(self):
            return forbidden("Document.Close")

    def create_image(values):
        if not creator:
            return forbidden("CreateImage")
        calls.append("creator.CreateImage")
        actual = np.array(values, copy=True)
        if np.isnan(actual).any():
            mutation = state.get("create_mutation")
            if mutation == "nan_to_zero":
                actual[np.isnan(actual)] = 0
            elif mutation == "nan_to_posinf":
                actual[np.isnan(actual)] = np.inf
            elif mutation == "nan_to_neginf":
                actual[np.isnan(actual)] = -np.inf
            elif mutation == "finite_to_posinf":
                actual.flat[0] = np.inf
            elif mutation == "finite_to_neginf":
                actual.flat[0] = -np.inf
        image = Image(100 + len(images), actual)
        images[image.image_id] = image
        return image

    # Arrays are loaded independently; a view is introduced only in the
    # deliberately aliased-crop case, rather than simulated via a flag.
    for entry in state.get("images", []):
        if "view_of" in entry:
            x0, y0, x1, y1 = entry["rect"]
            array = images[entry["view_of"]].array[y0:y1, x0:x1]
        else:
            array = np.load(entry["array"], allow_pickle=False)
        images[entry["id"]] = Image(entry["id"], array, entry["calibration"],
                                   entry.get("valid", True), entry.get("returned_id"))
    for members in state.get("documents", []):
        documents.append(Document([images[image_id] for image_id in members]))

    fake = types.ModuleType("DigitalMicrograph")
    fake.__offline_native_trial_fake__ = True
    fake.FindImageByID = lambda image_id: images.get(image_id)
    fake.CountImageDocumentsOfAllWorkspaces = lambda: state.get("document_count", len(documents))
    fake.GetImageDocumentOfAllWorkspaces = lambda position: documents[position]
    fake.CreateImage = create_image
    fake.Show = lambda *args: forbidden("Show")
    fake.Close = lambda *args: forbidden("Close")
    fake.DeleteImage = lambda *args: forbidden("DeleteImage")
    sys.modules["DigitalMicrograph"] = fake
    try:
        # This is an explicit child-only simulation of the hosting process.
        # Production oracles have no PID environment override.
        with mock.patch("os.getpid", return_value=state.get("process_pid", 101)):
            runpy.run_path(str(script), run_name="__main__")
    finally:
        _dump(Path(state_path).with_name("fake-calls.json"), calls)


class NativeTrialOracleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-trial-oracles-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.base_directory = self.directory
        self.case_index = 0
        self.state_path = self.directory / "fake-state.json"
        self.truth_path = self.directory / "trial-answers.json"
        self.summary_path = self.directory / "trial-acceptance" / "summary.json"
        self.summary_path.parent.mkdir()

    def _receipt(self, request_id):
        return {"protocol": "NB1", "session": SESSION, "id": request_id,
                "request_id": request_id, "state": "completed", "host_pid": 101,
                "worker_tid": 202, "exec_tid": 303,
                "timings_us": {"queue": 3, "execute": 7}}

    def _stop(self):
        return {"protocol": "NB1", "session": SESSION, "id": "stop-synthetic",
                "state": "completed", "host_pid": 101, "worker_tid": 202,
                "exec_tid": 0, "timings_us": {"queue": 0, "execute": 0},
                "result": {"ipc_stopped": True}}

    def _stop_request(self):
        return {"protocol": "NB1", "session": SESSION, "id": "stop-synthetic", "op": "STOP",
                "args": [], "host_pid": 101, "wire": "NB1 %s stop-synthetic STOP\n" % SESSION}

    def prepare(self, after_stop=False, closed=False):
        self.case_index += 1
        self.directory = self.base_directory / ("case-%03d" % self.case_index)
        self.directory.mkdir()
        self.state_path = self.directory / "fake-state.json"
        self.truth_path = self.directory / "trial-answers.json"
        self.summary_path = self.directory / "trial-acceptance" / "summary.json"
        self.summary_path.parent.mkdir()
        # Hard-coded, asymmetric arrays are unrelated to the creator's ramp.
        source = np.array([[-9, -3.5, 2, 1.5, 8, 4],
                           [7.5, -1.25, 0.5, 12, -6.5, 2],
                           [3.25, -8, 4.5, 9, -2, 11.5],
                           [-4.5, 6.25, 5, -7, 10.5, 0]], dtype=np.float32)
        raw = np.array([[2.5, -4, 8], [-1.5, 6, -2]], dtype=np.float32)
        integer = np.array([[1, 4, 9], [16, 25, 36]], dtype=np.uint16)
        nonfinite = np.array([[np.nan, np.inf, -np.inf], [1, -2, 3]], dtype=np.float32)
        arrays = [("CAL", 11, source, "nm"), ("RAW", 22, raw, ""),
                  ("UINT16", 33, integer, "nm"), ("NONFINITE", 44, nonfinite, "nm")]
        self.truth = {"session": SESSION, "kind": "synthetic-only", "python_is_listener": False,
                      "images": [], "crop_rect": [1, 1, 5, 4], "initial_document_count": 4}
        self.state = {"mode": "oracle", "images": [], "documents": []}
        for label, image_id, array, unit in arrays:
            path = self.directory / (label.lower() + ".npy")
            np.save(str(path), array, allow_pickle=False)
            calibration = [[6.25, -0.5, unit], [-3.5, 1.25, unit]]
            entry = {"label": label, "id": image_id, "shape": list(array.shape),
                     "dtype": str(array.dtype), "source_npy": str(path),
                     "pixel_sha256": _sha(array.tobytes(order="C")),
                     "source_file_sha256": _sha(path.read_bytes()),
                     "calibration": [{"dm_axis": axis, "origin": zero, "scale": scale,
                                      "raw_origin": -zero / scale, "unit": axis_unit}
                                     for axis, (zero, scale, axis_unit) in enumerate(calibration)]}
            self.truth["images"].append(entry)
            self.state["images"].append({"id": image_id, "array": str(path),
                                          "calibration": calibration})
            self.state["documents"].append([image_id])
        self.crop_array = np.array(source[1:4, 1:5], copy=True)
        self.crop_path = self.directory / "delivered-crop.npy"
        np.save(str(self.crop_path), self.crop_array, allow_pickle=False)
        if not closed:
            self.state["images"].append({"id": CROP_ID, "array": str(self.crop_path),
                                          "calibration": [[5.75, -0.5, "nm"], [-2.25, 1.25, "nm"]]})
            self.state["documents"].append([CROP_ID])
        self.summary = {"status": "PASS", "session": SESSION,
                        "checks": [{"tool": "dm_status", "output": {
                            "backend": "digitalmicrograph-native", "ready": True, "binary_gate": True,
                            "host_pid": 101, "host_thread": 303,
                            "native_receipt": self._receipt("status-synthetic")}}],
                        "crop": {"backend": "digitalmicrograph-native",
                                 "image_id": CROP_ID, "source_image_id": 11,
                                 "image": {"id": CROP_ID},
                                 "requested_rect": [1, 1, 5, 4], "effective_rect": [1, 1, 5, 4],
                                 "native_receipt": self._receipt("crop-synthetic")},
                        "delivery": {"backend": "digitalmicrograph-native",
                                     "image_id": CROP_ID, "delivery": "visible_dm_document",
                                     "document_visible": True, "file_saved": False,
                                     "model_visual_verification": False,
                                     "native_receipt": self._receipt("show-synthetic")},
                        "repeated_show": {"backend": "digitalmicrograph-native",
                                          "image_id": CROP_ID, "delivery": "visible_dm_document",
                                          "document_visible": True, "file_saved": False,
                                          "model_visual_verification": False,
                                          "native_receipt": self._receipt("show-again")}}
        if after_stop or closed:
            _dump(self.directory / "stop-request.json", self._stop_request())
            _dump(self.directory / "stop-receipt.json", self._stop())
        self.save_records()
        if closed:
            _dump(self.directory / "trial-independent-after_stop.json",
                  {"status": "PASS", "session": SESSION, "phase": "after_stop", "image_id": CROP_ID,
                   "oracle_mode": "strict", "host_pid": 101, "stop_request_verified": True,
                   "backend": "digitalmicrograph-native", "crop_all_pixels_equal": True,
                   "crop_independent_memory": True, "ordinary_python_success": True,
                   "matching_documents": 1, "total_documents": 5,
                   "truth_sha256": _sha(self.truth_path.read_bytes()),
                   "summary_sha256": _sha(self.summary_path.read_bytes()),
                   "stop_request_sha256": _sha((self.directory / "stop-request.json").read_bytes()),
                   "stop_receipt_sha256": _sha((self.directory / "stop-receipt.json").read_bytes())})

    def save_records(self):
        _dump(self.truth_path, self.truth)
        _dump(self.summary_path, self.summary)
        _dump(self.state_path, self.state)

    def run_script(self, script="verify_trial.py", success=True, phase="before_stop", expected_error=None,
                   mode="strict", protocol="NB1_LEGACY"):
        _dump(self.state_path, self.state)
        env = dict(os.environ, DM_NATIVE_SESSION=SESSION, DM_NATIVE_EVIDENCE_DIR=str(self.directory),
                   PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", DM_NATIVE_ORACLE_MODE=mode)
        if protocol is None:
            env.pop("DM_NATIVE_ORACLE_PROTOCOL", None)
        else:
            env["DM_NATIVE_ORACLE_PROTOCOL"] = protocol
        # The runner injects sys.modules before target imports. Do not add a
        # real GMS module directory to PYTHONPATH even if inherited locally.
        env.pop("PYTHONPATH", None)
        prefix = "trial-observation-" if mode == "observe_legacy_stop" else "trial-independent-"
        target = self.directory / (prefix + phase + ".json")
        if script == "create_trial_fixture.py":
            target = self.truth_path
        prior_json = {path: path.read_bytes() for path in self.directory.rglob("*.json")
                      if path.name not in {"fake-state.json", "fake-calls.json"}}
        result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()),
                                 "--run-trial-script", str(SCRIPTS / script), str(self.state_path)],
                                cwd=str(self.directory), env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=15)
        output = result.stdout.decode("utf-8", "replace") + result.stderr.decode("utf-8", "replace")
        calls = json.loads(self.state_path.with_name("fake-calls.json").read_text(encoding="utf-8"))
        self.assertFalse([call for call in calls if call.startswith("FORBIDDEN:")], output)
        if success:
            self.assertEqual(result.returncode, 0, output)
            self.assertTrue(target.is_file(), output)
            report = json.loads(target.read_text(encoding="utf-8"))
            if script != "create_trial_fixture.py":
                self.assertEqual(report["status"], "UNVERIFIED" if mode == "observe_legacy_stop" else "PASS")
                self.assertEqual(report["session"], SESSION)
                self.assertEqual(report["host_pid"], self.state.get("process_pid", 101))
                self.assertEqual(report["oracle_mode"], mode)
                if mode == "observe_legacy_stop":
                    self.assertNotIn("PASS", result.stdout.decode("utf-8", "replace"))
                    self.assertFalse((self.directory / ("trial-independent-" + phase + ".json")).exists())
            return report
        self.assertIsNotNone(expected_error, "Every injection must identify the intended failing check")
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("RuntimeError: " + expected_error, output)
        self.assertFalse(target.exists(), "Failed injection wrote accepted evidence: " + output)
        self.assertNotIn("PASS:", result.stdout.decode("utf-8", "replace"))
        for path, content in prior_json.items():
            self.assertEqual(path.read_bytes(), content, "Failed injection modified earlier evidence")
        return output

    def test_positive_before_after_stop_and_closed(self):
        self.prepare()
        before = self.run_script()
        self.assertTrue(before["crop_all_pixels_equal"])
        np.testing.assert_array_equal(np.load(str(self.directory / "trial-crop.npy")), self.crop_array)
        _dump(self.directory / "stop-request.json", self._stop_request())
        _dump(self.directory / "stop-receipt.json", self._stop())
        after = self.run_script(phase="after_stop")
        self.assertEqual(after["image_id"], CROP_ID)
        self.state["images"] = [image for image in self.state["images"] if image["id"] != CROP_ID]
        self.state["documents"].pop()
        closed = self.run_script("verify_trial_closed.py", phase="after_close")
        self.assertTrue(closed["released_after_document_close"])

    def upgrade_nb2(self):
        for key, operation, args, result_type in (("status", "STATUS", [], "status"),
                ("crop", "CROP", [11] + self.truth["crop_rect"], "image_crop"),
                ("delivery", "SHOW", [CROP_ID], "image_delivery"), ("repeated_show", "SHOW", [CROP_ID], "image_delivery")):
            output = self.summary["checks"][0]["output"] if key == "status" else self.summary[key]
            output["native_receipt"].update(protocol="NB2", original_operation=operation, normalized_args=args,
                                            result_type=result_type, result_version=1)
        stop_path = self.directory / "stop-receipt.json"
        if stop_path.exists():
            stop = json.loads(stop_path.read_text(encoding="utf-8"))
            stop.update(protocol="NB2", original_operation="STOP", normalized_args=[], result_type="ipc_stop", result_version=1)
            _dump(stop_path, stop)
            request = self._stop_request()
            request.update(protocol="NB2", wire=request["wire"].replace("NB1 ", "NB2 ", 1))
            _dump(self.directory / "stop-request.json", request)
        self.save_records()
        post_path = self.directory / "trial-independent-after_stop.json"
        if post_path.exists():
            post = json.loads(post_path.read_text(encoding="utf-8"))
            post.update(protocol="NB2", protocol_mode="NB2")
            _dump(post_path, post)
            self.refresh_post_fingerprints()

    def test_nb2_positive_before_after_stop_and_closed_and_legacy_requires_opt_in(self):
        self.prepare()
        self.run_script(success=False, expected_error="Invalid status native receipt", protocol=None)
        self.upgrade_nb2()
        before = self.run_script(protocol=None)
        self.assertEqual(before["protocol"], "NB2")
        self.prepare(after_stop=True)
        self.upgrade_nb2()
        after = self.run_script(phase="after_stop", protocol="NB2")
        self.assertTrue(after["stop_request_verified"])
        self.state["images"] = [image for image in self.state["images"] if image["id"] != CROP_ID]
        self.state["documents"].pop()
        closed = self.run_script("verify_trial_closed.py", phase="after_close", protocol="NB2")
        self.assertEqual(closed["protocol_mode"], "NB2")

    def test_nb2_operation_args_type_version_and_stop_identity_reject_precisely(self):
        for phase in ("before_stop", "after_stop", "after_close"):
            for key, value in (("original_operation", "SHOW"), ("normalized_args", [999]),
                               ("result_type", "native_mean"), ("result_version", 2)):
                with self.subTest(phase=phase, key=key):
                    self.prepare(after_stop=phase != "before_stop", closed=phase == "after_close")
                    self.upgrade_nb2()
                    self.summary["crop"]["native_receipt"][key] = value
                    self.save_records()
                    self.refresh_post_fingerprints()
                    self.run_script("verify_trial_closed.py" if phase == "after_close" else "verify_trial.py",
                        success=False, phase=phase, expected_error="NB2 original operation/arguments/result schema mismatch", protocol="NB2")
        for closed in (False, True):
            self.prepare(after_stop=True, closed=closed)
            self.upgrade_nb2()
            stop_path = self.directory / "stop-receipt.json"
            stop = json.loads(stop_path.read_text(encoding="utf-8"))
            stop["original_operation"] = "STATUS"
            _dump(stop_path, stop)
            self.refresh_post_fingerprints()
            self.run_script("verify_trial_closed.py" if closed else "verify_trial.py", success=False,
                phase="after_close" if closed else "after_stop", expected_error="NB2 original operation/arguments/result schema mismatch", protocol="NB2")
        for key, value in (("protocol", "NB1"), ("session", OTHER_SESSION), ("state", "queued"), ("id", "different")):
            with self.subTest(closed_header=key):
                self.prepare(closed=True)
                self.upgrade_nb2()
                self.summary["crop"]["native_receipt"][key] = value
                self.save_records()
                self.refresh_post_fingerprints()
                self.run_script("verify_trial_closed.py", success=False, phase="after_close",
                    expected_error="NB2 closed native receipt correlation/state mismatch", protocol="NB2")

    def test_crop_pixels_dtype_shape_and_actual_shared_memory(self):
        for fault in ("zero_sum_pixels", "dtype", "shape", "shared_view"):
            with self.subTest(fault=fault):
                self.prepare()
                if fault == "zero_sum_pixels":
                    wrong = self.crop_array.copy()
                    wrong[0, 0] += 0.25
                    wrong[0, 1] -= 0.25
                    self.assertEqual(float(np.mean(wrong, dtype=np.float64)),
                                     float(np.mean(self.crop_array, dtype=np.float64)))
                    np.save(str(self.crop_path), wrong, allow_pickle=False)
                elif fault == "dtype":
                    np.save(str(self.crop_path), self.crop_array.astype(np.float64), allow_pickle=False)
                elif fault == "shape":
                    np.save(str(self.crop_path), self.crop_array.reshape(2, 6), allow_pickle=False)
                else:
                    self.state["images"][-1].update(view_of=11, rect=[1, 1, 5, 4])
                self.run_script(success=False,
                                expected_error="Delivered crop pixels/dtype/shape/independent memory mismatch")

    def test_crop_and_source_calibration_each_axis(self):
        for subject in ("source", "crop"):
            for axis in (0, 1):
                for field, replacement in ((0, 77.25), (1, 0.0), (1, 0.5), (2, "um")):
                    with self.subTest(subject=subject, axis=axis, field=field, replacement=replacement):
                        self.prepare()
                        image = self.state["images"][0 if subject == "source" else -1]
                        if replacement == image["calibration"][axis][field]:
                            replacement = -replacement
                        image["calibration"][axis][field] = replacement
                        self.run_script(success=False, expected_error=("Source calibration changed"
                            if subject == "source" else "Delivered crop physical calibration mismatch"))

    def test_source_and_independent_oracle_changes(self):
        for fault in ("source_pixels", "source_dtype", "source_shape", "oracle_bytes", "oracle_rewritten_hash"):
            with self.subTest(fault=fault):
                self.prepare()
                entry = self.truth["images"][1]
                path = Path(entry["source_npy"])
                if fault == "oracle_bytes":
                    path.write_bytes(path.read_bytes() + b"changed")
                else:
                    values = np.load(str(path), allow_pickle=False)
                    if fault == "source_dtype":
                        values = values.astype(np.float64)
                    elif fault == "source_shape":
                        values = values.reshape(3, 2)
                    else:
                        values[0, 0] += 1
                    changed = self.directory / "changed-source.npy"
                    np.save(str(changed), values, allow_pickle=False)
                    if fault == "oracle_rewritten_hash":
                        # Even a replacement file with a refreshed file hash
                        # must disagree with the originally saved pixel hash.
                        entry["source_npy"] = str(changed)
                        entry["source_file_sha256"] = _sha(changed.read_bytes())
                        self.save_records()
                    else:
                        self.state["images"][1]["array"] = str(changed)
                self.run_script(success=False, expected_error=("Independent oracle file changed"
                    if fault == "oracle_bytes" else "Source pixel/shape/dtype changed"))

    def test_missing_invalid_and_wrong_returned_image_ids(self):
        for image_id in (11, CROP_ID):
            for fault in ("missing", "invalid", "wrong_id"):
                with self.subTest(image_id=image_id, fault=fault):
                    self.prepare()
                    selected = next(image for image in self.state["images"] if image["id"] == image_id)
                    if fault == "missing":
                        self.state["images"].remove(selected)
                        self.state["documents"] = [doc for doc in self.state["documents"] if image_id not in doc]
                    elif fault == "invalid":
                        selected["valid"] = False
                    else:
                        selected["returned_id"] = image_id + 1000
                    self.run_script(success=False, expected_error=("Synthetic source identity lost"
                        if image_id == 11 else "Delivered crop no longer exists"))

    def test_missing_duplicate_crop_documents_and_wrong_total(self):
        for fault in ("missing", "duplicate", "wrong_total"):
            with self.subTest(fault=fault):
                self.prepare()
                if fault == "missing":
                    self.state["documents"][-1] = [22]
                elif fault == "duplicate":
                    self.state["documents"][0] = [11, CROP_ID]
                else:
                    self.state["documents"].append([22])
                self.run_script(success=False,
                                expected_error="SHOW did not reuse exactly one document for the explicit crop ID")

    def test_top_level_sessions_and_summary_status(self):
        for subject in ("truth", "summary"):
            for field, value in (("session", OTHER_SESSION), ("status", "FAIL")):
                if subject == "truth" and field == "status":
                    continue
                with self.subTest(subject=subject, field=field):
                    self.prepare()
                    getattr(self, subject)[field] = value
                    self.save_records()
                    self.run_script(success=False, expected_error="Session or actual-MCP acceptance mismatch")

    def test_nested_receipt_sessions_states_and_ids(self):
        for subject in ("crop", "delivery", "repeated_show"):
            for field, value in (("session", OTHER_SESSION), ("state", "queued"),
                                 ("id", "different-id"), ("request_id", "different-id")):
                with self.subTest(subject=subject, field=field):
                    self.prepare()
                    self.summary[subject]["native_receipt"][field] = value
                    self.save_records()
                    self.run_script(success=False, expected_error="Invalid " + subject + " native receipt")

    def test_crop_source_roi_and_show_image_binding(self):
        for subject, field, value in (("crop", "source_image_id", 22),
                                      ("crop", "effective_rect", [0, 0, 4, 3]),
                                      ("crop", "requested_rect", [0, 0, 4, 3]),
                                      ("delivery", "image_id", 22),
                                      ("repeated_show", "image_id", 22)):
            with self.subTest(subject=subject, field=field):
                self.prepare()
                self.summary[subject][field] = value
                self.save_records()
                self.run_script(success=False, expected_error=("Crop source/rectangle binding mismatch"
                    if subject == "crop" else "Show delivery/image binding mismatch"))

    def test_backend_and_receipt_host_thread_bindings(self):
        for subject in ("crop", "delivery", "repeated_show"):
            with self.subTest(subject=subject, fault="mock_backend"):
                self.prepare()
                self.summary[subject]["backend"] = "mock-native"
                self.save_records()
                self.run_script(success=False, expected_error="Native backend mismatch")
        for subject, field, value in (("crop", "host_pid", 999), ("delivery", "worker_tid", 999),
                                      ("repeated_show", "exec_tid", 999), ("crop", "exec_tid", 0),
                                      ("delivery", "exec_tid", 202), ("repeated_show", "host_pid", True)):
            with self.subTest(subject=subject, field=field, value=value):
                self.prepare()
                self.summary[subject]["native_receipt"][field] = value
                self.save_records()
                self.run_script(success=False, expected_error="Native receipt host/thread identity mismatch")

    def test_host_status_anchor_must_be_native_ready_and_valid(self):
        for field, value in (("backend", "mock-native"), ("ready", False),
                             ("binary_gate", False), ("host_pid", 0)):
            with self.subTest(field=field):
                self.prepare()
                self.summary["checks"][0]["output"][field] = value
                self.save_records()
                self.run_script(success=False, expected_error="Invalid native host status anchor")

    def test_stop_host_worker_and_execution_bindings(self):
        for closed in (False, True):
            for field, value in (("host_pid", 999), ("worker_tid", 999), ("exec_tid", 303)):
                with self.subTest(closed=closed, field=field):
                    self.prepare(after_stop=True, closed=closed)
                    stop = self._stop()
                    stop[field] = value
                    stop_path = self.directory / "stop-receipt.json"
                    _dump(stop_path, stop)
                    if closed:
                        # The prior oracle also accepted this wrong-host STOP
                        # before the fix. A matching SHA must not replace the
                        # independent comparison with the status anchor.
                        post_path = self.directory / "trial-independent-after_stop.json"
                        post = json.loads(post_path.read_text(encoding="utf-8"))
                        post["stop_receipt_sha256"] = _sha(stop_path.read_bytes())
                        _dump(post_path, post)
                    self.run_script("verify_trial_closed.py" if closed else "verify_trial.py",
                                    success=False, phase="after_close" if closed else "after_stop",
                                    expected_error="STOP host/thread identity mismatch")

    def test_after_close_requires_successful_independent_post_conditions(self):
        for field, value in (("crop_all_pixels_equal", False), ("crop_independent_memory", False),
                             ("ordinary_python_success", False), ("matching_documents", 2)):
            with self.subTest(field=field):
                self.prepare(closed=True)
                post_path = self.directory / "trial-independent-after_stop.json"
                post = json.loads(post_path.read_text(encoding="utf-8"))
                post[field] = value
                _dump(post_path, post)
                self.run_script("verify_trial_closed.py", success=False, phase="after_close",
                                expected_error="Required same-session post-STOP acceptance is missing")

    def refresh_post_fingerprints(self):
        observation = self.directory / "trial-observation-after_stop.json"
        post_path = observation if observation.exists() else self.directory / "trial-independent-after_stop.json"
        if not post_path.exists():
            return
        post = json.loads(post_path.read_text(encoding="utf-8"))
        for field, path in (("truth_sha256", self.truth_path), ("summary_sha256", self.summary_path),
                            ("stop_request_sha256", self.directory / "stop-request.json"),
                            ("stop_receipt_sha256", self.directory / "stop-receipt.json")):
            post[field] = _sha(path.read_bytes()) if path.exists() else None
        _dump(post_path, post)

    def test_self_consistent_foreign_host_does_not_match_actual_process(self):
        for phase in ("before_stop", "after_stop", "after_close"):
            with self.subTest(phase=phase):
                self.prepare(after_stop=phase != "before_stop", closed=phase == "after_close")
                status = self.summary["checks"][0]["output"]
                status["host_pid"] = 999
                for output in [status] + [self.summary[key] for key in ("crop", "delivery", "repeated_show")]:
                    output["native_receipt"]["host_pid"] = 999
                self.save_records()
                if phase != "before_stop":
                    stop = self._stop()
                    stop["host_pid"] = 999
                    _dump(self.directory / "stop-receipt.json", stop)
                    request = self._stop_request()
                    request["host_pid"] = 999
                    _dump(self.directory / "stop-request.json", request)
                if phase == "after_close":
                    post_path = self.directory / "trial-independent-after_stop.json"
                    post = json.loads(post_path.read_text(encoding="utf-8"))
                    post["host_pid"] = 999
                    _dump(post_path, post)
                    self.refresh_post_fingerprints()
                self.run_script("verify_trial_closed.py" if phase == "after_close" else "verify_trial.py",
                                success=False, phase=phase,
                                expected_error="Native host PID does not match this process")

    def test_original_stop_request_is_required_and_bound(self):
        faults = [("missing", None, "UNVERIFIED: original pre-submission STOP request record is missing"),
                  ("protocol", "other", "Invalid original STOP request record"),
                  ("session", OTHER_SESSION, "STOP request/receipt identity mismatch"),
                  ("id", "other-stop", "STOP request/receipt identity mismatch"),
                  ("op", "QUERY", "Invalid original STOP request record"),
                  ("args", [1], "Invalid original STOP request record"),
                  ("host_pid", 999, "STOP request/receipt identity mismatch"),
                  ("wire", "NB1 %s other-stop STOP\n" % SESSION, "STOP wire/request binding mismatch"),
                  ("wire", "NB1 %s stop-synthetic QUERY\n" % SESSION, "STOP wire/request binding mismatch"),
                  ("wire", "NB1 %s stop-synthetic STOP" % SESSION, "STOP wire/request binding mismatch")]
        for closed in (False, True):
            for field, value, reason in faults:
                with self.subTest(closed=closed, field=field, value=value):
                    self.prepare(after_stop=True, closed=closed)
                    path = self.directory / "stop-request.json"
                    if field == "missing":
                        path.unlink()
                    else:
                        request = self._stop_request()
                        request[field] = value
                        _dump(path, request)
                    self.refresh_post_fingerprints()
                    self.run_script("verify_trial_closed.py" if closed else "verify_trial.py",
                                    success=False, phase="after_close" if closed else "after_stop",
                                    expected_error=reason)

    def test_saved_request_without_acknowledgement_cannot_be_before_stop_pass(self):
        self.prepare()
        _dump(self.directory / "stop-request.json", self._stop_request())
        self.run_script(success=False, expected_error="UNVERIFIED: saved STOP request has no acknowledged receipt")

    def test_stop_receipt_id_is_bounded_and_matches_original(self):
        for closed in (False, True):
            for request_id, reason in (("other-stop", "STOP request/receipt identity mismatch"),
                                       ("", "Invalid STOP receipt"), ("bad id", "Invalid STOP receipt")):
                with self.subTest(closed=closed, request_id=request_id):
                    self.prepare(after_stop=True, closed=closed)
                    stop = self._stop()
                    stop["id"] = request_id
                    _dump(self.directory / "stop-receipt.json", stop)
                    self.refresh_post_fingerprints()
                    self.run_script("verify_trial_closed.py" if closed else "verify_trial.py",
                                    success=False, phase="after_close" if closed else "after_stop",
                                    expected_error=reason)

    def observation_post(self):
        path = self.directory / "trial-independent-after_stop.json"
        post = json.loads(path.read_text(encoding="utf-8"))
        post.update(status="UNVERIFIED", oracle_mode="observe_legacy_stop",
                    stop_request_verified=(self.directory / "stop-request.json").exists())
        _dump(self.directory / "trial-observation-after_stop.json", post)
        path.unlink()
        self.refresh_post_fingerprints()

    def test_observation_missing_or_complete_request_never_writes_pass(self):
        for keep_request in (False, True):
            with self.subTest(keep_request=keep_request):
                self.prepare(after_stop=True)
                if not keep_request:
                    (self.directory / "stop-request.json").unlink()
                post = self.run_script(phase="after_stop", mode="observe_legacy_stop")
                self.assertIs(post["stop_request_verified"], keep_request)
                self.assertTrue(post["crop_all_pixels_equal"])
                self.assertTrue(post["crop_independent_memory"])
                self.state["images"] = [image for image in self.state["images"] if image["id"] != CROP_ID]
                self.state["documents"].pop()
                closed = self.run_script("verify_trial_closed.py", phase="after_close", mode="observe_legacy_stop")
                self.assertIs(closed["stop_request_verified"], keep_request)
                self.assertTrue(closed["released_after_document_close"])
                self.assertFalse(list(self.directory.glob("trial-independent-*.json")))

    def test_strict_closed_never_consumes_observation_as_acceptance(self):
        for put_at_strict_path in (False, True):
            with self.subTest(put_at_strict_path=put_at_strict_path):
                self.prepare(closed=True)
                self.observation_post()
                if put_at_strict_path:
                    (self.directory / "trial-observation-after_stop.json").rename(
                        self.directory / "trial-independent-after_stop.json")
                self.run_script("verify_trial_closed.py", success=False, phase="after_close",
                                expected_error="Required same-session post-STOP acceptance is missing")

    def test_observation_does_not_bypass_existing_wrong_request_record(self):
        for closed in (False, True):
            for field, value, reason in (("op", "QUERY", "Invalid original STOP request record"),
                                         ("id", "other-stop", "STOP request/receipt identity mismatch"),
                                         ("wire", "wrong wire", "STOP wire/request binding mismatch")):
                with self.subTest(closed=closed, field=field):
                    self.prepare(after_stop=True, closed=closed)
                    request = self._stop_request()
                    request[field] = value
                    _dump(self.directory / "stop-request.json", request)
                    if closed:
                        self.observation_post()
                    self.run_script("verify_trial_closed.py" if closed else "verify_trial.py", success=False,
                                    phase="after_close" if closed else "after_stop", mode="observe_legacy_stop",
                                    expected_error=reason)

    def test_observation_requires_acknowledged_stop_and_actual_host_pid(self):
        for closed in (False, True):
            for fault in ("missing_stop", "wrong_actual_pid"):
                with self.subTest(closed=closed, fault=fault):
                    self.prepare(after_stop=True, closed=closed)
                    (self.directory / "stop-request.json").unlink()
                    if closed:
                        self.observation_post()
                    if fault == "missing_stop":
                        (self.directory / "stop-receipt.json").unlink()
                        reason = ("Required STOP receipt is missing" if closed else
                                  "Legacy STOP observation requires an acknowledged STOP receipt")
                    else:
                        self.state["process_pid"] = 999
                        reason = "Native host PID does not match this process"
                    self.run_script("verify_trial_closed.py" if closed else "verify_trial.py", success=False,
                                    phase="after_close" if closed else "after_stop", mode="observe_legacy_stop",
                                    expected_error=reason)

    def test_observation_still_checks_pixels_documents_and_remaining_sources(self):
        for fault, closed, reason in (("crop_pixels", False, "Delivered crop pixels/dtype/shape/independent memory mismatch"),
                                      ("duplicate_document", False, "SHOW did not reuse exactly one document for the explicit crop ID"),
                                      ("live_output", True, "Closed crop still has a live owner; do not claim final release"),
                                      ("source_calibration", True, "Synthetic source calibration changed")):
            with self.subTest(fault=fault):
                self.prepare(after_stop=True, closed=closed)
                (self.directory / "stop-request.json").unlink()
                if closed:
                    self.observation_post()
                if fault == "crop_pixels":
                    values = self.crop_array.copy()
                    values[0, 0] += 0.25
                    values[0, 1] -= 0.25
                    np.save(str(self.crop_path), values, allow_pickle=False)
                elif fault == "duplicate_document":
                    self.state["documents"][0].append(CROP_ID)
                elif fault == "live_output":
                    self.state["images"].append({"id": CROP_ID, "array": str(self.crop_path),
                                                  "calibration": [[0, 1, "nm"], [0, 1, "nm"]]})
                else:
                    self.state["images"][0]["calibration"][0][2] = "um"
                self.run_script("verify_trial_closed.py" if closed else "verify_trial.py", success=False,
                                phase="after_close" if closed else "after_stop", mode="observe_legacy_stop",
                                expected_error=reason)

    def test_closed_observation_requires_same_mode_pid_session_and_record_bindings(self):
        fields = [("oracle_mode", "strict"), ("status", "PASS"), ("session", OTHER_SESSION),
                  ("host_pid", 999), ("summary_sha256", "wrong"), ("stop_request_verified", True)]
        for field, value in fields:
            with self.subTest(field=field):
                self.prepare(closed=True)
                (self.directory / "stop-request.json").unlink()
                self.observation_post()
                path = self.directory / "trial-observation-after_stop.json"
                post = json.loads(path.read_text(encoding="utf-8"))
                post[field] = value
                _dump(path, post)
                reason = ("Post-STOP evidence is not bound to the current trial records" if field in (
                    "summary_sha256", "stop_request_verified") else "Required same-session post-STOP observation is missing")
                self.run_script("verify_trial_closed.py", success=False, phase="after_close", mode="observe_legacy_stop",
                                expected_error=reason)

    def test_duplicate_stop_json_keys_are_ambiguous_even_when_last_wins(self):
        cases = [("request", "op", "QUERY", "STOP"),
                 ("request", "id", "other-stop", "stop-synthetic"),
                 ("receipt", "state", "failed", "completed"),
                 ("receipt", "id", "other-stop", "stop-synthetic")]
        for mode in ("strict", "observe_legacy_stop"):
            for closed in (False, True):
                for subject, field, first, last in cases:
                    with self.subTest(mode=mode, closed=closed, subject=subject, field=field):
                        self.prepare(after_stop=True, closed=closed)
                        path = self.directory / ("stop-request.json" if subject == "request" else "stop-receipt.json")
                        body = path.read_text(encoding="utf-8")
                        old = json.dumps(field) + ": " + json.dumps(last)
                        duplicate = json.dumps(field) + ": " + json.dumps(first) + ", " + old
                        self.assertEqual(body.count(old), 1)
                        path.write_text(body.replace(old, duplicate), encoding="utf-8")
                        # Confirm this is specifically the old last-wins
                        # ambiguity, not a syntax error or an altered value.
                        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))[field], last)
                        if closed and mode == "observe_legacy_stop":
                            self.observation_post()
                        self.refresh_post_fingerprints()
                        self.run_script("verify_trial_closed.py" if closed else "verify_trial.py", success=False,
                                        phase="after_close" if closed else "after_stop", mode=mode,
                                        expected_error="Ambiguous STOP JSON evidence: duplicate key")

    def test_bad_stop_receipt_before_and_after_close(self):
        for closed in (False, True):
            for field, value in (("session", OTHER_SESSION), ("state", "failed"),
                                 ("protocol", "other"), ("result", {"ipc_stopped": False}),
                                 ("result", {"ipc_stopped": 1})):
                with self.subTest(closed=closed, field=field, value=value):
                    self.prepare(after_stop=True, closed=closed)
                    stop = self._stop()
                    stop[field] = value
                    _dump(self.directory / "stop-receipt.json", stop)
                    self.run_script("verify_trial_closed.py" if closed else "verify_trial.py",
                                    success=False, phase="after_close" if closed else "after_stop",
                                    expected_error="Invalid STOP receipt")

    def test_after_close_requires_current_stop_and_matching_post(self):
        for fault in ("missing_stop", "post_session", "post_phase", "post_image", "post_status",
                      "changed_summary", "changed_truth", "changed_valid_stop"):
            with self.subTest(fault=fault):
                self.prepare(closed=True)
                if fault == "missing_stop":
                    (self.directory / "stop-receipt.json").unlink()
                elif fault.startswith("changed_"):
                    if fault == "changed_summary":
                        self.summary["delivery"]["native_receipt"]["id"] = "different-show"
                        self.summary["delivery"]["native_receipt"]["request_id"] = "different-show"
                        self.save_records()
                    elif fault == "changed_truth":
                        self.truth["kind"] = "different-trial"
                        self.save_records()
                    else:
                        stop = self._stop()
                        stop["id"] = "different-valid-stop"
                        _dump(self.directory / "stop-receipt.json", stop)
                else:
                    post_path = self.directory / "trial-independent-after_stop.json"
                    post = json.loads(post_path.read_text(encoding="utf-8"))
                    field, value = {"post_session": ("session", OTHER_SESSION),
                                    "post_phase": ("phase", "before_stop"),
                                    "post_image": ("image_id", CROP_ID + 1),
                                    "post_status": ("status", "FAIL")}[fault]
                    post[field] = value
                    _dump(post_path, post)
                reason = ("Required STOP receipt is missing" if fault == "missing_stop" else
                          "Post-STOP evidence is not bound to the current trial records" if fault.startswith("changed_") else
                          "Wrong post-STOP output identity" if fault == "post_image" else
                          "Required same-session post-STOP acceptance is missing")
                self.run_script("verify_trial_closed.py", success=False, phase="after_close", expected_error=reason)

    def test_after_close_live_output_missing_source_and_wrong_count(self):
        for fault in ("live_output", "missing_source", "invalid_source", "wrong_count",
                      "source_pixels", "source_calibration"):
            with self.subTest(fault=fault):
                self.prepare(closed=True)
                if fault == "live_output":
                    self.state["images"].append({"id": CROP_ID, "array": str(self.crop_path),
                                                  "calibration": [[0, 1, "nm"], [0, 1, "nm"]]})
                elif fault == "missing_source":
                    self.state["images"].pop()
                    self.state["documents"][-1] = [22]
                elif fault == "invalid_source":
                    self.state["images"][-1]["valid"] = False
                elif fault == "wrong_count":
                    self.state["documents"].append([22])
                elif fault == "source_pixels":
                    path = Path(self.state["images"][0]["array"])
                    values = np.load(str(path), allow_pickle=False)
                    values[0, 0] += 1
                    np.save(str(path), values, allow_pickle=False)
                else:
                    self.state["images"][0]["calibration"][1][1] *= -1
                reason = {"live_output": "Closed crop still has a live owner; do not claim final release",
                          "missing_source": "Unrelated synthetic source was closed",
                          "invalid_source": "Unrelated synthetic source was closed",
                          "wrong_count": "Unrelated documents changed or delivered document still exists",
                          "source_pixels": "Synthetic source changed",
                          "source_calibration": "Synthetic source calibration changed"}[fault]
                self.run_script("verify_trial_closed.py", success=False, phase="after_close", expected_error=reason)

    def test_creator_round_trip_and_nonfinite_faults(self):
        self.state = {"mode": "creator"}
        answers = self.run_script("create_trial_fixture.py")
        self.assertEqual({entry["label"] for entry in answers["images"]},
                         {"CAL", "RAW", "UINT16", "NONFINITE"})
        nonfinite = next(entry for entry in answers["images"] if entry["label"] == "NONFINITE")
        self.assertFalse(nonfinite["finite"])
        self.assertNotIn("mean", nonfinite)
        # Use a separate directory per failed creator; earlier partial NPY
        # files are permitted but never a complete answer/PASS record.
        for mutation in ("nan_to_zero", "nan_to_posinf", "nan_to_neginf",
                         "finite_to_posinf", "finite_to_neginf"):
            with self.subTest(mutation=mutation):
                self.directory = Path(self.temp.name) / mutation
                self.directory.mkdir()
                self.state_path = self.directory / "fake-state.json"
                self.truth_path = self.directory / "trial-answers.json"
                self.state = {"mode": "creator", "create_mutation": mutation}
                self.run_script("create_trial_fixture.py", success=False,
                                expected_error="Synthetic input round-trip mismatch")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--run-trial-script":
        _run_fake_host(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        unittest.main()
