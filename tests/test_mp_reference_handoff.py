"""Local fetched-response format handoff only; no MP service or DM claim."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

HAS_ASE = importlib.util.find_spec("ase") is not None
if HAS_ASE:
    import numpy as np
    from ase import Atoms
    from ase.io import read, write
    _file = Path(__file__).resolve().parents[1] / "skills/materials-project-reference/scripts/save_reference.py"
    _spec = importlib.util.spec_from_file_location("mp_reference_handoff", _file)
    handoff = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(handoff)


@unittest.skipUnless(HAS_ASE, "Optional independent ASE environment is not configured")
class MPReferenceHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mp-reference-test-")
        self.directory = Path(self.temporary.name)
        self.source = self.directory / "fetch.json"
        self.atoms = Atoms("Cu2", scaled_positions=[[0, 0, 0], [.25, .5, .75]],
                           cell=[[3, 0, 0], [1, 4, 0], [.5, -.25, 5]], pbc=True)
        text = io.StringIO()
        write(text, self.atoms, format="vasp", direct=True)
        self.data = {"id": "mp-123", "metadata": {"material_id": "mp-123", "nsites": 2, "poscar": text.getvalue(),
            "atoms": ["Cu", "Cu"], "cell_vectors": self.atoms.cell.array.tolist(),
            "cartesian_coordinates": self.atoms.positions.tolist()}}
        self.save_input()

    def tearDown(self):
        self.temporary.cleanup()

    def save_input(self):
        self.source.write_text(json.dumps(self.data), encoding="utf-8")

    def convert(self, name="output"):
        return handoff.save_reference(str(self.source), str(self.directory / name), "Cu", "2026-10-28T00:00:00Z")

    def test_nonorthogonal_structure_roundtrips_and_enters_existing_structure_tools(self):
        original = self.source.read_bytes()
        result = self.convert()
        self.assertEqual(result["interpretation_status"], "hypothesized")
        self.assertEqual(result["mp_id"], "mp-123")
        self.assertIsNone(result["provider_version"])
        self.assertIsNone(result["structure_version"])
        self.assertEqual(result["files"]["fetch-response.json"]["sha256"], hashlib.sha256(original).hexdigest())
        restored = read(result["structure_path"], format="cif")
        self.assertEqual(restored.get_chemical_symbols(), ["Cu", "Cu"])
        # Independently hand-computable Gram matrix of the declared row vectors.
        np.testing.assert_allclose(restored.cell.array @ restored.cell.array.T,
                                   [[9, 3, 1.5], [3, 17, -.5], [1.5, -.5, 25.3125]], atol=1e-10, rtol=0)
        np.testing.assert_allclose(restored.get_scaled_positions(), [[0, 0, 0], [.25, .5, .75]], atol=1e-10, rtol=0)
        from crystallography.structure_tools import execute
        reply = execute({"action": "open", "workspace": str(self.directory / "structures"),
                         "source_path": result["structure_path"], "request_id": "mp-handoff-open"})
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["result"]["atom_count"], 2)
        self.assertTrue(reply["result"]["has_periodic_3d_cell"])
        self.assertFalse(reply["result"]["phase_identified"])
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(json.loads((self.directory / "output/reference.json").read_text())["state"], "completed")

    def test_existing_output_is_never_overwritten(self):
        self.convert()
        before = {file.name: file.read_bytes() for file in (self.directory / "output").iterdir()}
        with self.assertRaises(FileExistsError):
            self.convert()
        self.assertEqual({file.name: file.read_bytes() for file in (self.directory / "output").iterdir()}, before)

    def test_missing_conflicting_or_oversized_structure_refuses_before_creating_output(self):
        for mutate in (lambda d: d["metadata"].pop("poscar"),
                       lambda d: d["metadata"].update(material_id="mp-999"),
                       lambda d: d["metadata"].update(nsites=3),
                       lambda d: d["metadata"].update(atoms=["Cu", "Ni"]),
                       lambda d: d["metadata"].update(cell_vectors=[[4, 0, 0], [0, 4, 0], [0, 0, 4]]),
                       lambda d: d["metadata"].update(cartesian_coordinates=[[0, 0, 0], [.1, .2, .3]]),
                       lambda d: d["metadata"].update(poscar=d["metadata"]["poscar"].replace("   2", "999999"))):
            data = json.loads(json.dumps(self.data))
            mutate(data)
            self.source.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                self.convert("refused")
            self.assertFalse((self.directory / "refused").exists())

    def test_failed_file_write_cannot_publish_completion_or_replay(self):
        real_write = handoff.write_new
        def fail_structure(file, raw):
            if file.name == "structure.cif":
                raise OSError("injected disk write failure")
            real_write(file, raw)
        with mock.patch.object(handoff, "write_new", side_effect=fail_structure):
            with self.assertRaisesRegex(OSError, "disk write"):
                self.convert()
        self.assertFalse((self.directory / "output/reference.json").exists())
        with self.assertRaises(FileExistsError):
            self.convert()


if __name__ == "__main__":
    unittest.main()
