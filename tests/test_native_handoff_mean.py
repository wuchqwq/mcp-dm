"""Explicit external workflow tests using fabricated saved READ text only.

No DM import, real native call, installed plugin, desktop, or actual host.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "native_handoff_mean.py"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ExternalMeanExample(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="native-external-mean-")
        self.directory = Path(self.temporary.name)
        tool = (ROOT / "tools" / "native_snapshot_handoff.mjs").as_uri()
        fixture = (ROOT / "tests" / "fixtures" / "native-operations.mjs").as_uri()
        script = """import fs from 'node:fs';import path from 'node:path';
import {handoff} from %s;import {readFixture} from %s;
const directory=process.argv[1],args=[77,1,1,4,3];
const payload={...readFixture(args),native_receipt:{protocol:'NB2',session:'a'.repeat(32),id:'synthetic-read',request_id:'synthetic-read',state:'completed',host_pid:1234,exec_tid:10,worker_tid:20,timings_us:{queue:3,execute:4},original_operation:'READ',normalized_args:args,result_type:'native_data_snapshot',result_version:1}};
const saved=path.join(directory,'synthetic.json');fs.writeFileSync(saved,JSON.stringify(payload));
console.log(JSON.stringify(handoff({workspace:directory,output:'capture',requestId:'external-test',snapshot:saved})));""" % (json.dumps(tool), json.dumps(fixture))
        result = subprocess.run(["node", "--input-type=module", "-e", script, str(self.directory)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.capture = self.directory / "capture"
        self.before = {name: (digest(self.capture / name), (self.capture / name).stat().st_mtime_ns)
                       for name in ("input.npy", "input.json", "capture.json")}

    def tearDown(self):
        self.temporary.cleanup()

    def call(self, output="external-result"):
        result = subprocess.run([sys.executable, str(EXAMPLE), "--workspace", str(self.directory),
                                 "--capture", str(self.capture), "--output", output], capture_output=True, text=True)
        return result.returncode, json.loads(result.stdout), result

    def assert_source_unchanged(self):
        self.assertEqual({name: (digest(self.capture / name), (self.capture / name).stat().st_mtime_ns)
                          for name in self.before}, self.before)

    def test_explicit_external_raw_mean_and_software_script_provenance(self):
        values = np.load(self.capture / "input.npy", allow_pickle=False)
        expected = np.array([[-0., -2.5, .125], [8., -0., -2.5]], dtype="<f4")
        np.testing.assert_array_equal(values.view("<u4"), expected.view("<u4"))
        code, report, process = self.call()
        self.assertEqual(code, 0, process.stderr)
        self.assertEqual(report["mean"], 3.125 / 6)  # Six manually enumerated raw values.
        self.assertEqual(report["sample_count"], 6)
        self.assertEqual(report["intensity_calibration_status"], "NOT_READ")
        self.assertIsNone(report["intensity_unit"])
        self.assertIs(report["dm_called"], False)
        self.assertIs(report["result_returned_to_dm"], False)
        output = self.directory / "external-result"
        self.assertEqual(set(path.name for path in output.iterdir()),
                         {"run.json", "parameters.json", "results.json", "native_handoff_mean.py"})
        parameters = json.loads((output / "parameters.json").read_text(encoding="utf-8"))
        self.assertIn("python_version", parameters); self.assertIn("numpy_version", parameters)
        self.assertEqual(parameters["script_sha256"], digest(EXAMPLE))
        self.assertEqual(digest(output / "native_handoff_mean.py"), digest(EXAMPLE))
        self.assertEqual(report["parameters_sha256"], hashlib.sha256(canonical(parameters)).hexdigest())
        self.assertEqual(json.loads((output / "run.json").read_text())["state"], "complete")
        self.assert_source_unchanged()

    def test_existing_output_and_source_subdirectory_are_never_overwritten(self):
        output = self.directory / "existing"; output.mkdir(); (output / "USER.txt").write_bytes(b"USER DATA")
        code, report, _ = self.call("existing")
        self.assertEqual(code, 1); self.assertEqual(report["state"], "failed")
        self.assertEqual((output / "USER.txt").read_bytes(), b"USER DATA")
        self.assertEqual(len(list(output.iterdir())), 1)
        code, report, _ = self.call("capture/inside")
        self.assertEqual(code, 1); self.assertFalse((self.capture / "inside").exists())
        self.assert_source_unchanged()

    def test_changed_npy_or_calibration_metadata_never_creates_success_output(self):
        for target in ("input.npy", "input.json"):
            original = (self.capture / target).read_bytes()
            try:
                if target.endswith(".npy"):
                    (self.capture / target).write_bytes(original + b"x")
                else:
                    info = json.loads(original); info["working_calibration_xy"][0]["scale"] = 99
                    (self.capture / target).write_text(json.dumps(info), encoding="utf-8")
                code, report, _ = self.call("wrong-" + target.replace(".", "-"))
                self.assertEqual(code, 1); self.assertEqual(report["state"], "failed")
                self.assertFalse((self.directory / ("wrong-" + target.replace(".", "-"))).exists())
            finally:
                (self.capture / target).write_bytes(original)

    def test_incomplete_capture_or_native_receipt_hash_cannot_pass_even_if_metadata_rehashed(self):
        manifest_path, info_path = self.capture / "capture.json", self.capture / "input.json"
        manifest_original, info_original = manifest_path.read_bytes(), info_path.read_bytes()
        for failure in ("capturing", "receipt"):
            try:
                manifest, info = json.loads(manifest_original), json.loads(info_original)
                if failure == "capturing": manifest["state"] = "capturing"
                else:
                    info["native_receipt_sha256"] = "0" * 64
                    info_path.write_bytes(canonical(info))
                    manifest["input_metadata_sha256"] = hashlib.sha256(canonical(info)).hexdigest()
                manifest_path.write_bytes(canonical(manifest))
                code, report, _ = self.call("failed-" + failure)
                self.assertEqual(code, 1); self.assertEqual(report["state"], "failed")
                self.assertFalse((self.directory / ("failed-" + failure)).exists())
            finally:
                manifest_path.write_bytes(manifest_original); info_path.write_bytes(info_original)

    def test_escape_and_existing_parent_requirement(self):
        for output in ("../escape", "missing-parent/output", str(self.directory / "absolute")):
            code, report, _ = self.call(output)
            self.assertEqual(code, 1); self.assertEqual(report["state"], "failed")
        self.assert_source_unchanged()

    def test_rehashed_receipt_args_and_session_identity_contradictions_fail_closed(self):
        manifest_path, info_path = self.capture / "capture.json", self.capture / "input.json"
        manifest_original, info_original = manifest_path.read_bytes(), info_path.read_bytes()
        mutations = [lambda i, m: i["native_receipt"].update(normalized_args=[999, 0, 0, 1, 1]),
                     lambda i, m: i["native_receipt"].update(session="bad"),
                     lambda i, m: i["native_receipt"].update(host_pid=2**40),
                     lambda i, m: i["native_receipt"]["timings_us"].update(execute=-1),
                     lambda i, m: i["native_receipt"].pop("timings_us"),
                     lambda i, m: i["native_receipt"].update(request_id="different-read"),
                     lambda i, m: m.update(native_session="b" * 32),
                     lambda i, m: m.update(native_request_id="another-original"),
                     lambda i, m: m.update(source_image_id=999)]
        for index, mutate in enumerate(mutations):
            try:
                info, manifest = json.loads(info_original), json.loads(manifest_original)
                mutate(info, manifest)
                info["native_receipt_sha256"] = hashlib.sha256(canonical(info["native_receipt"])).hexdigest()
                manifest["native_receipt_sha256"] = info["native_receipt_sha256"]
                manifest["input_metadata_sha256"] = hashlib.sha256(canonical(info)).hexdigest()
                info_path.write_bytes(canonical(info)); manifest_path.write_bytes(canonical(manifest))
                code, report, _ = self.call("rehashed-failure-%s" % index)
                self.assertEqual(code, 1); self.assertEqual(report["state"], "failed")
                self.assertFalse((self.directory / ("rehashed-failure-%s" % index)).exists())
            finally:
                manifest_path.write_bytes(manifest_original); info_path.write_bytes(info_original)


if __name__ == "__main__": unittest.main()
