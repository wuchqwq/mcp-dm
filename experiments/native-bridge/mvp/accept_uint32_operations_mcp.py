# -*- coding: utf-8 -*-
"""Record a fixed synthetic uint32 production workflow over strict stdio MCP.

Every NB2 request is durably recorded before submission. Only this client's
own Node and explicitly requested external-analysis processes are started.
This client never controls DM, retries an uncertain producer, performs SHOW,
or certifies live pixels. The independent same-host oracle must qualify the
recorded results before the two explicit SHOW/lifecycle checks are performed.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from accept_mcp import (ROOT, StdioClient, integer, require, strict_json,
                        validate_receipt)
from accept_summary_mcp import CATALOG
from uint32_operations_acceptance import (Evidence, READ_TARGETS, SHOW_TARGETS,
    load_truth, plan, record, sha, specification, status_contract)


REPORT_NAME = "uint32-operations-mcp-report.json"
LEDGER_NAME = "uint32-operations-requests.jsonl"
RECOVERY_LEDGER_NAME = "uint32-operations-recovery-requests.jsonl"
FOURIER = {"FFT", "IFFT", "REAL", "IMAG", "VENDOR_ARG", "VENDOR_NORM"}
# A saved report describes its historical catalog, not the current Node child.
# Only these exact known sets are admitted; live connections below still
# require the current CATALOG. No receipt/argument/qualification is rewritten.
LEGACY_PRE_ROIS_CATALOG = {"dm_status", "dm_datasets", "dm_native_mean", "dm_native_summary",
    "dm_native_result", "dm_crop", "dm_native_show", "dm_native_unary", "dm_native_binary",
    "dm_native_fft", "dm_native_complex", "dm_native_filter", "dm_native_preview", "dm_native_read",
    "dm_native_result_info", "dm_native_release"}
LEGACY_ROIS_CATALOG = LEGACY_PRE_ROIS_CATALOG | {"dm_native_rois"}
LEGACY_PROFILE_CATALOG = LEGACY_ROIS_CATALOG | {"dm_native_profile"}


def valid_saved_catalog(value):
    return (type(value) is list and all(type(name) is str for name in value)
            and len(value) == len(set(value))
            and set(value) in (LEGACY_PRE_ROIS_CATALOG, LEGACY_ROIS_CATALOG, LEGACY_PROFILE_CATALOG, CATALOG))


def new_json(filename, value):
    with Path(filename).open("x", encoding="utf-8") as output:
        json.dump(value, output, indent=2, ensure_ascii=True, allow_nan=False)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def new_bytes(filename, raw):
    with Path(filename).open("xb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())


def analysis_python_executable(value):
    resolved = shutil.which(str(value))
    require(resolved is not None and Path(resolved).is_file(),
            "Analysis Python executable does not exist; no native request has been submitted")
    return str(Path(resolved).resolve())


def complete_handoff(report, directory, snapshots, node, analysis_python):
    workspace = directory / "external-workspace"
    workspace.mkdir()
    for label, snapshot in snapshots:
        request_id = "u32op-encode-" + label + "-" + uuid.uuid4().hex
        command = [node, str(ROOT / "tools" / "native_snapshot_handoff.mjs"), "--workspace", str(workspace),
            "--output", "capture-" + label, "--request-id", request_id, "--snapshot", str(snapshot)]
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=True)
        captured = strict_json(completed.stdout.decode("utf-8", errors="strict"))
        require(type(captured) is dict and captured.get("state") == "captured", "Explicit uint32 operation NPY encoder failed")
        report["captures"].append({"label": label, "snapshot": str(snapshot), "snapshot_sha256": sha(snapshot.read_bytes()),
            "request_record": str(workspace / "handoff-requests" / (request_id + ".json")), "receipt": captured})
        external_name = "external-mean-" + label
        command = [analysis_python, str(ROOT / "examples" / "native_handoff_mean.py"), "--workspace", str(workspace),
            "--capture", captured["capture_dir"], "--output", external_name]
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=True)
        report["externals"].append({"capture_label": label, "output_dir": str(workspace / external_name),
            "command": command, "stdout": completed.stdout.decode("utf-8", errors="strict"),
            "stderr": completed.stderr.decode("utf-8", errors="strict")})
        external = strict_json(report["externals"][-1]["stdout"])
        require(type(external) is dict and external.get("state") == "complete" and external.get("dm_called") is False
                and external.get("result_returned_to_dm") is False, "Explicit external example did not complete independently")


def persist_request(ledger, session, host_pid, operation, native_args, request_id):
    saved = record(session, host_pid, operation, native_args, request_id)
    ledger.write(json.dumps(saved, ensure_ascii=True, allow_nan=False) + "\n")
    ledger.flush()
    os.fsync(ledger.fileno())
    return saved


def completed_output(response, saved, host_thread, worker_tid):
    require(type(response) is dict and type(response.get("isError", False)) is bool
            and response.get("isError") is not True, "uint32 operation MCP tool failed; preserve the original request, do not resubmit")
    content = response.get("content")
    require(type(content) is list and len(content) == 1 and type(content[0]) is dict
            and content[0].get("type") == "text" and type(content[0].get("text")) is str,
            "uint32 operation requires exactly one JSON text block, not PNG or an error")
    output = strict_json(content[0]["text"])
    require(type(output) is dict, "uint32 operation output must be an object")
    receipt = validate_receipt(output, saved["id"], saved["session"],
                               "digitalmicrograph-native", saved["host_pid"], host_thread)
    require(receipt.get("original_operation") == saved["op"]
            and receipt.get("normalized_args") == saved["args"], "uint32 operation original identity changed")
    require(worker_tid is None or receipt["worker_tid"] == worker_tid, "uint32 operation worker identity changed")
    require(not any(key in receipt for key in ("result", "code", "error")),
            "Completed public native receipt contains terminal error/embedded result fields")
    timing = receipt.get("timings_us")
    require(type(timing) is dict and set(timing) == {"queue", "execute"}
            and all(integer(timing[key]) for key in timing), "uint32 operation timing fields invalid")
    require(receipt["result_version"] == (2 if saved["op"] in FOURIER else 1),
            "uint32 production operation result version mismatch")
    require(output.get("candidate_probe") is not True and output.get("qualification") != "NOT_QUALIFIED",
            "Unqualified probe result is not production MCP evidence")
    return output


def output_identity(output, item, native_args, source_ids, output_ids):
    operation = item["op"]
    image_id, image = output.get("image_id"), output.get("image")
    require(integer(image_id, 1, 0xfffffffe) and image_id not in source_ids
            and image_id not in output_ids and type(image) is dict and image.get("id") == image_id,
            "uint32 operation output ID aliases a source/earlier output or differs from metadata")
    dtype = ("complex64" if operation in ("FFT", "IFFT") else "uint32"
             if operation == "CROP" or operation == "FILTER" and item["opcode"] in (1, 4) else "float32")
    require(image.get("dtype") == dtype and image.get("data_type_code") == {"float32": 2, "complex64": 3, "uint32": 11}[dtype]
            and image.get("packing_style") == 1, "uint32 operation native output dtype/code/packing mismatch")
    if dtype == "uint32":
        require(image.get("is_integer") is True and image.get("is_unsigned") is True,
                "uint32 operation native output integer/unsigned flags mismatch")
    sources = native_args[:2] if operation == "BINARY" else native_args[:1]
    require(output.get("source_image_ids") == sources if operation in ("UNARY", "BINARY")
            else output.get("source_image_id") == sources[0], "uint32 operation result source ID mismatch")
    require(output.get("source_write_requested") is False and output.get("snapshot_atomic") is False,
            "uint32 operation source-protection/snapshot contract mismatch")
    return image_id


def resume_source(evidence, filename, truth_path, truth, sources):
    """Accept only a complete immutable native phase, never partial producers."""
    original_path = Path(filename).resolve()
    original = evidence.json(str(original_path))
    require(original.get("schema") == 1 and original.get("kind") == "synthetic-only"
            and original.get("status") == "FAIL" and original.get("error_type") == "FileNotFoundError"
            and type(original.get("error")) is str and bool(original["error"])
            and original.get("qualification_mode") == "production"
            and original.get("host_pid") == truth["host_pid"] and original.get("session") == truth["session"]
            and original.get("truth_sha256") == sha(evidence.raw(str(truth_path)))
            and valid_saved_catalog(original.get("catalog")), "Resume requires the original complete production post-native FileNotFound FAIL report")

    def ledger(filename):
        values = {}
        for line in evidence.raw(str(filename)).splitlines():
            saved = strict_json(line)
            request_id = saved.get("id")
            require(type(request_id) is str and 1 <= len(request_id) <= 64
                    and all(ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for ch in request_id)
                    and request_id not in values and type(saved.get("args")) is list
                    and all(integer(value, 0, 0xffffffff) for value in saved["args"])
                    and saved == record(truth["session"], truth["host_pid"], saved.get("op"), saved["args"], request_id),
                    "Resume original ledger/wire/ID mismatch")
            values[request_id] = saved
        return values

    original_ledger = original_path.parent / LEDGER_NAME
    original_recovery = original_path.parent / RECOVERY_LEDGER_NAME
    requests, query_requests = ledger(original_ledger), ledger(original_recovery)
    seen, outputs, entries = set(), {}, {}
    host_thread = worker_tid = None

    def bind(entry, label, tool, arguments, operation, native_args):
        saved = entry.get("request", {})
        request_id = saved.get("id")
        require(entry.get("label") == label and request_id in requests and request_id not in seen
                and saved == requests[request_id] == record(truth["session"], truth["host_pid"], operation, native_args, request_id)
                and entry.get("tool") == tool and entry.get("arguments") == dict(arguments, request_id=request_id),
                "Resume original tool/arguments/request binding mismatch")
        output = completed_output(entry.get("response"), saved, host_thread, worker_tid)
        seen.add(request_id)
        return output

    matrix = plan()
    checks = original.get("checks")
    require(type(checks) is list and [entry.get("label") for entry in checks] == ["STATUS"] + [item["label"] for item in matrix] + ["STATUS_FINAL"],
            "Resume requires all 32 terminal producers and both original STATUS records")
    status = bind(checks[0], "STATUS", "dm_status", {}, "STATUS", [])
    status_contract(status, truth["host_pid"], "production")
    host_thread, worker_tid = status["native_receipt"]["exec_tid"], status["native_receipt"]["worker_tid"]
    require(integer(status.get("retained_result_count"), 0, 0), "Resume original initial pool was not empty")
    source_ids = {entry[0]["id"] for entry in sources.values()}
    for item, entry in zip(matrix, checks[1:-1]):
        tool, arguments, operation, native_args = specification(item, sources, outputs)
        output = bind(entry, item["label"], tool, arguments, operation, native_args)
        outputs[item["label"]] = output_identity(output, item, native_args, source_ids, set(outputs.values()))
        entries[item["label"]] = entry
    status = bind(checks[-1], "STATUS_FINAL", "dm_status", {}, "STATUS", [])
    status_contract(status, truth["host_pid"], "production")
    require(integer(status.get("retained_result_count"), 32, 32) and original.get("output_ids") == outputs
            and original.get("show_targets") == [{"label": label, "image_id": outputs[label]} for label in SHOW_TARGETS],
            "Resume original final output pool/ID/SHOW target binding mismatch")
    reads = original.get("reads")
    require(type(reads) is list and len(reads) == 2 and {entry.get("label") for entry in reads} == set(READ_TARGETS),
            "Resume requires both original completed typed READs")
    for entry in reads:
        label = entry["label"]
        parent, rect = READ_TARGETS[label]
        image_id = outputs[parent]
        output = bind(entry, label, "dm_native_read", {"image_id": image_id, "rect": rect}, "READ", [image_id] + rect)
        require(output.get("source_image_id") == image_id and output.get("requested_rect") == rect and output.get("effective_rect") == rect
                and output.get("dtype") == ("uint32" if label == "filter" else "float32"), "Resume original READ source/ROI/dtype mismatch")
        producer = entries[parent]["request"]
        provenance = output.get("source_provenance", {})
        require(type(provenance) is dict and set(provenance) == {"operation", "request_id", "source_image_ids", "semantics"}
                and provenance["operation"] == producer["op"] and provenance["request_id"] == producer["id"]
                and provenance["source_image_ids"] == (producer["args"][:2] if producer["op"] == "BINARY" else producer["args"][:1])
                and type(provenance["semantics"]) is str and bool(provenance["semantics"]), "Resume original READ creation identity mismatch")
        snapshot = original_path.parent / ("snapshot-" + label + ".json")
        require(evidence.json(str(snapshot)) == entry["response"], "Resume original saved READ response differs from its immutable record")
    require(seen == set(requests), "Resume original request ledger has missing or unbound submissions")
    recovery = original.get("recovery")
    require(type(recovery) is list and [entry.get("label") for entry in recovery] == [item["label"] for item in matrix]
            and len(query_requests) == 32, "Resume requires the complete original fresh-client 32-QUERY matrix")
    for item, entry in zip(matrix, recovery):
        saved = entry.get("request", {})
        original_entry = entries[item["label"]]
        request_id = original_entry["request"]["id"]
        require(request_id in query_requests and saved == query_requests[request_id] == record(truth["session"], truth["host_pid"], "QUERY", [], request_id)
                and entry.get("response") == original_entry["response"], "Resume original fresh-client QUERY identity/response mismatch")
    captures = original.get("captures")
    require(type(captures) is list and len(captures) == 1 and captures[0].get("label") == "filter"
            and original.get("externals") == [], "Resume only accepts the first-filter-capture external-start failure")
    preserved = []
    for entry in captures:
        require(entry.get("label") in READ_TARGETS and type(entry.get("receipt")) is dict, "Resume existing capture identity invalid")
        snapshot = Path(entry["snapshot"])
        require(sha(evidence.raw(str(snapshot))) == entry.get("snapshot_sha256"), "Resume existing capture snapshot hash changed")
        captured = entry["receipt"]
        require(captured.get("state") == "captured" and type(captured.get("files_sha256")) is dict
                and set(captured["files_sha256"]) == {"input.npy", "input.json", "capture.json"}, "Resume existing capture manifest invalid")
        for name, digest in captured["files_sha256"].items():
            path = Path(captured["capture_dir"]) / name
            require(sha(evidence.raw(str(path))) == digest, "Resume existing captured file hash changed")
            preserved.append({"path": str(path.resolve()), "sha256": digest})
        journal = Path(entry["request_record"]).resolve()
        preserved.append({"path": str(journal), "sha256": sha(evidence.raw(str(journal)))})
    for label in READ_TARGETS:
        snapshot = original_path.parent / ("snapshot-" + label + ".json")
        preserved.append({"path": str(snapshot), "sha256": sha(evidence.raw(str(snapshot)))})
    require(not original.get("externals"), "Resume mode only accepts the external-start failure before any recorded external result")
    return original, original_path, original_ledger, original_recovery, entries, (host_thread, worker_tid), preserved


def resume_handoff(args, evidence, truth_path, truth, sources):
    original, original_path, original_ledger, original_recovery, entries, threads, preserved = resume_source(
        evidence, args.resume_report, truth_path, truth, sources)
    directory = args.output_directory.resolve()
    directory.mkdir(exist_ok=False)
    report = dict(original)
    report.update(status="FAIL", captures=[], externals=[])
    report.pop("error", None)
    report.pop("error_type", None)
    report.pop("shutdown_error", None)
    report["recovered_from"] = {}
    for role, source, destination in (("report", original_path, directory / "original-failed-report.json"),
        ("ledger", original_ledger, directory / LEDGER_NAME), ("recovery_ledger", original_recovery, directory / RECOVERY_LEDGER_NAME)):
        raw = evidence.raw(str(source))
        new_bytes(destination, raw)
        report["recovered_from"][role] = {"path": str(source), "sha256": sha(raw), "bytes_copy": str(destination)}
    report["recovered_from"]["preserved_files"] = preserved
    resume_ledger = directory / "uint32-operations-resume-requests.jsonl"
    report["resume"] = {"ledger": str(resume_ledger), "queries": []}
    client = None
    node = shutil.which("node") or "node"
    with (directory / REPORT_NAME).open("x", encoding="utf-8") as report_file:
        try:
            with (directory / "uint32-operations-events.jsonl").open("x", encoding="utf-8") as trace, resume_ledger.open("x", encoding="utf-8") as ledger:
                client = StdioClient([node, str(ROOT / "server.mjs")], dict(os.environ, DM_MCP_BACKEND="native", DM_NATIVE_SESSION=truth["session"],
                    DM_MCP_TIMEOUT_MS="20000", DM_MCP_ALLOW_DMSCRIPT="0"), trace, 25)
                initialized = client.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "native-uint32-operations-resume", "version": "1"}})
                require("error" not in initialized and initialized.get("result", {}).get("protocolVersion") == "2024-11-05"
                        and initialized["result"].get("serverInfo") == {"name": "digitalmicrograph", "version": "0.6.0"}, "Resume MCP initialization failed")
                client.notify("notifications/initialized")
                listed = client.rpc("tools/list", {})
                catalog = listed.get("result", {}).get("tools")
                require("error" not in listed and type(catalog) is list and len(catalog) == len(CATALOG)
                        and all(type(tool) is dict and type(tool.get("name")) is str for tool in catalog)
                        and {tool["name"] for tool in catalog} == CATALOG, "Resume native catalog changed")
                for item in plan():
                    original_entry = entries[item["label"]]
                    request_id = original_entry["request"]["id"]
                    saved = persist_request(ledger, truth["session"], truth["host_pid"], "QUERY", [], request_id)
                    message = client.rpc("tools/call", {"name": "dm_native_result", "arguments": {"request_id": request_id}})
                    require("error" not in message and type(message.get("result")) is dict, "Resume QUERY failed; no producer may be submitted")
                    report["resume"]["queries"].append({"label": item["label"], "request": saved, "response": message["result"]})
                    completed_output(message["result"], original_entry["request"], threads[0], threads[1])
                    require(message["result"] == original_entry["response"], "Resume QUERY differs from original immutable completed response")
            report["resume"]["ledger_sha256"] = sha(resume_ledger.read_bytes())
            snapshots = []
            for label in READ_TARGETS:
                source = original_path.parent / ("snapshot-" + label + ".json")
                destination = directory / source.name
                new_bytes(destination, evidence.raw(str(source)))
                snapshots.append((label, destination))
            complete_handoff(report, directory, snapshots, node, args.analysis_python)
            evidence.unchanged()
            report["status"] = "RECORDED_RECOVERED"
        except BaseException as error:
            report.update(status="FAIL", error_type=type(error).__name__, error=str(error))
            if isinstance(error, subprocess.CalledProcessError):
                report.update(subprocess_stdout=(error.stdout or b"").decode("utf-8", errors="replace"),
                              subprocess_stderr=(error.stderr or b"").decode("utf-8", errors="replace"))
        finally:
            if client is not None:
                try:
                    client.close()
                    require(client.proc.returncode == 0, "Owned resume stdio child did not exit normally")
                except Exception as error:
                    report.update(status="FAIL", shutdown_error=str(error))
                new_bytes(directory / "uint32-operations-stderr-0.txt", bytes(client.stderr))
            json.dump(report, report_file, indent=2, ensure_ascii=True, allow_nan=False)
            report_file.write("\n")
            report_file.flush()
            os.fsync(report_file.fileno())
    print(report["status"] + ": original failed evidence preserved; independent same-host oracle REQUIRED; no producer was resubmitted")
    return 0 if report["status"] == "RECORDED_RECOVERED" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--qualification-mode", required=True, choices=("production",))
    parser.add_argument("--analysis-python", default=sys.executable)
    parser.add_argument("--resume-report", type=Path, help="Recover only a complete post-native FileNotFound FAIL using QUERY and new external files")
    args = parser.parse_args(argv)
    args.analysis_python = analysis_python_executable(args.analysis_python)
    truth_path = args.directory.resolve() / "uint32-production-truth.json"
    evidence = Evidence()
    original_truth = evidence.json(str(truth_path))
    require(integer(original_truth.get("host_pid"), 1, 0xffffffff), "Explicit synthetic host PID required")
    truth, sources = load_truth(evidence, str(truth_path), original_truth["host_pid"])
    require(truth["session"] == os.environ.get("DM_NATIVE_SESSION"), "Explicit production session differs from fixture")
    if args.resume_report is not None:
        return resume_handoff(args, evidence, truth_path, truth, sources)
    operation_plan = plan()
    require(len(operation_plan) == 32 and len({item["label"] for item in operation_plan}) == 32,
            "Fixed 32-operation production plan required")
    directory = args.output_directory.resolve()
    directory.mkdir(exist_ok=False)
    report = {"schema": 1, "kind": "synthetic-only", "status": "FAIL", "host_pid": truth["host_pid"],
        "session": truth["session"], "truth_sha256": sha(evidence.raw(str(truth_path))),
        "qualification_mode": args.qualification_mode, "checks": [], "reads": [], "recovery": [],
        "captures": [], "externals": [], "source_invariance": "NOT_TESTED_BY_THIS_CLIENT",
        "model_viewing": "NOT_TESTED", "independent_host_oracle_required": True,
        "show_status": "NOT_TESTED; run only after independent numerical oracle"}
    clients = []
    client = None
    node = shutil.which("node") or "node"
    host_thread = worker_tid = None
    outputs, entries = {}, {}
    report_path = directory / REPORT_NAME
    with report_path.open("x", encoding="utf-8") as report_file:
        try:
            with (directory / "uint32-operations-events.jsonl").open("x", encoding="utf-8") as trace, \
                 (directory / LEDGER_NAME).open("x", encoding="utf-8") as ledger, \
                 (directory / RECOVERY_LEDGER_NAME).open("x", encoding="utf-8") as recovery_ledger:
                def connect():
                    value = StdioClient([node, str(ROOT / "server.mjs")],
                        dict(os.environ, DM_MCP_BACKEND="native", DM_NATIVE_SESSION=truth["session"],
                             DM_MCP_TIMEOUT_MS="20000", DM_MCP_ALLOW_DMSCRIPT="0"), trace, 25)
                    clients.append(value)
                    try:
                        initialized = value.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                            "clientInfo": {"name": "native-uint32-operations-acceptance", "version": "1"}})
                        require("error" not in initialized and initialized.get("result", {}).get("protocolVersion") == "2024-11-05"
                                and initialized["result"].get("serverInfo") == {"name": "digitalmicrograph", "version": "0.6.0"},
                                "uint32 operations MCP initialization failed")
                        value.notify("notifications/initialized")
                        listed = value.rpc("tools/list", {})
                        catalog = listed.get("result", {}).get("tools")
                        require("error" not in listed and type(catalog) is list and len(catalog) == len(CATALOG)
                                and all(type(tool) is dict and type(tool.get("name")) is str for tool in catalog)
                                and {tool["name"] for tool in catalog} == CATALOG, "uint32 operations native catalog changed")
                        report["catalog"] = [tool["name"] for tool in catalog]
                        return value
                    except BaseException:
                        value.close()
                        raise

                def call(label, tool, arguments, operation, native_args, bucket="checks"):
                    request_id = "u32op-" + uuid.uuid4().hex
                    parameters = dict(arguments, request_id=request_id)
                    saved = persist_request(ledger, truth["session"], truth["host_pid"], operation, native_args, request_id)
                    message = client.rpc("tools/call", {"name": tool, "arguments": parameters})
                    require("error" not in message and type(message.get("result")) is dict, "uint32 operations RPC failed; no automatic retry")
                    entry = {"label": label, "tool": tool, "arguments": parameters, "request": saved, "response": message["result"]}
                    report[bucket].append(entry)
                    return completed_output(entry["response"], saved, host_thread, worker_tid), entry

                client = connect()
                status, unused = call("STATUS", "dm_status", {}, "STATUS", [])
                status_contract(status, truth["host_pid"], "production")
                host_thread, worker_tid = status["native_receipt"]["exec_tid"], status["native_receipt"]["worker_tid"]
                require(status.get("retained_result_count") == 0 and status.get("retained_result_bytes") == 0,
                        "Fixed production boundary plan requires an initially empty retained-result pool")
                source_ids = {entry[0]["id"] for entry in sources.values()}
                for item in operation_plan:
                    tool, parameters, operation, native_args = specification(item, sources, outputs)
                    output, entry = call(item["label"], tool, parameters, operation, native_args)
                    outputs[item["label"]] = output_identity(output, item, native_args, source_ids, set(outputs.values()))
                    entries[item["label"]] = entry
                report["output_ids"] = dict(outputs)
                report["show_targets"] = [{"label": label, "image_id": outputs[label]} for label in SHOW_TARGETS]
                snapshots = []
                for label, (producer_label, rect) in READ_TARGETS.items():
                    image_id = outputs[producer_label]
                    output, entry = call(label, "dm_native_read", {"image_id": image_id, "rect": rect},
                                         "READ", [image_id] + rect, "reads")
                    require(output.get("source_image_id") == image_id and output.get("requested_rect") == rect
                            and output.get("effective_rect") == rect and output.get("dtype") == ("uint32" if label == "filter" else "float32"),
                            "uint32 operation READ target/ROI/actual dtype changed")
                    provenance = output.get("source_provenance")
                    original = entries[producer_label]["request"]
                    expected_sources = original["args"][:2] if original["op"] == "BINARY" else original["args"][:1]
                    require(type(provenance) is dict and set(provenance) == {"operation", "request_id", "source_image_ids", "semantics"}
                            and provenance["operation"] == original["op"] and provenance["request_id"] == original["id"]
                            and provenance["source_image_ids"] == expected_sources
                            and type(provenance["semantics"]) is str and bool(provenance["semantics"]),
                            "uint32 operation READ immutable creation provenance changed")
                    saved = directory / ("snapshot-" + label + ".json")
                    new_json(saved, entry["response"])
                    snapshots.append((label, saved))

                client.close()
                require(client.proc.returncode == 0, "First owned stdio child did not exit normally")
                client = None
                client = connect()  # This does not restart or change the native host/session.
                for item in operation_plan:
                    original = entries[item["label"]]
                    original_id = original["request"]["id"]
                    saved = persist_request(recovery_ledger, truth["session"], truth["host_pid"], "QUERY", [], original_id)
                    message = client.rpc("tools/call", {"name": "dm_native_result", "arguments": {"request_id": original_id}})
                    require("error" not in message and type(message.get("result")) is dict, "Fresh-client uint32 QUERY failed; do not resubmit producer")
                    report["recovery"].append({"label": item["label"], "request": saved, "response": message["result"]})
                    completed_output(message["result"], original["request"], host_thread, worker_tid)
                    require(message["result"] == original["response"], "Fresh-client uint32 QUERY changed the immutable original response")
                status, unused = call("STATUS_FINAL", "dm_status", {}, "STATUS", [])
                status_contract(status, truth["host_pid"], "production")
                require(status.get("retained_result_count") == 32 and integer(status.get("retained_result_bytes"), 1, 16*1024*1024),
                        "Fixed production result pool must still contain exactly the 32 recorded outputs")

                complete_handoff(report, directory, snapshots, node, args.analysis_python)
                evidence.unchanged()
                report["status"] = "RECORDED"
        except BaseException as error:
            report.update(status="FAIL", error_type=type(error).__name__, error=str(error))
            if isinstance(error, subprocess.CalledProcessError):
                report.update(subprocess_stdout=(error.stdout or b"").decode("utf-8", errors="replace"),
                              subprocess_stderr=(error.stderr or b"").decode("utf-8", errors="replace"))
        finally:
            if client is not None:
                try:
                    client.close()
                    require(client.proc.returncode == 0, "Owned stdio child did not exit normally")
                except Exception as error:
                    report.update(status="FAIL", shutdown_error=str(error))
            for index, value in enumerate(clients):
                with (directory / ("uint32-operations-stderr-%d.txt" % index)).open("xb") as output:
                    output.write(bytes(value.stderr))
            json.dump(report, report_file, indent=2, ensure_ascii=True, allow_nan=False)
            report_file.write("\n")
            report_file.flush()
            os.fsync(report_file.fileno())
    print(report["status"] + ": independent same-host uint32 operations oracle REQUIRED; SHOW has not been performed")
    return 0 if report["status"] == "RECORDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
