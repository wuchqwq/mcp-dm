# -*- coding: utf-8 -*-
"""Synthetic uint32 MCP/artifact/host-oracle faults. Never imports real DM."""
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
from unittest import mock
import weakref

import numpy as np
from test_native_handoff_oracle import png

ROOT=Path(__file__).resolve().parents[1]
MVP=ROOT/"experiments"/"native-bridge"/"mvp"
with mock.patch.object(sys,"path",[str(MVP)]+sys.path):
    U=runpy.run_path(str(MVP/"uint32_acceptance.py"))
    CLIENT=runpy.run_path(str(MVP/"accept_uint32_mcp.py"))
    ORACLE=runpy.run_path(str(MVP/"verify_uint32.py"))
    STOPPED=runpy.run_path(str(MVP/"verify_uint32_stopped.py"))
SESSION="0123456789abcdef0123456789abcdef"


def save(path,value):
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+"\n",encoding="utf-8")


class Synthetic:
    def __init__(self,directory):
        self.directory=Path(directory);self.images={};self.saved={};self.clients=0;self.refs=[];self.views=[];self.docs=2;self.mode="prepared"
        self.source=np.array([[0,1,16777215,16777216],[16777217,2147483647,2147483648,4294967294],
            [123456789,3,65537,4294967295],[11,29,100000001,4000000001]],dtype=np.uint32)
        truth={"schema":1,"kind":"synthetic-only","status":"RECORDED","python_is_listener":False,"host_pid":os.getpid(),"session":SESSION,
               "document_count_before_fixture":0,"initial_document_count":2,"images":[]}
        for image_id,label,unit in ((101,"CALIBRATED","nm"),(102,"RAW_UNITS","")):
            data={"values":self.source.copy(),"name":"synthetic-uint32-"+label,"calibration":U["expected_axes"](unit),
                  "intensity_calibration":{"origin":7.5,"scale":-2.0,"unit":"arb"},"code":11}
            self.images[image_id]=data;path=self.directory/(label+".npy");np.save(str(path),data["values"],allow_pickle=False)
            truth["images"].append({"id":image_id,"label":label,"name":data["name"],"dtype":"uint32","shape":[4,4],"python_data_type_code":11,
                "source_npy":str(path),"source_file_sha256":U["sha"](path.read_bytes()),"pixel_sha256":U["sha"](data["values"].tobytes()),
                "calibration":data["calibration"],"intensity_calibration":data["intensity_calibration"],"expected_summary":dict(U["SOURCE_STATS"])})
        self.truth_path=self.directory/"uint32-truth.json";save(self.truth_path,truth)
        self.attempt=self.directory/"attempt"

    def metadata(self,image_id):
        data=self.images[image_id];shape=list(data["values"].shape)
        axes=[{"dm_dimension":a["dm_axis"],"numpy_axis":1-a["dm_axis"],"size":shape[1-a["dm_axis"]],"origin":a["raw_origin"],
            "calibrated_value_at_pixel_zero":a["origin"],"scale":a["scale"],"unit":a["unit"] or None,"usable":bool(a["unit"]),
            "issue":None if a["unit"] else "unknown_units"} for a in data["calibration"]]
        return {"id":image_id,"name":data["name"],"dtype":"uint32","data_type_code":11,"is_integer":True,"is_unsigned":True,"packing_style":1,
            "ndim":2,"shape":shape,"dm_dimensions":shape[::-1],"pixels":int(data["values"].size),"shape_order":"numpy (last axis is X)",
            "coordinate_rule":"physical(i)=calibrated_value_at_pixel_zero+i*scale","native_mean_supported":True,"native_summary_supported":True,
            "calibration_complete":all(a["usable"] for a in axes),"calibration":axes}

    def receipt(self,request_id,op,args,state="completed",code=None,error=None):
        value={"protocol":"NB2","session":SESSION,"id":request_id,"request_id":request_id,"state":state,"host_pid":os.getpid(),
            "worker_tid":200,"exec_tid":100,"timings_us":{"queue":1,"execute":2},"original_operation":op,"normalized_args":args,
            "result_type":U["TYPES"][op],"result_version":2 if op in ("FFT","REAL") else 1}
        if error:value.update(code=code,error=error)
        return value

    def response(self,tool,params):
        request_id=params["request_id"]
        if tool=="dm_native_result":return copy.deepcopy(self.saved[request_id][2])
        inv={"dm_status":("STATUS",[]),"dm_native_mean":("MEAN",[params.get("image_id")]),"dm_native_summary":("SUMMARY",[params.get("image_id")]),
             "dm_crop":("CROP",[params.get("image_id")]+params.get("rect",[])),
             "dm_native_read":("READ",[params.get("image_id")]+params.get("rect",[])),
             "dm_native_preview":("PREVIEW",[params.get("image_id"),params.get("max_width",128),params.get("max_height",128)]),
             "dm_native_unary":("UNARY",[params.get("image_id"),3]),"dm_native_binary":("BINARY",[params.get("left_image_id"),params.get("right_image_id"),1]),
             "dm_native_fft":("FFT",[params.get("image_id")]),"dm_native_complex":("REAL",[params.get("image_id")]),"dm_native_filter":("FILTER",[params.get("image_id"),1])}
        op,args=inv[tool]
        if request_id in self.saved:
            original_op,original_args,response=self.saved[request_id]
            if (op,args)==(original_op,original_args):return copy.deepcopy(response)
            receipt=self.receipt(request_id,original_op,original_args,"failed","id_conflict","id is already bound to different operation parameters");receipt["exec_tid"]=0
            return {"isError":True,"content":[{"type":"text","text":json.dumps({"native_receipt":receipt,"error":receipt["error"]})}]}
        failed={"UNARY":"native_arithmetic_requires_float32_2d","BINARY":"native_arithmetic_requires_float32_2d","FFT":"native_fft_input_type_or_dimensions_unsupported",
                "REAL":"native_fft_component_requires_plugin_transform","FILTER":"native_filter_requires_float32_2d_ordinary_packing"}.get(op)
        if op=="CROP" and args[0]==102:failed="unknown_image_units"
        if failed:
            receipt=self.receipt(request_id,op,args,"failed","native_error",failed)
            response={"isError":True,"content":[{"type":"text","text":json.dumps({"native_receipt":receipt,"error":failed})}]}
            self.saved[request_id]=(op,args,response);return copy.deepcopy(response)
        out={"backend":"digitalmicrograph-native"}
        if op=="STATUS":
            out.update(ready=True,binary_gate=True,host_pid=os.getpid(),host_thread=100,supported_build="3.53.4137.0-x64",host_build="3.53.4137.0",
                host_architecture="x64",adapter_profile="gms-3.53.4137.0-windows-x64",adapter_active=True,compatibility={"state":"SUPPORTED"},
                retained_result_count=int(201 in self.images),prepared_uint32_execution_enabled=True,
                native_capabilities=[{"name":name,"available":False,"qualification":"NOT_QUALIFIED"} for name in U["CAPABILITIES"]])
            if self.mode=="production":
                out.pop("prepared_uint32_execution_enabled")
                out["native_capabilities"]=[{"name":name,"available":True,"qualification":"LIMITED_REAL_HOST"} for name in U["CAPABILITIES"]]
        elif op in ("MEAN","SUMMARY"):
            expected=U["CROP_STATS"] if args[0]==201 else U["SOURCE_STATS"]
            out.update(image_id=args[0],image=self.metadata(args[0]),computation="DM native",intensity_calibration_applied=False,
                intensity_semantics="raw pixel intensity",source_write_requested=False,snapshot_atomic=False)
            if op=="MEAN":out.update(mean=expected["mean"],operator="GMSImageProcessing::GetMean")
            else:out.update(expected);out["operators"]=U["OPERATORS"]
        elif op=="CROP":
            source=self.images[args[0]]
            data={"values":source["values"][1:3,1:4].copy(),"name":"synthetic-u32-crop","calibration":[dict(a,raw_origin=a["raw_origin"]-1,origin=a["origin"]+a["scale"]) for a in source["calibration"]],
                "intensity_calibration":copy.deepcopy(source["intensity_calibration"]),"code":11}
            self.images[201]=data;self.crop_request_id=request_id
            out.update(source_image_id=args[0],image_id=201,source=self.metadata(args[0]),image=self.metadata(201),requested_rect=args[1:],effective_rect=args[1:],
                operator="GMS::Image::GetSubSliceAsImage",source_write_requested=False,snapshot_atomic=False,ownership="synthetic owned image")
        elif op=="READ":
            image_id,x0,y0,x1,y1=args;source=self.metadata(image_id);values=self.images[image_id]["values"][y0:y1,x0:x1];rect=args[1:]
            axes=[]
            for axis in source["calibration"]:
                dim=axis["dm_dimension"];offset=rect[dim]
                axes.append({"dm_dimension":dim,"numpy_axis":1-dim,"size":values.shape[1-dim],"source_offset":offset,"source_origin":axis["origin"],
                    "source_calibrated_value_at_pixel_zero":axis["calibrated_value_at_pixel_zero"],"origin":axis["origin"]-offset,
                    "calibrated_value_at_pixel_zero":axis["calibrated_value_at_pixel_zero"]+offset*axis["scale"],"scale":axis["scale"],"unit":axis["unit"],"usable":axis["usable"],"issue":axis["issue"]})
            provenance={"operation":"CROP","request_id":self.crop_request_id,"source_image_ids":[101],"semantics":"independent native crop copy"} if image_id==201 else None
            out.update(operation="READ",source_image_id=image_id,source=source,requested_rect=rect,effective_rect=rect,shape=list(values.shape),dtype="uint32",
                byte_order="little",axes=["y","x"],array_order="C",data_encoding="base64",values_base64=base64.b64encode(values.tobytes()).decode("ascii"),sample_count=int(values.size),raw_bytes=values.nbytes,
                roi_calibration=axes,calibration_complete=source["calibration_complete"],coordinate_mapping_policy=U["MAPPING_POLICY"],source_provenance=provenance,source_provenance_scope=U["PROVENANCE_SCOPE"],
                operator="GMS::Image::GetRealValue",computation="DM native point reads; data handoff only",intensity_calibration_applied=False,intensity_semantics="raw pixel intensity",
                ownership="response-owned numeric snapshot; no native result image",source_write_requested=False,snapshot_atomic=False)
        elif op=="PREVIEW":
            image_id,mw,mh=args;w,h,low,high,gray,unused,unused2=U["reference_preview"](self.images[image_id]["values"],mw,mh)
            out.update(operation="PREVIEW",image_id=image_id,source=self.metadata(image_id),width=w,height=h,sample_count=w*h,sampled_minimum=low,sampled_maximum=high,gray8_hex=gray.hex(),
                mapping=U["MAPPING"],orientation=U["ORIENTATION"],sampling=U["SAMPLING"],range_source="sampled native point values",constant_range_gray8=0,
                operator="GMS::Image::GetRealValue",quantitative=False,source_write_requested=False,snapshot_atomic=False)
        out["native_receipt"]=self.receipt(request_id,op,args)
        response={"content":[{"type":"text","text":json.dumps(out)}]}
        if op=="PREVIEW":response["content"].append({"type":"image","mimeType":"image/png","data":base64.b64encode(png(gray,w,h)).decode("ascii")})
        self.saved[request_id]=(op,args,response);return copy.deepcopy(response)

    def client_type(self):
        fixture=self
        class Client:
            def __init__(self,*args,**kwargs):fixture.clients+=1;self.proc=types.SimpleNamespace(returncode=0);self.stderr=b""
            def rpc(self,method,params):
                if method=="initialize":return {"result":{"serverInfo":{"name":"digitalmicrograph","version":"0.6.0"}}}
                if method=="tools/list":return {"result":{"tools":[{"name":name} for name in CLIENT["CATALOG"]]}}
                return {"result":fixture.response(params["name"],params["arguments"])}
            def notify(self,*args):pass
            def close(self):pass
        return Client

    def build(self):
        with mock.patch.dict(os.environ,{"DM_NATIVE_SESSION":SESSION}),mock.patch.dict(CLIENT["main"].__globals__,{"StdioClient":self.client_type()}),mock.patch("sys.stdout",io.StringIO()):
            result=CLIENT["main"](["--directory",str(self.directory),"--output-directory",str(self.attempt),"--qualification-mode",self.mode])
        if result!=0:raise AssertionError((self.attempt/"uint32-mcp-report.json").read_text())
        self.report_path=self.attempt/"uint32-mcp-report.json";self.report=json.loads(self.report_path.read_bytes())
        self.ledger=self.attempt/"uint32-requests.jsonl";self.recovery=self.attempt/"uint32-recovery-requests.jsonl"

    def module(self):
        fixture=self
        class Image:
            def __init__(self,i):self.i=i;fixture.refs.append(weakref.ref(self))
            def IsValid(self):return self.i in fixture.images
            def GetID(self):return self.i
            def GetName(self):return fixture.images[self.i]["name"]
            def GetDataType(self):return fixture.images[self.i]["code"]
            def GetNumArray(self):
                view=fixture.images[self.i]["values"].view();fixture.views.append(weakref.ref(view));return view
            def GetDimensionCalibration(self,dim,mode):
                a=fixture.images[self.i]["calibration"][dim];return a["raw_origin" if mode else "origin"],a["scale"],a["unit"]
            def GetIntensityOrigin(self):return fixture.images[self.i]["intensity_calibration"]["origin"]
            def GetIntensityScale(self):return fixture.images[self.i]["intensity_calibration"]["scale"]
            def GetIntensityUnitString(self):return fixture.images[self.i]["intensity_calibration"]["unit"]
        return types.SimpleNamespace(FindImageByID=lambda i:Image(i),CountImageDocumentsOfAllWorkspaces=lambda:fixture.docs)

    def run(self):
        save(self.report_path,self.report);result={"schema":1,"kind":"synthetic-only","status":"FAIL"}
        with mock.patch.dict(sys.modules,{"DigitalMicrograph":self.module()}):ORACLE["collect"](result,str(self.truth_path),str(self.report_path),str(self.ledger),str(self.recovery))
        return result


@unittest.skipUnless(shutil.which("node"),"Offline native encoder requires Node; no download")
class Uint32OracleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.f=Synthetic(self.temp.name);self.f.build()

    def fails(self,message):
        with self.assertRaisesRegex(RuntimeError,message):self.f.run()

    def mutate(self,label,callback):
        entry=next(v for v in self.f.report["checks"] if v["label"]==label)
        out=json.loads(entry["response"]["content"][0]["text"]);callback(out);entry["response"]["content"][0]["text"]=json.dumps(out)

    def test_complete_synthetic_chain_real_encoder_external_and_fresh_client(self):
        result=self.f.run();self.assertEqual(result["status"],"PASS_BOUNDED_UINT32");self.assertEqual(self.f.clients,2)
        self.assertEqual(result["external_mean"]["sum"],12884967424)
        self.assertEqual(result["external_mean"]["mean"],2147494570.6666665)
        package=next(v for v in self.f.report["captures"] if v["label"]=="source")
        values=np.load(Path(package["receipt"]["capture_dir"])/"input.npy",allow_pickle=False)
        self.assertEqual(values.dtype,np.dtype("<u4"));self.assertEqual(int(values[1,0]),16777217);self.assertEqual(int(values[2,3]),4294967295)
        gc.collect();self.assertTrue(all(ref() is None for ref in self.f.refs+self.f.views))

    def test_native_summary_wrong_sum(self):
        self.mutate("summary_calibrated",lambda o:o.update(sum=o["sum"]+1));self.fails("native sum differs")

    def test_native_mean_float32_rounded_high_value(self):
        self.mutate("mean_crop",lambda o:o.update(mean=float(np.float32(o["mean"]))));self.fails("native mean differs")

    def test_wrong_metadata_dtype(self):
        self.mutate("summary_calibrated",lambda o:o["image"].update(dtype="float32",data_type_code=2));self.fails("dtype/signedness")

    def test_wrong_metadata_signedness(self):
        self.mutate("summary_calibrated",lambda o:o["image"].update(is_unsigned=False));self.fails("dtype/signedness")

    def test_source_high_bit_truncation(self):
        self.f.images[101]["values"][1,0]=np.uint32(16777216);self.fails("source pixels")

    def test_live_signed_int32_view_is_rejected(self):
        self.f.images[101]["values"]=self.f.images[101]["values"].view("<i4");self.fails("Raw host view shape/dtype")

    def test_python_native_type_code(self):
        self.f.images[101]["code"]=7;self.fails("GetDataType disagrees")

    def test_crop_wrong_roi_axes(self):
        self.f.images[201]["values"]=self.f.images[201]["values"].T;self.fails("Raw host view shape/dtype")

    def test_crop_aliases_raw_source(self):
        self.f.images[201]["values"]=self.f.images[101]["values"][1:3,1:4];self.fails("raw views share memory")

    def test_source_signed_calibration_changed(self):
        self.f.images[101]["calibration"][0]["scale"]*=-1;self.fails("spatial/intensity calibration changed")

    def test_crop_intensity_calibration_changed(self):
        self.f.images[201]["intensity_calibration"]["scale"]=1;self.fails("spatial/intensity calibration not preserved")

    def test_unknown_not_negative_pass(self):
        self.mutate("bad_fft",lambda o:o["native_receipt"].update(state="unknown"));self.fails("receipt identity/type/thread")

    def test_wrong_negative_error_not_budget_mask(self):
        self.mutate("bad_unary",lambda o:o["native_receipt"].update(error="native_crop_retained_budget_exceeded"));self.fails("failure domain")

    def test_host_pid_not_env_self_consistency(self):
        self.f.report["host_pid"]+=1
        with mock.patch.dict(os.environ,{"DM_NATIVE_HOST_PID":str(self.f.report["host_pid"])}):self.fails("report/truth/host")

    def test_receipt_wrong_session(self):
        self.mutate("summary_calibrated",lambda o:o["native_receipt"].update(session="f"*32));self.fails("receipt identity")

    def test_axis_metadata_wrong(self):
        self.mutate("summary_calibrated",lambda o:o["image"]["calibration"][0].update(numpy_axis=0));self.fails("calibration axis/unit")

    def test_missing_units_not_invented(self):
        self.mutate("summary_raw_units",lambda o:o["image"]["calibration"][0].update(unit="nm",usable=True,issue=None));self.fails("calibration axis/unit")

    def test_query_changed_output(self):
        self.f.report["recovery"][0]["response"]["content"][0]["text"]+=" ";self.fails("immutable QUERY/repeat changed")

    def test_conflict_unknown_not_refusal(self):
        entry=self.f.report["recovery"][2];out=json.loads(entry["response"]["content"][0]["text"]);out["native_receipt"]["code"]="busy"
        entry["response"]["content"][0]["text"]=json.dumps(out);self.fails("precise original-record refusal")

    def test_conflict_receipt_timings_reject_precise_malformed_fields(self):
        entry=self.f.report["recovery"][2]
        original=json.loads(entry["response"]["content"][0]["text"])
        invalid=(("missing",None),("null",None),("array",[]),("empty",{}),
            ("missing_queue",{"execute":0}),("missing_execute",{"queue":0}),
            ("negative_both",{"queue":-1,"execute":-1}),("negative_queue",{"queue":-1,"execute":0}),
            ("negative_execute",{"queue":0,"execute":-1}),("fraction_queue",{"queue":.5,"execute":0}),
            ("fraction_execute",{"queue":0,"execute":.5}),("bool_queue",{"queue":False,"execute":0}),
            ("bool_execute",{"queue":0,"execute":True}),("over_queue",{"queue":2**53,"execute":0}),
            ("over_execute",{"queue":0,"execute":2**53}),("extra",{"queue":0,"execute":0,"other":0}))
        for label,timings in invalid:
            with self.subTest(timings=label):
                output=copy.deepcopy(original)
                if label=="missing":output["native_receipt"].pop("timings_us")
                else:output["native_receipt"]["timings_us"]=timings
                entry["response"]["content"][0]["text"]=json.dumps(output)
                self.fails("uint32 conflict receipt timings mismatch")
        self.assertEqual(self.f.views,[])  # Every fault hits the timing guard before host pixel reads.

    def test_conflict_receipt_zero_timings_remain_valid(self):
        entry=self.f.report["recovery"][2]
        output=json.loads(entry["response"]["content"][0]["text"])
        output["native_receipt"]["timings_us"]={"queue":0,"execute":0}
        entry["response"]["content"][0]["text"]=json.dumps(output)
        self.assertEqual(self.f.run()["status"],"PASS_BOUNDED_UINT32")

    def test_repeat_created_extra_pool_object(self):
        self.mutate("pool_after_recovery",lambda o:o.update(retained_result_count=2));self.fails("extra retained object")

    def test_new_production_does_not_accept_prepared_status(self):
        self.f.report["qualification_mode"]="production";self.fails("subgroup qualification")

    def test_production_complete_positive(self):
        directory=self.f.directory/"production";directory.mkdir();fixture=Synthetic(str(directory));fixture.mode="production";fixture.build()
        self.assertEqual(fixture.run()["qualification_mode"],"production")

    def test_acceptance_native_mean_error_is_not_external_fallback(self):
        original=self.f.response
        def wrong(tool,args):
            response=original(tool,args)
            if tool=="dm_native_mean":
                output=json.loads(response["content"][0]["text"]);output["mean"]+=1;response["content"][0]["text"]=json.dumps(output)
            return response
        self.f.response=wrong
        target=self.f.directory/"mean-failed-attempt"
        with mock.patch.dict(os.environ,{"DM_NATIVE_SESSION":SESSION}),mock.patch.dict(CLIENT["main"].__globals__,{"StdioClient":self.f.client_type()}),mock.patch("sys.stdout",io.StringIO()):
            status=CLIENT["main"](["--directory",str(self.f.directory),"--output-directory",str(target),"--qualification-mode","prepared"])
        report=json.loads((target/"uint32-mcp-report.json").read_bytes())
        self.assertEqual(status,1);self.assertEqual(report["status"],"FAIL");self.assertIn("native mean differs",report["error"])
        self.assertFalse((target/"external-workspace").exists())

    def test_uint32_read_not_float32_conversion(self):
        entry=next(v for v in self.f.report["checks"] if v["label"]=="read_source");out=json.loads(entry["response"]["content"][0]["text"])
        values=self.f.images[101]["values"].astype(np.float32).astype(np.uint64);values=np.minimum(values,4294967295).astype(np.uint32)
        out["values_base64"]=base64.b64encode(values.tobytes()).decode("ascii")
        with self.assertRaisesRegex(RuntimeError,"READ high bits"):
            U["read"](out,101,[0,0,4,4],self.f.images[101],None)

    def test_npy_signed_dtype_rejected_even_same_raw_bits(self):
        raw=io.BytesIO();np.save(raw,self.f.source.view("<i4"),allow_pickle=False)
        with self.assertRaisesRegex(RuntimeError,"NPY header/shape/dtype"):
            U["bounded_npy"](raw.getvalue(),[4,4],"<u4")

    def test_external_sum_wrong_with_refreshed_result_hash(self):
        directory=Path(self.f.report["external"]["output_dir"]);result=json.loads((directory/"results.json").read_bytes());result["sum"]+=1;save(directory/"results.json",result)
        run=json.loads((directory/"run.json").read_bytes());run["results_sha256"]=U["sha"]((directory/"results.json").read_bytes());save(directory/"run.json",run)
        self.fails("external exact sum/mean")

    def test_uint32_stop_identity_and_release(self):
        independent=self.f.run();path=self.f.directory/"uint32-independent.json";save(path,independent)
        request={"protocol":"NB2","session":SESSION,"id":"uint32-stop","op":"STOP","args":[],"host_pid":os.getpid(),"wire":"NB2 %s uint32-stop STOP\n" % SESSION}
        receipt={"protocol":"NB2","session":SESSION,"id":"uint32-stop","state":"completed","host_pid":os.getpid(),"exec_tid":0,"worker_tid":200,
            "original_operation":"STOP","normalized_args":[],"result_type":"ipc_stop","result_version":1,"timings_us":{"queue":0,"execute":0},"result":{"ipc_stopped":True}}
        request_path=self.f.directory/"stop-request.json";receipt_path=self.f.directory/"stop-receipt.json";save(request_path,request);save(receipt_path,receipt)
        def run():
            value={"status":"FAIL"}
            with mock.patch.dict(sys.modules,{"DigitalMicrograph":self.f.module()}):STOPPED["collect"](value,str(self.f.truth_path),str(self.f.report_path),str(self.f.ledger),str(self.f.recovery),str(path),str(request_path),str(receipt_path))
            return value
        with self.assertRaisesRegex(RuntimeError,"crop still valid"):run()
        self.f.images.pop(201)
        self.assertEqual(run()["status"],"PASS_UINT32_STOPPED")
        receipt["host_pid"]+=1;save(receipt_path,receipt)
        with self.assertRaisesRegex(RuntimeError,"STOP receipt identity"):run()

    def test_uint32_stop_wrong_op_wire_session_state_and_worker(self):
        independent=self.f.run();path=self.f.directory/"uint32-independent.json";save(path,independent);self.f.images.pop(201)
        request={"protocol":"NB2","session":SESSION,"id":"uint32-stop","op":"STOP","args":[],"host_pid":os.getpid(),"wire":"NB2 %s uint32-stop STOP\n" % SESSION}
        receipt={"protocol":"NB2","session":SESSION,"id":"uint32-stop","state":"completed","host_pid":os.getpid(),"exec_tid":0,"worker_tid":200,
            "original_operation":"STOP","normalized_args":[],"result_type":"ipc_stop","result_version":1,"timings_us":{"queue":0,"execute":0},"result":{"ipc_stopped":True}}
        request_path=self.f.directory/"stop-request.json";receipt_path=self.f.directory/"stop-receipt.json"
        mutations=(("request","op","SHOW"),("request","wire","STOP\n"),("request","session","f"*32),("request","args",[201]),
                   ("receipt","state","unknown"),("receipt","worker_tid",201),("receipt","id","wrong-stop"),("receipt","exec_tid",100))
        for owner,key,value in mutations:
            with self.subTest(owner=owner,key=key):
                changed_request=copy.deepcopy(request);changed_receipt=copy.deepcopy(receipt)
                (changed_request if owner=="request" else changed_receipt)[key]=value
                save(request_path,changed_request);save(receipt_path,changed_receipt)
                with mock.patch.dict(sys.modules,{"DigitalMicrograph":self.f.module()}):
                    with self.assertRaisesRegex(RuntimeError,"STOP request|STOP wire|STOP receipt identity"):
                        STOPPED["collect"]({},str(self.f.truth_path),str(self.f.report_path),str(self.f.ledger),str(self.f.recovery),str(path),str(request_path),str(receipt_path))


if __name__=="__main__":unittest.main()
