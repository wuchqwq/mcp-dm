"""Independent hand-calculable zone-axis geometry and actual diffsims checks."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock

HAS_ASE = importlib.util.find_spec("ase") is not None
HAS_DIFFSIMS = importlib.util.find_spec("diffsims") is not None
if HAS_ASE:
    import numpy as np
    from ase import Atoms
    from ase.io import write
    from crystallography.orientation import from_zone_axis, OrientationError
    from crystallography.structure_tools import execute, canonical


@unittest.skipUnless(HAS_ASE, "Optional external ASE/SciPy environment is not configured")
class ZoneAxisGeometry(unittest.TestCase):
    def test_cubic_110_reference_001_has_hand_calculated_right_handed_basis(self):
        record = from_zone_axis(np.eye(3) * 3.6, [1, 1, 0], [0, 0, 1])
        a = 1 / math.sqrt(2)
        expected = [[0, 0, 1], [a, -a, 0], [a, a, 0]]
        np.testing.assert_allclose(record["rotation_matrix_cartesian"], expected, atol=4e-16, rtol=0)
        np.testing.assert_allclose(np.asarray(expected) @ [a, a, 0], [0, 0, 1], atol=4e-16, rtol=0)
        self.assertAlmostEqual(record["determinant"], 1)
        self.assertEqual(record["handedness"], "right")
        self.assertFalse(record["source_coordinates_modified"])

    def test_hexagonal_indices_are_not_cartesian_components(self):
        cell = [[2, 0, 0], [-1, math.sqrt(3), 0], [0, 0, 3]]
        record = from_zone_axis(cell, [1, 1, 0], [0, 0, 1])
        expected = [[0, 0, 1], [math.sqrt(3)/2, -.5, 0], [.5, math.sqrt(3)/2, 0]]
        np.testing.assert_allclose(record["rotation_matrix_cartesian"], expected, atol=4e-16, rtol=0)
        np.testing.assert_allclose(record["beam_direction_cartesian_source_unit"], [.5, math.sqrt(3)/2, 0], atol=4e-16)
        self.assertGreater(np.linalg.norm(np.asarray(record["beam_direction_cartesian_source_unit"]) - [1/math.sqrt(2), 1/math.sqrt(2), 0]), .1)

    def test_nonorthogonal_reference_projection_has_independent_exact_matrix(self):
        record = from_zone_axis([[3, 0, 0], [1, 4, 0], [.5, .25, 5]], [0, 1, 0], [1, 0, 0])
        b = 1 / math.sqrt(17)
        expected = [[4*b, -b, 0], [0, 0, -1], [b, 4*b, 0]]
        np.testing.assert_allclose(record["rotation_matrix_cartesian"], expected, atol=4e-16, rtol=0)
        self.assertEqual(record["reference"]["kind"], "projected_direct_lattice_direction")

    def test_negative_zone_and_positive_roll_are_explicit_proper_rotations(self):
        up = from_zone_axis(np.eye(3), [0, 0, 1], [1, 0, 0], 90)
        np.testing.assert_allclose(up["rotation_matrix_cartesian"], [[0, -1, 0], [1, 0, 0], [0, 0, 1]], atol=3e-16, rtol=0)
        down = from_zone_axis(np.eye(3), [0, 0, -1], [1, 0, 0])
        np.testing.assert_allclose(down["rotation_matrix_cartesian"], [[1, 0, 0], [0, -1, 0], [0, 0, -1]], atol=1e-16, rtol=0)
        self.assertAlmostEqual(np.linalg.det(down["rotation_matrix_cartesian"]), 1)
        self.assertNotEqual(up["zone_axis_uvw"], down["zone_axis_uvw"])

    def test_zone_only_roll_rule_and_gimbal_lock_remain_reproducible(self):
        record = from_zone_axis(np.eye(3), [0, 0, 1])
        self.assertEqual(record["reference"]["cartesian_axis"], "x")
        self.assertEqual(record["reference"]["kind"], "cartesian_axis_least_parallel_to_beam")
        np.testing.assert_array_equal(record["rotation_matrix_cartesian"], np.eye(3))
        self.assertTrue(record["euler_gimbal_lock"])
        self.assertEqual(record, from_zone_axis(np.eye(3), [0, 0, 1]))

    def test_partial_cell_direction_can_be_observed_without_inventing_missing_axes(self):
        record = from_zone_axis([[0, 2, 0], [0, 0, 0], [0, 0, 0]], [1, 0, 0])
        np.testing.assert_allclose(record["beam_direction_cartesian_source_unit"], [0, 1, 0], atol=0, rtol=0)
        self.assertEqual(record["source_cell_angstrom"][1], [0, 0, 0])
        with self.assertRaises(OrientationError):
            from_zone_axis([[0, 2, 0], [0, 0, 0], [0, 0, 0]], [0, 1, 0])
        with self.assertRaisesRegex(OrientationError, "missing cell vector"):
            from_zone_axis([[0, 2, 0], [0, 0, 0], [0, 0, 0]], [1, 0, 1])
        with self.assertRaisesRegex(OrientationError, "missing cell vector"):
            from_zone_axis([[0, 2, 0], [0, 0, 0], [0, 0, 3]], [1, 0, 0], [1, 1, 1])

    def test_invalid_indices_missing_or_parallel_references_are_refused(self):
        for zone in ([0, 0, 0], [1., 0, 0], [True, 0, 0], [1, 0, 0, 0], [33, 0, 0], None):
            with self.subTest(zone=zone), self.assertRaises(OrientationError):
                from_zone_axis(np.eye(3), zone)
        for ref in ([0, 0, 1], [0, 0, -1], [0, 0, 0]):
            with self.subTest(reference=ref), self.assertRaises(OrientationError):
                from_zone_axis(np.eye(3), [0, 0, 1], ref)
        for angle in (True, float("nan"), float("inf"), 361):
            with self.subTest(angle=angle), self.assertRaises(OrientationError):
                from_zone_axis(np.eye(3), [0, 0, 1], in_plane_rotation_deg=angle)
        with self.assertRaises(OrientationError):
            from_zone_axis(np.zeros((3, 3)), [1, 0, 0])


@unittest.skipUnless(HAS_ASE, "Optional external ASE environment is not configured")
class OrientationWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dm-zone-axis-")
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.counter = 0
        self.file = self.root / "silicon.xyz"
        self.atoms = Atoms("Si", scaled_positions=[[.1, .2, .3]], cell=[3, 3, 3], pbc=True)
        write(self.file, self.atoms, format="extxyz")
        self.opened = self.call("open", source_path=str(self.file))

    def tearDown(self):
        self.temp.cleanup()

    def request(self, action, **kwargs):
        self.counter += 1
        return {"workspace": str(self.workspace), "action": action,
                **({"request_id": "zone-" + str(self.counter)} if action not in ("get", "result") else {}), **kwargs}

    def call(self, action, **kwargs):
        result = execute(self.request(action, **kwargs))
        self.assertTrue(result.get("ok"), result)
        return result["result"]

    def orientation(self):
        return self.call("orient", object_id=self.opened["object_id"], zone_axis_uvw=[1, 1, 0], in_plane_direction_uvw=[0, 0, 1])

    def test_view_rotates_only_a_copy_and_derive_makes_an_explicit_new_structure(self):
        original = self.call("get", object_id=self.opened["object_id"], include_atoms=True)["atoms"]
        digest = hashlib.sha256(self.file.read_bytes()).hexdigest()
        orient = self.orientation()
        matrix = np.asarray(orient["orientation"]["rotation_matrix_cartesian"])
        captured = []
        def render(atoms, directory, rotation, size):
            captured.append((atoms.positions.copy(), atoms.cell.array.copy(), rotation))
        with mock.patch("crystallography.structure_tools.render_atoms", side_effect=render):
            shown = self.call("view", object_id=self.opened["object_id"], orientation_id=orient["object_id"])
        np.testing.assert_allclose(captured[0][0], np.asarray(original["positions_angstrom"]) @ matrix.T, atol=1e-15, rtol=0)
        np.testing.assert_allclose(captured[0][1], np.asarray(original["cell_angstrom"]) @ matrix.T, atol=1e-15, rtol=0)
        self.assertEqual(captured[0][2], [0., 0., 0.])
        self.assertEqual(shown["orientation"], orient["orientation"])
        self.assertTrue(shown["display_recipe"]["display_coordinates_transformed"])
        self.assertFalse(shown["display_recipe"]["scientific_coordinates_modified"])
        self.assertEqual(self.call("get", object_id=shown["object_id"], include_atoms=True)["atoms"], original)
        derived = self.call("derive", object_id=self.opened["object_id"], orientation_id=orient["object_id"])
        transformed = self.call("get", object_id=derived["object_id"], include_atoms=True)["atoms"]
        np.testing.assert_allclose(transformed["positions_angstrom"], np.asarray(original["positions_angstrom"]) @ matrix.T, atol=1e-15, rtol=0)
        self.assertEqual(self.call("get", object_id=self.opened["object_id"], include_atoms=True)["atoms"], original)
        self.assertEqual(hashlib.sha256(self.file.read_bytes()).hexdigest(), digest)

    def test_reference_identity_conflict_and_double_rotation_are_rejected(self):
        orient = self.orientation()
        other = self.call("open", source_path=str(self.file))
        for request in (
            self.request("view", object_id=other["object_id"], orientation_id=orient["object_id"]),
            self.request("view", object_id=self.opened["object_id"], orientation_id=self.opened["object_id"]),
            self.request("view", object_id=self.opened["object_id"], orientation_id=orient["object_id"], rotation_deg_xyz=[0, 0, 0]),
            self.request("derive", object_id=self.opened["object_id"], orientation_id=orient["object_id"], rotation_deg_xyz=[0, 0, 0]),
        ):
            with self.subTest(request=request):
                reply = execute(request)
                self.assertFalse(reply.get("ok"), reply)
        reused = self.request("orient", object_id=self.opened["object_id"], zone_axis_uvw=[1, 0, 0], request_id=orient["request_id"])
        self.assertEqual(execute(reused)["error"]["code"], "REQUEST_CONFLICT")
        recovered = self.call("result", query_request_id=orient["request_id"])
        self.assertEqual(recovered["orientation"], orient["orientation"])
        self.assertEqual(recovered["object_id"], orient["object_id"])

    @unittest.skipUnless(HAS_DIFFSIMS, "Optional diffsims environment is not configured")
    def test_actual_simulation_uses_same_matrix_and_uvw_zone_law(self):
        orient = self.orientation()
        result = self.call("simulate", object_id=self.opened["object_id"], orientation_id=orient["object_id"],
                           voltage_kv=200, reciprocal_radius_inv_angstrom=1.3,
                           max_excitation_error_inv_angstrom=.02, size=64)
        hkl = np.asarray(result["reflections"]["hkl"])
        self.assertGreater(len(hkl), 2)
        a = 1 / math.sqrt(2)
        # Independently derived: R has rows (001),(1,-1,0)/sqrt2,(110)/sqrt2.
        expected = np.stack((hkl[:, 2]/3., (hkl[:, 0]-hkl[:, 1])*a/3., (hkl[:, 0]+hkl[:, 1])*a/3.), axis=1)
        np.testing.assert_allclose(result["reflections"]["coordinates_inv_angstrom"], expected, atol=2e-14, rtol=0)
        np.testing.assert_allclose(hkl[:, 0] + hkl[:, 1], 0, atol=0, rtol=0)
        self.assertEqual(result["orientation"], orient["orientation"])
        info = json.loads((Path(result["capture_path"]) / "input.json").read_text())
        self.assertEqual(info["external_provenance"]["orientation"], orient["orientation"])
        with mock.patch("diffsims.generators.diffraction_generator.DiffractionGenerator") as engine:
            bad = execute(self.request("simulate", object_id=self.opened["object_id"], orientation_id=orient["object_id"],
                                      euler_rzxz_deg=[0, 0, 0], voltage_kv=200, reciprocal_radius_inv_angstrom=1.3,
                                      max_excitation_error_inv_angstrom=.02, size=64))
        self.assertFalse(bad.get("ok"), bad)
        engine.assert_not_called()


if __name__ == "__main__":
    unittest.main()
