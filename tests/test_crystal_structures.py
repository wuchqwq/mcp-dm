"""Independent fixed CIF examples and refusal tests for the optional ASE adapter."""

import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    from crystallography import structures
finally:
    sys.path.pop(0)


CUBIC_CIF = b"""data_copper_reference
_cell_length_a 3.615
_cell_length_b 3.615
_cell_length_c 3.615
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'F m -3 m'
_symmetry_Int_Tables_number 225
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Cu1 Cu 0 0 0
"""


HEXAGONAL_CIF = b"""data_hexagonal_reference
_cell_length_a 3.2
_cell_length_b 3.2
_cell_length_c 5.4
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 120
_symmetry_space_group_name_H-M 'P 63/m m c'
_symmetry_Int_Tables_number 194
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Mg1 Mg 0.3333333333333333 0.6666666666666667 0.25
"""


def with_parameters(a="3.615", b="3.615", c="3.615", alpha="90", beta="90", gamma="90"):
    text = CUBIC_CIF.decode("ascii")
    for name, original, replacement in (
        ("length_a", "3.615", a), ("length_b", "3.615", b),
        ("length_c", "3.615", c), ("angle_alpha", "90", alpha),
        ("angle_beta", "90", beta), ("angle_gamma", "90", gamma),
    ):
        text = text.replace("_cell_{} {}".format(name, original), "_cell_{} {}".format(name, replacement))
    return text.encode("ascii")


class ReferenceFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "reference.cif"
        self.path.write_bytes(CUBIC_CIF)

    def load(self, path=None, **kwargs):
        options = {"label": "user copper candidate", "centering": "F"}
        options.update(kwargs)
        return structures.load_cubic_reference(self.path if path is None else path, **options)

    def assert_refused_before_parser(self, path=None, **kwargs):
        with mock.patch.object(structures, "_ase_modules") as import_ase:
            with self.assertRaises(structures.CubicReferenceError):
                self.load(path, **kwargs)
            import_ase.assert_not_called()


class FileAndDependencyContractTests(ReferenceFixture, unittest.TestCase):
    def test_optional_dependency_absence_is_clear_and_source_preserved(self):
        with mock.patch.object(structures.importlib, "import_module", side_effect=ModuleNotFoundError("ase")):
            with self.assertRaisesRegex(structures.OptionalDependencyError, "independent.*requirements-crystallography.txt.*GMS"):
                self.load()
        self.assertEqual(self.path.read_bytes(), CUBIC_CIF)

    def test_label_and_explicit_centering_are_required(self):
        for label in ("", " ", None, 3, "x" * 129, "bad\nlabel"):
            with self.subTest(label=label):
                self.assert_refused_before_parser(label=label)
        for centering in (None, "fcc", "f", "R", "", 1):
            with self.subTest(centering=centering):
                self.assert_refused_before_parser(centering=centering)

    def test_model_is_explicit_and_does_not_infer_from_file(self):
        for model in (None, "", "hcp", "HEX", "F", "I", "R", 1):
            with self.subTest(model=model):
                with mock.patch.object(structures, "_ase_modules") as import_ase:
                    with self.assertRaises(structures.StructureReferenceError):
                        structures.load_reference(self.path, label="reference", model=model)
                    import_ase.assert_not_called()

    def test_missing_file_directory_and_wrong_extension_are_rejected(self):
        self.assert_refused_before_parser(Path(self.temp.name) / "missing.cif")
        directory = Path(self.temp.name) / "directory.cif"
        directory.mkdir()
        self.assert_refused_before_parser(directory)
        for suffix in (".txt", ".cif.gz", ".npy"):
            wrong = Path(self.temp.name) / ("wrong" + suffix)
            wrong.write_bytes(CUBIC_CIF)
            self.assert_refused_before_parser(wrong)

    def test_bytes_are_not_a_path_or_guessed_text(self):
        self.assert_refused_before_parser(CUBIC_CIF)
        for payload in (b"", b"\xff\xfe\x00d\x00a\x00t\x00a", b"data_bad\x01", b"data_bad\x7f"):
            with self.subTest(payload=payload):
                self.path.write_bytes(payload)
                self.assert_refused_before_parser()

    def test_oversized_input_is_rejected_before_parser(self):
        self.path.write_bytes(b"#" * (structures.MAX_CIF_BYTES + 1))
        self.assert_refused_before_parser()

    def test_cif2_is_explicitly_unsupported(self):
        self.path.write_bytes(b"#\\#CIF_2.0\n" + CUBIC_CIF)
        self.assert_refused_before_parser()

    def test_importing_module_does_not_import_ase(self):
        filename = ROOT / "crystallography" / "structures.py"
        module_spec = importlib.util.spec_from_file_location("cif_adapter_lazy_import", filename)
        module = importlib.util.module_from_spec(module_spec)
        with mock.patch("importlib.import_module", side_effect=AssertionError("unexpected scientific import")):
            module_spec.loader.exec_module(module)
        self.assertTrue(callable(module.load_cubic_reference))


HAS_ASE = importlib.util.find_spec("ase") is not None


@unittest.skipUnless(HAS_ASE, "external ASE is absent; install requirements-crystallography.txt outside GMS")
class ActualAseCifTests(ReferenceFixture, unittest.TestCase):
    def test_conventional_cubic_reference_preserves_hash_and_units(self):
        result = self.load()
        self.assertAlmostEqual(result["lattice_parameter_nm"], 0.3615, places=13)
        self.assertEqual(result["centering"], "F")
        self.assertEqual(result["reference_kind"], "user_supplied_not_phaseproof")
        self.assertEqual(result["source"]["sha256"], hashlib.sha256(CUBIC_CIF).hexdigest())
        self.assertEqual(result["source"]["size_bytes"], len(CUBIC_CIF))
        self.assertEqual(result["source"]["data_block"], "copper_reference")
        self.assertEqual(result["atom_count"], 4)
        self.assertEqual(result["library"]["name"], "ase")
        self.assertTrue(result["library"]["version"])
        self.assertEqual(result["cell_parameters"]["a_angstrom"], 3.615)
        self.assertEqual(result["cell_parameters"]["gamma_deg"], 90.0)
        self.assertFalse(result["cubic_metric_policy"]["cell_standardized"])
        self.assertFalse(result["cubic_metric_policy"]["symmetry_qualified"])
        self.assertEqual(self.path.read_bytes(), CUBIC_CIF)

    def test_centering_is_user_hypothesis_not_spacegroup_inference(self):
        for centering in ("P", "I", "F"):
            with self.subTest(centering=centering):
                result = self.load(centering=centering)
                self.assertEqual(result["centering"], centering)
                self.assertEqual(result["centering_source"], "explicit_user_hypothesis_not_inferred_from_cif")
                self.assertFalse(result["cubic_metric_policy"]["symmetry_qualified"])

    def test_general_entrypoint_preserves_legacy_cubic_contract(self):
        for model, centering in (("FCC", "F"), ("BCC", "I"), ("P", "P")):
            with self.subTest(model=model):
                new = structures.load_reference(self.path, label="candidate", model=model)
                old = structures.load_cubic_reference(self.path, label="candidate", centering=centering)
                self.assertEqual(new, old)
                self.assertEqual(new["model"], model)
                self.assertEqual(new["lattice_system"], "cubic")

    def test_scalene_and_primitive_rhombohedral_cells_are_refused(self):
        for payload in (
            with_parameters(b="3.7"),
            with_parameters(a="2.556", b="2.556", c="2.556", alpha="60", beta="60", gamma="60"),
            with_parameters(gamma="89.99"),
        ):
            with self.subTest(payload=payload):
                self.path.write_bytes(payload)
                with self.assertRaisesRegex(structures.CubicReferenceError, "conventional cubic"):
                    self.load()
                self.assertEqual(self.path.read_bytes(), payload)

    def test_finite_positive_declared_cell_is_required(self):
        for value in ("nan", "inf", "1e309", "0", "-2", "?", "."):
            with self.subTest(value=value):
                self.path.write_bytes(with_parameters(a=value, b=value, c=value))
                with self.assertRaises(structures.CubicReferenceError):
                    self.load()

    def test_cell_missing_and_nonstructure_data_do_not_pass(self):
        for payload in (
            CUBIC_CIF.replace(b"_cell_angle_beta 90\n", b""),
            b"data_metadata\n_title 'no atomic reference'\n",
            CUBIC_CIF[:CUBIC_CIF.index(b"loop_")],
            b"this is not a cif\n",
        ):
            with self.subTest(payload=payload):
                self.path.write_bytes(payload)
                with self.assertRaises(structures.CubicReferenceError):
                    self.load()

    def test_nonfinite_atomic_coordinates_do_not_qualify_a_reference(self):
        for value in (b"nan", b"inf", b"1e309"):
            with self.subTest(value=value):
                self.path.write_bytes(CUBIC_CIF.replace(b"Cu1 Cu 0 0 0", b"Cu1 Cu " + value + b" 0 0"))
                with self.assertRaises(structures.CubicReferenceError):
                    self.load()

    def test_multiple_blocks_do_not_silently_choose_a_candidate(self):
        self.path.write_bytes(CUBIC_CIF + b"\n" + CUBIC_CIF.replace(b"data_copper_reference", b"data_other"))
        with self.assertRaisesRegex(structures.CubicReferenceError, "exactly one data block"):
            self.load()

    def test_parser_warnings_are_returned_and_not_a_symmetry_pass(self):
        # A genuinely malformed uncertainty token triggers ASE's own warning
        # while still providing a finite numeric lattice parameter.
        payload = with_parameters(a="3.615(2", b="3.615(2", c="3.615(2")
        self.path.write_bytes(payload)
        result = self.load()
        self.assertAlmostEqual(result["lattice_parameter_nm"], 0.3615, places=13)
        self.assertTrue(any("Badly formed number" in item["message"] for item in result["parser_warnings"]))
        self.assertFalse(result["cubic_metric_policy"]["symmetry_qualified"])
        self.assertEqual(self.path.read_bytes(), payload)

    def test_latin1_comment_bytes_are_preserved_not_reencoded(self):
        payload = b"# user supplied caf\xe9 comment\n" + CUBIC_CIF
        self.path.write_bytes(payload)
        result = self.load()
        self.assertEqual(result["source"]["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(self.path.read_bytes(), payload)

    def test_declared_metric_tolerances_are_fixed_and_recorded(self):
        self.path.write_bytes(with_parameters(b="3.615001", gamma="90.000001"))
        result = self.load()
        self.assertEqual(result["cubic_metric_policy"]["length_relative_tolerance"], 1e-6)
        self.assertEqual(result["cubic_metric_policy"]["angle_tolerance_degrees"], 1e-5)
        self.assertEqual(result["cell_parameters"]["b_angstrom"], 3.615001)
        self.assertEqual(result["cell_parameters"]["gamma_deg"], 90.000001)
        self.path.write_bytes(with_parameters(b="3.61501"))
        with self.assertRaises(structures.CubicReferenceError):
            self.load()


@unittest.skipUnless(HAS_ASE, "external ASE is absent; install requirements-crystallography.txt outside GMS")
class ActualAseHexagonalCifTests(ReferenceFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.path.write_bytes(HEXAGONAL_CIF)

    def load_model(self, model="HCP"):
        return structures.load_reference(self.path, label="user hexagonal hypothesis", model=model)

    def test_hexagonal_a_and_c_are_independent_and_exactly_scaled(self):
        result = self.load_model()
        self.assertEqual(result["model"], "HCP")
        self.assertEqual(result["lattice_system"], "hexagonal")
        self.assertAlmostEqual(result["lattice_parameter_a_nm"], 0.32, places=13)
        self.assertAlmostEqual(result["lattice_parameter_c_nm"], 0.54, places=13)
        self.assertAlmostEqual(result["c_over_a"], 1.6875, places=13)
        self.assertNotIn("lattice_parameter_nm", result)
        self.assertEqual(result["cell_parameters"]["gamma_deg"], 120.0)
        self.assertEqual(result["atom_count"], 2)
        self.assertFalse(result["metric_policy"]["basis_qualified"])
        self.assertFalse(result["metric_policy"]["cell_standardized"])
        self.assertIn("not_Miller-Bravais", result["orientation_convention"]["zone_indices"])
        self.assertEqual(result["orientation_convention"]["reciprocal_convention"], "cycles_per_length_no_2pi")
        self.assertEqual(result["source"]["sha256"], hashlib.sha256(HEXAGONAL_CIF).hexdigest())
        self.assertEqual(self.path.read_bytes(), HEXAGONAL_CIF)

    def test_wrong_model_is_not_accepted_or_silently_standardized(self):
        for model in ("FCC", "BCC", "P"):
            with self.subTest(model=model):
                with self.assertRaisesRegex(structures.StructureReferenceError, "conventional cubic"):
                    self.load_model(model)
        self.path.write_bytes(CUBIC_CIF)
        with self.assertRaisesRegex(structures.StructureReferenceError, "conventional hexagonal"):
            self.load_model()

    def test_rhombohedral_acute_gamma_and_unequal_basal_axes_are_refused(self):
        for payload in (
            HEXAGONAL_CIF.replace(b"_cell_angle_alpha 90", b"_cell_angle_alpha 60")
                .replace(b"_cell_angle_beta 90", b"_cell_angle_beta 60")
                .replace(b"_cell_angle_gamma 120", b"_cell_angle_gamma 60"),
            HEXAGONAL_CIF.replace(b"_cell_angle_gamma 120", b"_cell_angle_gamma 60"),
            HEXAGONAL_CIF.replace(b"_cell_length_b 3.2", b"_cell_length_b 3.3"),
            HEXAGONAL_CIF.replace(b"_cell_angle_beta 90", b"_cell_angle_beta 90.01"),
        ):
            with self.subTest(payload=payload):
                self.path.write_bytes(payload)
                with self.assertRaisesRegex(structures.StructureReferenceError, "conventional hexagonal"):
                    self.load_model()
                self.assertEqual(self.path.read_bytes(), payload)

    def test_hexagonal_c_is_finite_and_positive(self):
        for value in (b"nan", b"inf", b"1e309", b"0", b"-2", b"?"):
            with self.subTest(value=value):
                self.path.write_bytes(HEXAGONAL_CIF.replace(b"_cell_length_c 5.4", b"_cell_length_c " + value))
                with self.assertRaises(structures.StructureReferenceError):
                    self.load_model()

    def test_hexagonal_metric_does_not_qualify_a_two_site_hcp_basis(self):
        # One arbitrary P1 site still supplies a metric reference; it must not
        # silently become a qualified HCP structure or extinction model.
        payload = HEXAGONAL_CIF.replace(b"'P 63/m m c'", b"'P 1'").replace(
            b"_symmetry_Int_Tables_number 194", b"_symmetry_Int_Tables_number 1")
        self.path.write_bytes(payload)
        result = self.load_model()
        self.assertEqual(result["atom_count"], 1)
        self.assertFalse(result["metric_policy"]["symmetry_qualified"])
        self.assertFalse(result["metric_policy"]["basis_qualified"])
        self.assertTrue(any("HCP structure-factor extinction" in value for value in result["warnings"]))
        self.assertEqual(result["reference_kind"], "user_supplied_not_phaseproof")

    def test_hexagonal_tolerances_are_fixed_and_recorded(self):
        self.path.write_bytes(HEXAGONAL_CIF.replace(b"_cell_length_b 3.2", b"_cell_length_b 3.200001")
                             .replace(b"_cell_angle_gamma 120", b"_cell_angle_gamma 120.000001"))
        result = self.load_model()
        self.assertEqual(result["hexagonal_metric_policy"]["length_relative_tolerance"], 1e-6)
        self.assertEqual(result["hexagonal_metric_policy"]["angle_tolerance_degrees"], 1e-5)
        self.assertEqual(result["cell_parameters"]["b_angstrom"], 3.200001)


if __name__ == "__main__":
    unittest.main()
