"""Offline ownership/transaction checks: temp dirs, dummy bytes, mocked process list.

No Gatan directory is accessed and no DM process is queried, launched or stopped.
The mocks live in this harness, not in the production installer's interface.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "experiments" / "native-bridge" / "mvp" / "manage_plugin.ps1"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
DLL_NAME = "dm_native_bridge_mvp.dll"
LOCK_NAME = ".dm_native_bridge_mvp.lock"

WRAPPER = r"""
$ErrorActionPreference = 'Stop'
function Get-Process {
    [CmdletBinding()] param()
    if ($env:NATIVE_INSTALL_TEST_DM_ACTIVE -eq '1') {
        [pscustomobject]@{ProcessName='DigitalMicrograph'; Id=424242}
    }
}
if ($env:NATIVE_INSTALL_TEST_FAIL_STATE) {
    function ConvertTo-Json {
        [CmdletBinding()]
        param([Parameter(ValueFromPipeline=$true)]$InputObject, [int]$Depth=2, [switch]$Compress)
        process {
            $state = $null
            if ($InputObject -is [Collections.IDictionary]) {
                if ($InputObject.Contains('state')) { $state = $InputObject['state'] }
            } elseif ($InputObject -and $InputObject.PSObject.Properties['state']) { $state = $InputObject.state }
            if ($state -and $state -eq $env:NATIVE_INSTALL_TEST_FAIL_STATE) { throw 'Injected offline manifest serialization failure' }
            Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject $InputObject -Depth $Depth -Compress:$Compress
        }
    }
}
$arguments = @{Action=$env:NATIVE_INSTALL_TEST_ACTION; SourceDll=$env:NATIVE_INSTALL_TEST_SOURCE;
    PluginDirectory=$env:NATIVE_INSTALL_TEST_PLUGINS; StateDirectory=$env:NATIVE_INSTALL_TEST_STATE; Confirm=$false}
if ($env:NATIVE_INSTALL_TEST_WHATIF -eq '1') { $arguments.WhatIf = $true }
& $env:NATIVE_INSTALL_TEST_SCRIPT @arguments
"""


@unittest.skipUnless(POWERSHELL, "PowerShell is required for offline installer checks")
class NativeInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-install-offline-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plugins = self.root / "plugins"
        self.state = self.root / "private-state"
        self.source = self.root / "build" / "dummy-built.dll"
        self.source.parent.mkdir()
        self.source.write_bytes(b"offline dummy DLL bytes; not a loadable plugin\x00\x01")
        self.target = self.plugins / DLL_NAME
        self.manifest = self.state / "install-manifest.json"

    def run_manager(self, action="Install", success=True, **settings):
        env = dict(os.environ)
        env.update({"NATIVE_INSTALL_TEST_SCRIPT": str(SCRIPT), "NATIVE_INSTALL_TEST_ACTION": action,
                    "NATIVE_INSTALL_TEST_SOURCE": str(self.source), "NATIVE_INSTALL_TEST_PLUGINS": str(self.plugins),
                    "NATIVE_INSTALL_TEST_STATE": str(self.state), "NATIVE_INSTALL_TEST_DM_ACTIVE": "0",
                    "NATIVE_INSTALL_TEST_FAIL_STATE": "", "NATIVE_INSTALL_TEST_WHATIF": "0"})
        env.update({"NATIVE_INSTALL_TEST_" + key.upper(): str(value) for key, value in settings.items()})
        encoded = base64.b64encode(WRAPPER.encode("utf-16-le")).decode("ascii")
        result = subprocess.run([POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
                                env=env, cwd=str(self.root), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        output = result.stdout.decode("utf-8", "replace") + result.stderr.decode("utf-8", "replace")
        if success:
            self.assertEqual(result.returncode, 0, output)
        else:
            self.assertNotEqual(result.returncode, 0, output)
        return output

    def read_manifest(self):
        return json.loads(self.manifest.read_text(encoding="utf-8-sig"))

    def change_manifest(self, **changes):
        record = self.read_manifest()
        record.update(changes)
        self.manifest.write_text(json.dumps(record), encoding="utf-8")
        return record

    def add_foreign(self):
        self.plugins.mkdir(exist_ok=True)
        foreign = {"other.dll": b"foreign plugin", "other.log": b"foreign log"}
        for name, data in foreign.items():
            (self.plugins / name).write_bytes(data)
        return foreign

    def assert_foreign(self, foreign):
        for name, data in foreign.items():
            self.assertEqual((self.plugins / name).read_bytes(), data)

    def test_install_remove_owns_one_dll_and_preserves_foreign_files(self):
        foreign = self.add_foreign()
        output = self.run_manager()
        self.assertIn("other.dll", output)
        record = self.read_manifest()
        self.assertEqual(record["state"], "installed")
        self.assertTrue(Path(record["source_path"]).is_absolute())
        self.assertTrue(Path(record["owned_path"]).is_absolute())
        self.assertTrue(os.path.samefile(record["source_path"], self.source))
        self.assertTrue(os.path.samefile(record["owned_path"], self.target))
        self.assertEqual(record["sha256"], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assertFalse((self.plugins / LOCK_NAME).exists())
        self.run_manager("Remove")
        self.assertFalse(self.target.exists())
        self.assertEqual(self.read_manifest()["state"], "removed")
        self.assert_foreign(foreign)
        self.assertEqual(set(path.name for path in self.plugins.iterdir()), set(foreign))
        self.run_manager("Remove")
        self.run_manager("Install", success=False)

    def test_refuses_existing_target_and_existing_manifest(self):
        self.plugins.mkdir()
        self.target.write_bytes(b"foreign even though name matches")
        self.run_manager(success=False)
        self.assertEqual(self.target.read_bytes(), b"foreign even though name matches")
        self.assertFalse(self.state.exists())
        self.target.unlink()
        self.state.mkdir()
        self.manifest.write_text("foreign manifest", encoding="utf-8")
        self.run_manager(success=False)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.manifest.read_text(encoding="utf-8"), "foreign manifest")

    def test_changed_hash_foreign_manifest_and_missing_manifest_refuse_delete(self):
        foreign = self.add_foreign()
        self.run_manager()
        original = self.target.read_bytes()
        self.target.write_bytes(b"modified DLL")
        self.run_manager("Remove", success=False)
        self.assertEqual(self.target.read_bytes(), b"modified DLL")
        self.target.write_bytes(original)
        self.change_manifest(project="foreign-project")
        self.run_manager("Remove", success=False)
        self.assertEqual(self.target.read_bytes(), original)
        self.manifest.unlink()
        self.run_manager("Remove", success=False)
        self.assertEqual(self.target.read_bytes(), original)
        self.assert_foreign(foreign)

    def test_manifest_path_escape_and_foreign_filename_are_rejected(self):
        self.run_manager()
        outside = self.root / DLL_NAME
        outside.write_bytes(self.source.read_bytes())
        self.change_manifest(owned_path=str(outside))
        self.run_manager("Remove", success=False)
        self.assertTrue(outside.exists())
        self.assertTrue(self.target.exists())
        self.change_manifest(owned_path=str(self.target), dll_name="other.dll")
        self.run_manager("Remove", success=False)
        self.assertTrue(self.target.exists())
        self.change_manifest(dll_name=DLL_NAME, plugin_directory=str(self.root))
        self.run_manager("Remove", success=False)
        self.assertTrue(self.target.exists())

    def test_whatif_and_running_process_guard_make_no_writes(self):
        self.run_manager(whatif="1")
        self.assertFalse(self.plugins.exists())
        self.assertFalse(self.state.exists())
        self.run_manager(success=False, dm_active="1")
        self.assertFalse(self.plugins.exists())
        self.assertFalse(self.state.exists())
        self.run_manager()
        before = self.manifest.read_bytes()
        self.run_manager("Remove", whatif="1")
        self.assertTrue(self.target.exists())
        self.assertEqual(self.manifest.read_bytes(), before)
        self.run_manager("Remove", success=False, dm_active="1")
        self.assertTrue(self.target.exists())

    def test_prepared_manifest_and_matching_stale_lock_allow_recovery(self):
        self.run_manager()
        record = self.change_manifest(state="prepared")
        lock = self.plugins / LOCK_NAME
        lock.write_text(json.dumps({"project": record["project"], "install_id": record["install_id"]}), encoding="utf-8")
        self.run_manager("Remove")
        self.assertFalse(self.target.exists())
        self.assertFalse(lock.exists())
        self.assertEqual(self.read_manifest()["state"], "removed")

    def test_foreign_or_malformed_stale_lock_is_preserved(self):
        self.run_manager()
        lock = self.plugins / LOCK_NAME
        for contents in ['{"project":"foreign", "install_id":"foreign"}', "invalid JSON"]:
            lock.write_text(contents, encoding="utf-8")
            self.run_manager("Remove", success=False)
            self.assertEqual(lock.read_text(encoding="utf-8"), contents)
            self.assertTrue(self.target.exists())

    def test_failed_initial_manifest_never_copies_dll(self):
        self.run_manager(success=False, fail_state="prepared")
        self.assertFalse(self.target.exists())
        self.assertFalse(self.manifest.exists())
        self.assertEqual(list(self.plugins.iterdir()), [])

    def test_failed_install_commit_leaves_recognized_recoverable_dll(self):
        foreign = self.add_foreign()
        self.run_manager(success=False, fail_state="installed")
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assertEqual(self.read_manifest()["state"], "prepared")
        self.run_manager("Remove")
        self.assertFalse(self.target.exists())
        self.assert_foreign(foreign)

    def test_failed_removal_commit_is_recoverable(self):
        self.run_manager()
        self.run_manager("Remove", success=False, fail_state="removing")
        self.assertTrue(self.target.exists(), "pending-removal state must persist before deletion")
        self.assertEqual(self.read_manifest()["state"], "installed")
        self.run_manager("Remove", success=False, fail_state="removed")
        self.assertFalse(self.target.exists())
        self.assertEqual(self.read_manifest()["state"], "removing")
        self.run_manager("Remove")
        self.assertEqual(self.read_manifest()["state"], "removed")

    def test_symlink_plugin_directory_refuses_path_alias(self):
        actual = self.root / "actual"
        actual.mkdir()
        try:
            os.symlink(str(actual), str(self.plugins), target_is_directory=True)
        except OSError as error:
            if os.name != "nt":
                self.skipTest("symlink creation unavailable: %s" % error)
            env = dict(os.environ, NATIVE_TEST_JUNCTION=str(self.plugins), NATIVE_TEST_JUNCTION_TARGET=str(actual))
            result = subprocess.run([POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                                     "New-Item -ItemType Junction -Path $env:NATIVE_TEST_JUNCTION -Target $env:NATIVE_TEST_JUNCTION_TARGET | Out-Null"],
                                    env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
            if result.returncode:
                self.skipTest("neither symlink nor junction creation is available")
        self.run_manager(success=False)
        self.assertEqual(list(actual.iterdir()), [])
        self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main()
