# -*- coding: utf-8 -*-
"""Synthetic fault injection for the manual same-host oracle; no DM is loaded."""
import base64
import copy
import gc
import hashlib
import json
import os
from pathlib import Path
import runpy
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zlib

import numpy as np
from test_native_operations_oracle import Harness, metadata, MVP, SESSION

with mock.patch.object(sys, "path", [str(MVP)] + sys.path):
    ORACLE = runpy.run_path(str(MVP / "verify_handoff.py"))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def save(path, value):
    Path(path).write_bytes(json.dumps(value, indent=2, allow_nan=False).encode("utf-8")+b"\n")


def png(gray, width, height):
    def chunk(name, data):
        return struct.pack(">I", len(data))+name+data+struct.pack(">I", zlib.crc32(name+data) & 0xffffffff)
    rows = b"".join(b"\0"+gray[y*width:(y+1)*width] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))+
            chunk(b"IDAT", zlib.compress(rows))+chunk(b"IEND", b""))


class Handoff:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.h = Harness(directory)
        self.h.images = {key: value for key, value in self.h.images.items() if key < 1000}
        self.h.doc_count = 9
        bits = self.h.images[self.h.ids["A"]]["values"].copy()
        bits.view("<u4")[0] = [0x80000000, 0, 1, 0x80000001]
        self.source_id = 25
        data = self.h.new_data(self.source_id, bits, "synthetic-READ_BITS")
        self.h.ids["READ_BITS"] = self.source_id
        path = self.directory / "READ_BITS.npy"
        np.save(str(path), bits, allow_pickle=False)
        self.h.truth["images"].append({"id": self.source_id, "label": "READ_BITS", "name": data["name"],
            "dtype": "float32", "shape": [4, 4], "source_npy": str(path), "source_file_sha256": sha(path.read_bytes()),
            "pixel_sha256": sha(bits.tobytes()), "calibration": copy.deepcopy(data["axes"]),
            "intensity_calibration": copy.deepcopy(data["intensity"])})
        self.h.truth["initial_document_count"] = 9
        self.truth = self.directory / "truth.json"
        save(self.truth, self.h.truth)
        self.report = {"schema": 1, "status": "RECORDED", "host_pid": os.getpid(), "session": SESSION,
            "source_label": "READ_BITS", "crop_rect": [1, 1, 4, 4], "read_rect": [0, 0, 3, 3], "source_read_rect": [0, 0, 4, 4],
            "truth_sha256": sha(self.truth.read_bytes()), "checks": [], "previews": [], "extra_checks": [], "captures": []}
        self.records = []
        self.call("status", "dm_status", {}, "STATUS", [], {"backend": "digitalmicrograph-native", "ready": True,
            "binary_gate": True, "host_pid": os.getpid(), "host_thread": 100, "candidate_execution_enabled": True,
            "supported_build": "3.53.4137.0-x64", "compatibility": {"state": "SUPPORTED"},
            "host_build":"3.53.4137.0","host_architecture":"x64","adapter_profile":"gms-3.53.4137.0-windows-x64","adapter_active":True})
        self.crop_id, self.square_id = 1000, 1001
        crop = self.h.new_data(self.crop_id, bits[1:4, 1:4].copy(), "synthetic-crop")
        crop["axes"] = [dict(axis, raw_origin=axis["raw_origin"]-1, origin=axis["origin"]+axis["scale"])
                        for axis in data["axes"]]
        square = self.h.new_data(self.square_id, (crop["values"]**2).astype(np.float32), "synthetic-square")
        square["axes"] = copy.deepcopy(crop["axes"])
        self.call("crop", "dm_crop", {"image_id": self.source_id, "rect": [1, 1, 4, 4]}, "CROP", [self.source_id, 1, 1, 4, 4],
            dict(self.common(self.crop_id, crop), source_image_id=self.source_id, source=metadata(self.source_id, data),
                 requested_rect=[1, 1, 4, 4], effective_rect=[1, 1, 4, 4], operator="GMS::Image::GetSubSliceAsImage"))
        self.call("square", "dm_native_unary", {"image_id": self.crop_id, "operation": "square"}, "UNARY", [self.crop_id, 3],
            dict(self.common(self.square_id, square), operation="square", opcode=3, source_image_ids=[self.crop_id],
                 sources=[metadata(self.crop_id, crop)], operator="GMSImageProcessing::Square", computation="DM native",
                 intensity_calibration_applied=False, intensity_semantics="raw pixel intensity"))
        provenance = {"operation": "UNARY", "request_id": self.report["checks"][2]["request"]["id"],
                      "source_image_ids": [self.crop_id], "semantics": ORACLE["ARITHMETIC_SEMANTICS"]}
        self.call("read_source", "dm_native_read", {"image_id": self.source_id, "rect": [0, 0, 4, 4]}, "READ",
                  [self.source_id, 0, 0, 4, 4], self.read(self.source_id, [0, 0, 4, 4], None))
        self.call("read", "dm_native_read", {"image_id": self.square_id, "rect": [0, 0, 3, 3]}, "READ",
                  [self.square_id, 0, 0, 3, 3], self.read(self.square_id, [0, 0, 3, 3], provenance))
        w, h, low, high, gray, unused, unused2 = ORACLE["reference_preview"](bits, 128, 128)
        preview = {"backend": "digitalmicrograph-native", "operation": "PREVIEW", "image_id": self.source_id,
            "source": metadata(self.source_id, data), "width": w, "height": h, "sample_count": w*h,
            "sampled_minimum": low, "sampled_maximum": high, "gray8_hex": gray.hex(), "quantitative": False,
            "mapping": ORACLE["MAPPING"], "orientation": ORACLE["ORIENTATION"], "sampling": ORACLE["SAMPLING"],
            "range_source": "sampled native point values", "constant_range_gray8": 0,
            "operator": "GMS::Image::GetRealValue", "source_write_requested": False, "snapshot_atomic": False}
        entry = self.call("source", "dm_native_preview", {"image_id": self.source_id}, "PREVIEW", [self.source_id, 128, 128], preview, "previews")
        self.png = self.directory / "source.png"
        self.png.write_bytes(png(gray, w, h))
        entry.update(png=str(self.png), png_sha256=sha(self.png.read_bytes()))
        entry["response"]["content"].append({"type": "image", "mimeType": "image/png", "data": base64.b64encode(self.png.read_bytes()).decode("ascii")})
        self.extras()
        for label, check in (("source", self.report["checks"][3]), ("processed", self.report["checks"][4])):
            self.capture(label, check)
        self.external()
        self.report_path, self.ledger_path = self.directory / "report.json", self.directory / "ledger.jsonl"
        self.persist()

    def common(self, image_id, data):
        return {"backend": "digitalmicrograph-native", "image_id": image_id, "image": metadata(image_id, data),
                "source_write_requested": False, "snapshot_atomic": False, "ownership": "synthetic owned reference"}

    def call(self, label, tool, arguments, op, args, output, bucket="checks"):
        request_id = "synthetic-"+str(len(self.records))
        request = {"protocol": "NB2", "session": SESSION, "host_pid": os.getpid(), "id": request_id, "op": op, "args": args,
            "wire": "NB2 %s %s %s%s\n" % (SESSION, request_id, op, " "+" ".join(map(str, args)) if args else "")}
        self.records.append(request)
        output = dict(output, native_receipt={"protocol": "NB2", "session": SESSION, "id": request_id, "request_id": request_id,
            "state": "completed", "host_pid": os.getpid(), "exec_tid": 100, "worker_tid": 200,
            "original_operation": op, "normalized_args": args, "result_type": ORACLE["TYPES"][op],
            "result_version": 2 if op in ("FFT", "IFFT", "REAL") else 1, "timings_us": {"queue": 1, "execute": 2}})
        entry = {"label": label, "tool": tool, "arguments": dict(arguments, request_id=request_id), "request": copy.deepcopy(request),
                 "response": {"content": [{"type": "text", "text": json.dumps(output)}]}}
        self.report[bucket].append(entry)
        return entry

    def read(self, image_id, rect, provenance):
        data = self.h.images[image_id]
        source = metadata(image_id, data)
        values = data["values"][rect[1]:rect[3], rect[0]:rect[2]]
        cal = []
        for axis in source["calibration"]:
            dim, offset = axis["dm_dimension"], rect[axis["dm_dimension"]]
            cal.append({"dm_dimension": dim, "numpy_axis": 1-dim, "size": values.shape[1-dim], "source_offset": offset,
                "source_origin": axis["origin"], "source_calibrated_value_at_pixel_zero": axis["calibrated_value_at_pixel_zero"],
                "origin": axis["origin"]-offset, "calibrated_value_at_pixel_zero": axis["calibrated_value_at_pixel_zero"]+offset*axis["scale"],
                "scale": axis["scale"], "unit": axis["unit"], "usable": True, "issue": None})
        return {"backend": "digitalmicrograph-native", "operation": "READ", "source_image_id": image_id, "source": source,
            "requested_rect": rect, "effective_rect": rect, "shape": list(values.shape), "dtype": "float32", "byte_order": "little",
            "axes": ["y", "x"], "array_order": "C", "data_encoding": "base64", "values_base64": base64.b64encode(values.tobytes()).decode("ascii"),
            "sample_count": int(values.size), "raw_bytes": values.nbytes, "roi_calibration": cal, "calibration_complete": True,
            "coordinate_mapping_policy": ORACLE["MAPPING_POLICY"], "source_provenance": provenance,
            "source_provenance_scope": ORACLE["PROVENANCE_SCOPE"], "operator": "GMS::Image::GetRealValue",
            "computation": "DM native point reads; data handoff only", "intensity_calibration_applied": False,
            "intensity_semantics": "raw pixel intensity", "ownership": "response-owned numeric snapshot; no native result image",
            "source_write_requested": False, "snapshot_atomic": False}

    def extras(self):
        a_id = self.h.ids["A"]
        a = self.h.images[a_id]
        forward = ORACLE["quarter_turn_dft"](a["values"])
        parent = a_id
        for image_id, label, op, values, tool, extra in (
            (1002, "fft", "FFT", forward, "dm_native_fft", {"direction": "forward"}),
            (1003, "ifft", "IFFT", a["values"].astype(np.complex64), "dm_native_fft", {"direction": "inverse"}),
            (1004, "inverse_real", "REAL", a["values"].copy(), "dm_native_complex", {"component": "real"})):
            data = self.h.new_data(image_id, values, "synthetic-"+label)
            data["axes"] = []
            for axis in a["axes"]:
                scale = 1.0/(4*axis["scale"]) if op == "FFT" else axis["scale"]
                origin = 2.5 if op == "FFT" else 0.0
                data["axes"].append(dict(axis, scale=scale, raw_origin=origin,
                                        origin=-origin*scale if op == "FFT" else 0.0, unit="1/nm" if op == "FFT" else "nm"))
            data["intensity"] = {"origin": 0., "scale": 1., "unit": ""}
            out = dict(self.common(image_id, data), operation=op, source_image_id=parent,
                       source=metadata(parent, self.h.images[parent]), operator="GMSImageProcessing::"+{"FFT":"Real_FFT","IFFT":"IFFT","REAL":"Real"}[op],
                       intensity_calibration_applied=False, computation="DM native",
                       representation="real_component" if op == "REAL" else "full_complex",
                       normalization={"FFT":"none","IFFT":"1/(width*height)","REAL":"inherited_parent_transform"}[op],
                       centering="fftshift_data" if op == "FFT" else "spatial_origin_zero", phase_units="not_applicable",
                       transform_signs={"forward":"+","inverse":"-"},input_index_origin="zero-based pixel indices",
                       source_spatial_origin_used=False,inverse_restores_source_origin=False,
                       intensity_calibration_policy=ORACLE["FOURIER_INTENSITY_POLICY"],frequency_grid=None)
            if op == "FFT":
                axes = []
                for axis in data["axes"]:
                    step, zero = axis["scale"], axis["origin"]
                    axes.append({"dm_dimension":axis["dm_axis"],"size":4,"dc_index":2,"cycles_per_pixel_step":.25,
                        "physical_frequency_step":step,"unit":"1/nm","frequency_at_index_zero":-2*step,
                        "native_calibrated_value_at_pixel_zero":zero,"native_calibration_dc_value":zero+2*step,
                        "coordinate_rule":"f(i)=(i-dc_index)*physical_frequency_step"})
                out["frequency_grid"] = {"native_calibration_has_half_bin_offset":True,"axes":axes}
            self.call(label, tool, dict(extra, image_id=parent), op, [parent], out, "extra_checks")
            parent = image_id
        source_id = self.h.ids["FILTER_A"]
        source = self.h.images[source_id]
        for code, name in enumerate(("smooth", "sobel", "laplace", "sharpen"), 1):
            values, unused = ORACLE["verify_filter"].__globals__["filter_reference"](source["values"], code)
            image_id = 1004+code
            data = self.h.new_data(image_id, values, "synthetic-"+name)
            out = dict(self.common(image_id, data), operation="FILTER", source_image_id=source_id,
                       source=metadata(source_id, source), filter_kind=code, computation="DM native", kernel="vendor_defined", edge_behavior="vendor_defined",
                       operator="GMSImageProcessing::"+("SmoothFilter", "SobelFilter", "LaplaceFilter", "SharpenFilter")[code-1])
            self.call(name, "dm_native_filter", {"image_id": source_id, "operation": name}, "FILTER", [source_id, code], out, "extra_checks")

    def capture(self, label, check):
        out = json.loads(check["response"]["content"][0]["text"])
        snapshot = self.directory / (label+"-snapshot.json")
        save(snapshot, check["response"])
        directory = self.directory / ("capture-"+label)
        directory.mkdir()
        raw = base64.b64decode(out["values_base64"])
        receipt = out["native_receipt"]
        receipt_hash = sha(canonical(receipt))
        capture_id, request_id = "capture-"+label, "encode-"+label
        values = np.frombuffer(raw, dtype="<f4").reshape(out["shape"])
        np.save(str(directory / "input.npy"), values, allow_pickle=False)
        npy_raw = (directory / "input.npy").read_bytes()
        source_cal = [dict(axis, axis="x" if i == 0 else "y") for i, axis in enumerate(out["source"]["calibration"])]
        work_cal = [dict(axis, axis="x" if i == 0 else "y") for i, axis in enumerate(out["roi_calibration"])]
        info = {"schema_version":1,"capture_id":capture_id,"shape_yx":out["shape"],"dtype":"float32","byte_order":"little","array_order":"C",
            "axes":["y","x"],"axis_roles":[{"numpy_axis":0,"dm_dimension":1,"role":"y"},{"numpy_axis":1,"dm_dimension":0,"role":"x"}],
            "source_image_id":out["source_image_id"],"source_shape_yx":out["source"]["shape"],"source_rect_xyxy":out["effective_rect"],
            "source_calibration_dm":source_cal,"working_calibration_xy":work_cal,"source_metadata":out["source"],
            "intensity_calibration":{"origin":None,"scale":None,"unit":None,"status":"NOT_READ"},"intensity_calibration_applied":False,
            "input_file":"input.npy","input_sha256":sha(npy_raw),"input_file_bytes":len(npy_raw),"raw_bytes":out["raw_bytes"],"sample_count":out["sample_count"],
            "pixel_sha256":sha(raw),"native_receipt":receipt,"native_receipt_sha256":receipt_hash,"saved_snapshot_sha256":sha(snapshot.read_bytes()),
            "native_source_provenance":out["source_provenance"],"native_source_provenance_scope":ORACLE["PROVENANCE_SCOPE"],
            "coordinate_mapping_policy":ORACLE["MAPPING_POLICY"],"pixel_capture_atomic":False,"dm_file_save":False,"external_saved_response_encoding":True}
        info.update(source_rect_convention="zero-based half-open [x0,y0,x1,y1]",
                    pixel_coordinate_model="pixel centers at integer x,y; physical value = calibrated_value_at_pixel_zero + index*scale",
                    calibration_complete=True,source_path_included=False,
                    snapshot_identity_scope="immutable stored numeric bytes; source image ID and live pixels remain mutable")
        save(directory / "input.json", info)
        manifest = {"schema_version":1,"capture_id":capture_id,"state":"captured","external_saved_response_encoding":True,
            "source_image_id":out["source_image_id"],"source_shape_yx":out["source"]["shape"],"source_rect_xyxy":out["effective_rect"],
            "source_dtype":"float32","source_data_type_code":2,"calibration_before":source_cal,"calibration_after":source_cal,
            "pixel_capture_atomic":False,"native_session":SESSION,"native_request_id":receipt["id"],"handoff_request_id":request_id,
            "native_receipt_sha256":receipt_hash,"saved_snapshot_sha256":sha(snapshot.read_bytes()),"dm_file_save":False,
            "live_source_reobserved":False,"input_sha256":sha(npy_raw),"input_metadata_sha256":sha(canonical(info)),
            "input_metadata_file_sha256":sha((directory / "input.json").read_bytes()),"pixel_sha256":sha(raw),"descriptor_unchanged":True}
        manifest.update(source_rect_convention="zero-based half-open [x0,y0,x1,y1]",operation="bounded 2D capture",
                        capture_backend="saved digitalmicrograph-native READ numeric snapshot",memory_estimate_bytes=len(npy_raw)+len(raw),
                        memory_budget_bytes=256*1024,descriptor_evidence="native READ metadata-before/after contract; no atomic pixel claim")
        save(directory / "capture.json", manifest)
        cap = {"state":"captured","capture_id":capture_id,"capture_dir":str(directory),"shape_yx":out["shape"],"dtype":"float32",
            "source_rect_xyxy":out["effective_rect"],"input_sha256":sha(npy_raw),"request_id":request_id,"native_session":SESSION,
            "native_request_id":receipt["id"],"files_sha256":{name:sha((directory/name).read_bytes()) for name in ("input.npy","input.json","capture.json")},
            "pixel_capture_atomic":False,"dm_file_save":False}
        params = {"workspace":str(self.directory),"output":directory.name,"snapshot_path":str(snapshot),
            "saved_snapshot_sha256":sha(snapshot.read_bytes()),"native_receipt_sha256":receipt_hash,"native_values_sha256":sha(raw),
            "session":SESSION,"native_request_id":receipt["id"],"operation":"READ","normalized_args":receipt["normalized_args"]}
        record = {"schema_version":1,"kind":"native_snapshot_handoff_request","request_id":request_id,"state":"CAPTURED",
            "capture_id":capture_id,"parameters":params,"parameters_sha256":sha(canonical(params)),"native_receipt":receipt,
            "native_receipt_sha256":receipt_hash,"capture_receipt":cap}
        record_path = self.directory/(request_id+".json")
        save(record_path, record)
        self.report["captures"].append({"label":label,"snapshot":str(snapshot),"snapshot_sha256":sha(snapshot.read_bytes()),
                                        "request_record":str(record_path),"receipt":cap})

    def external(self):
        capture = self.report["captures"][1]
        directory = self.directory / "external-mean"
        directory.mkdir()
        capdir = Path(capture["receipt"]["capture_dir"])
        info = json.loads((capdir/"input.json").read_bytes())
        script = (MVP.parents[2]/"examples"/"native_handoff_mean.py").read_bytes()
        (directory/"native_handoff_mean.py").write_bytes(script)
        params = {"schema_version":1,"operation":"raw mean","execution":"explicit external NumPy example",
            "capture_id":info["capture_id"],"capture_files_sha256":capture["receipt"]["files_sha256"],"dtype":"float32","accumulator_dtype":"float64",
            "shape_yx":info["shape_yx"],"source_image_id":info["source_image_id"],"source_rect_xyxy":info["source_rect_xyxy"],
            "native_session":SESSION,"native_request_id":info["native_receipt"]["id"],"native_receipt_sha256":info["native_receipt_sha256"],
            "intensity_calibration_applied":False,"source_calibration_dm":info["source_calibration_dm"],"working_calibration_xy":info["working_calibration_xy"],
            "dm_called":False,"result_returned_to_dm":False,"script_sha256":sha(script),"python_version":"synthetic", "numpy_version":"synthetic","platform":"synthetic"}
        save(directory/"parameters.json", params)
        result = {"schema_version":1,"state":"complete","scope":"explicit external NumPy raw mean only","capture_id":info["capture_id"],
            "mean":float(np.mean(self.h.images[self.square_id]["values"],dtype=np.float64)),"sample_count":9,"accumulator_dtype":"float64",
            "intensity_calibration_applied":False,"intensity_unit":None,"intensity_calibration_status":"NOT_READ","dm_called":False,
            "result_returned_to_dm":False,"parameters_sha256":sha(canonical(params)),"script_sha256":sha(script),"input_sha256":info["input_sha256"]}
        save(directory/"results.json", result)
        save(directory/"run.json", {"schema_version":1,"state":"complete","scope":"explicit external raw mean only","results_sha256":sha((directory/"results.json").read_bytes())})
        self.report["external"] = {"capture_label":"processed","output_dir":str(directory)}

    def persist(self):
        save(self.report_path, self.report)
        self.ledger_path.write_bytes(b"".join(canonical(record)+b"\n" for record in self.records))

    def run(self):
        self.persist()
        result = {"status": "FAIL"}
        with mock.patch.dict(sys.modules, {"DigitalMicrograph": self.h.fake_module()}):
            ORACLE["collect"](result, str(self.truth), str(self.report_path), str(self.ledger_path))
        return result


class HandoffOracleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = Handoff(self.temp.name)

    def mutate_text(self, entry, callback):
        out = json.loads(entry["response"]["content"][0]["text"])
        callback(out)
        entry["response"]["content"][0]["text"] = json.dumps(out)

    def fails(self, message):
        with self.assertRaisesRegex(RuntimeError, message):
            self.fixture.run()

    def test_full_positive_and_wrapper_release(self):
        result = self.fixture.run()
        self.assertEqual(result["status"], "PASS_BOUNDED_SYNTHETIC_HANDOFF")
        self.assertEqual(len(result["additional_operations"]), 7)
        self.assertEqual(result["signed_zero_and_subnormal"], "PASS")
        gc.collect()
        self.assertTrue(all(ref() is None for ref in self.fixture.h.views+self.fixture.h.wrappers))

    def test_actual_pid_not_environment_or_self_consistent_report(self):
        self.fixture.h.truth["host_pid"] += 1
        save(self.fixture.truth, self.fixture.h.truth)
        self.fixture.report["host_pid"] += 1
        self.fixture.report["truth_sha256"] = sha(self.fixture.truth.read_bytes())
        with mock.patch.dict(os.environ, {"DM_NATIVE_HOST_PID": str(self.fixture.report["host_pid"])}):
            self.fails("not actual oracle PID")

    def test_wrong_session_receipt(self):
        self.mutate_text(self.fixture.report["checks"][1], lambda o:o["native_receipt"].update(session="f"*32))
        self.fails("receipt identity")

    def test_wrong_native_thread(self):
        self.mutate_text(self.fixture.report["checks"][1], lambda o:o["native_receipt"].update(exec_tid=101))
        self.fails("thread anchor")

    def test_unknown_or_failed_never_completed(self):
        for state in ("unknown", "running", "failed"):
            with self.subTest(state=state):
                check = self.fixture.report["checks"][1]
                old = copy.deepcopy(check)
                self.mutate_text(check, lambda o:o["native_receipt"].update(state=state))
                self.fails("receipt identity")
                check.update(old)

    def test_original_wire_tamper(self):
        self.fixture.records[1]["wire"] += "\n"
        self.fails("ledger wire")

    def test_missing_case(self):
        self.fixture.report["checks"].pop()
        self.fails("five-check")

    def test_crop_roi_mismatch(self):
        self.mutate_text(self.fixture.report["checks"][1], lambda o:o.update(effective_rect=[0,0,3,3]))
        self.fails("CROP output identity/ROI")

    def test_source_truth_flush_cannot_self_validate(self):
        entry = self.fixture.h.truth["images"][-1]
        values = self.fixture.h.images[self.fixture.source_id]["values"]
        values.view("<u4")[0] = 0
        np.save(entry["source_npy"], values, allow_pickle=False)
        entry.update(source_file_sha256=sha(Path(entry["source_npy"]).read_bytes()),pixel_sha256=sha(values.tobytes()))
        save(self.fixture.truth, self.fixture.h.truth)
        self.fixture.report["truth_sha256"] = sha(self.fixture.truth.read_bytes())
        self.fails("predetermined signed-zero/subnormal")

    def test_live_signed_zero_and_subnormal(self):
        self.fixture.h.images[self.fixture.source_id]["values"].view("<u4")[0,0] = 0
        self.fails("source pixels")

    def test_native_read_wrong_bits_target_validation(self):
        output = json.loads(self.fixture.report["checks"][3]["response"]["content"][0]["text"])
        raw = bytearray(base64.b64decode(output["values_base64"]))
        raw[3] = 0
        output["values_base64"] = base64.b64encode(raw).decode("ascii")
        data = self.fixture.h.images[self.fixture.source_id]
        observation = {"values":data["values"],"name":data["name"],"calibration":data["axes"],"intensity_calibration":data["intensity"]}
        with self.assertRaisesRegex(RuntimeError,"READ raw pixels"):
            ORACLE["validate_read"](output,self.fixture.source_id,[0,0,4,4],observation,None)

    def test_read_roi_calibration_target_validation(self):
        output = json.loads(self.fixture.report["checks"][3]["response"]["content"][0]["text"])
        output["roi_calibration"][0]["scale"] *= -1
        data = self.fixture.h.images[self.fixture.source_id]
        observation = {"values":data["values"],"name":data["name"],"calibration":data["axes"],"intensity_calibration":data["intensity"]}
        with self.assertRaisesRegex(RuntimeError,"signed ROI calibration"):
            ORACLE["validate_read"](output,self.fixture.source_id,[0,0,4,4],observation,None)

    def test_crop_alias_detected_on_raw_views(self):
        self.fixture.h.images[self.fixture.crop_id]["values"] = self.fixture.h.images[self.fixture.source_id]["values"][1:4,1:4]
        self.fails("raw views share memory")

    def test_square_pixels_not_intensity_scaled(self):
        self.fixture.h.images[self.fixture.square_id]["values"][0,0] += 1
        self.fails("Native square differs")

    def test_source_intensity_preserved(self):
        self.fixture.h.images[self.fixture.source_id]["intensity"]["scale"] = 1
        self.fails("spatial/intensity calibration changed")

    def test_receipt_metadata_false_shape(self):
        self.mutate_text(self.fixture.report["checks"][2],lambda o:o["image"].update(shape=[1,9]))
        self.fails("metadata type/shape")

    def test_capture_incomplete_state(self):
        entry = self.fixture.report["captures"][0]
        record = json.loads(Path(entry["request_record"]).read_bytes())
        record["state"] = "PREPARED"
        save(entry["request_record"],record)
        self.fails("incomplete")

    def test_manifest_failed_with_updated_file_hash(self):
        entry = self.fixture.report["captures"][0]
        path = Path(entry["receipt"]["capture_dir"])/"capture.json"
        manifest = json.loads(path.read_bytes()); manifest["state"] = "failed"; save(path,manifest)
        entry["receipt"]["files_sha256"]["capture.json"] = sha(path.read_bytes())
        record = json.loads(Path(entry["request_record"]).read_bytes()); record["capture_receipt"] = entry["receipt"]; save(entry["request_record"],record)
        self.fails("Captured manifest/native/file identity")

    def test_encoded_npy_tamper(self):
        path = Path(self.fixture.report["captures"][0]["receipt"]["capture_dir"])/"input.npy"
        path.write_bytes(path.read_bytes()[:-1]+b"x")
        self.fails("original files hash")

    def test_external_mean_wrong_even_with_refreshed_run_hash(self):
        directory = Path(self.fixture.report["external"]["output_dir"])
        result = json.loads((directory/"results.json").read_bytes()); result["mean"] += 1; save(directory/"results.json",result)
        run = json.loads((directory/"run.json").read_bytes()); run["results_sha256"] = sha((directory/"results.json").read_bytes()); save(directory/"run.json",run)
        self.fails("External mean/state")

    def test_external_capture_hash_binding(self):
        path = Path(self.fixture.report["external"]["output_dir"])/"parameters.json"
        params = json.loads(path.read_bytes()); params["capture_files_sha256"]["input.npy"] = "0"*64; save(path,params)
        self.fails("External original parameters")

    def test_png_pixels_not_transposed(self):
        self.fixture.png.write_bytes(png(bytes(range(16)),4,4))
        entry = self.fixture.report["previews"][0]
        entry["png_sha256"] = sha(self.fixture.png.read_bytes())
        entry["response"]["content"][1]["data"] = base64.b64encode(self.fixture.png.read_bytes()).decode("ascii")
        self.fails("PNG decoded pixels/axes")

    def test_fourier_version_and_actual_pixels(self):
        self.mutate_text(self.fixture.report["extra_checks"][0],lambda o:o["native_receipt"].update(result_version=1))
        self.fails("receipt identity/type/version")

    def test_fourier_wrong_pixels(self):
        self.fixture.h.images[1002]["values"][0,0] += 1
        self.fails("predetermined DFT")

    def test_filter_wrong_pixels(self):
        self.fixture.h.images[1005]["values"][0,0] += 1
        self.fails("predetermined kernel/edge")

    def test_fourier_declared_normalization_not_fitted(self):
        self.mutate_text(self.fixture.report["extra_checks"][1],lambda o:o.update(normalization="none"))
        self.fails("declared normalization")

    def test_fourier_grid_wrong_dc(self):
        self.mutate_text(self.fixture.report["extra_checks"][0],lambda o:o["frequency_grid"]["axes"][0].update(dc_index=0))
        self.fails("frequency grid/DC")

    def test_raw_view_shape_rejected_before_copy(self):
        self.fixture.h.images[self.fixture.crop_id]["values"] = np.ones((1,9),dtype=np.float32)
        self.fails("Raw host view shape/dtype")

    def production(self):
        self.fixture.report["qualification_mode"] = "production"
        def status(out):
            out.pop("candidate_execution_enabled",None)
            out.pop("candidate_capabilities",None)
            out["native_capabilities"] = [{"name":name,"available":True,"qualification":"LIMITED_REAL_HOST"}
                for name in ("native_image_arithmetic","native_fft","native_filters","native_preview","native_read")]
        self.mutate_text(self.fixture.report["checks"][0],status)

    def test_production_mode_full_positive(self):
        self.production()
        self.assertEqual(self.fixture.run()["qualification_mode"],"production")

    def test_production_missing_each_qualification(self):
        self.production()
        original = copy.deepcopy(self.fixture.report["checks"][0])
        for index in range(5):
            with self.subTest(index=index):
                self.mutate_text(self.fixture.report["checks"][0],lambda out:out["native_capabilities"][index].update(qualification="NOT_QUALIFIED"))
                self.fails("not qualified")
                self.fixture.report["checks"][0] = copy.deepcopy(original)

    def test_production_candidate_bypass_refused(self):
        self.production()
        self.mutate_text(self.fixture.report["checks"][0],lambda out:out.update(candidate_execution_enabled=False))
        self.fails("candidate execution bypass")

    def test_prepared_must_be_explicitly_enabled(self):
        self.fixture.report["qualification_mode"] = "prepared"
        self.mutate_text(self.fixture.report["checks"][0],lambda out:out.update(candidate_execution_enabled=False))
        self.fails("Prepared qualification mode")

    def test_missing_mode_not_inferred_as_production(self):
        self.mutate_text(self.fixture.report["checks"][0],lambda out:out.pop("candidate_execution_enabled"))
        self.fails("Unspecified qualification mode")

    def test_exact_profile_required_both_modes(self):
        for production in (False,True):
            if production:self.production()
            self.mutate_text(self.fixture.report["checks"][0],lambda out:out.update(adapter_profile="another-profile"))
            self.fails("profile/host anchor")

    def test_read_exception_never_pass(self):
        self.fixture.h.point_fault = self.fixture.crop_id
        self.fails("fake raw read failure")

    def test_evidence_change_during_collection(self):
        original = self.fixture.h.fake_module()
        original_count = original.CountImageDocumentsOfAllWorkspaces
        calls = [0]
        def count():
            calls[0] += 1
            if calls[0] == 2:
                self.fixture.truth.write_bytes(self.fixture.truth.read_bytes()+b" ")
            return original_count()
        original.CountImageDocumentsOfAllWorkspaces = count
        self.fixture.persist()
        with mock.patch.dict(sys.modules,{"DigitalMicrograph":original}):
            with self.assertRaisesRegex(RuntimeError,"Original evidence changed"):
                ORACLE["collect"]({},str(self.fixture.truth),str(self.fixture.report_path),str(self.fixture.ledger_path))


if __name__ == "__main__":
    unittest.main()
