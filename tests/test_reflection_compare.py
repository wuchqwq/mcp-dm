"""Hand-solvable comparison counterexamples plus immutable tool composition."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest

HAS_ASE = importlib.util.find_spec("ase") is not None
HAS_DIFFSIMS = importlib.util.find_spec("diffsims") is not None
HAS_IMAGES = importlib.util.find_spec("tifffile") is not None
if HAS_ASE:
    import numpy as np
    from crystallography.reflection_compare import compare, measurement_vector, load_measurement, ComparisonError


def registration(**kwargs):
    return {"rotation_deg": 0., "scale": 1., "translation_inv_angstrom": [0., 0.], "flip_y": False,
            "basis": "Synthetic independently fixed axes; identity is a declared assumption, no fitting", **kwargs}


def measurement(q, ident="a", dc=0, scale_x=.1, scale_y=.1, unit="nm"):
    # Hand inputs use cycles/nm: q_A = f_pixel / (0.1 nm/pixel) / 10.
    points = [[0, 0], list(q)]
    if dc == 1:
        points.reverse()
    delta = [points[1][i] - points[0][i] for i in (0, 1)]
    record = {"calibration_id": "b"*32, "revision": 1, "status": "active", "source": "user_statement_not_independently_verified",
              "coordinate_domain": "real_space", "xy_scale": {"x": scale_x, "y": scale_y, "unit": unit}}
    return {"object_id": ident*32, "request_id": "measure-"+ident, "source_object_id": "c"*32,
            "kind": "measure", "backend": "external-image-workspace", "points": points,
            "xy_calibration": record, "calibration_dependency": {key: record[key] for key in ("calibration_id", "revision", "status", "source", "coordinate_domain")},
            "coordinate_space": "frequency_cycles_per_pixel", "measurement_domain": "reciprocal_space",
            "dc_reference_point_index": dc,
            "physical_vector_xy": [delta[0]/scale_x, delta[1]/scale_y], "physical_frequency_unit": "cycles/"+unit}


def simulation(vectors):
    return {"reflections": {"coordinates_inv_angstrom": [list(p) for p in vectors],
                            "hkl": [[i+1, 0, 0] for i in range(len(vectors))],
                            "kinematic_intensity": [i+1. for i in range(len(vectors))],
                            "reciprocal_convention": "cycles_per_angstrom_no_2pi",
                            "coordinates_frame": "rotated laboratory xyz; beam +z; raster columns +x, rows +y"}}


@unittest.skipUnless(HAS_ASE, "Optional independent ASE/SciPy environment is not configured")
class ReflectionGeometryTests(unittest.TestCase):
    def test_nm_to_angstrom_period_angle_and_unmatched_reflections_are_explicit(self):
        rows = [measurement([.2, 0]), measurement([0, .1], "d"), measurement([-.3, 0], "e")]
        sim = simulation([[.2, 0, 0], [0, .1, 0], [.4, .4, 0]])
        originals = copy.deepcopy((rows, sim))
        result = compare(rows, sim, registration(), 1e-12, "real_space_fft")
        self.assertEqual(len(result["matched"]), 2)
        self.assertEqual([item["measurement_index"] for item in result["unmatched_experimental"]], [2])
        self.assertEqual([item["simulation_reflection_index"] for item in result["unmatched_simulated"]], [2])
        self.assertAlmostEqual(result["matched"][0]["experiment_original_projected_period_angstrom"], 5.)
        self.assertAlmostEqual(result["matched"][1]["simulation_lattice_d_spacing_angstrom"], 10.)
        self.assertAlmostEqual(result["pairwise_angles"][0]["experimental_registered_signed_angle_deg"], 90.)
        self.assertAlmostEqual(result["pairwise_angles"][0]["angle_residual_deg"], 0.)
        self.assertFalse(result["all_experimental_reflections_matched_within_tolerance"])
        self.assertFalse(result["phase_identified"])
        self.assertFalse(result["intensity_comparison_performed"])
        self.assertFalse(result["registration"]["registration_verified"])
        self.assertEqual((rows, sim), originals)

    def test_signed_anisotropic_axes_and_reverse_dc_reference_preserve_direction(self):
        row = measurement([.2, .1], dc=1, scale_x=-.1, scale_y=.2)
        got = measurement_vector(row)
        np.testing.assert_allclose(got["q_xy_inv_angstrom"], [-.2, .05], atol=1e-16, rtol=0)
        self.assertEqual(got["dc_reference_point_index"], 1)
        self.assertEqual(got["calibration_record"]["xy_scale"]["x"], -.1)

    def test_native_reciprocal_indices_keep_raw_origin_and_do_not_apply_real_space_rule(self):
        row = measurement([.1, 0])
        row.update(coordinate_space="source_array_indices", points=[[4, 3], [6, 1]], physical_vector_xy=[1., .5])
        record = row["xy_calibration"]
        record.update(source="native_dm_capture", coordinate_domain="reciprocal_space", dc_index_xy=[4., 3.],
                      physical_zero_xy=[-2., .75], xy_scale={"x": .5, "y": -.25, "unit": "1/nm"})
        row["calibration_dependency"] = {key: record[key] for key in ("calibration_id", "revision", "status", "source", "coordinate_domain")}
        got = measurement_vector(row)
        np.testing.assert_allclose(got["q_xy_inv_angstrom"], [.1, .05], atol=1e-16, rtol=0)
        self.assertEqual(got["calibration_record"]["physical_zero_xy"], [-2., .75])
        bad = copy.deepcopy(row);bad["points"][0] = [4.000000000000001, 3]
        with self.assertRaisesRegex(ComparisonError, "DC index"):
            measurement_vector(bad)

    def test_declared_flip_roll_scale_translation_are_applied_to_comparison_copy_only(self):
        row = measurement([.2, .1]);before = copy.deepcopy(row)
        declared = registration(rotation_deg=90., scale=2., translation_inv_angstrom=[.1, -.2], flip_y=True,
                                basis="Synthetic known Y flip, quarter-turn, scale2 and independent centre offset")
        result = compare([row], simulation([[.3, .2, 0]]), declared, 1e-12, "real_space_fft")
        self.assertTrue(result["all_experimental_reflections_matched_within_tolerance"])
        np.testing.assert_allclose(result["matched"][0]["experiment_registered_q_xy_inv_angstrom"], [.3, .2], atol=2e-16, rtol=0)
        self.assertLess(result["matched"][0]["position_residual_inv_angstrom"], 2e-16)
        self.assertFalse(result["registration"]["experimental_calibration_modified"])
        self.assertFalse(result["registration"]["identity_parameters"])
        self.assertEqual(row, before)

    def test_coincident_projections_are_ambiguous_and_true_d_spacing_is_not_projected_period(self):
        sim = simulation([[.2, 0, 0], [.2, 0, .01]])
        result = compare([measurement([.2, 0])], sim, registration(), 1e-12, "real_space_fft")
        self.assertEqual(result["ambiguity"][0]["candidate_count"], 2)
        self.assertTrue(result["ambiguity"][0]["ambiguous_within_tolerance"])
        self.assertEqual(len(result["unmatched_simulated"]), 1)
        forced = compare([measurement([.2, 0])], sim, registration(), 1e-12, "real_space_fft", [{"measurement_index": 0, "hkl": [2, 0, 0]}])
        row = forced["matched"][0]
        self.assertAlmostEqual(row["simulation_projected_period_angstrom"], 5)
        self.assertAlmostEqual(row["simulation_lattice_d_spacing_angstrom"], 1/math.sqrt(.2**2+.01**2))
        self.assertFalse(forced["ambiguity"][0]["assignment_is_unique_proof"])

    def test_one_to_one_assignment_never_reuses_a_reflection_or_forces_far_match(self):
        result = compare([measurement([.2, 0]), measurement([.2, 0], "d")], simulation([[.2, 0, 0], [-.4, 0, 0]]), registration(), .001, "real_space_fft")
        self.assertEqual(len(result["matched"]), 1)
        self.assertEqual(len(result["unmatched_experimental"]), 1)
        self.assertTrue(all(row["ambiguous_within_tolerance"] for row in result["ambiguity"]))
        forced = compare([measurement([.2, 0])], simulation([[-.2, 0, 0]]), registration(), .001, "real_space_fft", [{"measurement_index":0,"hkl":[1,0,0]}])
        self.assertFalse(forced["matched"][0]["within_declared_tolerance"])
        self.assertFalse(forced["all_experimental_reflections_matched_within_tolerance"])

    def test_hand_binary_exact_matching_maximizes_cardinality_before_minimizing_residual(self):
        # Exact binary numbers: all four diagonal edges have residual .5.
        # Three zero edges plus a dummy must not defeat four feasible matches.
        rows = [measurement([x, 0], ident=ident, scale_x=.125, scale_y=.125, unit="angstrom")
                for x, ident in zip((.0625, .125, .1875, .25), "adef")]
        sim = simulation([[1.,0,0], [1.5,0,0], [2.,0,0], [2.5,0,0]])
        result = compare(rows, sim, registration(), .5, "real_space_fft")
        self.assertEqual(len(result["matched"]), 4)
        self.assertTrue(result["all_experimental_reflections_matched_within_tolerance"])
        self.assertEqual([r["position_residual_inv_angstrom"] for r in result["matched"]], [.5]*4)
        self.assertEqual(result["unmatched_experimental"], [])
        self.assertEqual(result["unmatched_simulated"], [])
        self.assertTrue(any(r["ambiguous_within_tolerance"] for r in result["ambiguity"]))

    def test_tiny_perpendicular_angles_and_nonzero_residuals_do_not_underflow_to_false_zero(self):
        rows = [measurement([1e-300,0], scale_x=1., scale_y=1.),
                measurement([0,1e-300], ident="d", scale_x=1., scale_y=1.)]
        sim = simulation([[1e-301,0,0], [0,1e-301,0]])
        result = compare(rows, sim, registration(), 1e-12, "real_space_fft")
        self.assertEqual(result["pairwise_angles"][0]["experimental_registered_signed_angle_deg"], 90.)
        self.assertEqual(result["pairwise_angles"][0]["simulation_projected_signed_angle_deg"], 90.)
        crossed = compare(rows, sim, registration(), 1e-12, "real_space_fft",
                          [{"measurement_index":0,"hkl":[2,0,0]},{"measurement_index":1,"hkl":[1,0,0]}])
        residual = crossed["matched"][0]["position_residual_inv_angstrom"]
        self.assertGreater(residual, 0.)
        self.assertTrue(math.isclose(residual, math.hypot(*crossed["matched"][0]["position_residual_xy_inv_angstrom"]), rel_tol=1e-15))
        self.assertEqual(crossed["pairwise_angles"][0]["angle_residual_deg"], -180.)

    def test_tiny_signed_angle_residual_is_not_lost_by_adding_180_degrees(self):
        rows = [measurement([.2,0], scale_x=1., scale_y=1., unit="angstrom"),
                measurement([.2,1e-300], ident="d", scale_x=1., scale_y=1., unit="angstrom")]
        sim = simulation([[.2,0,0], [.2,0,1e-6]])
        result = compare(rows, sim, registration(), 1e-12, "real_space_fft",
                         [{"measurement_index":0,"hkl":[1,0,0]},{"measurement_index":1,"hkl":[2,0,0]}])
        residual = result["pairwise_angles"][0]["angle_residual_deg"]
        self.assertLess(residual, 0.)
        self.assertTrue(math.isclose(residual, -math.degrees(math.atan2(1e-300, .2)), rel_tol=1e-14))

    def test_nonzero_component_unit_or_registration_underflow_is_refused_without_epsilon(self):
        tiny = measurement([5e-324,.25], scale_x=1e-4, scale_y=1e-4, unit="m")
        self.assertNotEqual(tiny["physical_vector_xy"][0], 0.)
        with self.assertRaisesRegex(ComparisonError, "underflows during unit conversion"):
            measurement_vector(tiny)
        row = measurement([5e-324,.2], scale_x=1., scale_y=1., unit="angstrom")
        self.assertNotEqual(measurement_vector(row)["q_xy_inv_angstrom"][0], 0.)
        with self.assertRaisesRegex(ComparisonError, "registration component underflows"):
            compare([row], simulation([[0,2e-7,0]]), registration(scale=1e-6), 1e-12, "real_space_fft")

    def test_unit_conversion_cannot_return_infinite_period_or_false_finite_lattice_spacing(self):
        tiny = measurement([5e-308,0], scale_x=1., scale_y=1., unit="m")
        with self.assertRaisesRegex(ComparisonError, "period overflows"):
            measurement_vector(tiny)
        normal = measurement([.2,0])
        with self.assertRaisesRegex(ComparisonError, "period overflows"):
            compare([normal], simulation([[5e-318,0,0]]), registration(), .5, "real_space_fft", [{"measurement_index":0,"hkl":[1,0,0]}])

    def test_unknown_withdrawn_conflicting_non_dc_and_radians_inputs_cannot_supply_reflections(self):
        mutations = [lambda r:r.update(dc_reference_point_index=None),
                     lambda r:r.update(physical_frequency_unit="radians/nm"),
                     lambda r:r.update(measurement_domain="real_space"),
                     lambda r:r["xy_calibration"].update(status="withdrawn"),
                     lambda r:r["xy_calibration"].update(source="unknown"),
                     lambda r:r["calibration_dependency"].update(revision=2),
                     lambda r:r.update(physical_vector_xy=[123., 0.]),
                     lambda r:r["points"].__setitem__(0, [.01, 0]),
                     lambda r:r.update(calibration_result_status="stale_relative_to_new_revision")]
        for mutate in mutations:
            row = measurement([.2, 0]);mutate(row)
            with self.subTest(mutation=mutate), self.assertRaises(ComparisonError):
                measurement_vector(row)
        with self.assertRaisesRegex(ComparisonError, "relabeled"):
            compare([measurement([.2, 0])], simulation([[.2, 0, 0]]), registration(), .001, "saed")
        with self.assertRaises(ComparisonError):
            compare([measurement([.2, 0])], simulation([[.2, 0, 0]]), {"scale":1.}, .001, "real_space_fft")


@unittest.skipUnless(HAS_ASE and HAS_DIFFSIMS and HAS_IMAGES, "Optional structure and image environments are not configured")
class ReflectionComparisonWorkflow(unittest.TestCase):
    def setUp(self):
        from ase import Atoms
        from ase.io import write
        import tifffile
        self.temp = tempfile.TemporaryDirectory(prefix="dm-reflection-compare-")
        self.root = Path(self.temp.name)
        self.counter = 0
        self.structure_workspace, self.image_workspace = self.root / "structures", self.root / "images"
        cif = self.root / "synthetic.xyz"
        write(cif, Atoms("Si", positions=[[0,0,0]], cell=[4,4,4], pbc=True), format="extxyz")
        opened = self.struct("open", source_path=str(cif))
        orient = self.struct("orient", object_id=opened["object_id"], zone_axis_uvw=[0,0,1], in_plane_direction_uvw=[1,0,0])
        self.sim = self.struct("simulate", object_id=opened["object_id"], orientation_id=orient["object_id"], voltage_kv=200,
                               reciprocal_radius_inv_angstrom=1.3, max_excitation_error_inv_angstrom=.02, size=64)
        self.tiff = self.root / "synthetic.tiff"
        y,x = np.indices((16,16));values=np.rint(1000+100*np.cos(2*np.pi*x/4)+100*np.cos(2*np.pi*y/4)).astype(np.uint16)
        tifffile.imwrite(self.tiff, values, photometric="minisblack")
        sequence = self.image("open", source_path=str(self.tiff))
        frame = self.image("frame", object_id=sequence["object_id"], frame_index=0)
        self.cal = self.image("calibrate", object_id=frame["object_id"], scope="image", xy_scale={"x":.1,"y":.1,"unit":"nm"}, source_text="Independent synthetic grid: real-space XY 0.1nm/px")
        self.fft = self.image("fft", object_id=self.cal["object_id"], rect=[0,0,16,16], window="none", subtract_mean=True)
        self.measures = [self.image("measure", object_id=self.fft["object_id"], coordinate_space="frequency_cycles_per_pixel", points=[[0,0],point]) for point in ([.25,0],[0,.25])]

    def tearDown(self):
        self.temp.cleanup()

    def struct(self, action, **kwargs):
        from crystallography.structure_tools import execute
        self.counter += 1
        request = {"workspace":str(self.structure_workspace),"action":action,"request_id":"structure-"+str(self.counter),**kwargs}
        response = execute(request)
        self.assertTrue(response.get("ok"), response)
        return response["result"]

    def image(self, action, **kwargs):
        from tools.image_workspace import execute
        self.counter += 1
        response=execute({"workspace":str(self.image_workspace),"action":action,"request_id":"image-"+str(self.counter),**kwargs})
        self.assertTrue(response.get("ok"),response)
        return response["result"]

    def compare_args(self):
        return {"object_id":self.sim["object_id"], "measurement_paths":[m["manifest_path"] for m in self.measures],
                "experimental_kind":"real_space_fft", "registration":registration(), "max_residual_inv_angstrom":1e-12,
                "correspondences":[{"measurement_index":0,"hkl":[1,0,0]},{"measurement_index":1,"hkl":[0,1,0]}]}

    def test_actual_tools_preserve_fixed_experimental_records_and_original_request_recovery(self):
        paths=[Path(m["manifest_path"]) for m in self.measures]
        before=[p.read_bytes() for p in paths]
        science=Path(self.fft["array_path"]).read_bytes();source=self.tiff.read_bytes()
        result=self.struct("compare",**self.compare_args())
        self.assertTrue(result["all_experimental_reflections_matched_within_tolerance"])
        self.assertEqual(len(result["matched"]),2)
        for row in result["matched"]:
            self.assertLess(row["position_residual_inv_angstrom"],1e-14)
            self.assertAlmostEqual(row["experiment_original_projected_period_angstrom"],4.)
        self.assertAlmostEqual(result["pairwise_angles"][0]["experimental_registered_signed_angle_deg"],90.)
        self.assertEqual(result["observations"][0]["calibration_dependency"]["calibration_id"],self.cal["object_id"])
        self.assertEqual([p.read_bytes() for p in paths],before)
        self.assertEqual(Path(self.fft["array_path"]).read_bytes(),science)
        self.assertEqual(self.tiff.read_bytes(),source)
        # Original compare recovery verifies its fixed copies, not a new state
        # read from a subsequently corrupted experimental record.
        paths[0].write_text('{}',encoding='utf-8')
        recovered=self.struct("result",query_request_id=result["request_id"])
        self.assertEqual(recovered["object_id"],result["object_id"])
        self.assertEqual(recovered["matched"],result["matched"])
        with self.assertRaises(ComparisonError):
            load_measurement(str(paths[0]))
        from crystallography.structure_tools import execute
        bad=execute({"workspace":str(self.structure_workspace),"action":"compare","request_id":"new-after-corruption",**self.compare_args()})
        self.assertFalse(bad.get("ok"),bad)

    def test_withdrawal_requires_a_new_measurement_and_cannot_silently_keep_physical_scale(self):
        withdrawn=self.image("calibrate",object_id=self.fft["object_id"],scope="image",xy_scale=None,source_text="Synthetic scale withdrawn; use pixel geometry only")
        new_measure=self.image("measure",object_id=withdrawn["object_id"],coordinate_space="frequency_cycles_per_pixel",points=[[0,0],[.25,0]])
        from crystallography.structure_tools import execute
        bad=execute({"workspace":str(self.structure_workspace),"action":"compare","request_id":"withdrawn-compare",
                     **{**self.compare_args(),"measurement_paths":[new_measure["manifest_path"]],"correspondences":[{"measurement_index":0,"hkl":[1,0,0]}]}})
        self.assertFalse(bad.get("ok"),bad)
        self.assertRegex(bad["error"]["message"],"active|withdrawn|unknown")

    def test_original_request_fields_cannot_disagree_with_measurement_even_after_rehashing_parameters(self):
        from crystallography.reflection_compare import canonical, sha
        file = Path(self.measures[0]["manifest_path"])
        _, binding, manifest_raw, journal_raw = load_measurement(file)
        journal_file = Path(binding["journal_path"])
        mutations = [("points", [[0,0],[0,.25]]),
                     ("object_id", self.cal["object_id"]),
                     ("coordinate_space", "source_array_indices")]
        for field, value in mutations:
            with self.subTest(field=field):
                journal = json.loads(journal_raw)
                journal["parameters"][field] = value
                journal["parameters_sha256"] = sha(canonical(journal["parameters"]))
                journal_file.write_bytes(canonical(journal))
                self.assertEqual(file.read_bytes(), manifest_raw)
                with self.assertRaisesRegex(ComparisonError, "contradict"):
                    load_measurement(file)
                journal_file.write_bytes(journal_raw)
                self.assertEqual(load_measurement(file)[0]["object_id"], self.measures[0]["object_id"])
        # Omitted space is valid: the actual saved FFT domain selected it at
        # creation. It must not be guessed as source_pixels by this reader.
        implicit = self.image("measure", object_id=self.fft["object_id"], points=[[0,0],[.25,0]])
        checked = load_measurement(implicit["manifest_path"])[0]
        self.assertEqual(checked["coordinate_space"], "frequency_cycles_per_pixel")


if __name__ == "__main__":
    unittest.main()
