"""Offline tests for gms-compat compare.

The fixtures are synthetic PE images plus synthetic manifests. Nothing here
loads a vendor module. The invariant under test is that a structural diff can
never turn into a qualification decision.
"""
import copy
import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _path in (os.path.join(_ROOT, "tools", "gms_compat"), _HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import compare  # noqa: E402
import evidence as evidence_module  # noqa: E402
import gms_compat_pe_fixture as fixtures  # noqa: E402
import manifest as manifest_model  # noqa: E402
import pe  # noqa: E402

GET_MEAN = "?GetMean@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z"
SUBSLICE = ("?GetSubSliceAsImage@Image@GMS@@QEBA?AV?$ref_ptr@VImage@GMS@@@Gatan@@"
            "AEBVDataSlice@Imaging@4@@Z")
FIND_BY_ID = "?FindByID@Image@GMS@@SA?AV?$ref_ptr@VImage@GMS@@@Gatan@@K@Z"


class CompareTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = self._directory.name
        self.evidence = evidence_module.Evidence.load()

    def manifest(self, name, **kwargs):
        path = fixtures.write_pe(os.path.join(self.root, name), **kwargs)
        return manifest_model.new_manifest("inspect", {}, [pe.inspect_module(path)])

    def test_identical_build_is_identical_but_not_qualified(self):
        reference = self.manifest("Same.dll", exports=[{"name": "Alpha"},
                                                       {"name": "Beta"}])
        candidate = self.manifest("Same.dll", exports=[{"name": "Alpha"},
                                                       {"name": "Beta"}])
        report = compare.compare(reference, candidate, evidence=self.evidence)
        self.assertEqual(report["modules"][0]["status"], "IDENTICAL")
        self.assertEqual(report["summary"]["identical_modules"], 1)
        self.assertEqual(report["qualification"]["state"], "REFUSED")
        self.assertFalse(report["qualification"]["may_authorize_calls"])
        self.assertEqual(report["high_risk"], [])

    def test_never_emits_a_qualified_state(self):
        reference = self.manifest("A.dll", exports=[{"name": GET_MEAN}])
        candidate = self.manifest("B.dll", exports=[{"name": GET_MEAN}],
                                  stub_padding=32)
        text = manifest_model.dumps(compare.compare(reference, candidate,
                                                    evidence=self.evidence))
        self.assertNotIn('"QUALIFIED_LIMITED"', text)
        self.assertNotIn('"state": "QUALIFIED', text)
        self.assertIn('"state": "REFUSED"', text)

    def test_changed_module_hash_marks_same_named_exports_unknown(self):
        reference = self.manifest("GMSImage.dll", exports=[{"name": FIND_BY_ID}])
        candidate = self.manifest("GMSImage.dll", exports=[{"name": FIND_BY_ID}],
                                  stub_padding=16)
        report = compare.compare(reference, candidate, evidence=self.evidence)
        module = report["modules"][0]
        self.assertEqual(module["status"], "CHANGED")
        self.assertEqual(module["identity"]["sha256"]["equal"], False)
        self.assertEqual(module["exports"]["rva_changed"], 1)
        reasons = [item["reason"] for item in report["abi_unknown"]]
        self.assertTrue(reasons)
        self.assertTrue(any("call shape" in reason for reason in reasons))

    def test_same_name_same_rva_is_still_not_abi_evidence(self):
        reference = self.manifest("Same.dll", exports=[{"name": "Alpha"}])
        candidate = self.manifest("Same.dll", exports=[{"name": "Alpha"}],
                                  file_version=(3, 54, 1, 0))
        report = compare.compare(reference, candidate, evidence=self.evidence)
        module = report["modules"][0]
        self.assertEqual(module["status"], "CHANGED")
        self.assertEqual(module["exports"]["rva_changed"], 0)
        self.assertEqual(len(report["abi_unknown"]), 1)
        self.assertIn("identical export name and RVA", report["abi_unknown"][0]["reason"])

    def test_architecture_change_is_critical(self):
        reference = self.manifest("Arch.dll", machine="x64", exports=[{"name": "A"}])
        candidate = self.manifest("Arch.dll", machine="x86", exports=[{"name": "A"}])
        report = compare.compare(reference, candidate, evidence=self.evidence)
        severities = [item["severity"] for item in report["modules"][0]["assessment"]]
        self.assertIn("CRITICAL", severities)

    def test_module_hash_change_without_export_change_is_reported(self):
        reference = self.manifest("Hash.dll", exports=[{"name": "Alpha"}])
        candidate = self.manifest("Hash.dll", exports=[{"name": "Alpha"}],
                                  imports={"KERNEL32.dll": ["GetLastError"]})
        report = compare.compare(reference, candidate, evidence=self.evidence)
        module = report["modules"][0]
        self.assertEqual(module["identity"]["sha256"]["equal"], False)
        self.assertEqual(module["exports"]["rva_changed"], 0)
        self.assertEqual(module["exports"]["removed"], 0)

    def test_rename_candidate_uses_rva_only_and_says_so(self):
        reference = self.manifest("Rename.dll", exports=[{"name": "OldName"}])
        candidate = self.manifest("Rename.dll", exports=[{"name": "NewName"}])
        report = compare.compare(reference, candidate, evidence=self.evidence)
        module = report["modules"][0]
        self.assertEqual(module["exports"]["removed"], 1)
        self.assertEqual(module["exports"]["added"], 1)
        pairs = module["exports"]["rename_candidates"]
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["removed_name"], "OldName")
        self.assertEqual(pairs[0]["added_name"], "NewName")
        self.assertEqual(pairs[0]["confidence"], "low")
        self.assertFalse(pairs[0]["establishes_equivalent_abi"])

    def test_forwarder_change_is_high_severity(self):
        reference = self.manifest("Fwd.dll", exports=[
            {"name": "Remote", "forward": "OLD.Func"}])
        candidate = self.manifest("Fwd.dll", exports=[
            {"name": "Remote", "forward": "NEW.Func"}])
        report = compare.compare(reference, candidate, evidence=self.evidence)
        module = report["modules"][0]
        self.assertEqual(module["exports"]["forwarder_changed"], 1)
        self.assertEqual(module["exports"]["detail"]["forwarder_changed"][0]["name"],
                         "Remote")
        severities = [item["severity"] for item in module["assessment"]]
        self.assertIn("HIGH", severities)

    def test_missing_and_added_modules(self):
        reference = manifest_model.new_manifest("inspect", {}, [
            manifest_model.normalize_module(self.manifest("A.dll")["modules"][0]),
            manifest_model.normalize_module(self.manifest("B.dll")["modules"][0]),
        ])
        candidate = manifest_model.new_manifest("inspect", {}, [
            manifest_model.normalize_module(self.manifest("B.dll")["modules"][0]),
            manifest_model.normalize_module(self.manifest("C.dll")["modules"][0]),
        ])
        report = compare.compare(reference, candidate, evidence=self.evidence)
        statuses = dict((item["name"], item["status"]) for item in report["modules"])
        self.assertEqual(statuses["A.dll"], "MISSING_IN_CANDIDATE")
        self.assertEqual(statuses["C.dll"], "ADDED_IN_CANDIDATE")
        self.assertEqual(statuses["B.dll"], "IDENTICAL")

    def test_changed_export_maps_to_evidence_and_operations(self):
        reference = self.manifest("GMSImageProcessing.dll",
                                  exports=[{"name": GET_MEAN}])
        candidate = self.manifest("GMSImageProcessing.dll",
                                  exports=[{"name": GET_MEAN}], stub_padding=48)
        report = compare.compare(reference, candidate, evidence=self.evidence)
        self.assertEqual(len(report["high_risk"]), 1)
        entry = report["high_risk"][0]
        self.assertEqual(entry["evidence_entry"], "processing.reductions")
        self.assertIn("call_shape", entry["revalidation"])
        operations = [item["operation"] for item in report["affected_operations"]]
        self.assertIn("native_mean", operations)
        self.assertIn("native_statistics", operations)

    def test_changed_export_without_evidence_is_still_high_risk(self):
        reference = self.manifest("Unknown.dll", exports=[{"name": "?Mystery@X@@YAXXZ"}])
        candidate = self.manifest("Unknown.dll", exports=[{"name": "?Mystery@X@@YAXXZ"}],
                                  stub_padding=8)
        report = compare.compare(reference, candidate, evidence=self.evidence)
        self.assertEqual(report["high_risk"][0]["evidence_entry"], None)
        self.assertIn("no recorded ABI evidence", report["high_risk"][0]["reason"])

    def test_non_export_contracts_require_manual_rederivation(self):
        reference = self.manifest("GMS.dll", exports=[{"name": "Marker"}])
        candidate = self.manifest("GMS.dll", exports=[{"name": "Marker"}],
                                  stub_padding=24)
        report = compare.compare(reference, candidate, evidence=self.evidence)
        entries = set(item["evidence_entry"] for item in report["manual_review"])
        self.assertIn("document.factory_show", entries)
        self.assertIn("roi.geometry", entries)
        for item in report["manual_review"]:
            self.assertIn("RVA does not transfer", item["reason"])

    def test_comparison_is_reproducible(self):
        reference = self.manifest("Rep.dll", exports=[{"name": "A"}, {"name": "B"}])
        candidate = self.manifest("Rep.dll", exports=[{"name": "A"}, {"name": "C"}],
                                  stub_padding=8)
        first = manifest_model.dumps(compare.compare(reference, candidate,
                                                     evidence=self.evidence))
        second = manifest_model.dumps(compare.compare(reference, candidate,
                                                      evidence=self.evidence))
        self.assertEqual(first, second)

    def test_module_filter_limits_the_report(self):
        reference = manifest_model.new_manifest("inspect", {}, [
            manifest_model.normalize_module(self.manifest("A.dll")["modules"][0]),
            manifest_model.normalize_module(self.manifest("B.dll")["modules"][0]),
        ])
        candidate = copy.deepcopy(reference)
        report = compare.compare(reference, candidate, evidence=self.evidence,
                                 module_filter=["a.dll"])
        self.assertEqual([item["name"] for item in report["modules"]], ["A.dll"])

    def test_without_evidence_no_capability_mapping_is_claimed(self):
        reference = self.manifest("GMSImageProcessing.dll", exports=[{"name": GET_MEAN}])
        candidate = self.manifest("GMSImageProcessing.dll", exports=[{"name": GET_MEAN}],
                                  stub_padding=16)
        report = compare.compare(reference, candidate)
        self.assertEqual(report["high_risk"], [])
        self.assertEqual(report["affected_operations"], [])
        self.assertEqual(report["qualification"]["state"], "REFUSED")


class CompareCliTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = self._directory.name

    def write_manifest(self, name, exports, label="ref", **kwargs):
        staging = os.path.join(self.root, label)
        if not os.path.isdir(staging):
            os.makedirs(staging)
        path = fixtures.write_pe(os.path.join(staging, name), exports=exports, **kwargs)
        document = manifest_model.new_manifest("inspect", {},
                                               [pe.inspect_module(path)])
        target = os.path.join(self.root, label + ".json")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(manifest_model.dumps(document))
        return target

    def run_cli(self, argv):
        from io import StringIO
        from contextlib import redirect_stdout, redirect_stderr
        import cli
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_cli_compare_writes_a_report(self):
        reference = self.write_manifest("Cmp.dll", [{"name": "Alpha"}], label="ref")
        candidate = self.write_manifest("Cmp.dll", [{"name": "Beta"}], label="cand")
        code, out, _ = self.run_cli(["compare", reference, candidate])
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertEqual(report["summary"]["changed_modules"], 1)
        self.assertEqual(report["qualification"]["state"], "REFUSED")

    def test_cli_fail_on_change_exit_code(self):
        reference = self.write_manifest("Cmp.dll", [{"name": "Alpha"}], label="ref")
        candidate = self.write_manifest("Cmp.dll", [{"name": "Beta"}], label="cand")
        code, _, _ = self.run_cli(["compare", "--fail-on-change", reference, candidate])
        self.assertEqual(code, 1)

    def test_cli_rejects_a_malformed_manifest(self):
        broken = os.path.join(self.root, "broken.json")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("{\"schema\": \"wrong\"}")
        good = self.write_manifest("Ok.dll", [{"name": "Alpha"}], label="ok")
        code, _, err = self.run_cli(["compare", good, broken])
        self.assertEqual(code, 2)
        self.assertIn("manifest_schema_mismatch", err)

    def test_cli_rejects_a_bad_hash(self):
        good = self.write_manifest("Ok.dll", [{"name": "Alpha"}], label="ok")
        with open(good, encoding="utf-8") as handle:
            document = json.load(handle)
        document["modules"][0]["sha256"] = "not-a-hash"
        broken = os.path.join(self.root, "badhash.json")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write(manifest_model.dumps(document))
        code, _, err = self.run_cli(["compare", good, broken])
        self.assertEqual(code, 2)
        self.assertIn("manifest_module_hash_invalid", err)


if __name__ == "__main__":
    unittest.main()
