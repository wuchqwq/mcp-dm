# -*- coding: utf-8 -*-
"""Acceptance-only synthetic record faults; not native runtime qualification."""
import copy
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

from test_native_uint32_operations_probe import Synthetic, save, MVP, P

with mock.patch.object(sys,"path",[str(MVP)]+sys.path):
    M=runpy.run_path(str(MVP/"verify_uint32_operations_math.py"))


class Uint32OperationsMathTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.directory=Path(self.temp.name)
        self.f=Synthetic(self.directory)
        original=self.f.exchange
        def exchange(*call):
            receipt=original(*call);op=receipt["original_operation"];args=receipt["normalized_args"]
            if op=="STATUS" or call[1].split()[3]=="QUERY":return receipt
            result=receipt["result"];image_id=result["image_id"];data=self.f.images[image_id];source=self.f.images[args[0]]
            if op in ("UNARY","BINARY"):
                data["values"]=M["arithmetic_reference"](op,args,[self.f.images[value]["values"] for value in (args[:2] if op=="BINARY" else args[:1])])
            elif op=="FILTER":data["values"]=M["filter_reference"](source["values"],args[-1])
            elif op=="FFT" and args[0] in (101,106,107):
                data["values"]=M["quarter_turn_dft"](source["values"].astype(np.float32))
                data["calibration"]=M["frequency_calibration"](self.f.truth["images"][args[0]-101],source["values"].shape)
                data["intensity_calibration"]={"origin":0.,"scale":1.,"unit":""}
            elif op in ("IFFT","REAL") and (op=="IFFT" and args[0]==1020 or op=="REAL" and args[0]==1024):
                data["values"]=self.f.images[101]["values"].astype(np.complex64 if op=="IFFT" else np.float32)
                data["calibration"]=M["frequency_calibration"](self.f.truth["images"][0],data["values"].shape,True)
                data["intensity_calibration"]={"origin":0.,"scale":1.,"unit":""}
            result["image"]=self.f.metadata(image_id)
            self.f.saved[receipt["id"]]=copy.deepcopy(receipt)
            return receipt
        self.f.exchange=exchange;self.f.run();self.observation=self.f.observe()
        self.observation_path=self.directory/"observation.json";save(self.observation_path,self.observation)

    def verify(self):
        save(self.observation_path,self.observation)
        context=M["load_context"](str(self.f.truth_path),str(self.f.probe_path),str(self.f.ledger_path),str(self.observation_path))
        report={};M["verify"](report,context);return report

    def change_pixels(self,label,edit):
        entry=next(value for value in self.observation["outputs"] if value["label"]==label)
        values=np.load(entry["snapshot"],allow_pickle=False);edit(values)
        with open(entry["snapshot"],"wb") as output:np.save(output,values,allow_pickle=False)
        entry["snapshot_file_sha256"]=P["sha"](Path(entry["snapshot"]).read_bytes());entry["pixel_sha256"]=P["sha"](values.tobytes(order="C"))

    def test_positive_fixed_matrix_is_partial_and_never_upgrades_high_fft(self):
        report=self.verify();self.assertEqual(report["status"],"PASS_BOUNDED_PARTIAL_UINT32_NUMERICAL")
        self.assertEqual(report["qualified_count"],26);self.assertEqual(report["unqualified_count"],5)
        self.assertFalse(report["production_qualification"])
        self.assertEqual(set(report["unqualified_labels"]),{"fft-HIGH","ifft-HIGH","inverse-real-HIGH","fft-real-HIGH","fft-imag-HIGH"})

    def test_binary_rounding_reference_is_fixed_double_before_float32(self):
        left=P["arrays"]()["HIGH"];right=P["arrays"]()["RHS"]
        actual=M["arithmetic_reference"]("BINARY",[1,2,1],[left,right])
        self.assertEqual(actual[1,0],16777218.)
        self.assertNotEqual(actual[1,0],np.float32(left[1,0])+np.float32(right[1,0]))
        self.assertEqual(M["arithmetic_reference"]("BINARY",[1,2,2],[P["arrays"]()["LOW"],right])[0,0],-1.)

    def test_unary_negative_signed_zero_and_large_square_are_float32(self):
        reference=M["arithmetic_reference"]("UNARY",[1,1],[P["arrays"]()["HIGH"]])
        self.assertTrue(np.signbit(reference[0,0]));self.assertLess(reference[1,0],0)
        squared=M["arithmetic_reference"]("UNARY",[1,3],[P["arrays"]()["HIGH"]])
        self.assertEqual(squared.dtype,np.float32);self.assertTrue(np.isfinite(squared).all());self.assertGreater(float(squared[2,3]),4294967295.)

    def test_filter_uint32_store_truncates_and_saturates_without_wrapping(self):
        values=np.zeros((8,8),dtype=np.uint32);values[2,2]=1
        smooth=M["filter_reference"](values,1);self.assertEqual(smooth.dtype,np.uint32);self.assertEqual(int(smooth[2,2]),0)
        values[2,2]=4294967295;sharpen=M["filter_reference"](values,4)
        self.assertEqual(int(sharpen[2,2]),4294967295);self.assertEqual(int(sharpen[2,3]),0)
        self.assertEqual(int(sharpen[0,0]),int(values[0,0]))

    def test_wrong_high_arithmetic_value_reaches_fixed_math_check(self):
        self.change_pixels("binary-HIGH-1",lambda values:values.__setitem__((1,0),16777216.))
        with self.assertRaisesRegex(RuntimeError,"Fixed binary-HIGH-1 native dtype/values"):self.verify()

    def test_unsigned_negation_or_loss_of_signed_zero_is_rejected(self):
        self.change_pixels("unary-HIGH-1",lambda values:values.__setitem__((0,0),0.))
        with self.assertRaisesRegex(RuntimeError,"Fixed unary-HIGH-1 native dtype/values"):self.verify()

    def test_wrong_filter_clamp_value_reaches_fixed_math_check(self):
        self.change_pixels("filter-FILTER_HIGH-4",lambda values:values.__setitem__((2,2),0))
        with self.assertRaisesRegex(RuntimeError,"Fixed filter-FILTER_HIGH-4 native dtype/values"):self.verify()

    def test_transposed_fourier_is_not_best_matched(self):
        self.change_pixels("fft-LOW",lambda values:values.__setitem__(slice(None),values.T.copy()))
        with self.assertRaisesRegex(RuntimeError,"Fixed exact-root low-range Fourier"):self.verify()

    def test_wrong_snapshot_dtype_is_rejected(self):
        entry=self.observation["outputs"][0]
        values=np.load(entry["snapshot"],allow_pickle=False).astype(np.uint32)
        with open(entry["snapshot"],"wb") as output:np.save(output,values,allow_pickle=False)
        entry["snapshot_file_sha256"]=P["sha"](Path(entry["snapshot"]).read_bytes());entry["pixel_sha256"]=P["sha"](values.tobytes())
        with self.assertRaisesRegex(RuntimeError,"Bounded NPY header"):self.verify()

    def test_wrong_host_session_or_missing_case_are_rejected(self):
        original=copy.deepcopy(self.observation)
        for field,value in (("host_pid",os.getpid()+1),("session","f"*32),("outputs",original["outputs"][:-1])):
            with self.subTest(field=field):
                self.observation=copy.deepcopy(original);self.observation[field]=value
                with self.assertRaisesRegex(RuntimeError,"observation evidence|31-output matrix"):self.verify()

    def test_wrong_axis_calibration_binds_to_native_receipt(self):
        self.observation["outputs"][0]["calibration"][0]["scale"]*=-1
        with self.assertRaisesRegex(RuntimeError,"signed calibration differs"):self.verify()

    def test_unbound_npys_do_not_gain_pass_from_self_report(self):
        self.observation["outputs"][0]["pixel_sha256"]="0"*64
        with self.assertRaisesRegex(RuntimeError,"NPY/file/pixel hash"):self.verify()


if __name__=="__main__":unittest.main()
