"""Independent small cubic geometries for the optional external companion."""

import math
import unittest
from unittest import mock

import numpy as np

from crystallography import indexing


def project(hkl, a, first, second, rotation=0., mirror=False):
    """Analytical orthonormal viewing plane, independent of candidate search."""
    first = np.array(first, dtype=float)
    first /= np.linalg.norm(first)
    second = np.array(second, dtype=float)
    second /= np.linalg.norm(second)
    values = np.array(hkl) @ np.array([first, second]).T / a
    angle = math.radians(rotation)
    rotate = np.array([[math.cos(angle), -math.sin(angle)],
                       [math.sin(angle), math.cos(angle)]])
    values = values @ rotate.T
    if mirror:
        values[:, 0] *= -1
    return values


class CubicIndexingTests(unittest.TestCase):
    def assert_common_model(self, candidate, observed, expected_a=None):
        orientation = np.array(candidate["crystal_to_image_orientation"])
        np.testing.assert_allclose(orientation @ orientation.T, np.eye(3), atol=1e-12)
        self.assertAlmostEqual(np.linalg.det(orientation), 1., places=12)
        scale = candidate["reciprocal_scale_per_hkl"]
        if expected_a is not None:
            self.assertAlmostEqual(candidate["lattice_parameter_nm"], expected_a, places=11)
        for item in candidate["observations"]:
            if not item["matched"]:
                continue
            predicted_3d = orientation @ np.array(item["hkl"]) * scale
            self.assertAlmostEqual(predicted_3d[2], 0., places=10)
            np.testing.assert_allclose(predicted_3d[:2], item["predicted_vector"], atol=1e-12)
            np.testing.assert_allclose(item["predicted_vector"],
                                       observed[item["observation_index"]], atol=1e-10)
            self.assertEqual(np.dot(item["hkl"], candidate["zone_axis_uvw"]), 0)
        self.assertFalse(candidate["chemical_phase_identified"])

    def test_fcc_111_zone_fixed_a_joint_model(self):
        observed = project([[2, -2, 0], [0, 2, -2], [2, 0, -2]], .4,
                           [1, -1, 0], [1, 1, -2], 23)
        result = indexing.index_cubic(observed, calibrated=True, centerings=["F"],
                                      max_index=2, candidate_lattice_nm={"F": .4},
                                      relative_tolerance=.0001, angle_tolerance_deg=.01)
        self.assertTrue(result["candidates"])
        candidate = result["candidates"][0]
        self.assertEqual(sorted(abs(v) for v in candidate["zone_axis_uvw"]), [1, 1, 1])
        self.assertEqual(candidate["lattice_parameter_source"], "fixed_reference")
        self.assert_common_model(candidate, observed, .4)
        for item in candidate["observations"]:
            parity = np.array(item["hkl"]) % 2
            self.assertTrue(np.all(parity == parity[0]))

    def test_bcc_110_zone_and_mirrored_pattern_have_proper_orientation(self):
        for mirror in (False, True):
            with self.subTest(mirror=mirror):
                observed = project([[1, -1, 0], [0, 0, 2], [1, -1, 2]], .3,
                                   [1, -1, 0], [0, 0, 1], -37, mirror)
                result = indexing.index_cubic(observed, calibrated=True, centerings=["I"],
                                              candidate_lattice_nm={"I": .3}, max_index=2,
                                              relative_tolerance=.0001, angle_tolerance_deg=.01)
                self.assertTrue(result["candidates"])
                candidate = result["candidates"][0]
                self.assertEqual(sorted(abs(v) for v in candidate["zone_axis_uvw"]), [0, 1, 1])
                self.assert_common_model(candidate, observed, .3)
                self.assertTrue(all(sum(o["hkl"]) % 2 == 0 for o in candidate["observations"]))

    def test_homothetic_f_i_p_ambiguity_survives_display_limit(self):
        result = indexing.index_cubic([[5, 0], [0, 5], [5, 5]], calibrated=True,
                                      max_index=4, max_candidates=1,
                                      relative_tolerance=.0001, angle_tolerance_deg=.01)
        self.assertEqual(result["ambiguity"]["compatible_centerings"], ["F", "I", "P"])
        self.assertEqual(set(c["centering"] for c in result["candidates"]), {"F", "I", "P"})
        self.assertTrue(result["search"]["output_truncated"])
        self.assertFalse(result["ambiguity"]["unique_chemical_phase_claim"])
        self.assertFalse(result["search"]["global_noisy_solution_completeness_proven"])
        self.assertGreater(result["search"]["candidate_counts_by_centering"]["P"], 1)
        self.assertTrue(result["search"]["anchor_enumeration_exhausted"])

    def test_uncalibrated_scale_never_claims_absolute_a(self):
        result = indexing.index_cubic([[1, 0], [0, 1], [1, 1]], calibrated=False)
        self.assertTrue(result["candidates"])
        for candidate in result["candidates"]:
            self.assertIsNone(candidate["lattice_parameter_nm"])
            self.assertEqual(candidate["reciprocal_scale_unit"], "relative")
            self.assertTrue(all(o.get("individual_lattice_estimate_nm") is None
                                for o in candidate["observations"]))
        with self.assertRaisesRegex(ValueError, "absolute"):
            indexing.index_cubic([[1, 0], [0, 1], [1, 1]], calibrated=False,
                                 candidate_lattice_nm={"F": .4})

    def test_joint_noisy_fit_and_fixed_reference_never_recalibrates(self):
        observed = np.array([[5., 0.], [0., 5.], [5., 5.], [-5., 5.]])
        observed += np.array([[.006, -.004], [-.002, .004], [.003, .001], [.002, -.003]])
        result = indexing.index_cubic(observed, calibrated=True, centerings=["F"],
                                      candidate_lattice_nm={"F": .4}, max_index=2,
                                      relative_tolerance=.003, angle_tolerance_deg=.2)
        self.assertTrue(result["candidates"])
        for candidate in result["candidates"]:
            self.assertEqual(candidate["lattice_parameter_nm"], .4)
            self.assertEqual(candidate["matched_count"], 4)
            self.assertLess(candidate["rms_relative_vector_residual"], .003)
            self.assertLess(candidate["max_pair_angle_residual_deg"], .2)
        wrong = indexing.index_cubic(observed, calibrated=True, centerings=["F"],
                                     candidate_lattice_nm={"F": .42}, max_index=2,
                                     relative_tolerance=.003, angle_tolerance_deg=.2)
        self.assertEqual(wrong["candidates"], [])

    def test_outlier_is_explicit_and_residual_denominator_is_matched_count(self):
        observed = [[5, 0], [0, 5], [5, 5], [3.141, 8.765]]
        strict = indexing.index_cubic(observed, calibrated=True, centerings=["F"],
                                      max_index=2, candidate_lattice_nm={"F": .4},
                                      relative_tolerance=.0001, angle_tolerance_deg=.01)
        self.assertEqual(strict["candidates"], [])
        result = indexing.index_cubic(observed, calibrated=True, centerings=["F"],
                                      max_index=2, candidate_lattice_nm={"F": .4}, max_unmatched=1,
                                      relative_tolerance=.0001, angle_tolerance_deg=.01)
        self.assertTrue(result["candidates"])
        for candidate in result["candidates"]:
            self.assertEqual(candidate["matched_count"], 3)
            self.assertEqual(candidate["unmatched_observation_indices"], [3])
            residuals = [o["relative_vector_residual"] for o in candidate["observations"] if o["matched"]]
            self.assertAlmostEqual(candidate["rms_relative_vector_residual"],
                                   math.sqrt(sum(v * v for v in residuals) / 3), places=14)

    def test_individually_near_radii_do_not_replace_shared_geometry(self):
        # All three magnitudes match F 200/020/220; the third angle does not.
        third = math.sqrt(50) * np.array([math.cos(.55), math.sin(.55)])
        result = indexing.index_cubic([[5, 0], [0, 5], third], calibrated=True,
                                      centerings=["F"], max_index=2,
                                      candidate_lattice_nm={"F": .4},
                                      relative_tolerance=.001, angle_tolerance_deg=.1)
        self.assertEqual(result["candidates"], [])

    def test_anisotropic_pixel_mapping_must_be_resolved_before_indexing(self):
        # Pixel delta [10,0],[0,20],[10,20] with signed physical scales -.5,.25.
        physical = np.array([[10, 0], [0, 20], [10, 20]]) * np.array([-.5, .25])
        result = indexing.index_cubic(physical, calibrated=True, centerings=["F"],
                                      max_index=2, candidate_lattice_nm={"F": .4})
        self.assertTrue(result["candidates"])
        self.assert_common_model(result["candidates"][0], physical, .4)

    def test_impossible_budget_has_no_partial_candidate_pass(self):
        with mock.patch.object(indexing, "MAX_SEARCH_SEEDS", 0):
            with self.assertRaisesRegex(ValueError, "no partial candidate"):
                indexing.index_cubic([[5, 0], [0, 5], [5, 5]], calibrated=True)

    def test_search_is_deterministic_and_does_not_change_input(self):
        observed = np.array([[5., 0.], [0., 5.], [5., 5.]])
        before = observed.copy()
        first = indexing.index_cubic(observed, calibrated=True)
        second = indexing.index_cubic(observed, calibrated=True)
        self.assertEqual(first, second)
        np.testing.assert_array_equal(observed, before)

    def test_input_and_search_guards(self):
        base = {"vectors": [[1, 0], [0, 1], [1, 1]], "calibrated": True}
        changes = [
            {"vectors": [[1, 0], [2, 0], [-1, 0]]},
            {"vectors": [[1, 0], [0, 1], [1, 0]]},
            {"vectors": [[1, 0], [0, 0], [1, 1]]},
            {"vectors": [[1, 0], [0, float("nan")], [1, 1]]},
            {"vectors": [[1, 0], [0, float("inf")], [1, 1]]},
            {"vectors": [["1", "0"], ["0", "1"], ["1", "1"]]},
            {"vectors": [[1j, 0], [0, 1], [1, 1]]},
            {"vectors": [[1, 0], [0, 1]]},
            {"vectors": [[1, 0]] * 13},
            {"calibrated": 1}, {"max_index": True}, {"max_index": 5},
            {"max_unmatched": 1}, {"max_candidates": 0},
            {"relative_tolerance": 0}, {"relative_tolerance": float("nan")},
            {"angle_tolerance_deg": 11}, {"centerings": ["F", "F"]},
            {"centerings": ["C"]}, {"centerings": []},
            {"candidate_lattice_nm": {"F": 0}},
            {"candidate_lattice_nm": {"F": float("inf")}},
            {"candidate_lattice_nm": {"C": .4}},
        ]
        for change in changes:
            with self.subTest(change=change):
                arguments = dict(base)
                arguments.update(change)
                with self.assertRaises(ValueError):
                    indexing.index_cubic(**arguments)


if __name__ == "__main__":
    unittest.main()
