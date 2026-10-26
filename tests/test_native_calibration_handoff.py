"""Independent geometry examples over saved protocol fixtures, never real DM.

Expected vectors/absolute offsets are hand enumerated. The existing scientific
encoder and independent capture validator produce/read the input contract;
neither a protocol fixture nor consistent hashes establish a real host.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from tools import image_workspace as engine


ROOT = Path(__file__).resolve().parents[1]


class NativeCalibrationHandoff(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_temp = tempfile.TemporaryDirectory(prefix="native-xy-fixtures-")
        cls.fixtures = Path(cls.fixture_temp.name)
        script = r"""import fs from 'node:fs';import path from 'node:path';
import {imageMetadata,readFixture,fourierFixture} from FIXTURE;
import {handoff} from ENCODER;
const dir=process.argv[1];
function save(name,source,args,context=null,provenance=null){
 const read=readFixture(args,{source,provenance});read.scientific_context=context;
 const receipt={protocol:'NB2',session:'a'.repeat(32),id:name,request_id:name,state:'completed',host_pid:1234,
 exec_tid:10,worker_tid:20,timings_us:{queue:0,execute:1},original_operation:'READ',normalized_args:args,
 result_type:'native_data_snapshot',result_version:1};
 const filename=path.join(dir,name+'.json');fs.writeFileSync(filename,JSON.stringify({...read,native_receipt:receipt}));
 handoff({workspace:dir,output:name,requestId:'encode-'+name,snapshot:filename});
}
const real=imageMetadata(77,{shape:[16,32]});
Object.assign(real.calibration[0],{origin:3.5,scale:-.5,calibrated_value_at_pixel_zero:1.75,unit:'nm'});
Object.assign(real.calibration[1],{origin:-2,scale:.002,calibrated_value_at_pixel_zero:.004,unit:'um'});
save('real-mixed',real,[77,4,3,20,15]);
const reciprocal=structuredClone(real);
Object.assign(reciprocal.calibration[0],{origin:10,scale:.25,calibrated_value_at_pixel_zero:-2.5,unit:'1/nm'});
Object.assign(reciprocal.calibration[1],{origin:5,scale:-.05,calibrated_value_at_pixel_zero:.25,unit:'1/angstrom'});
save('reciprocal-mixed',reciprocal,[77,4,3,20,15]);
const unknown=structuredClone(real);unknown.calibration_complete=false;
unknown.calibration.forEach(a=>Object.assign(a,{unit:null,usable:false,issue:'unknown_units'}));
save('unknown',unknown,[77,4,3,20,15]);
const unsupported=structuredClone(real);unsupported.calibration.forEach(a=>a.unit='counts');
save('unsupported-unit',unsupported,[77,4,3,20,15]);
const producer=fourierFixture('REAL',77),source=producer.image;
const context={schema_version:1,status:'tracked_fourier',original_operation:'REAL',request_id:'component',
 normalized_args:[77],result_version:2,result:producer,source_offset_xy:[0,0],postprocessing:[]};
save('native-fft',source,[99,1,1,7,4],context,{operation:'REAL',request_id:'component',source_image_ids:[77],semantics:'synthetic contract only'});
""".replace("FIXTURE", json.dumps((ROOT / "tests/fixtures/native-operations.mjs").as_uri())).replace(
            "ENCODER", json.dumps((ROOT / "tools/native_snapshot_handoff.mjs").as_uri()))
        result = subprocess.run(["node", "--input-type=module", "-e", script, str(cls.fixtures)],
                                cwd=str(ROOT), capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.fixture_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-xy-case-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.counter = 0

    def call(self, action, **args):
        self.counter += 1
        return engine.execute({"workspace": str(self.workspace), "action": action,
                               "request_id": "native-xy-" + str(self.counter), **args})

    def ok(self, action, **args):
        response = self.call(action, **args)
        self.assertTrue(response["ok"], response)
        return response["result"]

    def capture(self, name="real-mixed"):
        target = self.root / name
        shutil.copytree(self.fixtures / name, target)
        return target

    def opened(self, name="real-mixed"):
        path = self.capture(name)
        return self.ok("import_capture", source_path=str(path)), path

    def rehash_metadata(self, path, edit):
        info, manifest = [json.loads((path / name).read_text()) for name in ("input.json", "capture.json")]
        edit(info)
        raw = engine.canonical(info)
        (path / "input.json").write_bytes(raw)
        manifest["input_metadata_sha256"] = hashlib.sha256(raw).hexdigest()
        manifest["input_metadata_file_sha256"] = hashlib.sha256(raw).hexdigest()
        (path / "capture.json").write_bytes(engine.canonical(manifest))

    def test_reciprocal_scale_revision_preserves_dc_and_recomputes_zero(self):
        from crystallography.reflection_compare import measurement_vector
        frame, _ = self.opened("reciprocal-mixed")
        original = copy.deepcopy(frame["xy_calibration"])
        source_bytes = Path(frame["array_path"]).read_bytes()
        revised = self.ok("calibrate", object_id=frame["object_id"], scope="image",
                          coordinate_domain="reciprocal_space",
                          xy_scale={"x": .2, "y": -.4, "unit": "1/nm"},
                          source_text="Synthetic scale-only correction; centre unchanged")
        record = revised["xy_calibration"]
        self.assertEqual(record["dc_index_xy"], [6, 2])
        self.assertEqual(record["dc_identity_source"], original["dc_identity_source"])
        np.testing.assert_allclose(record["physical_zero_xy"], [-1.2, .8], atol=1e-15, rtol=0)
        view = self.ok("view", object_id=revised["object_id"], rect=[2, 1, 15, 10])
        result = self.ok("measure", object_id=view["object_id"], points=[[6, 2], [10, 5]])
        self.assertEqual(result["dc_reference_point_index"], 0)
        self.assertAlmostEqual(result["d_spacing"], 1 / math.hypot(.8, -1.2))
        np.testing.assert_allclose(result["physical_points_xy"], [[0, 0], [.8, -1.2]], atol=1e-15, rtol=0)
        np.testing.assert_allclose(measurement_vector(result)["q_xy_inv_angstrom"], [.08, -.12], atol=1e-15, rtol=0)
        self.assertEqual(self.ok("get", object_id=frame["object_id"])["xy_calibration"], original)
        self.assertEqual(Path(frame["array_path"]).read_bytes(), source_bytes)

    def test_reciprocal_revision_inherits_domain_and_preserves_dc_through_withdrawal(self):
        frame, _ = self.opened("reciprocal-mixed")
        revised = self.ok("calibrate", object_id=frame["object_id"], scope="image",
                          xy_scale={"x": .02, "y": -.04, "unit": "1/angstrom"},
                          source_text="Synthetic unit/scale correction, same origin")
        self.assertEqual(revised["xy_calibration"]["coordinate_domain"], "reciprocal_space")
        np.testing.assert_allclose(revised["xy_calibration"]["physical_zero_xy"], [-.12, .08], rtol=0, atol=1e-15)
        withdrawn = self.ok("calibrate", object_id=revised["object_id"], scope="image", xy_scale=None,
                            source_text="Withdraw only the physical scale, not the recorded pixel centre")
        self.assertEqual(withdrawn["xy_calibration"]["dc_index_xy"], [6, 2])
        measured = self.ok("measure", object_id=withdrawn["object_id"], points=[[6, 2], [10, 5]])
        self.assertIsNone(measured["physical_frequency_magnitude"])
        self.assertIsNone(measured["d_spacing"])
        restored = self.ok("calibrate", object_id=withdrawn["object_id"], scope="image",
                           xy_scale={"x": .2, "y": -.4, "unit": "1/nm"}, source_text="Restore sourced scale")
        self.assertEqual(restored["xy_calibration"]["revision"], 4)
        measured = self.ok("measure", object_id=restored["object_id"], points=[[6, 2], [10, 5]])
        self.assertAlmostEqual(measured["d_spacing"], 1 / math.hypot(.8, -1.2))
        self.assertFalse(self.call("calibrate", object_id=restored["object_id"], scope="image",
                                  coordinate_domain="real_space", xy_scale={"x": 1, "y": 1, "unit": "nm"},
                                  source_text="Do not reinterpret the reciprocal array")["ok"])

    def test_scale_revision_does_not_invent_a_dc_or_hide_unrepresentable_zero(self):
        from tools import image_calibration as calibration
        method = calibration.revised_reciprocal_origin
        base = {"coordinate_domain": "reciprocal_space", "calibration_id": "a" * 32}
        scale = calibration.validated_scale({"x": .2, "y": -.4, "unit": "1/nm"}, "reciprocal_space")
        self.assertEqual(method(base, scale), {})
        self.assertEqual(method({**base, "coordinate_domain": "real_space", "dc_index_xy": [6, 2]}, scale), {})
        for dc, steps in (([1e308, 2], {"x": 10., "y": 1.}), ([1e-300, 2], {"x": 1e-100, "y": 1.})):
            with self.subTest(dc=dc), self.assertRaises(calibration.CalibrationError):
                method({**base, "dc_index_xy": dc}, steps)
        # The helper never changes the old record; a withdrawn scale has no
        # physical zero, but its exact pixel origin remains available.
        old = {**base, "dc_index_xy": [6, 2], "dc_identity_source": "independent fixture"}
        before = copy.deepcopy(old)
        self.assertNotIn("physical_zero_xy", method(old, None))
        self.assertEqual(old, before)

    def test_automatic_native_scale_mixed_units_signed_axes_read_offset_and_3_4_5(self):
        frame, capture = self.opened()
        record = frame["xy_calibration"]
        self.assertEqual(record["source"], "native_dm_capture")
        self.assertEqual(record["revision"], 1)
        self.assertEqual(record["coordinate_domain"], "real_space")
        self.assertEqual(record["xy_scale"]["unit"], "nm")
        self.assertEqual(record["xy_scale"]["x"], -.5)
        self.assertAlmostEqual(record["xy_scale"]["y"], 2.)
        self.assertEqual(record["native_axes"][0]["raw_origin"], -.5)
        self.assertEqual(record["native_axes"][1]["raw_origin"], -5)
        self.assertAlmostEqual(record["physical_zero_xy"][0], -.25)
        self.assertAlmostEqual(record["physical_zero_xy"][1], 10.)
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in capture.iterdir()}
        measured = self.ok("measure", object_id=frame["object_id"], points=[[1, 1], [7, 3]])
        self.assertAlmostEqual(measured["physical_vector_xy"][0], -3.)
        self.assertAlmostEqual(measured["physical_vector_xy"][1], 4.)
        self.assertAlmostEqual(measured["physical_distance"], 5.)
        self.assertEqual(measured["physical_unit"], "nm")
        self.assertEqual(measured["calibration_dependency"]["source"], "native_dm_capture")
        for got, expected in zip(measured["physical_points_xy"], [[-.75, 12.], [-3.75, 16.]]):
            np.testing.assert_allclose(got, expected, rtol=0, atol=4e-15)
        cropped = self.ok("view", object_id=frame["object_id"], rect=[2, 1, 15, 10], max_size=320, upscale=True)
        self.assertEqual(cropped["scale_bar"]["provenance"], "native_dm_capture")
        double_crop = self.ok("view", object_id=cropped["object_id"], rect=[1, 1, 12, 8])
        again = self.ok("measure", object_id=double_crop["object_id"], points=[[3, 2], [9, 4]])
        self.assertAlmostEqual(again["physical_distance"], 5.)
        self.assertEqual(again["source_rect_xyxy"], [3, 2, 14, 9])
        self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in capture.iterdir()})

    def test_reciprocal_capture_returns_frequency_not_real_distance_and_requires_explicit_domain(self):
        frame, _ = self.opened("reciprocal-mixed")
        record = frame["xy_calibration"]
        self.assertEqual(record["coordinate_domain"], "reciprocal_space")
        self.assertEqual(frame["array_domain"], "reciprocal")
        self.assertEqual(record["xy_scale"]["x"], .25)
        self.assertAlmostEqual(record["xy_scale"]["y"], -.5)
        measured = self.ok("measure", object_id=frame["object_id"], points=[[6, 2], [10, 5]])
        self.assertEqual(measured["coordinate_space"], "source_array_indices")
        self.assertIsNone(measured["physical_distance"])
        self.assertEqual(measured["physical_frequency_unit"], "cycles/nm")
        np.testing.assert_allclose(measured["physical_vector_xy"], [1., -1.5], rtol=0, atol=1e-15)
        self.assertAlmostEqual(measured["physical_frequency_magnitude"], math.sqrt(3.25))
        self.assertAlmostEqual(measured["d_spacing"], 1 / math.sqrt(3.25))
        viewed = self.ok("view", object_id=frame["object_id"], max_size=320, upscale=True)
        self.assertIsNone(viewed["scale_bar"])
        self.assertEqual(viewed["panels"][0]["domain"], "source_array_indices")
        refused = self.call("calibrate", object_id=frame["object_id"], scope="image",
                            xy_scale={"x": 1, "y": 1, "unit": "nm"}, source_text="do not misapply real-space scale")
        self.assertFalse(refused["ok"])
        updated = self.ok("calibrate", object_id=frame["object_id"], scope="image", coordinate_domain="reciprocal_space",
                          xy_scale={"x": .2, "y": -.4, "unit": "1/nm"}, source_text="synthetic explicit inverse-length correction")
        self.assertEqual(updated["xy_calibration"]["revision"], 2)
        self.assertEqual(updated["xy_calibration"]["previous_calibration_id"], frame["object_id"])
        self.assertFalse(self.call("measure", object_id=frame["object_id"], coordinate_space="source_pixels", points=[[6, 2], [10, 5]])["ok"])
        cropped = self.ok("view", object_id=frame["object_id"], rect=[2, 1, 15, 10])
        nested = self.ok("view", object_id=cropped["object_id"], rect=[1, 1, 12, 8])
        # These coordinates are in the fixed captured NPY (not the whole DM
        # source). Original READ[4,3,...] is already in the axis zero/DC.
        repeated = self.ok("measure", object_id=nested["object_id"], points=[[6, 2], [10, 5]])
        self.assertEqual(repeated["source_rect_xyxy"], [3, 2, 14, 9])
        self.assertEqual(repeated["dc_reference_point_index"], 0)
        np.testing.assert_allclose(repeated["physical_vector_xy"], [1., -1.5], rtol=0, atol=1e-15)
        self.assertEqual(repeated["physical_points_xy"], measured["physical_points_xy"])

    def test_saved_external_fft_uses_native_scale_revisions_without_recomputing_or_rewriting(self):
        frame, _ = self.opened()
        fft = self.ok("fft", object_id=frame["object_id"], rect=[0, 0, 8, 8])
        original = Path(fft["array_path"]).read_bytes()
        revised = self.ok("calibrate", object_id=fft["object_id"], scope="image",
                          xy_scale={"x": -.25, "y": 1., "unit": "nm"}, source_text="synthetic user correction")
        self.assertEqual(revised["xy_calibration"]["revision"], 2)
        self.assertEqual(revised["xy_calibration"]["source"], "user_statement_not_independently_verified")
        with patch.object(np.fft, "fft2", side_effect=AssertionError("must reuse saved complex spectrum")):
            view = self.ok("view", object_id=revised["object_id"], spectrum_axes=True, max_size=320, upscale=True)
            measured = self.ok("measure", object_id=view["object_id"], points=[[0, 0], [.125, .25]])
        self.assertEqual(Path(view["array_path"]).read_bytes(), original)
        self.assertEqual(measured["physical_vector_xy"], [-.5, .25])
        self.assertAlmostEqual(measured["d_spacing"], 1 / math.sqrt(.3125))
        self.assertFalse(view["fft_recomputed"])
        self.assertEqual(view["physical_frequency_axes"][1]["step"], -.5)
        withdrawn = self.ok("calibrate", object_id=revised["object_id"], scope="image", xy_scale=None,
                            source_text="synthetic user withdrew correction")
        self.assertEqual(withdrawn["xy_calibration"]["revision"], 3)
        self.assertIsNone(self.ok("measure", object_id=withdrawn["object_id"], points=[[0, 0], [.125, .25]])["physical_frequency_magnitude"])
        exported = self.ok("export", object_id=view["object_id"], output_dir=str(self.root / "export"))
        provenance = json.loads((Path(exported["output_dir"]) / "provenance.json").read_text())
        self.assertEqual(provenance["objects"][frame["object_id"]]["xy_calibration"]["source"], "native_dm_capture")
        self.assertEqual(provenance["objects"][revised["object_id"]]["xy_calibration"]["revision"], 2)

    def test_tracked_native_fft_uses_mathematical_dc_not_half_bin_native_origin(self):
        frame, _ = self.opened("native-fft")
        record = frame["xy_calibration"]
        self.assertEqual(record["coordinate_domain"], "reciprocal_space")
        self.assertEqual(record["physical_zero_xy"], [1.5, -.5])
        self.assertEqual(record["raw_native_calibration"][0]["calibrated_value_at_pixel_zero"], 1.75)
        measured = self.ok("measure", object_id=frame["object_id"], points=[[3, 1], [4, 1]])
        self.assertEqual(measured["physical_points_xy"], [[0., 0.], [-.5, 0.]])
        self.assertEqual(measured["d_spacing"], 2.)
        wrong = self.call("measure", object_id=frame["object_id"], coordinate_space="frequency_cycles_per_pixel", points=[[0, 0], [.125, 0]])
        self.assertFalse(wrong["ok"])

    def test_unknown_unsupported_or_conflicting_metadata_remains_pixel_only(self):
        for name in ("unknown", "unsupported-unit"):
            frame, _ = self.opened(name)
            self.assertNotIn("xy_calibration", frame)
            self.assertEqual(frame["calibration_admission"]["status"], "pixel_only")
            self.assertIsNone(self.ok("measure", object_id=frame["object_id"], points=[[1, 1], [7, 3]])["physical_distance"])
        conflict = self.capture()
        self.rehash_metadata(conflict, lambda info: info.update(native_external_import={"coordinate_domain": "reciprocal_space"}))
        frame = self.ok("import_capture", source_path=str(conflict))
        self.assertNotIn("xy_calibration", frame)
        self.assertIn("historical", frame["calibration_admission"]["reason"])

    def test_wrong_hash_receipt_and_mixed_domains_never_activate_physical_results(self):
        capture = self.capture()
        info_path = capture / "input.json"
        info = json.loads(info_path.read_text());info["working_calibration_xy"][0]["scale"] = 123
        info_path.write_bytes(engine.canonical(info))
        self.assertFalse(self.call("import_capture", source_path=str(capture))["ok"])
        other = self.root / "wrong-receipt";shutil.copytree(self.fixtures / "real-mixed", other)
        self.rehash_metadata(other, lambda info: info["native_receipt"].update(host_pid=9876))
        self.assertFalse(self.call("import_capture", source_path=str(other))["ok"])
        from tools import image_calibration as cal
        info = json.loads((self.fixtures / "real-mixed" / "input.json").read_text())
        info["working_calibration_xy"][1]["unit"] = "1/nm"
        record, admission = cal.native_record(info, {}, "a" * 32, {})
        self.assertIsNone(record)
        self.assertIn("domains disagree", admission["reason"])

    def test_nonzero_native_zero_cannot_underflow_during_mixed_unit_conversion(self):
        from tools import image_calibration as cal
        info = {"working_calibration_xy": [
            {"dm_dimension": 0, "numpy_axis": 1, "size": 1, "origin": 0., "scale": 1.,
             "calibrated_value_at_pixel_zero": 0., "unit": "m", "usable": True},
            {"dm_dimension": 1, "numpy_axis": 0, "size": 1, "origin": -5e-324, "scale": 1.,
             "calibrated_value_at_pixel_zero": 5e-324, "unit": "angstrom", "usable": True}],
            "scientific_semantics": {}, "scientific_context": None}
        record, admission = cal.native_record(info, {}, "a" * 32, {})
        self.assertIsNone(record)
        self.assertEqual(admission["status"], "pixel_only")
        self.assertIn("resolution", admission["reason"])
        # A representable conversion is still admitted without a wider cutoff.
        info["working_calibration_xy"][1]["calibrated_value_at_pixel_zero"] = 1e-300
        record, _ = cal.native_record(info, {}, "a" * 32, {})
        self.assertIsNotNone(record)
        self.assertNotEqual(record["physical_zero_xy"][1], 0.)

    def test_nonzero_absolute_point_product_cannot_underflow_to_zero(self):
        from tools import image_calibration as cal
        record = {"status": "active", "coordinate_domain": "real_space", "calibration_id": "b" * 32,
                  "revision": 1, "physical_zero_xy": [0., 0.],
                  "xy_scale": cal.validated_scale({"x": 1e-308, "y": 1., "unit": "m"})}
        with self.assertRaisesRegex(cal.CalibrationError, "underflows"):
            cal.physical_points([[1e-20, 0.]], record)
        self.assertEqual(cal.physical_points([[1., 0.]], record), [[1e-308, 0.]])
        self.assertEqual(cal.physical_points([[0., 0.]], record), [[0., 0.]])

    def test_known_native_spatial_image_cannot_be_reinterpreted_by_reciprocal_scale(self):
        frame, capture = self.opened()
        original_manifest = Path(frame["manifest_path"]).read_bytes()
        original_input = (capture / "input.npy").read_bytes()
        refused = self.call("calibrate", object_id=frame["object_id"], scope="image", coordinate_domain="reciprocal_space",
                            xy_scale={"x": .2, "y": .2, "unit": "1/nm"}, source_text="synthetic wrong domain")
        self.assertFalse(refused["ok"])
        self.assertIn("cannot change an established", refused["error"]["message"])
        self.assertEqual(Path(frame["manifest_path"]).read_bytes(), original_manifest)
        self.assertEqual((capture / "input.npy").read_bytes(), original_input)
        still_real = self.ok("measure", object_id=frame["object_id"], points=[[1, 1], [7, 3]])
        self.assertEqual(still_real["measurement_domain"], "real_space")
        self.assertAlmostEqual(still_real["physical_distance"], 5.)

    def test_user_domain_cannot_change_or_bypass_the_guard_through_withdrawal(self):
        capture = self.root / "generic-capture";capture.mkdir()
        values = np.arange(64, dtype=np.float32).reshape(8, 8)
        np.save(capture / "input.npy", values, allow_pickle=False)
        digest = hashlib.sha256((capture / "input.npy").read_bytes()).hexdigest()
        info = {"schema_version": 1, "capture_id": "c" * 32, "input_file": "input.npy", "input_sha256": digest,
                "dtype": "float32", "shape_yx": [8, 8], "axes": ["y", "x"], "array_order": "C", "byte_order": "little"}
        manifest = {"schema_version": 1, "capture_id": info["capture_id"], "state": "captured", "input_sha256": digest,
                    "capture_backend": "explicit generic synthetic input", "input_metadata_sha256": hashlib.sha256(engine.canonical(info)).hexdigest()}
        (capture / "input.json").write_bytes(engine.canonical(info));(capture / "capture.json").write_bytes(engine.canonical(manifest))
        frame = self.ok("import_capture", source_path=str(capture))
        self.assertNotIn("xy_calibration", frame)
        unknown_recip = self.call("calibrate", object_id=frame["object_id"], scope="image", coordinate_domain="reciprocal_space",
                                 xy_scale={"x": .2, "y": .2, "unit": "1/nm"}, source_text="unknown input is not established reciprocal")
        self.assertFalse(unknown_recip["ok"])
        calibrated = self.ok("calibrate", object_id=frame["object_id"], scope="image",
                             xy_scale={"x": .2, "y": .3, "unit": "nm"}, source_text="synthetic known real-space scale")
        withdrawn = self.ok("calibrate", object_id=calibrated["object_id"], scope="image", xy_scale=None,
                            source_text="synthetic scale withdrawal, not an array reinterpretation")
        for selected in (calibrated, withdrawn):
            failure = self.call("calibrate", object_id=selected["object_id"], scope="image", coordinate_domain="reciprocal_space",
                                xy_scale={"x": .2, "y": .2, "unit": "1/nm"}, source_text="cross-domain revision refused")
            self.assertFalse(failure["ok"])
            self.assertIn("cannot change an established", failure["error"]["message"])
        fft = self.ok("fft", object_id=frame["object_id"])
        failure = self.call("calibrate", object_id=fft["object_id"], scope="image", coordinate_domain="reciprocal_space",
                            xy_scale={"x": .2, "y": .2, "unit": "1/nm"}, source_text="do not treat reciprocal step as FFT source pixel length")
        self.assertFalse(failure["ok"])
        self.assertIn("source real-space", failure["error"]["message"])


if __name__ == "__main__":
    unittest.main()
