# -*- coding: utf-8 -*-
"""One-shot read-only math-result ownership check inside the SAME idle DM.

Run three separate phases around an externally requested SHOW, native STOP and
manual closing of that one result document. This script sends no IPC, creates
no image/document and never closes anything. No legacy/UNVERIFIED fallback.
"""
import hashlib
import io
import json
import os
import re

from create_summary_fixture import require
from verify_operations import (bind_evidence, detached_observation, integer,
                               read_json_hashed, strict_json, verify_source)


def env_path(directory, key, name):
    return os.environ.get("DM_NATIVE_LIFECYCLE_" + key, os.path.join(directory, name))


def saved_operation(request, receipt, operation, args, context):
    fields = {"protocol", "session", "id", "op", "args", "host_pid", "wire"}
    require(type(request) is dict and set(request) == fields and request.get("protocol") == "NB2" and
            request.get("session") == context["session"] and integer(request.get("host_pid"), 1) and
            request["host_pid"] == os.getpid() and request.get("op") == operation and
            type(request.get("args")) is list and all(integer(value) for value in request["args"]) and
            request["args"] == args and type(request.get("id")) is str and
            re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request["id"]) is not None and
            request["id"] not in context["operation_request_ids"],
            "Invalid original saved " + operation + " request")
    wire = "NB2 %s %s %s%s\n" % (context["session"], request["id"], operation,
                                  " " + " ".join(str(value) for value in args) if args else "")
    require(request["wire"] == wire, "Saved " + operation + " wire mismatch")
    require(type(receipt) is dict and receipt.get("protocol") == "NB2" and
            receipt.get("session") == context["session"] and receipt.get("id") == request["id"] and
            receipt.get("state") == "completed" and integer(receipt.get("host_pid"), 1) and
            receipt["host_pid"] == os.getpid() and integer(receipt.get("worker_tid"), 1) and
            receipt["worker_tid"] == context["worker_tid"] and integer(receipt.get("exec_tid")) and
            receipt["exec_tid"] == (0 if operation == "STOP" else context["host_thread"]) and
            receipt.get("original_operation") == operation and
            type(receipt.get("normalized_args")) is list and all(integer(value) for value in receipt["normalized_args"]) and
            receipt["normalized_args"] == args and receipt.get("result_type") == ("ipc_stop" if operation == "STOP" else "image_delivery") and
            integer(receipt.get("result_version"), 1, 1) and "error" not in receipt and "code" not in receipt,
            "Saved " + operation + " receipt identity mismatch")
    if operation == "STOP":
        require(type(receipt.get("result")) is dict and set(receipt["result"]) == {"ipc_stopped"} and
                receipt["result"]["ipc_stopped"] is True, "STOP was not acknowledged")
    else:
        result = receipt.get("result", {})
        require(type(result) is dict and result.get("backend") == "digitalmicrograph-native" and
                integer(result.get("image_id"), args[0], args[0]) and
                result.get("delivery") == "visible_dm_document" and result.get("document_visible") is True and
                result.get("operator") == "ImageGetOrCreateImageDocument + ImageDocumentShow" and
                result.get("source_write_requested") is False and result.get("snapshot_atomic") is False and
                result.get("file_saved") is False and result.get("model_visual_verification") is False,
                "SHOW result delivery mismatch")
    timings = receipt.get("timings_us")
    require(type(timings) is dict and all(integer(timings.get(key), 0, (1 << 53)-1) for key in ("queue", "execute")),
            "Saved " + operation + " timing mismatch")


def check_previous(previous, phase, context, previous_hash=None):
    require(type(previous) is dict and previous.get("status") == "PASS_NATIVE_RESULT_LIFECYCLE_PHASE" and
            previous.get("phase") == phase and integer(previous.get("host_pid"), 1) and previous["host_pid"] == os.getpid() and
            previous.get("session") == context["session"] and previous.get("image_id") == context["shown_id"] and
            previous.get("sources_unchanged") is True and previous.get("raw_views_and_wrappers_released") is True and
            previous.get("ordinary_python_success") is True, "Previous lifecycle phase identity/flags mismatch")
    for key in ("truth_sha256", "operations_report_sha256", "operations_observation_sha256", "requests_sha256",
                "show_request_sha256", "show_receipt_sha256"):
        require(previous.get(key) == context[key], "Previous lifecycle phase bound to different evidence")
    require(previous.get("matching_documents") == 1 and
            previous.get("total_documents") == context["truth"]["initial_document_count"]+1 and
            previous.get("shown_pixels_equal") is True and previous.get("shown_calibration_equal") is True,
            "Previous lifecycle document/pixel evidence missing")
    require(previous.get("source_document_matches") == {str(entry["id"]): 1 for entry in context["truth"]["images"]},
            "Previous lifecycle source document evidence missing")
    if phase == "before_stop":
        require(previous.get("live_output_ids") == sorted(context["output_ids"]) and previous.get("released_output_ids") == [] and
                previous.get("stop_request_sha256") is None and previous.get("stop_receipt_sha256") is None,
                "Previous before-STOP pool evidence missing")
    else:
        require(previous.get("live_output_ids") == [context["shown_id"]] and
                previous.get("released_output_ids") == sorted(context["output_ids"] - {context["shown_id"]}) and
                previous.get("stop_request_verified") is True and previous.get("stop_request_sha256") == context["stop_request_sha256"] and
                previous.get("stop_receipt_sha256") == context["stop_receipt_sha256"] and
                previous.get("previous_phase_sha256") == previous_hash,
                "Previous after-STOP pool evidence missing")


def load_context(directory, phase):
    truth, truth_hash = read_json_hashed(os.path.join(directory, "operations-truth.json"))
    operations, operations_hash = read_json_hashed(os.environ.get("DM_NATIVE_OPERATIONS_REPORT",
                                                  os.path.join(directory, "operations-report.json")))
    observation, observation_hash = read_json_hashed(os.environ.get("DM_NATIVE_OPERATIONS_OBSERVATION",
                                                     os.path.join(directory, "operations-observation-01.json")))
    with open(os.environ.get("DM_NATIVE_OPERATIONS_LEDGER", os.path.join(directory, "operations-requests.jsonl")), "rb") as source:
        ledger_raw = source.read()
    records = [strict_json(line) for line in ledger_raw.splitlines() if line.strip()]
    bind_evidence(truth, operations, records, os.getpid())
    require(observation.get("status") == "RECORDED_PARTIAL_QUALIFICATION" and
            integer(observation.get("host_pid"), 1) and observation["host_pid"] == os.getpid() and
            observation.get("session") == truth["session"] and observation.get("truth_sha256") == truth_hash and
            observation.get("operations_report_sha256") == operations_hash and
            observation.get("requests_sha256") == hashlib.sha256(ledger_raw).hexdigest() and
            observation.get("source_protection") == "PASS" and observation.get("independent_memory") == "PASS" and
            observation.get("raw_views_and_wrappers_released") is True and integer(observation.get("output_count"), 32, 32),
            "Original same-host observation/hash/flags mismatch")
    originals = {entry["image_id"]: entry for entry in observation.get("outputs", [])}
    require(len(originals) == len(observation.get("outputs", [])) == 32 and
            set(originals) == {entry["image_id"] for entry in operations["outputs"]}, "Original output pool mismatch")
    status = next(entry["receipt"] for entry in operations["checks"] if entry["label"] == "STATUS")
    context = {"truth": truth, "operations": operations, "observation": observation, "originals": originals,
               "session": truth["session"], "truth_sha256": truth_hash, "operations_report_sha256": operations_hash,
               "operations_observation_sha256": observation_hash, "requests_sha256": hashlib.sha256(ledger_raw).hexdigest(),
               "host_thread": status["exec_tid"], "worker_tid": status["worker_tid"],
               "operation_request_ids": {entry["id"] for entry in records}, "output_ids": set(originals),
               "stop_request_sha256": None, "stop_receipt_sha256": None, "previous_phase_sha256": None}
    show_request, context["show_request_sha256"] = read_json_hashed(env_path(directory, "SHOW_REQUEST", "operations-show-request.json"))
    show_receipt, context["show_receipt_sha256"] = read_json_hashed(env_path(directory, "SHOW_RECEIPT", "operations-show-receipt.json"))
    args = show_request.get("args")
    require(type(args) is list and len(args) == 1 and integer(args[0], 1) and args[0] in originals and
            originals[args[0]].get("kind") in ("UNARY", "BINARY") and originals[args[0]].get("status") == "PASS",
            "SHOW target is not an independently qualified arithmetic result")
    context["shown_id"] = args[0]
    saved_operation(show_request, show_receipt, "SHOW", args, context)
    context["operation_request_ids"].add(show_request["id"])
    stop_request_path = env_path(directory, "STOP_REQUEST", "stop-request.json")
    stop_receipt_path = env_path(directory, "STOP_RECEIPT", "stop-receipt.json")
    if phase == "before_stop":
        require(not os.path.lexists(stop_request_path) and not os.path.lexists(stop_receipt_path),
                "before_stop phase has existing or ambiguous STOP evidence")
    else:
        stop_request, context["stop_request_sha256"] = read_json_hashed(stop_request_path)
        stop_receipt, context["stop_receipt_sha256"] = read_json_hashed(stop_receipt_path)
        saved_operation(stop_request, stop_receipt, "STOP", [], context)
        before, before_hash = read_json_hashed(env_path(directory, "BEFORE", "operations-lifecycle-before_stop.json"))
        check_previous(before, "before_stop", context)
        context["previous_phase_sha256"] = before_hash
        if phase == "after_close":
            after, after_hash = read_json_hashed(env_path(directory, "AFTER_STOP", "operations-lifecycle-after_stop.json"))
            check_previous(after, "after_stop", context, before_hash)
            context["previous_phase_sha256"] = after_hash
    return context


def output_present(DM, image_id):
    image = None
    try:
        image = DM.FindImageByID(image_id)
        if image is None or not image.IsValid():
            return False
        require(integer(image.GetID(), image_id, image_id), "Registry returned different image identity")
        return True
    finally:
        image = None


def matching_documents(DM, image_id, source_ids):
    document = candidate = None
    count = DM.CountImageDocumentsOfAllWorkspaces()
    require(integer(count, 0, 128), "Invalid bounded document count")
    matches = 0
    source_matches = {str(source_id): 0 for source_id in source_ids}
    try:
        for position in range(count):
            document = DM.GetImageDocumentOfAllWorkspaces(position)
            require(document is not None, "Document enumeration returned null")
            images = document.CountImages()
            require(integer(images, 0, 128), "Invalid bounded document image count")
            contains = False
            contained_sources = set()
            for index in range(images):
                candidate = document.GetImage(index)
                require(candidate is not None and candidate.IsValid(), "Invalid enumerated document image")
                actual_id = candidate.GetID()
                require(integer(actual_id, 1), "Invalid document image identity")
                contains = contains or actual_id == image_id
                if actual_id in source_ids:
                    contained_sources.add(actual_id)
                candidate = None
            if contains:
                matches += 1
            for source_id in contained_sources:
                source_matches[str(source_id)] += 1
            document = None
        return count, matches, source_matches
    finally:
        candidate = document = None


def collect(report, context, phase):
    import numpy as np
    import DigitalMicrograph as DM

    truth, originals, shown_id = context["truth"], context["originals"], context["shown_id"]
    for entry in truth["images"]:
        verify_source(np, entry, detached_observation(DM, np, entry["id"]))
    references = {}
    for image_id, entry in originals.items():
        with open(entry["snapshot"], "rb") as source:
            raw = source.read()
        values = np.load(io.BytesIO(raw), allow_pickle=False)
        require(hashlib.sha256(raw).hexdigest() == entry.get("snapshot_file_sha256") and
                str(values.dtype) == entry.get("dtype") and list(values.shape) == entry.get("shape") and
                hashlib.sha256(values.tobytes(order="C")).hexdigest() == entry.get("pixel_sha256"),
                "Original output snapshot/hash changed")
        references[image_id] = values
    live, released = [], []
    for image_id in sorted(context["output_ids"]):
        present = output_present(DM, image_id)
        expected_live = phase == "before_stop" or (phase == "after_stop" and image_id == shown_id)
        require(present is expected_live, "Unexpected live/released result ownership")
        if not present:
            released.append(image_id)
            continue
        live.append(image_id)
        comparisons = [entry["id"] for entry in truth["images"]]
        if phase == "before_stop":
            comparisons += [prior for prior in live if prior != image_id]
        current = detached_observation(DM, np, image_id, comparisons)
        original = originals[image_id]
        require(current["values"].dtype == references[image_id].dtype and
                current["values"].shape == references[image_id].shape and
                hashlib.sha256(current["values"].tobytes(order="C")).hexdigest() == original["pixel_sha256"],
                "Current output pixels/dtype/shape changed")
        require(current["calibration"] == original["calibration"] and
                current["intensity_calibration"] == original["intensity_calibration"], "Current output calibration changed")
    source_ids = {entry["id"] for entry in truth["images"]}
    total, matches, source_matches = matching_documents(DM, shown_id, source_ids)
    require(matches == (0 if phase == "after_close" else 1) and
            total == truth["initial_document_count"]+(0 if phase == "after_close" else 1),
            "Shown document identity/count mismatch")
    require(all(count == 1 for count in source_matches.values()), "Source document membership changed")
    # Re-read after document iteration; every helper releases its views/wrappers.
    for entry in truth["images"]:
        verify_source(np, entry, detached_observation(DM, np, entry["id"]))
    report.update(sources_unchanged=True, live_output_ids=live, released_output_ids=released,
                  matching_documents=matches, total_documents=total, ordinary_python_success=True,
                  source_document_matches=source_matches,
                  shown_pixels_equal=None if phase == "after_close" else True,
                  shown_calibration_equal=None if phase == "after_close" else True,
                  independent_memory="NOT_APPLICABLE_OUTPUT_RELEASED" if phase == "after_close" else "PASS",
                  raw_views_and_wrappers_released=True)


def main():
    directory = os.environ["DM_NATIVE_EVIDENCE_DIR"]
    phase = os.environ["DM_NATIVE_LIFECYCLE_PHASE"]
    require(phase in ("before_stop", "after_stop", "after_close"), "Unsupported explicit lifecycle phase")
    filename = os.environ.get("DM_NATIVE_LIFECYCLE_OUTPUT",
                              os.path.join(directory, "operations-lifecycle-"+phase+".json"))
    with open(filename, "x", encoding="utf-8") as output:
        report = {"schema": 1, "status": "FAIL", "phase": phase, "host_pid": os.getpid(),
                  "ui_visibility": "NOT_TESTED_BY_THIS_SCRIPT", "file_saved": False}
        try:
            context = load_context(directory, phase)
            for key in ("session", "truth_sha256", "operations_report_sha256", "operations_observation_sha256",
                        "requests_sha256", "show_request_sha256", "show_receipt_sha256",
                        "stop_request_sha256", "stop_receipt_sha256", "previous_phase_sha256"):
                report[key] = context[key]
            report.update(image_id=context["shown_id"], stop_request_verified=phase != "before_stop")
            collect(report, context, phase)
            report["status"] = "PASS_NATIVE_RESULT_LIFECYCLE_PHASE"
        except BaseException as error:
            report.update(error_type=type(error).__name__, error=str(error))
        json.dump(report, output, indent=2, ensure_ascii=True, allow_nan=False)
        output.write("\n")
    print("Native result lifecycle " + phase + ": " + report["status"])
    return 0 if report["status"] == "PASS_NATIVE_RESULT_LIFECYCLE_PHASE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
