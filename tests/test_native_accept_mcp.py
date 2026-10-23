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
    const reply={protocol:'NB1',session,id,state:'completed',host_pid:process.pid,worker_tid:1002,exec_tid:1003,timings_us:{queue:1,execute:2},result};
    socket.end(JSON.stringify(reply)+'\n'); input='';
  });
});
server.listen(pipe, () => process.stdout.write('ready\n'));
"""


class NativeStrictClientTests(unittest.TestCase):
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
                        self.assertIn("no WorkBuddy", report["scope"])
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
