# -*- coding: utf-8 -*-
"""Strict explicit synthetic uint32 stdio workflow; no DM process/UI control.

Original NB2 requests are fsynced before every tool call. This client records
receipts and saved files; the separate same-host oracle certifies live pixels.
STOP is deliberately a later explicit stop_native.py action, with its own
pre-submission record, after that oracle has released its Python wrappers.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from accept_mcp import ROOT, StdioClient, require, strict_json, validate_receipt
from accept_summary_mcp import CATALOG
from uint32_acceptance import Evidence, RECT, SOURCE_STATS, CROP_STATS, load_truth, sha, status_contract, summary
from verify_uint32 import cases


def new_json(path,value):
    with Path(path).open("x",encoding="utf-8") as output:
        json.dump(value,output,indent=2,ensure_ascii=True,allow_nan=False);output.write("\n");output.flush();os.fsync(output.fileno())


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory",required=True,type=Path)
    parser.add_argument("--output-directory",required=True,type=Path)
    parser.add_argument("--qualification-mode",required=True,choices=("prepared","production"))
    parser.add_argument("--analysis-python",default=sys.executable)
    args=parser.parse_args(argv)
    truth_path=args.directory.resolve()/"uint32-truth.json"
    truth=json.loads(truth_path.read_text(encoding="utf-8"))
    evidence=Evidence();truth,sources=load_truth(evidence,str(truth_path),truth["host_pid"])
    require(truth["session"]==os.environ.get("DM_NATIVE_SESSION"),"Explicit prepared session required")
    directory=args.output_directory.resolve();directory.mkdir(exist_ok=False)
    report={"schema":1,"status":"FAIL","host_pid":truth["host_pid"],"session":truth["session"],"truth_sha256":sha(truth_path.read_bytes()),
        "qualification_mode":args.qualification_mode,"crop_rect":RECT,"checks":[],"previews":[],"recovery":[],"captures":[],
        "source_invariance":"NOT_TESTED_BY_THIS_CLIENT","model_viewing":"NOT_TESTED","independent_host_oracle_required":True}
    client=None;node=shutil.which("node") or "node";host_thread=worker=None
    with (directory/"uint32-mcp-report.json").open("x",encoding="utf-8") as report_file:
        try:
            with (directory/"uint32-events.jsonl").open("x",encoding="utf-8") as trace,(directory/"uint32-requests.jsonl").open("x",encoding="utf-8") as ledger,(directory/"uint32-recovery-requests.jsonl").open("x",encoding="utf-8") as recovery_ledger:
                def connect():
                    value=StdioClient([node,str(ROOT/"server.mjs")],dict(os.environ,DM_MCP_BACKEND="native",DM_NATIVE_SESSION=truth["session"],DM_MCP_TIMEOUT_MS="10000",DM_MCP_ALLOW_DMSCRIPT="0"),trace,15)
                    try:
                        initialized=value.rpc("initialize",{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"native-uint32-acceptance","version":"1"}})
                        require("error" not in initialized and initialized.get("result",{}).get("serverInfo")=={"name":"digitalmicrograph","version":"0.6.0"},"uint32 MCP initialization failed")
                        value.notify("notifications/initialized")
                        catalog=value.rpc("tools/list",{}).get("result",{}).get("tools",[])
                        require(len(catalog)==len(CATALOG) and {v.get("name") for v in catalog}==CATALOG,"uint32 native catalog changed")
                        return value
                    except BaseException:
                        value.close()
                        raise
                def record(operation,native_args,request_id,target):
                    value={"protocol":"NB2","session":truth["session"],"host_pid":truth["host_pid"],"id":request_id,"op":operation,"args":native_args,
                        "wire":"NB2 %s %s %s%s\n" % (truth["session"],request_id,operation," "+" ".join(map(str,native_args)) if native_args else "")}
                    target.write(json.dumps(value,allow_nan=False)+"\n");target.flush();os.fsync(target.fileno());return value
                def call(label,spec,bucket="checks",request_id=None,target=None):
                    tool,arguments,operation,native_args,failure=spec
                    request_id=request_id or "uint32-"+uuid.uuid4().hex
                    params=dict(arguments,request_id=request_id);saved=record(operation,native_args,request_id,target or ledger)
                    response=client.rpc("tools/call",{"name":tool,"arguments":params})
                    require("error" not in response and type(response.get("result")) is dict,"uint32 MCP RPC error")
                    response=response["result"];entry={"label":label,"tool":tool,"arguments":params,"request":saved,"response":response};report[bucket].append(entry)
                    require(response.get("isError") is not True if failure is None else response.get("isError") is True,"uint32 wrong MCP failure state")
                    output=strict_json(response["content"][0]["text"])
                    receipt=output.get("native_receipt",{})
                    if failure is None:
                        validate_receipt(output,request_id,truth["session"],"digitalmicrograph-native",truth["host_pid"],host_thread)
                    else:
                        require(receipt.get("state")=="failed" and receipt.get("code")=="native_error" and receipt.get("error")==failure,"uint32 refusal wrong domain or unknown")
                    require(receipt.get("original_operation")==operation and receipt.get("normalized_args")==native_args and (worker is None or receipt.get("worker_tid")==worker),"uint32 original native identity changed")
                    return output,entry
                client=connect()
                source,raw=sources["CALIBRATED"][0]["id"],sources["RAW_UNITS"][0]["id"]
                matrix=cases(source,raw,1)
                status,unused=call("status",matrix["status"])
                status_contract(status,args.qualification_mode,truth["host_pid"])
                host_thread,worker=status["native_receipt"]["exec_tid"],status["native_receipt"]["worker_tid"]
                for label in ("mean_calibrated","summary_calibrated","mean_raw_units","summary_raw_units"):
                    output,unused=call(label,matrix[label])
                    entry,values=sources["RAW_UNITS" if label.endswith("raw_units") else "CALIBRATED"]
                    summary(output,entry["id"],{"values":values,"name":entry["name"],"calibration":entry["calibration"]},SOURCE_STATS,label.startswith("mean_"))
                def preview(label,image_id,bounds):
                    output,entry=call(label,("dm_native_preview",{"image_id":image_id,"max_width":bounds[0],"max_height":bounds[1]},"PREVIEW",[image_id]+bounds,None),"previews")
                    blocks=[v for v in entry["response"]["content"] if v.get("type")=="image"]
                    require(len(blocks)==1 and blocks[0].get("mimeType")=="image/png","uint32 preview PNG missing")
                    target=directory/("uint32-preview-"+label+".png")
                    with target.open("xb") as file:file.write(base64.b64decode(blocks[0]["data"],validate=True))
                    entry.update(png=str(target),png_sha256=sha(target.read_bytes()))
                preview("source",source,[128,128])
                crop,crop_entry=call("crop",matrix["crop"])
                crop_id=crop["image_id"]
                require(type(crop_id) is int and crop_id not in (source,raw) and crop.get("image",{}).get("dtype")=="uint32","uint32 CROP did not create uint32 output")
                matrix=cases(source,raw,crop_id)
                call("pool_after_crop",matrix["pool_after_crop"])
                for label in ("mean_crop","summary_crop"):
                    output,unused=call(label,matrix[label])
                    entry,values=sources["CALIBRATED"]
                    cal=[dict(axis,raw_origin=axis["raw_origin"]-1,origin=axis["origin"]+axis["scale"]) for axis in entry["calibration"]]
                    summary(output,crop_id,{"values":values[1:3,1:4],"name":crop["image"]["name"],"calibration":cal},CROP_STATS,label.startswith("mean_"))
                snapshots=[]
                for label in ("read_source","read_raw_units","read_crop"):
                    output,entry=call(label,matrix[label])
                    if label!="read_raw_units":
                        capture_label="source" if label=="read_source" else "crop"
                        path=directory/("snapshot-"+capture_label+".json");new_json(path,entry["response"]);snapshots.append((capture_label,path))
                preview("crop",crop_id,[2,1])
                for label in ("bad_unary","bad_binary","bad_fft","bad_real","bad_filter","bad_crop_missing_units"):call(label,matrix[label])
                client.close();require(client.proc.returncode==0,"First owned Node did not exit normally");client=None
                client=connect()  # Same native host/session, genuinely new stdio client.
                original_id=crop_entry["request"]["id"]
                for kind in ("fresh_query","repeat","conflict","query_after_conflict"):
                    tool="dm_crop" if kind in ("repeat","conflict") else "dm_native_result"
                    rect=[0,0,2,2] if kind=="conflict" else RECT
                    operation="CROP" if tool=="dm_crop" else "QUERY";native_args=[source]+rect if operation=="CROP" else []
                    params={"image_id":source,"rect":rect,"request_id":original_id} if operation=="CROP" else {"request_id":original_id}
                    saved=record(operation,native_args,original_id,recovery_ledger)
                    message=client.rpc("tools/call",{"name":tool,"arguments":params});require("error" not in message,"uint32 recovery RPC failed")
                    response=message["result"];report["recovery"].append({"kind":kind,"tool":tool,"arguments":params,"request":saved,"response":response})
                    if kind=="conflict":
                        output=strict_json(response["content"][0]["text"])
                        require(response.get("isError") is True and output.get("native_receipt",{}).get("code")=="id_conflict","uint32 conflicting ID was not refused")
                    else:require(response==crop_entry["response"],"uint32 immutable repeat/QUERY changed CROP output")
                call("pool_after_recovery",matrix["pool_after_recovery"])
                workspace=directory/"external-workspace";workspace.mkdir()
                for label,snapshot in snapshots:
                    request_id="uint32-encode-"+label+"-"+uuid.uuid4().hex
                    command=[node,str(ROOT/"tools"/"native_snapshot_handoff.mjs"),"--workspace",str(workspace),"--output","capture-"+label,"--request-id",request_id,"--snapshot",str(snapshot)]
                    completed=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,check=True)
                    cap=strict_json(completed.stdout.decode("utf-8"));require(cap.get("state")=="captured","uint32 encoder did not complete")
                    report["captures"].append({"label":label,"snapshot":str(snapshot),"snapshot_sha256":sha(snapshot.read_bytes()),"request_record":str(workspace/"handoff-requests"/(request_id+".json")),"receipt":cap})
                crop_capture=next(v for v in report["captures"] if v["label"]=="crop")
                external_dir=workspace/"external-mean"
                command=[args.analysis_python,str(ROOT/"examples"/"native_handoff_mean.py"),"--workspace",str(workspace),"--capture",crop_capture["receipt"]["capture_dir"],"--output","external-mean"]
                completed=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60,check=True)
                report["external"]={"output_dir":str(external_dir),"capture_label":"crop","command":command,"stdout":completed.stdout.decode("utf-8"),"stderr":completed.stderr.decode("utf-8")}
                evidence.unchanged();report["status"]="RECORDED"
        except BaseException as error:
            report.update(status="FAIL",error_type=type(error).__name__,error=str(error))
            if isinstance(error,subprocess.CalledProcessError):
                report.update(subprocess_stdout=(error.stdout or b"").decode("utf-8",errors="replace"),subprocess_stderr=(error.stderr or b"").decode("utf-8",errors="replace"))
        finally:
            if client is not None:
                try:client.close();require(client.proc.returncode==0,"Owned Node did not exit normally")
                except Exception as error:report.update(status="FAIL",shutdown_error=str(error))
            json.dump(report,report_file,indent=2,ensure_ascii=True,allow_nan=False);report_file.write("\n");report_file.flush();os.fsync(report_file.fileno())
    print(report["status"]+": independent same-host uint32 oracle REQUIRED")
    return 0 if report["status"]=="RECORDED" else 1


if __name__=="__main__":raise SystemExit(main())
