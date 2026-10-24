# -*- coding: utf-8 -*-
"""Synthetic callbacks plus real offline NPY encoder; no native pipe or DM."""
import base64
import copy
import gc
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import types
import unittest
import weakref
from unittest import mock

import numpy as np

from test_native_uint32_oracles import Synthetic as PriorSynthetic
from test_native_uint32_operations_probe import MVP,SESSION,calibration,save

with mock.patch.object(sys,"path",[str(MVP)]+sys.path):
    S=runpy.run_path(str(MVP/"uint32_operations_acceptance.py"))
    C=runpy.run_path(str(MVP/"accept_uint32_operations_mcp.py"))
    O=runpy.run_path(str(MVP/"verify_uint32_operations.py"))
    F=runpy.run_path(str(MVP/"create_uint32_production_fixture.py"))


class SyntheticProduction(PriorSynthetic):
    def __init__(self,directory):
        self.directory=Path(directory);self.images={};self.saved={};self.clients=0;self.refs=[];self.views=[];self.docs=9;self.created=0;self.producer_ops=[]
        self.truth={"schema":1,"kind":"synthetic-only","status":"RECORDED","fixture":"uint32-production-operations-v1","python_is_listener":False,
                    "host_pid":os.getpid(),"session":SESSION,"document_count_before_fixture":0,"initial_document_count":9,"images":[]}
        for image_id,(label,values) in enumerate(S["arrays"]().items(),101):
            data={"values":values.copy(),"name":"synthetic-prod-"+label,"calibration":calibration(),"intensity_calibration":{"origin":7.5,"scale":-2.,"unit":"arb"},"code":11}
            self.images[image_id]=data;filename=self.directory/(label+".npy");np.save(str(filename),values,allow_pickle=False)
            self.truth["images"].append({"id":image_id,"label":label,"name":data["name"],"dtype":"uint32","shape":list(values.shape),"python_data_type_code":11,
                "source_npy":str(filename),"source_file_sha256":S["sha"](filename.read_bytes()),"pixel_sha256":S["sha"](values.tobytes()),
                "calibration":data["calibration"],"intensity_calibration":data["intensity_calibration"]})
        self.truth_path=self.directory/"uint32-production-truth.json";save(self.truth_path,self.truth);self.attempt=self.directory/"attempt"

    def metadata(self,image_id):
        data=self.images[image_id];shape=list(data["values"].shape);axes=data["calibration"];code=data["code"]
        value={"id":image_id,"name":data["name"],"dtype":{2:"float32",3:"complex64",11:"uint32"}[code],"data_type_code":code,"packing_style":1,
               "ndim":2,"shape":shape,"dm_dimensions":shape[::-1],"pixels":int(data["values"].size),"shape_order":"numpy (last axis is X)",
               "coordinate_rule":"physical(i)=calibrated_value_at_pixel_zero+i*scale","native_mean_supported":code!=3,"native_summary_supported":code!=3,
               "calibration_complete":True,"calibration":[{"dm_dimension":axis["dm_axis"],"numpy_axis":1-axis["dm_axis"],"size":shape[1-axis["dm_axis"]],
                    "origin":axis["raw_origin"],"calibrated_value_at_pixel_zero":axis["origin"],"scale":axis["scale"],"unit":axis["unit"],"usable":True,"issue":None} for axis in axes]}
        if code==11:value.update(is_integer=True,is_unsigned=True)
        return value

    def receipt(self,request_id,op,args):
        return {"protocol":"NB2","session":SESSION,"id":request_id,"request_id":request_id,"state":"completed","host_pid":os.getpid(),"exec_tid":100,"worker_tid":200,
                "timings_us":{"queue":0,"execute":0},"original_operation":op,"normalized_args":args,"result_type":"native_data_snapshot" if op=="READ" else O["RESULT_TYPES"][op],
                "result_version":2 if op in ("FFT","IFFT","REAL") else 1}

    def response(self,tool,params):
        request_id=params["request_id"]
        if tool=="dm_native_result":return copy.deepcopy(self.saved[request_id][2])
        if tool=="dm_status":op,args="STATUS",[]
        elif tool=="dm_native_read":op,args="READ",[params["image_id"]]+params["rect"]
        else:
            item=S["plan"]()[self.created];sources={entry["label"]:(entry,None) for entry in self.truth["images"]}
            expected_tool,expected_params,op,args=S["specification"](item,sources,self.label_ids)
            if tool!=expected_tool or {k:v for k,v in params.items() if k!="request_id"}!=expected_params:raise AssertionError("synthetic client invocation differs from fixed plan")
        out={"backend":"digitalmicrograph-native"}
        if op=="STATUS":
            out.update(ready=True,binary_gate=True,host_pid=os.getpid(),host_thread=100,adapter_profile="gms-3.53.4137.0-windows-x64",compatibility={"state":"SUPPORTED"},
                retained_result_count=self.created,retained_result_bytes=sum(data["values"].nbytes for image_id,data in self.images.items() if image_id>=1000),
                native_capabilities=[{"name":name,"available":True,"qualification":"LIMITED_REAL_HOST"} for name in S["CAPABILITIES"]])
        elif op=="READ":
            image_id,x0,y0,x1,y1=args;meta=self.metadata(image_id);values=self.images[image_id]["values"][y0:y1,x0:x1];rect=args[1:];axes=[]
            for axis in meta["calibration"]:
                dim=axis["dm_dimension"];offset=rect[dim]
                axes.append({"dm_dimension":dim,"numpy_axis":1-dim,"size":values.shape[1-dim],"source_offset":offset,"source_origin":axis["origin"],
                    "source_calibrated_value_at_pixel_zero":axis["calibrated_value_at_pixel_zero"],"origin":axis["origin"]-offset,
                    "calibrated_value_at_pixel_zero":axis["calibrated_value_at_pixel_zero"]+offset*axis["scale"],"scale":axis["scale"],"unit":axis["unit"],"usable":True,"issue":None})
            label="filter" if values.dtype==np.uint32 else "arithmetic";creation=self.creation[image_id]
            provenance={"operation":creation[0],"request_id":creation[2],"source_image_ids":creation[1][:2] if creation[0]=="BINARY" else creation[1][:1],"semantics":S["READ_PROVENANCE"][label]}
            out.update(operation="READ",source_image_id=image_id,source=meta,requested_rect=rect,effective_rect=rect,shape=list(values.shape),dtype=str(values.dtype),byte_order="little",axes=["y","x"],array_order="C",
                data_encoding="base64",values_base64=base64.b64encode(values.tobytes()).decode(),sample_count=int(values.size),raw_bytes=values.nbytes,roi_calibration=axes,calibration_complete=True,
                coordinate_mapping_policy="logical ROI only; source_x=x0+roi_x; source_y=y0+roi_y; source unchanged",source_provenance=provenance,source_provenance_scope="immutable creation record only; source image remains mutable",
                operator="GMS::Image::GetRealValue",computation="DM native point reads; data handoff only",intensity_calibration_applied=False,intensity_semantics="raw pixel intensity",ownership="response-owned numeric snapshot; no native result image",
                source_write_requested=False,snapshot_atomic=False)
        else:
            self.producer_ops.append((op,args));item=S["plan"]()[self.created];source=self.images[args[0]];label=item["label"]
            if op in ("UNARY","BINARY"):values=O["arithmetic_reference"](op,args,[self.images[i]["values"] for i in (args[:2] if op=="BINARY" else args[:1])])
            elif op=="FILTER":values=source["values"].copy() if source["values"].shape==(256,256) else O["filter_reference"](source["values"],args[-1])
            elif op=="CROP":values=source["values"][1:3,1:4].copy()
            elif op=="FFT":
                if label=="fft-BOUNDARY256":values=np.zeros((256,256),np.complex64);values[128,128]=2**40
                elif label=="fft-HIGH":values=O["dense_fourier_reference"](source["values"])[0]
                else:values=O["quarter_turn_dft"](source["values"].astype(np.float32))
            else:values=self.images[101]["values"].astype(np.complex64 if op=="IFFT" else np.float32)
            cal=copy.deepcopy(source["calibration"]);intensity=copy.deepcopy(source["intensity_calibration"])
            if op in ("FFT","IFFT","REAL"):
                truth_source=next(entry for entry in self.truth["images"] if entry["label"]==("LOW" if op!="FFT" else item["sources"][0]))
                cal=O["frequency_calibration"](truth_source,values.shape,op!="FFT");intensity={"origin":0.,"scale":1.,"unit":""}
            if op=="CROP":cal=[dict(axis,raw_origin=axis["raw_origin"]-1,origin=axis["origin"]+axis["scale"]) for axis in cal]
            image_id=1000+self.created;self.created+=1;self.label_ids[label]=image_id;self.creation[image_id]=(op,args,request_id)
            self.images[image_id]={"values":values,"name":"synthetic-produced-"+str(image_id),"code":{"float32":2,"complex64":3,"uint32":11}[str(values.dtype)],"calibration":cal,"intensity_calibration":intensity}
            operator="GMS::Image::GetSubSliceAsImage" if op=="CROP" else "GMSImageProcessing::"+({1:"Negate",2:"Abs",3:"Square"}[args[-1]] if op=="UNARY" else {1:"operator+",2:"operator-",3:"operator*"}[args[-1]] if op=="BINARY" else {1:"SmoothFilter",2:"SobelFilter",3:"LaplaceFilter",4:"SharpenFilter"}[args[-1]] if op=="FILTER" else {"FFT":"Real_FFT","IFFT":"IFFT","REAL":"Real"}[op])
            source_ids=args[:2] if op=="BINARY" else args[:1]
            out.update(image_id=image_id,image=self.metadata(image_id),operator=operator,source_write_requested=False,snapshot_atomic=False)
            if op in ("UNARY","BINARY"):out.update(source_image_ids=source_ids,sources=[self.metadata(i) for i in source_ids])
            else:out.update(source_image_id=source_ids[0],source=self.metadata(source_ids[0]))
            if op!="CROP":out["dtype_semantics"]={"input_dtypes":[str(self.images[i]["values"].dtype) for i in source_ids],"output_dtype":str(values.dtype),
                "selection":"DM native operator output; no bridge pixel cast","precision":{"float32":"binary32 result; not lossless for arbitrary uint32 inputs","uint32":"uint32 native result storage","complex64":"complex binary32 result; not lossless for arbitrary uint32 inputs"}[str(values.dtype)]}
        out["native_receipt"]=self.receipt(request_id,op,args);response={"content":[{"type":"text","text":json.dumps(out)}]}
        self.saved[request_id]=(op,args,response);return copy.deepcopy(response)

    def build(self):
        self.label_ids={};self.creation={}
        with mock.patch.dict(os.environ,{"DM_NATIVE_SESSION":SESSION}),mock.patch.dict(C["main"].__globals__,{"StdioClient":self.client_type()}),mock.patch("sys.stdout",io.StringIO()):
            result=C["main"](["--directory",str(self.directory),"--output-directory",str(self.attempt),"--qualification-mode","production"])
        if result!=0:raise AssertionError((self.attempt/C["REPORT_NAME"]).read_text())
        self.report_path=self.attempt/C["REPORT_NAME"];self.report=json.loads(self.report_path.read_bytes());self.ledger=self.attempt/C["LEDGER_NAME"];self.recovery=self.attempt/C["RECOVERY_LEDGER_NAME"]

    def client_type(self):
        base=super().client_type()
        class Client(base):
            def rpc(self,method,params):
                result=super().rpc(method,params)
                if method=="initialize":result["result"]["protocolVersion"]="2024-11-05"
                return result
        return Client

    def run(self):
        save(self.report_path,self.report);result={"status":"FAIL"};destination=self.directory/("independent-"+str(len(list(self.directory.glob('independent-*')))));destination.mkdir()
        with mock.patch.dict(sys.modules,{"DigitalMicrograph":self.module()}):O["collect"](result,str(self.truth_path),str(self.report_path),str(self.ledger),str(self.recovery),str(destination))
        return result


class Uint32ProductionFixtureTests(unittest.TestCase):
    def test_fixture_creates_only_nine_literal_sources_with_detached_original_files(self):
        with tempfile.TemporaryDirectory() as directory:
            images={};refs=[];views=[];documents=[]
            class Image:
                def __init__(self,values):
                    self.i=500+len(images);images[self.i]={"values":values.copy(),"calibration":[None,None]};refs.append(weakref.ref(self))
                def IsValid(self):return self.i in images
                def GetID(self):return self.i
                def GetDataType(self):return 11
                def SetName(self,value):images[self.i]["name"]=value
                def GetName(self):return images[self.i]["name"]
                def SetDimensionCalibration(self,axis,zero,scale,unit,mode):images[self.i]["calibration"][axis]=(zero,scale,unit)
                def GetDimensionCalibration(self,axis,mode):
                    zero,scale,unit=images[self.i]["calibration"][axis];return (-zero/scale if mode else zero),scale,unit
                def SetIntensityOrigin(self,value):images[self.i]["origin"]=value
                def SetIntensityScale(self,value):images[self.i]["scale"]=value
                def SetIntensityUnitString(self,value):images[self.i]["unit"]=value
                def GetIntensityOrigin(self):return images[self.i]["origin"]
                def GetIntensityScale(self):return images[self.i]["scale"]
                def GetIntensityUnitString(self):return images[self.i]["unit"]
                def GetNumArray(self):
                    view=images[self.i]["values"].view();views.append(weakref.ref(view));return view
                def GetOrCreateImageDocument(self):return types.SimpleNamespace(Show=lambda:documents.append(self.i))
            report={"schema":1,"status":"RECORDED","kind":"synthetic-only","fixture":"uint32-production-operations-v1","python_is_listener":False,"host_pid":os.getpid(),"session":SESSION,"images":[]}
            module=types.SimpleNamespace(CreateImage=Image,CountImageDocumentsOfAllWorkspaces=lambda:len(documents))
            with mock.patch.dict(sys.modules,{"DigitalMicrograph":module}):F["collect"](report,directory)
            self.assertEqual(len(images),9);self.assertEqual(len(documents),9);self.assertEqual(report["initial_document_count"],9)
            filename=Path(directory)/"truth.json";save(filename,report);truth,sources=S["load_truth"](S["Evidence"](),str(filename),os.getpid())
            self.assertEqual(int(sources["HIGH"][1][0,2]),16777217);self.assertEqual(sources["BOUNDARY256"][1].shape,(256,256))
            gc.collect();self.assertTrue(all(ref() is None for ref in refs+views))


@unittest.skipUnless(shutil.which("node"),"Offline NPY encoder requires Node; no download")
class Uint32ProductionOracleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.f=SyntheticProduction(self.temp.name);self.f.build()

    def test_full_offline_client_encoder_external_and_same_pid_oracle(self):
        result=self.f.run();self.assertEqual(result["status"],"PASS_BOUNDED_UINT32_OPERATIONS");self.assertEqual(result["output_count"],32)
        self.assertEqual(len(self.f.producer_ops),32);self.assertEqual(self.f.clients,2);self.assertEqual(len(self.f.report["recovery"]),32)
        self.assertEqual(result["captures"]["filter"]["dtype"],"uint32");self.assertEqual(result["captures"]["arithmetic"]["dtype"],"float32")
        gc.collect();self.assertTrue(all(ref() is None for ref in self.f.refs+self.f.views))

    def test_registered_new_high_and_policy_are_distinct_from_prepared(self):
        values=S["arrays"]()["HIGH"];self.assertEqual(int(values[0,0]),4294967295);self.assertEqual(int(values[0,2]),16777217)
        self.assertEqual(S["HIGH_FFT_POLICY"]["threshold_factor"],32*2**-24)
        self.assertIn("not a theoretical",S["HIGH_FFT_POLICY"]["scope"])

    def test_dense_high_sign_axis_and_wrong_peak_exceed_fixed_threshold(self):
        item=next(item for item in S["plan"]() if item["label"]=="fft-HIGH");sources={entry["label"]:(entry,self.f.images[entry["id"]]["values"]) for entry in self.f.truth["images"]}
        image_id=self.f.label_ids["fft-HIGH"];original=self.f.images[image_id]
        for values in (np.conj(original["values"]),original["values"].T.copy(),np.zeros_like(original["values"])):
            with self.subTest(fault=str(values[0,0])):
                with self.assertRaisesRegex(RuntimeError,"predeclared empirical"):O["numerical"](item,dict(original,values=values),sources,{})

    def test_boundary_non_dc_pixel_is_not_accepted(self):
        self.f.images[self.f.label_ids["fft-BOUNDARY256"]]["values"][0,0]=1
        with self.assertRaisesRegex(RuntimeError,"Fixed exact-root Fourier"):self.f.run()

    def test_uint32_sharpen_clamp_is_not_signed_or_wrapped(self):
        self.f.images[self.f.label_ids["filter-FILTER_EXTREME-4"]]["values"][1,1]^=np.uint32(1)
        with self.assertRaisesRegex(RuntimeError,"Fixed native filter-FILTER_EXTREME-4"):self.f.run()

    def test_wrong_actual_host_cannot_be_overridden_by_environment(self):
        self.f.report["host_pid"]+=1
        with mock.patch.dict(os.environ,{"DM_NATIVE_HOST_PID":str(self.f.report["host_pid"])}):
            with self.assertRaisesRegex(RuntimeError,"actual PID/session"):self.f.run()

    def test_raw_source_output_alias_rejected_before_copy(self):
        image_id=self.f.label_ids["filter-FILTER_LOW-1"];self.f.images[image_id]["values"]=self.f.images[104]["values"].view()
        with self.assertRaisesRegex(RuntimeError,"raw source/output views share memory"):self.f.run()

    def test_missing_or_changed_fresh_query_never_passes(self):
        self.f.report["recovery"][0]["response"]["content"][0]["text"]+=" "
        with self.assertRaisesRegex(RuntimeError,"immutable fresh-client QUERY"):self.f.run()

    def test_receipt_timings_exact_keys_types_bounds(self):
        entry=self.f.report["checks"][1];original=json.loads(entry["response"]["content"][0]["text"])
        for timing in (None,{}, {"queue":0,"execute":-1},{"queue":0,"execute":.5},{"queue":False,"execute":0},{"queue":2**53,"execute":0},{"queue":0,"execute":0,"extra":0}):
            with self.subTest(timing=timing):
                payload=copy.deepcopy(original);payload["native_receipt"]["timings_us"]=timing;entry["response"]["content"][0]["text"]=json.dumps(payload)
                with self.assertRaisesRegex(RuntimeError,"receipt timings"):self.f.run()

    def test_output_dtype_signedness_and_calibration_require_raw_agreement(self):
        image_id=self.f.label_ids["filter-FILTER_EXTREME-4"];self.f.images[image_id]["values"]=self.f.images[image_id]["values"].view(np.int32)
        with self.assertRaisesRegex(RuntimeError,"raw view dtype/shape"):self.f.run()

    def test_source_intensity_and_high_bits_remain_protected(self):
        self.f.images[102]["values"][0,2]=np.uint32(16777216)
        with self.assertRaisesRegex(RuntimeError,"source pixels/type/shape"):self.f.run()

    def test_incomplete_capture_manifest_rejected_after_live_math(self):
        capture=self.f.report["captures"][0];filename=Path(capture["receipt"]["capture_dir"])/"capture.json"
        value=json.loads(filename.read_bytes());value["state"]="capturing";save(filename,value)
        capture["receipt"]["files_sha256"]["capture.json"]=S["sha"](filename.read_bytes())
        # The journal is immutable too, so the target rejection is its
        # capture/native/file identity boundary, never an earlier math check.
        with self.assertRaisesRegex(RuntimeError,"capture journal/native state"):self.f.run()

    def test_derived_complex_lineage_requires_actual_direct_dtype_disclosure(self):
        original=copy.deepcopy(self.f.report)
        for label in ("ifft-LOW","inverse-real-LOW"):
            for fault in ("missing","input_dtype"):
                with self.subTest(label=label,fault=fault):
                    self.f.report=copy.deepcopy(original);entry=next(entry for entry in self.f.report["checks"] if entry["label"]==label)
                    output=json.loads(entry["response"]["content"][0]["text"])
                    if fault=="missing":output.pop("dtype_semantics")
                    else:output["dtype_semantics"]["input_dtypes"]=["uint32"]
                    entry["response"]["content"][0]["text"]=json.dumps(output)
                    for query in self.f.report["recovery"]:
                        if query["label"]==label:query["response"]=copy.deepcopy(entry["response"])
                    with self.assertRaisesRegex(RuntimeError,"native dtype/precision disclosure"):self.f.run()


if __name__=="__main__":unittest.main()
