# -*- coding: utf-8 -*-
"""Offline STOP/ownership fault cases. Synthetic module only, never real DM."""
import copy
import gc
import io
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest import mock

from test_native_handoff_oracle import Handoff, MVP, SESSION, save, sha

with mock.patch.object(sys, "path", [str(MVP)] + sys.path):
    STOPPED = runpy.run_path(str(MVP / "verify_handoff_stopped.py"))


class StoppedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.handoff = Handoff(self.temp.name)
        self.independent = Path(self.temp.name)/"independent.json"
        observed = self.handoff.run()
        observed.update(schema=1,kind="synthetic-only")
        save(self.independent,observed)
        self.output_ids = [key for key in self.handoff.h.images if key >= 1000]
        self.original_data = {key:self.handoff.h.images.pop(key) for key in self.output_ids}
        self.request = {"protocol":"NB2","session":SESSION,"id":"original-stop","op":"STOP","args":[],
                        "host_pid":os.getpid(),"wire":"NB2 %s original-stop STOP\n" % SESSION}
        self.receipt = {"protocol":"NB2","session":SESSION,"id":"original-stop","state":"completed","host_pid":os.getpid(),
                        "exec_tid":0,"worker_tid":200,"original_operation":"STOP","normalized_args":[],
                        "result_type":"ipc_stop","result_version":1,"timings_us":{"queue":1,"execute":1},"result":{"ipc_stopped":True}}
        self.request_path,self.receipt_path = Path(self.temp.name)/"stop-request.json",Path(self.temp.name)/"stop-receipt.json"
        self.prior = []

    def run_oracle(self):
        save(self.request_path,self.request);save(self.receipt_path,self.receipt)
        result = {"status":"FAIL"}
        with mock.patch.dict(sys.modules,{"DigitalMicrograph":self.handoff.h.fake_module()}):
            STOPPED["collect"](result,str(self.handoff.truth),str(self.handoff.report_path),str(self.handoff.ledger_path),
                str(self.independent),str(self.request_path),str(self.receipt_path),self.prior)
        return result

    def fails(self,message):
        with self.assertRaisesRegex(RuntimeError,message):self.run_oracle()

    def test_stopped_positive_nine_explicit_ids_and_persistent_captures(self):
        result = self.run_oracle()
        self.assertEqual(result["status"],"PASS_UNSHOWN_HANDOFF_STOPPED")
        self.assertEqual(result["released_output_ids"],self.output_ids)
        self.assertEqual(result["document_count"],9)
        self.assertEqual(result["capture_persistence"],"PASS_ORIGINAL_THREE_FILE_HASHES")
        gc.collect()
        self.assertTrue(all(ref() is None for ref in self.handoff.h.views+self.handoff.h.wrappers))

    def test_production_mode_stopped_positive(self):
        self.handoff.h.images.update(self.original_data)
        self.handoff.report["qualification_mode"] = "production"
        entry = self.handoff.report["checks"][0]
        status = json.loads(entry["response"]["content"][0]["text"])
        status.pop("candidate_execution_enabled")
        status["native_capabilities"] = [{"name":name,"available":True,"qualification":"LIMITED_REAL_HOST"}
            for name in ("native_image_arithmetic","native_fft","native_filters","native_preview","native_read")]
        entry["response"]["content"][0]["text"] = json.dumps(status)
        observed = self.handoff.run();observed.update(schema=1,kind="synthetic-only");save(self.independent,observed)
        for image_id in self.output_ids:self.handoff.h.images.pop(image_id)
        self.assertEqual(self.run_oracle()["qualification_mode"],"production")

    def test_wrong_stop_request_id(self):
        self.receipt["id"] = "another-stop"
        self.fails("STOP receipt identity")

    def test_wrong_stop_host(self):
        self.receipt["host_pid"] += 1
        self.fails("STOP receipt identity")

    def test_wrong_stop_session(self):
        self.request["session"] = "f"*32
        self.fails("original saved STOP")

    def test_stop_requires_original_op_args_wire(self):
        original = copy.deepcopy(self.request)
        for key,value in (("op","SHOW"),("args",[1000]),("wire","STOP\n")):
            with self.subTest(key=key):
                self.request = dict(original,**{key:value})
                self.fails("STOP request|STOP wire")

    def test_unknown_stop_not_accepted(self):
        self.receipt["state"] = "unknown"
        self.fails("STOP receipt identity")

    def test_stop_worker_and_exec_thread(self):
        original = copy.deepcopy(self.receipt)
        for key,value in (("worker_tid",201),("exec_tid",100)):
            with self.subTest(key=key):
                self.receipt = dict(original,**{key:value})
                self.fails("STOP receipt identity")

    def test_stop_success_payload_must_ack(self):
        self.receipt["result"] = {"ipc_stopped":False}
        self.fails("STOP was not acknowledged")

    def test_stop_id_cannot_reuse_original_operation(self):
        previous_id = self.handoff.records[1]["id"]
        self.request["id"] = self.receipt["id"] = previous_id
        self.request["wire"] = "NB2 %s %s STOP\n" % (SESSION,previous_id)
        self.fails("original saved STOP")

    def test_any_explicit_output_still_live_is_failure(self):
        self.handoff.h.images[self.handoff.square_id] = self.original_data[self.handoff.square_id]
        self.fails("result remains valid")

    def test_source_pixel_changed(self):
        self.handoff.h.images[self.handoff.source_id]["values"].view("<u4")[0,0] = 0
        self.fails("source pixels")

    def test_source_calibration_changed(self):
        self.handoff.h.images[self.handoff.source_id]["axes"][0]["scale"] *= -1
        self.fails("spatial/intensity calibration changed")

    def test_source_invalid(self):
        del self.handoff.h.images[self.handoff.source_id]
        self.fails("Independent image identity")

    def test_document_count_changed(self):
        self.handoff.h.doc_count = 10
        self.fails("document count changed")

    def test_npy_must_persist_original_bytes(self):
        path = Path(self.handoff.report["captures"][0]["receipt"]["capture_dir"])/"input.npy"
        path.write_bytes(path.read_bytes()[:-1]+b"x")
        self.fails("pre-STOP handoff evidence file changed")

    def test_wrong_previous_host_even_self_consistent_env(self):
        old = json.loads(self.independent.read_bytes());old["host_pid"] += 1;save(self.independent,old)
        with mock.patch.dict(os.environ,{"DM_NATIVE_HOST_PID":str(old["host_pid"])}):self.fails("successful same-host")

    def test_missing_or_changed_previous_proof_flags(self):
        old = json.loads(self.independent.read_bytes());old["independent_memory"] = "NOT_TESTED";save(self.independent,old)
        self.fails("successful same-host")

    def prior_prefix(self):
        directory = Path(self.temp.name)/"prior-failure";directory.mkdir()
        previous = copy.deepcopy(self.handoff.report)
        previous.update(status="FAIL",previews=[],extra_checks=[],captures=[])
        previous["checks"] = copy.deepcopy(previous["checks"][:3])
        records = []
        for index,entry in enumerate(previous["checks"]):
            request = entry["request"]
            request["id"] = "prior-"+str(index)
            if index == 2:request["args"][0] = 2000;entry["arguments"]["image_id"] = 2000
            request["wire"] = "NB2 %s %s %s%s\n" % (SESSION,request["id"],request["op"]," "+" ".join(map(str,request["args"])) if request["args"] else "")
            entry["arguments"]["request_id"] = request["id"]
            out = json.loads(entry["response"]["content"][0]["text"])
            out["native_receipt"].update(id=request["id"],request_id=request["id"],normalized_args=request["args"])
            if index:
                out["image_id"] = 1999+index;out["image"]["id"] = 1999+index
                if index==2:out["source_image_ids"] = [2000]
            entry["response"]["content"][0]["text"] = json.dumps(out)
            records.append(request)
        path = directory/"mcp-handoff-report.json";save(path,previous)
        (directory/"mcp-handoff-requests.jsonl").write_bytes(b"".join(json.dumps(r).encode()+b"\n" for r in records))
        self.prior = [str(path)]
        return path,previous,records

    def test_prior_failed_attempt_explicit_ids_included_without_qualifying_failure(self):
        self.prior_prefix()
        result = self.run_oracle()
        self.assertEqual(result["released_output_ids"],self.output_ids+[2000,2001])
        self.assertEqual(result["prior_failed_attempts"][0]["status"],"FAIL_PRESERVED")

    def test_prior_completed_producer_still_live(self):
        self.prior_prefix()
        self.handoff.h.images[2000] = self.original_data[1000]
        self.fails("result remains valid")

    def test_prior_wrong_host(self):
        path,previous,unused = self.prior_prefix();previous["host_pid"] += 1;save(path,previous)
        self.fails("failed prefix host/session")

    def test_prior_wrong_original_receipt(self):
        path,previous,unused = self.prior_prefix()
        out = json.loads(previous["checks"][1]["response"]["content"][0]["text"]);out["native_receipt"]["state"] = "unknown"
        previous["checks"][1]["response"]["content"][0]["text"] = json.dumps(out);save(path,previous)
        self.fails("receipt identity")

    def test_prior_unresolved_side_effect_not_ignored(self):
        path,unused,records = self.prior_prefix()
        request = dict(records[-1],id="prior-unresolved",wire="NB2 %s prior-unresolved UNARY 2000 3\n" % SESSION)
        records.append(request)
        (path.parent/"mcp-handoff-requests.jsonl").write_bytes(b"".join(json.dumps(r).encode()+b"\n" for r in records))
        self.fails("unresolved or unaccounted")

    def test_missing_original_stop_writes_failed_new_report_and_nonzero(self):
        target = Path(self.temp.name)/"failed-new-oracle.json"
        env = {"DM_NATIVE_EVIDENCE_DIR":self.temp.name,"DM_NATIVE_HANDOFF_TRUTH":str(self.handoff.truth),
            "DM_NATIVE_HANDOFF_REPORT":str(self.handoff.report_path),"DM_NATIVE_HANDOFF_LEDGER":str(self.handoff.ledger_path),
            "DM_NATIVE_HANDOFF_INDEPENDENT":str(self.independent),"DM_NATIVE_HANDOFF_STOPPED_OUTPUT":str(target),
            "DM_NATIVE_HANDOFF_STOP_REQUEST":str(self.request_path),"DM_NATIVE_HANDOFF_STOP_RECEIPT":str(self.receipt_path),
            "DM_NATIVE_HANDOFF_PRIOR_REPORTS":"[]"}
        with mock.patch.dict(os.environ,env),mock.patch("sys.stdout",io.StringIO()):
            self.assertEqual(STOPPED["main"](),1)
        report = json.loads(target.read_bytes())
        self.assertEqual(report["status"],"FAIL")
        self.assertEqual(report["error_type"],"FileNotFoundError")


if __name__ == "__main__":unittest.main()
