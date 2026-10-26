# -*- coding: utf-8 -*-
"""Narrow post-native external-executable continuation, synthetic host only."""
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from test_native_uint32_production_oracle import SyntheticProduction,C,O,S,SESSION,save


@unittest.skipUnless(shutil.which("node"),"Offline NPY encoder requires Node; no download")
class Uint32ProductionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.directory=Path(self.temp.name);self.f=SyntheticProduction(self.directory)
        self.f.label_ids={};self.f.creation={};real_run=subprocess.run
        def missing_external(command,*args,**kwargs):
            if len(command)>1 and Path(command[1]).name=="native_handoff_mean.py":raise FileNotFoundError("synthetic missing external interpreter after native completion")
            return real_run(command,*args,**kwargs)
        with mock.patch.dict(os.environ,{"DM_NATIVE_SESSION":SESSION}),mock.patch.dict(C["main"].__globals__,{"StdioClient":self.f.client_type()}),mock.patch.object(subprocess,"run",missing_external),mock.patch("sys.stdout",io.StringIO()):
            status=C["main"](["--directory",str(self.directory),"--output-directory",str(self.f.attempt),"--qualification-mode","production"])
        self.assertEqual(status,1);self.original_path=self.f.attempt/C["REPORT_NAME"];self.original_bytes=self.original_path.read_bytes();self.original=json.loads(self.original_bytes)
        self.assertEqual(self.original["status"],"FAIL");self.assertEqual(self.original["error_type"],"FileNotFoundError");self.assertEqual(len(self.original["checks"]),34)
        self.assertEqual(len(self.original["captures"]),1);self.assertEqual(self.original["externals"],[]);self.assertEqual(self.f.created,32)
        self.resumed=self.directory/"resumed"

    def resume(self):
        with mock.patch.dict(os.environ,{"DM_NATIVE_SESSION":SESSION}),mock.patch.dict(C["main"].__globals__,{"StdioClient":self.f.client_type()}),mock.patch("sys.stdout",io.StringIO()):
            status=C["main"](["--directory",str(self.directory),"--output-directory",str(self.resumed),"--qualification-mode","production","--resume-report",str(self.original_path),"--analysis-python",sys.executable])
        self.assertEqual(status,0,(self.resumed/C["REPORT_NAME"]).read_text())
        self.f.report_path=self.resumed/C["REPORT_NAME"];self.f.report=json.loads(self.f.report_path.read_bytes());self.f.ledger=self.resumed/C["LEDGER_NAME"];self.f.recovery=self.resumed/C["RECOVERY_LEDGER_NAME"]

    def test_resume_only_queries_and_keeps_failed_files_then_full_oracle(self):
        self.resume();self.assertEqual(self.f.created,32);self.assertEqual(len(self.f.producer_ops),32);self.assertEqual(self.f.clients,3)
        self.assertEqual(self.original_path.read_bytes(),self.original_bytes);self.assertEqual(self.f.report["status"],"RECORDED_RECOVERED")
        self.assertEqual(len(self.f.report["resume"]["queries"]),32);self.assertEqual(len(self.f.report["recovered_from"]["preserved_files"]),6)
        original_ledger=self.original_path.parent/C["LEDGER_NAME"]
        self.assertEqual(original_ledger.read_bytes(),self.f.ledger.read_bytes())
        self.assertEqual(self.f.run()["status"],"PASS_BOUNDED_UINT32_OPERATIONS")

    def test_known_pre_rois_catalog_keeps_original_bytes_and_queries_only(self):
        # Synthetic historical-catalog simulation, never edits a real receipt.
        for name in ("dm_native_rois", "dm_native_profile", "dm_native_histogram", "dm_native_frame", "dm_native_import"):
            self.original["catalog"].remove(name)
        self.assertEqual(len(self.original["catalog"]), 16)
        save(self.original_path, self.original)
        self.original_bytes = self.original_path.read_bytes()
        self.resume()
        self.assertEqual(self.original_path.read_bytes(), self.original_bytes)
        self.assertEqual(self.f.created, 32)
        self.assertEqual(len(self.f.producer_ops), 32)
        self.assertEqual(len(self.f.report["resume"]["queries"]), 32)
        self.assertEqual(self.f.run()["status"], "PASS_BOUNDED_UINT32_OPERATIONS")

    def test_known_pre_import_catalog_keeps_historical_bytes_and_queries_only(self):
        # Explicit prior20-tool history remains history; the new live child
        # still reports the exact current21-tool catalog and creates nothing.
        self.original["catalog"].remove("dm_native_import")
        self.assertEqual(len(self.original["catalog"]), 20)
        save(self.original_path, self.original)
        self.original_bytes = self.original_path.read_bytes()
        self.resume()
        self.assertEqual(self.original_path.read_bytes(), self.original_bytes)
        self.assertEqual(self.f.created, 32)
        self.assertEqual(len(self.f.producer_ops), 32)
        self.assertEqual(len(self.f.report["resume"]["queries"]), 32)
        self.assertEqual(self.f.run()["status"], "PASS_BOUNDED_UINT32_OPERATIONS")

    def test_plain_failed_report_stays_rejected(self):
        with self.assertRaisesRegex(RuntimeError,"report/hash/actual PID/session/mode"):
            O["load_context"](S["Evidence"](),str(self.f.truth_path),str(self.original_path),str(self.original_path.parent/C["LEDGER_NAME"]),str(self.original_path.parent/C["RECOVERY_LEDGER_NAME"]),os.getpid())

    def test_new_resume_query_cannot_submit_a_producer_or_change_reply(self):
        self.resume();original=copy.deepcopy(self.f.report)
        for fault in ("producer","reply","missing"):
            with self.subTest(fault=fault):
                self.f.report=copy.deepcopy(original);query=self.f.report["resume"]["queries"][0]
                if fault=="producer":query["request"]=copy.deepcopy(self.f.report["checks"][1]["request"])
                elif fault=="reply":query["response"]["content"][0]["text"]+=" "
                else:self.f.report["resume"]["queries"].pop()
                with self.assertRaisesRegex(RuntimeError,"Recovery attempted a producer|32 new QUERY-only"):self.f.run()

    def test_original_bytes_hash_or_native_check_cannot_be_rewritten(self):
        self.resume();original=copy.deepcopy(self.f.report)
        for fault in ("hash","check","preserved_set"):
            with self.subTest(fault=fault):
                self.f.report=copy.deepcopy(original)
                if fault=="hash":self.f.report["recovered_from"]["report"]["sha256"]="0"*64
                elif fault=="check":self.f.report["checks"][1]["response"]["content"][0]["text"]+=" "
                else:self.f.report["recovered_from"]["preserved_files"].pop()
                with self.assertRaisesRegex(RuntimeError,"raw bytes or hash differ|changed original native evidence|preserved-file set incomplete"):self.f.run()

    def test_new_capture_cannot_adopt_old_partial_capture(self):
        self.resume();self.f.report["captures"][0]=self.original["captures"][0]
        with self.assertRaisesRegex(RuntimeError,"create new capture artifacts"):self.f.run()

    def test_bad_analysis_path_is_rejected_before_node_or_new_directory(self):
        next_dir=self.directory/"invalid-python"
        with mock.patch.dict(os.environ,{"DM_NATIVE_SESSION":SESSION}),mock.patch.dict(C["main"].__globals__,{"StdioClient":mock.Mock(side_effect=AssertionError("must not construct Node"))}):
            with self.assertRaisesRegex(ValueError,"Python executable"):
                C["main"](["--directory",str(self.directory),"--output-directory",str(next_dir),"--qualification-mode","production","--analysis-python",str(self.directory/"no-python.exe")])
        self.assertFalse(next_dir.exists())


class SavedCatalogTests(unittest.TestCase):
    def test_only_exact_known_historical_and_current_sets_can_resume(self):
        current = sorted(C["CATALOG"])
        legacy = sorted(C["LEGACY_PRE_ROIS_CATALOG"])
        self.assertEqual(len(current), 21)
        self.assertEqual(len(legacy), 16)
        self.assertTrue(C["valid_saved_catalog"](current))
        self.assertTrue(C["valid_saved_catalog"](legacy))
        self.assertEqual(len(C["LEGACY_ROIS_CATALOG"]), 17)
        self.assertTrue(C["valid_saved_catalog"](sorted(C["LEGACY_ROIS_CATALOG"])))
        self.assertEqual(len(C["LEGACY_PROFILE_CATALOG"]), 18)
        self.assertTrue(C["valid_saved_catalog"](sorted(C["LEGACY_PROFILE_CATALOG"])))
        self.assertEqual(len(C["LEGACY_PRE_IMPORT_CATALOG"]), 20)
        self.assertEqual(C["LEGACY_PRE_IMPORT_CATALOG"] | {"dm_native_import"}, C["CATALOG"])
        self.assertTrue(C["valid_saved_catalog"](sorted(C["LEGACY_PRE_IMPORT_CATALOG"])))
        for value in [None, {}, current + [current[0]], current + ["dm_unknown"],
                      legacy[:-1], [*legacy[:-1], "dm_native_rois"], legacy + [True],
                      sorted(C["LEGACY_PROFILE_CATALOG"] | {"dm_native_histogram"})]:
            with self.subTest(catalog=value):
                self.assertFalse(C["valid_saved_catalog"](value))


if __name__=="__main__":unittest.main()
