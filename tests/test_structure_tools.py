"""External ASE/diffsims synthetic acceptance; never DM or private data."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

HAS_ASE = importlib.util.find_spec("ase") is not None
HAS_DIFFSIMS = importlib.util.find_spec("diffsims") is not None
if HAS_ASE:
    import numpy as np
    from ase import Atoms
    from ase.build import bulk
    from ase.io import write
    from crystallography.structure_tools import execute, canonical, StructureWorkspace, raster_geometry


@unittest.skipUnless(HAS_ASE, "Optional external ASE environment is not configured")
class StructureToolsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dm-structure-test-")
        self.directory = Path(self.temporary.name)
        self.workspace = self.directory / "workspace"
        self.number = 0

    def tearDown(self):
        self.temporary.cleanup()

    def call(self, action, **arguments):
        self.number += 1
        payload = {"workspace": str(self.workspace), "action": action, **arguments}
        if action not in ("get", "result"):
            payload.setdefault("request_id", "request-{}".format(self.number))
        reply = execute(payload)
        self.assertTrue(reply.get("ok"), reply)
        return reply["result"]

    def xyz(self):
        file = self.directory / "molecule.xyz"
        file.write_text("4\nSynthetic geometry, Cartesian Angstrom\nC 0 0 0\nC 1 0 0\nO 1 1 0\nH 1 1 1\n", encoding="utf-8")
        return file

    def cif(self, atoms, name="structure"):
        file = self.directory / (name + ".cif")
        write(file, atoms, format="cif")
        return file

    def test_cell_free_xyz_is_a_valid_immutable_view_and_atomic_geometry(self):
        file = self.xyz()
        original = file.read_bytes()
        opened = self.call("open", source_path=str(file))
        self.assertEqual(opened["cell_rank"], 0)
        self.assertFalse(opened["has_periodic_3d_cell"])
        self.assertIn("ASE XYZ/extXYZ Angstrom convention", opened["source"]["coordinate_unit_convention"])
        self.assertIn("not independently verified", opened["source"]["coordinate_unit_convention"])
        info = self.call("get", object_id=opened["object_id"], include_atoms=True)
        self.assertEqual(info["atoms"]["positions_angstrom"], [[0, 0, 0], [1, 0, 0], [1, 1, 0], [1, 1, 1]])
        for kind, ids, expected in (("distance", [0, 1], 1.), ("angle", [0, 1, 2], 90.), ("dihedral", [0, 1, 2, 3], 90.)):
            result = self.call("measure", object_id=opened["object_id"], kind=kind, atom_indices=ids)
            self.assertAlmostEqual(result["measurement"]["value"], expected)
        view = self.call("view", object_id=opened["object_id"], rotation_deg_xyz=[10, 20, 0], max_size=256)
        self.assertEqual(Path(view["image_path"]).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertTrue(view["projection_only"])
        self.assertEqual(self.call("get", object_id=view["object_id"], include_atoms=True)["atoms"], info["atoms"])
        self.assertEqual(file.read_bytes(), original)

    def test_generic_triclinic_metric_and_signed_basis_are_not_forced_into_cubic_models(self):
        cell = [[3., 0, 0], [1., 4., 0], [.5, .25, 5.]]
        atoms = Atoms("SiO", scaled_positions=[[0, 0, 0], [.5, .25, .2]], cell=cell, pbc=True)
        file = self.cif(atoms)
        opened = self.call("open", source_path=str(file))
        np.testing.assert_allclose(opened["cell_angstrom"], cell, atol=1e-13)
        self.assertFalse(opened["cell_standardized"])
        measured = self.call("measure", object_id=opened["object_id"], kind="d_spacing", hkls=[[1, 0, 0]])["measurement"]
        # Independently solved a_i dot g_100 = delta_i1:
        # g_100 = (80,-20,-7)/240, so d100=240/sqrt(6849).
        self.assertAlmostEqual(measured["value"], 240. / math.sqrt(6849.))
        np.testing.assert_allclose(measured["reciprocal_vectors_inv_angstrom"][0], [80/240, -20/240, -7/240], atol=1e-14)
        angle = self.call("measure", object_id=opened["object_id"], kind="reciprocal_angle", hkls=[[1, 0, 0], [0, 1, 0]])["measurement"]
        u, v = [80., -20., -7.], [0., 20., -1.]
        expected = math.degrees(math.acos(sum(x*y for x,y in zip(u,v))/math.sqrt(sum(x*x for x in u)*sum(x*x for x in v))))
        self.assertAlmostEqual(angle["value"], expected)
        self.assertFalse(angle["phase_identified"])

    def test_readable_tiny_full_rank_cell_cannot_return_zero_spacing_or_invalid_angles(self):
        file = self.directory / "tiny-cell.xyz"
        file.write_text('2\nLattice="1e-200 0 0 0 1e-200 0 0 0 1e-200" '
                        'Properties=species:S:1:pos:R:3 pbc="T T T"\nC 0 0 0\nC 1 0 0\n', encoding="utf-8")
        source = file.read_bytes()
        opened = self.call("open", source_path=str(file))
        self.assertEqual(opened["cell_rank"], 3)
        # Reading raw finite geometry and ordinary Cartesian atomic distance
        # remain valid. Reciprocal components are finite1e200, but their norm
        # overflows; this must be refusal rather than successful d=0 Angstrom.
        info = self.call("get", object_id=opened["object_id"], include_atoms=True)
        self.assertEqual(info["atoms"]["cell_angstrom"][0][0], 1e-200)
        distance = self.call("measure", object_id=opened["object_id"], kind="distance", atom_indices=[0, 1])
        self.assertEqual(distance["measurement"]["value"], 1.)
        cases = [{"kind": "d_spacing", "hkls": [[1, 0, 0]]},
                 {"kind": "reciprocal_angle", "hkls": [[1, 0, 0], [0, 1, 0]]},
                 {"kind": "direction_angle", "directions": [[1, 0, 0], [0, 1, 0]]},
                 {"kind": "zone_relation", "hkls": [[1, 0, 0]], "directions": [[0, 1, 0]]}]
        for index, parameters in enumerate(cases):
            with self.subTest(kind=parameters["kind"]), np.errstate(over="ignore", under="ignore", invalid="ignore"):
                result = execute({"workspace": str(self.workspace), "action": "measure", "object_id": opened["object_id"],
                                  "request_id": "tiny-cell-{}".format(index), **parameters})
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["state"], "failed")
                self.assertNotIn("measurement", result)
                self.assertRegex(result["error"]["message"], "finite|nonzero|overflow|underflow")
        self.assertEqual(file.read_bytes(), source)

    def test_repeat_and_rotation_create_new_ase_snapshot_without_source_changes(self):
        file = self.cif(Atoms("C", positions=[[1, 0, 0]], cell=[3, 4, 5], pbc=True))
        before = file.read_bytes()
        opened = self.call("open", source_path=str(file))
        derived = self.call("derive", object_id=opened["object_id"], repeat=[2, 1, 1], rotation_deg_xyz=[0, 0, 90])
        self.assertEqual(derived["atom_count"], 2)
        atoms = self.call("get", object_id=derived["object_id"], include_atoms=True)["atoms"]
        np.testing.assert_allclose(atoms["positions_angstrom"], [[0, 1, 0], [0, 4, 0]], atol=1e-13)
        self.assertEqual(self.call("get", object_id=opened["object_id"])["atom_count"], 1)
        self.assertEqual(file.read_bytes(), before)
        failure = execute({"workspace": str(self.workspace), "action": "derive", "object_id": opened["object_id"], "repeat": [32, 32, 32], "request_id": "oversize"})
        self.assertFalse(failure["ok"])
        self.assertEqual(failure["error"]["code"], "BUDGET_EXCEEDED")

    def test_direct_direction_angle_and_zone_law_use_the_actual_triclinic_cell(self):
        atoms = Atoms("Si", positions=[[0, 0, 0]], cell=[[3, 0, 0], [1, 4, 0], [.5, .25, 5]], pbc=True)
        opened = self.call("open", source_path=str(self.cif(atoms)))
        measured = self.call("measure", object_id=opened["object_id"], kind="direction_angle", directions=[[1, 0, 0], [0, 1, 0]])["measurement"]
        self.assertAlmostEqual(measured["value"], math.degrees(math.atan2(4, 1)))
        np.testing.assert_allclose(measured["direct_vectors_angstrom"], [[3, 0, 0], [1, 4, 0]], atol=1e-13)
        zone = self.call("measure", object_id=opened["object_id"], kind="zone_relation", hkls=[[1, 0, 0]], directions=[[0, 1, 0]])["measurement"]
        self.assertEqual(zone["zone_law_hu_kv_lw"], 0); self.assertTrue(zone["plane_contains_direction"])
        self.assertAlmostEqual(zone["acute_angle_to_plane_degrees"], 0, places=12)
        crossing = self.call("measure", object_id=opened["object_id"], kind="zone_relation", hkls=[[1, 0, 0]], directions=[[1, 0, 0]])["measurement"]
        self.assertEqual(crossing["zone_law_hu_kv_lw"], 1); self.assertFalse(crossing["plane_contains_direction"])
        normal_angle = math.degrees(math.acos(80 / math.sqrt(6849)))
        self.assertAlmostEqual(crossing["angle_to_plane_normal_degrees"], normal_angle)
        xyz = self.call("open", source_path=str(self.xyz()))
        for index, changes in enumerate(({"object_id": opened["object_id"], "directions": [[0, 0, 0], [1, 0, 0]]},
                                         {"object_id": xyz["object_id"], "directions": [[1, 0, 0], [0, 1, 0]]})):
            failed = execute({"workspace": str(self.workspace), "action": "measure", "kind": "direction_angle", "request_id": "bad-direction{}".format(index), **changes})
            self.assertFalse(failed["ok"])

    def test_minimum_image_is_explicit_and_never_fabricated_for_cell_free_xyz(self):
        opened = self.call("open", source_path=str(self.cif(Atoms("CC", positions=[[.2, 0, 0], [9.8, 0, 0]], cell=[10, 10, 10], pbc=True))))
        direct = self.call("measure", object_id=opened["object_id"], kind="distance", atom_indices=[0, 1])["measurement"]
        minimum = self.call("measure", object_id=opened["object_id"], kind="distance", atom_indices=[0, 1], mic=True)["measurement"]
        self.assertAlmostEqual(direct["value"], 9.6); self.assertFalse(direct["minimum_image"])
        self.assertAlmostEqual(minimum["value"], .4); self.assertTrue(minimum["minimum_image"])
        xyz = self.call("open", source_path=str(self.xyz()))
        failed = execute({"workspace": str(self.workspace), "action": "measure", "object_id": xyz["object_id"], "kind": "distance", "atom_indices": [0, 1], "mic": True, "request_id": "unknown-cell-mic"})
        self.assertFalse(failed["ok"])
        self.assertIn("periodic cell", failed["error"]["message"])

    def test_write_identity_conflict_corruption_and_incomplete_records_never_pass(self):
        file = self.xyz()
        missing = execute({"workspace": str(self.workspace), "action": "open", "source_path": str(file)})
        self.assertFalse(missing["ok"])
        self.assertFalse(self.workspace.exists())
        opened = self.call("open", source_path=str(file), request_id="saved")
        again = self.call("open", source_path=str(file), request_id="saved")
        self.assertEqual(opened["object_id"], again["object_id"])
        bad = execute({"workspace": str(self.workspace), "action": "open", "source_path": str(self.directory / "else.xyz"), "request_id": "saved"})
        self.assertEqual(bad["error"]["code"], "REQUEST_CONFLICT")
        self.assertEqual(len(list((self.workspace / "objects").iterdir())), 1)
        incomplete = {"schema_version": 1, "request_id": "pending", "state": "prepared"}
        (self.workspace / "requests" / "pending.json").write_bytes(canonical(incomplete))
        queried = execute({"workspace": str(self.workspace), "action": "result", "query_request_id": "pending"})
        self.assertEqual(queried["state"], "unknown")
        self.assertFalse(queried["automatic_retry"])
        atoms = Path(opened["manifest_path"]).parent / "atoms.json"
        atoms.write_bytes(atoms.read_bytes().replace(b'"C"', b'"H"', 1))
        for action, kwargs in (("get", {"object_id": opened["object_id"]}), ("result", {"query_request_id": "saved"})):
            failed = execute({"workspace": str(self.workspace), "action": action, **kwargs})
            self.assertFalse(failed["ok"])
            self.assertEqual(failed["error"]["code"], "CORRUPT_OBJECT")

    def test_foreign_workspace_self_consistent_records_do_not_qualify_current_namespace(self):
        opened = self.call("open", source_path=str(self.xyz()), request_id="original-workspace")
        foreign = self.directory / "copied-workspace"
        shutil.copytree(self.workspace, foreign)
        failed = execute({"workspace": str(foreign), "action": "get", "object_id": opened["object_id"]})
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["error"]["code"], "CORRUPT_OBJECT")

    def test_xyz_multiple_configs_or_oversized_counts_and_cif_symmetry_are_bounded_before_atom_construction(self):
        for index, text in enumerate(("999999999\nLarge\n", "1\nOne\nC 0 0 0\n1\nTwo\nO 0 0 0\n")):
            file = self.directory / ("bad{}.xyz".format(index)); file.write_text(text)
            with mock.patch("crystallography.structure_tools.ase_read") as reader:
                failed = execute({"workspace": str(self.workspace), "action": "open", "source_path": str(file), "request_id": "bad-{}".format(index)})
                self.assertFalse(failed["ok"]); reader.assert_not_called()
        file = self.directory / "huge-symmetry.cif"
        file.write_text("data_test\n_cell_length_a 4\n_cell_length_b 4\n_cell_length_c 4\n_cell_angle_alpha 90\n_cell_angle_beta 90\n_cell_angle_gamma 90\n_space_group_IT_number 225\nloop_\n_atom_site_label\n_atom_site_type_symbol\n_atom_site_fract_x\n_atom_site_fract_y\n_atom_site_fract_z\n" + "".join("C{} C {} 0 0\n".format(i, i/30) for i in range(22)))
        with mock.patch("crystallography.structure_tools.ase_read") as reader:
            failed = execute({"workspace": str(self.workspace), "action": "open", "source_path": str(file), "request_id": "cif-budget"})
            self.assertEqual(failed["error"]["code"], "BUDGET_EXCEEDED"); reader.assert_not_called()

    @unittest.skipUnless(HAS_DIFFSIMS, "Optional diffsims environment is not configured")
    def test_missing_cell_bad_parameters_and_work_budget_never_enter_simulator(self):
        xyz = self.call("open", source_path=str(self.xyz()))
        periodic = self.call("open", source_path=str(self.cif(bulk("Cu", "fcc", a=3.6, cubic=True))))
        base = {"workspace": str(self.workspace), "action": "simulate", "voltage_kv": 200, "euler_rzxz_deg": [0, 0, 0],
                "reciprocal_radius_inv_angstrom": 1.3, "max_excitation_error_inv_angstrom": .02, "size": 128}
        with mock.patch("diffsims.generators.diffraction_generator.DiffractionGenerator") as generator:
            for index, changes in enumerate(({"object_id": xyz["object_id"]}, {"object_id": periodic["object_id"], "voltage_kv": 0},
                                             {"object_id": periodic["object_id"], "native_float32": True, "size": 256})):
                failed = execute({**base, **changes, "request_id": "invalid-sim{}".format(index)})
                self.assertFalse(failed["ok"], failed)
            generator.assert_not_called()
        self.assertEqual(self.call("get", object_id=xyz["object_id"])["cell_rank"], 0)

    @unittest.skipUnless(HAS_DIFFSIMS, "Optional diffsims environment is not configured")
    def test_partial_occupancy_remains_inspectable_but_cannot_become_a_full_occupancy_simulation(self):
        file = self.directory / "partial.cif"
        file.write_text("data_partial\n_cell_length_a 4\n_cell_length_b 4\n_cell_length_c 4\n_cell_angle_alpha 90\n_cell_angle_beta 90\n_cell_angle_gamma 90\n_space_group_IT_number 1\nloop_\n_atom_site_label\n_atom_site_type_symbol\n_atom_site_fract_x\n_atom_site_fract_y\n_atom_site_fract_z\n_atom_site_occupancy\nCu1 Cu 0 0 0 .5\n")
        before = file.read_bytes(); opened = self.call("open", source_path=str(file))
        self.assertEqual(self.call("get", object_id=opened["object_id"], include_atoms=True)["atoms"]["occupancy"]["0"]["Cu"], .5)
        with mock.patch("diffsims.generators.diffraction_generator.DiffractionGenerator") as generator:
            failed = execute({"workspace": str(self.workspace), "action": "simulate", "object_id": opened["object_id"],
                              "request_id": "partial", "voltage_kv": 200, "euler_rzxz_deg": [0, 0, 0], "reciprocal_radius_inv_angstrom": 1.,
                              "max_excitation_error_inv_angstrom": .02})
            self.assertFalse(failed["ok"]); self.assertIn("occupancy", failed["error"]["message"]); generator.assert_not_called()
        self.assertEqual(file.read_bytes(), before)

    @unittest.skipUnless(HAS_DIFFSIMS, "Optional diffsims environment is not configured")
    def test_actual_fcc_bcc_hcp_and_triclinic_simulations_obey_metrics_and_centering_without_phase_claims(self):
        variants = (("fcc", bulk("Cu", "fcc", a=3.6, cubic=True)), ("bcc", bulk("Fe", "bcc", a=2.87, cubic=True)),
                    ("hcp", bulk("Ti", "hcp", a=2.95, c=4.68)),
                    ("triclinic", Atoms("Si", scaled_positions=[[0, 0, 0]], cell=[[3, 0, 0], [1, 4, 0], [.5, .25, 5]], pbc=True)))
        for name, atoms in variants:
            with self.subTest(name=name):
                file = self.cif(atoms, name); original = file.read_bytes()
                opened = self.call("open", source_path=str(file))
                result = self.call("simulate", object_id=opened["object_id"], voltage_kv=200, euler_rzxz_deg=[0, 0, 0],
                                   reciprocal_radius_inv_angstrom=1.3, max_excitation_error_inv_angstrom=.1, size=128)
                self.assertGreater(result["reflection_count"], 0)
                self.assertFalse(result["dm_called"])
                self.assertFalse(result["phase_identified"])
                hkls = np.asarray(result["reflections"]["hkl"], dtype=int)
                if name == "fcc":
                    self.assertTrue(np.all(np.mod(hkls, 2) == np.mod(hkls[:, :1], 2)))
                if name == "bcc":
                    self.assertTrue(np.all(np.mod(hkls.sum(axis=1), 2) == 0))
                coordinates = np.asarray(result["reflections"]["coordinates_inv_angstrom"])
                reference = hkls @ np.linalg.inv(atoms.cell.array).T
                np.testing.assert_allclose(coordinates, reference, atol=1e-12)
                self.assertEqual(file.read_bytes(), original)

    @unittest.skipUnless(HAS_DIFFSIMS, "Optional diffsims environment is not configured")
    def test_asymmetric_nonzero_orientation_and_qualitative_raster_coordinate_convergence(self):
        opened = self.call("open", source_path=str(self.cif(bulk("Cu", "fcc", a=3.6, cubic=True))))
        base = {"object_id": opened["object_id"], "voltage_kv": 200, "euler_rzxz_deg": [0, 0, 17],
                "reciprocal_radius_inv_angstrom": 1.3, "max_excitation_error_inv_angstrom": .02}
        angled = self.call("simulate", **base, size=128, sigma_pixels=.2)
        hkls = np.asarray(angled["reflections"]["hkl"])
        index = np.flatnonzero(np.all(hkls == [2, 0, 0], axis=1)).item()
        theta = math.radians(17)
        expected = np.array([2/3.6 * math.cos(theta), 2/3.6 * math.sin(theta), 0.])
        np.testing.assert_allclose(angled["reflections"]["coordinates_inv_angstrom"][index], expected, atol=1e-12)
        continuous = expected[:2] / (2.6/128) + 64
        np.testing.assert_allclose(angled["rasterization"]["continuous_center_xy_pixels"][index], continuous, atol=1e-12)
        inside_index = angled["rasterization"]["in_frame_reflection_indices"].index(index)
        col, row = np.floor(continuous).astype(int)
        self.assertEqual(angled["rasterization"]["integer_center_row_col"][inside_index], [row, col])
        raster = np.load(angled["array_path"], allow_pickle=False)
        self.assertGreater(raster[row, col], raster[col, row], "asymmetric orientation exposes XY transpose errors")
        local = raster[row-1:row+2, col-1:col+2]
        self.assertEqual(np.argmax(local), 4, "library Gaussian is centred on the quantized integer pixel")
        prior = None
        for size in (64, 128, 256):
            result = self.call("simulate", **base, size=size, sigma_pixels=size/64)
            self.assertEqual(result["reflections"], angled["reflections"])
            geometry = result["rasterization"]
            self.assertAlmostEqual(geometry["sigma_inv_angstrom"], 2.6/64)
            self.assertLess(geometry["maximum_center_quantization_error_inv_angstrom"], 2.6/size)
            if prior is not None:
                self.assertLessEqual(geometry["maximum_center_quantization_error_inv_angstrom"], prior + 1e-12)
            prior = geometry["maximum_center_quantization_error_inv_angstrom"]
        cutoff = self.call("simulate", **{**base, "reciprocal_radius_inv_angstrom": 1.}, size=128)
        full = {tuple(h): (c, i) for h,c,i in zip(angled["reflections"]["hkl"], angled["reflections"]["coordinates_inv_angstrom"], angled["reflections"]["kinematic_intensity"])}
        for h,c,i in zip(cutoff["reflections"]["hkl"], cutoff["reflections"]["coordinates_inv_angstrom"], cutoff["reflections"]["kinematic_intensity"]):
            reference_coords, reference_intensity = full[tuple(h)]
            np.testing.assert_allclose(c, reference_coords, atol=1e-12)
            self.assertAlmostEqual(i, reference_intensity, places=12)

    @unittest.skipUnless(HAS_DIFFSIMS, "Optional diffsims environment is not configured")
    def test_library_raster_collision_is_reported_and_never_disguised_as_summed_scientific_intensity(self):
        from diffsims.sims.diffraction_simulation import DiffractionSimulation
        # A geometric fixture for the actual library rasterizer, not a claimed
        # scattering calculation: first two spots share one integer centre.
        simulation = DiffractionSimulation(coordinates=np.array([[.103, .147, 0], [.105, .148, 0], [-.183, .087, 0]]),
                                          indices=np.array([[1, 0, 0], [1, 1, 0], [0, 1, 0]]), intensities=np.array([100., 2., 4.]), with_direct_beam=False)
        simulation.calibration = .01
        geometry = raster_geometry(simulation, 64, .01, .2)
        self.assertEqual(geometry["cumulative_collision_count"], 1)
        self.assertEqual(geometry["colliding_integer_center_count"], 1)
        self.assertEqual(geometry["unique_integer_center_count"], 2)
        self.assertEqual(geometry["integer_center_row_col"], [[46, 42], [46, 42], [40, 13]])
        raster = simulation.get_diffraction_pattern(shape=(64, 64), sigma=.2)
        self.assertAlmostEqual(raster[46, 42] / raster[40, 13], .5, places=12)
        self.assertIn("does not sum", geometry["coincident_center_policy"])

    @unittest.skipUnless(HAS_DIFFSIMS, "Optional diffsims environment is not configured")
    def test_scientific_capture_and_explicit_float32_conversion_reopen_and_import_without_precision_disguise(self):
        opened = self.call("open", source_path=str(self.cif(bulk("Cu", "fcc", a=3.6, cubic=True))))
        result = self.call("simulate", object_id=opened["object_id"], voltage_kv=200, euler_rzxz_deg=[0, 0, 0],
                           reciprocal_radius_inv_angstrom=1.3, max_excitation_error_inv_angstrom=.02, size=128, native_float32=True)
        raw = np.load(result["array_path"], allow_pickle=False)
        converted = np.load(result["native_float32_path"], allow_pickle=False)
        self.assertEqual(raw.dtype, np.float64); self.assertEqual(converted.dtype, np.float32)
        self.assertEqual(raw.shape, (128, 128)); self.assertTrue(np.isfinite(raw).all())
        np.testing.assert_array_equal(converted, raw.astype(np.float32))
        conversion = result["native_float32_conversion"]
        self.assertEqual(conversion["source_float64_npy_sha256"], hashlib.sha256(Path(result["array_path"]).read_bytes()).hexdigest())
        self.assertEqual(conversion["maximum_absolute_error"], float(np.abs(converted.astype(np.float64)-raw).max()))
        self.assertLessEqual(conversion["maximum_absolute_error"], 3e-8)
        self.assertEqual(conversion["calibration_xy"][0]["origin"], 64.)
        self.assertAlmostEqual(conversion["calibration_xy"][0]["physical_pixel_zero"], -1.3)
        from tools.image_workspace import execute as image_execute
        imported = image_execute({"workspace": str(self.directory / "image-workspace"), "action": "import_capture",
                                  "source_path": result["capture_path"], "request_id": "explicit-import"})
        self.assertTrue(imported["ok"], imported)
        np.testing.assert_array_equal(np.load(imported["result"]["array_path"], allow_pickle=False), raw)
        self.assertEqual(imported["result"]["array_domain"], "frequency")
        upstream = json.loads((Path(imported["result"]["manifest_path"]).parent / "upstream-metadata.json").read_text())
        provenance = upstream["input"]["external_provenance"]
        self.assertEqual(provenance["effective_parameters"]["sigma_pixels"], 1.)
        self.assertEqual(provenance["effective_parameters"]["scattering_params"], "lobato")
        self.assertEqual(conversion["external_provenance"]["rasterization"], result["rasterization"])
        self.assertEqual(provenance["rasterization"]["sigma_pixels"], 1.)
        self.assertEqual(provenance["structure_snapshot"]["symbols"], ["Cu"] * 4)
        self.assertEqual(hashlib.sha256(canonical(provenance["structure_snapshot"])).hexdigest(), provenance["structure_snapshot_sha256"])
        self.assertFalse(result["display_recipe"]["scientific_raster_modified"])
        queried = self.call("result", query_request_id=result["request_id"])
        self.assertEqual(queried["object_id"], result["object_id"])

    @unittest.skipUnless(HAS_DIFFSIMS, "Optional diffsims environment is not configured")
    def test_export_contains_fixed_source_parser_and_derivation_chain_after_original_is_deleted(self):
        file = self.cif(bulk("Cu", "fcc", a=3.6, cubic=True))
        raw = file.read_bytes()
        opened = self.call("open", source_path=str(file))
        first = self.call("derive", object_id=opened["object_id"], repeat=[2, 1, 1], rotation_deg_xyz=[0, 0, 17])
        second = self.call("derive", object_id=first["object_id"], repeat=[1, 1, 1], rotation_deg_xyz=[0, 0, 11])
        file.unlink()
        result = self.call("simulate", object_id=second["object_id"], voltage_kv=200, euler_rzxz_deg=[0, 0, 0],
                           reciprocal_radius_inv_angstrom=1.3, max_excitation_error_inv_angstrom=.02, size=64, native_float32=True)
        info = json.loads((Path(result["capture_path"]) / "input.json").read_text())
        provenance = info["external_provenance"]["source_provenance"]
        self.assertEqual(provenance["source"]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(provenance["source_object_id"], opened["object_id"])
        self.assertEqual(provenance["parser"]["library"], "ASE")
        self.assertEqual(provenance["parser"]["format"], "cif")
        self.assertEqual(provenance["parser"]["warnings"], opened["parser_warnings"])
        self.assertFalse(provenance["original_source_reread"])
        chain = provenance["derivation_chain"]
        self.assertEqual([link["object_id"] for link in chain], [first["object_id"], second["object_id"]])
        self.assertEqual([link["rotation_deg_xyz"] for link in chain], [[0., 0., 17.], [0., 0., 11.]])
        self.assertEqual(chain[0]["repeat"], [2, 1, 1])
        self.assertEqual(result["native_float32_conversion"]["external_provenance"]["source_provenance"], provenance)
        for link in chain:
            self.assertEqual(len(link["atoms_json_sha256"]), 64)
            self.assertEqual(len(link["software_provenance"]["module_sha256"]), 64)

    @unittest.skipUnless(HAS_DIFFSIMS, "Optional diffsims environment is not configured")
    def test_simulation_provenance_distinguishes_input_reference_from_resolved_derived_structure(self):
        opened = self.call("open", source_path=str(self.cif(bulk("Cu", "fcc", a=3.6, cubic=True))))
        derived = self.call("derive", object_id=opened["object_id"], rotation_deg_xyz=[0, 0, 17])
        view = self.call("view", object_id=derived["object_id"], max_size=128)
        measured = self.call("measure", object_id=view["object_id"], kind="d_spacing", hkls=[[1, 0, 0]])
        inputs = [view["object_id"], measured["object_id"]]
        for reference in inputs:
            with self.subTest(reference=reference):
                result = self.call("simulate", object_id=reference, voltage_kv=200, euler_rzxz_deg=[0, 0, 0],
                                   reciprocal_radius_inv_angstrom=1.3, max_excitation_error_inv_angstrom=.02, size=64,
                                   native_float32=True)
                self.assertEqual(result["parent_object_id"], reference)
                self.assertEqual(result["structure_object_id"], derived["object_id"])
                info = json.loads((Path(result["capture_path"]) / "input.json").read_text())
                provenance = info["external_provenance"]
                self.assertEqual(provenance["input_object_id"], reference)
                self.assertEqual(provenance["structure_object_id"], derived["object_id"])
                self.assertNotEqual(provenance["structure_object_id"], opened["object_id"])
                self.assertEqual(provenance["source_provenance"]["source_object_id"], opened["object_id"])
                self.assertEqual(result["native_float32_conversion"]["external_provenance"], provenance)
                # A previous simulation is also a valid reference to its exact
                # atomic snapshot; it is not itself an atomic-structure ID.
                if len(inputs) == 2:
                    inputs.append(result["object_id"])


if __name__ == "__main__":
    unittest.main()
