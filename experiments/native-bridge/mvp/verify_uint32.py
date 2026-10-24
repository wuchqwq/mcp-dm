# -*- coding: utf-8 -*-
"""Independent same-PID uint32 oracle; explicit manual host execution only."""
import base64
import json
import os

from create_summary_fixture import require
from uint32_acceptance import (Evidence, RECT, SOURCE_STATS, CROP_STATS, bind, capture, external, decode,
    fixed_values, load_truth, load_ledger, metadata, read, sha, status_contract, summary, bit_equal,
    reference_preview, decode_gray8_png, MAPPING, ORIENTATION, SAMPLING, integer)
from verify_handoff import observe, check_source


def cases(source,raw,crop):
    result={"status":("dm_status",{},"STATUS",[],None),
            "pool_after_crop":("dm_status",{},"STATUS",[],None),"pool_after_recovery":("dm_status",{},"STATUS",[],None),
            "crop":("dm_crop",{"image_id":source,"rect":RECT},"CROP",[source]+RECT,None)}
    for label,image_id in (("calibrated",source),("raw_units",raw),("crop",crop)):
        result["mean_"+label]=("dm_native_mean",{"image_id":image_id},"MEAN",[image_id],None)
        result["summary_"+label]=("dm_native_summary",{"image_id":image_id},"SUMMARY",[image_id],None)
    for label,image_id,rect in (("read_source",source,[0,0,4,4]),("read_raw_units",raw,[0,0,4,4]),("read_crop",crop,[0,0,3,2])):
        result[label]=("dm_native_read",{"image_id":image_id,"rect":rect},"READ",[image_id]+rect,None)
    result.update({
        "bad_unary":("dm_native_unary",{"image_id":source,"operation":"square"},"UNARY",[source,3],"native_arithmetic_requires_float32_2d"),
        "bad_binary":("dm_native_binary",{"left_image_id":source,"right_image_id":source,"operation":"add"},"BINARY",[source,source,1],"native_arithmetic_requires_float32_2d"),
        "bad_fft":("dm_native_fft",{"image_id":source,"direction":"forward"},"FFT",[source],"native_fft_input_type_or_dimensions_unsupported"),
        "bad_real":("dm_native_complex",{"image_id":source,"component":"real"},"REAL",[source],"native_fft_component_requires_plugin_transform"),
        "bad_filter":("dm_native_filter",{"image_id":source,"operation":"smooth"},"FILTER",[source,1],"native_filter_requires_float32_2d_ordinary_packing"),
        "bad_crop_missing_units":("dm_crop",{"image_id":raw,"rect":RECT},"CROP",[raw]+RECT,"unknown_image_units")})
    return result


def load_context(evidence,truth_path,report_path,ledger_path,recovery_path,pid):
    truth,sources=load_truth(evidence,truth_path,pid);report=evidence.json(report_path)
    require(report.get("schema")==1 and report.get("status")=="RECORDED" and integer(report.get("host_pid"),pid,pid) and
            report.get("session")==truth["session"] and report.get("truth_sha256")==sha(evidence.raw(truth_path)) and
            report.get("crop_rect")==RECT and report.get("qualification_mode") in ("prepared","production"),"uint32 MCP report/truth/host/mode mismatch")
    records=load_ledger(evidence,ledger_path,pid,truth["session"])
    context={"pid":pid,"session":truth["session"],"ledger":{v["id"]:v for v in records},"seen":set(),"truth":truth,"sources":sources,"report":report}
    checks=report.get("checks")
    require(type(checks) is list,"uint32 check matrix missing")
    labels={entry.get("label"):entry for entry in checks}
    require(len(labels)==len(checks) and "crop" in labels,"uint32 duplicate/missing checks")
    source=sources["CALIBRATED"][0]["id"];raw=sources["RAW_UNITS"][0]["id"]
    crop=decode(labels["crop"]).get("image_id")
    require(integer(crop,1) and crop not in (source,raw),"uint32 independent crop ID invalid")
    matrix=cases(source,raw,crop)
    require(set(labels)==set(matrix),"uint32 complete fixed check matrix required")
    status=bind(labels["status"],*matrix["status"][:4],context)
    status_contract(status,report["qualification_mode"],pid)
    context["threads"]=(status["native_receipt"]["exec_tid"],status["native_receipt"]["worker_tid"])
    outputs={"status":status}
    for label,(tool,arguments,op,args,failure) in matrix.items():
        if label!="status":outputs[label]=bind(labels[label],tool,arguments,op,args,context,failure)
    for label in ("pool_after_crop","pool_after_recovery"):
        status_contract(outputs[label],report["qualification_mode"],pid)
        require(integer(outputs[label].get("retained_result_count"),status.get("retained_result_count",-1)+1,status.get("retained_result_count",-1)+1),
                "uint32 repeated/conflicting CROP created an extra retained object")
    require(integer(status.get("retained_result_count"),0),"uint32 initial retained pool count invalid")
    previews=report.get("previews")
    require(type(previews) is list and len(previews)==2 and {v.get("label") for v in previews}=={"source","crop"},"uint32 complete preview matrix required")
    for entry in previews:
        image_id,bounds=(source,[128,128]) if entry["label"]=="source" else (crop,[2,1])
        outputs["preview_"+entry["label"]]=bind(entry,"dm_native_preview",{"image_id":image_id,"max_width":bounds[0],"max_height":bounds[1]},"PREVIEW",[image_id]+bounds,context)
    require(context["seen"]==set(context["ledger"]),"uint32 original requests/checks not one-to-one")
    recovery=report.get("recovery")
    saved=load_ledger(evidence,recovery_path,pid,truth["session"],True)
    require(type(recovery) is list and len(recovery)==len(saved)==4 and [v.get("kind") for v in recovery]==["fresh_query","repeat","conflict","query_after_conflict"],
            "uint32 immutable fresh-client QUERY/repeat/conflict matrix missing")
    original=labels["crop"];original_id=original["request"]["id"]
    for index,entry in enumerate(recovery):
        expected_op="CROP" if entry["kind"] in ("repeat","conflict") else "QUERY"
        expected_args=[source]+([0,0,2,2] if entry["kind"]=="conflict" else RECT) if expected_op=="CROP" else []
        require(entry.get("request")==saved[index] and saved[index]["id"]==original_id and saved[index]["op"]==expected_op and saved[index]["args"]==expected_args,
                "uint32 saved recovery original identity/arguments mismatch")
        require(entry.get("tool")== ("dm_crop" if expected_op=="CROP" else "dm_native_result") and
                entry.get("arguments")==({"image_id":source,"rect":expected_args[1:],"request_id":original_id} if expected_op=="CROP" else {"request_id":original_id}),
                "uint32 recovery MCP tool arguments mismatch")
        if entry["kind"]!="conflict":
            require(entry.get("response")==original["response"],"uint32 immutable QUERY/repeat changed original CROP receipt or output")
        else:
            receipt=decode(entry,failed=True).get("native_receipt",{})
            require(receipt.get("protocol")=="NB2" and receipt.get("session")==truth["session"] and receipt.get("id")==receipt.get("request_id")==original_id and
                    receipt.get("state")=="failed" and receipt.get("code")=="id_conflict" and
                    receipt.get("error")=="id is already bound to different operation parameters" and integer(receipt.get("host_pid"),pid,pid) and
                    integer(receipt.get("worker_tid"),context["threads"][1],context["threads"][1]) and integer(receipt.get("exec_tid"),0,0) and
                    receipt.get("original_operation")=="CROP" and receipt.get("normalized_args")==[source]+RECT and receipt.get("result_type")=="image_crop" and
                    integer(receipt.get("result_version"),1,1) and "result" not in receipt,"uint32 conflict was not the precise original-record refusal")
            timings=receipt.get("timings_us")
            require(type(timings) is dict and set(timings)=={"queue","execute"} and
                    all(integer(timings[key],0,2**53-1) for key in timings),"uint32 conflict receipt timings mismatch")
    context.update(outputs=outputs,crop_id=crop,source_id=source,raw_id=raw)
    return context


def check_preview(evidence,entry,output,observation,image_id,bounds):
    metadata(output.get("source"),image_id,observation)
    width,height,low,high,gray,coordinates,unused=reference_preview(observation["values"],*bounds)
    require(output.get("operation")=="PREVIEW" and output.get("image_id")==image_id and output.get("width")==width and output.get("height")==height and
            output.get("sample_count")==width*height and output.get("sampled_minimum")==low and output.get("sampled_maximum")==high and
            output.get("gray8_hex")==gray.hex() and output.get("mapping")==MAPPING and output.get("orientation")==ORIENTATION and output.get("sampling")==SAMPLING and
            output.get("range_source")=="sampled native point values" and output.get("constant_range_gray8")==0 and
            output.get("operator")=="GMS::Image::GetRealValue" and output.get("quantitative") is False and output.get("source_write_requested") is False and output.get("snapshot_atomic") is False,
            "uint32 PREVIEW raw high-bit range/mapping/gray8 mismatch")
    png=evidence.raw(entry["png"],2*1024*1024);block=entry["response"]["content"][1]
    require(sha(png)==entry.get("png_sha256") and block.get("type")=="image" and block.get("mimeType")=="image/png" and
            base64.b64decode(block["data"],validate=True)==png and decode_gray8_png(png)==(width,height,gray),"uint32 PNG bytes/CRC/axes/pixels mismatch")
    return {"label":entry["label"],"status":"PASS_DISPLAY_MAPPING_ONLY","png_sha256":sha(png),"coordinates_xy":coordinates,"model_viewing":"NOT_TESTED"}


def collect(report,truth_path,report_path,ledger_path,recovery_path):
    import numpy as np
    evidence=Evidence();context=load_context(evidence,truth_path,report_path,ledger_path,recovery_path,os.getpid())
    outputs=context["outputs"]
    crop_output=outputs["crop"]
    require(crop_output.get("source_image_id")==context["source_id"] and crop_output.get("requested_rect")==crop_output.get("effective_rect")==RECT and
            crop_output.get("operator")=="GMS::Image::GetSubSliceAsImage" and crop_output.get("source_write_requested") is False and crop_output.get("snapshot_atomic") is False,
            "uint32 CROP original source/ROI/operator mismatch")
    packages={}
    entries=context["report"].get("captures")
    require(type(entries) is list and len(entries)==2 and {v.get("label") for v in entries}=={"source","crop"},"uint32 source/crop NPY captures required")
    for entry in entries:packages[entry["label"]]=capture(evidence,entry,outputs["read_source" if entry["label"]=="source" else "read_crop"])
    external_result=external(evidence,context["report"]["external"],packages["crop"])
    for entry in context["report"]["previews"]:evidence.raw(entry["png"],2*1024*1024)
    import DigitalMicrograph as DM
    expected_docs=context["truth"]["initial_document_count"]
    require(integer(DM.CountImageDocumentsOfAllWorkspaces(),expected_docs,expected_docs),"uint32 document count changed")
    observations={}
    for label,(entry,values) in context["sources"].items():
        observation=observe(DM,np,entry["id"],[4,4],np.uint32,[other[0]["id"] for name,other in context["sources"].items() if name!=label])
        check_source(entry,values,observation)
        image=None
        try:
            image=DM.FindImageByID(entry["id"])
            require(integer(image.GetDataType(),11,11),"Independent source GetDataType disagrees with uint32 code11")
        finally:image=None
        observations[label]=observation
    source=observations["CALIBRATED"];crop=observe(DM,np,context["crop_id"],[2,3],np.uint32,[context["source_id"],context["raw_id"]])
    bit_equal(crop["values"],fixed_values()[1:3,1:4],"uint32 crop dtype/high bits or ROI axes differ")
    expected_cal=[dict(axis,raw_origin=axis["raw_origin"]-1,origin=axis["origin"]+axis["scale"]) for axis in source["calibration"]]
    require(crop["calibration"]==expected_cal and crop["intensity_calibration"]==source["intensity_calibration"],"uint32 crop spatial/intensity calibration not preserved")
    metadata(crop_output.get("source"),context["source_id"],source);metadata(crop_output.get("image"),context["crop_id"],crop)
    for label,image_id,observation,expected in (("calibrated",context["source_id"],source,SOURCE_STATS),("raw_units",context["raw_id"],observations["RAW_UNITS"],SOURCE_STATS),("crop",context["crop_id"],crop,CROP_STATS)):
        summary(outputs["mean_"+label],image_id,observation,expected,True);summary(outputs["summary_"+label],image_id,observation,expected)
    read(outputs["read_source"],context["source_id"],[0,0,4,4],source,None)
    read(outputs["read_raw_units"],context["raw_id"],[0,0,4,4],observations["RAW_UNITS"],None)
    provenance={"operation":"CROP","request_id":crop_output["native_receipt"]["id"],"source_image_ids":[context["source_id"]],"semantics":"independent native crop copy"}
    read(outputs["read_crop"],context["crop_id"],[0,0,3,2],crop,provenance)
    previews=[]
    for entry in context["report"]["previews"]:
        observation,image_id,bounds=(source,context["source_id"],[128,128]) if entry["label"]=="source" else (crop,context["crop_id"],[2,1])
        previews.append(check_preview(evidence,entry,outputs["preview_"+entry["label"]],observation,image_id,bounds))
    for label,(entry,values) in context["sources"].items():check_source(entry,values,observe(DM,np,entry["id"],[4,4],np.uint32))
    bit_equal(observe(DM,np,context["crop_id"],[2,3],np.uint32)["values"],crop["values"],"uint32 crop changed during oracle")
    require(integer(DM.CountImageDocumentsOfAllWorkspaces(),expected_docs,expected_docs),"uint32 document count changed during oracle")
    evidence.unchanged()
    report.update(status="PASS_BOUNDED_UINT32",host_pid=os.getpid(),session=context["session"],qualification_mode=context["report"]["qualification_mode"],
        truth_sha256=sha(evidence.raw(truth_path)),mcp_report_sha256=sha(evidence.raw(report_path)),ledger_sha256=sha(evidence.raw(ledger_path)),recovery_ledger_sha256=sha(evidence.raw(recovery_path)),
        source_protection="PASS",independent_memory="PASS",native_statistics="PASS_EXACT_INTEGER_FIXTURE",numeric_handoff="PASS_BITWISE_UINT32",crop_id=context["crop_id"],
        document_count=expected_docs,raw_views_and_wrappers_released=True,external_mean=external_result,previews=previews,immutable_query_repeat_conflict="PASS",
        sources=[{"label":label,"image_id":entry["id"],"pixel_sha256":entry["pixel_sha256"]} for label,(entry,unused) in context["sources"].items()],
        captures=[{"label":label,"files_sha256":package["hashes"]} for label,package in packages.items()],evidence_files_sha256={path:sha(raw) for path,raw in evidence.original.items()})


def paths():
    directory=os.environ["DM_NATIVE_EVIDENCE_DIR"]
    def filename(key,default):return os.environ.get("DM_NATIVE_UINT32_"+key,os.path.join(directory,default))
    return filename


def main():
    filename=paths()
    with open(filename("OUTPUT","uint32-independent.json"),"x",encoding="utf-8") as output:
        report={"schema":1,"status":"FAIL","kind":"synthetic-only","scope":"bounded exact uint32 synthetic/profile qualification",
            "dm_file_save":False,"snapshot_atomic":False,"model_viewing":"NOT_TESTED","lifecycle":"NOT_TESTED_BY_THIS_SCRIPT"}
        try:collect(report,filename("TRUTH","uint32-truth.json"),filename("REPORT","uint32-mcp-report.json"),filename("LEDGER","uint32-requests.jsonl"),filename("RECOVERY_LEDGER","uint32-recovery-requests.jsonl"))
        except BaseException as error:report.update(status="FAIL",error_type=type(error).__name__,error=str(error))
        json.dump(report,output,indent=2,ensure_ascii=True,allow_nan=False);output.write("\n");output.flush();os.fsync(output.fileno())
    print(report["status"]+": bounded uint32 synthetic only; no model/SaveAs/other-operator claim")
    return 0 if report["status"]=="PASS_BOUNDED_UINT32" else 1


if __name__=="__main__":raise SystemExit(main())
