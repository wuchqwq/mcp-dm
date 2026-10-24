# -*- coding: utf-8 -*-
"""Offline fixed-reference checks over original prepared uint32 snapshots.

This acceptance-only tool imports neither DM nor the native runtime. Arithmetic
uses the statically reviewed native double operation followed by float32 store.
No rule is selected by matching observed output. High-dynamic-range Fourier
rounding remains explicitly unqualified until its conversion contract closes.
"""
import argparse
import json
import math
import os

from create_summary_fixture import require
from observe_uint32_operations import bind_metadata, load_context as probe_context
from uint32_operations_probe import Evidence, bit_equal, bounded_npy, integer, sha
from verify_operations_math import quarter_turn_dft


def filter_reference(values,opcode):
    import numpy as np
    require(type(values) is np.ndarray and values.dtype==np.uint32 and values.shape==(8,8) and opcode in (1,2,3,4),
            "Fixed uint32 FILTER reference requires the original 8x8 fixture")
    kernels={1:((1/16.,2/16.,1/16.),(2/16.,4/16.,2/16.),(1/16.,2/16.,1/16.)),
             3:((-1,-1,-1),(-1,8,-1),(-1,-1,-1)),4:((-1,-1,-1),(-1,9,-1),(-1,-1,-1))}
    gx=((1,0,-1),(2,0,-2),(1,0,-1));gy=((1,2,1),(0,0,0),(-1,-2,-1))
    result=values.copy() if opcode in (1,4) else np.zeros(values.shape,dtype=np.float32)
    def dot(y,x,kernel):
        # Every fixed-fixture product/sum is an exact binary64 integer or
        # multiple of 1/16, far below 2^53. Thus addition order is immaterial.
        return math.fsum(float(values[y+dy-1,x+dx-1])*kernel[dy][dx] for dy in range(3) for dx in range(3))
    for y in range(1,7):
        for x in range(1,7):
            if opcode==2:
                a,b=np.float32(dot(y,x,gx)),np.float32(dot(y,x,gy))
                squared=np.float32(np.float32(a*a)+np.float32(b*b))
                result[y,x]=np.float32(math.sqrt(float(squared)))
            else:
                value=dot(y,x,kernels[opcode])
                result[y,x]=int(min(4294967295.,max(0.,value))) if opcode in (1,4) else np.float32(value)
    return result


def arithmetic_reference(op,args,values):
    import numpy as np
    left=values[0].astype(np.float64)
    if op=="UNARY":result=-left if args[-1]==1 else np.abs(left) if args[-1]==2 else left*left
    else:
        right=values[1].astype(np.float64)
        result=left+right if args[-1]==1 else left-right if args[-1]==2 else left*right
    return result.astype(np.float32)


def frequency_calibration(source,shape,inverse=False):
    axes=[]
    for axis in source["calibration"]:
        dim=axis["dm_axis"];length=shape[1-dim]
        scale=axis["scale"] if inverse else 1./(length*axis["scale"])
        raw=0. if inverse else (length+1)/2.
        axes.append({"dm_axis":dim,"origin":-raw*scale,"raw_origin":raw,"scale":scale,"unit":"nm" if inverse else "1/nm"})
    return axes


def load_context(truth_path,probe_path,ledger_path,observation_path):
    evidence=Evidence();truth=evidence.json(truth_path)
    require(integer(truth.get("host_pid"),1),"Original host PID missing")
    context=probe_context(evidence,truth_path,probe_path,ledger_path,truth["host_pid"])
    observation=evidence.json(observation_path)
    require(observation.get("status")=="RECORDED_UNQUALIFIED" and integer(observation.get("host_pid"),truth["host_pid"],truth["host_pid"]) and
            observation.get("session")==context["session"] and observation.get("truth_sha256")==sha(evidence.raw(truth_path)) and
            observation.get("probe_sha256")==sha(evidence.raw(probe_path)) and observation.get("ledger_sha256")==sha(evidence.raw(ledger_path)) and
            observation.get("source_protection")=="PASS_OBSERVED_SAME_HOST" and observation.get("independent_memory")=="PASS_OBSERVED_RAW_VIEWS" and
            observation.get("raw_views_and_wrappers_released") is True and observation.get("control_crop_verified") is True and
            observation.get("numerical_qualification")=="NOT_QUALIFIED" and observation.get("scientific_operator_pass") is False,
            "Original same-host observation evidence/hash/flags mismatch")
    entries=observation.get("outputs")
    require(type(entries) is list and len(entries)==31 and observation.get("output_count")==31 and len(context["outputs"])==31,
            "Exact complete fixed 31-output matrix required")
    values={};observations={}
    for entry in entries:
        image_id=entry.get("image_id")
        require(integer(image_id,1) and image_id not in values and image_id in context["outputs"],"Independent numerical output identity mismatch")
        original=context["outputs"][image_id];request=original["request"]
        require(entry.get("label")==original["label"] and entry.get("request_id")==request["id"] and entry.get("operation")==request["op"] and
                entry.get("args")==request["args"] and entry.get("status")=="OBSERVED_UNQUALIFIED" and
                entry.get("dtype") in ("float32","uint32","complex64"),"Independent numerical output request/label/dtype mismatch")
        raw=evidence.raw(entry["snapshot"],8192)
        actual=bounded_npy(raw,entry["shape"],{"float32":"<f4","uint32":"<u4","complex64":"<c8"}[entry["dtype"]])
        require(sha(raw)==entry.get("snapshot_file_sha256") and sha(actual.tobytes(order="C"))==entry.get("pixel_sha256"),"Independent NPY/file/pixel hash mismatch")
        bind_metadata(original["result"]["image"],image_id,dict(entry,values=actual))
        values[image_id]=actual;observations[image_id]=entry
    context.update(evidence=evidence,values=values,observations=observations,bound_hashes={"truth_sha256":sha(evidence.raw(truth_path)),
        "probe_sha256":sha(evidence.raw(probe_path)),"ledger_sha256":sha(evidence.raw(ledger_path)),"observation_sha256":sha(evidence.raw(observation_path))})
    return context


def verify(report,context):
    import numpy as np
    report.update(context["bound_hashes"])
    report.update(host_pid=context["truth"]["host_pid"],session=context["session"],outputs=[])
    for image_id,entry in context["outputs"].items():
        request=entry["request"];op=request["op"];args=request["args"];plan=entry["plan"];label=entry["label"]
        actual=context["values"][image_id];observed=context["observations"][image_id]
        record={"label":label,"image_id":image_id,"request_id":request["id"],"operation":op,"args":args,
                "snapshot_file_sha256":observed["snapshot_file_sha256"],"pixel_sha256":observed["pixel_sha256"]}
        reference=None;expected_cal=None;expected_intensity=None
        if op in ("UNARY","BINARY","FILTER","CROP"):
            sources=[context["sources"][value] for value in plan["sources"]]
            source=sources[0][0]
            if op in ("UNARY","BINARY"):
                reference=arithmetic_reference(op,args,[value[1] for value in sources]);record["reference"]="uint32 exact load to binary64; native double operation; binary32 store"
            elif op=="FILTER":
                reference=filter_reference(sources[0][1],args[-1]);record["reference"]="fixed native 3x3 double kernel; documented edge and dtype-specific store"
            else:
                reference=sources[0][1][1:3,1:4];record["reference"]="exact independent uint32 half-open crop"
            expected_cal=source["calibration"]
            if op=="CROP":expected_cal=[dict(axis,raw_origin=axis["raw_origin"]-1,origin=axis["origin"]+axis["scale"]) for axis in expected_cal]
            expected_intensity=source["intensity_calibration"]
            bit_equal(actual,reference,"Fixed "+label+" native dtype/values/axes/signed-zero differ")
        elif label in ("fft-LOW","fft-FFT_CONSTANT","fft-FFT_IMPULSE","ifft-LOW","inverse-real-LOW"):
            source_label="FFT_CONSTANT" if label=="fft-FFT_CONSTANT" else "FFT_IMPULSE" if label=="fft-FFT_IMPULSE" else "LOW"
            source,saved=context["sources"][source_label]
            inverse=op!="FFT"
            reference=(saved.astype(np.complex64) if inverse else quarter_turn_dft(saved.astype(np.float32)))
            if op=="REAL":reference=reference.real.copy()
            require(actual.dtype==reference.dtype and actual.shape==reference.shape and np.isfinite(actual).all() and np.array_equal(actual,reference),
                    "Fixed exact-root low-range Fourier dtype/values/axes differ: "+label)
            expected_cal=frequency_calibration(source,saved.shape,inverse)
            expected_intensity={"origin":0.,"scale":1.,"unit":""}
            record["reference"]="DM uint32-to-binary32 input conversion; fixed positive-exponent centered exact-root DFT; normalized negative inverse"
        else:
            record.update(status="NOT_QUALIFIED",reason="high-dynamic-range uint32 Fourier conversion and rounding contract not qualified")
        if reference is not None:
            require(observed["calibration"]==expected_cal and observed["intensity_calibration"]==expected_intensity,
                    "Fixed "+label+" spatial/intensity calibration differs")
            record.update(status="PASS_BOUNDED_SYNTHETIC_NUMERICAL",reference_pixel_sha256=sha(reference.tobytes(order="C")))
        report["outputs"].append(record)
    context["evidence"].unchanged()
    passed=[entry["label"] for entry in report["outputs"] if entry["status"]=="PASS_BOUNDED_SYNTHETIC_NUMERICAL"]
    pending=[entry["label"] for entry in report["outputs"] if entry["status"]=="NOT_QUALIFIED"]
    require(len(passed)==26 and len(pending)==5,"Unexpected bounded numerical qualification matrix")
    report.update(status="PASS_BOUNDED_PARTIAL_UINT32_NUMERICAL",qualified_labels=passed,unqualified_labels=pending,
                  qualified_count=len(passed),unqualified_count=len(pending),source_protection="BOUND_TO_SAME_HOST_OBSERVATION",
                  production_qualification=False,lifecycle="NOT_TESTED_BY_THIS_SCRIPT",model_viewing="NOT_TESTED")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("truth","probe","ledger","observation","output"):parser.add_argument("--"+name,required=True)
    args=parser.parse_args()
    with open(args.output,"x",encoding="utf-8") as output:
        report={"schema":1,"status":"FAIL","kind":"synthetic-only","outputs":[]}
        try:verify(report,load_context(args.truth,args.probe,args.ledger,args.observation))
        except BaseException as error:report.update(status="FAIL",error_type=type(error).__name__,error=str(error))
        json.dump(report,output,indent=2,ensure_ascii=True,allow_nan=False);output.write("\n");output.flush();os.fsync(output.fileno())
    print(report["status"])
    return 0 if report["status"]=="PASS_BOUNDED_PARTIAL_UINT32_NUMERICAL" else 1


if __name__=="__main__":raise SystemExit(main())
