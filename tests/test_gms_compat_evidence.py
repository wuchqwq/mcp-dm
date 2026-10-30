"""Offline tests for the ABI evidence inventory and its qualification gates.

The point of these tests is negative coverage: the validator must refuse every
attempt to promote an entry without the evidence that its state demands.
"""
import copy
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _path in (os.path.join(_ROOT, "tools", "gms_compat"), _HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import evidence as evidence_module  # noqa: E402


def codes(issues):
    return [issue["code"] for issue in issues]


class ShippedInventoryTests(unittest.TestCase):
    def setUp(self):
        self.evidence = evidence_module.Evidence.load()

    def test_inventory_is_valid(self):
        self.assertEqual(evidence_module.validate(self.evidence), [])

    def test_pinned_identity_matches_the_runtime_gate(self):
        self.assertEqual(evidence_module.cross_check_profile(self.evidence), [])

    def test_every_entry_declares_a_qualification_and_a_derivation(self):
        for entry in self.evidence.entries:
            self.assertIn(entry["qualification"], evidence_module.QUALIFICATIONS)
            self.assertIn(entry["derivation"], evidence_module.DERIVATIONS)

    def test_qualified_entries_have_a_recorded_real_host_pass(self):
        for entry in self.evidence.entries:
            if entry["qualification"] != "QUALIFIED_LIMITED":
                continue
            statuses = [record["status"] for record in entry["verification"]["real_host"]]
            self.assertIn("PASS_LIMITED", statuses, entry["id"])

    def test_static_candidates_have_no_real_host_record(self):
        for entry in self.evidence.entries:
            if entry["qualification"] == "STATIC_CANDIDATE":
                self.assertEqual(entry["verification"]["real_host"], [], entry["id"])

    def test_no_vendor_address_is_duplicated_in_the_inventory(self):
        for entry in self.evidence.entries:
            for symbol in entry["symbols"]:
                if symbol["kind"] == "rva":
                    self.assertIsNone(symbol["rva"], entry["id"])
                    self.assertTrue(symbol["entry_contract"])

    def test_operation_names_match_the_runtime_profile(self):
        known = set(self.evidence.document["known_operations"])
        for entry in self.evidence.entries:
            for operation in entry["scope"]["operations"]:
                self.assertIn(operation, known)

    def test_symbol_index_only_covers_exact_exports(self):
        index = self.evidence.symbol_index()
        self.assertIn("?GetMean@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z",
                      index)
        self.assertNotIn("#1487", index)
        self.assertNotIn("FFT", index)
        self.assertNotIn("image_document_show", index)

    def test_render_is_deterministic_and_current(self):
        first = evidence_module.render_markdown(self.evidence)
        second = evidence_module.render_markdown(self.evidence)
        self.assertEqual(first, second)
        path = os.path.join(evidence_module.repo_root(), "docs",
                            "GMS_COMPAT_ABI_EVIDENCE.md")
        with open(path, "r", encoding="utf-8") as handle:
            current = handle.read()
        self.assertEqual(current, first,
                         "docs/GMS_COMPAT_ABI_EVIDENCE.md is stale; run "
                         "python tools/gms_compat/cli.py evidence render")


class GateTamperTests(unittest.TestCase):
    def setUp(self):
        self.evidence = evidence_module.Evidence.load()

    def tampered(self):
        document = copy.deepcopy(self.evidence.document)
        return evidence_module.Evidence(document, self.evidence.path, self.evidence.root)

    def entry(self, document, entry_id):
        for entry in document.entries:
            if entry["id"] == entry_id:
                return entry
        raise AssertionError(entry_id)

    def test_removing_the_host_record_blocks_a_qualified_entry(self):
        broken = self.tampered()
        self.entry(broken, "image.lookup")["verification"]["real_host"] = []
        self.assertIn("qualified_without_real_host_pass",
                      codes(evidence_module.validate(broken)))

    def test_a_name_only_derivation_cannot_be_qualified(self):
        broken = self.tampered()
        self.entry(broken, "image.lookup")["derivation"] = "name_only"
        self.assertIn("qualification_exceeds_derivation",
                      codes(evidence_module.validate(broken)))

    def test_a_similarity_only_derivation_cannot_be_qualified(self):
        broken = self.tampered()
        self.entry(broken, "processing.histogram")["derivation"] = "similarity_only"
        self.assertIn("qualification_exceeds_derivation",
                      codes(evidence_module.validate(broken)))

    def test_a_fabricated_heading_anchor_is_detected(self):
        broken = self.tampered()
        self.entry(broken, "image.lookup")["static_evidence"][0]["anchor"] = \
            "## A heading that does not exist"
        self.assertIn("evidence_anchor_not_found",
                      codes(evidence_module.validate(broken)))

    def test_a_fabricated_source_file_is_detected(self):
        broken = self.tampered()
        self.entry(broken, "image.lookup")["static_evidence"][0]["source"] = \
            "experiments/native-bridge/INVENTED.md"
        self.assertIn("evidence_source_not_found",
                      codes(evidence_module.validate(broken)))

    def test_a_layout_without_its_own_anchor_is_detected(self):
        broken = self.tampered()
        self.entry(broken, "image.lookup")["layout"]["evidence_anchor"] = "## Missing"
        self.assertIn("evidence_anchor_not_found",
                      codes(evidence_module.validate(broken)))

    def test_a_layout_without_ownership_is_detected(self):
        broken = self.tampered()
        self.entry(broken, "image.lookup")["layout"]["ownership"] = ""
        self.assertIn("layout_ownership_missing",
                      codes(evidence_module.validate(broken)))

    def test_a_duplicated_vendor_rva_is_rejected(self):
        broken = self.tampered()
        symbol = self.entry(broken, "document.factory_show")["symbols"][0]
        symbol["rva"] = 0x4C3040
        self.assertIn("rva_duplicated_in_evidence",
                      codes(evidence_module.validate(broken)))

    def test_a_symbol_bound_twice_is_rejected(self):
        broken = self.tampered()
        target = self.entry(broken, "image.enumerate")
        source = self.entry(broken, "image.lookup")
        target["symbols"].append(copy.deepcopy(source["symbols"][0]))
        self.assertIn("symbol_bound_twice", codes(evidence_module.validate(broken)))

    def test_an_unknown_operation_is_rejected(self):
        broken = self.tampered()
        self.entry(broken, "image.lookup")["scope"]["operations"].append(
            "native_invented_operation")
        self.assertIn("scope_operation_unknown",
                      codes(evidence_module.validate(broken)))

    def test_an_open_conflict_blocks_a_qualified_entry(self):
        broken = self.tampered()
        self.entry(broken, "processing.fourier")["conflicts"].append(
            {"summary": "unresolved packing disagreement", "resolved": False})
        self.assertIn("qualified_with_open_conflict",
                      codes(evidence_module.validate(broken)))

    def test_a_mismatched_module_hash_is_rejected(self):
        broken = self.tampered()
        self.entry(broken, "image.lookup")["modules"][0]["sha256"] = "0" * 64
        self.assertIn("entry_module_hash_mismatch",
                      codes(evidence_module.validate(broken)))

    def test_a_wrong_build_profile_is_rejected(self):
        broken = self.tampered()
        self.entry(broken, "image.lookup")["build_profile"] = "gms-3.54.x"
        self.assertIn("entry_build_profile_mismatch",
                      codes(evidence_module.validate(broken)))

    def test_a_drifted_build_identity_is_detected(self):
        document = copy.deepcopy(self.evidence.document)
        document["build"]["modules"][1]["sha256"] = "1" * 64
        broken = evidence_module.Evidence(document, self.evidence.path, self.evidence.root)
        self.assertIn("profile_module_hash_mismatch",
                      codes(evidence_module.cross_check_profile(broken)))

    def test_a_missing_offline_test_path_is_detected(self):
        broken = self.tampered()
        self.entry(broken, "image.lookup")["verification"]["offline_tests"][0]["path"] = \
            "experiments/native-bridge/mvp/invented_tests.cpp"
        self.assertIn("offline_test_not_found",
                      codes(evidence_module.validate(broken)))

    def test_a_profile_contract_missing_from_the_inventory_is_detected(self):
        broken = self.tampered()
        entry = self.entry(broken, "roi.geometry")
        entry["symbols"] = [symbol for symbol in entry["symbols"]
                            if symbol.get("entry_contract") != "roi_is_rectangle"]
        self.assertIn("profile_contract_not_in_evidence",
                      codes(evidence_module.cross_check_profile(broken)))


class SchemaContractTests(unittest.TestCase):
    """The published JSON Schema must state exactly what the validator enforces."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(evidence_module.repo_root(), "tools", "gms_compat",
                            "schema", "abi_evidence.schema.json")
        with open(path, "r", encoding="utf-8") as handle:
            cls.schema = json.load(handle)
        cls.entry_schema = cls.schema["definitions"]["entry"]

    def test_required_keys_match_the_validator(self):
        self.assertEqual(sorted(self.entry_schema["required"]),
                         sorted(evidence_module._REQUIRED_ENTRY_KEYS))

    def test_qualification_enum_matches(self):
        self.assertEqual(self.entry_schema["properties"]["qualification"]["enum"],
                         list(evidence_module.QUALIFICATIONS))

    def test_derivation_enum_matches(self):
        self.assertEqual(self.entry_schema["properties"]["derivation"]["enum"],
                         list(evidence_module.DERIVATIONS))

    def test_shipped_entries_conform_to_the_published_schema(self):
        evidence = evidence_module.Evidence.load()
        allowed_revalidation = set(
            self.entry_schema["properties"]["revalidation"]["items"]["enum"])
        for entry in evidence.entries:
            for key in self.entry_schema["required"]:
                self.assertIn(key, entry, "%s missing %s" % (entry["id"], key))
            self.assertIn(entry["qualification"],
                          self.entry_schema["properties"]["qualification"]["enum"])
            self.assertIn(entry["derivation"],
                          self.entry_schema["properties"]["derivation"]["enum"])
            for value in entry["revalidation"]:
                self.assertIn(value, allowed_revalidation,
                              "%s uses an undeclared revalidation key" % entry["id"])


class EvidenceCliTests(unittest.TestCase):
    def run_cli(self, argv):
        from io import StringIO
        from contextlib import redirect_stdout, redirect_stderr
        import cli
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_validate_exits_zero_for_the_shipped_inventory(self):
        code, out, _ = self.run_cli(["evidence", "validate"])
        self.assertEqual(code, 0)
        self.assertIn("evidence valid", out)

    def test_validate_json_reports_counts(self):
        code, out, _ = self.run_cli(["evidence", "validate", "--json"])
        self.assertEqual(code, 0)
        document = json.loads(out)
        self.assertTrue(document["valid"])
        self.assertEqual(document["issues"], [])

    def test_render_check_detects_no_drift(self):
        code, out, _ = self.run_cli(["evidence", "render", "--check"])
        self.assertEqual(code, 0)
        self.assertIn("up to date", out)

    def test_show_returns_one_entry(self):
        code, out, _ = self.run_cli(["evidence", "show", "image.lookup"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["id"], "image.lookup")

    def test_show_rejects_an_unknown_entry(self):
        code, _, err = self.run_cli(["evidence", "show", "image.nonexistent"])
        self.assertEqual(code, 2)
        self.assertIn("evidence_entry_not_found", err)


if __name__ == "__main__":
    unittest.main()
