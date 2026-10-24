# -*- coding: utf-8 -*-
"""SAME-PID read-only production uint32 operation, raw-view and handoff oracle.

Only new synthetic images from the fixed nine-source fixture are accepted.
This observer issues no native requests, opens/closes no document, and never
turns an unknown/error response into a numerical PASS. Explicit saved records
and detached arrays remain distinct from live DM identity and ownership.
"""
import json
import math
import os

from create_summary_fixture import require,spatial,intensity
from observe_uint32_operations import bind_metadata,source_unchanged
from uint32_acceptance import (decode,read as read_uint32,capture as capture_uint32,external as external_uint32)
from uint32_operations_acceptance import (Evidence,load_truth,plan,specification,status_contract,READ_TARGETS,
                                          SHOW_TARGETS,READ_PROVENANCE,HIGH_FFT_POLICY,record,integer,sha,bit_equal,bounded_npy)
from uint32_operations_probe import RESULT_TYPES,validate_output,RID
from verify_operations import strict_json
from verify_operations_math import quarter_turn_dft
from verify_uint32_operations_math import arithmetic_reference,filter_reference,frequency_calibration
from verify_handoff import validate_read,validate_capture,validate_external


def ledger(evidence,filename,session,pid):
    saved={}
    for line in evidence.raw(filename).splitlines():
        value=strict_json(line);request_id=value.get("id")
        require(type(request_id) is str and RID.fullmatch(request_id) and request_id not in saved and
                value==record(session,pid,value.get("op"),value.get("args"),request_id) and type(value.get("args")) is list and
                all(integer(arg) for arg in value["args"]),"Original production ledger/wire/ID mismatch")
        saved[request_id]=value
    return saved


def bind(entry,expected_tool,arguments,operation,args,context):
    request=entry.get("request",{});request_id=request.get("id")
    require(request_id in context["ledger"] and request_id not in context["seen"] and request==context["ledger"][request_id] and
            request==record(context["session"],context["pid"],operation,args,request_id) and entry.get("tool")==expected_tool and
            entry.get("arguments")==dict(arguments,request_id=request_id),"Production MCP tool/arguments/original request mismatch")
    output=decode(entry);receipt=output.get("native_receipt",{})
    expected_type="native_data_snapshot" if operation=="READ" else RESULT_TYPES[operation]
    version=2 if operation in ("FFT","IFFT","REAL") else 1
    require(type(receipt) is dict and receipt.get("protocol")=="NB2" and receipt.get("session")==context["session"] and
            receipt.get("id")==receipt.get("request_id")==request_id and integer(receipt.get("host_pid"),context["pid"],context["pid"]) and
            receipt.get("state")=="completed" and receipt.get("original_operation")==operation and receipt.get("normalized_args")==args and
            type(receipt.get("normalized_args")) is list and all(integer(value) for value in receipt["normalized_args"]) and
            receipt.get("result_type")==expected_type and integer(receipt.get("result_version"),version,version) and
            integer(receipt.get("exec_tid"),1) and integer(receipt.get("worker_tid"),1) and receipt["exec_tid"]!=receipt["worker_tid"] and
            not any(key in receipt for key in ("code","error","result")),"Production receipt identity/type/state/thread mismatch")
    timings=receipt.get("timings_us")
    require(type(timings) is dict and set(timings)=={"queue","execute"} and all(integer(timings[key],0,2**53-1) for key in timings),
            "Production exact nonnegative safe-integer receipt timings required")
    if "threads" in context:require((receipt["exec_tid"],receipt["worker_tid"])==context["threads"],"Production STATUS thread anchor changed")
    require(not any(key.startswith("candidate_") or key.startswith("prepared_") for key in output),"Production result contains candidate bypass/discovery payload")
    context["seen"].add(request_id)
    return output


def recovered_record(evidence,report,report_path,ledger_path,recovery_path):
    """One narrow post-native missing-executable continuation, never a retry."""
    source=report.get("recovered_from");resume=report.get("resume")
    require(type(source) is dict and set(source)=={"report","ledger","recovery_ledger","preserved_files"} and
            type(resume) is dict and set(resume)=={"ledger","ledger_sha256","queries"},"Explicit recovered-report original/copy/query descriptors required")
    original={}
    for key in ("report","ledger","recovery_ledger"):
        entry=source[key]
        require(type(entry) is dict and set(entry)=={"path","sha256","bytes_copy"} and
                os.path.realpath(entry["path"])!=os.path.realpath(entry["bytes_copy"]),"Recovery must preserve distinct original and exclusive bytes-copy files")
        raw=evidence.raw(entry["path"]);copied=evidence.raw(entry["bytes_copy"])
        require(raw==copied and sha(raw)==entry["sha256"],"Recovery original failure/ledger raw bytes or hash differ")
        original[key]=strict_json(raw) if key=="report" else raw
    require(os.path.realpath(source["report"]["bytes_copy"])!=os.path.realpath(report_path) and
            os.path.realpath(source["ledger"]["bytes_copy"])==os.path.realpath(ledger_path) and
            os.path.realpath(source["recovery_ledger"]["bytes_copy"])==os.path.realpath(recovery_path),"Recovery copied original files differ from supplied oracle inputs")
    failed=original["report"]
    require(failed.get("status")=="FAIL" and failed.get("error_type")=="FileNotFoundError" and type(failed.get("error")) is str and bool(failed["error"]) and
            type(failed.get("captures")) is list and len(failed["captures"])==1 and failed["captures"][0].get("label")=="filter" and failed.get("externals")==[],
            "Recovery only permits the recorded post-native missing external executable failure")
    for key in ("schema","kind","host_pid","session","truth_sha256","qualification_mode","checks","reads","recovery","catalog","output_ids","show_targets"):
        require(key in failed and report.get(key)==failed[key],"Recovered report changed original native evidence: "+key)
    old_capture=failed["captures"][0];old_read=next((entry for entry in failed["reads"] if entry.get("label")=="filter"),{})
    capture_uint32(evidence,old_capture,decode(old_read))
    expected_paths={os.path.realpath(old_capture["snapshot"]),os.path.realpath(old_capture["request_record"])}
    expected_paths.update(os.path.realpath(os.path.join(old_capture["receipt"]["capture_dir"],name)) for name in ("input.npy","input.json","capture.json"))
    arithmetic_snapshot=os.path.realpath(os.path.join(os.path.dirname(source["report"]["path"]),"snapshot-arithmetic.json"))
    arithmetic_read=next((entry for entry in failed["reads"] if entry.get("label")=="arithmetic"),{})
    require(evidence.json(arithmetic_snapshot)==arithmetic_read.get("response"),"Recovery original arithmetic READ snapshot differs from original MCP response")
    expected_paths.add(arithmetic_snapshot)
    preserved=source["preserved_files"]
    require(type(preserved) is list and len(preserved)==len(expected_paths) and
            all(type(entry) is dict and set(entry)=={"path","sha256"} for entry in preserved) and
            {os.path.realpath(entry["path"]) for entry in preserved}==expected_paths,"Recovery old-capture preserved-file set incomplete/duplicated")
    for entry in preserved:require(sha(evidence.raw(entry["path"]))==entry["sha256"],"Recovery modified an original captured artifact")
    for entry in report.get("captures",[]):
        require(os.path.realpath(entry["snapshot"]) not in expected_paths and os.path.realpath(entry["request_record"]) not in expected_paths and
                os.path.realpath(entry["receipt"]["capture_dir"])!=os.path.realpath(old_capture["receipt"]["capture_dir"]),"Recovery must create new capture artifacts without adopting/overwriting the old capture")
    saved=ledger(evidence,resume["ledger"],report["session"],report["host_pid"])
    require(sha(evidence.raw(resume["ledger"]))==resume["ledger_sha256"],"Recovery new QUERY ledger hash mismatch")
    queries=resume["queries"];producers={entry["label"]:entry for entry in failed["checks"] if entry.get("label") in {item["label"] for item in plan()}}
    require(type(queries) is list and len(queries)==len(saved)==len(producers)==32,"Recovery requires exactly 32 new QUERY-only observations")
    seen=set()
    for entry in queries:
        label=entry.get("label");old=producers.get(label,{});request=entry.get("request",{});request_id=request.get("id")
        require(label in producers and label not in seen and request_id==old["request"]["id"] and request_id in saved and request==saved[request_id] and
                request==record(report["session"],report["host_pid"],"QUERY",[],request_id) and entry.get("response")==old["response"],
                "Recovery attempted a producer or changed original immutable QUERY result")
        seen.add(label)


def load_context(evidence,truth_path,report_path,ledger_path,recovery_path,pid):
    truth,sources=load_truth(evidence,truth_path,pid);report=evidence.json(report_path)
    require(report.get("schema")==1 and report.get("kind")=="synthetic-only" and report.get("status") in ("RECORDED","RECORDED_RECOVERED") and
            report.get("qualification_mode")=="production" and integer(report.get("host_pid"),pid,pid) and report.get("session")==truth["session"] and
            report.get("truth_sha256")==sha(evidence.raw(truth_path)),"Original production report/hash/actual PID/session/mode mismatch")
    if report["status"]=="RECORDED_RECOVERED":recovered_record(evidence,report,report_path,ledger_path,recovery_path)
    else:require("recovered_from" not in report and "resume" not in report,"Normal production record cannot disguise recovery evidence")
    context={"evidence":evidence,"truth":truth,"sources":sources,"report":report,"session":truth["session"],"pid":pid,"seen":set(),
             "ledger":ledger(evidence,ledger_path,truth["session"],pid)}
    entries=report.get("checks");matrix=plan()
    require(type(entries) is list and [entry.get("label") for entry in entries]==["STATUS"]+[item["label"] for item in matrix]+["STATUS_FINAL"],
            "Exact ordered production 32-output matrix required")
    status=bind(entries[0],"dm_status",{},"STATUS",[],context);status_contract(status,pid)
    context["threads"]=(status["native_receipt"]["exec_tid"],status["native_receipt"]["worker_tid"])
    require(integer(status.get("retained_result_count"),0,0),"Production fixture must start with empty retained pool")
    outputs={};source_ids={entry[0]["id"] for entry in sources.values()};ids={}
    for item,entry in zip(matrix,entries[1:-1]):
        tool,arguments,operation,args=specification(item,sources,ids)
        output=bind(entry,tool,arguments,operation,args,context)
        image_id=validate_output(output,entry["request"],set(outputs),source_ids)
        ids[item["label"]]=image_id;outputs[image_id]={"plan":item,"entry":entry,"output":output}
    final=bind(entries[-1],"dm_status",{},"STATUS",[],context);status_contract(final,pid)
    require(integer(final.get("retained_result_count"),32,32),"Production final pool must contain exactly 32 explicitly recorded outputs")
    reads=report.get("reads")
    require(type(reads) is list and len(reads)==2 and {entry.get("label") for entry in reads}==set(READ_TARGETS),"Two typed output READs required")
    read_outputs={}
    for entry in reads:
        label=entry["label"];parent,rect=READ_TARGETS[label];image_id=ids[parent]
        read_outputs[label]=bind(entry,"dm_native_read",{"image_id":image_id,"rect":rect},"READ",[image_id]+rect,context)
    require(context["seen"]==set(context["ledger"]),"Unbound or missing original production ledger record")
    recovery=report.get("recovery");saved=ledger(evidence,recovery_path,truth["session"],pid)
    require(type(recovery) is list and len(recovery)==32 and len(saved)==32,"Complete fresh-client QUERY matrix required")
    seen=set();by_label={value["plan"]["label"]:value["entry"] for value in outputs.values()}
    for entry in recovery:
        label=entry.get("label");original=by_label.get(label,{});request=entry.get("request",{});request_id=request.get("id")
        require(label in by_label and label not in seen and request_id==original["request"]["id"] and request_id in saved and request==saved[request_id] and
                request==record(truth["session"],pid,"QUERY",[],request_id) and entry.get("response")==original["response"],
                "Production immutable fresh-client QUERY/original binding mismatch")
        seen.add(label)
    context.update(outputs=outputs,ids=ids,read_outputs=read_outputs)
    return context


def detached(DM,np,image_id,shape,code,comparisons=()):
    image=view=other=other_view=None
    try:
        image=DM.FindImageByID(image_id)
        require(image is not None and image.IsValid() and integer(image.GetID(),image_id,image_id) and integer(image.GetDataType(),code,code),
                "Production raw image native identity/type mismatch")
        view=image.GetNumArray();dtype={2:np.float32,3:np.complex64,11:np.uint32}.get(code)
        require(dtype is not None and type(view) is np.ndarray and view.ndim==2 and list(view.shape)==shape and view.dtype==np.dtype(dtype) and
                all(integer(value,1,256) for value in shape),"Production raw view dtype/shape exceeds bound")
        for other_id in comparisons:
            try:
                other=DM.FindImageByID(other_id);require(other is not None and other.IsValid() and other.GetID()==other_id,"Production raw memory comparison image invalid")
                other_view=other.GetNumArray();require(type(other_view) is np.ndarray and other_view.ndim==2 and all(integer(value,1,256) for value in other_view.shape),
                                                      "Production raw comparison view unbounded")
                require(not np.shares_memory(view,other_view),"Production raw source/output views share memory")
            finally:other_view=other=None
        return {"values":np.array(view,order="C",copy=True),"python_data_type_code":code,"name":image.GetName(),
                "calibration":[spatial(image,dim) for dim in (0,1)],"intensity_calibration":intensity(image)}
    finally:other_view=other=view=image=None


def dense_fourier_reference(source):
    import numpy as np
    require(source.dtype==np.uint32 and source.shape==(4,4),"Empirical dense Fourier policy only accepts fixed 4x4 uint32 fixture")
    rounded=source.astype(np.float32);result=np.empty((4,4),dtype=np.complex64);roots=(1,1j,-1,-1j)
    for y in range(4):
        for x in range(4):
            terms=[float(rounded[j,i])*roots[((y-2)*j+(x-2)*i)%4] for j in range(4) for i in range(4)]
            result[y,x]=complex(math.fsum(complex(value).real for value in terms),math.fsum(complex(value).imag for value in terms))
    threshold=HIGH_FFT_POLICY["threshold_factor"]*math.fsum(abs(float(value)) for value in rounded.flat)
    return result,threshold


def numerical(item,actual,sources,observations):
    import numpy as np
    op=item["op"];label=item["label"];source_label=item.get("sources",["LOW"])[0];source,saved=sources[source_label]
    expected_cal=source["calibration"];expected_intensity=source["intensity_calibration"];policy="exact represented values; signed zero preserved"
    if op in ("UNARY","BINARY"):
        reference=arithmetic_reference(op,[item["opcode"]],[sources[name][1] for name in item["sources"]])
    elif op=="FILTER":
        reference=saved.copy() if source_label=="BOUNDARY256" else filter_reference(saved,item["opcode"])
    elif op=="CROP":
        reference=saved[1:3,1:4]
        expected_cal=[dict(axis,raw_origin=axis["raw_origin"]-1,origin=axis["origin"]+axis["scale"]) for axis in expected_cal]
    else:
        inverse=op!="FFT";expected_cal=frequency_calibration(source,saved.shape,inverse);expected_intensity={"origin":0.,"scale":1.,"unit":""}
        if source_label=="BOUNDARY256":
            reference=np.zeros((256,256),dtype=np.complex64);reference[128,128]=complex(2**40,0)
        elif label=="fft-HIGH":
            reference,threshold=dense_fourier_reference(saved)
            require(actual["values"].dtype==np.complex64 and actual["values"].shape==reference.shape and np.isfinite(actual["values"]).all(),"Dense Fourier native dtype/shape/finite mismatch")
            error=float(np.abs(actual["values"].astype(np.complex128)-reference.astype(np.complex128)).max())
            require(error<=threshold,"Dense Fourier exceeds predeclared empirical acceptance threshold")
            require(actual["calibration"]==expected_cal and actual["intensity_calibration"]==expected_intensity,"Dense Fourier signed/spatial/intensity calibration mismatch")
            return {"status":"PASS_PREDECLARED_EMPIRICAL_FIXTURE","maximum_absolute_error":error,"acceptance_threshold":threshold,"policy":HIGH_FFT_POLICY}
        elif inverse:reference=saved.astype(np.complex64 if op=="IFFT" else np.float32)
        else:reference=quarter_turn_dft(saved.astype(np.float32))
        # Native FFT may choose either IEEE sign for mathematically zero
        # components. No nonzero bit or nonzero numerical tolerance is allowed.
        observed=actual["values"]
        require(observed.dtype==reference.dtype and observed.shape==reference.shape and np.isfinite(observed).all() and np.array_equal(observed,reference),
                "Fixed exact-root Fourier values/type/axes differ: "+label)
        policy="exact binary32 component values; IEEE zero sign unspecified by native Fourier"
    if op not in ("FFT","IFFT","REAL"):bit_equal(actual["values"],reference,"Fixed native "+label+" values/dtype/axes/signed-zero differ")
    require(actual["calibration"]==expected_cal and actual["intensity_calibration"]==expected_intensity,"Fixed native "+label+" source/spatial/intensity calibration differs")
    return {"status":"PASS_BOUNDED_FIXED_SYNTHETIC","reference_pixel_sha256":sha(reference.tobytes(order="C")),"comparison":policy}


def collect(report,truth_path,report_path,ledger_path,recovery_path,directory):
    import numpy as np
    evidence=Evidence();context=load_context(evidence,truth_path,report_path,ledger_path,recovery_path,os.getpid())
    import DigitalMicrograph as DM
    docs=context["truth"]["initial_document_count"]
    require(integer(DM.CountImageDocumentsOfAllWorkspaces(),docs,docs),"Production observer document baseline changed")
    observations={};source_ids=[entry[0]["id"] for entry in context["sources"].values()]
    for entry,saved in context["sources"].values():
        observed=detached(DM,np,entry["id"],entry["shape"],11,[value for value in source_ids if value!=entry["id"]])
        source_unchanged(entry,saved,observed);observations[entry["id"]]=observed
    output_records=[]
    for image_id,entry in context["outputs"].items():
        output=entry["output"];meta=output.get("image",{});shape=meta.get("shape");code=meta.get("data_type_code")
        require(code in (2,3,11) and type(shape) is list and len(shape)==2 and all(integer(value,1,256) for value in shape),"Production output descriptor not safely observable")
        observed=detached(DM,np,image_id,shape,code,list(observations));bind_metadata(meta,image_id,observed)
        request=entry["entry"]["request"];args=request["args"];op=request["op"];source_ids_requested=args[:2] if op=="BINARY" else args[:1]
        source_metas=output.get("sources") if "sources" in output else [output.get("source")]
        require(type(source_metas) is list and len(source_metas)==len(source_ids_requested),"Production source metadata missing")
        for source_id,source_meta in zip(source_ids_requested,source_metas):bind_metadata(source_meta,source_id,observations[source_id])
        if op!="CROP":
            expected={"input_dtypes":[str(observations[source_id]["values"].dtype) for source_id in source_ids_requested],"output_dtype":str(observed["values"].dtype),
                "selection":"DM native operator output; no bridge pixel cast","precision":{2:"binary32 result; not lossless for arbitrary uint32 inputs",11:"uint32 native result storage",3:"complex binary32 result; not lossless for arbitrary uint32 inputs"}[code]}
            require(output.get("dtype_semantics")==expected,"Production native dtype/precision disclosure mismatch")
        math_result=numerical(entry["plan"],observed,context["sources"],observations)
        filename=os.path.abspath(os.path.join(directory,"observed-"+entry["plan"]["label"]+".npy"))
        with open(filename,"xb") as target:np.save(target,observed["values"],allow_pickle=False);target.flush();os.fsync(target.fileno())
        with open(filename,"rb") as source:snapshot_raw=source.read()
        output_records.append(dict(math_result,label=entry["plan"]["label"],image_id=image_id,request_id=request["id"],operation=op,args=args,
            snapshot=filename,snapshot_file_sha256=sha(snapshot_raw),pixel_sha256=sha(observed["values"].tobytes(order="C")),dtype=str(observed["values"].dtype),
            python_data_type_code=code,shape=shape,name=observed["name"],calibration=observed["calibration"],intensity_calibration=observed["intensity_calibration"]))
        observations[image_id]=observed
    packages={};captures=context["report"].get("captures")
    require(type(captures) is list and len(captures)==2 and {entry.get("label") for entry in captures}==set(READ_TARGETS),"Both typed captured output packages required")
    for capture in captures:
        label=capture["label"];parent,rect=READ_TARGETS[label];image_id=context["ids"][parent];creation=context["outputs"][image_id]
        output=context["read_outputs"][label];request=creation["entry"]["request"]
        provenance={"operation":request["op"],"request_id":request["id"],"source_image_ids":request["args"][:2] if request["op"]=="BINARY" else request["args"][:1],
                    "semantics":READ_PROVENANCE[label]}
        # The immutable retained-result semantic is checked against the
        # protocol's fixed operation-specific value, never inferred from dtype.
        if output["dtype"]=="uint32":
            read_uint32(output,image_id,rect,observations[image_id],provenance);packages[label]=capture_uint32(evidence,capture,output)
        else:
            validate_read(output,image_id,rect,observations[image_id],provenance);packages[label]=validate_capture(evidence,capture,output)
    external_entries=context["report"].get("externals")
    require(type(external_entries) is list and len(external_entries)==2 and {entry.get("capture_label") for entry in external_entries}==set(READ_TARGETS),"Both explicit external result records required")
    externals={}
    for entry in external_entries:
        label=entry["capture_label"];package=packages[label]
        externals[label]=(external_uint32(evidence,entry,package) if package["values"].dtype==np.uint32 else
                          validate_external(evidence,dict(entry,capture_label="processed"),package))
    for entry,saved in context["sources"].values():source_unchanged(entry,saved,detached(DM,np,entry["id"],entry["shape"],11))
    require(integer(DM.CountImageDocumentsOfAllWorkspaces(),docs,docs),"Production source documents changed during oracle")
    evidence.unchanged()
    report.update(status="PASS_BOUNDED_UINT32_OPERATIONS",host_pid=os.getpid(),session=context["session"],qualification_mode="production",outputs=output_records,output_count=32,
        truth_sha256=sha(evidence.raw(truth_path)),mcp_report_sha256=sha(evidence.raw(report_path)),ledger_sha256=sha(evidence.raw(ledger_path)),recovery_ledger_sha256=sha(evidence.raw(recovery_path)),
        source_protection="PASS",independent_memory="PASS_RAW_VIEWS",raw_views_and_wrappers_released=True,document_count=docs,immutable_fresh_query="PASS",
        typed_handoff="PASS_BITWISE_ACTUAL_DTYPE",captures={label:{"dtype":str(value["values"].dtype),"files_sha256":value["hashes"]} for label,value in packages.items()},
        external_means=externals,show_target_ids=[context["ids"][label] for label in SHOW_TARGETS],
        evidence_files_sha256={filename:sha(raw) for filename,raw in evidence.original.items()})


def paths():
    directory=os.environ["DM_NATIVE_EVIDENCE_DIR"]
    return lambda key,default:os.environ.get("DM_NATIVE_U32_PROD_"+key,os.path.join(directory,default))


def main():
    filename=paths();target=filename("OUTPUT","uint32-production-independent.json")
    with open(target,"x",encoding="utf-8") as output:
        report={"schema":1,"status":"FAIL","kind":"synthetic-only","model_viewing":"NOT_TESTED","lifecycle":"NOT_TESTED_BY_THIS_SCRIPT","dm_file_save":False}
        try:collect(report,filename("TRUTH","uint32-production-truth.json"),filename("REPORT","uint32-operations-mcp-report.json"),
                    filename("LEDGER","uint32-operations-requests.jsonl"),filename("RECOVERY_LEDGER","uint32-operations-recovery-requests.jsonl"),os.path.dirname(target))
        except BaseException as error:report.update(status="FAIL",error_type=type(error).__name__,error=str(error))
        json.dump(report,output,indent=2,ensure_ascii=True,allow_nan=False);output.write("\n");output.flush();os.fsync(output.fileno())
    print(report["status"]+": fixed synthetic scope; dense HIGH uses predeclared empirical policy")
    return 0 if report["status"]=="PASS_BOUNDED_UINT32_OPERATIONS" else 1


if __name__=="__main__":raise SystemExit(main())
