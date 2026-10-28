"""Small numerical counterexamples for the bounded Agent-side recipe."""
import copy
import importlib.util
import math
from pathlib import Path
import tempfile
import unittest

HAS_TOOLS = all(importlib.util.find_spec(name) is not None for name in ("ase", "scipy", "diffsims", "tifffile"))
if HAS_TOOLS:
    import numpy as np
    from tools.hypothesis_explorer import (metrics, neighborhood_inside_cutoff, next_observation,
                                            propose_rotations, rank, run, save_json, validate_config)


@unittest.skipUnless(HAS_TOOLS, "Independent optional structure/image dependencies are required")
class HypothesisExplorerTests(unittest.TestCase):
    def config(self):
        return {"measurement_paths": [str(Path("unused-measurement.json").resolve())],
                "current_image_object_id": "a"*32, "experimental_kind": "other_diffraction",
                "screen_axes": {"flip_y": False, "basis": "independent detector convention"},
                "max_residual_inv_angstrom": .001, "rotation_range_deg": [-180, 180],
                "simulation": {"voltage_kv": 200, "reciprocal_radius_inv_angstrom": .9,
                               "max_excitation_error_inv_angstrom": .02, "size": 128,
                               "sigma_pixels": 1., "with_direct_beam": False},
                "candidates": [{"label": "A", "source_path": str(Path("candidate.cif").resolve()), "zone_axes": [[0, 0, 1]]}]}

    def hypothesis(self, label, points, angle=0., cutoff=1.25):
        theta = math.radians(angle)
        matrix = [[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]]
        return ({"label": label, "zone_axis_uvw": [0, 0, 1], "rotation_deg": angle},
                {"reflections": {"coordinates_inv_angstrom": [[*point, 0.] for point in points],
                                 "hkl": [[i+1, 0, 0] for i in range(len(points))]},
                 "parameters": {"voltage_kv": 200, "max_excitation_error_inv_angstrom": .02,
                                "reciprocal_radius_inv_angstrom": cutoff}},
                {"registration": {"matrix_xy": matrix}})

    def test_angle_sign_range_and_fixed_radius_do_not_fit_scale(self):
        # A +30 degree measured vector needs -30 degrees into the lab model.
        q = [[math.sqrt(3)/2, .5]]
        angles = propose_rotations(q, [[1., 0.]], 1e-6, [-90, 0])
        self.assertTrue(any(abs(a+30) < 1e-12 for a in angles))
        self.assertTrue(all(-90 <= a < 0 for a in angles))
        self.assertEqual(propose_rotations(q, [[2., 0.]], .001, [-90, 0]), [-90.])

    def test_proposal_overflow_refuses_instead_of_dropping_angles(self):
        vectors = [[math.cos(a), math.sin(a)] for a in np.linspace(-3, 3, 300)]
        with self.assertRaisesRegex(ValueError, "nothing truncated"):
            propose_rotations([[1., 0.]], vectors, .001, [-180, 180])

    def test_missing_parity_or_confirmation_injection_is_not_accepted(self):
        for mutate in (lambda c: c["screen_axes"].pop("basis"),
                       lambda c: c.update(confirmation={"source": "user_confirmed"}),
                       lambda c: c["candidates"][0].update(zone_axes=[[0, 0, 2]])):
            config = self.config()
            mutate(config)
            with self.assertRaises(ValueError):
                validate_config(config)

    def test_no_matches_have_null_rms_and_cardinality_wins(self):
        comparison = {"matched": [], "unmatched_experimental": [{}], "unmatched_simulated": [],
                      "all_experimental_reflections_matched_within_tolerance": False}
        self.assertIsNone(metrics(comparison)["rms_residual_inv_angstrom"])
        self.assertLess(rank({"matched_count": 2, "total_residual_inv_angstrom": .1}),
                        rank({"matched_count": 1, "total_residual_inv_angstrom": 0.}))

    def test_followup_uses_all_competing_rolls_and_skips_searched_points(self):
        a = self.hypothesis("A", [[1., 0.]])
        b_far = self.hypothesis("B", [[0., 1.]])
        b_near = self.hypothesis("B", [[0., 1.001]], angle=90.)
        original = copy.deepcopy([a, b_far, b_near])
        result = next_observation([a, b_far, b_near], np.array([[.2, 0.]]), .01, .9)
        # A cannot pretend B's unfavorable roll is its only explanation.
        if result["target_label"] == "A":
            self.assertLess(result["model_separation_inv_angstrom"], .002)
        # Independently check the chosen target against ALL other-label points.
        point = np.asarray(result["target_q_xy_inv_angstrom"])
        competitors = []
        for row, sim, comparison in (a, b_far, b_near):
            if row["label"] != result["target_label"]:
                competitors.extend(np.asarray(sim["reflections"]["coordinates_inv_angstrom"])[:, :2] @
                                   np.asarray(comparison["registration"]["matrix_xy"]))
        self.assertAlmostEqual(result["model_separation_inv_angstrom"],
                               min(np.linalg.norm(point-p) for p in competitors))
        self.assertGreater(np.linalg.norm(point), .9)
        self.assertEqual([a, b_far, b_near], original)

    def test_followup_boundary_is_certified_in_3d_not_only_projected_radius(self):
        sim = self.hypothesis("A", [[1., 0.]])[1]
        self.assertTrue(neighborhood_inside_cutoff(1.1, .002, sim))
        self.assertFalse(neighborhood_inside_cutoff(1.2499, .0002, sim))
        # Even an XY neighborhood just inside the cutoff may have admitted g_z
        # that moves it outside the full-3D enumerated sphere.
        self.assertFalse(neighborhood_inside_cutoff(1.2498, .0001, sim))

    def test_existing_results_are_never_overwritten_or_replayed(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            saved = output / "record.json"
            save_json(saved, {"keep": True})
            before = saved.read_bytes()
            with self.assertRaises(FileExistsError):
                save_json(saved, {"keep": False})
            with self.assertRaisesRegex(ValueError, "already exists"):
                run(self.config(), output)
            self.assertEqual(saved.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
