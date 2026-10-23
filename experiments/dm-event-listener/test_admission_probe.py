import json
import os
from pathlib import Path
import tempfile
import unittest

import admission_probe as probe


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "run"
        self.token = probe.prepare(self.root)["token"]

    def receipt(self, name, instant, pid=123):
        probe.save(self.root / (name + ".json"),
                   dict(token=self.token, pid=pid, thread=1, time=instant))

    def mark(self, name):
        (self.root / (name + ".marker")).write_text(self.token)

    def normal(self):
        for phase, instant in (("idle", 1), ("after", 20)):
            self.receipt(phase + "_entered", instant)
            self.receipt(phase + "_finished", instant + 0.01)
            self.mark(phase + "_before")
            self.mark(phase + "_returned")
        self.receipt("busy_started", 5)
        self.receipt("busy_finished", 15.01)
        self.mark("overlap_before")
        os.utime(str(self.root / "overlap_before.marker"), (5.3, 5.3))

    def test_missing_evidence_unknown(self):
        result = probe.verify(self.root)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertEqual(result["overlap_outcome"], "unknown")

    def test_catch_is_not_global_busy_query(self):
        self.normal()
        self.mark("overlap_caught")
        self.mark("overlap_returned")
        result = probe.verify(self.root)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["overlap_outcome"], "rejected_catchable")
        self.assertTrue(result["global_busy_query"].startswith("NOT_TESTED"))
        self.assertTrue(result["external_wake"].startswith("NOT_TESTED"))

    def test_admission_during_busy_distinguished(self):
        self.normal()
        self.receipt("overlap_entered", 6)
        self.receipt("overlap_finished", 6.1)
        self.mark("overlap_returned")
        self.assertEqual(probe.verify(self.root)["overlap_outcome"], "entered_while_busy")

    def test_deferred_is_not_refused(self):
        self.normal()
        self.receipt("overlap_entered", 16)
        self.receipt("overlap_finished", 16.1)
        self.mark("overlap_returned")
        self.assertEqual(probe.verify(self.root)["overlap_outcome"], "deferred_until_free")

    def test_modal_or_early_return_is_unknown(self):
        self.normal()
        self.mark("overlap_returned")
        self.assertEqual(probe.verify(self.root)["overlap_outcome"], "unknown")

    def test_partial_python_entry_is_unknown(self):
        self.normal()
        self.receipt("overlap_entered", 6)
        self.mark("overlap_returned")
        self.assertEqual(probe.verify(self.root)["overlap_outcome"], "unknown")

    def test_contradictory_rejection_and_execution_is_unknown(self):
        self.normal()
        self.receipt("overlap_entered", 6)
        self.receipt("overlap_finished", 6.1)
        self.mark("overlap_caught")
        self.mark("overlap_returned")
        self.assertEqual(probe.verify(self.root)["overlap_outcome"], "unknown")

    def test_execution_before_attempt_is_unknown(self):
        self.normal()
        self.receipt("overlap_entered", 4)
        self.receipt("overlap_finished", 4.1)
        self.mark("overlap_returned")
        self.assertEqual(probe.verify(self.root)["overlap_outcome"], "unknown")

    def test_native_session_mismatch_rejected(self):
        self.normal()
        (self.root / "idle_before.marker").write_text("other session")
        with self.assertRaises(ValueError):
            probe.verify(self.root)

    def test_python_session_mismatch_rejected(self):
        self.normal()
        p = self.root / "busy_started.json"
        data = json.loads(p.read_text())
        data["token"] = "other session"
        p.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            probe.verify(self.root)

    def test_other_process_cannot_pass(self):
        self.normal()
        p = self.root / "after_entered.json"
        data = json.loads(p.read_text())
        data["pid"] = 456
        p.write_text(json.dumps(data))
        self.mark("overlap_caught")
        self.mark("overlap_returned")
        self.assertEqual(probe.verify(self.root)["status"], "INCOMPLETE")

    def test_no_overwrite(self):
        with self.assertRaises(FileExistsError):
            probe.prepare(self.root)

    def test_attempt_after_busy_ended_cannot_prove_overlap(self):
        self.normal()
        os.utime(str(self.root / "overlap_before.marker"), (16, 16))
        self.mark("overlap_caught")
        self.mark("overlap_returned")
        result = probe.verify(self.root)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertEqual(result["overlap_outcome"], "unknown")

    def test_missing_native_attempt_cannot_pass(self):
        self.normal()
        (self.root / "overlap_before.marker").unlink()
        self.mark("overlap_caught")
        self.mark("overlap_returned")
        self.assertEqual(probe.verify(self.root)["status"], "INCOMPLETE")

    def test_generated_python_compiles_without_dm(self):
        for p in self.root.glob("*.py"):
            compile(p.read_text(), str(p), "exec")
        source = (self.root / "bounded_busy.py").read_text()
        self.assertNotIn("DigitalMicrograph", source)
        self.assertNotIn("while ", source)
        self.assertIn("time.sleep(10)", source)


if __name__ == "__main__":
    unittest.main()
