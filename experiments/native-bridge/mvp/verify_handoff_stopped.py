# -*- coding: utf-8 -*-
"""Same-host, read-only check after an independently submitted original STOP.

No IPC, GUI action, document search, image creation or cleanup is performed.
Only explicitly recorded completed output IDs are examined. Historical failed
attempts remain failed; they contribute ownership IDs, never numerical PASS.
"""
import json
import os

from create_summary_fixture import require
from verify_handoff import (Evidence, ID, bind_call, bind_pipeline, check_preview,
                            check_source, integer, observe, observation_expected,
                            payload, prepare, sha, strict_json, validate_capture)
from verify_operations_lifecycle import saved_operation


def bind_current(evidence, truth_path, report_path, ledger_path, independent_path):
    context = prepare(evidence, truth_path, report_path, ledger_path, os.getpid())
    bind_pipeline(context)
    independent = evidence.json(independent_path)
    require(independent.get("schema") == 1 and independent.get("kind") == "synthetic-only" and
            independent.get("status") == "PASS_BOUNDED_SYNTHETIC_HANDOFF" and
            integer(independent.get("host_pid"), os.getpid(), os.getpid()) and independent.get("session") == context["session"] and
            independent.get("qualification_mode") == context["qualification_mode"] and
            independent.get("truth_sha256") == sha(evidence.raw(truth_path)) and
            independent.get("mcp_report_sha256") == sha(evidence.raw(report_path)) and
            independent.get("ledger_sha256") == sha(evidence.raw(ledger_path)) and
            independent.get("source_protection") == independent.get("independent_memory") == "PASS" and
            independent.get("numeric_handoff") == "PASS_BITWISE_FLOAT32" and independent.get("signed_zero_and_subnormal") == "PASS" and
            independent.get("raw_views_and_wrappers_released") is True and
            independent.get("crop_id") == context["crop_id"] and independent.get("processed_id") == context["square_id"] and
            independent.get("document_count") == context["truth"]["initial_document_count"],
            "Original successful same-host handoff observation/hash/flags mismatch")
    original_hashes = independent.get("evidence_files_sha256")
    require(type(original_hashes) is dict and len(original_hashes) > 10, "Original handoff evidence hash map missing")
    for path, expected in original_hashes.items():
        require(type(path) is str and os.path.isabs(path) and sha(evidence.raw(path)) == expected,
                "Original pre-STOP handoff evidence file changed")
    captures = context["report"].get("captures")
    require(type(captures) is list and len(captures) == 2 and {v.get("label") for v in captures} == {"source", "processed"},
            "Original source/processed captures missing")
    packages = {}
    for entry in captures:
        packages[entry["label"]] = validate_capture(evidence, entry,
            context["reads"]["read_source" if entry["label"] == "source" else "read"])
    source_entry, source_values = context["sources"]["READ_BITS"]
    check_preview(context, evidence, observation_expected(source_entry, source_values))
    extras = context["report"].get("extra_checks")
    labels = {"fft", "ifft", "inverse_real", "smooth", "sobel", "laplace", "sharpen"}
    require(type(extras) is list and len(extras) == 7 and {v.get("label") for v in extras} == labels,
            "Complete recorded extra operation matrix required")
    extras = {entry["label"]: entry for entry in extras}
    outputs = {context["crop_id"]: {"label": "crop", "request_id": context["crop"]["native_receipt"]["id"]},
               context["square_id"]: {"label": "square", "request_id": context["square"]["native_receipt"]["id"]}}
    observed_extras = independent.get("additional_operations")
    require(type(observed_extras) is list and len(observed_extras) == 7 and
            {value.get("label") for value in observed_extras} == labels, "Original extra-operation observations incomplete")
    observed_extras = {entry["label"]: entry for entry in observed_extras}
    parent = context["sources"]["A"][0]["id"]
    for label, op, tool, extra in (("fft", "FFT", "dm_native_fft", {"direction": "forward"}),
                                   ("ifft", "IFFT", "dm_native_fft", {"direction": "inverse"}),
                                   ("inverse_real", "REAL", "dm_native_complex", {"component": "real"})):
        result = bind_call(extras[label], tool, dict(extra, image_id=parent), op, [parent], context)
        image_id = result.get("image_id")
        require(integer(image_id, 1) and image_id not in context["source_ids"] | set(outputs) and
                result.get("source_image_id") == parent and result.get("image", {}).get("id") == image_id,
                "Recorded Fourier output/source identity invalid")
        observation = observed_extras[label]
        require(observation.get("status") == "PASS_PREDETERMINED_FIXTURE_ONLY" and observation.get("image_id") == image_id and
                observation.get("request_id") == result["native_receipt"]["id"], "Original Fourier ownership observation identity mismatch")
        outputs[image_id] = {"label": label, "request_id": result["native_receipt"]["id"]}
        parent = image_id
    parent = context["sources"]["FILTER_A"][0]["id"]
    for code, label in enumerate(("smooth", "sobel", "laplace", "sharpen"), 1):
        result = bind_call(extras[label], "dm_native_filter", {"image_id": parent, "operation": label}, "FILTER", [parent, code], context)
        image_id = result.get("image_id")
        require(integer(image_id, 1) and image_id not in context["source_ids"] | set(outputs) and
                result.get("source_image_id") == parent and result.get("filter_kind") == code and result.get("image", {}).get("id") == image_id,
                "Recorded FILTER output/source identity invalid")
        observation = observed_extras[label]
        require(observation.get("status") == "PASS_PREDETERMINED_FIXTURE_ONLY" and observation.get("image_id") == image_id and
                observation.get("request_id") == result["native_receipt"]["id"], "Original FILTER ownership observation identity mismatch")
        outputs[image_id] = {"label": label, "request_id": result["native_receipt"]["id"]}
    require(context["seen"] == set(context["ledger"]), "Original complete handoff request matrix mismatch")
    context.update(outputs=outputs, packages=packages, independent=independent,
                   operation_request_ids=set(context["ledger"]), host_thread=context["threads"][0], worker_tid=context["threads"][1])
    return context


def bind_failed_prefix(evidence, path, context):
    """Only the explicitly saved failed handoff prefix, never arbitrary IDs."""
    previous = evidence.json(path)
    require(previous.get("schema") == 1 and previous.get("status") == "FAIL" and
            integer(previous.get("host_pid"), os.getpid(), os.getpid()) and previous.get("session") == context["session"] and
            previous.get("truth_sha256") == sha(evidence.raw(context["truth_path"])) and
            previous.get("source_label") == "READ_BITS" and previous.get("crop_rect") == [1, 1, 4, 4],
            "Historical failed prefix host/session/truth mismatch")
    ledger_path = os.path.join(os.path.dirname(path), "mcp-handoff-requests.jsonl")
    records = [strict_json(line) for line in evidence.raw(ledger_path).splitlines()]
    ledger = {}
    for request in records:
        request_id = request.get("id")
        require(type(request) is dict and set(request) == {"protocol", "session", "id", "op", "args", "host_pid", "wire"} and
                type(request_id) is str and ID.fullmatch(request_id) is not None and
                request_id not in ledger and request_id not in context["operation_request_ids"] and
                request.get("protocol") == "NB2" and request.get("session") == context["session"] and
                integer(request.get("host_pid"), os.getpid(), os.getpid()) and
                request.get("op") in ("STATUS", "PREVIEW", "CROP", "UNARY", "READ") and
                type(request.get("args")) is list and all(integer(value) for value in request["args"]),
                "Historical prefix original request identity invalid")
        wire = "NB2 %s %s %s%s\n" % (context["session"], request_id, request["op"],
                                     " " + " ".join(map(str, request["args"])) if request["args"] else "")
        require(request.get("wire") == wire, "Historical prefix original wire mismatch")
        ledger[request_id] = request
    local = {"pid": os.getpid(), "session": context["session"], "ledger": ledger, "seen": set(), "threads": context["threads"]}
    checks = previous.get("checks")
    require(type(checks) is list, "Historical prefix checks missing")
    matches = {label: [entry for entry in checks if entry.get("label") == label] for label in ("status", "crop", "square")}
    require(all(len(values) == 1 for values in matches.values()), "Historical prefix completed producer records missing/duplicate")
    status = bind_call(matches["status"][0], "dm_status", {}, "STATUS", [], local)
    require(status.get("ready") is True and status.get("binary_gate") is True and status.get("host_pid") == os.getpid() and
            status.get("host_thread") == context["host_thread"] and status.get("adapter_profile") == "gms-3.53.4137.0-windows-x64",
            "Historical prefix STATUS anchor mismatch")
    source_id = context["sources"]["READ_BITS"][0]["id"]
    crop = bind_call(matches["crop"][0], "dm_crop", {"image_id": source_id, "rect": [1, 1, 4, 4]}, "CROP", [source_id, 1, 1, 4, 4], local)
    crop_id = crop.get("image_id")
    require(integer(crop_id, 1) and crop_id not in context["source_ids"] | set(context["outputs"]) and
            crop.get("source_image_id") == source_id and crop.get("requested_rect") == crop.get("effective_rect") == [1, 1, 4, 4] and
            crop.get("image", {}).get("id") == crop_id and crop.get("operator") == "GMS::Image::GetSubSliceAsImage",
            "Historical prefix CROP output identity invalid")
    square = bind_call(matches["square"][0], "dm_native_unary", {"image_id": crop_id, "operation": "square"}, "UNARY", [crop_id, 3], local)
    square_id = square.get("image_id")
    require(integer(square_id, 1) and square_id not in context["source_ids"] | set(context["outputs"]) | {crop_id} and
            square.get("operation") == "square" and square.get("opcode") == 3 and square.get("source_image_ids") == [crop_id] and
            square.get("image", {}).get("id") == square_id and square.get("operator") == "GMSImageProcessing::Square",
            "Historical prefix square output identity invalid")
    producers = {request_id for request_id, request in ledger.items() if request["op"] in ("CROP", "UNARY")}
    produced_requests = {crop["native_receipt"]["id"], square["native_receipt"]["id"]}
    require(producers == produced_requests, "Historical prefix has unresolved or unaccounted side-effect request")
    context["operation_request_ids"].update(ledger)
    context["outputs"].update({crop_id: {"label": "prior_failed_crop", "request_id": crop["native_receipt"]["id"]},
                               square_id: {"label": "prior_failed_square", "request_id": square["native_receipt"]["id"]}})
    return {"report": os.path.realpath(path), "status": "FAIL_PRESERVED", "report_sha256": sha(evidence.raw(path)),
            "ledger_sha256": sha(evidence.raw(ledger_path)), "produced_ids": [crop_id, square_id],
            "numerical_qualification": "NOT_INFERRED_FROM_FAILED_ATTEMPT"}


def collect(report, truth_path, report_path, ledger_path, independent_path, stop_request_path, stop_receipt_path, prior_reports=()):
    import numpy as np
    evidence = Evidence()
    context = bind_current(evidence, truth_path, report_path, ledger_path, independent_path)
    context["truth_path"] = truth_path
    require(type(prior_reports) in (list, tuple) and len(prior_reports) <= 4 and
            len(set(prior_reports)) == len(prior_reports) and all(type(path) is str and os.path.isabs(path) for path in prior_reports),
            "Prior failed-report paths must be an explicit bounded unique absolute list")
    prior = [bind_failed_prefix(evidence, path, context) for path in prior_reports]
    stop_request, stop_receipt = evidence.json(stop_request_path), evidence.json(stop_receipt_path)
    saved_operation(stop_request, stop_receipt, "STOP", [], context)
    require(type(stop_receipt.get("timings_us")) is dict and set(stop_receipt["timings_us"]) == {"queue", "execute"},
            "Original STOP timings invalid")
    import DigitalMicrograph as DM
    released = []
    for image_id in sorted(context["outputs"]):
        image = None
        try:
            image = DM.FindImageByID(image_id)
            require(image is None or not image.IsValid(), "Explicitly recorded unshown native result remains valid after STOP")
            released.append(image_id)
        finally:
            image = None
    sources = []
    for label, (entry, values) in context["sources"].items():
        actual = observe(DM, np, entry["id"], values.shape, values.dtype)
        check_source(entry, values, actual)
        sources.append({"label": label, "image_id": entry["id"], "pixel_sha256": entry["pixel_sha256"],
                        "source_file_sha256": entry["source_file_sha256"], "name_spatial_intensity_unchanged": True})
    documents = DM.CountImageDocumentsOfAllWorkspaces()
    require(integer(documents, context["truth"]["initial_document_count"], context["truth"]["initial_document_count"]),
            "Post-STOP fixture document count changed")
    evidence.unchanged()
    report.update(status="PASS_UNSHOWN_HANDOFF_STOPPED", host_pid=os.getpid(), session=context["session"],
                  qualification_mode=context["qualification_mode"], stop_request_verified=True,
                  stop_request_sha256=sha(evidence.raw(stop_request_path)), stop_receipt_sha256=sha(evidence.raw(stop_receipt_path)),
                  original_handoff_sha256=sha(evidence.raw(independent_path)), source_protection="PASS",
                  sources=sources, document_count=documents, released_output_ids=released,
                  explicit_output_requests=[dict(value, image_id=key) for key, value in sorted(context["outputs"].items())],
                  prior_failed_attempts=prior, capture_persistence="PASS_ORIGINAL_THREE_FILE_HASHES",
                  captures=[{"label": label, "files_sha256": value["hashes"]} for label, value in context["packages"].items()],
                  raw_views_and_wrappers_released=True, ordinary_python_success=True,
                  evidence_files_sha256={path: sha(raw) for path, raw in evidence.original.items()})


def main():
    directory = os.environ["DM_NATIVE_EVIDENCE_DIR"]
    def filename(key, default):
        return os.environ.get("DM_NATIVE_HANDOFF_"+key, os.path.join(directory, default))
    target = filename("STOPPED_OUTPUT", "independent-handoff-stopped.json")
    with open(target, "x", encoding="utf-8") as output:
        report = {"schema": 1, "status": "FAIL", "kind": "synthetic-only", "scope": "explicit unshown result release after original STOP",
                  "ui_visibility": "NOT_TESTED", "host_exit": "NOT_TESTED", "plugin_removal": "NOT_TESTED",
                  "dm_file_save": False, "model_viewing": "NOT_TESTED", "ipc_sent_by_this_script": False}
        try:
            prior = strict_json(os.environ.get("DM_NATIVE_HANDOFF_PRIOR_REPORTS", "[]").encode("utf-8"))
            collect(report, filename("TRUTH", "operations-truth.json"), filename("REPORT", "mcp-handoff-report.json"),
                    filename("LEDGER", "mcp-handoff-requests.jsonl"), filename("INDEPENDENT", "independent-handoff-01.json"),
                    filename("STOP_REQUEST", "stop-request.json"), filename("STOP_RECEIPT", "stop-receipt.json"), prior)
        except BaseException as error:
            report.update(status="FAIL", error_type=type(error).__name__, error=str(error))
        json.dump(report, output, ensure_ascii=True, allow_nan=False, indent=2)
        output.write("\n"); output.flush(); os.fsync(output.fileno())
    print(report["status"]+": explicit recorded IDs only; DM remains open")
    return 0 if report["status"] == "PASS_UNSHOWN_HANDOFF_STOPPED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
