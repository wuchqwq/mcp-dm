# -*- coding: utf-8 -*-
"""Targeted offline PNG/sample guards; no real DM or production encoder."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import runpy
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zlib

import numpy as np
from test_native_operations_oracle import Harness, MVP, metadata

with mock.patch.object(sys,"path",[str(MVP)]+sys.path):
    PREVIEW = runpy.run_path(str(MVP/"verify_preview.py"))


def chunk(name,payload):
    return struct.pack(">I",len(payload))+name+payload+struct.pack(">I",zlib.crc32(name+payload)&0xffffffff)


def png(width,height,gray,filter_kind=0):
    rows=[]
    previous=bytes(width)
    for y in range(height):
        row=gray[y*width:(y+1)*width]
        encoded=bytearray()
        for x,value in enumerate(row):
            a,b,c=row[x-1] if x else 0,previous[x],previous[x-1] if x else 0
            if filter_kind==1:
                predictor=a
            elif filter_kind==2:
                predictor=b
            elif filter_kind==3:
                predictor=(a+b)//2
            elif filter_kind==4:
                p=a+b-c
                distances=[abs(p-a),abs(p-b),abs(p-c)]
                predictor=[a,b,c][distances.index(min(distances))]
            else:
                predictor=0
            encoded.append((value-predictor)&255)
        rows.append(bytes([filter_kind])+bytes(encoded))
        previous=row
    return b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",width,height,8,0,0,0,0))+chunk(b"IDAT",zlib.compress(b"".join(rows)))+chunk(b"IEND",b"")


class NativePreviewOracleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name)
        self.h=Harness(self.tmp.name)
        observation=self.h.collect()
        self.paths={}
        for key,value in (("truth",self.h.truth),("operations-report",self.h.observed)):
            raw=json.dumps(value).encode("utf-8")
            self.paths[key]=self.directory/(key+".json")
            self.paths[key].write_bytes(raw)
        observation.update(schema=1,status="RECORDED_PARTIAL_QUALIFICATION",host_pid=self.h.truth["host_pid"],
            session=self.h.truth["session"],truth_sha256=hashlib.sha256(self.paths["truth"].read_bytes()).hexdigest(),
            operations_report_sha256=hashlib.sha256(self.paths["operations-report"].read_bytes()).hexdigest())
        self.paths["operations-observation"]=self.directory/"independent.json"
        self.paths["operations-observation"].write_text(json.dumps(observation),encoding="utf-8")
        self.previews={"schema":1,"status":"RECORDED","host_pid":self.h.truth["host_pid"],
                       "session":self.h.truth["session"],"checks":[]}
        self.requests=[]
        for label,bounds in (("A",[128,128]),("FILTER_A",[3,5])):
            image_id=self.h.ids[label]
            request_id="preview-"+label
            args=[image_id]+bounds
            request={"protocol":"NB2","session":self.h.truth["session"],"host_pid":self.h.truth["host_pid"],"id":request_id,
                     "op":"PREVIEW","args":args,"wire":"NB2 %s %s PREVIEW %s\n" %
                     (self.h.truth["session"],request_id," ".join(map(str,args)))}
            self.requests.append(request)
            if label=="A":
                width,height,minimum,maximum,gray=4,4,-16,15,bytes.fromhex("8e6fa2a55ab5bd42d0d629e6effbff00")
            else:
                width,height,minimum,maximum=3,5,0,53
                hand=[0,2,5,8,10,13,24,26,29,32,34,37,48,50,53]
                gray=bytes((2*value*255+53)//106 for value in hand)
            result={"backend":"digitalmicrograph-native","operation":"PREVIEW","image_id":image_id,
                "source":metadata(image_id,self.h.images[image_id]),"width":width,"height":height,
                "sample_count":width*height,"sampled_minimum":minimum,"sampled_maximum":maximum,
                "gray8_hex":gray.hex(),"range_source":"sampled native point values","constant_range_gray8":0,
                "mapping":"x=floor(px*source_width/width);y=floor(py*source_height/height)",
                "orientation":"row-major [y,x], x increases right, y increases down",
                "sampling":"nearest source integer index, no averaging","operator":"GMS::Image::GetRealValue",
                "computation":"DM native value reads; display adaptation only","quantitative":False,
                "source_write_requested":False,"snapshot_atomic":False}
            receipt={"protocol":"NB2","session":request["session"],"host_pid":request["host_pid"],"id":request_id,
                "state":"completed","worker_tid":200,"exec_tid":100,"timings_us":{"queue":1,"execute":2},
                "original_operation":"PREVIEW","normalized_args":args[:],"result_type":"native_preview","result_version":1,
                "result":result}
            path=self.directory/(label+".png")
            path.write_bytes(png(width,height,gray))
            self.previews["checks"].append({"label":label,"request":copy.deepcopy(request),"receipt":receipt,
                                           "png":str(path),"png_sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
        self.paths["preview-observations"]=self.directory/"previews.json"
        self.paths["preview-requests"]=self.directory/"preview-requests.jsonl"

    def run_cli(self,expected=None):
        self.paths["preview-observations"].write_text(json.dumps(self.previews),encoding="utf-8")
        self.paths["preview-requests"].write_text("".join(json.dumps(row)+"\n" for row in self.requests),encoding="utf-8")
        output=self.directory/"result.json"
        args=[]
        for key,path in self.paths.items():
            args.extend(["--"+key,str(path)])
        args.extend(["--output",str(output)])
        with contextlib.redirect_stdout(io.StringIO()):
            code=PREVIEW["main"](args)
        report=json.loads(output.read_text(encoding="utf-8"))
        if expected:
            self.assertEqual(code,1)
            self.assertEqual(report["status"],"FAIL")
            self.assertIn(expected,report["error"])
        else:
            self.assertEqual(code,0,report)
            self.assertEqual(report["status"],"PASS_DISPLAY_SAMPLE_MAPPING")
        return report

    def test_complete_two_case_display_mapping_not_scientific_export(self):
        report=self.run_cli()
        self.assertEqual(len(report["checks"]),2)
        self.assertFalse(report["scientific_export"])
        self.assertEqual(report["model_visual_verification"],"NOT_TESTED")
        self.assertEqual(report["checks"][1]["sample_coordinates_xy"],
                         [[x,y] for y in (0,1,3,4,6) for x in (0,2,5)])

    def test_all_standard_gray8_row_filters_decode_exact_pixels(self):
        gray=bytes([1,3,8,255,0,7,23,77,211,9,42,128])
        for kind in range(5):
            with self.subTest(kind=kind):
                self.assertEqual(PREVIEW["decode_gray8_png"](png(4,3,gray,kind)),(4,3,gray))

    def test_constant_zero_and_half_up_are_explicit_offline_rules(self):
        constant=PREVIEW["reference_preview"](np.full((2,3),7.5,dtype=np.float32),128,128)
        self.assertEqual(constant[:4],(3,2,7.5,7.5))
        self.assertEqual(constant[4],bytes(6))
        half=PREVIEW["reference_preview"](np.array([[0,0.5,1]],dtype=np.float32),128,128)
        self.assertEqual(half[4],bytes([0,128,255]))

    def test_wrong_native_host_or_state_rejected(self):
        self.previews["checks"][0]["receipt"]["host_pid"]+=1
        self.run_cli("PREVIEW native receipt identity/state mismatch")

    def test_wrong_original_request_wire_cannot_use_matching_receipt(self):
        self.requests[0]["wire"]+=" "
        self.previews["checks"][0]["request"]=copy.deepcopy(self.requests[0])
        self.run_cli("Original PREVIEW wire/identity/arguments mismatch")

    def test_wrong_result_type_and_args_rejected(self):
        self.previews["checks"][0]["receipt"]["result_type"]="native_mean"
        self.run_cli("PREVIEW native receipt identity/state mismatch")

    def test_raw_range_does_not_apply_nontrivial_intensity_calibration(self):
        self.previews["checks"][0]["receipt"]["result"]["sampled_minimum"]=-15
        self.run_cli("PREVIEW sampled raw range mismatch")

    def test_non_square_axes_are_not_transposed(self):
        self.previews["checks"][1]["receipt"]["result"]["gray8_hex"]=bytes(
            reversed(bytes.fromhex(self.previews["checks"][1]["receipt"]["result"]["gray8_hex"]))).hex()
        self.run_cli("PREVIEW grayscale differs")

    def test_receipt_source_metadata_must_match_original_shape_and_calibration(self):
        self.previews["checks"][0]["receipt"]["result"]["source"]["calibration"][0]["scale"]=-.5
        self.run_cli("Receipt metadata calibration number mismatch")

    def test_png_crc_fault_reaches_crc_check_after_rehashed_bytes(self):
        entry=self.previews["checks"][0]
        path=Path(entry["png"])
        raw=bytearray(path.read_bytes())
        raw[29]^=1
        path.write_bytes(raw)
        entry["png_sha256"]=hashlib.sha256(raw).hexdigest()
        self.run_cli("PNG chunk CRC mismatch")

    def test_png_pixels_are_decoded_not_only_bytehash_and_crc(self):
        entry=self.previews["checks"][1]
        path=Path(entry["png"])
        gray=bytes.fromhex(entry["receipt"]["result"]["gray8_hex"])
        path.write_bytes(png(3,5,gray[::-1]))
        entry["png_sha256"]=hashlib.sha256(path.read_bytes()).hexdigest()
        self.run_cli("PNG dimensions/decoded gray pixels differ")

    def test_png_trailing_and_invalid_grayscale_contract(self):
        for raw,target in [(png(1,1,b"\0")+b"x","PNG bytes after IEND"),
                           (b"not a PNG","PNG signature/size mismatch")]:
            with self.subTest(target=target),self.assertRaisesRegex(RuntimeError,target):
                PREVIEW["decode_gray8_png"](raw)

    def test_prior_formal_observation_hash_cannot_be_stale(self):
        path=self.paths["operations-observation"]
        value=json.loads(path.read_text());value["truth_sha256"]="0"*64;path.write_text(json.dumps(value))
        self.run_cli("Formal source/memory observation missing or bound to different evidence")

    def test_source_pixel_file_change_is_not_a_new_truth(self):
        truth=json.loads(self.paths["truth"].read_text())
        path=Path(next(entry for entry in truth["images"] if entry["label"]=="A")["source_npy"])
        raw=bytearray(path.read_bytes());raw[-1]^=1;path.write_bytes(raw)
        self.run_cli("Preview source original NPY hash/size mismatch")


if __name__=="__main__":
    unittest.main()
