"""Prepared synthetic-only stdio MCP -> saved READ -> explicit NPY handoff.

Starts only its own Node/analysis subprocesses. Never starts DM, injects a
script or certifies live pixels. Run the separate in-host oracle afterwards.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from accept_mcp import StdioClient, ROOT, require, strict_json, validate_receipt


def digest(filename):
    return hashlib.sha256(Path(filename).read_bytes()).hexdigest()


def new_json(filename, value):
    with Path(filename).open("x", encoding="utf-8") as output:
        json.dump(value, output, indent=2, ensure_ascii=True, allow_nan=False)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--analysis-python", default=sys.executable)
    parser.add_argument("--qualification-mode", choices=("prepared", "production"), required=True)
    args = parser.parse_args(argv)
    fixture_directory = args.directory.resolve()
    directory = args.output_directory.resolve()
    directory.mkdir(exist_ok=False)
    truth = strict_json((fixture_directory / "operations-truth.json").read_text(encoding="utf-8"))
    require(truth["kind"] == "synthetic-only" and truth["status"] == "RECORDED", "Prepared synthetic truth required")
    require(truth["session"] == os.environ.get("DM_NATIVE_SESSION"), "Session must be explicit")
    images = {item["label"]: item for item in truth["images"]}
    source = images["READ_BITS"]
    report = {"schema": 1, "status": "FAIL", "host_pid": truth["host_pid"], "session": truth["session"],
              "qualification_mode": args.qualification_mode,
              "source_label": "READ_BITS", "crop_rect": [1, 1, 4, 4], "read_rect": [0, 0, 3, 3],
              "source_read_rect": [0, 0, 4, 4], "checks": [], "previews": [], "extra_checks": [], "captures": [],
              "truth_sha256": digest(fixture_directory / "operations-truth.json"), "model_client": "NOT_TESTED",
              "source_invariance": "NOT_TESTED_BY_THIS_CLIENT", "independent_host_oracle_required": True}
    report_path = directory / "mcp-handoff-report.json"
    with report_path.open("x"): pass  # Refuse overwriting any earlier attempt.
    client = None
    try:
        with (directory / "mcp-handoff-events.jsonl").open("x", encoding="utf-8") as trace, \
             (directory / "mcp-handoff-requests.jsonl").open("x", encoding="utf-8") as ledger:
            env = dict(os.environ, DM_MCP_BACKEND="native", DM_NATIVE_SESSION=truth["session"],
                       DM_MCP_TIMEOUT_MS="20000", DM_MCP_ALLOW_DMSCRIPT="0")
            node = shutil.which("node") or "node"
            client = StdioClient([node, str(ROOT / "server.mjs")], env, trace, 25)
            initialized = client.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "prepared-native-handoff", "version": "1"}})
            require("error" not in initialized, "MCP initialize failed")
            client.notify("notifications/initialized")
            catalog = client.rpc("tools/list", {}).get("result", {}).get("tools", [])
            require(len(catalog) == 14 and any(t.get("name") == "dm_native_read" for t in catalog), "Wrong native catalog")
            report["catalog"] = [tool["name"] for tool in catalog]
            host_thread = worker_tid = None

            def call(label, tool, arguments, operation, native_args, bucket="checks"):
                request_id = "handoff-" + uuid.uuid4().hex
                arguments = dict(arguments, request_id=request_id)
                record = {"protocol": "NB2", "session": truth["session"], "host_pid": truth["host_pid"],
                          "id": request_id, "op": operation, "args": native_args,
                          "wire": "NB2 %s %s %s%s\n" % (truth["session"], request_id, operation,
                            " " + " ".join(str(value) for value in native_args) if native_args else "")}
                ledger.write(json.dumps(record, allow_nan=False) + "\n"); ledger.flush(); os.fsync(ledger.fileno())
                message = client.rpc("tools/call", {"name": tool, "arguments": arguments})
                require("error" not in message and isinstance(message.get("result"), dict), "RPC tool failure")
                response = message["result"]
                entry = {"label": label, "tool": tool, "arguments": arguments, "request": record, "response": response}
                report[bucket].append(entry)
                require(response.get("isError") is not True and response.get("content", [{}])[0].get("type") == "text", "MCP tool rejected")
                output = strict_json(response["content"][0]["text"])
                receipt = validate_receipt(output, request_id, truth["session"], "digitalmicrograph-native", truth["host_pid"], host_thread)
                require(receipt["original_operation"] == operation and receipt["normalized_args"] == native_args, "Original operation mismatch")
                if worker_tid is not None: require(receipt["worker_tid"] == worker_tid, "Worker identity changed")
                return output, entry

            status, unused = call("status", "dm_status", {}, "STATUS", [])
            host_thread, worker_tid = status["native_receipt"]["exec_tid"], status["native_receipt"]["worker_tid"]
            require(status.get("ready") is True and status.get("binary_gate") is True and
                    status.get("compatibility", {}).get("state") == "SUPPORTED", "Actual adapter is not ready")
            preview, preview_entry = call("source", "dm_native_preview", {"image_id": source["id"]},
                                         "PREVIEW", [source["id"], 128, 128], "previews")
            png_blocks = [item for item in preview_entry["response"]["content"] if item.get("type") == "image"]
            require(len(png_blocks) == 1 and png_blocks[0].get("mimeType") == "image/png", "Bounded PNG missing")
            png = directory / "mcp-source-preview.png"
            with png.open("xb") as output: output.write(base64.b64decode(png_blocks[0]["data"], validate=True))
            preview_entry.update(png=str(png), png_sha256=digest(png))
            crop, unused = call("crop", "dm_crop", {"image_id": source["id"], "rect": report["crop_rect"]},
                                "CROP", [source["id"]] + report["crop_rect"])
            square, unused = call("square", "dm_native_unary", {"image_id": crop["image_id"], "operation": "square"},
                                  "UNARY", [crop["image_id"], 3])
            snapshots = []
            for label, image_id, rect, capture_label in (("read_source", source["id"], report["source_read_rect"], "source"),
                                                        ("read", square["image_id"], report["read_rect"], "processed")):
                read, entry = call(label, "dm_native_read", {"image_id": image_id, "rect": rect}, "READ", [image_id] + rect)
                saved = directory / ("snapshot-" + capture_label + ".json")
                new_json(saved, entry["response"])
                snapshots.append((capture_label, saved))
                recovered = client.rpc("tools/call", {"name": "dm_native_result", "arguments": {"request_id": entry["arguments"]["request_id"]}})
                require(recovered.get("result") == entry["response"], "READ immutable QUERY changed")
            # Additional public-MCP checks of the current Fourier v2 contract.
            fourier, unused = call("fft", "dm_native_fft", {"image_id": images["A"]["id"], "direction": "forward"},
                                  "FFT", [images["A"]["id"]], "extra_checks")
            require(fourier["native_receipt"]["result_version"] == 2, "Fourier v2 receipt missing")
            inverse, unused = call("ifft", "dm_native_fft", {"image_id": fourier["image_id"], "direction": "inverse"},
                                  "IFFT", [fourier["image_id"]], "extra_checks")
            real, unused = call("inverse_real", "dm_native_complex", {"image_id": inverse["image_id"], "component": "real"},
                                "REAL", [inverse["image_id"]], "extra_checks")
            for code, operation in enumerate(("smooth", "sobel", "laplace", "sharpen"), 1):
                call(operation, "dm_native_filter", {"image_id": images["FILTER_A"]["id"], "operation": operation},
                     "FILTER", [images["FILTER_A"]["id"], code], "extra_checks")
            # Invalid input is an explicit refusal; it must never become a success.
            missing = client.rpc("tools/call", {"name": "dm_native_unary", "arguments": {"image_id": source["id"], "operation": "square"}})
            require(missing.get("error", {}).get("code") == -32602, "Missing side-effect request ID accepted")
            report["missing_side_effect_id_rejected"] = True
            workspace = directory / "external-workspace"; workspace.mkdir()
            for label, saved in snapshots:
                request_id = "encode-" + label + "-" + uuid.uuid4().hex
                command = [node, str(ROOT / "tools" / "native_snapshot_handoff.mjs"), "--workspace", str(workspace),
                           "--output", "capture-" + label, "--request-id", request_id, "--snapshot", str(saved)]
                completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                receipt = strict_json(completed.stdout.decode("utf-8"))
                require(receipt.get("state") == "captured", "NPY handoff did not complete")
                # Same immutable request returns the original files/receipt.
                repeated = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                require(strict_json(repeated.stdout.decode("utf-8")) == receipt, "Repeated handoff changed output")
                report["captures"].append({"label": label, "snapshot": str(saved), "snapshot_sha256": digest(saved),
                    "request_record": str(workspace / "handoff-requests" / (request_id + ".json")), "receipt": receipt})
            processed = next(item for item in report["captures"] if item["label"] == "processed")
            external_dir = workspace / "external-mean"
            command = [args.analysis_python, str(ROOT / "examples" / "native_handoff_mean.py"),
                       "--workspace", str(workspace), "--capture", processed["receipt"]["capture_dir"],
                       "--output", "external-mean"]
            completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            report["external"] = {"capture_label": "processed", "output_dir": str(external_dir),
                "command": command, "stdout": completed.stdout.decode("utf-8"), "stderr": completed.stderr.decode("utf-8")}
            report["status"] = "RECORDED"
    except BaseException as error:
        report.update(status="FAIL", error_type=type(error).__name__, error=str(error))
    finally:
        if client is not None:
            try:
                client.close()
                require(client.proc.returncode == 0, "Owned stdio child did not exit normally")
            except Exception as error: report.update(status="FAIL", shutdown_error=str(error))
            with (directory / "mcp-handoff-stderr.txt").open("xb") as output:
                output.write(bytes(client.stderr))
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "independent_host_oracle": "REQUIRED"}))
    return 0 if report["status"] == "RECORDED" else 1


if __name__ == "__main__":
    sys.exit(main())
