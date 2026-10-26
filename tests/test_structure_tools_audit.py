"""Independent synthetic scientific counterexamples, never DM/private data.

These tests exercise metric/completeness contracts rather than implementing a
replacement diffraction engine.  In particular a mature library's unsupported
geometry must be refused, not silently presented as a complete reflection set.
"""
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
    from crystallography.structure_tools import (
        StructureError, execute, measure, simulate, summary,
    )


@unittest.skipUnless(HAS_ASE, "Optional independent ASE environment is not configured")
class StructureToolsScientificAudit(unittest.TestCase):
    def test_nonzero_but_dependent_cell_is_not_a_3d_crystal_metric(self):
        atoms = Atoms("SiSi", positions=[[0, 0, 0], [1, 0, 0]],
                      cell=[[1, 0, 0], [2, 0, 0], [0, 0, 3]], pbc=True)
        self.assertEqual(atoms.cell.rank, 3, "ASE rank counts nonzero vectors")
        self.assertEqual(np.linalg.matrix_rank(atoms.cell.array), 2)
        info = summary(atoms)
        self.assertEqual(info["cell_rank"], 2)
        self.assertFalse(info["has_periodic_3d_cell"])
        # Ordinary Cartesian geometry remains usable; pseudoinverse-derived
        # crystal spacings/directions and ill-defined MIC must not pass.
        self.assertEqual(measure(atoms, {"kind": "distance", "atom_indices": [0, 1]})["value"], 1.)
        for request in (
            {"kind": "d_spacing", "hkls": [[1, 0, 0]]},
            {"kind": "zone_relation", "hkls": [[1, 0, 0]], "directions": [[1, 0, 0]]},
            {"kind": "direction_angle", "directions": [[1, 0, 0], [0, 0, 1]]},
            {"kind": "distance", "atom_indices": [0, 1], "mic": True},
        ):
            with self.subTest(request=request), self.assertRaises(StructureError):
                measure(atoms, request)

    def test_partial_periodic_independence_uses_only_declared_periodic_vectors(self):
        atoms = Atoms("CC", positions=[[.2, 0, 0], [2.8, 0, 0]],
                      cell=[[3, 0, 0], [0, 0, 0], [0, 0, 0]], pbc=[True, False, False])
        result = measure(atoms, {"kind": "distance", "atom_indices": [0, 1], "mic": True})
        self.assertAlmostEqual(result["value"], .4)
        atoms.cell = [[3, 0, 0], [6, 0, 0], [0, 0, 0]]
        atoms.pbc = [True, True, False]
        with mock.patch.object(atoms, "get_distance") as geometry:
            with self.assertRaises(StructureError):
                measure(atoms, {"kind": "distance", "atom_indices": [0, 1], "mic": True})
            geometry.assert_not_called()

    def test_original_request_recovers_fixed_copy_after_source_changed_or_deleted(self):
        with tempfile.TemporaryDirectory(prefix="dm-structure-audit-") as temporary:
            directory = Path(temporary)
            source, workspace = directory / "source.xyz", directory / "workspace"
            first = b"1\nInitial fixed input\nC 0 0 0\n"
            source.write_bytes(first)
            request = {"workspace": str(workspace), "action": "open", "source_path": str(source), "request_id": "original"}
            opened = execute(request)
            self.assertTrue(opened["ok"], opened)
            original = opened["result"]
            source.write_text("1\nDifferent future input\nO 1 2 3\n", encoding="utf-8")
            self.assertEqual(execute(request)["result"]["object_id"], original["object_id"])
            source.unlink()
            recovered = execute({"workspace": str(workspace), "action": "result", "query_request_id": "original"})
            self.assertTrue(recovered["ok"], recovered)
            self.assertEqual(recovered["result"]["object_id"], original["object_id"])
            self.assertEqual(execute(request)["result"]["source"], original["source"])
            self.assertEqual((Path(original["manifest_path"]).parent / "source.xyz").read_bytes(), first)
            new_capture = execute({**request, "request_id": "new-capture"})
            self.assertFalse(new_capture["ok"], "A new capture must not pretend the deleted source exists")

    @unittest.skipUnless(HAS_DIFFSIMS, "Optional independent diffsims environment is not configured")
    def test_candidate_budget_refuses_before_scattering_engine_creation(self):
        atoms = Atoms("Si", positions=[[0, 0, 0]], cell=[100, 100, 100], pbc=True)
        with tempfile.TemporaryDirectory() as temporary, mock.patch(
                "diffsims.generators.diffraction_generator.DiffractionGenerator") as generator:
            with self.assertRaises(StructureError) as caught:
                simulate(atoms, self.parameters(), Path(temporary), "b" * 32)
            self.assertEqual(caught.exception.code, "BUDGET_EXCEEDED")
            generator.assert_not_called()

    @staticmethod
    def parameters(**changes):
        return {"object_id": "a" * 32, "voltage_kv": 200,
                "euler_rzxz_deg": [17, 23, 31],
                "reciprocal_radius_inv_angstrom": 1.3,
                "max_excitation_error_inv_angstrom": .2,
                "size": 64, "with_direct_beam": True, **changes}

    @unittest.skipUnless(HAS_DIFFSIMS, "Optional independent diffsims environment is not configured")
    def test_all_three_rzxz_angles_preserve_generic_source_basis_and_saved_axes(self):
        cell = np.array([[0., 3., 0.], [-4., 1., 0.], [.25, .5, 5.]])
        atoms = Atoms("Si", scaled_positions=[[.1, .2, .3]], cell=cell, pbc=True)
        original_cell, original_positions = atoms.cell.array.copy(), atoms.positions.copy()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            result = simulate(atoms, self.parameters(), directory, "b" * 32)
            # Active intrinsic Z-X-Z means Rz(first) Rx(second) Rz(third).
            def rz(degrees):
                angle = math.radians(degrees)
                c, s = math.cos(angle), math.sin(angle)
                return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
            angle = math.radians(23)
            rx = np.array([[1, 0, 0], [0, math.cos(angle), -math.sin(angle)], [0, math.sin(angle), math.cos(angle)]])
            rotation = rz(17) @ rx @ rz(31)
            hkls = np.asarray(result["reflections"]["hkl"])
            self.assertGreater(len(hkls), 3)
            expected = (rotation @ (hkls @ np.linalg.inv(cell).T).T).T
            np.testing.assert_allclose(result["reflections"]["coordinates_inv_angstrom"], expected, atol=2e-14, rtol=0)
            metadata = json.loads((directory / "input.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["axes"], ["y", "x"])
            self.assertEqual(metadata["array_order"], "C")
            self.assertEqual(np.load(directory / "input.npy", allow_pickle=False).shape, (64, 64))
            for axis in metadata["calibration"]:
                self.assertEqual(axis["origin"], 32.)
                self.assertAlmostEqual(axis["scale"], 2.6 / 64)
                self.assertAlmostEqual(axis["physical_pixel_zero"], -1.3)
                self.assertEqual((32 - axis["origin"]) * axis["scale"], 0.)
            np.testing.assert_array_equal(atoms.cell.array, original_cell)
            np.testing.assert_array_equal(atoms.positions, original_positions)

    @unittest.skipUnless(HAS_DIFFSIMS, "Optional independent diffsims environment is not configured")
    def test_skew_cell_enumeration_must_not_silently_omit_eligible_110(self):
        # The library's simple |index|<=floor(R/|basis_vector|) enumeration
        # omits cancellation combinations.  g110=(1/3,1/9,0) is in-radius,
        # almost exactly on the Ewald sphere, with nonzero P1-Si scattering.
        atoms = Atoms("Si", scaled_positions=[[0, 0, 0]],
                      cell=[[3., 0, 0], [2.9, .3, 0], [0, 0, 3.]], pbc=True)
        reciprocal = np.array([1, 1, 0]) @ np.linalg.inv(atoms.cell.array).T
        np.testing.assert_allclose(reciprocal, [1/3, 1/9, 0], atol=1e-14)
        self.assertLess(np.linalg.norm(reciprocal), 1.3)
        self.assertLess(np.linalg.cond(atoms.cell.array), 20)
        with tempfile.TemporaryDirectory() as temporary:
            try:
                result = simulate(atoms, self.parameters(euler_rzxz_deg=[0, 0, 0]), Path(temporary), "b" * 32)
            except StructureError as error:
                self.assertRegex(str(error).lower(), "enumerat|completeness|skew|metric")
                return  # Explicitly unqualified library scope is safe.
            self.assertIn([1., 1., 0.], result["reflections"]["hkl"],
                          "Missing in-scope110 must not be returned as a complete generic-cell simulation")


if __name__ == "__main__":
    unittest.main()
