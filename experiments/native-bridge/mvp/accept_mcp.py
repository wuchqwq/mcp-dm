"""Strict stdio MCP acceptance client; it starts/closes only its own Node child.

Run against an already prepared, idle synthetic DM fixture. This validates
protocol and numerical receipts, never client UI or visual acceptance.
"""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

MAX_MESSAGE = 2 * 1024 * 1024
MAX_SAFE_INTEGER = (1 << 53) - 1
ROOT = Path(__file__).resolve().parents[3]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, minimum=0, maximum=MAX_SAFE_INTEGER):
    return type(value) is int and minimum <= value <= maximum


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key: " + key)
        result[key] = value
    return result


def strict_json(data):
    def number(text):
        result = float(text)
        require(math.isfinite(result), "Nonfinite JSON number")
        return result
    return json.loads(data, object_pairs_hook=unique_object, parse_float=number,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Invalid JSON number: " + value)))


class StdioClient:
    """Bounded reader queues keep readline off the thread enforcing deadlines."""
    def __init__(self, command, env, trace, timeout=5):
        self.trace, self.timeout, self.next_id = trace, timeout, 1
        self.messages = queue.Queue(maxsize=32)
        self.stderr = bytearray()
        self.proc = subprocess.Popen(command, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.readers = [threading.Thread(target=self._stdout, daemon=True), threading.Thread(target=self._stderr, daemon=True)]
        for reader in self.readers:
            reader.start()

    def event(self, kind, value):
        self.trace.write(json.dumps({"time_utc": datetime.now(timezone.utc).isoformat(), kind: value}, ensure_ascii=True, allow_nan=False) + "\n")
        self.trace.flush()

    def _put(self, item):
        try:
            self.messages.put(item, timeout=0.2)
        except queue.Full:
            pass  # Main thread will fail on the first unexpected response.

    def _stdout(self):
        try:
            while True:
                line = self.proc.stdout.readline(MAX_MESSAGE + 1)
                if not line:
                    self._put(("eof", "Node stdout closed"))
                    return
                require(len(line) <= MAX_MESSAGE and line.endswith(b"\n"), "MCP response exceeds 2 MiB or lacks LF")
                self._put(("message", strict_json(line.decode("utf-8", errors="strict"))))
        except Exception as error:
            self._put(("error", str(error)))

    def _stderr(self):
        while True:
            chunk = self.proc.stderr.read(1024)
            if not chunk:
                return
            if len(self.stderr) < 16384:
                self.stderr.extend(chunk[:16384 - len(self.stderr)])

    def notify(self, method, params=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.event("send", message)
        self.proc.stdin.write((json.dumps(message, allow_nan=False) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def rpc(self, method, params):
        ident = self.next_id
        self.next_id += 1
        message = {"jsonrpc": "2.0", "id": ident, "method": method, "params": params}
        self.event("send", message)  # Save explicit native IDs before dispatch.
        self.proc.stdin.write((json.dumps(message, allow_nan=False) + "\n").encode("utf-8"))
        self.proc.stdin.flush()
        deadline = time.monotonic() + self.timeout
        try:
            kind, response = self.messages.get(timeout=max(0.001, deadline - time.monotonic()))
        except queue.Empty:
            raise TimeoutError("MCP deadline expired; pending native request IDs are in stdio-events.jsonl; do not resubmit")
        require(kind == "message", "MCP reader failed: " + str(response))
        self.event("receive", response)
        require(isinstance(response, dict) and response.get("jsonrpc") == "2.0", "Invalid JSON-RPC response")
        require(type(response.get("id")) is int and response["id"] == ident, "MCP response ID mismatch or unsolicited message")
        require(("result" in response) != ("error" in response), "MCP response requires exactly one result/error")
        return response

    def tool(self, name, arguments):
        response = self.rpc("tools/call", {"name": name, "arguments": arguments})
        require("error" not in response, "JSON-RPC tool error: " + str(response.get("error")))
        result = response["result"]
        require(isinstance(result, dict), "MCP tool result must be an object")
        require(type(result.get("isError", False)) is bool, "Invalid MCP isError value")
        require(result.get("isError") is not True, "MCP tool isError: " + str(result))
        content = result.get("content")
        require(isinstance(content, list) and len(content) == 1 and isinstance(content[0], dict)
                and content[0].get("type") == "text" and isinstance(content[0].get("text"), str), "Expected one native JSON text block")
        output = strict_json(content[0]["text"])
        require(isinstance(output, dict), "Native output must be an object")
        return output

    def close(self):
        # These operations target this subprocess handle only, never DM/PIDs
        # discovered elsewhere. Closing an MCP client does not cancel DM work.
        try:
            self.proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self.proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=1)
        for reader in self.readers:
            reader.join(timeout=0.5)
        self.proc.stdout.close()
        self.proc.stderr.close()


def validate_fixture(fixture):
    require(isinstance(fixture, dict) and isinstance(fixture.get("session"), str)
            and re.fullmatch(r"[a-f0-9]{32}", fixture["session"]) is not None, "Invalid fixture session")
    require(fixture.get("kind") == "synthetic-only" and fixture.get("python_is_listener") is False, "Only an explicit one-shot synthetic fixture is accepted")
    images = fixture.get("images")
    require(isinstance(images, list) and len(images) == 2, "Exactly two synthetic fixture images are required")
    ids = set()
    for image in images:
        require(isinstance(image, dict) and integer(image.get("id"), 0, 0xffffffff) and image["id"] not in ids, "Invalid/duplicate fixture image ID")
        ids.add(image["id"])
        require(isinstance(image.get("name"), str) and image["name"] and image.get("dtype") == "float32", "Invalid fixture name/dtype")
        shape = image.get("shape")
        require(isinstance(shape, list) and len(shape) == 2 and all(integer(n, 1, 4194304) for n in shape)
                and math.prod(shape) <= 4194304 and finite(image.get("mean")), "Invalid fixture shape/mean")
        calibration = image.get("calibration")
        require(isinstance(calibration, list) and len(calibration) == 2, "Missing fixture calibration")
        require({axis.get("dm_axis") for axis in calibration if isinstance(axis, dict)} == {0, 1}, "Invalid fixture calibration axes")
        for axis in calibration:
            require(integer(axis.get("dm_axis"), 0, 1) and finite(axis.get("origin")) and finite(axis.get("scale")) and axis["scale"] != 0
                    and isinstance(axis.get("unit"), str) and axis["unit"], "Invalid fixture calibration values")
    return fixture


def validate_receipt(output, request_id, session, expected_backend, host_pid=None, host_thread=None):
    require(output.get("backend") == expected_backend, "Native backend mismatch; mock-native must never pass as real DM")
    receipt = output.get("native_receipt")
    require(isinstance(receipt, dict) and receipt.get("protocol") == "NB1" and receipt.get("session") == session
            and receipt.get("id") == request_id and receipt.get("request_id") == request_id
            and receipt.get("state") == "completed", "Native receipt correlation/state mismatch")
    for field in ("host_pid", "worker_tid", "exec_tid"):
        require(integer(receipt.get(field), 1, 0xffffffff), "Invalid native " + field)
    require(receipt["worker_tid"] != receipt["exec_tid"], "Native API execution must not run on IPC worker")
    timings = receipt.get("timings_us")
    require(isinstance(timings, dict) and all(integer(timings.get(field)) for field in ("queue", "execute")), "Invalid native timings")
    if host_pid is not None:
        require(receipt["host_pid"] == host_pid, "Native host PID changed")
    if host_thread is not None:
        require(receipt["exec_tid"] == host_thread, "Native execution did not use the bound host thread")
    return receipt


def validate_image(actual, truth):
    require(isinstance(actual, dict) and integer(actual.get("id"), 0, 0xffffffff) and actual.get("id") == truth["id"] and actual.get("name") == truth["name"], "Image identity/name mismatch")
    require(actual.get("shape") == truth["shape"] and isinstance(actual.get("shape"), list)
            and all(integer(size, 1) for size in actual["shape"]) and actual.get("dtype") == truth["dtype"]
            and integer(actual.get("ndim"), 2, 2) and integer(actual.get("pixels"), 1)
            and actual.get("dm_dimensions") == list(reversed(truth["shape"])) and actual.get("pixels") == math.prod(truth["shape"]), "Image shape/dtype mismatch")
    require(actual.get("native_mean_supported") is True, "Fixture not marked as supported native mean input")
    require(actual.get("coordinate_rule") == "physical(i)=calibrated_value_at_pixel_zero+i*scale", "Unknown coordinate rule")
    axes = actual.get("calibration")
    require(isinstance(axes, list) and len(axes) == 2, "Missing native image calibration")
    for expected in truth["calibration"]:
        matches = [axis for axis in axes if isinstance(axis, dict) and axis.get("dm_dimension") == expected["dm_axis"]]
        require(len(matches) == 1, "Ambiguous native calibration axis")
        axis = matches[0]
        require(integer(axis.get("dm_dimension"), 0, 1) and integer(axis.get("numpy_axis"), 0, 1) and integer(axis.get("size"), 1)
                and axis.get("numpy_axis") == 1 - expected["dm_axis"] and axis.get("size") == truth["shape"][1 - expected["dm_axis"]]
                and axis.get("unit") == expected["unit"], "Native axis order/size/unit mismatch")
        # The fixture used DM GetDimensionCalibration(axis, 0). Its origin is
        # physical zero, whereas metadata.origin is the raw-origin convention.
        for native_key, fixture_key in (("scale", "scale"), ("calibrated_value_at_pixel_zero", "origin")):
            # Both values are the same host binary32 getter widened to binary64;
            # there is no intervening arithmetic that needs a loose tolerance.
            require(finite(axis.get(native_key)) and axis[native_key] == expected[fixture_key], "Native signed scale/physical zero mismatch")


def run_acceptance(client, fixture, backend, build, expected_pid=None, repeats=1):
    initialized = client.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "native-strict-stdio-acceptance", "version": "1"}})
    require("error" not in initialized and initialized["result"].get("protocolVersion") == "2024-11-05", "MCP initialization failed")
    require(initialized["result"].get("serverInfo") == {"name": "digitalmicrograph", "version": "0.6.0"}, "Unexpected MCP server identity")
    client.notify("notifications/initialized")
    catalog_response = client.rpc("tools/list", {})
    require("error" not in catalog_response, "MCP tools/list failed")
    catalog = catalog_response["result"].get("tools")
    core_names = {"dm_status", "dm_datasets", "dm_native_mean", "dm_native_result"}
    require(isinstance(catalog, list) and all(isinstance(tool, dict) and isinstance(tool.get("name"), str) for tool in catalog), "Invalid native tool catalog")
    names = {tool["name"] for tool in catalog}
    require(len(catalog) == len(names) and core_names <= names <= core_names | {"dm_crop", "dm_native_show"}, "Unexpected native tool catalog")
    if "dm_crop" in names:
        crop_schema = next(tool["inputSchema"] for tool in catalog if tool["name"] == "dm_crop")
        require("request_id" in crop_schema.get("required", []) and crop_schema.get("properties", {}).get("request_id", {}).get("type") == "string",
                "Native crop must require a caller-saved request_id before dispatch")
    if "dm_native_show" in names:
        show_schema = next(tool["inputSchema"] for tool in catalog if tool["name"] == "dm_native_show")
        require({"image_id", "request_id"} <= set(show_schema.get("required", []))
                and show_schema.get("properties", {}).get("image_id", {}).get("type") == "integer"
                and show_schema.get("properties", {}).get("request_id", {}).get("type") == "string",
                "Native show must require explicit image_id and a caller-saved request_id before dispatch")
    session, checks = fixture["session"], []

    def submit(name, arguments):
        request_id = "accept-" + uuid.uuid4().hex
        return request_id, client.tool(name, dict(arguments, request_id=request_id))

    request_id, status = submit("dm_status", {})
    receipt = validate_receipt(status, request_id, session, backend, expected_pid)
    pid, host_thread = receipt["host_pid"], receipt["exec_tid"]
    require(status.get("ready") is True and status.get("binary_gate") is True and status.get("supported_build") == build
            and status.get("host_pid") == pid and status.get("host_thread") == host_thread
            and status.get("resident_python_required") is False and status.get("arbitrary_script") is False
            and status.get("requires_idle_host") is True and status.get("build_error") is None, "Native status/build/host gate failed")
    checks.append({"check": "status", "native_receipt": receipt, "backend": status["backend"], "supported_build": status["supported_build"]})
    request_id, datasets = submit("dm_datasets", {})
    receipt = validate_receipt(datasets, request_id, session, backend, pid, host_thread)
    require(isinstance(datasets.get("datasets"), list), "Missing native datasets")
    for truth in fixture["images"]:
        matches = [image for image in datasets["datasets"] if isinstance(image, dict) and image.get("id") == truth["id"]]
        require(len(matches) == 1, "Fixture ID missing or ambiguous in native datasets")
        validate_image(matches[0], truth)
    checks.append({"check": "datasets_and_calibration", "native_receipt": receipt})
    for iteration in range(repeats):
        for truth in fixture["images"]:
            request_id, mean = submit("dm_native_mean", {"image_id": truth["id"]})
            receipt = validate_receipt(mean, request_id, session, backend, pid, host_thread)
            require(integer(mean.get("image_id"), 0, 0xffffffff) and mean.get("image_id") == truth["id"] and finite(mean.get("mean"))
                    and math.isclose(mean["mean"], truth["mean"], rel_tol=1e-6, abs_tol=1e-6), "Native mean differs from independent fixture oracle")
            require(mean.get("operator") == "GMSImageProcessing::GetMean" and mean.get("computation") == "DM native"
                    and mean.get("intensity_calibration_applied") is False and mean.get("source_write_requested") is False
                    and mean.get("snapshot_atomic") is False, "Native mean provenance/scope mismatch")
            validate_image(mean.get("image"), truth)
            checks.append({"check": "native_mean", "image_id": truth["id"], "iteration": iteration,
                           "expected_mean": truth["mean"], "actual_mean": mean["mean"], "native_receipt": receipt})
    for invalid_id in (-1, "front"):
        response = client.rpc("tools/call", {"name": "dm_native_mean", "arguments": {"image_id": invalid_id}})
        require("result" not in response and isinstance(response.get("error"), dict) and response["error"].get("code") == -32602,
                "Invalid image ID was not rejected as a schema error")
    checks.append({"check": "invalid_negative_and_front_rejected"})
    return {"checks": checks, "host_pid": pid, "host_thread": host_thread, "backend": backend, "catalog": [tool["name"] for tool in catalog]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--evidence-directory", type=Path, required=True, help="new private directory; existing paths refused")
    parser.add_argument("--server", type=Path, default=ROOT / "server.mjs")
    parser.add_argument("--node", default=shutil.which("node") or "node")
    parser.add_argument("--timeout-seconds", type=float, default=5)
    parser.add_argument("--expected-backend", choices=("digitalmicrograph-native", "mock-native"), default="digitalmicrograph-native")
    parser.add_argument("--expected-build", default="3.53.4137.0-x64")
    parser.add_argument("--expected-host-pid", type=int)
    parser.add_argument("--mean-repeats", type=int, default=1)
    args = parser.parse_args(argv)
    require(math.isfinite(args.timeout_seconds) and 1 <= args.timeout_seconds <= 30, "Timeout must be 1..30 seconds")
    require(1 <= args.mean_repeats <= 100, "Mean repeats must be 1..100")
    fixture = validate_fixture(strict_json(args.fixture.read_text(encoding="utf-8-sig")))
    evidence = args.evidence_directory.resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    report = {"status": "FAIL", "scope": "strict stdio MCP and native receipts; no client UI/visual validation",
              "fixture_kind": "synthetic-only", "session": fixture["session"], "backend": args.expected_backend}
    client = None
    try:
        with (evidence / "stdio-events.jsonl").open("x", encoding="utf-8") as trace:
            env = dict(os.environ, DM_MCP_BACKEND="native", DM_NATIVE_SESSION=fixture["session"],
                       DM_MCP_TIMEOUT_MS=str(max(100, int((args.timeout_seconds - 0.5) * 1000))), DM_MCP_ALLOW_DMSCRIPT="0")
            client = StdioClient([args.node, str(args.server.resolve())], env, trace, args.timeout_seconds)
            report.update(run_acceptance(client, fixture, args.expected_backend, args.expected_build, args.expected_host_pid, args.mean_repeats))
            report["status"] = "PASS"
    except Exception as error:
        report.update(error_type=type(error).__name__, error=str(error))
    finally:
        if client is not None:
            try:
                client.close()
                if client.proc.returncode != 0:
                    report.update(status="FAIL", error_type="ClientShutdownError", error="The owned Node subprocess did not exit cleanly")
            except Exception as error:
                report.update(status="FAIL", error_type=type(error).__name__, error="Client shutdown failed: " + str(error))
            (evidence / "node-stderr.txt").write_bytes(bytes(client.stderr))
            report["node_exit_code"] = client.proc.returncode
        with (evidence / "result.json").open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2, ensure_ascii=True, allow_nan=False)
    print(json.dumps({"status": report["status"], "evidence_directory": str(evidence), "scope": report["scope"]}, ensure_ascii=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
