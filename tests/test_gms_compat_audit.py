"""Offline tests for gms-compat audit (manifest vs recorded ABI evidence).

The audit answers "which recorded bindings are present, which are absent, and
which cannot be checked without loading the module". It never answers "is this
safe to call".
"""
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

import audit  # noqa: E402
import cli  # noqa: E402
import evidence as evidence_module  # noqa: E402
import gms_compat_pe_fixture as fixtures  # noqa: E402
import manifest as manifest_model  # noqa: E402
import pe  # noqa: E402

_VERSION = (3, 53, 4137, 0)


def named_exports(evidence, module_name):
    names = []
    for entry in evidence.entries:
        for symbol in entry["symbols"]:
            if symbol["kind"] == "export" and symbol["module"].lower() == module_name:
                names.append(symbol["name"])
    return names


class AuditFixture(object):
    """Builds a manifest that matches the recorded evidence exactly."""

    def __init__(self, directory, evidence):
        self.directory = directory
        self.evidence = evidence
        self.modules = []

    def build(self, module_name, exports=None, ordinal_base=1, **kwargs):
        path = os.path.join(self.directory, module_name)
        if exports is None:
            exports = named_exports(self.evidence, module_name.lower())
        kwargs.setdefault("file_version", _VERSION)
        fixtures.write_pe(path, exports=[{"name": name} for name in exports],
                          ordinal_base=ordinal_base, **kwargs)
        self.modules.append(pe.inspect_module(path))
        return path

    def build_all(self, skip=(), override=None, drop=()):
        override = override or {}
        for module in self.evidence.build["modules"]:
            name = module["name"]
            if name.lower() in skip:
                continue
            exports = named_exports(self.evidence, name.lower())
            exports = [item for item in exports if item not in drop]
            ordinal_base = 1
            if module["name"].lower() == "mfc140.dll":
                # A real mfc140.dll exports by ordinal only; the fixture models a
                # single export whose ordinal is 1487, which is what the evidence
                # binding actually checks.
                ordinal_base = 1487
                exports = ["mfcOrdinalPlaceholder"]
            exports = override.get(name.lower(), exports)
            kwargs = {}
            if name.lower() == "mfc140.dll":
                kwargs["file_version"] = (14, 51, 36247, 0)
            self.build(name, exports=exports, ordinal_base=ordinal_base, **kwargs)
        return manifest_model.new_manifest("inspect", {}, self.modules)


class AuditTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.evidence = evidence_module.Evidence.load()

    def complete_manifest(self, **kwargs):
        builder = AuditFixture(self._directory.name, self.evidence)
        return builder.build_all(**kwargs)

    def apply_pinned_hashes(self, manifest):
        pinned = dict((module["name"].lower(), module["sha256"])
                      for module in self.evidence.build["modules"])
        for module in manifest["modules"]:
            module["sha256"] = pinned[module["name"].lower()]
        return manifest

    def test_complete_build_has_every_export_binding(self):
        manifest = self.apply_pinned_hashes(self.complete_manifest())
        report = audit.audit(manifest, self.evidence)
        self.assertEqual(report["summary"]["export_bindings_missing"], 0)
        self.assertGreater(report["summary"]["export_bindings_required"], 40)
        self.assertEqual(report["summary"]["modules_missing"], 0)
        self.assertEqual(report["summary"]["modules_hash_matched"], 5)

    def test_synthetic_build_is_a_hash_mismatch_by_construction(self):
        report = audit.audit(self.complete_manifest(), self.evidence)
        self.assertEqual(report["summary"]["modules_hash_mismatched"], 5)
        self.assertEqual(report["summary"]["export_bindings_missing"], 0)

    def test_ordinal_only_binding_is_checked_by_ordinal(self):
        report = audit.audit(self.complete_manifest(), self.evidence)
        mfc = [item for item in report["modules"]
               if item["name"].lower() == "mfc140.dll"][0]
        self.assertEqual(mfc["required_exports"], 1)
        self.assertEqual(mfc["missing_exports"], [])
        self.assertIsNone(mfc["version_match"],
                          "mfc140.dll is gated by hash only, not by version")

    def test_missing_export_marks_the_dependent_capabilities(self):
        report = audit.audit(self.complete_manifest(drop=[
            "?GetMean@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z"]),
            self.evidence)
        self.assertEqual(report["summary"]["export_bindings_missing"], 1)
        states = dict((item["operation"], item["state"]) for item in report["capabilities"])
        self.assertEqual(states["native_mean"], audit.SYMBOL_MISSING)
        self.assertEqual(states["native_statistics"], audit.SYMBOL_MISSING)

    def test_absent_module_is_reported_as_missing(self):
        report = audit.audit(self.complete_manifest(skip=("mfc140.dll",)), self.evidence)
        mfc = [item for item in report["modules"]
               if item["name"].lower() == "mfc140.dll"][0]
        self.assertFalse(mfc["present"])
        self.assertEqual(report["summary"]["modules_missing"], 1)
        self.assertGreater(report["summary"]["export_bindings_missing"], 0)

    def test_hash_mismatch_is_reported_and_bindings_are_still_checked(self):
        manifest = self.apply_pinned_hashes(self.complete_manifest())
        manifest["modules"][0]["sha256"] = "0" * 64
        report = audit.audit(manifest, self.evidence)
        self.assertEqual(report["summary"]["modules_hash_mismatched"], 1)
        self.assertEqual(report["summary"]["modules_hash_matched"], 4)
        self.assertEqual(report["summary"]["export_bindings_missing"], 0)

    def test_architecture_mismatch_is_reported(self):
        manifest = self.complete_manifest()
        manifest["modules"][0]["architecture"] = "x86"
        report = audit.audit(manifest, self.evidence)
        mismatched = [item for item in report["modules"]
                      if item["architecture_match"] is False]
        self.assertEqual(len(mismatched), 1)

    def test_contract_only_capability_cannot_be_confirmed_offline(self):
        report = audit.audit(self.complete_manifest(), self.evidence)
        states = dict((item["operation"], item["state"]) for item in report["capabilities"])
        self.assertEqual(states["native_display"], audit.CONTRACT_UNVERIFIABLE)
        display = [item for item in report["capabilities"]
                   if item["operation"] == "native_display"][0]
        self.assertTrue(display["non_export_contracts"])

    def test_blocked_operation_is_refused_by_evidence(self):
        report = audit.audit(self.complete_manifest(), self.evidence)
        states = dict((item["operation"], item["state"]) for item in report["capabilities"])
        self.assertEqual(states["native_save"], audit.REFUSED_BY_EVIDENCE)

    def test_every_report_stays_refused(self):
        text = manifest_model.dumps(audit.audit(self.complete_manifest(), self.evidence))
        self.assertIn('"state": "REFUSED"', text)
        self.assertNotIn('"QUALIFIED_LIMITED"', text)
        report = json.loads(text)
        self.assertFalse(report["qualification"]["may_authorize_calls"])
        self.assertTrue(report["limitations"])

    def test_report_is_reproducible(self):
        manifest = self.complete_manifest()
        first = manifest_model.dumps(audit.audit(manifest, self.evidence))
        second = manifest_model.dumps(audit.audit(manifest, self.evidence))
        self.assertEqual(first, second)


class AuditCliTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.evidence = evidence_module.Evidence.load()

    def write_manifest(self, **kwargs):
        builder = AuditFixture(self._directory.name, self.evidence)
        document = builder.build_all(**kwargs)
        path = os.path.join(self._directory.name, "manifest.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(manifest_model.dumps(document))
        return path

    def run_cli(self, argv):
        from io import StringIO
        from contextlib import redirect_stdout, redirect_stderr
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_cli_audit_reports_no_missing_bindings(self):
        path = self.write_manifest()
        code, out, _ = self.run_cli(["audit", path])
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertEqual(report["summary"]["export_bindings_missing"], 0)
        self.assertEqual(report["qualification"]["state"], "REFUSED")

    def test_cli_fail_on_missing_exit_code(self):
        path = self.write_manifest(drop=[
            "?GetMean@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z"])
        code, _, _ = self.run_cli(["audit", "--fail-on-missing", path])
        self.assertEqual(code, 1)

    def test_cli_rejects_a_bad_manifest(self):
        broken = os.path.join(self._directory.name, "broken.json")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write('{"schema": "mcp-dm/gms-compat/module-manifest"}')
        code, _, err = self.run_cli(["audit", broken])
        self.assertEqual(code, 2)
        self.assertIn("manifest_schema_version_unsupported", err)


if __name__ == "__main__":
    unittest.main()
