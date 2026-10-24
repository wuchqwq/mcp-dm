# -*- coding: utf-8 -*-
"""Synthetic callbacks only. Arbitrary output values MUST stay unqualified."""
import copy
import gc
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import types
import unittest
from unittest import mock
import weakref

import numpy as np

MVP=Path(__file__).resolve().parents[1]/"experiments"/"native-bridge"/"mvp"
with mock.patch.object(sys,"path",[str(MVP)]+sys.path):
    P=runpy.run_path(str(MVP/"uint32_operations_probe.py"))
    O=runpy.run_path(str(MVP/"observe_uint32_operations.py"))
    F=runpy.run_path(str(MVP/"create_uint32_operations_fixture.py"))
SESSION="0123456789abcdef0123456789abcdef"


def save(path,value):
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+"\n",encoding="utf-8")


def calibration():
    return [{"dm_axis":0,"origin":1.25,"raw_origin":5.,"scale":-.25,"unit":"nm"},
            {"dm_axis":1,"origin":-2.5,"raw_origin":5.,"scale":.5,"unit":"nm"}]


class Synthetic:
    def __init__(self,directory):
        self.directory=Path(directory);self.images={};self.saved={};self.calls=[];self.created=0;self.refs=[];self.views=[];self.queued=False;self.fail_fft_low=False
        self.truth={"schema":1,"kind":"synthetic-only","status":"RECORDED","python_is_listener":False,"host_pid":os.getpid(),"session":SESSION,
                    "document_count_before_fixture":0,"initial_document_count":7,"images":[]}
        for image_id,(label,values) in enumerate(P["arrays"]().items(),101):
            data={"values":values.copy(),"code":11,"name":"synthetic-"+label,"calibration":calibration(),"intensity_calibration":{"origin":7.5,"scale":-2.,"unit":"arb"}}
            self.images[image_id]=data;path=self.directory/(label+".npy");np.save(str(path),values,allow_pickle=False)
            self.truth["images"].append({"id":image_id,"label":label,"name":data["name"],"dtype":"uint32","shape":list(values.shape),"python_data_type_code":11,
                "source_npy":str(path),"source_file_sha256":P["sha"](path.read_bytes()),"pixel_sha256":P["sha"](values.tobytes()),
                "calibration":data["calibration"],"intensity_calibration":data["intensity_calibration"]})
        self.truth_path=self.directory/"truth.json";save(self.truth_path,self.truth)
        self.output=self.directory/"probe"

    def metadata(self,image_id):
        d=self.images[image_id];shape=list(d["values"].shape);code=d["code"]
        value={"id":image_id,"name":d["name"],"ndim":2,"shape":shape,"dm_dimensions":shape[::-1],"pixels":int(d["values"].size),"packing_style":1,
            "data_type_code":code,"dtype":{2:"float32",3:"complex64",11:"uint32"}[code],"calibration_complete":True,
            "calibration":[{"dm_dimension":a["dm_axis"],"numpy_axis":1-a["dm_axis"],"size":shape[1-a["dm_axis"]],"origin":a["raw_origin"],
                "calibrated_value_at_pixel_zero":a["origin"],"scale":a["scale"],"unit":a["unit"],"usable":True,"issue":None} for a in d["calibration"]]}
        if code==11:value.update(is_integer=True,is_unsigned=True)
        return value

    def exchange(self,session,wire,remaining):
        self.calls.append(wire);tokens=wire.strip().split();request_id,op=tokens[2:4];args=list(map(int,tokens[4:]))
        if op=="QUERY":return copy.deepcopy(self.saved[request_id])
        receipt={"protocol":"NB2","session":session,"id":request_id,"state":"completed","host_pid":os.getpid(),"worker_tid":200,"exec_tid":100,
                 "timings_us":{"queue":1,"execute":2},"original_operation":op,"normalized_args":args,"result_type":P["RESULT_TYPES"][op],
                 "result_version":2 if op in ("FFT","IFFT","REAL","IMAG") else 1}
        if op=="STATUS":
            receipt["result"]={"backend":"digitalmicrograph-native","ready":True,"binary_gate":True,"host_pid":os.getpid(),"host_thread":100,
                "prepared_uint32_operations_enabled":True,"adapter_profile":"gms-3.53.4137.0-windows-x64","compatibility":{"state":"SUPPORTED"},"retained_result_count":self.created}
        elif op=="FFT" and args[0]==101 and self.fail_fft_low:
            receipt.update(state="failed",code="native_error",error="synthetic_unknown_native_error")
        else:
            source_ids=args[:2] if op=="BINARY" else args[:1];source=self.images[source_ids[0]];shape=source["values"].shape
            code=3 if op in ("FFT","IFFT") else 11 if op=="CROP" or (op=="FILTER" and args[1] in (1,4)) else 2
            if op=="CROP":values=source["values"][1:3,1:4].copy()
            else:values=np.full(shape,complex(self.created+1,.25) if code==3 else self.created+1,dtype={2:np.float32,3:np.complex64,11:np.uint32}[code])
            image_id=1000+self.created;self.created+=1
            data={"values":values,"code":code,"name":"synthetic-output-"+str(image_id),"calibration":calibration(),"intensity_calibration":{"origin":7.5,"scale":-2.,"unit":"arb"}}
            if op=="CROP":
                for axis in data["calibration"]:
                    axis["raw_origin"]-=1
                    axis["origin"]+=axis["scale"]
            self.images[image_id]=data
            names={"FFT":"Real_FFT","IFFT":"IFFT","REAL":"Real","IMAG":"Imag"}
            operator=("GMS::Image::GetSubSliceAsImage" if op=="CROP" else "GMSImageProcessing::"+(
                {1:"Negate",2:"Abs",3:"Square"}[args[1]] if op=="UNARY" else {1:"operator+",2:"operator-",3:"operator*"}[args[2]] if op=="BINARY" else
                {1:"SmoothFilter",2:"SobelFilter",3:"LaplaceFilter",4:"SharpenFilter"}[args[1]] if op=="FILTER" else names[op]))
            result={"backend":"digitalmicrograph-native","image_id":image_id,"image":self.metadata(image_id),"source_image_ids":source_ids,
                    "operator":operator,"source_write_requested":False,"snapshot_atomic":False}
            if op in ("UNARY","BINARY"):result["sources"]=[self.metadata(i) for i in source_ids]
            else:result["source"]=self.metadata(source_ids[0])
            if source["code"]==11 and op!="CROP":
                result.update(candidate_probe=True,qualification="NOT_QUALIFIED",dtype_semantics={"input_dtypes":[str(self.images[i]["values"].dtype) for i in source_ids],
                    "output_dtype":str(values.dtype),"selection":"DM native operator output; no bridge pixel cast",
                    "precision":{2:"binary32 result; not lossless for arbitrary uint32 inputs",11:"uint32 native result storage",3:"complex binary32 result; not lossless for arbitrary uint32 inputs"}[code]})
            receipt["result"]=result
        self.saved[request_id]=copy.deepcopy(receipt)
        if self.queued and op!="STATUS" and receipt["state"]=="completed":
            first=copy.deepcopy(receipt);first.pop("result");first.update(state="queued",exec_tid=0);return first
        return receipt

    def run(self):
        with mock.patch.dict(os.environ,{"DM_NATIVE_SESSION":SESSION}):
            self.report=P["run"](str(self.truth_path),str(self.output),"prepared_uint32_operations_enabled",self.exchange)
        self.probe_path=self.output/"uint32-operations-probe.json";self.ledger_path=self.output/"uint32-operations-requests.jsonl"
        return self.report

    def module(self):
        fixture=self
        class Image:
            def __init__(self,image_id):self.i=image_id;fixture.refs.append(weakref.ref(self))
            def IsValid(self):return self.i in fixture.images
            def GetID(self):return self.i
            def GetDataType(self):return fixture.images[self.i]["code"]
            def GetName(self):return fixture.images[self.i]["name"]
            def GetNumArray(self):
                view=fixture.images[self.i]["values"].view();fixture.views.append(weakref.ref(view));return view
            def GetDimensionCalibration(self,dim,mode):
                a=fixture.images[self.i]["calibration"][dim];return a["raw_origin" if mode else "origin"],a["scale"],a["unit"]
            def GetIntensityOrigin(self):return fixture.images[self.i]["intensity_calibration"]["origin"]
            def GetIntensityScale(self):return fixture.images[self.i]["intensity_calibration"]["scale"]
            def GetIntensityUnitString(self):return fixture.images[self.i]["intensity_calibration"]["unit"]
        return types.SimpleNamespace(FindImageByID=lambda i:Image(i),CountImageDocumentsOfAllWorkspaces=lambda:7)

    def observe(self):
        save(self.probe_path,self.report)
        target=self.directory/("observation-"+str(len(list(self.directory.glob('observation-*')))));target.mkdir()
        report={"status":"FAIL","outputs":[],"numerical_qualification":"NOT_QUALIFIED","scientific_operator_pass":False}
        with mock.patch.dict(sys.modules,{"DigitalMicrograph":self.module()}):
            O["collect"](report,str(self.truth_path),str(self.probe_path),str(self.ledger_path),str(target))
        return report


class Uint32OperationsProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.f=Synthetic(self.temp.name)

    def test_raw_protocol_and_independent_snapshots_never_qualify_arbitrary_pixels(self):
        self.assertEqual(self.f.run()["status"],"RECORDED_UNQUALIFIED")
        result=self.f.observe();self.assertEqual(result["status"],"RECORDED_UNQUALIFIED");self.assertEqual(result["output_count"],31)
        self.assertEqual({v["dtype"] for v in result["outputs"]},{"float32","complex64","uint32"})
        self.assertFalse(result["scientific_operator_pass"]);self.assertEqual(result["numerical_qualification"],"NOT_QUALIFIED")
        gc.collect();self.assertTrue(all(ref() is None for ref in self.f.refs+self.f.views))

    def test_rhs_high_add_distinguishes_input_rounding(self):
        a=P["arrays"]()["HIGH"];b=P["arrays"]()["RHS"]
        self.assertEqual(int(a[1,0]),16777217);self.assertEqual(int(b[1,0]),1)
        self.assertNotEqual(np.float32(int(a[1,0])+int(b[1,0])),np.float32(np.float32(a[1,0])+np.float32(b[1,0])))

    def test_queued_receipt_only_queries_and_does_not_resubmit(self):
        self.f.queued=True;self.assertEqual(self.f.run()["status"],"RECORDED_UNQUALIFIED")
        operations=[line.split()[3] for line in self.f.calls]
        self.assertEqual(sum(op!="QUERY" for op in operations),33);self.assertEqual(self.f.created,31)

    def test_failed_parent_skips_children_without_fabricating_outputs(self):
        self.f.fail_fft_low=True;report=self.f.run();self.assertEqual(report["status"],"RECORDED_UNQUALIFIED")
        skipped=[v["label"] for v in report["checks"] if v.get("status")=="SKIPPED_DEPENDENCY_FAILED"]
        self.assertEqual(skipped,["ifft-LOW","inverse-real-LOW"]);self.assertEqual(self.f.observe()["output_count"],28)

    def test_unknown_is_not_recorded_terminal(self):
        original=self.f.exchange
        def exchange(*args):
            value=original(*args);value["state"]="unknown";return value
        with mock.patch.dict(os.environ,{"DM_NATIVE_SESSION":SESSION}):result=P["run"](str(self.f.truth_path),str(self.f.output),"prepared_uint32_operations_enabled",exchange)
        self.assertEqual(result["status"],"FAIL");self.assertIn("unknown is not success",result["error"])

    def test_timeout_preserves_single_submission(self):
        request=P["record"](SESSION,os.getpid(),"UNARY",[101,1],"known-before-submit")
        def exchange(session,wire,remaining):
            self.f.calls.append(wire)
            return {"protocol":"NB2","session":session,"id":request["id"],"state":"queued","host_pid":os.getpid(),"worker_tid":200,"exec_tid":0,
                "timings_us":{"queue":0,"execute":0},"original_operation":"UNARY","normalized_args":[101,1],"result_type":"native_image_operation","result_version":1}
        with self.assertRaisesRegex(RuntimeError,"submitted operation may still execute"):P["submit"](request,exchange,timeout=0)
        self.assertEqual(self.f.calls,[request["wire"]])

    def test_wrong_pid_and_session_and_timing_rejected_at_shared_receipt_guard(self):
        request=P["record"](SESSION,os.getpid(),"STATUS",[],"status")
        original=self.f.exchange(SESSION,request["wire"],1)
        for field,value in (("host_pid",os.getpid()+1),("session","f"*32),("exec_tid",200),("timings_us",{"queue":-1,"execute":0}),
                            ("timings_us",{"queue":False,"execute":0}),("timings_us",{"queue":0,"execute":0,"other":0})):
            with self.subTest(field=field,value=value):
                receipt=copy.deepcopy(original);receipt[field]=value
                with self.assertRaises(RuntimeError):P["validate_receipt"](receipt,request)

    def test_wrong_observation_host_is_not_overridden_by_env(self):
        self.f.run();self.f.report["host_pid"]+=1
        with mock.patch.dict(os.environ,{"DM_NATIVE_HOST_PID":str(self.f.report["host_pid"])}):
            with self.assertRaisesRegex(RuntimeError,"actual PID/session"):self.f.observe()

    def test_snapshot_dtype_mismatch_rejected(self):
        self.f.run();self.f.images[1000]["values"]=self.f.images[1000]["values"].astype(np.uint32)
        with self.assertRaisesRegex(RuntimeError,"raw view dtype/shape"):self.f.observe()

    def test_alias_raw_views_rejected_before_copy(self):
        self.f.run();self.f.images[1000]["code"]=11;self.f.images[1000]["values"]=self.f.images[101]["values"].view()
        receipt=self.f.report["checks"][1]["receipt"];receipt["result"]["image"]=self.f.metadata(1000)
        for recovery in self.f.report["recovered"]:
            if recovery["request"]["id"]==receipt["id"]:recovery["receipt"]=copy.deepcopy(receipt)
        with self.assertRaisesRegex(RuntimeError,"raw views share memory"):self.f.observe()

    def test_control_crop_is_bitwise_verified_before_show(self):
        self.f.run();result=self.f.observe()
        self.assertTrue(result["control_crop_verified"])
        self.assertEqual(result["control_crop_image_id"],1030)
        self.assertEqual(result["control_crop_rect"],[1,1,4,3])

    def test_control_crop_wrong_values_are_not_verified(self):
        self.f.run();self.f.images[1030]["values"][0,0]=0
        with self.assertRaisesRegex(RuntimeError,"control crop pixel"):self.f.observe()

    def test_control_crop_wrong_calibration_is_not_verified(self):
        self.f.run();self.f.images[1030]["intensity_calibration"]["origin"]=0
        with self.assertRaisesRegex(RuntimeError,"control crop spatial/intensity"):self.f.observe()

    def test_source_high_bits_and_calibration_are_protected(self):
        self.f.run();self.f.images[102]["values"][1,0]=16777216
        with self.assertRaisesRegex(RuntimeError,"source pixels/type/shape"):self.f.observe()

    def test_output_receipt_calibration_does_not_override_raw_host(self):
        self.f.run();self.f.images[1000]["calibration"][0]["scale"]=.25
        with self.assertRaisesRegex(RuntimeError,"signed calibration differs"):self.f.observe()

    def test_missing_matrix_or_modified_query_not_observed(self):
        self.f.run();self.f.report["recovered"][0]["receipt"]["timings_us"]["queue"]+=1
        with self.assertRaisesRegex(RuntimeError,"QUERY recovery mismatch"):self.f.observe()

    def test_repeat_probe_output_directory_is_exclusive(self):
        self.f.run()
        with self.assertRaises(FileExistsError):self.f.run()


if __name__=="__main__":unittest.main()
