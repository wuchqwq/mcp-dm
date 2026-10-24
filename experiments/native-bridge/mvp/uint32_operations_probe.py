# -*- coding: utf-8 -*-
"""Prepared-only raw NB2 discovery. Records unknown science; never qualifies it.

This explicit client talks to one already prepared synthetic host. It starts
no host, opens no document and never retries a submitted operation. The raw
protocol route prevents an old Node dtype contract hiding a native result.
"""
import argparse
import json
import os
from pathlib import Path
import re
import time
import uuid

from create_summary_fixture import require
from verify_handoff import Evidence, bounded_npy, bit_equal, canonical, sha
from verify_operations import integer, strict_json

RESULT_TYPES={"STATUS":"status","CROP":"image_crop","UNARY":"native_image_operation","BINARY":"native_image_operation",
              "FILTER":"native_image_operation",**{op:"native_fourier_operation" for op in ("FFT","IFFT","REAL","IMAG")}}
RID=re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def arrays():
    import numpy as np
    low=np.arange(16,dtype=np.uint32).reshape(4,4)
    high=np.array([[0,1,16777215,16777216],[16777217,2147483647,2147483648,4294967294],
                   [123456789,3,65537,4294967295],[11,29,100000001,4000000001]],dtype=np.uint32)
    rhs=np.array([[1,2,0,3],[1,0,3,1],[0,3,1,2],[3,1,2,0]],dtype=np.uint32)
    filtered=np.array([[(7*x+11*y+(x*y)%5)%61 for x in range(8)] for y in range(8)],dtype=np.uint32)
    impulse=np.zeros((4,8),dtype=np.uint32);impulse[1,2]=16777217
    return {"LOW":low,"HIGH":high,"RHS":rhs,"FILTER_LOW":filtered,"FILTER_HIGH":filtered+np.uint32(16777217),
            "FFT_CONSTANT":np.full((4,4),3,dtype=np.uint32),"FFT_IMPULSE":impulse}


def plan():
    rows=[]
    for label in ("LOW","HIGH"):
        rows.extend({"label":"unary-"+label+"-"+str(code),"op":"UNARY","sources":[label],"opcode":code} for code in (1,2,3))
        rows.extend({"label":"binary-"+label+"-"+str(code),"op":"BINARY","sources":[label,"RHS"],"opcode":code} for code in (1,2,3))
    for label in ("FILTER_LOW","FILTER_HIGH"):
        rows.extend({"label":"filter-"+label+"-"+str(code),"op":"FILTER","sources":[label],"opcode":code} for code in (1,2,3,4))
    for label in ("LOW","HIGH","FFT_CONSTANT","FFT_IMPULSE"):
        rows.append({"label":"fft-"+label,"op":"FFT","sources":[label]})
    for label in ("LOW","HIGH"):
        rows.append({"label":"ifft-"+label,"op":"IFFT","parent":"fft-"+label})
        rows.append({"label":"inverse-real-"+label,"op":"REAL","parent":"ifft-"+label})
    rows.extend(({"label":"fft-real-HIGH","op":"REAL","parent":"fft-HIGH"},
                 {"label":"fft-imag-HIGH","op":"IMAG","parent":"fft-HIGH"},
                 {"label":"crop-HIGH","op":"CROP","sources":["HIGH"],"rect":[1,1,4,3]}))
    require(len(rows)==31,"Internal bounded probe matrix error")
    return rows


def load_truth(evidence,path,pid):
    truth=evidence.json(path);expected=arrays()
    require(truth.get("schema")==1 and truth.get("status")=="RECORDED" and truth.get("kind")=="synthetic-only" and
            truth.get("python_is_listener") is False and integer(truth.get("host_pid"),pid,pid) and type(truth.get("session")) is str and
            re.fullmatch(r"[a-f0-9]{32}",truth["session"]),"Prepared uint32 operations truth/PID/session mismatch")
    images=truth.get("images")
    require(type(images) is list and len(images)==len(expected) and {v.get("label") for v in images}==set(expected),"Complete fixed uint32 operations fixture required")
    ids=set();sources={}
    for entry in images:
        values=expected[entry["label"]]
        require(integer(entry.get("id"),1,0xfffffffe) and entry["id"] not in ids and entry.get("dtype")=="uint32" and
                entry.get("shape")==list(values.shape) and integer(entry.get("python_data_type_code"),11,11),"Probe source identity/type/shape mismatch")
        raw=evidence.raw(entry["source_npy"],8192);saved=bounded_npy(raw,list(values.shape),"<u4")
        bit_equal(saved,values,"Probe original high-bit fixture differs from predetermined uint32 values")
        require(sha(raw)==entry.get("source_file_sha256") and sha(saved.tobytes(order="C"))==entry.get("pixel_sha256"),"Probe source original NPY/hash mismatch")
        require(type(entry.get("name")) is str and entry["name"].isascii() and bool(entry["name"]) and
                entry.get("calibration")==[{"dm_axis":0,"origin":1.25,"raw_origin":5.,"scale":-.25,"unit":"nm"},
                    {"dm_axis":1,"origin":-2.5,"raw_origin":5.,"scale":.5,"unit":"nm"}] and
                entry.get("intensity_calibration")=={"origin":7.5,"scale":-2.,"unit":"arb"},"Probe fixed source name/spatial/intensity calibration mismatch")
        ids.add(entry["id"]);sources[entry["label"]]=(entry,saved)
    require(integer(truth.get("document_count_before_fixture"),0) and
            integer(truth.get("initial_document_count"),truth["document_count_before_fixture"]+7,truth["document_count_before_fixture"]+7),"Probe initial document count mismatch")
    return truth,sources


def record(session,pid,operation,args,request_id):
    return {"protocol":"NB2","session":session,"host_pid":pid,"id":request_id,"op":operation,"args":args,
            "wire":"NB2 %s %s %s%s\n"%(session,request_id,operation," "+" ".join(map(str,args)) if args else "")}


def validate_receipt(receipt,request,threads=None):
    require(type(request) is dict and type(request.get("id")) is str and RID.fullmatch(request["id"]) and request.get("op") in RESULT_TYPES,
            "Raw probe original request ID/operation invalid")
    require(type(receipt) is dict and receipt.get("protocol")=="NB2" and receipt.get("session")==request["session"] and
            receipt.get("id")==request["id"] and integer(receipt.get("host_pid"),request["host_pid"],request["host_pid"]) and
            receipt.get("state") in ("queued","running","completed","failed") and receipt.get("original_operation")==request["op"] and
            receipt.get("normalized_args")==request["args"] and type(receipt.get("normalized_args")) is list and all(integer(v) for v in receipt["normalized_args"]) and
            receipt.get("result_type")==RESULT_TYPES[request["op"]] and integer(receipt.get("result_version"),2 if request["op"] in ("FFT","IFFT","REAL","IMAG") else 1,
                2 if request["op"] in ("FFT","IFFT","REAL","IMAG") else 1),"Raw probe receipt original identity/state/type mismatch; unknown is not success")
    require(integer(receipt.get("worker_tid"),1) and integer(receipt.get("exec_tid")) and
            (threads is None or receipt["worker_tid"]==threads[1]),"Raw probe receipt worker identity mismatch")
    state=receipt["state"]
    if state in ("running","completed","failed"):
        require(integer(receipt["exec_tid"],1) and receipt["exec_tid"]!=receipt["worker_tid"] and
                (threads is None or receipt["exec_tid"]==threads[0]),"Raw probe execution did not use original host thread")
    else:require(receipt["exec_tid"]==0,"Raw queued receipt has native execution thread")
    timing=receipt.get("timings_us")
    require(type(timing) is dict and set(timing)=={"queue","execute"} and all(integer(timing[key],0,2**53-1) for key in timing),"Raw probe timing fields invalid")
    if state=="completed":require(type(receipt.get("result")) is dict and receipt["result"].get("backend")=="digitalmicrograph-native" and "code" not in receipt and "error" not in receipt,"Raw completed native result invalid")
    elif state=="failed":require(receipt.get("code")=="native_error" and type(receipt.get("error")) is str and bool(receipt["error"]) and "result" not in receipt,"Raw probe failed before native execution or has malformed native failure")
    else:require(not any(key in receipt for key in ("result","code","error")),"Raw nonterminal receipt contains terminal payload")


def validate_output(result,request,output_ids,source_ids):
    op,args=request["op"],request["args"]
    unary={1:"Negate",2:"Abs",3:"Square"};binary={1:"operator+",2:"operator-",3:"operator*"};filters={1:"SmoothFilter",2:"SobelFilter",3:"LaplaceFilter",4:"SharpenFilter"}
    name=(unary[args[-1]] if op=="UNARY" else binary[args[-1]] if op=="BINARY" else filters[args[-1]] if op=="FILTER" else
          {"FFT":"Real_FFT","IFFT":"IFFT","REAL":"Real","IMAG":"Imag"}.get(op))
    expected_operator="GMS::Image::GetSubSliceAsImage" if op=="CROP" else "GMSImageProcessing::"+name
    image_id=result.get("image_id")
    require(integer(image_id,1) and image_id not in output_ids|source_ids and result.get("image",{}).get("id")==image_id and
            result.get("operator")==expected_operator and result.get("source_write_requested") is False and result.get("snapshot_atomic") is False,
            "Raw probe output identity/operator/source protection contract invalid")
    expected_sources=args[:2] if op=="BINARY" else args[:1]
    require(result.get("source_image_ids")==expected_sources if "source_image_ids" in result else
            result.get("source_image_id")==expected_sources[0] and len(expected_sources)==1,"Raw probe output source identity differs from original arguments")
    return image_id


def default_exchange(session,wire,remaining):
    # Import only in this explicitly invoked client, never in an oracle/fixture.
    from test_transport import Pipe
    deadline=time.monotonic()+remaining
    def timeout_ms():
        left=deadline-time.monotonic()
        if left<=0:raise TimeoutError("Raw probe exchange deadline; preserve original request ID/session")
        return max(1,min(2500,int(left*1000)))
    with Pipe(session,timeout=min(3,remaining)) as pipe:
        encoded=wire.encode("ascii")
        require(pipe.io(encoded,timeout_ms=timeout_ms())==len(encoded),"Raw probe short request write; operation state unknown")
        data=b""
        while b"\n" not in data:
            chunk=pipe.io(timeout_ms=timeout_ms())
            require(bool(chunk),"Raw probe reply ended without LF")
            data+=chunk
            require(len(data)<=128*1024,"Raw probe response exceeded byte limit")
        line,tail=data.split(b"\n",1)
        require(not tail,"Raw probe received extra response bytes")
        receipt=strict_json(line)
        json.dumps(receipt,allow_nan=False)  # Reject overflowing exponents at every nesting depth.
        return receipt


def submit(request,exchange,threads=None,timeout=15):
    deadline=time.monotonic()+timeout
    receipt=exchange(request["session"],request["wire"],max(.001,deadline-time.monotonic()))
    validate_receipt(receipt,request,threads)
    while receipt["state"] in ("queued","running"):
        require(time.monotonic()<deadline,"Raw probe deadline elapsed; submitted operation may still execute; preserve its ID/session")
        time.sleep(min(.025,max(0,deadline-time.monotonic())))
        query=record(request["session"],request["host_pid"],"QUERY",[],request["id"])
        receipt=exchange(request["session"],query["wire"],max(.001,deadline-time.monotonic()))
        validate_receipt(receipt,request,threads)
    return receipt


def run(truth_path,new_directory,prepared_flag,exchange=default_exchange):
    evidence=Evidence();original=evidence.json(truth_path);truth,sources=load_truth(evidence,truth_path,original["host_pid"])
    require(truth["session"]==os.environ.get("DM_NATIVE_SESSION"),"Explicit raw probe session differs from prepared truth")
    require(type(prepared_flag) is str and re.fullmatch(r"prepared_[a-z0-9_]+_enabled",prepared_flag),"Explicit prepared-only status marker required")
    directory=Path(new_directory).resolve();directory.mkdir(exist_ok=False)
    report={"schema":1,"status":"FAIL","kind":"synthetic-only","host_pid":truth["host_pid"],"session":truth["session"],"truth_sha256":sha(evidence.raw(truth_path)),
            "prepared_flag":prepared_flag,"checks":[],"recovered":[],"numerical_qualification":"NOT_QUALIFIED","model_viewing":"NOT_TESTED"}
    with (directory/"uint32-operations-probe.json").open("x",encoding="utf-8") as output:
        try:
            with (directory/"uint32-operations-requests.jsonl").open("x",encoding="utf-8") as ledger:
                def call(label,op,args,threads=None):
                    request=record(truth["session"],truth["host_pid"],op,args,"u32-probe-"+uuid.uuid4().hex)
                    ledger.write(json.dumps(request,allow_nan=False)+"\n");ledger.flush();os.fsync(ledger.fileno())
                    entry={"label":label,"request":request};report["checks"].append(entry)
                    entry["receipt"]=submit(request,exchange,threads)
                    return entry
                status_entry=call("STATUS","STATUS",[]);status=status_entry["receipt"]["result"]
                require(status.get("ready") is True and status.get("binary_gate") is True and status.get(prepared_flag) is True and
                        status.get("host_pid")==truth["host_pid"] and status.get("host_thread")==status_entry["receipt"]["exec_tid"] and
                        status.get("adapter_profile")=="gms-3.53.4137.0-windows-x64" and status.get("compatibility",{}).get("state")=="SUPPORTED" and
                        integer(status.get("retained_result_count"),0,0),"Raw probe requires explicitly prepared exact-profile empty-pool host")
                threads=(status_entry["receipt"]["exec_tid"],status_entry["receipt"]["worker_tid"])
                entries={};output_ids=set();source_ids={v[0]["id"] for v in sources.values()}
                for item in plan():
                    parent=item.get("parent")
                    if parent:
                        prior=entries[parent]
                        if prior.get("receipt",{}).get("state")!="completed":
                            entry={"label":item["label"],"status":"SKIPPED_DEPENDENCY_FAILED","parent":parent};entries[item["label"]]=entry;report["checks"].append(entry);continue
                        args=[prior["receipt"]["result"]["image_id"]]
                    else:args=[sources[label][0]["id"] for label in item["sources"]]
                    if "opcode" in item:args.append(item["opcode"])
                    if "rect" in item:args.extend(item["rect"])
                    entry=call(item["label"],item["op"],args,threads);entries[item["label"]]=entry
                    if entry["receipt"]["state"]=="completed":
                        result=entry["receipt"]["result"];image_id=validate_output(result,entry["request"],output_ids,source_ids)
                        output_ids.add(image_id)
                final=call("STATUS_FINAL","STATUS",[],threads)
                require(final["receipt"]["result"].get(prepared_flag) is True and
                        integer(final["receipt"]["result"].get("retained_result_count"),len(output_ids),len(output_ids)),
                        "Raw probe retained-pool count differs from explicitly recorded outputs")
                for entry in report["checks"]:
                    if "receipt" not in entry:continue
                    request=entry["request"];query=record(truth["session"],truth["host_pid"],"QUERY",[],request["id"])
                    receipt=exchange(truth["session"],query["wire"],3);validate_receipt(receipt,request,threads)
                    require(receipt==entry["receipt"],"Raw fresh-connection QUERY changed immutable terminal record")
                    report["recovered"].append({"request":query,"receipt":receipt})
                report["output_ids"]=sorted(output_ids);evidence.unchanged();report["status"]="RECORDED_UNQUALIFIED"
        except BaseException as error:report.update(status="FAIL",error_type=type(error).__name__,error=str(error),automatic_retry=False)
        json.dump(report,output,indent=2,ensure_ascii=True,allow_nan=False);output.write("\n");output.flush();os.fsync(output.fileno())
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth",required=True);parser.add_argument("--output-directory",required=True)
    parser.add_argument("--prepared-flag",default="prepared_uint32_operations_enabled")
    args=parser.parse_args(argv);report=run(args.truth,args.output_directory,args.prepared_flag)
    print(report["status"]+": raw protocol discovery only; every new scientific operation remains NOT_QUALIFIED")
    return 0 if report["status"]=="RECORDED_UNQUALIFIED" else 1


if __name__=="__main__":raise SystemExit(main())
