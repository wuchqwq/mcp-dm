# -*- coding: utf-8 -*-
"""Two explicit uint32 result documents and STOP; synthetic host only."""
import copy
import gc
import os
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

from test_native_uint32_production_oracle import SyntheticProduction,S,MVP,save

with mock.patch.object(sys,"path",[str(MVP)]+sys.path):L=runpy.run_path(str(MVP/"verify_uint32_production_lifecycle.py"))


@unittest.skipUnless(shutil.which("node"),"Offline native encoder requires Node; no download")
class Uint32ProductionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.directory=Path(self.temp.name)
        self.f=SyntheticProduction(self.directory);self.f.build();independent=self.f.run()
        self.observation_path=self.directory/"uint32-production-independent.json";save(self.observation_path,independent)
        self.source_ids=[entry["id"] for entry in self.f.truth["images"]];self.shown=[self.f.label_ids[label] for label in S["SHOW_TARGETS"]]
        self.output_ids=set(self.f.label_ids.values());self.doc_ids=self.source_ids+self.shown
        self.env={"DM_NATIVE_U32_PROD_TRUTH":str(self.f.truth_path),"DM_NATIVE_U32_PROD_REPORT":str(self.f.report_path),
                  "DM_NATIVE_U32_PROD_LEDGER":str(self.f.ledger),"DM_NATIVE_U32_PROD_RECOVERY_LEDGER":str(self.f.recovery),"DM_NATIVE_U32_PROD_OBSERVATION":str(self.observation_path)}
        manifest={"schema":1,"host_pid":os.getpid(),"session":self.f.truth["session"],"targets":[]}
        for index,(label,image_id) in enumerate(zip(S["SHOW_TARGETS"],self.shown)):
            request=S["record"](self.f.truth["session"],os.getpid(),"SHOW",[image_id],"original-show-"+str(index))
            receipt={"protocol":"NB2","session":self.f.truth["session"],"id":request["id"],"state":"completed","host_pid":os.getpid(),"exec_tid":100,"worker_tid":200,
                "timings_us":{"queue":0,"execute":0},"original_operation":"SHOW","normalized_args":[image_id],"result_type":"image_delivery","result_version":1,
                "result":{"backend":"digitalmicrograph-native","image_id":image_id,"image":self.f.metadata(image_id),"delivery":"visible_dm_document","document_visible":True,
                    "operator":"ImageGetOrCreateImageDocument + ImageDocumentShow","source_write_requested":False,"snapshot_atomic":False,"file_saved":False,"model_visual_verification":False}}
            reuse=S["record"](self.f.truth["session"],os.getpid(),"SHOW",[image_id],"reuse-show-"+str(index));reuse_receipt=copy.deepcopy(receipt);reuse_receipt["id"]=reuse["id"]
            values={"request":request,"receipt":receipt,"repeat":{"request":request,"receipt":receipt},
                    "query":{"request":S["record"](self.f.truth["session"],os.getpid(),"QUERY",[],request["id"]),"receipt":receipt},
                    "reuse_request":reuse,"reuse_receipt":reuse_receipt}
            target={"label":label}
            for key,value in values.items():
                filename=self.directory/("show-"+str(index)+"-"+key+".json");save(filename,value);target[key]=str(filename)
            manifest["targets"].append(target)
        self.manifest=manifest;self.manifest_path=self.directory/"uint32-production-shows.json";save(self.manifest_path,manifest)

    def module(self):
        fixture=self;find=self.f.module().FindImageByID
        class Document:
            def __init__(self,image_id):self.image_id=image_id
            def CountImages(self):return 1
            def GetImage(self,index):return find(self.image_id)
        return types.SimpleNamespace(FindImageByID=find,CountImageDocumentsOfAllWorkspaces=lambda:len(fixture.doc_ids),
            GetImageDocumentOfAllWorkspaces=lambda index:Document(fixture.doc_ids[index]))

    def phase(self,phase):
        with mock.patch.dict(os.environ,self.env),mock.patch.dict(sys.modules,{"DigitalMicrograph":self.module()}):
            context=L["load_context"](str(self.directory),phase);report={};L["collect"](report,context,phase)
        save(self.directory/("uint32-production-"+phase+".json"),report);return report

    def stop(self):
        request=S["record"](self.f.truth["session"],os.getpid(),"STOP",[],"original-stop")
        receipt={"protocol":"NB2","session":self.f.truth["session"],"id":request["id"],"state":"completed","host_pid":os.getpid(),"exec_tid":0,"worker_tid":200,
            "timings_us":{"queue":0,"execute":0},"original_operation":"STOP","normalized_args":[],"result_type":"ipc_stop","result_version":1,"result":{"ipc_stopped":True}}
        save(self.directory/"stop-request.json",request);save(self.directory/"stop-receipt.json",receipt)
        for image_id in self.output_ids-set(self.shown):self.f.images.pop(image_id)

    def test_all_phases_two_docs_only_hold_two_results_after_stop(self):
        before=self.phase("before_stop");self.assertEqual(len(before["live_output_ids"]),32);self.assertEqual(before["total_documents"],11)
        self.stop();after=self.phase("after_stop");self.assertEqual(after["live_output_ids"],sorted(self.shown));self.assertEqual(len(after["released_output_ids"]),30)
        for image_id in self.shown:self.f.images.pop(image_id)
        self.doc_ids=self.source_ids[:];closed=self.phase("after_close");self.assertEqual(closed["released_output_ids"],sorted(self.output_ids));self.assertEqual(closed["total_documents"],9)
        gc.collect();self.assertTrue(all(ref() is None for ref in self.f.refs+self.f.views))

    def test_second_document_must_contain_filter_exact_id(self):
        self.doc_ids[-1]=self.shown[0]
        with self.assertRaisesRegex(RuntimeError,"two SHOW exact document"):self.phase("before_stop")

    def test_prepared_show_payload_not_accepted_as_production(self):
        filename=self.manifest["targets"][0]["receipt"];import json
        receipt=json.loads(Path(filename).read_bytes());receipt["result"].update(candidate_probe=True,qualification="NOT_QUALIFIED");save(filename,receipt)
        with self.assertRaisesRegex(RuntimeError,"candidate-only"):self.phase("before_stop")

    def test_stop_wrong_identity_or_timing_cannot_be_ownership_proof(self):
        self.phase("before_stop");self.stop();filename=self.directory/"stop-receipt.json";import json
        original=json.loads(filename.read_bytes())
        for field,value in (("host_pid",os.getpid()+1),("session","f"*32),("exec_tid",100),("original_operation","SHOW"),("timings_us",{"queue":0,"execute":0,"extra":0})):
            with self.subTest(field=field):
                receipt=copy.deepcopy(original);receipt[field]=value;save(filename,receipt)
                with self.assertRaisesRegex(RuntimeError,"STOP receipt identity|timing"):self.phase("after_stop")

    def test_unshown_result_still_alive_after_stop_is_failure(self):
        self.phase("before_stop");saved=self.f.images[self.f.label_ids["unary-HIGH-1"]];self.stop();self.f.images[self.f.label_ids["unary-HIGH-1"]]=saved
        with self.assertRaisesRegex(RuntimeError,"release/ownership"):self.phase("after_stop")

    def test_capture_npy_bytes_must_survive_stop(self):
        self.phase("before_stop");self.stop();capture=self.f.report["captures"][0]
        filename=Path(capture["receipt"]["capture_dir"])/"input.npy";data=bytearray(filename.read_bytes());data[-1]^=1;filename.write_bytes(data)
        with self.assertRaisesRegex(RuntimeError,"capture/evidence bytes changed"):self.phase("after_stop")

    def test_closing_only_one_document_cannot_complete_after_close(self):
        self.phase("before_stop");self.stop();self.phase("after_stop");self.f.images.pop(self.shown[0]);self.doc_ids=self.source_ids+[self.shown[1]]
        with self.assertRaisesRegex(RuntimeError,"release/ownership"):self.phase("after_close")


if __name__=="__main__":unittest.main()
