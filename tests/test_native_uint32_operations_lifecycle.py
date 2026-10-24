# -*- coding: utf-8 -*-
"""Synthetic ownership faults only; never opens a native pipe or real DM."""
import copy
import gc
import os
from pathlib import Path
import runpy
import sys
import tempfile
import types
import unittest
from unittest import mock

from test_native_uint32_operations_probe import Synthetic, save, MVP, P

with mock.patch.object(sys,"path",[str(MVP)]+sys.path):
    L=runpy.run_path(str(MVP/"verify_uint32_operations_lifecycle.py"))


class Uint32OperationsLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.directory=Path(self.temp.name)
        self.f=Synthetic(self.directory);self.f.run();observation=self.f.observe()
        self.observation_path=self.directory/"observation.json";save(self.observation_path,observation)
        self.original_ids=set(range(1000,1031));self.shown=1030;self.source_ids=list(range(101,108));self.docs=self.source_ids+[self.shown]
        self.request=P["record"](self.f.truth["session"],os.getpid(),"SHOW",[self.shown],"predeclared-show")
        self.receipt={"protocol":"NB2","session":self.f.truth["session"],"id":self.request["id"],"state":"completed","host_pid":os.getpid(),
            "worker_tid":200,"exec_tid":100,"timings_us":{"queue":0,"execute":0},"original_operation":"SHOW","normalized_args":[self.shown],
            "result_type":"image_delivery","result_version":1,"result":{"backend":"digitalmicrograph-native","image_id":self.shown,
             "delivery":"visible_dm_document","document_visible":True,"operator":"ImageGetOrCreateImageDocument + ImageDocumentShow",
             "source_write_requested":False,"snapshot_atomic":False,"file_saved":False,"model_visual_verification":False,
             "image":self.f.metadata(self.shown),"candidate_probe":True,"qualification":"NOT_QUALIFIED"}}
        self.reuse=P["record"](self.f.truth["session"],os.getpid(),"SHOW",[self.shown],"predeclared-show-reuse")
        reuse_receipt=copy.deepcopy(self.receipt);reuse_receipt["id"]=self.reuse["id"]
        values={"SHOW_REQUEST":self.request,"SHOW_RECEIPT":self.receipt,"SHOW_REPEAT":{"request":self.request,"receipt":self.receipt},
            "SHOW_QUERY":{"request":P["record"](self.f.truth["session"],os.getpid(),"QUERY",[],self.request["id"]),"receipt":self.receipt},
            "SHOW_REUSE_REQUEST":self.reuse,"SHOW_REUSE_RECEIPT":reuse_receipt}
        self.env={"DM_NATIVE_U32_OPS_TRUTH":str(self.f.truth_path),"DM_NATIVE_U32_OPS_PROBE":str(self.f.probe_path),
            "DM_NATIVE_U32_OPS_LEDGER":str(self.f.ledger_path),"DM_NATIVE_U32_OPS_OBSERVATION":str(self.observation_path)}
        for key,value in values.items():
            filename=self.directory/(key.lower()+".json");save(filename,value);self.env["DM_NATIVE_U32_OPS_"+key]=str(filename)

    def module(self):
        module=self.f.module();find=module.FindImageByID;fixture=self
        class Doc:
            def __init__(self,image_id):self.image_id=image_id
            def CountImages(self):return 1
            def GetImage(self,index):return find(self.image_id)
        return types.SimpleNamespace(FindImageByID=find,CountImageDocumentsOfAllWorkspaces=lambda:len(fixture.docs),
            GetImageDocumentOfAllWorkspaces=lambda index:Doc(fixture.docs[index]))

    def phase(self,phase):
        with mock.patch.dict(os.environ,self.env),mock.patch.dict(sys.modules,{"DigitalMicrograph":self.module()}):
            context=L["load_context"](str(self.directory),phase);report={"numerical_qualification":"NOT_QUALIFIED","scientific_operator_pass":False}
            L["collect"](report,context,phase)
        filename=self.directory/("uint32-lifecycle-"+phase+".json");save(filename,report)
        return report

    def stop(self):
        request=P["record"](self.f.truth["session"],os.getpid(),"STOP",[],"predeclared-stop")
        receipt=copy.deepcopy(self.receipt);receipt.update(id=request["id"],original_operation="STOP",normalized_args=[],result_type="ipc_stop",exec_tid=0,result={"ipc_stopped":True})
        save(self.directory/"stop-request.json",request);save(self.directory/"stop-receipt.json",receipt)
        for image_id in self.original_ids-{self.shown}:self.f.images.pop(image_id)

    def test_all_three_phases_keep_source_and_only_document_retains_crop(self):
        before=self.phase("before_stop");self.assertEqual(len(before["live_output_ids"]),31)
        self.stop();after=self.phase("after_stop");self.assertEqual(after["live_output_ids"],[self.shown]);self.assertEqual(len(after["released_output_ids"]),30)
        self.f.images.pop(self.shown);self.docs=self.source_ids[:];closed=self.phase("after_close")
        self.assertEqual(closed["live_output_ids"],[]);self.assertEqual(closed["total_documents"],7)
        self.assertEqual(closed["numerical_qualification"],"NOT_QUALIFIED")
        gc.collect();self.assertTrue(all(ref() is None for ref in self.f.refs+self.f.views))

    def test_timing_keyset_and_safe_integer_values_are_strict(self):
        context={"session":self.f.truth["session"],"host_thread":100,"worker_tid":200,"operation_request_ids":set()}
        for timing in (None,{}, {"queue":0}, {"queue":-1,"execute":0},{"queue":.5,"execute":0},
                       {"queue":False,"execute":0},{"queue":2**53,"execute":0},{"queue":0,"execute":0,"extra":0}):
            with self.subTest(timing=timing):
                receipt=copy.deepcopy(self.receipt);receipt["timings_us"]=timing
                with self.assertRaisesRegex(RuntimeError,"timing|timings"):L["strict_saved"](self.request,receipt,"SHOW",[self.shown],context)
        L["strict_saved"](self.request,self.receipt,"SHOW",[self.shown],context)

    def test_wrong_pid_session_operation_target_and_worker_rejected(self):
        context={"session":self.f.truth["session"],"host_thread":100,"worker_tid":200,"operation_request_ids":set()}
        for field,value in (("host_pid",os.getpid()+1),("session","f"*32),("original_operation","CROP"),("normalized_args",[self.shown+1]),("worker_tid",201),("exec_tid",0)):
            with self.subTest(field=field):
                receipt=copy.deepcopy(self.receipt);receipt[field]=value
                with self.assertRaisesRegex(RuntimeError,"identity mismatch"):L["strict_saved"](self.request,receipt,"SHOW",[self.shown],context)

    def test_duplicate_show_receipt_must_be_original_immutable_record(self):
        name=self.env["DM_NATIVE_U32_OPS_SHOW_REPEAT"];value={"request":self.request,"receipt":copy.deepcopy(self.receipt)}
        value["receipt"]["timings_us"]["execute"]+=1;save(name,value)
        with self.assertRaisesRegex(RuntimeError,"SHOW replay receipt"):self.phase("before_stop")

    def test_new_show_request_cannot_reuse_original_id(self):
        save(self.env["DM_NATIVE_U32_OPS_SHOW_REUSE_REQUEST"],self.request)
        with self.assertRaisesRegex(RuntimeError,"original saved SHOW"):self.phase("before_stop")

    def test_matching_document_requires_explicit_image_not_latest(self):
        self.docs[-1]=101
        with self.assertRaisesRegex(RuntimeError,"document identity/count"):self.phase("before_stop")

    def test_after_stop_unshown_output_must_be_invalid(self):
        self.phase("before_stop");saved=self.f.images[1000];self.stop();self.f.images[1000]=saved
        with self.assertRaisesRegex(RuntimeError,"release/ownership"):self.phase("after_stop")

    def test_before_phase_cannot_bypass_preexisting_stop(self):
        self.stop()
        with self.assertRaisesRegex(RuntimeError,"already has STOP"):self.phase("before_stop")

    def test_after_close_must_release_final_crop(self):
        self.phase("before_stop");self.stop();self.phase("after_stop");self.docs=self.source_ids[:]
        with self.assertRaisesRegex(RuntimeError,"release/ownership"):self.phase("after_close")

    def test_stop_wrong_thread_is_rejected_before_live_lookup(self):
        self.phase("before_stop");self.stop()
        filename=self.directory/"stop-receipt.json";receipt=copy.deepcopy(self.receipt)
        receipt.update(id="predeclared-stop",original_operation="STOP",normalized_args=[],result_type="ipc_stop",result={"ipc_stopped":True})
        save(filename,receipt)
        with self.assertRaisesRegex(RuntimeError,"STOP receipt identity"):self.phase("after_stop")


if __name__=="__main__":unittest.main()
