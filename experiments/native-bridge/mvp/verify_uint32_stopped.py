# -*- coding: utf-8 -*-
"""Read-only same-PID uint32 STOP oracle for its explicitly recorded crop."""
import json
import os

from create_summary_fixture import require
from uint32_acceptance import Evidence, capture, sha, integer
from verify_uint32 import load_context, paths
from verify_handoff import observe, check_source
from verify_operations_lifecycle import saved_operation


def collect(report,truth_path,report_path,ledger_path,recovery_path,independent_path,stop_request_path,stop_receipt_path):
    import numpy as np
    evidence=Evidence();context=load_context(evidence,truth_path,report_path,ledger_path,recovery_path,os.getpid())
    previous=evidence.json(independent_path)
    require(previous.get("schema")==1 and previous.get("kind")=="synthetic-only" and previous.get("status")=="PASS_BOUNDED_UINT32" and
            integer(previous.get("host_pid"),os.getpid(),os.getpid()) and previous.get("session")==context["session"] and
            previous.get("qualification_mode")==context["report"]["qualification_mode"] and previous.get("crop_id")==context["crop_id"] and
            previous.get("truth_sha256")==sha(evidence.raw(truth_path)) and previous.get("mcp_report_sha256")==sha(evidence.raw(report_path)) and
            previous.get("ledger_sha256")==sha(evidence.raw(ledger_path)) and previous.get("recovery_ledger_sha256")==sha(evidence.raw(recovery_path)) and
            previous.get("source_protection")==previous.get("independent_memory")=="PASS" and previous.get("numeric_handoff")=="PASS_BITWISE_UINT32" and
            previous.get("raw_views_and_wrappers_released") is True and previous.get("immutable_query_repeat_conflict")=="PASS",
            "uint32 original independent handoff proof/hash/host mismatch")
    hashes=previous.get("evidence_files_sha256")
    require(type(hashes) is dict and len(hashes)>10,"uint32 original evidence hash map missing")
    for path,expected in hashes.items():require(type(path) is str and os.path.isabs(path) and sha(evidence.raw(path))==expected,"uint32 original capture/source evidence file changed")
    packages=[]
    for entry in context["report"]["captures"]:
        package=capture(evidence,entry,context["outputs"]["read_source" if entry["label"]=="source" else "read_crop"])
        packages.append({"label":entry["label"],"files_sha256":package["hashes"]})
    # A fresh host is part of this bounded fixture contract. Unknown earlier
    # retained results cannot be silently omitted from a cleanup assertion.
    require(integer(context["outputs"]["status"].get("retained_result_count"),0,0),"uint32 STOP proof has unaccounted preexisting native outputs")
    stop_request=evidence.json(stop_request_path);stop_receipt=evidence.json(stop_receipt_path)
    anchor={"session":context["session"],"worker_tid":context["threads"][1],"host_thread":context["threads"][0],"operation_request_ids":set(context["ledger"])}
    saved_operation(stop_request,stop_receipt,"STOP",[],anchor)
    require(set(stop_receipt.get("timings_us",{}))=={"queue","execute"},"uint32 STOP timing fields mismatch")
    import DigitalMicrograph as DM
    image=None
    try:
        image=DM.FindImageByID(context["crop_id"])
        require(image is None or not image.IsValid(),"Explicit uint32 crop still valid after original STOP")
    finally:image=None
    sources=[]
    for label,(entry,values) in context["sources"].items():
        check_source(entry,values,observe(DM,np,entry["id"],[4,4],np.uint32))
        sources.append({"label":label,"image_id":entry["id"],"pixel_sha256":entry["pixel_sha256"],"calibration_and_name_unchanged":True})
    documents=DM.CountImageDocumentsOfAllWorkspaces();expected_docs=context["truth"]["initial_document_count"]
    require(integer(documents,expected_docs,expected_docs),"uint32 post-STOP document count changed")
    evidence.unchanged()
    report.update(status="PASS_UINT32_STOPPED",host_pid=os.getpid(),session=context["session"],qualification_mode=context["report"]["qualification_mode"],
        stop_request_verified=True,stop_request_sha256=sha(evidence.raw(stop_request_path)),stop_receipt_sha256=sha(evidence.raw(stop_receipt_path)),
        independent_sha256=sha(evidence.raw(independent_path)),released_output_ids=[context["crop_id"]],sources=sources,source_protection="PASS",
        document_count=documents,capture_persistence="PASS_ORIGINAL_THREE_FILE_HASHES",captures=packages,raw_views_and_wrappers_released=True,
        evidence_files_sha256={path:sha(raw) for path,raw in evidence.original.items()})


def main():
    filename=paths()
    with open(filename("STOPPED_OUTPUT","uint32-stopped.json"),"x",encoding="utf-8") as output:
        report={"schema":1,"status":"FAIL","kind":"synthetic-only","scope":"explicit unshown uint32 crop release and stored bytes persistence",
                "ipc_sent_by_this_script":False,"ui_visibility":"NOT_TESTED","host_exit":"NOT_TESTED","plugin_removal":"NOT_TESTED"}
        try:collect(report,filename("TRUTH","uint32-truth.json"),filename("REPORT","uint32-mcp-report.json"),filename("LEDGER","uint32-requests.jsonl"),
            filename("RECOVERY_LEDGER","uint32-recovery-requests.jsonl"),filename("INDEPENDENT","uint32-independent.json"),filename("STOP_REQUEST","stop-request.json"),filename("STOP_RECEIPT","stop-receipt.json"))
        except BaseException as error:report.update(status="FAIL",error_type=type(error).__name__,error=str(error))
        json.dump(report,output,indent=2,ensure_ascii=True,allow_nan=False);output.write("\n");output.flush();os.fsync(output.fileno())
    print(report["status"]+": explicit recorded uint32 output only; DM remains open")
    return 0 if report["status"]=="PASS_UINT32_STOPPED" else 1


if __name__=="__main__":raise SystemExit(main())
