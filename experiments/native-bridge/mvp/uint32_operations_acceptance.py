# -*- coding: utf-8 -*-
"""Fixed production uint32 synthetic acceptance plan; no DM/runtime imports."""
from create_summary_fixture import require
from uint32_operations_probe import arrays as prepared_arrays, record, integer, sha, bit_equal
from verify_handoff import Evidence, bounded_npy

CAPABILITIES=("native_uint32_display","native_uint32_image_arithmetic","native_uint32_filters","native_uint32_fft")
READ_TARGETS={"filter":("filter-FILTER_EXTREME-4",[1,2,5,6]),"arithmetic":("binary-HIGH-1",[0,0,4,4])}
SHOW_TARGETS=("crop-HIGH","filter-FILTER_EXTREME-4")
READ_PROVENANCE={
    "filter":"DM native uint32 filter; binary64 kernel accumulation; saturated and truncated uint32 storage; bridge performs no pixel cast",
    "arithmetic":"DM native uint32 inputs; binary64 native arithmetic then binary32 result; not lossless for arbitrary uint32 inputs; bridge performs no pixel cast"}
HIGH_FFT_POLICY={"fixture":"new production HIGH literal; 4x4 only","input_conversion":"DM uint32 to binary32 round before Fourier",
    "reference":"positive-exponent centered quarter-root DFT of rounded input; binary32 complex store",
    "threshold_factor":32*2**-24,"scale":"L1 norm of rounded real input",
    "scope":"predeclared empirical acceptance threshold; not a theoretical error bound or arbitrary-image guarantee"}


def arrays():
    import numpy as np
    result=prepared_arrays()
    # A NEW literal, not the old prepared HIGH evidence. Register the Fourier
    # acceptance policy above before this production fixture is ever created.
    result["HIGH"]=np.array([[4294967295,0,16777217,1],[2147483648,16777216,4294967294,16777215],
        [11,2147483647,65537,123456789],[4000000001,3,100000001,29]],dtype=np.uint32)
    result["RHS"]=np.array([[1,2,1,3],[1,0,3,1],[0,3,1,2],[3,1,2,0]],dtype=np.uint32)
    choices=(0,4294967295,1,4294967294,16777217)
    result["FILTER_EXTREME"]=np.array([[choices[(3*x+2*y+x*y)%5] for x in range(8)] for y in range(8)],dtype=np.uint32)
    result["BOUNDARY256"]=np.full((256,256),16777217,dtype=np.uint32)
    return result


def plan():
    # Boundary calls run while the result pool is empty; native temporary-slot
    # admission must not be accidentally tested only after the pool is full.
    result=[{"label":"fft-BOUNDARY256","op":"FFT","sources":["BOUNDARY256"]},
            {"label":"filter-BOUNDARY256-4","op":"FILTER","sources":["BOUNDARY256"],"opcode":4}]
    for label in ("LOW","HIGH"):
        result.extend({"label":"unary-"+label+"-"+str(code),"op":"UNARY","sources":[label],"opcode":code} for code in (1,2,3))
        result.extend({"label":"binary-"+label+"-"+str(code),"op":"BINARY","sources":[label,"RHS"],"opcode":code} for code in (1,2,3))
    for label in ("FILTER_LOW","FILTER_HIGH","FILTER_EXTREME"):
        result.extend({"label":"filter-"+label+"-"+str(code),"op":"FILTER","sources":[label],"opcode":code} for code in (1,2,3,4))
    result.extend({"label":"fft-"+label,"op":"FFT","sources":[label]} for label in ("LOW","HIGH","FFT_IMPULSE"))
    result.extend(({"label":"ifft-LOW","op":"IFFT","parent":"fft-LOW"},
                   {"label":"inverse-real-LOW","op":"REAL","parent":"ifft-LOW"},
                   {"label":"crop-HIGH","op":"CROP","sources":["HIGH"],"rect":[1,1,4,3]}))
    require(len(result)==32,"Fixed production uint32 32-output matrix mismatch")
    return result


def specification(item,sources,outputs):
    op=item["op"]
    ids=[outputs[item["parent"]]] if "parent" in item else [sources[name][0]["id"] for name in item["sources"]]
    if op=="UNARY":return "dm_native_unary",{"image_id":ids[0],"operation":{1:"negate",2:"abs",3:"square"}[item["opcode"]]},op,ids+[item["opcode"]]
    if op=="BINARY":return "dm_native_binary",{"left_image_id":ids[0],"right_image_id":ids[1],"operation":{1:"add",2:"subtract",3:"multiply"}[item["opcode"]]},op,ids+[item["opcode"]]
    if op=="FILTER":return "dm_native_filter",{"image_id":ids[0],"operation":{1:"smooth",2:"sobel",3:"laplace",4:"sharpen"}[item["opcode"]]},op,ids+[item["opcode"]]
    if op in ("FFT","IFFT"):return "dm_native_fft",{"image_id":ids[0],"direction":"forward" if op=="FFT" else "inverse"},op,ids
    if op=="REAL":return "dm_native_complex",{"image_id":ids[0],"component":"real"},op,ids
    require(op=="CROP","Unknown fixed production operation")
    return "dm_crop",{"image_id":ids[0],"rect":item["rect"]},op,ids+item["rect"]


def load_truth(evidence,filename,actual_pid):
    import re
    truth=evidence.json(filename);expected=arrays();images=truth.get("images")
    require(truth.get("schema")==1 and truth.get("status")=="RECORDED" and truth.get("kind")=="synthetic-only" and
            truth.get("fixture")=="uint32-production-operations-v1" and truth.get("python_is_listener") is False and
            integer(truth.get("host_pid"),actual_pid,actual_pid) and type(truth.get("session")) is str and re.fullmatch(r"[a-f0-9]{32}",truth["session"]),
            "Production uint32 fixed fixture actual PID/session mismatch")
    require(type(images) is list and len(images)==9 and {entry.get("label") for entry in images}==set(expected),"Complete fixed 9-source fixture required")
    sources={};ids=set()
    for entry in images:
        label=entry["label"];values=expected[label]
        require(integer(entry.get("id"),1,0xfffffffe) and entry["id"] not in ids and entry.get("dtype")=="uint32" and entry.get("shape")==list(values.shape) and
                integer(entry.get("python_data_type_code"),11,11),"Production uint32 source identity/type/shape mismatch")
        raw=evidence.raw(entry["source_npy"],1024*1024);saved=bounded_npy(raw,list(values.shape),"<u4")
        bit_equal(saved,values,"Predetermined production uint32 original source pixels differ")
        require(sha(raw)==entry.get("source_file_sha256") and sha(saved.tobytes(order="C"))==entry.get("pixel_sha256") and
                type(entry.get("name")) is str and entry["name"].isascii() and bool(entry["name"]) and
                entry.get("calibration")==[{"dm_axis":0,"origin":1.25,"raw_origin":5.,"scale":-.25,"unit":"nm"},
                    {"dm_axis":1,"origin":-2.5,"raw_origin":5.,"scale":.5,"unit":"nm"}] and
                entry.get("intensity_calibration")=={"origin":7.5,"scale":-2.,"unit":"arb"},"Production source file/hash/name/signed/intensity calibration mismatch")
        sources[label]=(entry,saved);ids.add(entry["id"])
    require(integer(truth.get("document_count_before_fixture"),0) and integer(truth.get("initial_document_count"),truth["document_count_before_fixture"]+9,truth["document_count_before_fixture"]+9),
            "Production source document count mismatch")
    return truth,sources


def status_contract(output,pid,mode="production"):
    require(mode=="production" and output.get("backend")=="digitalmicrograph-native" and output.get("ready") is True and output.get("binary_gate") is True and
            integer(output.get("host_pid"),pid,pid) and output.get("host_thread")==output.get("native_receipt",{}).get("exec_tid") and
            output.get("adapter_profile")=="gms-3.53.4137.0-windows-x64" and output.get("compatibility",{}).get("state")=="SUPPORTED" and
            not any(key.startswith("prepared_") or key.startswith("candidate_") for key in output),"Production profile/status/candidate gate mismatch")
    caps=output.get("native_capabilities")
    require(type(caps) is list,"Production uint32 capabilities absent")
    for name in CAPABILITIES:
        matches=[entry for entry in caps if entry.get("name")==name]
        require(len(matches)==1 and matches[0].get("available") is True and matches[0].get("qualification")=="LIMITED_REAL_HOST", "Production uint32 subgroup unavailable/unqualified: "+name)
