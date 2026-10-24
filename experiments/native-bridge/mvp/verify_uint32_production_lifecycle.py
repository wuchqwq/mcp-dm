# -*- coding: utf-8 -*-
"""Read-only two-document production uint32 ownership phases inside SAME DM.

Shows/STOP/document closes are external explicit actions. No IPC or UI action
occurs here. The original accepted crop and uint32 filter IDs are the only
allowed visible results; no newest-window or registry discovery is performed.
"""
import json
import os

from create_summary_fixture import require
from observe_uint32_operations import bind_metadata,source_unchanged
from uint32_operations_acceptance import SHOW_TARGETS,Evidence,integer,sha,bit_equal,bounded_npy,record
from verify_uint32_operations import load_context as production_context,detached
from verify_uint32_operations_lifecycle import strict_saved
from verify_operations_lifecycle import matching_documents,output_present


def path(directory,key,default):return os.environ.get("DM_NATIVE_U32_PROD_"+key,os.path.join(directory,default))


def previous(value,phase,context):
    require(type(value) is dict and value.get("status")=="PASS_UINT32_OPERATIONS_LIFECYCLE_PHASE" and value.get("phase")==phase and
            integer(value.get("host_pid"),os.getpid(),os.getpid()) and value.get("session")==context["session"] and
            value.get("shown_ids")==sorted(context["shown_ids"]) and value.get("sources_unchanged") is True and
            value.get("raw_views_and_wrappers_released") is True and value.get("ordinary_python_success") is True and
            value.get("same_id_repeat_and_fresh_query") is True and value.get("new_id_show_reuses_document") is True,
            "Previous production lifecycle identity/flags mismatch")
    for key,hash_value in context["bound_hashes"].items():require(value.get(key)==hash_value,"Previous production lifecycle evidence hash differs")
    ids=set(context["originals"]);shown=set(context["shown_ids"])
    require(value.get("live_output_ids")==sorted(ids if phase=="before_stop" else shown) and
            value.get("released_output_ids")==sorted(set() if phase=="before_stop" else ids-shown) and
            value.get("matching_documents")=={str(image_id):1 for image_id in shown} and
            value.get("total_documents")==context["truth"]["initial_document_count"]+2 and
            value.get("source_document_matches")=={str(entry[0]["id"]):1 for entry in context["sources"].values()} and
            value.get("shown_pixels_equal") is True and value.get("shown_calibration_equal") is True,"Previous production output/document/pixel facts missing")
    if phase=="before_stop":
        require(value.get("stop_request_verified") is False and value.get("stop_request_sha256") is None and value.get("stop_receipt_sha256") is None,
                "Previous before_stop has STOP evidence")
    else:
        require(value.get("stop_request_verified") is True and value.get("stop_request_sha256")==context["stop_request_sha256"] and
                value.get("stop_receipt_sha256")==context["stop_receipt_sha256"] and value.get("previous_phase_sha256")==context["before_hash"],
                "Previous production STOP identity/hash binding differs")


def load_context(directory,phase):
    require(phase in ("before_stop","after_stop","after_close"),"Explicit production lifecycle phase required")
    evidence=Evidence();names={"truth_sha256":path(directory,"TRUTH","uint32-production-truth.json"),
        "mcp_report_sha256":path(directory,"REPORT","uint32-operations-mcp-report.json"),"ledger_sha256":path(directory,"LEDGER","uint32-operations-requests.jsonl"),
        "recovery_ledger_sha256":path(directory,"RECOVERY_LEDGER","uint32-operations-recovery-requests.jsonl")}
    context=production_context(evidence,names["truth_sha256"],names["mcp_report_sha256"],names["ledger_sha256"],names["recovery_ledger_sha256"],os.getpid())
    observation_path=path(directory,"OBSERVATION","uint32-production-independent.json");observation=evidence.json(observation_path)
    require(observation.get("status")=="PASS_BOUNDED_UINT32_OPERATIONS" and integer(observation.get("host_pid"),os.getpid(),os.getpid()) and
            observation.get("session")==context["session"] and observation.get("qualification_mode")=="production" and
            observation.get("source_protection")=="PASS" and observation.get("independent_memory")=="PASS_RAW_VIEWS" and
            observation.get("raw_views_and_wrappers_released") is True and observation.get("output_count")==32 and
            observation.get("typed_handoff")=="PASS_BITWISE_ACTUAL_DTYPE" and observation.get("immutable_fresh_query")=="PASS",
            "Original independent production oracle actual PID/session/qualification flags mismatch")
    bound={key:sha(evidence.raw(filename)) for key,filename in names.items()}
    require(all(observation.get(key)==value for key,value in bound.items()),"Original independent production oracle evidence hashes mismatch")
    original_files=observation.get("evidence_files_sha256")
    require(type(original_files) is dict and bool(original_files) and all(type(filename) is str and type(value) is str and len(value)==64 for filename,value in original_files.items()),
            "Original independently bound capture/evidence file hashes missing")
    for filename,value in original_files.items():require(sha(evidence.raw(filename,2*1024*1024))==value,"Production original capture/evidence bytes changed")
    for capture in context["report"]["captures"]:
        filename=os.path.realpath(os.path.join(capture["receipt"]["capture_dir"],"input.npy"))
        require(filename in original_files,"Original production capture NPY was not bound by independent oracle")
    entries=observation.get("outputs");require(type(entries) is list and len(entries)==32,"Exactly 32 independent production outputs required")
    originals={};references={}
    for entry in entries:
        image_id=entry.get("image_id");original=context["outputs"].get(image_id)
        require(integer(image_id,1) and image_id not in originals and original is not None and entry.get("label")==original["plan"]["label"] and
                entry.get("request_id")==original["entry"]["request"]["id"] and entry.get("operation")==original["entry"]["request"]["op"] and
                entry.get("args")==original["entry"]["request"]["args"] and entry.get("status") in ("PASS_BOUNDED_FIXED_SYNTHETIC","PASS_PREDECLARED_EMPIRICAL_FIXTURE"),
                "Production lifecycle output original identity/math qualification missing")
        raw=evidence.raw(entry["snapshot"],1024*1024);dtype={"float32":"<f4","uint32":"<u4","complex64":"<c8"}.get(entry.get("dtype"))
        require(dtype is not None,"Production detached dtype unsupported")
        values=bounded_npy(raw,entry["shape"],dtype)
        require(sha(raw)==entry.get("snapshot_file_sha256") and sha(values.tobytes(order="C"))==entry.get("pixel_sha256"),"Detached production NPY/pixel hashes changed")
        bind_metadata(original["output"]["image"],image_id,dict(entry,values=values));originals[image_id]=entry;references[image_id]=values
    bound["observation_sha256"]=sha(evidence.raw(observation_path));context.update(originals=originals,references=references,evidence=evidence,
        host_thread=context["threads"][0],worker_tid=context["threads"][1],operation_request_ids=set(context["ledger"]),
        stop_request_sha256=None,stop_receipt_sha256=None,previous_phase_sha256=None)
    shown=[context["ids"][label] for label in SHOW_TARGETS]
    require(observation.get("show_target_ids")==shown,"Production SHOW target IDs differ from independent mathematical oracle")
    show_path=path(directory,"SHOWS","uint32-production-shows.json");show_manifest=evidence.json(show_path)
    require(show_manifest.get("schema")==1 and show_manifest.get("host_pid")==os.getpid() and show_manifest.get("session")==context["session"] and
            type(show_manifest.get("targets")) is list and [entry.get("label") for entry in show_manifest["targets"]]==list(SHOW_TARGETS),
            "Explicit original production SHOW file manifest identity/targets mismatch")
    for target,image_id in zip(show_manifest["targets"],shown):
        require(set(target)=={"label","request","receipt","repeat","query","reuse_request","reuse_receipt"},"Explicit SHOW original evidence paths required")
        request=evidence.json(target["request"]);receipt=evidence.json(target["receipt"])
        strict_saved(request,receipt,"SHOW",[image_id],context)
        require(not any(key.startswith("candidate_") or key.startswith("prepared_") for key in receipt["result"]) and
                receipt["result"].get("qualification")!="NOT_QUALIFIED","Production SHOW still has candidate-only payload")
        bind_metadata(receipt["result"].get("image"),image_id,dict(originals[image_id],values=references[image_id]))
        require(evidence.json(target["repeat"])=={"request":request,"receipt":receipt},"Production same-ID SHOW repeat differs")
        require(evidence.json(target["query"])=={"request":record(context["session"],os.getpid(),"QUERY",[],request["id"]),"receipt":receipt},
                "Production fresh QUERY differs from original SHOW")
        context["operation_request_ids"].add(request["id"])
        reuse=evidence.json(target["reuse_request"]);reuse_receipt=evidence.json(target["reuse_receipt"])
        strict_saved(reuse,reuse_receipt,"SHOW",[image_id],context)
        require(reuse_receipt["result"]==receipt["result"],"Production new-ID SHOW reuse result differs")
        context["operation_request_ids"].add(reuse["id"])
    bound["shows_manifest_sha256"]=sha(evidence.raw(show_path))
    # Bind the original SHOW bytes too; a manifest path alone is insufficient.
    bound["show_files_sha256"]={filename:sha(evidence.raw(filename)) for entry in show_manifest["targets"] for key,filename in entry.items() if key!="label"}
    context.update(bound_hashes=bound,shown_ids=shown)
    stop_path=path(directory,"STOP_REQUEST","stop-request.json");stop_receipt_path=path(directory,"STOP_RECEIPT","stop-receipt.json")
    if phase=="before_stop":require(not os.path.lexists(stop_path) and not os.path.lexists(stop_receipt_path),"Production before_stop has existing STOP evidence")
    else:
        strict_saved(evidence.json(stop_path),evidence.json(stop_receipt_path),"STOP",[],context)
        context["stop_request_sha256"]=sha(evidence.raw(stop_path));context["stop_receipt_sha256"]=sha(evidence.raw(stop_receipt_path))
        before_path=path(directory,"BEFORE","uint32-production-before_stop.json");before=evidence.json(before_path)
        previous(before,"before_stop",context);context["before_hash"]=sha(evidence.raw(before_path));context["previous_phase_sha256"]=context["before_hash"]
        if phase=="after_close":
            after_path=path(directory,"AFTER_STOP","uint32-production-after_stop.json");after=evidence.json(after_path)
            previous(after,"after_stop",context);context["previous_phase_sha256"]=sha(evidence.raw(after_path))
    return context


def collect(report,context,phase):
    import numpy as np
    import DigitalMicrograph as DM
    source_ids={entry[0]["id"] for entry in context["sources"].values()}
    for entry,saved in context["sources"].values():source_unchanged(entry,saved,detached(DM,np,entry["id"],entry["shape"],11))
    live=[];released=[]
    for image_id,entry in sorted(context["originals"].items()):
        valid=output_present(DM,image_id);expected=phase=="before_stop" or (phase=="after_stop" and image_id in context["shown_ids"])
        require(valid is expected,"Explicit production image release/ownership differs")
        if not valid:released.append(image_id);continue
        actual=detached(DM,np,image_id,entry["shape"],entry["python_data_type_code"],list(source_ids)+live)
        bit_equal(actual["values"],context["references"][image_id],"Production lifecycle result pixels/dtype/axes changed")
        require(actual["name"]==entry["name"] and actual["calibration"]==entry["calibration"] and actual["intensity_calibration"]==entry["intensity_calibration"],
                "Production lifecycle result name/spatial/intensity calibration changed")
        live.append(image_id)
    matches={};expected_docs=context["truth"]["initial_document_count"]+(0 if phase=="after_close" else 2)
    for image_id in context["shown_ids"]:
        total,matched,source_matches=matching_documents(DM,image_id,source_ids)
        require(total==expected_docs and matched==(0 if phase=="after_close" else 1) and all(count==1 for count in source_matches.values()),
                "Production two SHOW exact document identities/count differ")
        matches[str(image_id)]=matched
    for entry,saved in context["sources"].values():source_unchanged(entry,saved,detached(DM,np,entry["id"],entry["shape"],11))
    context["evidence"].unchanged()
    report.update(context["bound_hashes"])
    report.update(status="PASS_UINT32_OPERATIONS_LIFECYCLE_PHASE",host_pid=os.getpid(),session=context["session"],phase=phase,shown_ids=sorted(context["shown_ids"]),
        live_output_ids=live,released_output_ids=released,sources_unchanged=True,raw_views_and_wrappers_released=True,ordinary_python_success=True,
        matching_documents=matches,total_documents=expected_docs,source_document_matches=source_matches,
        shown_pixels_equal=None if phase=="after_close" else True,shown_calibration_equal=None if phase=="after_close" else True,
        same_id_repeat_and_fresh_query=True,new_id_show_reuses_document=True,stop_request_verified=phase!="before_stop",
        stop_request_sha256=context["stop_request_sha256"],stop_receipt_sha256=context["stop_receipt_sha256"],previous_phase_sha256=context["previous_phase_sha256"])


def main():
    directory=os.environ["DM_NATIVE_EVIDENCE_DIR"];phase=os.environ["DM_NATIVE_U32_PROD_PHASE"]
    with open(path(directory,"LIFECYCLE_OUTPUT","uint32-production-"+phase+".json"),"x",encoding="utf-8") as output:
        report={"schema":1,"kind":"synthetic-only","status":"FAIL","phase":phase,"host_pid":os.getpid(),"model_viewing":"NOT_TESTED","file_saved":False}
        try:collect(report,load_context(directory,phase),phase)
        except BaseException as error:report.update(status="FAIL",error_type=type(error).__name__,error=str(error))
        json.dump(report,output,indent=2,ensure_ascii=True,allow_nan=False);output.write("\n");output.flush();os.fsync(output.fileno())
    print(report["status"])
    return 0 if report["status"]=="PASS_UINT32_OPERATIONS_LIFECYCLE_PHASE" else 1


if __name__=="__main__":raise SystemExit(main())
