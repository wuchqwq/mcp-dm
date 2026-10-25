"""Strict-client tests using owned synthetic subprocesses and named-pipe mocks."""
import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
ACCEPT = ROOT / "experiments" / "native-bridge" / "mvp" / "accept_mcp.py"
spec = importlib.util.spec_from_file_location("native_accept_mcp", str(ACCEPT))
accept = importlib.util.module_from_spec(spec)
spec.loader.exec_module(accept)
NODE = shutil.which("node")

FAKE_HOST = r"""
import net from 'node:net';
import fs from 'node:fs';
const fixture = JSON.parse(fs.readFileSync(process.env.NATIVE_ACCEPT_FIXTURE, 'utf8'));
const mode = process.env.NATIVE_ACCEPT_MODE;
const pipe = '\\\\.\\pipe\\dm_mcp_native_' + fixture.session;
const image = truth => ({id: truth.id, name: truth.name, ndim: 2, dtype: truth.dtype,
  shape: truth.shape, dm_dimensions: [...truth.shape].reverse(), pixels: truth.shape[0]*truth.shape[1], native_mean_supported: true,
  coordinate_rule: 'physical(i)=calibrated_value_at_pixel_zero+i*scale', calibration: truth.calibration.map(axis => ({
    dm_dimension: axis.dm_axis, numpy_axis: 1-axis.dm_axis, size: truth.shape[1-axis.dm_axis], unit: axis.unit,
    scale: mode === 'badcal' ? -axis.scale : axis.scale, calibrated_value_at_pixel_zero: axis.origin, origin: -axis.origin/axis.scale}))});
const server = net.createServer(socket => {
  socket.on('error', () => {}); let input = '';
  socket.on('data', chunk => {
    input += chunk.toString('ascii'); const newline=input.indexOf('\n'); if(newline<0)return;
    const [protocol,session,id,operation,...args] = input.slice(0,newline).split(' ');
    fs.appendFileSync(process.env.NATIVE_ACCEPT_REQUESTS, JSON.stringify({protocol,session,id,operation,args})+'\n');
    const backend = mode === 'badbackend' ? 'digitalmicrograph-native' : 'mock-native';
    let result;
    if(operation==='STATUS')result={backend,ready:true,binary_gate:true,supported_build:'synthetic-only',host_pid:process.pid,host_thread:1003,
      resident_python_required:false,arbitrary_script:false,requires_idle_host:true,build_error:null};
    else if(operation==='DATASETS')result={backend,datasets:fixture.images.map(image)};
    else {
      const truth=fixture.images.find(item=>item.id===Number(args[0]));
      result={backend,image_id:truth.id,image:image(truth),mean:truth.mean+(mode==='badmean'?1:0),operator:'GMSImageProcessing::GetMean',computation:'DM native',
        intensity_calibration_applied:false,source_write_requested:false,snapshot_atomic:false};
    }
    const resultTypes={STATUS:'status',DATASETS:'datasets',MEAN:'native_mean'};
    const reply={protocol:'NB2',session,id,state:'completed',original_operation:operation,normalized_args:args.map(Number),result_type:resultTypes[operation],result_version:1,host_pid:process.pid,worker_tid:1002,exec_tid:1003,timings_us:{queue:1,execute:2},result};
    socket.end(JSON.stringify(reply)+'\n'); input='';
  });
});
server.listen(pipe, () => process.stdout.write('ready\n'));
"""


class NativeStrictClientTests(unittest.TestCase):
    def test_histogram_identity_and_float32_arguments_remain_distinct_from_profile(self):
        args = [77, 64, accept.native_float32_bits(-2.0), accept.native_float32_bits(2.0)]
        receipt = {"protocol": "NB2", "state": "completed", "original_operation": "HISTOGRAM",
                   "normalized_args": args, "result_type": "native_histogram", "result_version": 1}
        accept.validate_operation_identity(receipt, "HISTOGRAM", args)
        for key, value in (("result_type", "native_line_profile"), ("result_version", 2),
                           ("normalized_args", args[:2])):
            with self.assertRaises(ValueError):
                accept.validate_operation_identity(dict(receipt, **{key: value}), "HISTOGRAM", args)
        self.assertEqual(accept.native_float32_bits(-0.0), 0x80000000)
        self.assertEqual(accept.native_float32_bits(1e300), 0x7f800000)
        self.assertEqual(accept.native_float32_bits(-1e300), 0xff800000)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-accept-offline-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def owned_client(self, code, timeout=0.5):
        script = self.root / (uuid.uuid4().hex + ".py")
        script.write_text(code, encoding="utf-8")
        client = accept.StdioClient([sys.executable, "-u", str(script)], dict(os.environ), io.StringIO(), timeout)
        self.addCleanup(client.close)
        return client

    def test_reader_deadline_terminates_only_owned_silent_subprocess(self):
        client = self.owned_client("import sys,time\nsys.stdin.readline()\ntime.sleep(30)\n", timeout=0.1)
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            client.rpc("ping", {})
        client.close()
        self.assertIsNotNone(client.proc.poll())
        self.assertLess(time.monotonic() - started, 3)

    def test_rpc_id_utf8_and_tool_iserror_are_checked_independently(self):
        cases = [
            ("import sys\nsys.stdin.readline()\nprint('{\"jsonrpc\":\"2.0\",\"id\":99,\"result\":{}}')\n", "ID mismatch"),
            ("import sys\nsys.stdin.readline()\nsys.stdout.buffer.write(b'\\xff\\n');sys.stdout.flush()\n", "reader failed"),
            ("import sys\nsys.stdin.readline()\nprint('{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{\"isError\":true,\"content\":[{\"type\":\"text\",\"text\":\"{}\"}]}}')\n", "isError"),
        ]
        for code, expected in cases:
            client = self.owned_client(code)
            with self.assertRaisesRegex(ValueError, expected):
                client.tool("test", {})

    def test_strict_json_rejects_duplicates_and_nonfinite_values(self):
        for source in ['{"id":1,"id":2}', '{"mean":1e400}', '{"mean":NaN}']:
            with self.assertRaises(ValueError):
                accept.strict_json(source)

    def test_uint32_image_type_flags_and_exact_reduction_budget_are_explicit(self):
        fixture, _ = self.fixture()
        truth = fixture["images"][0]
        truth["dtype"] = "uint32"; truth["mean"] = 4294967295
        accept.validate_fixture(fixture)
        actual = {"id": truth["id"], "name": truth["name"], "shape": truth["shape"], "dtype": "uint32",
                  "ndim": 2, "pixels": 77, "dm_dimensions": list(reversed(truth["shape"])),
                  "data_type_code": 11, "is_integer": True, "is_unsigned": True, "packing_style": 1,
                  "native_mean_supported": True, "coordinate_rule": "physical(i)=calibrated_value_at_pixel_zero+i*scale",
                  "calibration": [{"dm_dimension": axis["dm_axis"], "numpy_axis": 1-axis["dm_axis"],
                                   "size": truth["shape"][1-axis["dm_axis"]], "unit": axis["unit"],
                                   "scale": axis["scale"], "calibrated_value_at_pixel_zero": axis["origin"]}
                                  for axis in truth["calibration"]]}
        accept.validate_image(actual, truth)
        for key, value in (("data_type_code", 2), ("is_integer", False), ("is_unsigned", 1), ("packing_style", 0)):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "uint32 dtype/code/integer/unsigned/packing/budget"):
                accept.validate_image(dict(actual, **{key: value}), truth)
        truth["shape"] = [1, 2097153]
        with self.assertRaisesRegex(ValueError, "fixture shape/mean"):
            accept.validate_fixture(fixture)

    def test_read_and_fourier_versions_bind_the_declared_result_contract(self):
        def receipt(operation, args, result_type, version):
            return {"protocol": "NB2", "original_operation": operation, "normalized_args": args,
                    "result_type": result_type, "result_version": version, "state": "completed"}
        read = receipt("READ", [77, 1, 1, 4, 3], "native_data_snapshot", 1)
        accept.validate_operation_identity(read, "READ", [77, 1, 1, 4, 3])
        accept.validate_operation_identity(read, "QUERY", [])
        for change in ({"result_type": "native_preview"}, {"normalized_args": [77, 1, 1, 4]},
                       {"normalized_args": [77, 1, 1, 4, True]}):
            with self.subTest(read=change), self.assertRaisesRegex(ValueError, "operation/result schema identity mismatch"):
                accept.validate_operation_identity(dict(read, **change))
        for version in (0, 2, 3, True, "1", 1.5):
            with self.subTest(read_version=version), self.assertRaisesRegex(ValueError, "operation/result schema identity mismatch"):
                accept.validate_operation_identity(dict(read, result_version=version))
        rois = receipt("ROIS", [77], "native_gui_rois", 1)
        accept.validate_operation_identity(rois, "QUERY", [])
        with self.assertRaisesRegex(ValueError, "historical version 1 is QUERY only"):
            accept.validate_operation_identity(rois, "ROIS", [77])
        accept.validate_operation_identity(dict(rois,result_version=2), "ROIS", [77])
        profile = receipt("PROFILE", [77,31,9,4,2,1,5,1,1], "native_line_profile", 1)
        accept.validate_operation_identity(profile, "PROFILE", [77,31,9,4,2,1,5,1,1])
        accept.validate_operation_identity(profile, "QUERY", [])
        for change in ({"normalized_args":[77]}, {"result_version":2}, {"normalized_args":[77,31,9,4,2,1,5,1,True]}):
            with self.subTest(profile=change), self.assertRaises(ValueError):
                accept.validate_operation_identity(dict(profile,**change))
        for change in ({"result_type": "datasets"}, {"normalized_args": []}, {"normalized_args": [True]},
                       {"result_version": 3}, {"result_version": True}):
            with self.subTest(rois=change), self.assertRaisesRegex(ValueError, "operation/result schema identity mismatch"):
                accept.validate_operation_identity(dict(rois, **change))
        for operation in ("FFT", "IFFT", "REAL", "IMAG", "VENDOR_ARG", "VENDOR_NORM"):
            for version in (1, 2):
                value = receipt(operation, [77], "native_fourier_operation", version)
                accept.validate_operation_identity(value, operation, [77])
                accept.validate_operation_identity(value, "QUERY", [])
            for version in (0, 3, True, "2", 1.5):
                with self.subTest(operation=operation, version=version), self.assertRaisesRegex(ValueError, "operation/result schema identity mismatch"):
                    accept.validate_operation_identity(receipt(operation, [77], "native_fourier_operation", version))
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, "operation/result schema identity mismatch"):
                accept.validate_operation_identity(receipt(operation, [77], "native_mean", 2))

    def test_new_tool_and_preview_rpc_receipts_bind_original_arguments(self):
        cases = [
            ("dm_native_rois", {"image_id": 77}, "ROIS", [77], "native_gui_rois"),
            ("dm_native_profile", {"image_id":77,"document_id":31,"display_id":9,"roi_id":4,"expected_line":[2,1,5,1],"width":1,"request_id":"saved"}, "PROFILE", [77,31,9,4,2,1,5,1,1], "native_line_profile"),
            ("dm_native_histogram", {"image_id":77,"bins":64,"min":-2.0,"max":2.0,"request_id":"saved"}, "HISTOGRAM", [77,64,accept.native_float32_bits(-2.0),accept.native_float32_bits(2.0)], "native_histogram"),
            ("dm_native_read", {"image_id": 77, "rect": [1, 1, 4, 3]}, "READ", [77, 1, 1, 4, 3], "native_data_snapshot"),
            ("dm_native_fft", {"image_id": 77, "direction": "forward"}, "FFT", [77], "native_fourier_operation"),
            ("dm_native_complex", {"image_id": 77, "component": "power"}, "VENDOR_NORM", [77], "native_fourier_operation"),
            ("dm_native_unary", {"image_id": 77, "operation": "abs"}, "UNARY", [77, 2], "native_image_operation"),
            ("dm_native_binary", {"left_image_id": 77, "right_image_id": 78, "operation": "subtract"}, "BINARY", [77, 78, 2], "native_image_operation"),
            ("dm_native_filter", {"image_id": 77, "operation": "sobel"}, "FILTER", [77, 2], "native_image_operation"),
            ("dm_native_preview", {"image_id": 77}, "PREVIEW", [77, 128, 128], "native_preview"),
        ]
        for name, arguments, operation, args, result_type in cases:
            for mismatch in (False, True):
                actual_args = list(args)
                if mismatch:
                    actual_args[0] = 78
                output = {"backend": "mock-native", "native_receipt": {
                    "protocol": "NB2", "original_operation": operation, "normalized_args": actual_args,
                    "result_type": result_type, "result_version": 2 if result_type in ("native_fourier_operation", "native_gui_rois") else 1,
                    "state": "completed"}}
                content = [{"type": "text", "text": json.dumps(output)}]
                if operation == "PREVIEW":
                    content.append({"type": "image", "mimeType": "image/png", "data": "synthetic-placeholder-only"})
                response = {"jsonrpc": "2.0", "id": 1, "result": {"content": content}}
                code = "import sys\nsys.stdin.readline()\nprint(%r)\n" % json.dumps(response)
                client = self.owned_client(code)
                with self.subTest(tool=name, mismatch=mismatch):
                    if mismatch:
                        with self.assertRaisesRegex(ValueError, "original operation/arguments differ from submitted request"):
                            client.rpc("tools/call", {"name": name, "arguments": arguments})
                    else:
                        actual = client.rpc("tools/call", {"name": name, "arguments": arguments})
                        self.assertEqual(actual["result"]["content"], content)

    def fixture(self):
        fixture = {"session": uuid.uuid4().hex, "kind": "synthetic-only", "python_is_listener": False, "images": []}
        for ident, shape, mean in [(17, [7, 11], -24.375), (18, [5, 9], 93.375)]:
            fixture["images"].append({"id": ident, "shape": shape, "dtype": "float32", "mean": mean,
                                      "name": "synthetic-" + str(ident), "calibration": [
                                          {"dm_axis": 0, "origin": 1.25, "scale": -0.25, "unit": "nm"},
                                          {"dm_axis": 1, "origin": -2.5, "scale": 0.5, "unit": "nm"}]})
        path = self.root / (fixture["session"] + ".json")
        path.write_text(json.dumps(fixture), encoding="utf-8")
        return fixture, path

    @unittest.skipUnless(NODE, "Node is required for synthetic end-to-end acceptance")
    def test_full_stdio_native_mock_and_semantic_failures(self):
        host_script = self.root / "fake_host.mjs"
        host_script.write_text(FAKE_HOST, encoding="utf-8")
        for mode in ["good", "badmean", "badcal", "badbackend"]:
            with self.subTest(mode=mode):
                fixture, fixture_path = self.fixture()
                requests_path = self.root / (fixture["session"] + "-requests.jsonl")
                env = dict(os.environ, NATIVE_ACCEPT_FIXTURE=str(fixture_path), NATIVE_ACCEPT_MODE=mode, NATIVE_ACCEPT_REQUESTS=str(requests_path))
                host = subprocess.Popen([NODE, str(host_script)], env=env, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                ready = queue.Queue()
                reader = threading.Thread(target=lambda: ready.put(host.stdout.readline()), daemon=True)
                reader.start()
                try:
                    self.assertEqual(ready.get(timeout=3), b"ready\n")
                    evidence = self.root / (fixture["session"] + "-evidence")
                    result = subprocess.run([sys.executable, "-B", str(ACCEPT), "--fixture", str(fixture_path), "--evidence-directory", str(evidence),
                                             "--expected-backend", "mock-native", "--expected-build", "synthetic-only", "--expected-host-pid", str(host.pid),
                                             "--mean-repeats", "2"], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=12)
                    report = json.loads((evidence / "result.json").read_text(encoding="utf-8"))
                    if mode == "good":
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertEqual(report["status"], "PASS")
                        self.assertEqual(report["backend"], "mock-native")
                        self.assertIn("no client UI", report["scope"])
                        requests = [json.loads(line) for line in requests_path.read_text(encoding="utf-8").splitlines()]
                        self.assertEqual([request["operation"] for request in requests], ["STATUS", "DATASETS", "MEAN", "MEAN", "MEAN", "MEAN"])
                        self.assertEqual(len({request["id"] for request in requests}), len(requests))
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(report["status"], "FAIL")
                        self.assertIn("mismatch" if mode != "badmean" else "differs", report["error"])
                finally:
                    host.terminate()
                    try:
                        host.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        host.kill()
                        host.wait(timeout=2)
                    host.stdout.close()
                    host.stderr.close()


if __name__ == "__main__":
    unittest.main()
