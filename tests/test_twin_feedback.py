"""Small counterexamples for scoped feedback and domain-qualified assignment.

Hand-built candidate graphs below are independent unit fixtures only. They are
not experimental records or evidence for the executed synthetic twin demo.
"""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HAS_TOOLS = all(importlib.util.find_spec(name) is not None for name in ("numpy", "scipy", "ase", "tifffile"))
if HAS_TOOLS:
    import numpy as np
    import tifffile
    from tools.image_workspace import Workspace, execute as image_execute
    from tools.hypothesis_explorer import save_json
    from tools.twin_feedback import (classify_joint, digest, measurements, primitive,
                                     require_conventional_fcc, revise, annotate, RecipeCalls)


@unittest.skipUnless(HAS_TOOLS, "Optional independent image/structure environment is required")
class TwinGeometryTests(unittest.TestCase):
    def compare_fixtures(self, points_a, points_b, observed, tolerance):
        """Build explicit Euclidean edges without using the production matcher."""
        observations = [{"measurement_object_id": str(i), "q_xy_inv_angstrom": point} for i, point in enumerate(observed)]
        simulations, comparisons = [], []
        for domain, points in zip(("a", "b"), (points_a, points_b)):
            simulations.append({"object_id": domain*32,
                                "reflections": {"coordinates_inv_angstrom": [[*p, 0.] for p in points],
                                                "hkl": [[i+1, 0, 0] for i in range(len(points))]}})
            edges = []
            for i, observed_point in enumerate(observed):
                candidates = []
                for j, point in enumerate(points):
                    residual = float(np.linalg.norm(np.asarray(observed_point)-point))
                    if residual <= tolerance:
                        candidates.append({"simulation_reflection_index": j, "residual_inv_angstrom": residual})
                edges.append({"measurement_index": i, "candidates": candidates})
            comparisons.append({"observations": copy.deepcopy(observations), "registration": {"matrix_xy": [[1., 0.], [0., 1.]]},
                                "ambiguity": edges})
        return simulations, comparisons

    def test_known_sigma3_matrix_maps_common_110_beam_to_011_and_keeps_primitive_sign(self):
        # Right-handed +60 degrees around [111], independently written exactly.
        twin = np.array([[2., -1., 2.], [2., 2., -1.], [-1., 2., 2.]])/3.
        np.testing.assert_allclose(twin.T @ twin, np.eye(3), atol=2e-16)
        self.assertAlmostEqual(float(np.linalg.det(twin)), 1.)
        self.assertEqual(primitive(twin.T @ [1., -1., 0.]), [0, -1, 1])
        self.assertEqual(primitive([-2/3, 4/3, -2/3]), [-1, 2, -1])
        with self.assertRaisesRegex(ValueError, "rational"):
            primitive([np.sqrt(2), 0., 1.])

    def test_only_the_supported_conventional_fcc_motif_is_admitted(self):
        fcc = {"cell_angstrom": np.eye(3).tolist(), "positions_angstrom": [[0, 0, 0], [0, .5, .5], [.5, 0, .5], [.5, .5, 0]],
               "symbols": ["Cu"]*4, "pbc": [True]*3}
        require_conventional_fcc(fcc)
        bcc = {**fcc, "positions_angstrom": [[0, 0, 0], [.5, .5, .5]], "symbols": ["Fe"]*2}
        with self.assertRaisesRegex(ValueError, "four-atom FCC"):
            require_conventional_fcc(bcc)
        duplicate = copy.deepcopy(fcc)
        duplicate["positions_angstrom"][-1] = duplicate["positions_angstrom"][0]
        with self.assertRaisesRegex(ValueError, "FCC basis"):
            require_conventional_fcc(duplicate)

    def test_domain_shared_and_unexplained_peaks_are_retained_without_counting_a_shared_spot_twice(self):
        simulations, comparisons = self.compare_fixtures([[1., 0.], [0., 1.]], [[1., 0.], [-1., 0.]],
                                                         [[1., 0.], [0., 1.], [-1., 0.], [.4, .4]], .001)
        before = copy.deepcopy((simulations, comparisons))
        result = classify_joint(simulations, comparisons, .001)
        self.assertEqual(result["counts"], {"A": 1, "B": 1, "shared": 1, "unexplained": 1})
        self.assertEqual(result["matched_count"], 3)
        self.assertEqual([r["classification"] for r in result["rows"]], ["shared", "A", "B", "unexplained"])
        self.assertEqual({m["domain"] for m in result["rows"][0]["members"]}, {"A", "B"})
        self.assertIsNone(result["rows"][3]["residual_inv_angstrom"])
        self.assertTrue(all(r["status"] == "hypothesized" for r in result["rows"]))
        self.assertEqual((simulations, comparisons), before)

    def test_nearby_projections_inside_experimental_tolerance_do_not_become_shared(self):
        simulations, comparisons = self.compare_fixtures([[1., 0.]], [[1.0005, 0.]], [[1., 0.]], .001)
        result = classify_joint(simulations, comparisons, .001)
        self.assertEqual(result["rows"][0]["classification"], "A")
        self.assertEqual(result["counts"]["shared"], 0)
        self.assertEqual(len(result["rows"][0]["feasible_projection_groups"]), 2)
        self.assertEqual(result["unassigned_simulated_groups"][0][0]["domain"], "B")

    def test_two_observations_cannot_claim_the_same_coincident_prediction(self):
        simulations, comparisons = self.compare_fixtures([[1., 0.]], [[1., 0.]], [[1., 0.], [1., 0.]], .001)
        result = classify_joint(simulations, comparisons, .001)
        self.assertEqual(result["matched_count"], 1)
        self.assertEqual(result["counts"]["shared"], 1)
        self.assertEqual(result["unexplained_count"], 1)

    def test_numerical_coincidence_never_widens_a_domain_edge_tolerance(self):
        simulations, comparisons = self.compare_fixtures([[1., 0.]], [[1.+1e-12, 0.]], [[.875, 0.]], .125)
        result = classify_joint(simulations, comparisons, .125)
        self.assertEqual(result["rows"][0]["classification"], "A")
        self.assertEqual([m["domain"] for m in result["rows"][0]["members"]], ["A"])
        self.assertEqual(result["unassigned_simulated_groups"][0][0]["domain"], "B")

    def test_joint_assignment_maximizes_cardinality_before_a_smaller_partial_residual(self):
        simulations, comparisons = self.compare_fixtures([[1., 0.], [1.5, 0.]], [[5., 5.]], [[1.5, 0.], [2., 0.]], .5)
        result = classify_joint(simulations, comparisons, .5)
        self.assertEqual(result["matched_count"], 2)
        self.assertEqual([r["residual_inv_angstrom"] for r in result["rows"]], [.5, .5])
        changed = copy.deepcopy(comparisons)
        changed[1]["registration"]["matrix_xy"] = [[0., -1.], [1., 0.]]
        with self.assertRaisesRegex(ValueError, "fixed registration"):
            classify_joint(simulations, changed, .5)


@unittest.skipUnless(HAS_TOOLS, "Optional independent image/structure environment is required")
class ScopedObservationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "images"
        self.counter = 0
        self.current = self.new_reciprocal("first")
        self.measure = self.image("measure", object_id=self.current["object_id"], coordinate_space="source_array_indices", points=[[8, 8], [12, 8]])
        self.config = {"measurement_paths": [self.measure["manifest_path"]]}
        _, self.binding, _ = measurements(self.config, self.current["object_id"])

    def tearDown(self):
        self.temporary.cleanup()

    def request(self, action, **args):
        self.counter += 1
        return {"workspace": str(self.workspace), "action": action, "request_id": "scope-test-"+str(self.counter), **args}

    def image(self, action, **args):
        result = image_execute(self.request(action, **args))
        self.assertTrue(result.get("ok"), result)
        return result["result"]

    def new_reciprocal(self, name):
        source = self.root / (name+".tiff")
        tifffile.imwrite(source, np.arange(256, dtype=np.uint16).reshape(16, 16), photometric="minisblack")
        opened = self.image("open", source_path=str(source))
        frame = self.image("frame", object_id=opened["object_id"], frame_index=0)
        calibrated = self.image("calibrate", object_id=frame["object_id"], scope="image", declare_reciprocal=True,
                                coordinate_domain="reciprocal_space", xy_scale={"x": .01, "y": .01, "unit": "1/angstrom"},
                                source_text="Unit-fixture reciprocal grid, .01 cycles/angstrom/pixel")
        return self.image("centre", object_id=calibrated["object_id"], center_xy=[8, 8], coordinate_space="source_array_indices",
                          source_text="Unit-fixture known synthetic DC at [8,8]")

    def observation(self, object_id, authority="synthetic_fixture"):
        return self.image("context", object_id=object_id,
                          metadata={"research_observation": {"kind": "twinning_present", "source_text": "此单元测试声明存在孪晶。", "authority": authority}})

    def write_initial(self):
        search = self.root / "search"
        search.mkdir()
        save_json(search / "input.json", self.config)
        report = search / "report.json"
        save_json(report, {"input_sha256": digest(search / "input.json")})
        initial = self.root / "initial.json"
        save_json(initial, {"initial_report_path": str(report), "initial_report_sha256": digest(report),
                            "source_measurement_hashes": {self.measure["manifest_path"]: digest(self.measure["manifest_path"])},
                            "image_workspace": str(self.workspace), "analysis_binding": self.binding})
        return initial

    def test_observation_confirms_presence_only_and_provider_binds_exact_scientific_grid(self):
        before = Path(self.measure["manifest_path"]).read_bytes()
        for authority in ("synthetic_fixture", "user_confirmed"):
            observation = self.observation(self.current["object_id"], authority)
            scope = observation["research_observation_scope"]
            self.assertEqual(scope["confirmation_scope"], "twinning_present_only")
            self.assertEqual(scope["source_object_id"], self.current["object_id"])
            self.assertEqual(scope["scientific_grid_identity"], self.binding["scientific_grid_identity"])
            self.assertEqual(observation["user_context"]["research_observation"]["authority"], authority)
            self.assertNotIn("hkl", observation["user_context"]["research_observation"])
        self.assertEqual(Path(self.measure["manifest_path"]).read_bytes(), before)

    def test_confirmed_peak_location_is_retained_separately_from_new_agent_domain_label(self):
        view = self.image("view", object_id=self.current["object_id"])
        stable = "hyp-" + self.measure["object_id"][:20]
        marked = self.image("annotate", object_id=view["object_id"], annotations=[
            {"kind": "point", "coordinates": [12, 8], "coordinate_space": "source_array_indices",
             "source_object_id": view["panels"][0]["source_object_id"], "annotation_id": stable,
             "status": "user_confirmed", "text": "Only peak location confirmed", "color": "white"}])
        before = Path(marked["manifest_path"]).read_bytes()
        calls = RecipeCalls(self.root / "new-label", self.workspace)
        revised = annotate(calls, marked["object_id"], [self.measure], ["B"])
        marks = {m["annotation_id"]: m for m in revised["annotations"]}
        self.assertEqual(marks[stable]["status"], "user_confirmed")
        self.assertEqual(marks[stable]["text"], "Only peak location confirmed")
        self.assertEqual(marks[stable+"-agent"]["status"], "hypothesized")
        self.assertIn("B", marks[stable+"-agent"]["text"])
        self.assertEqual(Path(marked["manifest_path"]).read_bytes(), before)

    def test_forged_hkl_or_unsupported_authority_cannot_expand_confirmation_scope(self):
        valid = {"kind": "twinning_present", "source_text": "Synthetic unit statement", "authority": "synthetic_fixture"}
        for value in ({**valid, "hkl": [1, 1, 1]}, {**valid, "authority": "agent_hypothesis"},
                      {**valid, "kind": "twin_law_confirmed"}, {**valid, "source_text": "   "}):
            result = image_execute(self.request("context", object_id=self.current["object_id"], metadata={"research_observation": value}))
            self.assertFalse(result.get("ok"), result)

    def test_different_grid_observation_is_rejected_before_any_revision_output(self):
        initial = self.write_initial()
        other = self.new_reciprocal("other")
        observation = self.observation(other["object_id"])
        output = self.root / "must-not-be-created"
        with self.assertRaisesRegex(ValueError, "another scientific image/grid"):
            revise(initial, observation["object_id"], output)
        self.assertFalse(output.exists())

    def test_changed_calibration_requires_remeasurement_before_revision_writes(self):
        initial = self.write_initial()
        changed = self.image("calibrate", object_id=self.current["object_id"], scope="image", coordinate_domain="reciprocal_space",
                             xy_scale={"x": .02, "y": .02, "unit": "1/angstrom"}, source_text="Unit-fixture corrected detector scale")
        observation = self.observation(changed["object_id"])
        output = self.root / "must-not-be-created"
        with self.assertRaisesRegex(ValueError, "different centre/scale revision"):
            revise(initial, observation["object_id"], output)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
