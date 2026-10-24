# -*- coding: utf-8 -*-
"""Synthetic lifecycle-oracle guards; no IPC, UI or real DM is used."""
import contextlib
import copy
import gc
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import sys
import unittest
from unittest import mock
import weakref

from test_native_operations_oracle import Harness, MVP

with mock.patch.object(sys,"path",[str(MVP)]+sys.path):
    LIFECYCLE = runpy.run_path(str(MVP/"verify_operations_lifecycle.py"))


def dump(path,value):
    with open(str(path),"x",encoding="utf-8") as output:
        json.dump(value,output)


class NativeOperationsLifecycleTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.h = Harness(self.tmp.name)
        self.directory = Path(self.tmp.name)
        observation = self.h.collect()
        truth_raw = json.dumps(self.h.truth).encode("utf-8")
        operations_raw = json.dumps(self.h.observed).encode("utf-8")
        ledger_raw = "".join(json.dumps(row)+"\n" for row in self.h.records).encode("utf-8")
        for name,raw in (("operations-truth.json",truth_raw),("operations-report.json",operations_raw),
                         ("operations-requests.jsonl",ledger_raw)):
            (self.directory/name).write_bytes(raw)
        observation.update(status="RECORDED_PARTIAL_QUALIFICATION",host_pid=os.getpid(),
            session=self.h.truth["session"],truth_sha256=hashlib.sha256(truth_raw).hexdigest(),
            operations_report_sha256=hashlib.sha256(operations_raw).hexdigest(),
            requests_sha256=hashlib.sha256(ledger_raw).hexdigest())
        dump(self.directory/"operations-observation-01.json",observation)
        self.shown_id = self.h.observed["outputs"][0]["image_id"]
        self.output_ids = {entry["image_id"] for entry in self.h.observed["outputs"]}
        self.documents = [[image_id] for image_id in self.h.ids.values()]+[[self.shown_id]]
        request,receipt = self.record("SHOW",[self.shown_id],"original-show")
        dump(self.directory/"operations-show-request.json",request)
        dump(self.directory/"operations-show-receipt.json",receipt)

    def record(self,op,args,request_id):
        request = {"protocol":"NB2","session":self.h.truth["session"],"id":request_id,"op":op,"args":args,
                   "host_pid":os.getpid(),"wire":"NB2 %s %s %s%s\n" %
                   (self.h.truth["session"],request_id,op," "+" ".join(map(str,args)) if args else "")}
        result = ({"ipc_stopped":True} if op=="STOP" else
                  {"backend":"digitalmicrograph-native","image_id":self.shown_id,"delivery":"visible_dm_document",
                   "document_visible":True,"operator":"ImageGetOrCreateImageDocument + ImageDocumentShow",
                   "source_write_requested":False,"snapshot_atomic":False,"file_saved":False,
                   "model_visual_verification":False})
        receipt = {"protocol":"NB2","session":self.h.truth["session"],"id":request_id,"state":"completed",
                   "host_pid":os.getpid(),"worker_tid":200,"exec_tid":0 if op=="STOP" else 100,
                   "original_operation":op,"normalized_args":args[:],"result_type":"ipc_stop" if op=="STOP" else "image_delivery",
                   "result_version":1,"timings_us":{"queue":0,"execute":1},"result":result}
        return request,receipt

    def save_stop(self):
        request,receipt = self.record("STOP",[],"original-stop")
        dump(self.directory/"stop-request.json",request)
        dump(self.directory/"stop-receipt.json",receipt)

    def fake_module(self):
        module = self.h.fake_module()
        test = self
        class Document:
            def __init__(self,ids):
                self.ids = ids
                test.h.wrappers.append(weakref.ref(self))
            def CountImages(self):
                return len(self.ids)
            def GetImage(self,index):
                return module.FindImageByID(self.ids[index])
        module.CountImageDocumentsOfAllWorkspaces = lambda: len(self.documents)
        module.GetImageDocumentOfAllWorkspaces = lambda index: Document(self.documents[index])
        return module

    def run_phase(self,phase,expected=None):
        environment = {"DM_NATIVE_EVIDENCE_DIR":str(self.directory),"DM_NATIVE_LIFECYCLE_PHASE":phase}
        with mock.patch.dict(os.environ,environment),mock.patch.dict(sys.modules,{"DigitalMicrograph":self.fake_module()}):
            with contextlib.redirect_stdout(io.StringIO()):
                code = LIFECYCLE["main"]()
        path = self.directory/("operations-lifecycle-"+phase+".json")
        report = json.loads(path.read_text(encoding="utf-8"))
        if expected:
            self.assertEqual(code,1)
            self.assertEqual(report["status"],"FAIL")
            self.assertIn(expected,report["error"])
        else:
            self.assertEqual(code,0,report)
            self.assertEqual(report["status"],"PASS_NATIVE_RESULT_LIFECYCLE_PHASE")
        gc.collect()
        self.assertTrue(all(reference() is None for reference in self.h.views+self.h.wrappers))
        return report

    def stop_release(self):
        for image_id in self.output_ids-{self.shown_id}:
            self.h.images.pop(image_id)

    def test_all_three_phases_only_shown_doc_retains_result_then_final_release(self):
        before = self.run_phase("before_stop")
        self.assertEqual(len(before["live_output_ids"]),32)
        self.assertEqual(before["released_output_ids"],[])
        self.save_stop()
        self.stop_release()
        after = self.run_phase("after_stop")
        self.assertEqual(after["live_output_ids"],[self.shown_id])
        self.assertEqual(len(after["released_output_ids"]),31)
        self.assertTrue(after["stop_request_verified"])
        self.assertEqual(after["total_documents"],9)
        self.h.images.pop(self.shown_id)
        self.documents.pop()
        closed = self.run_phase("after_close")
        self.assertEqual(closed["live_output_ids"],[])
        self.assertEqual(len(closed["released_output_ids"]),32)
        self.assertEqual(closed["total_documents"],8)
        self.assertEqual(closed["matching_documents"],0)
        self.assertEqual(closed["ui_visibility"],"NOT_TESTED_BY_THIS_SCRIPT")

    def test_show_wrong_wire_before_any_host_observation(self):
        path = self.directory/"operations-show-request.json"
        value = json.loads(path.read_text())
        value["wire"] = value["wire"].rstrip()+" 1\n"
        path.write_text(json.dumps(value))
        count = len(self.h.views)
        self.run_phase("before_stop","Saved SHOW wire mismatch")
        self.assertEqual(len(self.h.views),count)

    def test_show_unknown_state_is_not_delivery(self):
        path = self.directory/"operations-show-receipt.json"
        value = json.loads(path.read_text()); value["state"]="unknown"; path.write_text(json.dumps(value))
        self.run_phase("before_stop","Saved SHOW receipt identity mismatch")

    def test_before_stop_with_dangling_stop_record_is_rejected(self):
        dump(self.directory/"stop-request.json",self.record("STOP",[],"dangling")[0])
        self.run_phase("before_stop","existing or ambiguous STOP evidence")

    def test_stop_wrong_pid_cannot_use_consistent_receipt_pair(self):
        self.run_phase("before_stop")
        request,receipt = self.record("STOP",[],"original-stop")
        request["host_pid"] = receipt["host_pid"] = os.getpid()+1
        dump(self.directory/"stop-request.json",request)
        dump(self.directory/"stop-receipt.json",receipt)
        self.run_phase("after_stop","Invalid original saved STOP request")

    def test_stop_wrong_worker_or_exec_tid_is_rejected(self):
        self.run_phase("before_stop")
        self.save_stop()
        path = self.directory/"stop-receipt.json"
        receipt = json.loads(path.read_text()); receipt["exec_tid"]=100; path.write_text(json.dumps(receipt))
        self.run_phase("after_stop","Saved STOP receipt identity mismatch")

    def test_still_live_unshown_result_blocks_release_claim(self):
        self.run_phase("before_stop")
        self.save_stop()
        self.run_phase("after_stop","Unexpected live/released result ownership")

    def test_registry_exception_is_not_proof_of_invalid_output(self):
        self.run_phase("before_stop")
        self.save_stop()
        self.stop_release()
        module = self.fake_module()
        original = module.FindImageByID
        bad = next(image_id for image_id in sorted(self.output_ids) if image_id!=self.shown_id)
        def find(image_id):
            if image_id==bad:
                raise RuntimeError("fake invalid lookup exception")
            return original(image_id)
        module.FindImageByID = find
        with mock.patch.object(self,"fake_module",return_value=module):
            self.run_phase("after_stop","fake invalid lookup exception")

    def test_wrong_shown_pixels_after_stop_blocks_ownership_pass(self):
        self.run_phase("before_stop")
        self.save_stop()
        self.stop_release()
        self.h.images[self.shown_id]["values"][0,0] += 1
        self.run_phase("after_stop","Current output pixels/dtype/shape changed")

    def test_prior_phase_wrong_hash_is_not_accepted(self):
        self.run_phase("before_stop")
        self.save_stop()
        path=self.directory/"operations-lifecycle-before_stop.json"
        previous=json.loads(path.read_text()); previous["truth_sha256"]="0"*64; path.write_text(json.dumps(previous))
        self.run_phase("after_stop","Previous lifecycle phase bound to different evidence")

    def test_after_close_requires_target_invalid_not_only_document_count(self):
        self.run_phase("before_stop")
        self.save_stop()
        self.stop_release()
        self.run_phase("after_stop")
        self.documents.pop()
        self.run_phase("after_close","Unexpected live/released result ownership")

    def test_source_document_swap_is_rejected_with_same_count(self):
        self.documents[0]=[self.h.ids["B"]]
        self.run_phase("before_stop","Source document membership changed")

    def test_snapshot_payload_change_is_not_an_ownership_truth(self):
        path=self.directory/"snapshots"/("output_"+str(self.shown_id)+".npy")
        raw=bytearray(path.read_bytes()); raw[-1]^=1; path.write_bytes(raw)
        self.run_phase("before_stop","Original output snapshot/hash changed")


if __name__=="__main__":
    unittest.main()
