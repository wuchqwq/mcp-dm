# -*- coding: utf-8 -*-
"""Read-only SAME-PID ownership check of a verified uint32 control crop.

External callers alone issue SHOW/STOP and close the one result document. This
observer sends no IPC, opens/closes no document and leaves new scientific
operation semantics NOT_QUALIFIED. Run each phase into an exclusive new file.
"""
import json
import os

from create_summary_fixture import require
from observe_uint32_operations import (bind_metadata, detached, load_context as probe_context,
                                       source_unchanged)
from uint32_operations_probe import Evidence, bit_equal, bounded_npy, integer, record, sha
from verify_operations_lifecycle import matching_documents, output_present, saved_operation


def path(directory,key,default):
    return os.environ.get("DM_NATIVE_U32_OPS_"+key,os.path.join(directory,default))


def strict_saved(request,receipt,operation,args,context):
    saved_operation(request,receipt,operation,args,context)
    timings=receipt.get("timings_us")
    require(type(timings) is dict and set(timings)=={"queue","execute"} and
            all(integer(timings[key],0,2**53-1) for key in timings),"Exact safe-integer SHOW/STOP timings required")


def previous_phase(previous,phase,context):
    require(type(previous) is dict and previous.get("status")=="PASS_UINT32_CONTROL_CROP_LIFECYCLE_PHASE" and
            previous.get("phase")==phase and integer(previous.get("host_pid"),os.getpid(),os.getpid()) and
            previous.get("session")==context["session"] and previous.get("image_id")==context["shown_id"] and
            previous.get("sources_unchanged") is True and previous.get("raw_views_and_wrappers_released") is True and
            previous.get("ordinary_python_success") is True and previous.get("show_repeat_same_receipt") is True and
            previous.get("show_reuse_same_document") is True,"Previous uint32 lifecycle phase identity/flags mismatch")
    for key,value in context["bound_hashes"].items():
        require(previous.get(key)==value,"Previous lifecycle phase evidence hash mismatch: "+key)
    ids=set(context["originals"]);shown=context["shown_id"]
    require(previous.get("live_output_ids")==sorted(ids if phase=="before_stop" else {shown}) and
            previous.get("released_output_ids")==sorted(set() if phase=="before_stop" else ids-{shown}) and
            previous.get("matching_documents")==1 and previous.get("total_documents")==context["truth"]["initial_document_count"]+1 and
            previous.get("source_document_matches")=={str(value[0]["id"]):1 for value in context["sources"].values()} and
            previous.get("shown_pixels_equal") is True and previous.get("shown_calibration_equal") is True,
            "Previous uint32 lifecycle ownership/pixel/document evidence mismatch")
    if phase=="before_stop":
        require(previous.get("stop_request_sha256") is None and previous.get("stop_receipt_sha256") is None and
                previous.get("stop_request_verified") is False,"before_stop contains ambiguous STOP evidence")
    else:
        require(previous.get("stop_request_verified") is True and
                previous.get("stop_request_sha256")==context["stop_request_sha256"] and
                previous.get("stop_receipt_sha256")==context["stop_receipt_sha256"] and
                previous.get("previous_phase_sha256")==context["before_hash"],"Previous phase STOP/hash binding mismatch")


def load_context(directory,phase):
    require(phase in ("before_stop","after_stop","after_close"),"Explicit uint32 lifecycle phase required")
    evidence=Evidence()
    truth_path=path(directory,"TRUTH","uint32-operations-truth.json")
    probe_path=path(directory,"PROBE","uint32-operations-probe.json")
    ledger_path=path(directory,"LEDGER","uint32-operations-requests.jsonl")
    context=probe_context(evidence,truth_path,probe_path,ledger_path,os.getpid())
    observation_path=path(directory,"OBSERVATION","uint32-operations-observation.json")
    observation=evidence.json(observation_path)
    require(observation.get("status")=="RECORDED_UNQUALIFIED" and
            integer(observation.get("host_pid"),os.getpid(),os.getpid()) and observation.get("session")==context["session"] and
            observation.get("truth_sha256")==sha(evidence.raw(truth_path)) and observation.get("probe_sha256")==sha(evidence.raw(probe_path)) and
            observation.get("ledger_sha256")==sha(evidence.raw(ledger_path)) and observation.get("source_protection")=="PASS_OBSERVED_SAME_HOST" and
            observation.get("independent_memory")=="PASS_OBSERVED_RAW_VIEWS" and observation.get("raw_views_and_wrappers_released") is True and
            observation.get("control_crop_verified") is True and observation.get("control_crop_rect")==[1,1,4,3] and
            observation.get("numerical_qualification")=="NOT_QUALIFIED" and observation.get("scientific_operator_pass") is False,
            "Original same-PID control crop observation/hash/flags mismatch")
    entries=observation.get("outputs")
    require(type(entries) is list and len(entries)==31 and observation.get("output_count")==31 and len(context["outputs"])==31,
            "Complete explicitly recorded 31-output pool required")
    originals={};references={}
    for entry in entries:
        image_id=entry.get("image_id")
        require(integer(image_id,1) and image_id not in originals and image_id in context["outputs"],"Observation output identity missing/duplicated")
        original=context["outputs"][image_id];request=original["request"]
        require(entry.get("label")==original["label"] and entry.get("request_id")==request["id"] and entry.get("operation")==request["op"] and
                entry.get("args")==request["args"] and entry.get("dtype") in ("uint32","float32","complex64"),"Observation immutable request/label/dtype mismatch")
        raw=evidence.raw(entry["snapshot"],8192)
        values=bounded_npy(raw,entry["shape"],{"uint32":"<u4","float32":"<f4","complex64":"<c8"}[entry["dtype"]])
        require(sha(raw)==entry.get("snapshot_file_sha256") and sha(values.tobytes(order="C"))==entry.get("pixel_sha256"),
                "Original detached output NPY/pixel hash mismatch")
        observed=dict(entry,values=values)
        bind_metadata(original["result"]["image"],image_id,observed)
        originals[image_id]=entry;references[image_id]=values
    shown=observation.get("control_crop_image_id")
    require(shown in originals and context["outputs"][shown]["label"]=="crop-HIGH","SHOW target is not independently verified control crop")
    crop=originals[shown];source,saved=context["sources"]["HIGH"]
    bit_equal(references[shown],saved[1:3,1:4],"Lifecycle control crop pixels differ from fixed uint32 reference")
    expected_cal=[dict(axis,raw_origin=axis["raw_origin"]-1,origin=axis["origin"]+axis["scale"]) for axis in source["calibration"]]
    require(crop["calibration"]==expected_cal and crop["intensity_calibration"]==source["intensity_calibration"],"Lifecycle control crop calibration differs")
    context.update(evidence=evidence,originals=originals,references=references,shown_id=shown,host_thread=context["threads"][0],worker_tid=context["threads"][1],
                   operation_request_ids=set(context["ledger"]),stop_request_sha256=None,stop_receipt_sha256=None,previous_phase_sha256=None)
    bound={"truth_sha256":sha(evidence.raw(truth_path)),"probe_sha256":sha(evidence.raw(probe_path)),
           "ledger_sha256":sha(evidence.raw(ledger_path)),"observation_sha256":sha(evidence.raw(observation_path))}
    def saved(key,default):
        name=path(directory,key,default);value=evidence.json(name);bound[key.lower()+"_sha256"]=sha(evidence.raw(name));return value
    show=saved("SHOW_REQUEST","uint32-show-request.json");receipt=saved("SHOW_RECEIPT","uint32-show-receipt.json")
    strict_saved(show,receipt,"SHOW",[shown],context)
    require(receipt["result"].get("candidate_probe") is True and receipt["result"].get("qualification")=="NOT_QUALIFIED",
            "Prepared uint32 SHOW qualification disclosure mismatch")
    bind_metadata(receipt["result"].get("image"),shown,dict(crop,values=references[shown]))
    repeat=saved("SHOW_REPEAT","uint32-show-repeat.json")
    require(repeat=={"request":show,"receipt":receipt},"Same-ID SHOW replay receipt differs from original")
    query=saved("SHOW_QUERY","uint32-show-query.json")
    require(query=={"request":record(context["session"],os.getpid(),"QUERY",[],show["id"]),"receipt":receipt},
            "Fresh QUERY did not recover immutable original SHOW")
    context["operation_request_ids"].add(show["id"])
    reuse=saved("SHOW_REUSE_REQUEST","uint32-show-reuse-request.json");reuse_receipt=saved("SHOW_REUSE_RECEIPT","uint32-show-reuse-receipt.json")
    strict_saved(reuse,reuse_receipt,"SHOW",[shown],context)
    require(reuse_receipt["result"]==receipt["result"],"New-ID SHOW reuse delivered different image/result")
    context["operation_request_ids"].add(reuse["id"])
    context["bound_hashes"]=bound
    stop_path=path(directory,"STOP_REQUEST","stop-request.json");stop_receipt_path=path(directory,"STOP_RECEIPT","stop-receipt.json")
    if phase=="before_stop":
        require(not os.path.lexists(stop_path) and not os.path.lexists(stop_receipt_path),"before_stop already has STOP evidence")
    else:
        stop=evidence.json(stop_path);stop_receipt=evidence.json(stop_receipt_path);strict_saved(stop,stop_receipt,"STOP",[],context)
        context["stop_request_sha256"]=sha(evidence.raw(stop_path));context["stop_receipt_sha256"]=sha(evidence.raw(stop_receipt_path))
        before_path=path(directory,"BEFORE","uint32-lifecycle-before_stop.json");before=evidence.json(before_path)
        previous_phase(before,"before_stop",context);context["before_hash"]=sha(evidence.raw(before_path));context["previous_phase_sha256"]=context["before_hash"]
        if phase=="after_close":
            after_path=path(directory,"AFTER_STOP","uint32-lifecycle-after_stop.json");after=evidence.json(after_path)
            previous_phase(after,"after_stop",context);context["previous_phase_sha256"]=sha(evidence.raw(after_path))
    return context


def collect(report,context,phase):
    import numpy as np
    import DigitalMicrograph as DM
    sources=context["sources"];shown=context["shown_id"]
    for entry,saved in sources.values():source_unchanged(entry,saved,detached(DM,np,entry["id"],entry["shape"],11))
    live=[];released=[];comparisons=[value[0]["id"] for value in sources.values()]
    for image_id,original in sorted(context["originals"].items()):
        present=output_present(DM,image_id)
        require(present is (phase=="before_stop" or (phase=="after_stop" and image_id==shown)),"Explicit uint32 output release/ownership mismatch")
        if not present:released.append(image_id);continue
        current=detached(DM,np,image_id,original["shape"],original["python_data_type_code"],comparisons+live)
        bit_equal(current["values"],context["references"][image_id],"Current explicit output pixels/type/axes changed")
        require(current["name"]==original["name"] and current["calibration"]==original["calibration"] and
                current["intensity_calibration"]==original["intensity_calibration"],"Current explicit output name/calibration changed")
        live.append(image_id)
    total,matches,source_matches=matching_documents(DM,shown,{value[0]["id"] for value in sources.values()})
    expected=context["truth"]["initial_document_count"]+(0 if phase=="after_close" else 1)
    require(total==expected and matches==(0 if phase=="after_close" else 1) and all(value==1 for value in source_matches.values()),
            "uint32 SHOW exact document identity/count mismatch")
    for entry,saved in sources.values():source_unchanged(entry,saved,detached(DM,np,entry["id"],entry["shape"],11))
    context["evidence"].unchanged()
    report.update(context["bound_hashes"])
    report.update(host_pid=os.getpid(),session=context["session"],phase=phase,image_id=shown,sources_unchanged=True,
                  raw_views_and_wrappers_released=True,ordinary_python_success=True,show_repeat_same_receipt=True,show_reuse_same_document=True,
                  live_output_ids=live,released_output_ids=released,matching_documents=matches,total_documents=total,source_document_matches=source_matches,
                  shown_pixels_equal=None if phase=="after_close" else True,shown_calibration_equal=None if phase=="after_close" else True,
                  stop_request_verified=phase!="before_stop",stop_request_sha256=context["stop_request_sha256"],stop_receipt_sha256=context["stop_receipt_sha256"],
                  previous_phase_sha256=context["previous_phase_sha256"],status="PASS_UINT32_CONTROL_CROP_LIFECYCLE_PHASE")


def main():
    directory=os.environ["DM_NATIVE_EVIDENCE_DIR"];phase=os.environ["DM_NATIVE_U32_OPS_PHASE"]
    output_path=path(directory,"LIFECYCLE_OUTPUT","uint32-lifecycle-"+phase+".json")
    with open(output_path,"x",encoding="utf-8") as output:
        report={"schema":1,"kind":"synthetic-only","status":"FAIL","phase":phase,"host_pid":os.getpid(),
                "numerical_qualification":"NOT_QUALIFIED","scientific_operator_pass":False,"ui_visibility":"NOT_TESTED_BY_THIS_SCRIPT","model_viewing":"NOT_TESTED"}
        try:collect(report,load_context(directory,phase),phase)
        except BaseException as error:report.update(status="FAIL",error_type=type(error).__name__,error=str(error))
        json.dump(report,output,indent=2,ensure_ascii=True,allow_nan=False);output.write("\n");output.flush();os.fsync(output.fileno())
    print(report["status"]+": control crop ownership only; new scientific semantics remain NOT_QUALIFIED")
    return 0 if report["status"]=="PASS_UINT32_CONTROL_CROP_LIFECYCLE_PHASE" else 1


if __name__=="__main__":raise SystemExit(main())
