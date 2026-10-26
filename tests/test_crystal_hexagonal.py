"""Independent analytical hexagonal metrics, not synthetic DM acceptance."""

import math
import unittest
from unittest import mock

import numpy as np

from crystallography import hexagonal


def reciprocal_analytical(ca):
    # Inverse-transpose of direct a1=(1,0), a2=(-1/2,sqrt(3)/2), c=(0,0,ca).
    # This oracle does not call ASE or the companion's cell helper.
    return np.array([[1., 1. / math.sqrt(3.), 0.],
                     [0., 2. / math.sqrt(3.), 0.], [0., 0., 1. / ca]])


def observed_pattern(hkl, a, ca, plane_x, plane_y, rotation=0., mirror=False):
    cart = np.array(hkl) @ reciprocal_analytical(ca) / a
    plane = np.array([plane_x, plane_y], dtype=float)
    values = cart @ plane.T
    theta = math.radians(rotation)
    values = values @ np.array([[math.cos(theta), math.sin(theta)],
                               [-math.sin(theta), math.cos(theta)]])
    if mirror:
        values[:, 0] *= -1
    return values


class HexagonalIndexingTests(unittest.TestCase):
    def assert_joint_orientation(self, candidate, expected, a, ca):
        self.assertEqual(candidate["lattice_parameter_a_nm"], a)
        self.assertAlmostEqual(candidate["lattice_parameter_c_nm"], a * ca, places=13)
        self.assertEqual(candidate["c_over_a"], ca)
        transform = np.array(candidate["crystal_to_image_orientation"])
        np.testing.assert_allclose(transform @ transform.T, np.eye(3), atol=1e-12)
        self.assertAlmostEqual(np.linalg.det(transform), 1., places=12)
        reciprocal = reciprocal_analytical(ca)
        for observation in candidate["observations"]:
            if not observation["matched"]:
                continue
            hkl = np.array(observation["hkl"])
            g = transform @ (hkl @ reciprocal) / a
            np.testing.assert_allclose(g[:2], expected[observation["observation_index"]], atol=1e-10)
            self.assertAlmostEqual(g[2], 0., places=10)
            self.assertEqual(int(hkl @ candidate["zone_axis_uvw"]), 0)
            self.assertEqual(int(np.dot(observation["hkil"], candidate["zone_axis_uvtw"])), 0)
        self.assertEqual(candidate["centering"], "P")
        self.assertEqual(candidate["model"], "HCP")
        self.assertFalse(candidate["chemical_phase_identified"])

    def test_ase_cell_reciprocal_matches_analytic_metric_without_two_pi(self):
        for ca in (1.58, math.sqrt(8. / 3.), 1.90):
            reciprocal = np.asarray(hexagonal.hexagonal_cell(ca).reciprocal())
            np.testing.assert_allclose(reciprocal, reciprocal_analytical(ca), atol=1e-14)
            # 1/d_10-10^2 = 4/(3a^2), 1/d_0002^2 = 4/c^2.
            self.assertAlmostEqual(np.linalg.norm(reciprocal[0]) ** 2, 4. / 3.)
            self.assertAlmostEqual(np.linalg.norm(2 * reciprocal[2]) ** 2, 4. / (ca * ca))

    def test_basal_0001_rotated_and_mirrored_fixed_reference(self):
        ca, a = 1.58, .32
        for mirror in (False, True):
            with self.subTest(mirror=mirror):
                values = observed_pattern([[1, 0, 0], [0, 1, 0], [1, 1, 0]], a, ca,
                                          [1, 0, 0], [0, 1, 0], 37, mirror)
                result = hexagonal.index_hcp(values, calibrated=True, lattice_parameter_a_nm=a,
                                             c_over_a=ca, max_index=2,
                                             relative_tolerance=.0001, angle_tolerance_deg=.01)
                self.assertTrue(result["candidates"])
                candidate = result["candidates"][0]
                self.assertEqual(candidate["zone_axis_uvtw"][:3], [0, 0, 0])
                self.assertEqual(abs(candidate["zone_axis_uvtw"][3]), 1)
                self.assertEqual(candidate["c_over_a_sensitivity"], "basal_only_c_over_a_unconstrained")
                self.assert_joint_orientation(candidate, values, a, ca)

    def test_prismatic_11_minus2_0_zone_with_nonideal_c_over_a(self):
        ca, a = 1.58, .29
        values = observed_pattern([[1, -1, 0], [0, 0, 2], [1, -1, 2]], a, ca,
                                  [math.sqrt(3) / 2, -.5, 0], [0, 0, 1], -21)
        result = hexagonal.index_hcp(values, calibrated=True, lattice_parameter_a_nm=a,
                                     c_over_a=ca, max_index=2,
                                     relative_tolerance=.0001, angle_tolerance_deg=.01)
        self.assertTrue(result["candidates"])
        candidate = result["candidates"][0]
        self.assertEqual(sorted(abs(v) for v in candidate["zone_axis_uvtw"][:3]), [1, 1, 2])
        self.assertEqual(candidate["zone_axis_uvtw"][3], 0)
        self.assert_joint_orientation(candidate, values, a, ca)
        wrong_ratio = hexagonal.index_hcp(values, calibrated=True, lattice_parameter_a_nm=a,
                                          c_over_a=hexagonal.IDEAL_C_OVER_A, max_index=2,
                                          relative_tolerance=.0001, angle_tolerance_deg=.01)
        self.assertEqual(wrong_ratio["candidates"], [])

    def test_prismatic_10_minus1_0_zone_and_four_index_direction_conversion(self):
        ca, a = 1.9, .27
        values = observed_pattern([[1, -2, 0], [0, 0, 2], [1, -2, 2]], a, ca,
                                  [.5, -math.sqrt(3) / 2, 0], [0, 0, 1], 17, True)
        result = hexagonal.index_hcp(values, calibrated=True, lattice_parameter_a_nm=a,
                                     c_over_a=ca, max_index=2,
                                     relative_tolerance=.0001, angle_tolerance_deg=.01)
        self.assertTrue(result["candidates"])
        candidate = result["candidates"][0]
        self.assertEqual(sorted(abs(v) for v in candidate["zone_axis_uvtw"][:3]), [0, 1, 1])
        self.assertEqual(candidate["zone_axis_uvtw"][3], 0)
        self.assert_joint_orientation(candidate, values, a, ca)
        self.assertEqual(hexagonal.direction_three_to_four([1, 1, 0]), [1, 1, -2, 0])
        self.assertEqual(hexagonal.direction_three_to_four([2, 1, 0]), [1, 0, -1, 0])
        self.assertEqual(hexagonal.direction_three_to_four([1, 0, 1]), [2, -1, -1, 3])

    def test_oblique_zone_keeps_real_space_w_and_four_index_scale(self):
        ca, a = 1.58, .31
        # Direct zone [101] is Cartesian (1,0,c/a), not (1,0,1).
        plane_x = np.array([ca, 0, -1.]) / math.sqrt(1 + ca * ca)
        values = observed_pattern([[1, 0, -1], [0, 1, 0], [1, 1, -1]], a, ca,
                                  plane_x, [0, 1, 0], -14)
        result = hexagonal.index_hcp(values, calibrated=True, lattice_parameter_a_nm=a,
                                     c_over_a=ca, max_index=2,
                                     relative_tolerance=.0001, angle_tolerance_deg=.01)
        self.assertTrue(result["candidates"])
        for candidate in result["candidates"]:
            self.assertEqual(abs(candidate["zone_axis_uvtw"][3]), 3)
            self.assertEqual(sorted(abs(v) for v in candidate["zone_axis_uvtw"][:3]), [1, 1, 2])
            direct = np.array([[1, 0, 0], [-.5, math.sqrt(3) / 2, 0], [0, 0, ca]])
            zone_cart = np.array(candidate["zone_axis_uvw"]) @ direct
            beam = np.array(candidate["crystal_to_image_orientation"])[2]
            np.testing.assert_allclose(zone_cart / np.linalg.norm(zone_cart), beam, atol=1e-12)
            self.assert_joint_orientation(candidate, values, a, ca)

    def test_explicit_grid_does_not_erase_basal_ratio_ambiguity(self):
        ratios = [1.58, hexagonal.IDEAL_C_OVER_A, 1.90]
        values = observed_pattern([[1, 0, 0], [0, 1, 0], [1, 1, 0]], .3, 1.58,
                                  [1, 0, 0], [0, 1, 0])
        result = hexagonal.index_hcp(values, calibrated=True, c_over_a_candidates=ratios,
                                     max_index=2, max_candidates=1)
        self.assertEqual(result["ambiguity"]["compatible_c_over_a_values"], ratios)
        self.assertEqual(set(c["c_over_a"] for c in result["candidates"]), set(ratios))
        self.assertTrue(all(c["c_over_a_sensitivity"] == "basal_only_c_over_a_unconstrained"
                            for c in result["candidates"]))
        default = hexagonal.index_hcp(values, calibrated=False, max_index=2)
        self.assertEqual(default["search"]["c_over_a_source"], "assumed_ideal_hcp_sqrt_8_over_3")
        self.assertTrue(all(c["lattice_parameter_a_nm"] is None and c["lattice_parameter_c_nm"] is None
                            for c in default["candidates"]))

    def test_grid_selects_nonideal_ratio_when_data_contains_c_information(self):
        a, ca = .3, 1.58
        values = observed_pattern([[1, -1, 0], [0, 0, 2], [1, -1, 2]], a, ca,
                                  [math.sqrt(3) / 2, -.5, 0], [0, 0, 1])
        result = hexagonal.index_hcp(values, calibrated=True, lattice_parameter_a_nm=a,
                                     c_over_a_candidates=[1.58, hexagonal.IDEAL_C_OVER_A, 1.9],
                                     max_index=2, relative_tolerance=.0001, angle_tolerance_deg=.01)
        self.assertEqual(result["ambiguity"]["compatible_c_over_a_values"], [1.58])
        self.assertFalse(result["candidates"][0]["c_over_a_continuously_fitted"])
        self.assert_joint_orientation(result["candidates"][0], values, a, ca)

    def test_two_atom_basis_is_diagnostic_not_primitive_hexagonal_hcp_equivalence(self):
        self.assertTrue(hexagonal.hcp_basis_diagnostic([0, 0, 1])["kinematic_basis_cancellation"])
        self.assertEqual(hexagonal.hcp_basis_diagnostic([0, 0, 2])["ideal_identical_atom_basis_factor_squared"], 4.)
        self.assertAlmostEqual(hexagonal.hcp_basis_diagnostic([1, 0, 0])["ideal_identical_atom_basis_factor_squared"], 1.)
        self.assertAlmostEqual(hexagonal.hcp_basis_diagnostic([1, 0, 1])["ideal_identical_atom_basis_factor_squared"], 3.)
        values = observed_pattern([[1, -1, 0], [0, 0, 1], [1, -1, 1]], .3, 1.58,
                                  [math.sqrt(3) / 2, -.5, 0], [0, 0, 1])
        result = hexagonal.index_hcp(values, calibrated=True, lattice_parameter_a_nm=.3,
                                     c_over_a=1.58, max_index=1,
                                     relative_tolerance=.0001, angle_tolerance_deg=.01)
        self.assertTrue(result["candidates"])
        self.assertTrue(result["candidates"][0]["ideal_basis_cancellation_observation_indices"])
        self.assertFalse(result["candidates"][0]["observations"][1]["hcp_basis_diagnostic"]["used_as_hard_rejection"])
        self.assertTrue(result["basis"]["diagnostics_only"])

    def test_noise_outlier_and_fixed_parameters_preserved(self):
        ca, a = 1.58, .3
        values = observed_pattern([[1, -1, 0], [0, 0, 2], [1, -1, 2]], a, ca,
                                  [math.sqrt(3) / 2, -.5, 0], [0, 0, 1])
        values += np.array([[.001, -.002], [.002, .001], [-.001, .001]])
        values = np.vstack((values, [7.123, 8.765]))
        result = hexagonal.index_hcp(values, calibrated=True, lattice_parameter_a_nm=a,
                                     c_over_a=ca, max_index=2, max_unmatched=1,
                                     relative_tolerance=.003, angle_tolerance_deg=.2)
        self.assertTrue(result["candidates"])
        candidate = result["candidates"][0]
        self.assertEqual(candidate["unmatched_observation_indices"], [3])
        self.assertEqual(candidate["matched_count"], 3)
        self.assertEqual(candidate["lattice_parameter_a_nm"], a)
        self.assertEqual(candidate["lattice_parameter_c_nm"], a * ca)
        self.assertLess(candidate["rms_relative_vector_residual"], .003)

    def test_source_unchanged_and_bounded_search_failure(self):
        values = np.array([[1., 0.], [.5, math.sqrt(3) / 2], [1.5, math.sqrt(3) / 2]])
        original = values.copy()
        first = hexagonal.index_hcp(values, calibrated=False, max_index=2)
        second = hexagonal.index_hcp(values, calibrated=False, max_index=2)
        self.assertEqual(first, second)
        np.testing.assert_array_equal(values, original)
        with mock.patch.object(hexagonal, "MAX_HCP_SEARCH_SEEDS", 0):
            with self.assertRaisesRegex(ValueError, "no partial"):
                hexagonal.index_hcp(values, calibrated=False, max_index=2)

    def test_input_guards(self):
        base = {"vectors": [[1, 0], [.5, math.sqrt(3) / 2], [1.5, math.sqrt(3) / 2]],
                "calibrated": True}
        changes = [{"vectors": [[1, 0], [2, 0], [3, 0]]}, {"vectors": [[1, 0]] * 3},
                   {"vectors": [[0, 0], [0, 1], [1, 1]]},
                   {"vectors": [[1, 0], [0, float("nan")], [1, 1]]},
                   {"vectors": [["1", "0"], ["0", "1"], ["1", "1"]]},
                   {"calibrated": 1}, {"max_index": 5}, {"max_index": True},
                   {"c_over_a": .4}, {"c_over_a_candidates": []},
                   {"c_over_a_candidates": [1.58] * 2},
                   {"c_over_a_candidates": list(np.linspace(1.4, 2, 14))},
                   {"c_over_a": 1.58, "c_over_a_candidates": [1.6]},
                   {"calibrated": False, "lattice_parameter_a_nm": .3},
                   {"lattice_parameter_a_nm": 0}, {"max_unmatched": 1}]
        for change in changes:
            with self.subTest(change=change):
                arguments = dict(base)
                arguments.update(change)
                with self.assertRaises(ValueError):
                    hexagonal.index_hcp(**arguments)
        with self.assertRaises(ValueError):
            hexagonal.hcp_basis_diagnostic([1.5, 0, 0])
        with self.assertRaises(ValueError):
            hexagonal.direction_three_to_four([0, 0, 0])


if __name__ == "__main__":
    unittest.main()
