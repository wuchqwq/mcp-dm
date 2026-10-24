# -*- coding: utf-8 -*-
"""Offline fault tests for the independent oracle, never real-DM qualification."""
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
import tempfile
import types
import unittest
from unittest import mock
import weakref

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MVP = ROOT / "experiments" / "native-bridge" / "mvp"
with mock.patch.object(sys, "path", [str(MVP)] + sys.path):
    ORACLE = runpy.run_path(str(MVP / "verify_operations.py"))
SESSION = "0123456789abcdef0123456789abcdef"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def axes():
    return [{"dm_axis": 0, "origin": 1.25, "raw_origin": 5., "scale": -.25, "unit": "nm"},
            {"dm_axis": 1, "origin": -2.5, "raw_origin": 5., "scale": .5, "unit": "nm"}]


def metadata(image_id, data):
    shape, dtype = list(data["values"].shape), str(data["values"].dtype)
    typed = dtype in ("float32", "complex64")
    return {"id": image_id, "name": data["name"], "ndim": 2,
            "data_type_code": 2 if dtype == "float32" else 3 if dtype == "complex64" else 10,
            "dtype": dtype if typed else None, "packing_style": 1, "shape": shape,
            "dm_dimensions": shape[::-1], "shape_order": "numpy (last axis is X)",
            "pixels": int(data["values"].size), "native_mean_supported": dtype == "float32",
            "native_summary_supported": dtype == "float32", "calibration_complete": True,
            "coordinate_rule": "physical(i)=calibrated_value_at_pixel_zero+i*scale",
            "calibration": [{"dm_dimension": entry["dm_axis"], "numpy_axis": 1-entry["dm_axis"],
                             "size": shape[1-entry["dm_axis"]], "origin": entry["raw_origin"],
                             "calibrated_value_at_pixel_zero": entry["origin"], "scale": entry["scale"],
                             "unit": entry["unit"], "usable": True, "issue": None}
                            for entry in data["axes"]]}


class Harness:
    """A clearly synthetic module: views share its small in-memory test arrays."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.images, self.records, self.views, self.wrappers = {}, [], [], []
        self.point_fault = None
        self.mutate_source_on_output_read = False
        self.doc_count = 8
        a = np.array([[1.25,-2.5,3.75,4],[-5,6,7,-8],[9.25,10,-11,12],[13,14.5,15,-16]], dtype=np.float32)
        impulse = np.zeros((4,8), dtype=np.float32)
        impulse[1,2] = 1
        nonfinite = a.copy()
        nonfinite[1,2] = np.nan
        values = {"A": a, "B": np.full((4,4),2,dtype=np.float32),
                  "CONSTANT": np.full((4,4),3.25,dtype=np.float32), "IMPULSE": impulse,
                  "SINGLE_FREQUENCY": a.copy(), "NONFINITE": nonfinite,
                  "UINT16": np.arange(16,dtype=np.uint16).reshape(4,4),
                  "FILTER_A": np.arange(64,dtype=np.float32).reshape(8,8)}
        self.truth = {"schema":1, "kind":"synthetic-only", "status":"RECORDED", "session":SESSION,
                      "host_pid":os.getpid(), "python_is_listener":False, "initial_document_count":8, "images":[]}
        self.ids = {}
        for index, (label, array) in enumerate(values.items(), 17):
            self.ids[label] = index
            data = self.new_data(index, array, "synthetic-" + label)
            path = self.directory / (label + ".npy")
            np.save(str(path), array, allow_pickle=False)
            self.truth["images"].append({"id":index, "label":label, "name":data["name"],
                "dtype":str(array.dtype), "shape":list(array.shape), "source_npy":str(path),
                "source_file_sha256":sha(path.read_bytes()), "pixel_sha256":sha(array.tobytes(order="C")),
                "calibration":copy.deepcopy(data["axes"]), "intensity_calibration":copy.deepcopy(data["intensity"])})
        self.observed = {"schema":1, "kind":"synthetic-only", "status":"RECORDED", "session":SESSION,
                         "host_pid":os.getpid(), "checks":[], "outputs":[]}
        self.add("STATUS", [], "STATUS", {"backend":"digitalmicrograph-native", "ready":True,
            "binary_gate":True, "candidate_execution_enabled":True, "supported_build":"3.53.4137.0-x64",
            "host_pid":os.getpid(), "host_thread":100})
        self.add("DATASETS", [], "DATASETS", {"backend":"digitalmicrograph-native",
            "datasets":[metadata(key,data) for key,data in self.images.items()], "count":8,
            "complete":True, "snapshot_atomic":False})
        for label, op, args, error in [
            ("bad-unary-enum","UNARY",[self.ids["A"],99],"native_unary_opcode_unsupported"),
            ("unsupported-unary-dtype","UNARY",[self.ids["UINT16"],1],"native_arithmetic_requires_float32_2d"),
            ("nonfinite-unary","UNARY",[self.ids["NONFINITE"],1],"native_arithmetic_source_nonfinite"),
            ("invalid-source-id","UNARY",[0xffffffff,1],"image_not_found"),
            ("no-broadcast","BINARY",[self.ids["A"],self.ids["IMPULSE"],1],"native_binary_shape_mismatch"),
            ("nonfinite-fft","FFT",[self.ids["NONFINITE"]],"native_fft_nonfinite_source"),
            ("unsupported-fft-dtype","FFT",[self.ids["UINT16"]],"native_fft_input_type_or_dimensions_unsupported"),
            ("unsupported-filter-dtype","FILTER",[self.ids["UINT16"],1],"native_filter_requires_float32_2d_ordinary_packing")]:
            self.add(op,args,label,error=error)
        self.next_id = 1000
        for code in (1,2,3):
            self.output("UNARY",["A"],code)
        for code in (1,2,3):
            self.output("BINARY",["A","B"],code)
        frequencies = {}
        for label in ("CONSTANT","IMPULSE","SINGLE_FREQUENCY","A"):
            spectrum = self.output("FFT",[label])
            frequencies[label] = spectrum
            self.output("REAL",[label],parent=spectrum)
            self.output("IMAG",[label],parent=spectrum)
            inverse = self.output("IFFT",[label],parent=spectrum)
            self.output("IFFT_REAL",[label],parent=inverse)
        for op in ("VENDOR_ARG","VENDOR_NORM"):
            self.output(op,["A"],parent=frequencies["A"])
        for code in (1,2,3,4):
            self.output("FILTER",["FILTER_A"],code)
        self.sync_recovered()

    def new_data(self, image_id, values, name):
        self.images[image_id] = {"values":np.array(values,copy=True), "name":name, "axes":axes(),
                                "intensity":{"origin":7.5,"scale":-2.,"unit":"arb"}}
        return self.images[image_id]

    def add(self, op, args, label, result=None, error=None):
        request_id = "saved-" + str(len(self.records))
        self.records.append({"protocol":"NB2","session":SESSION,"host_pid":os.getpid(),"id":request_id,
            "op":op,"args":args[:],"wire":"NB2 %s %s %s%s\n" %
            (SESSION,request_id,op," "+" ".join(str(value) for value in args) if args else "")})
        receipt = {"protocol":"NB2","session":SESSION,"host_pid":os.getpid(),"id":request_id,
            "worker_tid":200,"exec_tid":100,"original_operation":op,"normalized_args":args[:],
            "result_version":1,"result_type":ORACLE["TYPES"][op],"state":"failed" if error else "completed"}
        if error:
            receipt.update(code="native_error",error=error)
        else:
            receipt["result"] = result
        self.observed["checks"].append({"label":label,"op":op,"args":args[:],"id":request_id,
                                       "receipt":receipt,"expected_failure":error is not None})

    def output(self, kind, labels, code=None, parent=None):
        op = "REAL" if kind == "IFFT_REAL" else kind
        source_ids = [self.ids[label] for label in labels] if parent is None else [parent]
        source = self.images[source_ids[0]]["values"]
        if kind == "UNARY":
            values = (-source,np.abs(source),source*source)[code-1]
        elif kind == "BINARY":
            rhs = self.images[source_ids[1]]["values"]
            values = (source+rhs,source-rhs,source*rhs)[code-1]
        elif kind == "FILTER":
            values = source.copy()  # never treated as a qualified native kernel
        else:
            values = np.full(source.shape, complex(self.next_id,.25) if kind in ("FFT","IFFT") else float(self.next_id),
                             dtype=np.complex64 if kind in ("FFT","IFFT") else np.float32)
        image_id = self.next_id
        self.next_id += 1
        data = self.new_data(image_id,values,"synthetic-output-" + str(image_id))
        entry = {"kind":kind,"source_labels":labels[:],"image_id":image_id}
        if code is not None:
            entry["opcode"] = code
        if parent is not None:
            entry["parent_image_id"] = parent
        self.observed["outputs"].append(entry)
        result = {"backend":"digitalmicrograph-native","image_id":image_id,"image":metadata(image_id,data),
                  "computation":"DM native","source_write_requested":False,"snapshot_atomic":False}
        if kind in ("UNARY","BINARY"):
            names = ("negate","abs","square") if kind == "UNARY" else ("add","subtract","multiply")
            operators = ("Negate","Abs","Square") if kind == "UNARY" else ("operator+","operator-","operator*")
            args, label = source_ids+[code], kind.lower()+"-"+str(code)
            result.update(operation=names[code-1],opcode=code,source_image_ids=source_ids[:],
                sources=[metadata(key,self.images[key]) for key in source_ids],
                operator="GMSImageProcessing::"+operators[code-1],intensity_calibration_applied=False,
                intensity_semantics="raw pixel intensity")
        else:
            args = source_ids+([code] if kind == "FILTER" else [])
            label = ("filter-"+str(code) if kind == "FILTER" else "fft-"+labels[0] if kind == "FFT" else
                     "ifft-"+labels[0] if kind == "IFFT" else "ifft-real-"+labels[0] if kind == "IFFT_REAL" else
                     kind+"-"+labels[0] if kind in ("REAL","IMAG") else kind)
            operators = {"FFT":"Real_FFT","IFFT":"IFFT","REAL":"Real","IMAG":"Imag","VENDOR_ARG":"Arg","VENDOR_NORM":"Norm"}
            result.update(operation=op,source_image_id=source_ids[0],source=metadata(source_ids[0],self.images[source_ids[0]]),
                operator="GMSImageProcessing::"+(("SmoothFilter","SobelFilter","LaplaceFilter","SharpenFilter")[code-1]
                                                if kind=="FILTER" else operators[op]))
            if kind == "FILTER":
                result.update(filter_kind=code,kernel="vendor_defined",edge_behavior="vendor_defined")
        self.add(op,args,label,result)
        return image_id

    def sync_recovered(self):
        self.observed["recovered"] = copy.deepcopy([check["receipt"] for check in self.observed["checks"]
                                                    if check["receipt"]["state"] == "completed"])

    def check(self, label):
        return next(check for check in self.observed["checks"] if check["label"] == label)

    def fake_module(self):
        harness = self

        class Image:
            def __init__(self, image_id):
                self.image_id = image_id
                harness.wrappers.append(weakref.ref(self))

            def IsValid(self):
                return self.image_id in harness.images

            def GetID(self):
                return self.image_id

            def GetName(self):
                return harness.images[self.image_id]["name"]

            def GetNumArray(self):
                if harness.point_fault == self.image_id:
                    raise RuntimeError("fake raw read failure")
                if harness.mutate_source_on_output_read and self.image_id >= 1000:
                    harness.images[harness.ids["A"]]["values"][0,0] += 1
                    harness.mutate_source_on_output_read = False
                view = harness.images[self.image_id]["values"].view()
                harness.views.append(weakref.ref(view))
                return view

            def GetDimensionCalibration(self, axis, mode):
                entry = harness.images[self.image_id]["axes"][axis]
                return entry["origin" if mode == 0 else "raw_origin"],entry["scale"],entry["unit"]

            def GetIntensityOrigin(self):
                return harness.images[self.image_id]["intensity"]["origin"]

            def GetIntensityScale(self):
                return harness.images[self.image_id]["intensity"]["scale"]

            def GetIntensityUnitString(self):
                return harness.images[self.image_id]["intensity"]["unit"]

        return types.SimpleNamespace(FindImageByID=lambda image_id: Image(image_id),
                                     CountImageDocumentsOfAllWorkspaces=lambda: harness.doc_count)

    def bind(self):
        self.sync_recovered()
        return ORACLE["bind_evidence"](self.truth,self.observed,self.records,os.getpid())

    def collect(self, name="snapshots"):
        self.bind()
        directory = self.directory / name
        directory.mkdir()
        report = {"outputs":[],"source_protection":"NOT_TESTED","fft_filters":"NOT_QUALIFIED"}
        with mock.patch.dict(sys.modules,{"DigitalMicrograph":self.fake_module()}):
            ORACLE["collect"](report,self.truth,self.observed,str(directory))
        return report


class NativeOperationsOracleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.h = Harness(self.tmp.name)

    def fails_bind(self, message):
        with self.assertRaisesRegex(RuntimeError,message):
            self.h.bind()

    def fails_collect(self, message):
        with self.assertRaisesRegex(RuntimeError,message):
            self.h.collect()
        gc.collect()
        self.assertTrue(all(reference() is None for reference in self.h.views+self.h.wrappers))

    def test_complete_offline_matrix_and_detached_view_cleanup(self):
        report = self.h.collect()
        self.assertEqual(report["source_protection"],"PASS")
        self.assertEqual(report["independent_memory"],"PASS")
        self.assertTrue(report["raw_views_and_wrappers_released"])
        self.assertEqual(report["output_count"],32)
        self.assertEqual(sum(entry["status"]=="PASS" for entry in report["outputs"]),6)
        self.assertEqual(sum(entry["status"]=="NOT_QUALIFIED" for entry in report["outputs"]),26)
        for entry in report["outputs"]:
            raw = Path(entry["snapshot"]).read_bytes()
            self.assertEqual(entry["snapshot_file_sha256"],sha(raw))
            saved = np.load(entry["snapshot"],allow_pickle=False)
            self.assertEqual(entry["pixel_sha256"],sha(saved.tobytes(order="C")))
        gc.collect()
        self.assertTrue(all(reference() is None for reference in self.h.views+self.h.wrappers))

    def test_wrong_real_host_and_session(self):
        self.h.truth["host_pid"] += 1
        self.fails_bind("not executing oracle process")
        self.h.truth["host_pid"] -= 1
        self.h.observed["session"] = "f" * 32
        self.fails_bind("Invalid synthetic evidence/session")

    def test_status_anchor_fields_are_not_receipt_self_consistency(self):
        base = copy.deepcopy(self.h.observed)
        for field,value in [("ready",False),("binary_gate",False),("candidate_execution_enabled",False),
                            ("backend","mock-native"),("host_pid",os.getpid()+1),("host_thread",True),
                            ("host_thread",101),("supported_build","other")]:
            with self.subTest(field=field,value=value):
                self.h.observed = copy.deepcopy(base)
                self.h.check("STATUS")["receipt"]["result"][field] = value
                self.fails_bind("STATUS host/build/readiness anchor mismatch")

    def test_deleted_output_and_deleted_case_cannot_shrink_acceptance(self):
        self.h.observed["outputs"].pop()
        self.fails_bind("Complete 32-output matrix required")

    def test_deleted_and_duplicate_receipts(self):
        original = copy.deepcopy(self.h.observed)
        self.h.observed["checks"].pop()
        self.fails_bind("Complete unique receipt matrix required")
        self.h.observed = copy.deepcopy(original)
        self.h.observed["checks"][-1] = copy.deepcopy(self.h.observed["checks"][0])
        self.fails_bind("Complete unique receipt matrix required")

    def test_duplicate_output_case_is_not_just_a_32_count(self):
        self.h.observed["outputs"][-1] = copy.deepcopy(self.h.observed["outputs"][0])
        self.fails_bind("Output matrix case missing/duplicate/unknown")

    def test_wrong_original_wire_and_arguments(self):
        self.h.records[10]["wire"] += " "
        self.fails_bind("Original submitted wire mismatch")
        self.h.records[10]["wire"] = self.h.records[10]["wire"][:-1]
        self.h.check("unary-1")["args"][1] = True
        self.fails_bind("Receipt original identity mismatch")

    def test_negative_capacity_unknown_and_exception_are_not_correct_rejection(self):
        original = copy.deepcopy(self.h.observed)
        for code,error,state in [("native_error","native_result_retention_capacity","failed"),
                                 ("native_exception","unknown C++ exception during native execution","failed"),
                                 ("native_error","native_unary_opcode_unsupported","unknown")]:
            with self.subTest(code=code,error=error,state=state):
                self.h.observed = copy.deepcopy(original)
                self.h.check("bad-unary-enum")["receipt"].update(code=code,error=error,state=state)
                self.fails_bind("Wrong completed/failed receipt state" if state=="unknown" else
                                "Negative case failed for wrong domain or capacity")

    def test_every_negative_domain_cannot_be_masked_by_a_full_pool(self):
        original = copy.deepcopy(self.h.observed)
        labels = [check["label"] for check in self.h.observed["checks"] if check["expected_failure"]]
        self.assertEqual(len(labels),8)
        for label in labels:
            with self.subTest(label=label):
                self.h.observed = copy.deepcopy(original)
                self.h.check(label)["receipt"]["error"] = "native_result_retention_capacity"
                self.fails_bind("Negative case failed for wrong domain or capacity")

    def test_thread_and_original_result_type(self):
        self.h.check("unary-1")["receipt"]["worker_tid"] = 201
        self.fails_bind("Native thread identity changed")
        self.h.check("unary-1")["receipt"]["worker_tid"] = 200
        self.h.check("unary-1")["receipt"]["result_type"] = "native_mean"
        self.fails_bind("Receipt original identity mismatch")

    def test_parent_lineage_cannot_be_relabelled(self):
        entry = next(entry for entry in self.h.observed["outputs"] if entry["kind"]=="IFFT_REAL")
        entry["parent_image_id"] = next(entry["image_id"] for entry in self.h.observed["outputs"] if entry["kind"]=="FFT")
        self.fails_bind("Derived result parent/lineage mismatch")

    def test_receipt_output_metadata_identity_shape_packing_calibration(self):
        original = copy.deepcopy(self.h.observed)
        mutations = [("id",999,"identity/name"),("shape",[2,8],"type/shape/packing"),
                     ("packing_style",2,"type/shape/packing"),("dtype","float64","type/shape/packing")]
        for index,(field,value,target) in enumerate(mutations):
            with self.subTest(field=field):
                self.h.observed = copy.deepcopy(original)
                self.h.check("unary-1")["receipt"]["result"]["image"][field] = value
                with self.assertRaisesRegex(RuntimeError,"Receipt metadata "+target+" mismatch"):
                    self.h.collect("bad-meta-"+str(index))
        self.h.observed = copy.deepcopy(original)
        self.h.check("unary-1")["receipt"]["result"]["image"]["calibration"][0]["scale"] = -.5
        self.fails_collect("Receipt metadata calibration number mismatch")

    def test_receipt_source_metadata_is_bound_to_actual_source(self):
        self.h.check("binary-1")["receipt"]["result"]["sources"][1]["name"] = "wrong-source"
        self.fails_collect("Receipt metadata identity/name mismatch")

    def test_wrong_operation_dtype_even_when_receipt_agrees_with_array(self):
        receipt = self.h.check("fft-CONSTANT")["receipt"]
        image_id = receipt["result"]["image_id"]
        self.h.images[image_id]["values"] = self.h.images[image_id]["values"].real.astype(np.float32)
        receipt["result"]["image"] = metadata(image_id,self.h.images[image_id])
        self.fails_collect("Operation output dtype/shape contract mismatch")

    def test_raw_output_source_alias_rejected_before_detaching(self):
        result_id = self.h.check("REAL-CONSTANT")["receipt"]["result"]["image_id"]
        self.h.images[result_id]["values"] = self.h.images[self.h.ids["CONSTANT"]]["values"]
        self.fails_collect("raw views share memory")

    def test_raw_output_output_alias_rejected(self):
        first = self.h.check("REAL-CONSTANT")["receipt"]["result"]["image_id"]
        second = self.h.check("IMAG-CONSTANT")["receipt"]["result"]["image_id"]
        self.h.images[second]["values"] = self.h.images[first]["values"]
        self.fails_collect("raw views share memory")

    def test_source_file_hash_and_saved_pixel_oracle_are_both_checked(self):
        source = self.h.truth["images"][0]
        path = Path(source["source_npy"])
        changed = np.load(str(path),allow_pickle=False)
        changed[0,0] += 1
        np.save(str(path),changed,allow_pickle=False)
        self.fails_collect("Source oracle file changed")

    def test_saved_pixels_not_just_self_consistent_file_hash(self):
        source = self.h.truth["images"][0]
        path = Path(source["source_npy"])
        changed = np.load(str(path),allow_pickle=False)
        changed[0,0] += 1
        np.save(str(path),changed,allow_pickle=False)
        source["source_file_sha256"] = sha(path.read_bytes())
        self.fails_collect("Saved source oracle dtype/shape/pixels mismatch")

    def test_source_and_output_intensity_preservation(self):
        source_id = self.h.ids["A"]
        self.h.images[source_id]["intensity"]["scale"] = 1.
        self.fails_collect("Source calibration changed")

    def test_source_spatial_and_pixel_mutations(self):
        self.h.images[self.h.ids["A"]]["axes"][0]["origin"] += 1
        self.fails_collect("Source calibration changed")

    def test_source_pixel_mutation_during_observation_is_detected_on_final_reread(self):
        self.h.mutate_source_on_output_read = True
        self.fails_collect("Source pixel/dtype/shape changed")

    def test_fresh_query_cannot_rebind_original_identity(self):
        self.h.observed["recovered"][0]["normalized_args"] = [17]
        with self.assertRaisesRegex(RuntimeError,"Fresh-client recovery changed original result identity"):
            ORACLE["bind_evidence"](self.h.truth,self.h.observed,self.h.records,os.getpid())

    def test_wrong_raw_arithmetic_pixels_and_output_calibration(self):
        result_id = self.h.check("unary-1")["receipt"]["result"]["image_id"]
        self.h.images[result_id]["values"][0,0] += 1
        self.fails_collect("Native arithmetic differs from independent raw-pixel reference")

    def test_output_intensity_metadata_is_independently_read(self):
        result_id = self.h.check("unary-1")["receipt"]["result"]["image_id"]
        self.h.images[result_id]["intensity"]["origin"] = 0.
        self.fails_collect("Result calibration changed")

    def test_read_exception_releases_raw_views_and_wrappers(self):
        self.h.point_fault = self.h.check("unary-1")["receipt"]["result"]["image_id"]
        self.fails_collect("fake raw read failure")

    def test_document_count_bool_is_not_a_valid_count(self):
        self.h.doc_count = True
        self.fails_collect("Hidden processing unexpectedly changed document count")

    def test_main_binds_original_file_bytes_and_actual_pid_not_environment(self):
        truth_path = self.h.directory / "operations-truth.json"
        report_path = self.h.directory / "operations-report.json"
        ledger_path = self.h.directory / "operations-requests.jsonl"
        output_path = self.h.directory / "verification.json"
        truth_path.write_text(json.dumps(self.h.truth),encoding="utf-8")
        report_path.write_text(json.dumps(self.h.observed),encoding="utf-8")
        ledger_path.write_text("".join(json.dumps(row)+"\n" for row in self.h.records),encoding="utf-8")
        environment = {"DM_NATIVE_EVIDENCE_DIR":str(self.h.directory),"DM_NATIVE_OPERATIONS_VERIFICATION":str(output_path),
                       "DM_NATIVE_HOST_PID":str(os.getpid()+1000)}
        with mock.patch.dict(os.environ,environment), mock.patch.dict(sys.modules,{"DigitalMicrograph":self.h.fake_module()}):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ORACLE["main"](),0)
        result = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(result["host_pid"],os.getpid())
        self.assertEqual(result["truth_sha256"],sha(truth_path.read_bytes()))
        self.assertEqual(result["operations_report_sha256"],sha(report_path.read_bytes()))
        self.assertEqual(result["requests_sha256"],sha(ledger_path.read_bytes()))
        self.assertEqual(result["status"],"RECORDED_PARTIAL_QUALIFICATION")
        self.assertEqual(result["fft_filters"],"NOT_QUALIFIED")

    def test_consistent_foreign_pid_plus_environment_cannot_override_actual_pid(self):
        foreign_pid = os.getpid()+1000
        self.h.truth["host_pid"] = foreign_pid
        self.h.observed["host_pid"] = foreign_pid
        self.h.check("STATUS")["receipt"]["result"]["host_pid"] = foreign_pid
        for check in self.h.observed["checks"]:
            check["receipt"]["host_pid"] = foreign_pid
        for row in self.h.records:
            row["host_pid"] = foreign_pid
        self.h.sync_recovered()
        truth_path = self.h.directory / "operations-truth.json"
        report_path = self.h.directory / "operations-report.json"
        ledger_path = self.h.directory / "operations-requests.jsonl"
        output_path = self.h.directory / "wrong-pid-verification.json"
        truth_path.write_text(json.dumps(self.h.truth),encoding="utf-8")
        report_path.write_text(json.dumps(self.h.observed),encoding="utf-8")
        ledger_path.write_text("".join(json.dumps(row)+"\n" for row in self.h.records),encoding="utf-8")
        environment = {"DM_NATIVE_EVIDENCE_DIR":str(self.h.directory),"DM_NATIVE_OPERATIONS_VERIFICATION":str(output_path),
                       "DM_NATIVE_HOST_PID":str(foreign_pid)}
        with mock.patch.dict(os.environ,environment), mock.patch.dict(sys.modules,{"DigitalMicrograph":self.h.fake_module()}):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ORACLE["main"](),1)
        result = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(result["host_pid"],os.getpid())
        self.assertEqual(result["status"],"FAIL")
        self.assertEqual(result["error"],"Truth/receipt host is not executing oracle process")
        self.assertEqual(result["outputs"],[])

    def test_strict_json_rejects_duplicate_and_nonfinite(self):
        for raw,target in [(b'{"id":1,"id":2}',"Duplicate JSON key"),(b'{"x":NaN}',"Nonfinite JSON")]:
            with self.subTest(raw=raw), self.assertRaisesRegex(RuntimeError,target):
                ORACLE["strict_json"](raw)


if __name__ == "__main__":
    unittest.main()
