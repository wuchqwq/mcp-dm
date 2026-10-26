"""Hand-computable centre/scale revisions on immutable scientific grids."""
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import tifffile

from tools import image_workspace as engine


ROOT = Path(__file__).resolve().parents[1]


class CentreRevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_temp = tempfile.TemporaryDirectory(prefix="centre-native-fixture-")
        cls.addClassCleanup(cls.fixture_temp.cleanup)
        cls.fixtures = Path(cls.fixture_temp.name)
        script = """import fs from 'node:fs';import path from 'node:path';
import {imageMetadata,readFixture,fourierFixture} from FIXTURE;
import {handoff} from ENCODER;
const dir=process.argv[1],source=imageMetadata(51,{shape:[16,24]});
Object.assign(source.calibration[0],{origin:6,scale:-.25,calibrated_value_at_pixel_zero:1.5,unit:'1/nm'});
Object.assign(source.calibration[1],{origin:5,scale:.05,calibrated_value_at_pixel_zero:-.25,unit:'1/angstrom'});
const args=[51,0,0,24,16],read=readFixture(args,{source});
const receipt={protocol:'NB2',session:'a'.repeat(32),id:'centre-source',request_id:'centre-source',state:'completed',host_pid:1234,
exec_tid:10,worker_tid:20,timings_us:{queue:0,execute:1},original_operation:'READ',normalized_args:args,result_type:'native_data_snapshot',result_version:1};
const filename=path.join(dir,'source.json');fs.writeFileSync(filename,JSON.stringify({...read,native_receipt:receipt}));
handoff({workspace:dir,output:'mixed-native',requestId:'encode-mixed',snapshot:filename});
const producer=fourierFixture('REAL',77),fourierRead=readFixture([99,1,1,7,4],{source:producer.image,provenance:{operation:'REAL',request_id:'component',source_image_ids:[77],semantics:'synthetic contract only'}});
fourierRead.scientific_context={schema_version:1,status:'tracked_fourier',original_operation:'REAL',request_id:'component',normalized_args:[77],result_version:2,result:producer,source_offset_xy:[0,0],postprocessing:[]};
const fftReceipt={...receipt,id:'native-fourier',request_id:'native-fourier',normalized_args:[99,1,1,7,4]};
const fftFile=path.join(dir,'fourier.json');fs.writeFileSync(fftFile,JSON.stringify({...fourierRead,native_receipt:fftReceipt}));
handoff({workspace:dir,output:'native-fourier',requestId:'encode-fourier',snapshot:fftFile});
""".replace("FIXTURE", json.dumps((ROOT / "tests/fixtures/native-operations.mjs").as_uri())).replace(
            "ENCODER", json.dumps((ROOT / "tools/native_snapshot_handoff.mjs").as_uri()))
        made = subprocess.run(["node", "--input-type=module", "-e", script, str(cls.fixtures)],
                              capture_output=True, text=True, cwd=ROOT, timeout=30)
        if made.returncode:
            raise RuntimeError(made.stderr + made.stdout)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="centre-revision-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root / "workspace"
        self.source = self.root / "sequence.tiff"
        self.values = np.arange(2 * 16 * 24, dtype=np.uint16).reshape(2, 16, 24)
        tifffile.imwrite(self.source, self.values, photometric="minisblack", metadata={"axes": "IYX"})
        self.source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.counter = 0
        self.sequence = self.ok("open", source_path=str(self.source))
        self.frame = self.ok("frame", object_id=self.sequence["object_id"], frame_index=0)

    def req(self, action, **args):
        self.counter += 1
        return dict(workspace=str(self.workspace), action=action, request_id="revision-{}".format(self.counter), **args)

    def ok(self, action, **args):
        reply = engine.execute(self.req(action, **args))
        self.assertTrue(reply["ok"], reply)
        return reply["result"]

    def declared(self):
        return self.ok("calibrate", object_id=self.frame["object_id"], coordinate_domain="reciprocal_space", scope="image",
                       declare_reciprocal=True, xy_scale={"x": .25, "y": -.5, "unit": "1/nm"},
                       source_text="Synthetic detector reciprocal domain and independent signed XY scale")

    def centred(self, previous=None, point=None):
        return self.ok("centre", object_id=(previous or self.declared())["object_id"], center_xy=point or [6, 5],
                       coordinate_space="source_array_indices", source_text="Synthetic explicit centre in original array coordinates")

    def test_unknown_domain_declaration_is_explicit_and_source_immutable(self):
        rejected = engine.execute(self.req("calibrate", object_id=self.frame["object_id"], scope="image", coordinate_domain="reciprocal_space",
                                          xy_scale={"x": .25, "y": -.5, "unit": "1/nm"}, source_text="No explicit domain declaration"))
        self.assertFalse(rejected["ok"])
        declared = self.declared()
        self.assertEqual(declared["xy_calibration"]["domain_declaration"]["source"], "user_statement_not_independently_verified")
        measured = self.ok("measure", object_id=declared["object_id"], points=[[6, 5], [10, 7]])
        self.assertEqual(measured["coordinate_space"], "source_array_indices")
        self.assertEqual(measured["physical_vector_xy"], [1., -1.])
        self.assertIsNone(measured["d_spacing"])
        original = self.ok("get", object_id=self.frame["object_id"])
        self.assertNotIn("array_domain", original)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_hash)
        np.testing.assert_array_equal(np.load(self.frame["array_path"]), self.values[0])

    def test_centre_revision_reuses_peak_and_moves_only_old_dc_endpoint(self):
        initial = self.centred()
        old = self.ok("measure", object_id=initial["object_id"], points=[[6, 5], [10, 7]])
        self.assertEqual(old["physical_vector_xy"], [1., -1.])
        self.assertAlmostEqual(old["d_spacing"], 1 / math.sqrt(2))
        updated = self.centred(initial, [7, 4])
        result = self.ok("remeasure", object_id=updated["object_id"], measurement_object_id=old["object_id"])
        self.assertEqual(result["kind"], "measure")
        self.assertEqual(result["points"], [[7, 4], [10, 7]])
        self.assertEqual(result["physical_vector_xy"], [.75, -1.5])
        self.assertAlmostEqual(result["d_spacing"], 1 / math.sqrt(2.8125))
        self.assertEqual(result["physical_points_xy"][0], [0., 0.])
        self.assertTrue(result["remeasurement"]["dc_endpoint_updated"])
        self.assertEqual(updated["xy_calibration"]["physical_zero_xy"], [-1.75, 2.])
        self.assertEqual(updated["xy_calibration"]["previous_calibration_id"], initial["xy_calibration"]["calibration_id"])
        self.assertEqual(result["calibration_dependency"]["centre_revision_id"], updated["object_id"])
        self.assertEqual(self.ok("get", object_id=old["object_id"])["points"], [[6, 5], [10, 7]])

    def test_scale_revision_preserves_corrected_centre_and_dependency(self):
        initial = self.centred()
        old = self.ok("measure", object_id=initial["object_id"], points=[[10, 7], [6, 5]])
        centre = self.centred(initial, [7, 4])
        scaled = self.ok("calibrate", object_id=centre["object_id"], scope="image", xy_scale={"x": .5, "y": -.5, "unit": "1/nm"},
                         source_text="Synthetic independently corrected scale")
        result = self.ok("remeasure", object_id=scaled["object_id"], measurement_object_id=old["object_id"])
        self.assertEqual(result["points"], [[10, 7], [7, 4]])
        self.assertEqual(result["dc_reference_point_index"], 1)
        self.assertEqual(result["physical_vector_xy"], [-1.5, 1.5])
        self.assertAlmostEqual(result["d_spacing"], 1 / math.sqrt(4.5))
        self.assertEqual(scaled["xy_calibration"]["dc_index_xy"], [7, 4])
        self.assertEqual(scaled["xy_calibration"]["centre_revision_id"], centre["object_id"])

    def test_non_dc_vector_keeps_both_points_and_user_point_correction_is_explicit(self):
        initial = self.centred()
        old = self.ok("measure", object_id=initial["object_id"], points=[[8, 6], [10, 7]])
        centre = self.centred(initial, [7, 4])
        reused = self.ok("remeasure", object_id=centre["object_id"], measurement_object_id=old["object_id"])
        self.assertEqual(reused["points"], old["points"])
        self.assertFalse(reused["remeasurement"]["dc_endpoint_updated"])
        self.assertIsNone(reused["d_spacing"])
        corrected = self.ok("remeasure", object_id=centre["object_id"], measurement_object_id=old["object_id"],
                            points=[[7, 4], [11, 7]], source_text="User moved this peak one original detector pixel")
        self.assertEqual(corrected["points"], [[7, 4], [11, 7]])
        self.assertFalse(corrected["remeasurement"]["reused_saved_points"])
        self.assertEqual(corrected["physical_vector_xy"], [1., -1.5])
        bad = engine.execute(self.req("remeasure", object_id=centre["object_id"], measurement_object_id=old["object_id"], points=[[7, 4], [11, 7]]))
        self.assertFalse(bad["ok"])

    def test_withdrawn_scale_keeps_pixel_centre_without_physical_claim(self):
        first = self.centred()
        old = self.ok("measure", object_id=first["object_id"], points=[[6, 5], [10, 7]])
        withdrawn = self.ok("calibrate", object_id=first["object_id"], scope="image", xy_scale=None,
                            source_text="User withdrew scale, not saved peak coordinates")
        revised = self.centred(withdrawn, [7, 4])
        self.assertEqual(revised["xy_calibration"]["status"], "withdrawn")
        self.assertNotIn("physical_zero_xy", revised["xy_calibration"])
        result = self.ok("remeasure", object_id=revised["object_id"], measurement_object_id=old["object_id"])
        self.assertEqual(result["points"], [[7, 4], [10, 7]])
        self.assertIsNone(result["physical_frequency_magnitude"])
        self.assertIsNone(result["d_spacing"])
        self.assertEqual(result["dc_reference_point_index"], 0)
        again = self.centred(revised, [8, 4])
        unscaled = self.ok("remeasure", object_id=again["object_id"], measurement_object_id=result["object_id"])
        self.assertEqual(unscaled["points"], [[8, 4], [10, 7]])
        self.assertIsNone(unscaled["physical_frequency_magnitude"])
        restored = self.ok("calibrate", object_id=again["object_id"], scope="image", xy_scale={"x": .25, "y": -.5, "unit": "1/nm"},
                           source_text="User supplied corrected scale again")
        self.assertEqual(restored["xy_calibration"]["dc_index_xy"], [8, 4])
        physical = self.ok("remeasure", object_id=restored["object_id"], measurement_object_id=unscaled["object_id"])
        self.assertEqual(physical["physical_vector_xy"], [.5, -1.5])
        self.assertAlmostEqual(physical["d_spacing"], 1 / math.sqrt(2.5))

    def test_saved_fft_scale_remeasurement_never_recomputes_or_recentres(self):
        selected = self.ok("calibrate", object_id=self.frame["object_id"], scope="image", xy_scale={"x": .2, "y": -.5, "unit": "nm"},
                           source_text="Synthetic real-space scale")
        fft = self.ok("fft", object_id=selected["object_id"], rect=[2, 2, 18, 10])
        old = self.ok("measure", object_id=fft["object_id"], points=[[0, 0], [.125, .25]])
        original = Path(fft["array_path"]).read_bytes()
        revised = self.ok("calibrate", object_id=fft["object_id"], scope="image", xy_scale={"x": .4, "y": -.25, "unit": "nm"},
                          source_text="Synthetic corrected scale, unchanged saved spectrum")
        with patch.object(np.fft, "fft2", side_effect=AssertionError("Do not recompute")):
            result = self.ok("remeasure", object_id=revised["object_id"], measurement_object_id=old["object_id"])
            bad = engine.execute(self.req("centre", object_id=revised["object_id"], center_xy=[1, 1], coordinate_space="source_array_indices", source_text="Not a legitimate FFT DC correction"))
        self.assertEqual(result["physical_vector_xy"], [.3125, -1.])
        self.assertEqual(result["points"], old["points"])
        self.assertEqual(Path(fft["array_path"]).read_bytes(), original)
        self.assertFalse(bad["ok"])

    def test_cross_frame_roi_and_separately_computed_fft_refuse(self):
        old = self.ok("measure", object_id=self.frame["object_id"], points=[[1, 1], [4, 5]])
        other = self.ok("frame", object_id=self.sequence["object_id"], frame_index=1)
        cropped = self.ok("view", object_id=self.frame["object_id"], rect=[0, 0, 12, 12])
        for target in (other, cropped):
            bad = engine.execute(self.req("remeasure", object_id=target["object_id"], measurement_object_id=old["object_id"]))
            self.assertFalse(bad["ok"])
            self.assertEqual(bad["error"]["code"], "MEASUREMENT_SCOPE_MISMATCH")
        a = self.ok("fft", object_id=self.frame["object_id"], rect=[0, 0, 8, 8])
        b = self.ok("fft", object_id=self.frame["object_id"], rect=[0, 0, 8, 8])
        measured = self.ok("measure", object_id=a["object_id"], points=[[0, 0], [.125, 0]])
        self.assertFalse(engine.execute(self.req("remeasure", object_id=b["object_id"], measurement_object_id=measured["object_id"]))["ok"])

    def test_remeasurement_through_old_measurement_wrapper_uses_selected_revision(self):
        first = self.centred()
        old = self.ok("measure", object_id=first["object_id"], points=[[6, 5], [10, 7]])
        revised = self.ok("calibrate", object_id=old["object_id"], scope="image", xy_scale={"x": .5, "y": -.5, "unit": "1/nm"},
                          source_text="Correction applied while old measurement selected")
        result = self.ok("remeasure", object_id=revised["object_id"], measurement_object_id=old["object_id"])
        self.assertEqual(result["physical_vector_xy"], [2., -1.])
        self.assertEqual(result["calibration_dependency"]["calibration_id"], revised["object_id"])

    def test_mixed_native_units_remain_original_evidence_after_centre_correction(self):
        frame = self.ok("import_capture", source_path=str(self.fixtures / "mixed-native"))
        original = Path(frame["array_path"]).read_bytes()
        old = self.ok("measure", object_id=frame["object_id"], points=[[6, 5], [10, 7]])
        centre = self.centred(frame, [7, 4])
        new = self.ok("remeasure", object_id=centre["object_id"], measurement_object_id=old["object_id"])
        self.assertEqual(new["physical_vector_xy"], [-.75, 1.5])
        self.assertEqual(centre["xy_calibration"]["physical_zero_xy"], [1.75, -2.])
        self.assertEqual(centre["xy_calibration"]["native_axes"], frame["xy_calibration"]["native_axes"])
        self.assertEqual(centre["xy_calibration"]["source"], "user_statement_not_independently_verified")
        self.assertEqual(Path(frame["array_path"]).read_bytes(), original)

    def test_invalid_centres_context_or_known_real_domain_never_pass(self):
        selected = self.declared()
        for point in ([float("nan"), 0], [24, 1], [-1, 0], [0, 16], [True, 1], [1], [5e-324, 0]):
            bad = engine.execute(self.req("centre", object_id=selected["object_id"], center_xy=point,
                                          coordinate_space="source_array_indices", source_text="Invalid synthetic centre"))
            self.assertFalse(bad["ok"])

    def test_declaration_cannot_silently_expand_to_other_frames(self):
        declared = self.declared()
        bad = engine.execute(self.req("calibrate", object_id=declared["object_id"], scope="sequence",
                                      coordinate_domain="reciprocal_space", xy_scale={"x": .25, "y": -.5, "unit": "1/nm"},
                                      source_text="A single frame declaration is not a sequence-wide domain proof"))
        self.assertFalse(bad["ok"])
        other = self.ok("frame", object_id=self.sequence["object_id"], frame_index=1)
        bad = engine.execute(self.req("calibrate", object_id=other["object_id"], calibration_object_id=declared["object_id"]))
        self.assertFalse(bad["ok"])

    def test_tracked_native_fourier_scalar_centre_is_fixed(self):
        frame = self.ok("import_capture", source_path=str(self.fixtures / "native-fourier"))
        self.assertEqual(frame["xy_calibration"]["dc_identity_source"], "validated mathematical Fourier bins")
        bad = engine.execute(self.req("centre", object_id=frame["object_id"], center_xy=[1, 1],
                                      coordinate_space="source_array_indices", source_text="Cannot recenter unchanged native Fourier values"))
        self.assertFalse(bad["ok"])
        self.assertIn("fixed mathematical DC", bad["error"]["message"])

    def test_existing_reconstruction_or_real_calibration_cannot_be_redeclared(self):
        context = self.ok("context", object_id=self.frame["object_id"], metadata={"reconstruction_type": "ptychography real-space reconstruction"})
        real = self.ok("calibrate", object_id=self.frame["object_id"], scope="image", xy_scale={"x": .1, "y": .1, "unit": "nm"}, source_text="Known spatial scale")
        for target in (context, real):
            bad = engine.execute(self.req("calibrate", object_id=target["object_id"], coordinate_domain="reciprocal_space", scope="image",
                                          declare_reciprocal=True, xy_scale={"x": .25, "y": -.5, "unit": "1/nm"}, source_text="Cannot reinterpret known real data"))
            self.assertFalse(bad["ok"])

    def test_original_request_recovery_conflict_and_changed_history_refuse(self):
        initial = self.centred()
        old = self.ok("measure", object_id=initial["object_id"], points=[[6, 5], [10, 7]])
        revised = self.centred(initial, [7, 4])
        req = self.req("remeasure", object_id=revised["object_id"], measurement_object_id=old["object_id"])
        result = engine.execute(req)
        self.assertTrue(result["ok"], result)
        self.assertEqual(engine.execute(req), result)
        self.assertEqual(engine.execute(dict(workspace=str(self.workspace), action="result", query_request_id=req["request_id"])), result)
        conflict = engine.execute({**req, "source_text": "Different operation arguments"})
        self.assertEqual(conflict["error"]["code"], "REQUEST_CONFLICT")
        Path(old["manifest_path"]).write_bytes(Path(old["manifest_path"]).read_bytes() + b" ")
        bad = engine.execute(self.req("remeasure", object_id=revised["object_id"], measurement_object_id=old["object_id"]))
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["error"]["code"], "CORRUPT_OBJECT")

    def test_rehashed_original_request_cannot_change_saved_point_identity(self):
        first = self.centred()
        old = self.ok("measure", object_id=first["object_id"], points=[[6, 5], [10, 7]])
        p = self.workspace / "requests" / (old["request_id"] + ".json")
        raw = p.read_bytes()
        journal = json.loads(raw)
        journal["parameters"]["points"] = [[6, 5], [11, 7]]
        journal["parameters_sha256"] = hashlib.sha256(engine.canonical(journal["parameters"])).hexdigest()
        p.write_bytes(engine.canonical(journal))
        bad = engine.execute(self.req("remeasure", object_id=first["object_id"], measurement_object_id=old["object_id"]))
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["error"]["code"], "CORRUPT_OBJECT")
        p.write_bytes(raw)
        once = self.ok("remeasure", object_id=first["object_id"], measurement_object_id=old["object_id"])
        twice = self.ok("remeasure", object_id=first["object_id"], measurement_object_id=once["object_id"])
        self.assertEqual(twice["points"], old["points"])


if __name__ == "__main__":
    unittest.main()
