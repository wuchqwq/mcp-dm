# Experimental native bridge: build, install and remove

This is a separate NB1 C++ experiment for an explicitly tested DigitalMicrograph
build. Keep the default v0.6 Python/TCP configuration unchanged. Do not load the
experimental plugin in a production acquisition session. Use an idle test host
and keep source images unchanged while requests run. This code does not control
the microscope.

## Build locally

Use a Windows x64 `clang++` toolchain targeting MinGW. The build uses `-static`
and the reverse-engineered adapter for the specified host build; it does not use
or distribute a Gatan SDK. A successful build alone does not validate the ABI or
the plugin in DM.

From the repository root, with your compiler on `PATH`:

```powershell
& .\experiments\native-bridge\mvp\build.ps1 -Cxx clang++.exe
```

`-Cxx` and `-OutputDirectory` accept explicit paths. `-OfflineOnly` builds the
synthetic host and core tests without building the real-DM plugin. The real
build produces `build/dm_native_bridge.dll`. The installer gives its installed
copy the distinct fixed name `dm_native_bridge_mvp.dll`.

## Inspect and install with DM closed

Disconnect clients and close DigitalMicrograph normally before installing.
`manage_plugin.ps1` refuses to run while any `DigitalMicrograph` process exists;
it never starts, stops, kills or restarts DM. Do not launch DM during file
management. Its default plugin directory is `$env:ProgramData\Gatan\Plugins`;
pass the actual directory explicitly if your installation differs.

Choose a new private state directory outside both the plugin directory and the
public checkout. Its manifest records absolute source/owned paths and SHA256,
so do not commit or publish it. Keep this exact directory for removal/recovery.

```powershell
$pluginDir = Join-Path $env:ProgramData 'Gatan\Plugins'
$stateDir = Join-Path $env:LOCALAPPDATA ('mcp-dm\native-install-' + [guid]::NewGuid().ToString('N'))
$builtDll = (Resolve-Path .\experiments\native-bridge\mvp\build\dm_native_bridge.dll).Path
$manager = '.\experiments\native-bridge\mvp\manage_plugin.ps1'
& $manager -Action Install -SourceDll $builtDll -PluginDirectory $pluginDir -StateDirectory $stateDir -WhatIf
& $manager -Action Install -SourceDll $builtDll -PluginDirectory $pluginDir -StateDirectory $stateDir -Confirm:$false
```

The script prints the directory inventory, resolves absolute paths, rejects
reparse points, and refuses an existing target, manifest or installation lock.
It creates a durable `prepared` ownership record before copying bytes, verifies
the staged checksum, then atomically moves the staged file without overwriting
anything. Successful manifest updates retain previous records as private
`manifest-*.previous` files. No directory is cleared.

Administrator rights may be needed for the chosen plugin directory; the script
does not elevate itself. `-WhatIf` performs inspection without creating files or
directories. Normal explicit invocations do not need another confirmation.

## Start and validate a separate test session

Start the approved test DM manually with a fresh `DM_NATIVE_SESSION` consisting
of exactly 32 lowercase hexadecimal characters in its inherited environment.
Use that same value in a separate configuration based on
[`mcp.native.json.example`](../../../mcp.native.json.example); do not replace or
edit the default v0.6 entry. The installer does not change client configuration.

Check `dm_status` and its actual host `backend`, build identity, process/thread
receipts and session before numerical work. `mock-native` is synthetic evidence
only. This native MCP catalog exposes status, datasets, native mean, result query,
experimental explicit-ID half-open `dm_crop` and `dm_native_show`. The crop creates a separate
native image retained by the plugin until normal native STOP/cleanup; it does
not create a visible DM document. The mean tool is not a replacement for the
full statistics tool. The strict core acceptance client does not call crop.

Qualified real-host name checks use ASCII synthetic names. An independent
comparison of non-ASCII names between legacy GMS Python bindings and native
`GetUnicodeName` failed and remains NOT_QUALIFIED. Do not silently recode image
names or overwrite the original failed truth to make acceptance pass; the
native UTF-16/UTF-8 path has no heuristic encoding repair.

Crop requires an explicit `request_id` saved before submitting; newly added
side-effect tools follow the same rule. Save its session, tool and arguments
too. Existing read-only status/datasets/mean calls keep generated-ID
compatibility, but the operator trial supplies IDs for all calls.
After a timeout, cancellation or disconnect, query that ID with
`dm_native_result`; never automatically resubmit the original operation.
`queued`, `running` and `unknown` are not successful completion. Cancellation
only ends local waiting, and a request may still execute in the host. Query
recovery applies only to the original running session's retained records.
After STOP, DM exit/restart or a new session, recovery is not promised; do not
replay an old operation ID as a new request.

Raw mean now permits recognized incomplete spatial calibration and reports
its per-axis issues without applying intensity calibration. Crop still
requires usable calibration; unknown units do not become invented pixel units.
Object/native/ABI failures remain failures, not missing-calibration fallback.
New real-host cases are recorded separately in [RESULTS.md](../RESULTS.md).

The strict stdio acceptance client takes the one-shot fixture JSON and a new
private evidence directory. It starts and closes only its own Node subprocess:

```powershell
python -B .\experiments\native-bridge\mvp\accept_mcp.py --fixture "$fixtureJson" --evidence-directory "$newEvidenceDir" --expected-host-pid $testDmPid
```

It checks the MCP and tool-error layers separately, backend/build identity,
receipts, fixture means, shapes and physical calibration, plus invalid ID
rejection. Its default deadline is five seconds per RPC; a reader thread keeps
that deadline effective if stdout stalls. The generated report does not claim
WorkBuddy or visual acceptance. This does not replace the independent post-run
source-invariance check in `verify_fixture.py`.

Native crop has a separate [strict MCP acceptance client](accept_crop_mcp.py),
an independent one-shot [pixel/calibration oracle](verify_crop.py), and a
post-STOP [output-ownership check](verify_stopped_outputs.py). These scripts
must agree on the same prepared synthetic session and private evidence
directory. Invoking or compiling them does not mean crop passed in DM; see
[RESULTS.md](../RESULTS.md) for its current acceptance status. GMS Python oracle
scripts run once inside DM after native calls have finished; they are not
resident listeners and must release their image/array references before an
output-lifetime check.

For the separate, answer-free ordinary WorkBuddy trial, follow
[WORKBUDDY_TRIAL.md](WORKBUDDY_TRIAL.md). Its private trial answers are operator
material; `accept_trial_mcp.py` is a strict protocol client, not a WorkBuddy
run. No existing client entry is edited by these instructions or scripts.

The P1 `dm_native_show` candidate completed actual MCP/native receipt and
same-image correlation checks. Independent desktop acceptance is still
NOT_TESTED, and the current trial is HOLD. It targets only an
already retained crop by exact ID and a new saved show request ID, without a
path or file save. It must not be advertised as completed delivery until its
own acceptance. STOP must not close a shown document; continued document
ownership after STOP needs separate testing from hidden-output release.
The current trial acknowledged STOP and removed the pipe/window, but its host
remains open with the DLL loaded and manifest installed. Complete its private
post-STOP oracle, then normally close only the delivered crop document and run
[verify_trial_closed.py](verify_trial_closed.py) while DM still runs. That
prepared check verifies final output release and unchanged other sources;
whole-host exit is not a substitute. These checks remain NOT_TESTED. Finally
complete normal exit and owned removal; do not force termination
or remove a loaded DLL. Earlier accepted cleanup is not this trial's cleanup.

## Stop IPC, close the test host and remove

1. Disconnect every MCP client and finish or inspect any outstanding operation
   using its saved ID. Do not assume that a client timeout stopped native work.
2. Save a fresh STOP ID and use the explicit NB1 helper:

   ```powershell
   $stopRequestId = 'stop-' + [guid]::NewGuid().ToString('N')
   $stopEvidence = Join-Path $stateDir ($stopRequestId + '.json')
   python -B .\experiments\native-bridge\mvp\stop_native.py --session $env:DM_NATIVE_SESSION --request-id $stopRequestId --evidence $stopEvidence
   ```

   The helper submits once and checks the bounded JSON frame, identity, state,
   process/thread fields and timings. Require `state=completed` and
   `result.ipc_stopped=true`. STOP is an IPC acknowledgement on the worker, so
   `exec_tid=0` is expected; it is not a DM API execution receipt. The normal
   MCP catalog does not expose STOP. A missing/invalid receipt is unresolved
   and must be investigated. Allow the host cleanup callback to complete and
   confirm the experimental pipe/window are gone; an acknowledgement alone
   does not establish every cleanup postcondition.
3. Close the test DM normally. STOP closes native IPC; it does not terminate DM,
   unload the DLL or prove that an already running host operation has finished.
4. With no DigitalMicrograph process left, use the same state directory:

```powershell
& $manager -Action Remove -PluginDirectory $pluginDir -StateDirectory $stateDir -WhatIf
& $manager -Action Remove -PluginDirectory $pluginDir -StateDirectory $stateDir -Confirm:$false
```

Removal requires this project's manifest, the exact fixed filename inside the
specified plugin directory and an unchanged checksum. It deletes only that DLL.
Foreign DLLs, logs and other files are preserved, and no recursive deletion is
used. The manifest remains with `state=removed`; a later installation must use a
new private state directory. A DLL appearing after the recorded removal is
foreign and will not be deleted by repeating Remove.

Removal does not edit any MCP client configuration. Close the separate
experimental native client and use the existing default v0.6 Python/TCP entry
and its normal launcher; that entry was never replaced by this installer.

If final installation bookkeeping fails, the DLL remains owned by its durable
`prepared` manifest; Remove can recover it after DM is closed. Removal writes a
durable `removing` state before deleting the DLL, so interrupted final
bookkeeping is also recoverable. A stale lock is accepted only when its project
and installation ID match that manifest. A changed DLL, foreign/corrupt lock or
manifest, missing installed DLL, or path mismatch is refused. Preserve and
inspect the local records before any manual recovery; do not clear a plugin
directory to resolve a conflict.

## Offline installer checks

```powershell
python -B -m unittest discover -s tests -p test_native_install.py -v
```

These tests use temporary directories, non-loadable dummy bytes and a mocked
process list. They cover ownership, conflicts, changed hashes, escaped paths,
reparse points, WhatIf and interrupted manifest updates. They do not install
into a Gatan directory or validate loading, numerical results or real-host
process detection.
