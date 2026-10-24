# -*- coding: utf-8 -*-
"""Create only nine NEW synthetic uint32 production-acceptance source images."""
import json
import os
import re

from create_summary_fixture import require,spatial,intensity
from uint32_operations_acceptance import arrays,bit_equal,sha


def collect(report,directory):
    import numpy as np
    import DigitalMicrograph as DM
    before=DM.CountImageDocumentsOfAllWorkspaces()
    require(type(before) is int and before>=0,"Original document count invalid")
    report["document_count_before_fixture"]=before;ids=set()
    for label,values in arrays().items():
        image=document=view=None;entry={"label":label};report["images"].append(entry)
        try:
            image=DM.CreateImage(np.array(values,order="C",copy=True))
            require(image is not None and image.IsValid(),"Production uint32 CreateImage failed")
            image_id=image.GetID();require(type(image_id) is int and 0<image_id<0xffffffff and image_id not in ids,"Production source identity invalid")
            ids.add(image_id);name="NATIVE_U32_PROD_"+label+"_"+report["session"][:8];image.SetName(name)
            for axis,(zero,scale) in enumerate(((1.25,-.25),(-2.5,.5))):image.SetDimensionCalibration(axis,zero,scale,"nm",0)
            image.SetIntensityOrigin(7.5);image.SetIntensityScale(-2.);image.SetIntensityUnitString("arb")
            require(image.GetName()==name and type(image.GetDataType()) is int and image.GetDataType()==11,"Production source name/type code mismatch")
            view=image.GetNumArray();require(type(view) is np.ndarray,"Production source raw array absent")
            bit_equal(view,values,"Production original uint32 full pixels/dtype/shape did not roundtrip")
            detached=np.array(view,order="C",copy=True);view=None
            filename=os.path.abspath(os.path.join(directory,"u32_prod_"+label.lower()+".npy"))
            with open(filename,"xb") as output:np.save(output,detached,allow_pickle=False);output.flush();os.fsync(output.fileno())
            with open(filename,"rb") as source:raw=source.read()
            entry.update(id=image_id,name=name,dtype="uint32",shape=list(values.shape),python_data_type_code=11,source_npy=filename,
                         source_file_sha256=sha(raw),pixel_sha256=sha(detached.tobytes(order="C")),calibration=[spatial(image,axis) for axis in (0,1)],intensity_calibration=intensity(image))
            require(entry["calibration"]==[{"dm_axis":0,"origin":1.25,"raw_origin":5.,"scale":-.25,"unit":"nm"},
                {"dm_axis":1,"origin":-2.5,"raw_origin":5.,"scale":.5,"unit":"nm"}] and entry["intensity_calibration"]=={"origin":7.5,"scale":-2.,"unit":"arb"},
                "Production source signed/intensity calibration mismatch")
            document=image.GetOrCreateImageDocument();require(document is not None,"Production source document absent");document.Show()
        finally:view=document=image=None
    report["initial_document_count"]=DM.CountImageDocumentsOfAllWorkspaces()
    require(report["initial_document_count"]==before+9,"Production source document count mismatch")


def main():
    directory=os.environ["DM_NATIVE_EVIDENCE_DIR"]
    filename=os.environ.get("DM_NATIVE_U32_PROD_TRUTH",os.path.join(directory,"uint32-production-truth.json"))
    with open(filename,"x",encoding="utf-8") as output:
        report={"schema":1,"status":"FAIL","kind":"synthetic-only","fixture":"uint32-production-operations-v1","python_is_listener":False,
                "host_pid":os.getpid(),"session":os.environ.get("DM_NATIVE_SESSION"),"images":[]}
        try:
            require(type(report["session"]) is str and re.fullmatch(r"[a-f0-9]{32}",report["session"]),"Explicit new production session required")
            collect(report,directory);report["status"]="RECORDED"
        except BaseException as error:report.update(error_type=type(error).__name__,error=str(error))
        json.dump(report,output,indent=2,ensure_ascii=True,allow_nan=False);output.write("\n");output.flush();os.fsync(output.fileno())
    print(report["status"]+": nine NEW uint32 synthetic sources only")
    return 0 if report["status"]=="RECORDED" else 1


if __name__=="__main__":raise SystemExit(main())
