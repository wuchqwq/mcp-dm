# -*- coding: utf-8 -*-
"""Explicit NEW uint32 operator-probe fixtures. No scientific qualification."""
import json
import os
import re

from create_summary_fixture import require, spatial, intensity
from uint32_operations_probe import arrays, bit_equal, sha


def collect(report,directory):
    import numpy as np
    import DigitalMicrograph as DM
    before=DM.CountImageDocumentsOfAllWorkspaces()
    require(type(before) is int and before>=0,"Invalid original document count")
    report["document_count_before_fixture"]=before
    ids=set()
    for label,values in arrays().items():
        image=document=view=None;entry={"label":label};report["images"].append(entry)
        try:
            image=DM.CreateImage(np.array(values,order="C",copy=True))
            require(image is not None and image.IsValid(),"CreateImage uint32 probe failed")
            image_id=image.GetID();require(type(image_id) is int and 0<image_id<0xffffffff and image_id not in ids,"Invalid uint32 probe source ID")
            ids.add(image_id);name="NATIVE_U32_OPS_"+label+"_"+report["session"][:8];image.SetName(name)
            require(image.GetName()==name,"Probe source ASCII name mismatch")
            for axis,(zero,scale) in enumerate(((1.25,-.25),(-2.5,.5))):image.SetDimensionCalibration(axis,zero,scale,"nm",0)
            image.SetIntensityOrigin(7.5);image.SetIntensityScale(-2.0);image.SetIntensityUnitString("arb")
            code=image.GetDataType();require(type(code) is int and code==11,"Probe source is not native uint32 code11")
            view=image.GetNumArray();require(type(view) is np.ndarray,"Probe raw GetNumArray did not return ndarray")
            bit_equal(view,values,"Probe fixed uint32 high bits/dtype/shape did not roundtrip")
            detached=np.array(view,order="C",copy=True);view=None
            filename=os.path.abspath(os.path.join(directory,"u32_ops_"+label.lower()+".npy"))
            with open(filename,"xb") as output:np.save(output,detached,allow_pickle=False);output.flush();os.fsync(output.fileno())
            with open(filename,"rb") as source:raw=source.read()
            entry.update(id=image_id,name=name,dtype="uint32",shape=list(values.shape),python_data_type_code=code,source_npy=filename,
                source_file_sha256=sha(raw),pixel_sha256=sha(detached.tobytes(order="C")),calibration=[spatial(image,d) for d in (0,1)],intensity_calibration=intensity(image))
            require(entry["calibration"]==[{"dm_axis":0,"origin":1.25,"raw_origin":5.,"scale":-.25,"unit":"nm"},
                {"dm_axis":1,"origin":-2.5,"raw_origin":5.,"scale":.5,"unit":"nm"}] and entry["intensity_calibration"]=={"origin":7.5,"scale":-2.,"unit":"arb"},"Probe signed/intensity calibration mismatch")
            document=image.GetOrCreateImageDocument();require(document is not None,"Probe source document missing");document.Show()
        finally:view=document=image=None
    report["initial_document_count"]=DM.CountImageDocumentsOfAllWorkspaces()
    require(report["initial_document_count"]==before+7,"Probe source document count mismatch")


def main():
    directory=os.environ["DM_NATIVE_EVIDENCE_DIR"]
    target=os.environ.get("DM_NATIVE_U32_OPS_TRUTH",os.path.join(directory,"uint32-operations-truth.json"))
    with open(target,"x",encoding="utf-8") as output:
        report={"schema":1,"status":"FAIL","kind":"synthetic-only","python_is_listener":False,"host_pid":os.getpid(),
                "session":os.environ.get("DM_NATIVE_SESSION"),"images":[],"numerical_qualification":"NOT_QUALIFIED"}
        try:
            require(type(report["session"]) is str and re.fullmatch(r"[a-f0-9]{32}",report["session"]),"Explicit prepared session required")
            collect(report,directory);report["status"]="RECORDED"
        except BaseException as error:report.update(error_type=type(error).__name__,error=str(error))
        json.dump(report,output,indent=2,ensure_ascii=True,allow_nan=False);output.write("\n");output.flush();os.fsync(output.fileno())
    print(report["status"]+": NEW uint32 operator-probe source fixture only; science NOT_QUALIFIED")
    return 0 if report["status"]=="RECORDED" else 1


if __name__=="__main__":raise SystemExit(main())
