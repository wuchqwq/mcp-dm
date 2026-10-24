# -*- coding: utf-8 -*-
"""One-shot NEW synthetic uint32 sources, manually run in the prepared host."""
import json
import os
import re

from create_summary_fixture import require, spatial, intensity
from uint32_acceptance import CODE, SOURCE_STATS, expected_axes, fixed_values, sha, bit_equal


def collect(report,directory):
    import numpy as np
    import DigitalMicrograph as DM
    before=DM.CountImageDocumentsOfAllWorkspaces()
    require(type(before) is int and before>=0,"Invalid original document count")
    report["document_count_before_fixture"]=before
    ids=set()
    for label,unit in (("CALIBRATED","nm"),("RAW_UNITS","")):
        image=document=view=None
        entry={"label":label};report["images"].append(entry)
        try:
            image=DM.CreateImage(fixed_values())
            require(image is not None and image.IsValid(),"CreateImage uint32 failed")
            image_id=image.GetID()
            require(type(image_id) is int and 0<image_id<0xffffffff and image_id not in ids,"Invalid new uint32 source ID")
            ids.add(image_id)
            name="NATIVE_UINT32_"+label+"_"+report["session"][:8]
            image.SetName(name)
            require(image.GetName()==name,"ASCII uint32 source name did not roundtrip")
            for axis,(zero,scale) in enumerate(((1.25,-.25),(-2.5,.5))):
                image.SetDimensionCalibration(axis,zero,scale,unit,0)
            image.SetIntensityOrigin(7.5);image.SetIntensityScale(-2.0);image.SetIntensityUnitString("arb")
            code=image.GetDataType()
            require(type(code) is int and code==CODE,"Python native uint32 GetDataType did not confirm code11")
            cal=[spatial(image,axis) for axis in (0,1)];cal_intensity=intensity(image)
            require(cal==expected_axes(unit) and cal_intensity=={"origin":7.5,"scale":-2.0,"unit":"arb"},"uint32 source calibration did not roundtrip")
            view=image.GetNumArray()
            require(type(view) is np.ndarray and view.dtype==np.dtype("<u4") and list(view.shape)==[4,4],"uint32 independent NumPy dtype/shape mismatch")
            bit_equal(view,fixed_values(),"uint32 fixture high-bit roundtrip changed values")
            values=np.array(view,order="C",copy=True);view=None
            filename=os.path.abspath(os.path.join(directory,"uint32_"+label.lower()+".npy"))
            with open(filename,"xb") as output:np.save(output,values,allow_pickle=False);output.flush();os.fsync(output.fileno())
            with open(filename,"rb") as source:original=source.read()
            entry.update(id=image_id,name=name,python_data_type_code=code,dtype="uint32",shape=[4,4],calibration=cal,
                         intensity_calibration=cal_intensity,source_npy=filename,source_file_sha256=sha(original),
                         pixel_sha256=sha(values.tobytes(order="C")),expected_summary=dict(SOURCE_STATS))
            document=image.GetOrCreateImageDocument()
            require(document is not None,"uint32 source document not created")
            document.Show()
        finally:
            view=document=image=None
    report["initial_document_count"]=DM.CountImageDocumentsOfAllWorkspaces()
    require(report["initial_document_count"]==before+2,"uint32 fixture document count mismatch")


def main():
    directory=os.environ["DM_NATIVE_EVIDENCE_DIR"]
    target=os.environ.get("DM_NATIVE_UINT32_TRUTH",os.path.join(directory,"uint32-truth.json"))
    with open(target,"x",encoding="utf-8") as output:
        report={"schema":1,"status":"FAIL","kind":"synthetic-only","python_is_listener":False,
                "host_pid":os.getpid(),"session":os.environ.get("DM_NATIVE_SESSION"),"images":[],"native_qualification":"NOT_TESTED"}
        try:
            require(type(report["session"]) is str and re.fullmatch(r"[a-f0-9]{32}",report["session"]),"Explicit uint32 session required")
            collect(report,directory);report["status"]="RECORDED"
        except BaseException as error:report.update(error_type=type(error).__name__,error=str(error))
        json.dump(report,output,indent=2,ensure_ascii=True,allow_nan=False);output.write("\n");output.flush();os.fsync(output.fileno())
    print("uint32 synthetic fixture "+report["status"]+"; native qualification NOT_TESTED")
    return 0 if report["status"]=="RECORDED" else 1


if __name__=="__main__":raise SystemExit(main())
