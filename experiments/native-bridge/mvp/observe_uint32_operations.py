# -*- coding: utf-8 -*-
"""Same-PID read-only snapshots of a prepared uint32 operation discovery run.

Copies are detached from raw host views only after descriptor checks. No
scientific convention is inferred from the observed arrays or their names.
"""
import json
import os

from create_summary_fixture import require, spatial, intensity
from uint32_operations_probe import (Evidence, RESULT_TYPES, arrays, bounded_npy, integer, load_truth, plan,
                                    record, sha, strict_json, validate_receipt, validate_output, bit_equal, RID)


DTYPES={2:"float32",3:"complex64",11:"uint32"}


def load_context(evidence,truth_path,probe_path,ledger_path,actual_pid):
    truth,sources=load_truth(evidence,truth_path,actual_pid);probe=evidence.json(probe_path)
    require(probe.get("schema")==1 and probe.get("kind")=="synthetic-only" and probe.get("status")=="RECORDED_UNQUALIFIED" and
            probe.get("numerical_qualification")=="NOT_QUALIFIED" and integer(probe.get("host_pid"),actual_pid,actual_pid) and
            probe.get("session")==truth["session"] and probe.get("truth_sha256")==sha(evidence.raw(truth_path)),"Raw probe record/actual PID/session/hash mismatch")
    ledger={}
    for line in evidence.raw(ledger_path).splitlines():
        saved=strict_json(line);request_id=saved.get("id")
        require(type(request_id) is str and RID.fullmatch(request_id) and request_id not in ledger and saved==record(truth["session"],actual_pid,saved.get("op"),saved.get("args"),request_id) and
                saved.get("op") in RESULT_TYPES and type(saved.get("args")) is list and all(integer(v) for v in saved["args"]),"Original raw probe ledger shape/identity/wire mismatch")
        ledger[request_id]=saved
    checks=probe.get("checks");matrix=plan();expected={item["label"]:item for item in matrix}
    require(type(checks) is list and len(checks)==len(matrix)+2 and {v.get("label") for v in checks}==set(expected)|{"STATUS","STATUS_FINAL"},"Complete unique raw probe matrix required")
    checks={entry["label"]:entry for entry in checks};status=checks["STATUS"];validate_receipt(status.get("receipt"),status.get("request"))
    anchor=status["receipt"];value=anchor["result"];flag=probe.get("prepared_flag")
    require(value.get("ready") is True and value.get("binary_gate") is True and value.get(flag) is True and value.get("host_pid")==actual_pid and
            value.get("host_thread")==anchor["exec_tid"] and value.get("adapter_profile")=="gms-3.53.4137.0-windows-x64" and
            value.get("compatibility",{}).get("state")=="SUPPORTED" and integer(value.get("retained_result_count"),0,0),"Prepared probe STATUS anchor mismatch")
    threads=(anchor["exec_tid"],anchor["worker_tid"]);seen=set();outputs={};source_ids={v[0]["id"] for v in sources.values()}
    for label in ("STATUS",)+tuple(item["label"] for item in matrix)+("STATUS_FINAL",):
        entry=checks[label]
        if label in expected:
            item=expected[label];parent=item.get("parent")
            if parent and checks[parent].get("receipt",{}).get("state")!="completed":
                require(entry=={"label":label,"status":"SKIPPED_DEPENDENCY_FAILED","parent":parent},"Unbound skipped probe dependency")
                continue
            args=([checks[parent]["receipt"]["result"]["image_id"]] if parent else [sources[name][0]["id"] for name in item["sources"]])
            if "opcode" in item:args.append(item["opcode"])
            if "rect" in item:args.extend(item["rect"])
            op=item["op"]
        else:op,args="STATUS",[]
        request=entry.get("request",{});request_id=request.get("id")
        require(request_id in ledger and request_id not in seen and request==ledger[request_id] and request.get("op")==op and request.get("args")==args,
                "Probe original operation/request arguments mismatch")
        seen.add(request_id);receipt=entry.get("receipt",{});validate_receipt(receipt,request,threads)
        require(receipt["state"] in ("completed","failed"),"Nonterminal probe record cannot be observed as success")
        if op!="STATUS" and receipt["state"]=="completed":
            result=receipt["result"];image_id=validate_output(result,request,set(outputs),source_ids)
            outputs[image_id]={"label":label,"request":request,"result":result,"plan":expected[label]}
    require(seen==set(ledger) and probe.get("output_ids")==sorted(outputs),"Probe output pool/original ledger mismatch")
    final=checks["STATUS_FINAL"]["receipt"]["result"]
    require(integer(final.get("retained_result_count"),len(outputs),len(outputs)),"Probe final retained pool count mismatch")
    recoveries=probe.get("recovered")
    require(type(recoveries) is list and len(recoveries)==len(ledger),"Complete fresh-connection recovery matrix required")
    recovered=set();originals={entry["request"]["id"]:entry for entry in checks.values() if "receipt" in entry}
    for value in recoveries:
        query=value.get("request",{});request_id=query.get("id")
        require(request_id in originals and request_id not in recovered and query==record(truth["session"],actual_pid,"QUERY",[],request_id) and
                value.get("receipt")==originals[request_id]["receipt"],"Probe immutable QUERY recovery mismatch")
        recovered.add(request_id)
    return {"truth":truth,"sources":sources,"probe":probe,"outputs":outputs,"threads":threads,"ledger":ledger,"session":truth["session"]}


def detached(DM,np,image_id,shape,expected_code,comparisons=()):
    image=view=other=other_view=None
    try:
        image=DM.FindImageByID(image_id)
        require(image is not None and image.IsValid() and integer(image.GetID(),image_id,image_id),"Probe independent image identity invalid")
        code=image.GetDataType()
        require(integer(code,expected_code,expected_code) and code in DTYPES,"Independent raw image native type code differs from receipt")
        view=image.GetNumArray()
        require(type(view) is np.ndarray and view.ndim==2 and list(view.shape)==shape and view.dtype==np.dtype(DTYPES[code]) and
                all(integer(v,1,8) for v in shape),"Probe raw view dtype/shape exceeds bound or differs from native type code")
        for other_id in comparisons:
            try:
                other=DM.FindImageByID(other_id);require(other is not None and other.IsValid() and other.GetID()==other_id,"Probe comparison image invalid")
                other_view=other.GetNumArray();require(type(other_view) is np.ndarray and other_view.ndim==2 and all(integer(v,1,8) for v in other_view.shape),"Probe comparison raw view unbounded")
                require(not np.shares_memory(view,other_view),"Probe source/output raw views share memory")
            finally:other_view=other=None
        return {"values":np.array(view,order="C",copy=True),"name":image.GetName(),"python_data_type_code":code,
                "calibration":[spatial(image,d) for d in (0,1)],"intensity_calibration":intensity(image)}
    finally:other_view=other=view=image=None


def source_unchanged(entry,saved,observed):
    bit_equal(observed["values"],saved,"Original uint32 probe source pixels/type/shape changed")
    require(observed["name"]==entry["name"] and observed["calibration"]==entry["calibration"] and
            observed["intensity_calibration"]==entry["intensity_calibration"],"Original probe source name/spatial/intensity calibration changed")


def bind_metadata(actual,image_id,observation):
    values=observation["values"];code=observation["python_data_type_code"]
    require(type(actual) is dict and integer(actual.get("id"),image_id,image_id) and actual.get("name")==observation["name"] and
            actual.get("data_type_code")==code and actual.get("dtype")==str(values.dtype) and integer(actual.get("ndim"),2,2) and integer(actual.get("packing_style"),1,1) and
            actual.get("shape")==list(values.shape) and actual.get("dm_dimensions")==list(values.shape)[::-1] and integer(actual.get("pixels"),values.size,values.size),"Observed output metadata identity/dtype/axes/packing mismatch")
    require(code!=11 or (actual.get("is_integer") is True and actual.get("is_unsigned") is True),"Observed uint32 metadata signedness flags mismatch")
    axes=actual.get("calibration");require(type(axes) is list and len(axes)==2,"Observed output calibration metadata missing")
    for dim,expected in enumerate(observation["calibration"]):
        axis=axes[dim]
        require(integer(axis.get("dm_dimension"),dim,dim) and integer(axis.get("numpy_axis"),1-dim,1-dim) and integer(axis.get("size"),values.shape[1-dim],values.shape[1-dim]) and
                axis.get("origin")==expected["raw_origin"] and axis.get("calibrated_value_at_pixel_zero")==expected["origin"] and axis.get("scale")==expected["scale"] and
                axis.get("unit")== (expected["unit"] or None) and axis.get("usable") is bool(expected["unit"]) and
                axis.get("issue")== (None if expected["unit"] else "unknown_units"),"Observed output signed calibration differs from native receipt")


def collect(report,truth_path,probe_path,ledger_path,directory):
    import numpy as np
    evidence=Evidence();context=load_context(evidence,truth_path,probe_path,ledger_path,os.getpid())
    report.update(host_pid=os.getpid(),session=context["session"],truth_sha256=sha(evidence.raw(truth_path)),probe_sha256=sha(evidence.raw(probe_path)),ledger_sha256=sha(evidence.raw(ledger_path)))
    import DigitalMicrograph as DM
    expected_docs=context["truth"]["initial_document_count"]
    require(integer(DM.CountImageDocumentsOfAllWorkspaces(),expected_docs,expected_docs),"Probe observation document count changed")
    source_ids=[entry[0]["id"] for entry in context["sources"].values()]
    observations={}
    for label,(entry,saved) in context["sources"].items():
        observed=detached(DM,np,entry["id"],entry["shape"],11,[other for other in source_ids if other!=entry["id"]])
        source_unchanged(entry,saved,observed);observations[entry["id"]]=observed
    for image_id,entry in context["outputs"].items():
        native=entry["result"]["image"];code=native.get("data_type_code");shape=native.get("shape")
        require(code in DTYPES and type(shape) is list and len(shape)==2 and all(integer(v,1,8) for v in shape),"Candidate output native dtype/shape is unsupported for safe observation")
        observed=detached(DM,np,image_id,shape,code,list(observations));bind_metadata(native,image_id,observed)
        result=entry["result"];args=entry["request"]["args"];op=entry["request"]["op"]
        source_metas=result.get("sources") if op=="BINARY" or "sources" in result else [result.get("source")]
        source_ids_requested=args[:2] if op=="BINARY" else args[:1]
        require(type(source_metas) is list and len(source_metas)==len(source_ids_requested),"Candidate source metadata missing")
        for source_id,meta in zip(source_ids_requested,source_metas):
            require(source_id in observations,"Candidate source was not independently observed")
            bind_metadata(meta,source_id,observations[source_id])
        if any(observations[value]["python_data_type_code"]==11 for value in source_ids_requested) and op!="CROP":
            semantics={"input_dtypes":[str(observations[value]["values"].dtype) for value in source_ids_requested],"output_dtype":str(observed["values"].dtype),
                "selection":"DM native operator output; no bridge pixel cast","precision":{2:"binary32 result; not lossless for arbitrary uint32 inputs",
                    11:"uint32 native result storage",3:"complex binary32 result; not lossless for arbitrary uint32 inputs"}[code]}
            require(result.get("candidate_probe") is True and result.get("qualification")=="NOT_QUALIFIED" and result.get("dtype_semantics")==semantics,
                    "Candidate dtype/precision/qualification disclosure mismatch")
        path=os.path.abspath(os.path.join(directory,"observed-"+entry["label"]+".npy"))
        with open(path,"xb") as output:np.save(output,observed["values"],allow_pickle=False);output.flush();os.fsync(output.fileno())
        with open(path,"rb") as source:raw=source.read()
        report["outputs"].append({"label":entry["label"],"image_id":image_id,"request_id":entry["request"]["id"],"operation":op,"args":args,
            "status":"OBSERVED_UNQUALIFIED","snapshot":path,"snapshot_file_sha256":sha(raw),"pixel_sha256":sha(observed["values"].tobytes(order="C")),
            "dtype":str(observed["values"].dtype),"shape":shape,"python_data_type_code":code,"name":observed["name"],
            "calibration":observed["calibration"],"intensity_calibration":observed["intensity_calibration"],"numerical_qualification":"NOT_QUALIFIED"})
        observations[image_id]=observed
    crop_entries=[(image_id,entry) for image_id,entry in context["outputs"].items() if entry["label"]=="crop-HIGH"]
    require(len(crop_entries)==1,"Verified control crop required before any SHOW lifecycle")
    crop_id,crop_entry=crop_entries[0];crop=observations[crop_id]
    original,saved=context["sources"]["HIGH"]
    bit_equal(crop["values"],saved[1:3,1:4],"Independent control crop pixels/dtype/axes differ")
    expected_cal=[]
    for axis in original["calibration"]:
        expected_cal.append(dict(axis,raw_origin=axis["raw_origin"]-1,origin=axis["origin"]+axis["scale"]))
    require(crop["calibration"]==expected_cal and crop["intensity_calibration"]==original["intensity_calibration"],
            "Independent control crop spatial/intensity calibration differs")
    for label,(entry,saved) in context["sources"].items():source_unchanged(entry,saved,detached(DM,np,entry["id"],entry["shape"],11))
    require(integer(DM.CountImageDocumentsOfAllWorkspaces(),expected_docs,expected_docs),"Probe source/document state changed during observation")
    evidence.unchanged()
    report.update(status="RECORDED_UNQUALIFIED",source_protection="PASS_OBSERVED_SAME_HOST",independent_memory="PASS_OBSERVED_RAW_VIEWS",
                  raw_views_and_wrappers_released=True,document_count=expected_docs,output_count=len(report["outputs"]),
                  control_crop_verified=True,control_crop_image_id=crop_id,control_crop_rect=[1,1,4,3],
                  evidence_files_sha256={path:sha(raw) for path,raw in evidence.original.items()})


def main():
    directory=os.environ["DM_NATIVE_EVIDENCE_DIR"]
    def filename(key,default):return os.environ.get("DM_NATIVE_U32_OPS_"+key,os.path.join(directory,default))
    target=filename("OBSERVATION","uint32-operations-observation.json")
    with open(target,"x",encoding="utf-8") as output:
        report={"schema":1,"status":"FAIL","kind":"synthetic-only","outputs":[],"numerical_qualification":"NOT_QUALIFIED",
                "scientific_operator_pass":False,"ui_visibility":"NOT_TESTED","model_viewing":"NOT_TESTED","lifecycle":"NOT_TESTED"}
        try:collect(report,filename("TRUTH","uint32-operations-truth.json"),filename("PROBE","uint32-operations-probe.json"),filename("LEDGER","uint32-operations-requests.jsonl"),os.path.dirname(target))
        except BaseException as error:report.update(status="FAIL",error_type=type(error).__name__,error=str(error))
        json.dump(report,output,indent=2,ensure_ascii=True,allow_nan=False);output.write("\n");output.flush();os.fsync(output.fileno())
    print(report["status"]+": snapshots only; all new scientific semantics remain NOT_QUALIFIED")
    return 0 if report["status"]=="RECORDED_UNQUALIFIED" else 1


if __name__=="__main__":raise SystemExit(main())
