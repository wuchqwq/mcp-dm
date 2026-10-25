"""Saved-file external workflow controls. All captures are explicitly mock."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import numpy as np

from bridge.dm_bridge import MockBackend
from crystallography.workflow import run, verify
from crystallography.geometry import NonIdentifiableGeometry


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="crystal-workflow-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.capture = self.root / "capture"
        MockBackend().capture2d(1000, [7, 9, 71, 73], str(self.capture))
        self.before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.capture.iterdir()}
        self.request = {"schema_version": 1, "coordinate_frame": "source_pixel_centers_xy",
                        "source": {"kind": "synthetic_diffraction", "capture_directory": "capture"},
                        "center": {"mode": "user_confirmed", "xy": [39., 41.]},
                        "spots": [{"id": "a", "xy": [49., 41.]}, {"id": "b", "xy": [39., 51.]},
                                  {"id": "c", "xy": [49., 51.]}],
                        "calibration": {"mode": "explicit", "scale_xy": [.5, -.5], "unit": "1/nm",
                                        "convention": "cycles_per_length", "basis": "known synthetic standard"},
                        "indexing": {"models": ["FCC", "BCC", "P"], "max_index": 2}}
        self.path = self.root / "request.json"

    def invoke(self, output="result"):
        self.path.write_text(json.dumps(self.request), encoding="utf-8")
        return run(self.path, self.root/output, "saved-before-submit")

    def test_end_to_end_joint_candidates_overlay_table_and_source_unchanged(self):
        summary = self.invoke()
        self.assertEqual(summary["state"], "COMPLETE")
        self.assertEqual(set(summary["compatible_models"]), {"FCC", "BCC", "P"})
        data = json.loads((self.root/"result/results.json").read_text())
        self.assertEqual(data["measurement"]["spots"][0]["source_xy"], [49., 41.])
        self.assertEqual(data["measurement"]["spots"][0]["xy"], [42., 32.])
        self.assertAlmostEqual(data["measurement"]["spots"][0]["d_nm"], .2)
        self.assertFalse(data["source"]["actual_dm"])
        self.assertFalse(data["chemical_phase_identified"])
        self.assertTrue((self.root/"result/positions.svg").read_text().startswith('<svg'))
        self.assertIn("source_x", (self.root/"result/measurements.csv").read_text())
        self.assertEqual(verify(self.root/"result")["state"], "VERIFIED")
        self.assertEqual(self.before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.capture.iterdir()})

    def test_request_id_required_and_existing_outputs_never_overwritten(self):
        self.invoke()
        original = (self.root/"result/results.json").read_bytes()
        for request_id in (None, "", "bad id"):
            with self.subTest(request_id=request_id), self.assertRaises(ValueError):
                run(self.path, self.root/"another", request_id)
        with self.assertRaises(ValueError):
            run(self.path, self.root/"result", "saved-before-submit")
        self.assertEqual(original, (self.root/"result/results.json").read_bytes())
        self.assertFalse((self.root/"another").exists())

    def test_relative_only_returns_no_absolute_d(self):
        self.request["calibration"] = dict(mode="relative", isotropic_pixel_geometry_confirmed=True)
        self.invoke()
        data = json.loads((self.root/"result/results.json").read_text())
        self.assertIsNone(data["measurement"]["spots"][0]["d_nm"])
        for model in data["indexing"]["model_results"]:
            self.assertTrue(all(c["lattice_parameter_nm"] is None for c in model["candidates"]))

    def test_unknown_geometry_no_indexing_and_bad_coordinates_refuse_before_files(self):
        for mutation in ("relative", "coordinate_frame", "outside", "duplicate"):
            with self.subTest(mutation=mutation):
                original = json.loads(json.dumps(self.request))
                if mutation == "relative":
                    self.request["calibration"] = dict(mode="relative", isotropic_pixel_geometry_confirmed=False)
                elif mutation == "outside":
                    self.request["spots"][0]["xy"] = [71., 11.]
                elif mutation == "duplicate":
                    self.request["spots"][1]["xy"] = self.request["spots"][0]["xy"]
                else:
                    self.request["coordinate_frame"] = "preview_png"
                with self.assertRaises(ValueError):
                    self.invoke()
                self.assertFalse((self.root/"result").exists())
                self.request = original

    def test_tampered_output_or_source_does_not_verify(self):
        self.invoke()
        path = self.root/"result/measurements.csv"
        original = path.read_bytes(); path.write_bytes(original+b"wrong")
        with self.assertRaises(ValueError):
            verify(self.root/"result")
        path.write_bytes(original)
        (self.capture/"input.npy").write_bytes(b"wrong")
        with self.assertRaises(ValueError):
            verify(self.root/"result")

    def test_rehashed_missing_input_inventory_does_not_verify(self):
        self.invoke()
        folder = self.root/"result"
        parameters = json.loads((folder/"parameters.json").read_bytes())
        parameters["input_files_sha256"] = {}
        changed = json.dumps(parameters).encode()
        (folder/"parameters.json").write_bytes(changed)
        manifest = json.loads((folder/"manifest.json").read_bytes())
        manifest["files_sha256"]["parameters.json"] = hashlib.sha256(changed).hexdigest()
        (folder/"manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ValueError):
            verify(folder)

    def test_cli_bad_input_exit_code_and_no_false_success(self):
        self.path.write_text(json.dumps(self.request), encoding="utf-8")
        result = subprocess.run([sys.executable, "-B", "-m", "crystallography", "run", "--request", str(self.path),
                                 "--output", str(self.root/"result"), "--request-id", "bad id"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(json.loads(result.stderr)["state"], "ERROR")
        self.assertFalse((self.root/"result").exists())

    def test_completion_marker_cannot_omit_outputs_or_change_result_identity(self):
        self.invoke()
        path = self.root/"result/manifest.json"
        original = path.read_bytes()
        for names in (["results.json"], list(json.loads(original)["files_sha256"])):
            manifest = json.loads(original)
            for name in names:
                manifest["files_sha256"].pop(name)
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                verify(self.root/"result")
        path.write_bytes(original)
        result_path = self.root/"result/results.json"
        result = json.loads(result_path.read_bytes()); result["request_id"] = "another-request"
        changed = json.dumps(result).encode()
        result_path.write_bytes(changed)
        manifest = json.loads(original)
        manifest["files_sha256"]["results.json"] = hashlib.sha256(changed).hexdigest()
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ValueError):
            verify(self.root/"result")

    def test_explicit_zero_frame_and_small_indexing_table(self):
        self.request["calibration"].update(zero_xy=[13., -7.], zero_frame="source_pixel_zero")
        self.request["spots"] = self.request["spots"][:2]
        summary = self.invoke()
        self.assertEqual(summary["state"], "NEEDS_REVIEW")
        result = json.loads((self.root/"result/results.json").read_bytes())
        self.assertEqual(result["measurement"]["spots"][0]["absolute_coordinate_xy"], [37.5, -27.5])
        self.assertEqual(result["measurement"]["spots"][0]["d_nm"], .2)
        self.assertEqual(verify(self.root/"result")["analysis_state"], "NEEDS_REVIEW")

    def test_collinear_three_and_eight_points_preserve_signed_calibrated_measurement_for_review(self):
        import math
        for offsets in ([2, 4, 6], [-8, -6, -4, -2, 2, 4, 6, 8]):
            with self.subTest(points=len(offsets)):
                self.request["spots"] = [{"id": "p"+str(i), "xy": [39+d, 41+d]} for i, d in enumerate(offsets)]
                self.request["indexing"]["models"] = ["FCC", "HCP"]
                output = "linear-"+str(len(offsets))
                summary = self.invoke(output)
                self.assertEqual(summary["state"], "NEEDS_REVIEW")
                self.assertEqual(summary["compatible_models"], [])
                folder = self.root/output
                data = json.loads((folder/"results.json").read_bytes())
                self.assertIn("noncollinear", data["review_reason"])
                self.assertIsNone(data["indexing"])
                self.assertEqual(data["measurement"]["calibration"]["scale_xy"], [.5, -.5])
                self.assertFalse(data["chemical_phase_identified"])
                self.assertEqual(len(data["measurement"]["spots"]), len(offsets))
                for spot, d in zip(data["measurement"]["spots"], offsets):
                    self.assertEqual(spot["source_xy"], [39+d, 41+d])
                    self.assertEqual(spot["g_xy_cycles_per_nm"], [.5*d, -.5*d])
                    self.assertAlmostEqual(spot["d_nm"], 1/math.hypot(.5*d, -.5*d))
                self.assertEqual(len((folder/"measurements.csv").read_text().splitlines()), len(offsets)+1)
                self.assertIn("<svg", (folder/"positions.svg").read_text())
                self.assertEqual(verify(folder)["analysis_state"], "NEEDS_REVIEW")
        self.assertEqual(self.before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.capture.iterdir()})

    def test_collinear_cli_returns_review_exit_two_and_verifiable_files(self):
        self.request["spots"] = [{"id": str(d), "xy": [39+d, 41+d]} for d in (2, 4, 6)]
        self.path.write_text(json.dumps(self.request), encoding="utf-8")
        output = self.root/"cli-linear"
        result = subprocess.run([sys.executable, "-B", "-m", "crystallography", "run", "--request", str(self.path),
                                 "--output", str(output), "--request-id", "saved-linear"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stdout)["state"], "NEEDS_REVIEW")
        self.assertEqual(result.stderr, "")
        self.assertEqual(verify(output)["analysis_state"], "NEEDS_REVIEW")

    def test_collinearity_does_not_hide_invalid_fields_identity_or_other_model_errors(self):
        original = json.loads(json.dumps(self.request))
        for field in ("max_index", "max_unmatched", "later_hcp", "nonfinite", "identity", "references", "duplicate"):
            with self.subTest(field=field):
                self.request = json.loads(json.dumps(original))
                self.request["spots"] = [{"id": str(d), "xy": [39+d, 41+d]} for d in (2, 4, 6)]
                if field == "max_index": self.request["indexing"]["max_index"] = 99
                elif field == "max_unmatched": self.request["indexing"]["max_unmatched"] = True
                elif field == "later_hcp": self.request["indexing"].update(models=["FCC", "HCP"], c_over_a=0)
                elif field == "nonfinite": self.request["spots"][0]["xy"][0] = float("nan")
                elif field == "identity": self.request["source"]["expected_capture_id"] = "foreign"
                elif field == "references": self.request["references"] = {"cif": "not-a-list"}
                else: self.request["spots"][1]["id"] = self.request["spots"][0]["id"]
                with self.assertRaises(ValueError) as failure:
                    self.invoke("invalid-"+field)
                self.assertNotIsInstance(failure.exception, NonIdentifiableGeometry)
                self.assertFalse((self.root/("invalid-"+field)).exists())

    def test_search_budget_failure_still_errors_without_outputs(self):
        with mock.patch("crystallography.indexing.MAX_SEARCH_SEEDS", 0):
            with self.assertRaisesRegex(ValueError, "search seed budget exceeded"):
                self.invoke("budget-error")
        self.assertFalse((self.root/"budget-error").exists())

    def test_direct_indexers_share_typed_collinearity_without_masking_invalid_options(self):
        from crystallography.indexing import index_cubic
        from crystallography.hexagonal import index_hcp
        vectors = [[1., 0.], [2., 0.], [-1., 0.]]
        for function in (index_cubic, index_hcp):
            with self.subTest(api=function.__name__):
                with self.assertRaises(NonIdentifiableGeometry) as cause:
                    function(vectors, calibrated=True)
                self.assertIsInstance(cause.exception, ValueError)
                for options in ({"max_index": 99}, {"max_unmatched": True}):
                    with self.assertRaises(ValueError) as error:
                        function(vectors, calibrated=True, **options)
                    self.assertNotIsInstance(error.exception, NonIdentifiableGeometry)

    def test_ambiguous_explicit_zero_and_excess_detection_budget_refused(self):
        self.request["calibration"]["zero_xy"] = [13., -7.]
        with self.assertRaises(ValueError):
            self.invoke()
        self.request["calibration"].pop("zero_xy")
        self.request["spots"] = "auto"
        self.request["detection"] = {"max_spots": 32}
        with self.assertRaises(ValueError):
            self.invoke()

    def test_auto_fcc_and_hcp_complete_without_point_or_centre_prompts(self):
        from examples.crystallography_demo import prepare
        for model in ("FCC", "HCP"):
            with self.subTest(model=model):
                folder = self.root/model
                request = prepare(folder, model)
                summary = run(request, folder/"result", "auto-"+model)
                self.assertEqual(summary["state"], "COMPLETE")
                self.assertIn(model, summary["compatible_models"])
                result = json.loads((folder/"result/results.json").read_bytes())
                truth = json.loads((folder/"answer-record.json").read_bytes())
                self.assertLess(np.linalg.norm(np.array(result["measurement"]["center_source_xy"])-truth["center_source_xy"]), .05)
                expected = 1/np.linalg.norm(truth["g_vectors_cycles_per_nm"], axis=1)
                for spot in result["measurement"]["spots"]:
                    self.assertLess(min(abs(spot["d_nm"] / d - 1) for d in expected), .01)
                    self.assertEqual(spot["uncertainty_status"], "UNKNOWN")
                if model == "FCC":
                    self.assertGreater(len(summary["compatible_models"]), 1)
                else:
                    candidate = result["reference_comparisons"][0]["comparison"]["model_results"][0]["candidates"][0]
                    self.assertAlmostEqual(candidate["lattice_parameter_a_nm"], truth["a_nm"])
                    self.assertAlmostEqual(candidate["c_over_a"], truth["c_over_a"])
                self.assertEqual(verify(folder/"result")["state"], "VERIFIED")

    def test_auto_no_evidence_is_review_not_success_or_phase(self):
        class FlatMock(MockBackend):
            def _mk(self, image_id, rect):
                record, array = super()._mk(image_id, rect)
                return record, np.ones(array.shape)
        new_capture = self.root/"flat-capture"
        FlatMock().capture2d(1000, [7, 9, 71, 73], str(new_capture))
        self.request["source"]["capture_directory"] = "flat-capture"
        self.request["center"] = {"mode": "auto"}
        self.request["spots"] = "auto"
        summary = self.invoke()
        self.assertEqual(summary["state"], "NEEDS_REVIEW")
        result = json.loads((self.root/"result/results.json").read_bytes())
        self.assertNotIn("measurement", result)
        self.assertFalse(result["chemical_phase_identified"])
        self.assertEqual(verify(self.root/"result")["analysis_state"], "NEEDS_REVIEW")


if __name__ == "__main__":
    unittest.main()
