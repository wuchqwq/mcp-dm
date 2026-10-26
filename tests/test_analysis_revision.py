"""Real saved image/structure objects, with independent reciprocal references."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

READY = all(importlib.util.find_spec(name) is not None for name in ("ase", "diffsims", "tifffile"))
if READY:
    import numpy as np
    import tifffile
    from ase.build import bulk
    from ase.io import write
    from tools.image_workspace import execute as image_execute
    from crystallography.structure_tools import execute as structure_execute
    from crystallography.reflection_compare import load_measurement


@unittest.skipUnless(READY, "Independent image/ASE/diffsims environment required")
class AnalysisRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.images, self.structures = self.root / "images", self.root / "structures"
        y, x = np.indices((32, 32))
        values = np.rint(1000 + 100*np.cos(2*np.pi*x/4) + 80*np.cos(2*np.pi*y/4) +
                         70*np.cos(2*np.pi*(x+y)/4) + 50*np.cos(2*np.pi*(x-y)/4)).astype(np.uint16)
        source = self.root / "synthetic.tiff"
        tifffile.imwrite(source, values, photometric="minisblack")
        cif = self.root / "copper.cif"
        write(cif, bulk("Cu", "fcc", a=3.6, cubic=True), format="cif")
        opened = self.image("open", "open", source_path=str(source))
        frame = self.image("frame", "frame", object_id=opened["object_id"], frame_index=0)
        self.cal = self.image("calibrate", "scale", object_id=frame["object_id"], scope="image",
                              xy_scale={"x": .045, "y": .045, "unit": "nm"}, source_text="Independent synthetic four-pixel period =1.8 Angstrom")
        self.fft = self.image("fft", "fft", object_id=self.cal["object_id"], window="none", subtract_mean=True)
        self.fft_hash = self.sha(Path(self.fft["array_path"]))
        structure = self.structure("open", "structure", source_path=str(cif))
        orientation = self.structure("orient", "orientation", object_id=structure["object_id"], zone_axis_uvw=[0, 0, 1], in_plane_direction_uvw=[1, 0, 0])
        self.sim = self.structure("simulate", "simulation", object_id=structure["object_id"], orientation_id=orientation["object_id"], voltage_kv=200,
                                  reciprocal_radius_inv_angstrom=1.3, max_excitation_error_inv_angstrom=.02, size=64)
        self.measures = [self.image("measure", "peak-"+str(i), object_id=self.fft["object_id"], coordinate_space="frequency_cycles_per_pixel",
                                    points=[[0, 0], p]) for i, p in enumerate(([.25, 0], [0, .25], [.25, .25], [.25, -.25]))]

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def image(self, action, request, **args):
        value = image_execute({"workspace": str(self.images), "action": action, "request_id": request, **args})
        self.assertTrue(value.get("ok"), value)
        return value["result"]

    def structure(self, action, request, **args):
        value = structure_execute({"workspace": str(self.structures), "action": action, "request_id": request, **args})
        self.assertTrue(value.get("ok"), value)
        return value["result"]

    def register(self, request, measures=None, current=None):
        return self.structure("register", request, object_id=self.sim["object_id"], measurement_paths=[m["manifest_path"] for m in measures or self.measures],
                              current_image_object_id=(current or self.fft)["object_id"],
                              fit_correspondences=[{"measurement_index": 0, "hkl": [2, 0, 0]}, {"measurement_index": 1, "hkl": [0, 2, 0]}],
                              validation_correspondences=[{"measurement_index": 2, "hkl": [2, 2, 0]}, {"measurement_index": 3, "hkl": [2, -2, 0]}],
                              screen_axes={"flip_y": False, "basis": "Explicit common synthetic XY coordinates"},
                              confirmation={"source": "synthetic_fixture", "source_text": "Independent literal sinusoidal fixture, not experimental confirmation"},
                              experimental_kind="real_space_fft", max_residual_inv_angstrom=1e-12)

    def compare(self, request, registration, measures=None, current=None, **kwargs):
        return self.structure("compare", request, object_id=self.sim["object_id"], measurement_paths=[m["manifest_path"] for m in measures or self.measures],
                              current_image_object_id=(current or self.fft)["object_id"], registration_object_id=registration["object_id"],
                              experimental_kind="real_space_fft", max_residual_inv_angstrom=1e-12, **kwargs)

    def test_current_scale_revision_reuses_points_and_fft_but_not_old_physical_results(self):
        registration = self.register("fit-original")
        comparison = self.compare("compare-original", registration)
        self.assertTrue(comparison["all_experimental_reflections_matched_within_tolerance"])
        self.assertAlmostEqual(registration["registration"]["rotation_deg"], 0., places=11)
        self.assertEqual(registration["registration"]["scale"], 1)
        self.assertEqual(registration["registration"]["translation_inv_angstrom"], [0, 0])
        revised = self.image("calibrate", "revised-scale", object_id=self.fft["object_id"], scope="image",
                             xy_scale={"x": .05, "y": .05, "unit": "nm"}, source_text="Synthetic sensitivity correction; independent period no longer1.8A")
        stale = structure_execute({"workspace": str(self.structures), "action": "compare", "request_id": "stale-old-results",
                                   "object_id": self.sim["object_id"], "measurement_paths": [m["manifest_path"] for m in self.measures],
                                   "current_image_object_id": revised["object_id"], "registration_object_id": registration["object_id"],
                                   "experimental_kind": "real_space_fft", "max_residual_inv_angstrom": 1e-12})
        self.assertFalse(stale["ok"])
        self.assertIn("remeasure", stale["error"]["message"])
        updated = [self.image("remeasure", "update-"+str(i), object_id=revised["object_id"], measurement_object_id=m["object_id"])
                   for i, m in enumerate(self.measures)]
        for before, after in zip(self.measures, updated):
            self.assertEqual(before["points"], after["points"])
            self.assertEqual(load_measurement(after["manifest_path"])[0]["object_id"], after["object_id"])
        self.assertAlmostEqual(updated[0]["physical_frequency_magnitude"] / 10, .5)
        refit = self.register("refit-revised", updated, revised)
        changed = self.compare("compare-revised", refit, updated, revised, previous_comparison_id=comparison["object_id"])
        self.assertFalse(changed["all_experimental_reflections_matched_within_tolerance"])
        self.assertEqual(changed["analysis_root_id"], comparison["object_id"])
        self.assertEqual(changed["analysis_revision"], 2)
        self.assertTrue(changed["revision_changes"]["calibration_or_centre_changed"])
        self.assertTrue(changed["unchanged_scientific_array_reused"])
        self.assertFalse(changed["new_fft_computed_by_comparison"])
        self.assertEqual(self.sha(Path(self.fft["array_path"])), self.fft_hash)
        old = self.structure("result", "unused", query_request_id="compare-original")
        self.assertTrue(old["all_experimental_reflections_matched_within_tolerance"])
        self.assertEqual(old["object_id"], comparison["object_id"])

    def test_point_correction_changes_heldout_not_fit_and_keeps_history(self):
        registration = self.register("fit-before-point-edit")
        original = self.compare("comparison-before-point-edit", registration)
        edited = self.image("remeasure", "move-heldout-point", object_id=self.fft["object_id"], measurement_object_id=self.measures[2]["object_id"],
                            points=[[0, 0], [.24, .25]], source_text="Explicit synthetic held-out point correction")
        measures = [*self.measures[:2], edited, self.measures[3]]
        registration2 = self.register("fit-after-point-edit", measures)
        self.assertEqual(registration2["fit_status"], "within_declared_tolerance")
        self.assertTrue(all(row["position_residual_inv_angstrom"] < 1e-14 for row in registration2["fit_evidence"]))
        self.assertFalse(registration2["held_out_validation_passed"])
        second = self.compare("comparison-after-point-edit", registration2, measures, previous_comparison_id=original["object_id"])
        self.assertTrue(second["revision_changes"]["measurement_points_changed"])
        self.assertFalse(second["phase_identified"])
        self.assertEqual(self.measures[2]["points"], [[0, 0], [.25, .25]])

    def test_explicit_historical_review_does_not_claim_current_geometry(self):
        transform = {"rotation_deg": 0., "scale": 1., "translation_inv_angstrom": [0., 0.], "flip_y": False, "basis": "Literal synthetic common coordinates"}
        historical = self.structure("compare", "historical", object_id=self.sim["object_id"], measurement_paths=[m["manifest_path"] for m in self.measures],
                                    registration=transform, analysis_mode="historical_review", experimental_kind="real_space_fft", max_residual_inv_angstrom=1e-12)
        self.assertEqual(historical["analysis_binding"]["analysis_mode"], "historical_review")
        self.assertFalse(historical["analysis_binding"]["current_geometry_checked"])
        self.assertTrue(historical["all_experimental_reflections_matched_within_tolerance"])

    def test_centre_remeasurement_loader_updates_only_bound_dc_endpoint(self):
        # A reciprocal scalar declares its semantics explicitly; no FFT DC is moved.
        sequence = self.image("open", "reciprocal-open", source_path=str(self.root / "synthetic.tiff"))
        frame = self.image("frame", "reciprocal-frame", object_id=sequence["object_id"], frame_index=0)
        calibrated = self.image("calibrate", "reciprocal-scale", object_id=frame["object_id"], scope="image", coordinate_domain="reciprocal_space",
                                declare_reciprocal=True, xy_scale={"x": 1.25, "y": -2.5, "unit": "1/nm"}, source_text="Synthetic diffraction scalar; not the real-space TIFF interpretation")
        centred = self.image("centre", "centre-one", object_id=calibrated["object_id"], center_xy=[16., 16.], coordinate_space="source_array_indices", source_text="Synthetic literal centre")
        old = self.image("measure", "centre-peak", object_id=centred["object_id"], points=[[16., 16.], [20., 16.]], coordinate_space="source_array_indices")
        new_centre = self.image("centre", "centre-two", object_id=centred["object_id"], center_xy=[16.5, 15.5], coordinate_space="source_array_indices", source_text="Synthetic half-pixel centre correction")
        changed = self.image("remeasure", "centre-remeasure", object_id=new_centre["object_id"], measurement_object_id=old["object_id"])
        loaded = load_measurement(changed["manifest_path"])[0]
        self.assertEqual(loaded["points"], [[16.5, 15.5], [20., 16.]])
        self.assertEqual(loaded["physical_vector_xy"], [4.375, -1.25])
        self.assertEqual(old["physical_vector_xy"], [5., 0.])
        self.assertEqual(old["points"], [[16., 16.], [20., 16.]])


if __name__ == "__main__":
    unittest.main()
