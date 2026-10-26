"""Hand-computable SO(2) and held-out-leakage tests; no DM or phase claim."""
import copy
import importlib.util
import math
import unittest

HAS_SCIENCE = importlib.util.find_spec("scipy") is not None and importlib.util.find_spec("numpy") is not None
if HAS_SCIENCE:
    import numpy as np
    from crystallography.registration_proposal import propose, geometry_binding, RegistrationError
    from crystallography.reflection_compare import ComparisonError


def measurement(point, number, scale=(1., 1.), unit="angstrom"):
    # Binary64 division is required by the saved measurement contract; expected
    # rotations/residuals below are supplied independently as literal geometry.
    cal = {"calibration_id": "b"*32, "revision": 1, "status": "active",
           "source": "user_statement_not_independently_verified", "coordinate_domain": "real_space",
           "xy_scale": {"x": scale[0], "y": scale[1], "unit": unit}}
    return {"object_id": "{:032x}".format(number), "request_id": "measured-"+str(number),
            "source_object_id": "c"*32, "kind": "measure", "backend": "external-image-workspace",
            "points": [[0, 0], list(point)], "xy_calibration": cal,
            "calibration_dependency": {key: cal[key] for key in ("calibration_id", "revision", "status", "source", "coordinate_domain")},
            "coordinate_space": "frequency_cycles_per_pixel", "measurement_domain": "reciprocal_space",
            "dc_reference_point_index": 0, "physical_vector_xy": [point[0]/scale[0], point[1]/scale[1]],
            "physical_frequency_unit": "cycles/"+unit}


def simulation(vectors, hkls=None):
    return {"kind": "simulate", "software_provenance": {"diffsims": "0.7.0"},
            "reciprocal_enumeration": {"completeness_certified": True},
            "reflections": {"coordinates_inv_angstrom": [list(v) for v in vectors],
                            "hkl": hkls or [[1, 0, 0], [0, 1, 0], [1, 1, 0], [2, 0, 0]][:len(vectors)],
                            "kinematic_intensity": [float(i+1) for i in range(len(vectors))],
                            "reciprocal_convention": "cycles_per_angstrom_no_2pi",
                            "coordinates_frame": "rotated laboratory xyz; beam +z; raster columns +x, rows +y"}}


def pairs(*rows):
    return [{"measurement_index": index, "hkl": list(hkl)} for index, hkl in rows]


def call(rows=None, sim=None, **changes):
    args = {"measurements": rows or [measurement([.2, 0], 1), measurement([0, .3], 2), measurement([.2, .3], 3)],
            "simulation": sim or simulation([[0, .2, 0], [-.3, 0, 0], [-.3, .2, 0]]),
            "fit_correspondences": pairs((0, [1, 0, 0]), (1, [0, 1, 0])),
            "validation_correspondences": pairs((2, [1, 1, 0])),
            "screen_axes": {"flip_y": False, "basis": "Known independent synthetic image axes"},
            "max_residual_inv_angstrom": 1e-12, "experimental_kind": "real_space_fft",
            "confirmation": {"source": "synthetic_fixture", "source_text": "Independent hand-enumerated correspondences, not experimental identification"}}
    args.update(changes)
    return propose(**args)


@unittest.skipUnless(HAS_SCIENCE, "Optional independent NumPy/SciPy environment not configured")
class RegistrationProposalTests(unittest.TestCase):
    def test_hand_quarter_turn_and_independent_diagonal_validation_do_not_mutate_inputs(self):
        rows = [measurement([.2, 0], 1), measurement([0, .3], 2), measurement([.2, .3], 3)]
        sim = simulation([[0, .2, 0], [-.3, 0, 0], [-.3, .2, 0]])
        before = copy.deepcopy((rows, sim))
        result = call(rows, sim)
        self.assertAlmostEqual(result["registration"]["rotation_deg"], 90., places=12)
        np.testing.assert_allclose(result["rotation_matrix_xy"], [[0, -1], [1, 0]], atol=2e-16, rtol=0)
        self.assertEqual(result["registration"]["scale"], 1)
        self.assertEqual(result["registration"]["translation_inv_angstrom"], [0, 0])
        self.assertEqual(result["allowed_degrees_of_freedom"], ["in_plane_rotation"])
        self.assertEqual(result["validation_status"], "held_out_geometry_consistent")
        self.assertTrue(result["held_out_validation_passed"])
        self.assertEqual([v["measurement_index"] for v in result["fit_evidence"]], [0, 1])
        self.assertEqual([v["measurement_index"] for v in result["validation_evidence"]], [2])
        self.assertLess(result["validation_evidence"][0]["position_residual_inv_angstrom"], 1e-15)
        self.assertFalse(result["phase_identified"])
        self.assertFalse(result["intensity_comparison_performed"])
        self.assertEqual(result["comparison"]["registration"]["rotation_parameter_source"], "constrained_fit_correspondences_only")
        self.assertNotIn("never fitted", " ".join(result["comparison"]["scientific_limits"]))
        self.assertEqual((rows, sim), before)

    def test_hand_thirty_degree_and_signed_anisotropic_nm_axes(self):
        # f/scale/10 gives the literal q vectors (.2,0), (0,.3), (.2,.3).
        rows = [measurement([-.4, 0], 1, (-.2, .1), "nm"),
                measurement([0, .3], 2, (-.2, .1), "nm"),
                measurement([-.4, .3], 3, (-.2, .1), "nm")]
        c = math.sqrt(3)/2
        sim = simulation([[.2*c, .1, 0], [-.15, .3*c, 0], [.2*c-.15, .1+.3*c, 0]])
        got = call(rows, sim)
        self.assertAlmostEqual(got["registration"]["rotation_deg"], 30, places=12)
        self.assertTrue(got["held_out_validation_passed"])
        self.assertEqual(got["experimental_geometry_binding"]["calibration_dependency"]["revision"], 1)

    def test_explicit_screen_flip_is_fixed_not_inferred_and_rotation_stays_proper(self):
        sim = simulation([[0, .2, 0], [.3, 0, 0], [.3, .2, 0]])
        got = call(sim=sim, screen_axes={"flip_y": True, "basis": "Known synthetic downward image Y relative to laboratory Y"})
        self.assertAlmostEqual(got["registration"]["rotation_deg"], 90, places=12)
        self.assertAlmostEqual(float(np.linalg.det(got["rotation_matrix_xy"])), 1.)
        self.assertAlmostEqual(float(np.linalg.det(got["comparison_matrix_xy"])), -1.)
        self.assertTrue(got["held_out_validation_passed"])
        with self.assertRaisesRegex(RegistrationError, "Declare fixed"):
            call(screen_axes={"flip_y": "unknown", "basis": "Unknown experimental orientation is not a known screen flip"})

    def test_fit_points_alone_never_validate_registration(self):
        got = call(validation_correspondences=[])
        self.assertEqual(got["validation_status"], "not_tested_no_held_out")
        self.assertIsNone(got["held_out_validation_passed"])
        self.assertEqual(got["unassigned_measurement_indices"], [2])
        self.assertEqual(got["comparison"]["matched"][2]["evidence_role"], "not_used_for_fit_or_validation")

    def test_wrong_validation_is_reported_without_refitting_or_scale_change(self):
        sim = simulation([[0, .2, 0], [-.3, 0, 0], [-.31, .2, 0]])
        got = call(sim=sim, max_residual_inv_angstrom=.001)
        self.assertEqual(got["fit_status"], "within_declared_tolerance")
        self.assertEqual(got["validation_status"], "held_out_inconsistent")
        self.assertFalse(got["held_out_validation_passed"])
        self.assertAlmostEqual(got["registration"]["rotation_deg"], 90.)
        self.assertAlmostEqual(got["validation_evidence"][0]["position_residual_inv_angstrom"], .01)
        self.assertEqual(got["registration"]["scale"], 1.)

    def test_noise_uses_predeclared_tolerance_and_fit_failure_cannot_borrow_heldout_pass(self):
        sim = simulation([[.2, 0, 0], [0, .3, 0], [.2, .3, 0]])
        rows = [measurement([.200001, 0], 1), measurement([0, .300001], 2), measurement([.2, .3], 3)]
        accepted = call(rows, sim, max_residual_inv_angstrom=1e-5)
        self.assertTrue(accepted["held_out_validation_passed"])
        rejected = call(rows, sim, max_residual_inv_angstrom=1e-7)
        self.assertEqual(rejected["fit_status"], "outside_declared_tolerance")
        self.assertEqual(rejected["validation_status"], "fit_inconsistent")
        self.assertFalse(rejected["held_out_validation_passed"])
        self.assertEqual(rejected["registration"]["scale"], 1.)
        self.assertEqual(rejected["registration"]["translation_inv_angstrom"], [0., 0.])

    def test_bad_correspondence_does_not_add_a_hidden_mirror_or_distortion(self):
        # This wrong correspondence still has a unique proper least-squares
        # angle. The exact reflected/flat objective is separately refused below.
        sim = simulation([[0,.2,0],[-.3,0,0],[-.3,.2,0],[-.4,-.1,0]])
        got = call(sim=sim, fit_correspondences=pairs((0, [2, 0, 0]), (1, [0, 1, 0])), max_residual_inv_angstrom=.001)
        self.assertEqual(got["fit_status"], "outside_declared_tolerance")
        self.assertFalse(got["held_out_validation_passed"])
        self.assertFalse(got["registration"]["flip_y"])
        self.assertIsNone(got["fixed_parameters"]["distortion_model"])
        self.assertAlmostEqual(float(np.linalg.det(got["rotation_matrix_xy"])), 1.)

    def test_collinear_single_and_numerically_unresolved_fit_vectors_are_refused(self):
        for rows in ([measurement([.2, 0], 1), measurement([.3, 0], 2), measurement([.2, .3], 3)],
                     [measurement([.2, 0], 1), measurement([.3, 1e-20], 2), measurement([.2, .3], 3)]):
            with self.subTest(rows=rows), self.assertRaisesRegex(RegistrationError, "non-collinear"):
                call(rows)
        with self.assertRaisesRegex(RegistrationError, "Fit requires"):
            call(fit_correspondences=pairs((0, [1, 0, 0])))
        sim = simulation([[.2, 0, 0], [0, -.2, 0], [.2, -.2, 0]])
        rows = [measurement([.2, 0], 1), measurement([0, .2], 2), measurement([.2, .2], 3)]
        with self.assertRaisesRegex(RegistrationError, "non-unique"):
            call(rows, sim)

    def test_same_point_new_measurement_id_and_hkl_cannot_leak_between_fit_and_validation(self):
        for modify in (lambda rows: rows[2].update(object_id=rows[0]["object_id"]),
                       lambda rows: rows.__setitem__(2, measurement([.2, 0], 3))):
            rows = [measurement([.2, 0], 1), measurement([0, .3], 2), measurement([.2, .3], 3)]
            modify(rows)
            with self.subTest(modify=modify), self.assertRaises(RegistrationError):
                call(rows)
        for validation in (pairs((0, [1, 1, 0])), pairs((2, [1, 0, 0]))):
            with self.subTest(validation=validation), self.assertRaisesRegex(RegistrationError, "cannot reuse"):
                call(validation_correspondences=validation)

    def test_projected_duplicates_and_friedel_or_conjugate_mates_are_not_independent_validation(self):
        sim = simulation([[0, .2, 0], [-.3, 0, 0], [0, .2, .01]])
        with self.assertRaisesRegex(RegistrationError, "coincident"):
            call(sim=sim)
        sim = simulation([[0, .2, 0], [-.3, 0, 0], [0, -.2, 0]], [[1,0,0], [0,1,0], [-1,0,0]])
        rows = [measurement([.2, 0], 1), measurement([0, .3], 2), measurement([-.2, 0], 3)]
        with self.assertRaisesRegex(RegistrationError, "Friedel"):
            call(rows, sim, validation_correspondences=pairs((2, [-1, 0, 0])))
        sim = simulation([[0, .2, 0], [-.3, 0, 0], [-.1, -.2, 0]])
        with self.assertRaisesRegex(RegistrationError, "conjugate"):
            call(rows, sim)

    def test_heldout_list_itself_cannot_double_count_antipodal_or_projected_aliases(self):
        rows = [measurement([.2,0],1), measurement([0,.3],2), measurement([.2,.3],3), measurement([-.2,-.3],4)]
        sim = simulation([[0,.2,0],[-.3,0,0],[-.3,.2,0],[.3,-.2,0]], [[1,0,0],[0,1,0],[1,1,0],[-1,-1,0]])
        with self.assertRaisesRegex(RegistrationError, "separate independent"):
            call(rows, sim, validation_correspondences=pairs((2,[1,1,0]),(3,[-1,-1,0])))
        sim = simulation([[0,.2,0],[-.3,0,0],[-.3,.2,0],[-.3,.2,.01]])
        with self.assertRaisesRegex(RegistrationError, "Coincident"):
            call(rows, sim, validation_correspondences=pairs((2,[1,1,0]),(3,[2,0,0])))

    def test_one_ulp_alias_is_unresolved_not_reported_as_independent_validation(self):
        rows = [measurement([.2,0],1), measurement([0,.3],2), measurement([math.nextafter(.2,math.inf),0],3)]
        sim = simulation([[0,.2,0],[-.3,0,0],[0,math.nextafter(.2,math.inf),0]])
        got = call(rows, sim)
        self.assertEqual(got["validation_status"], "held_out_independence_unresolved")
        self.assertFalse(got["held_out_validation_passed"])
        self.assertTrue(got["held_out_independence"]["unresolved_binary64_aliases"])
        self.assertEqual(got["max_residual_inv_angstrom"],1e-12)

    def test_simulated_direct_beam_cannot_be_claimed_as_an_extra_heldout_reflection(self):
        sim = simulation([[0,.2,0],[-.3,0,0],[0,0,0]], [[1,0,0],[0,1,0],[0,0,0]])
        with self.assertRaisesRegex(RegistrationError, "direct beam"):
            call(sim=sim, validation_correspondences=pairs((2,[0,0,0])), max_residual_inv_angstrom=1)
        sim["reflections"]["coordinates_inv_angstrom"][2] = [0,0,.1]
        with self.assertRaisesRegex(RegistrationError, "zero transverse"):
            call(sim=sim, validation_correspondences=pairs((2,[0,0,0])), max_residual_inv_angstrom=1)

    def test_mixed_frame_roi_calibration_or_center_versions_fail_before_fitting(self):
        mutations = [lambda row: row.update(source_object_id="d"*32),
                     lambda row: row.update(source_rect_xyxy=[0,0,16,16]),
                     lambda row: row["calibration_dependency"].update(revision=2),
                     lambda row: row["xy_calibration"].update(source_text="Different origin provenance")]
        for mutate in mutations:
            rows = [measurement([.2, 0], 1), measurement([0, .3], 2), measurement([.2, .3], 3)]
            mutate(rows[1])
            with self.subTest(mutate=mutate), self.assertRaises((RegistrationError, ComparisonError)):
                call(rows)

    def test_unknown_scale_radians_withdrawal_and_uncertified_simulation_cannot_fit(self):
        for mutation in (lambda row: row["xy_calibration"].update(status="withdrawn"),
                         lambda row: row["xy_calibration"].update(source="unknown"),
                         lambda row: row.update(physical_frequency_unit="radians/angstrom")):
            rows = [measurement([.2, 0], 1), measurement([0, .3], 2), measurement([.2, .3], 3)]
            mutation(rows[0])
            with self.subTest(mutation=mutation), self.assertRaises(ComparisonError):
                call(rows)
        for cert in (False, None):
            sim = simulation([[0,.2,0],[-.3,0,0],[-.3,.2,0]])
            sim["reciprocal_enumeration"]["completeness_certified"] = cert
            with self.subTest(cert=cert), self.assertRaisesRegex(RegistrationError, "certified"):
                call(sim=sim)
        with self.assertRaisesRegex(RegistrationError, "confirmation"):
            call(confirmation={"source":"agent_hypothesis","source_text":"Not user-confirmed"})

    def test_binding_changes_for_scale_center_or_peak_revision_and_never_changes_input(self):
        rows = [measurement([.2, 0], 1), measurement([0, .3], 2), measurement([.2, .3], 3)]
        before = copy.deepcopy(rows)
        baseline = geometry_binding(rows)
        revised = copy.deepcopy(rows)
        for row in revised:
            row["xy_calibration"]["calibration_id"] = "e"*32
            row["xy_calibration"]["revision"] = 2
            row["calibration_dependency"] = {key: row["xy_calibration"][key] for key in row["calibration_dependency"]}
        self.assertNotEqual(geometry_binding(revised)["sha256"], baseline["sha256"])
        changed = copy.deepcopy(rows);changed[2] = measurement([.3, .3], 3)
        self.assertNotEqual(geometry_binding(changed)["sha256"], baseline["sha256"])
        self.assertEqual(rows, before)

    def test_unassigned_observations_and_coincident_hkl_ambiguities_remain_visible(self):
        rows = [measurement([.2,0],1), measurement([0,.3],2), measurement([.2,.3],3), measurement([.4,.4],4)]
        sim = simulation([[0,.2,0],[-.3,0,0],[-.3,.2,0],[0,.2,.01]])
        got = call(rows, sim)
        self.assertEqual(got["unassigned_measurement_indices"], [3])
        self.assertEqual(len(got["comparison"]["unmatched_experimental"]), 1)
        self.assertTrue(got["comparison"]["ambiguity"][0]["ambiguous_within_tolerance"])
        self.assertEqual(len(got["comparison"]["unmatched_simulated"]), 1)
        self.assertTrue(got["held_out_validation_passed"])

    def test_tiny_finite_vectors_preserve_quarter_turn_without_covariance_underflow(self):
        rows = [measurement([1e-300,0],1), measurement([0,1e-300],2), measurement([1e-300,1e-300],3)]
        sim = simulation([[0,1e-300,0],[-1e-300,0,0],[-1e-300,1e-300,0]])
        got = call(rows, sim)
        self.assertAlmostEqual(got["registration"]["rotation_deg"], 90)
        self.assertAlmostEqual(float(np.linalg.det(got["rotation_matrix_xy"])), 1)
        self.assertTrue(got["held_out_validation_passed"])


if __name__ == "__main__":
    unittest.main()
