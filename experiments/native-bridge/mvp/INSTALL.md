# Experimental native bridge: build, install and remove

This is a separate NB2 C++ experiment for an explicitly tested DigitalMicrograph
build. Keep the default v0.6 Python/TCP configuration unchanged. Do not load the
experimental plugin in a production acquisition session. Use an idle test host
and keep source images unchanged while requests run. This code does not control
the microscope.

The [adapter matrix](ADAPTERS.md) currently supports only the exact Windows x64
GMS 3.53.4137.0 profile with all five pinned module fingerprints matching.
Profile selection and each admitted operation have separate bounded real-host
qualification; see [operation acceptance](OPERATIONS_ACCEPTANCE.md). New clients explicitly
reject an old NB1 DLL and never downgrade the protocol.

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
only. Also inspect compatibility: `SUPPORTED` admits the matching profile;
`UNSUPPORTED_BUILD`, `ABI_MISMATCH` and `NOT_READY` reject image operations.
`native_statistics` is the complete four-reduction SUMMARY group, with
`native_mean` reported separately. The fourteen-tool catalog additionally exposes
limited arithmetic, Fourier, filters, preview and numeric READ; see the
[tool table](README.md#public-native-tools) and [data handoff workflow](NATIVE_WORKFLOW.md).
Explicit-ID half-open `dm_crop` creates a separate
native image retained by the plugin until normal native STOP/cleanup; it does
not create a visible DM document. The mean tool is not a replacement for the
full statistics tool. The strict core acceptance client does not call crop.
An unavailable adapter capability rejects before image lookup. Do not infer
support from tool discovery or symbol presence alone. Preview is display-only;
READ plus the explicit external encoder is NPY data handoff, not native SaveAs.

For ordinary 2D uint32, follow the separate [uint32 acceptance](UINT32_ACCEPTANCE.md)
and check its dtype capabilities and current prepared/production qualification.
The prepared trial, original-STOP release, normal exit and owned-plugin removal
are separate from final production acceptance. Mean/SUMMARY allow at most
2,097,152 pixels, preserving the worst-case integer-sum bound below 2^53;
fractional mean remains binary64. Crop requires complete spatial calibration,
a source of at most 4,194,304 pixels, and same-dtype output of at most 4 MiB
(1,048,576 pixels). Preview has that source bound and at most 128x128 samples;
READ has that source bound and at most 16,384 ROI samples/65,536 raw bytes.
Explicit saved-response encoding preserves `<u4` NPY bytes; the external
example records exact integer sum/float64 mean and provenance in a new directory.
Do not convert uint32 to float32 or substitute PNG for numerical input.
Arithmetic, Fourier, filters and eligible retained-result SHOW require their
[separate uint32 operation capabilities](UINT32_OPERATIONS_ACCEPTANCE.md).
Native output dtype and rounding are explicit; no bridge cast is performed.
The scientific READ/NPY path exports the actual result dtype. Native SaveAs
remains unavailable. Other integers, native 4D, real data and model-client
use are not qualified by this trial. The default backend and client entries
remain unchanged; the existing float32 commands below retain their own fixtures.

Qualified real-host name checks use ASCII synthetic names. An independent
comparison of non-ASCII names between legacy GMS Python bindings and native
`GetUnicodeName` failed and remains NOT_QUALIFIED. Do not silently recode image
names or overwrite the original failed truth to make acceptance pass; the
native UTF-16/UTF-8 path has no heuristic encoding repair.

Crop requires an explicit `request_id` saved before submitting; newly added
side-effect tools follow the same rule. Save its session, tool and arguments
too. Read-only status/datasets/mean/SUMMARY calls permit generated-ID
compatibility, but the operator trial supplies IDs for all calls.
After a timeout, cancellation or disconnect, query that ID with
`dm_native_result`; never automatically resubmit the original operation.
`queued`, `running` and `unknown` are not successful completion. Cancellation
only ends local waiting, and a request may still execute in the host. Query
recovery applies only to the original running session's retained records.
After STOP, DM exit/restart or a new session, recovery is not promised; do not
replay an old operation ID as a new request.

NB2 receipts bind `original_operation`, `normalized_args`, `result_type` and
`result_version` to the immutable accepted request, including QUERY recovery.
Unknown IDs have all four fields `null`. Keep the pre-submission record and
validate the returned operation contract; do not infer it from payload fields.

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
that deadline effective if stdout stalls. Independent visual acceptance and
the post-run source-invariance check in `verify_fixture.py` remain separate.

Native crop has a separate [strict MCP acceptance client](accept_crop_mcp.py),
an independent one-shot [pixel/calibration oracle](verify_crop.py), and a
post-STOP [output-ownership check](verify_stopped_outputs.py). These scripts
must agree on the same prepared synthetic session and private evidence
directory. Invoking or compiling them does not mean crop passed in DM; see
[RESULTS.md](../RESULTS.md) for its current acceptance status. GMS Python oracle
scripts run once inside DM after native calls have finished; they are not
resident listeners and must release their image/array references before an
output-lifetime check.

Follow [TRIAL_ACCEPTANCE.md](TRIAL_ACCEPTANCE.md) for the complete synthetic
fixture, `accept_trial_mcp.py`, independent oracle and saved-STOP sequence.
Its answers and evidence remain private. No existing client entry is edited
by these instructions or scripts.

An earlier limited strict synthetic session passed `dm_native_show` receipt/identity,
independent visibility, unique-document and post-STOP ownership checks. It
targets only an already retained crop by exact ID and a saved show request ID,
without a path or file save. Closing only the delivered document made its image
ID invalid while preserving other sources. The host then exited normally and
its manifest-owned DLL was removed. Older observations remain UNVERIFIED when
their original STOP request is missing; do not backfill that record.

Repeat the full sequence for changed implementations: before-STOP oracle,
saved original STOP request, after-STOP oracle, normal closure of only the
delivered document, then [verify_trial_closed.py](verify_trial_closed.py) while
DM still runs. Whole-host exit cannot substitute for the last-reference check.
SUMMARY has a separate [acceptance procedure](SUMMARY_ACCEPTANCE.md). Never
force termination or remove a loaded DLL.

## Stop IPC, close the test host and remove

1. Disconnect every MCP client and finish or inspect any outstanding operation
   using its saved ID. Do not assume that a client timeout stopped native work.
2. Save a fresh STOP ID and use the explicit NB2 helper with the previously
   confirmed target DM PID and a new request-record path:

   ```powershell
   $stopRequestId = 'stop-' + [guid]::NewGuid().ToString('N')
   $stopRequestRecord = Join-Path $stateDir ($stopRequestId + '.request.json')
   $stopEvidence = Join-Path $stateDir ($stopRequestId + '.json')
   python -B .\experiments\native-bridge\mvp\stop_native.py --session $env:DM_NATIVE_SESSION --request-id $stopRequestId --expected-host-pid $testDmPid --request-record $stopRequestRecord --evidence $stopEvidence
   ```

   The helper exclusively creates the original request record, flushes and
   fsyncs it before connecting or sending. It records NB2/session/ID/STOP,
   empty arguments, target PID and the exact wire line. Existing evidence or
   failure to persist that record refuses dispatch. Never reconstruct this
   record from a later receipt. For the trial oracle, use the fixed filenames
   `stop-request.json` and `stop-receipt.json` in that trial's evidence directory.

   The helper submits once and checks the bounded JSON frame, identity, state,
   process/thread fields and timings. Require `state=completed`,
   `original_operation=STOP`, `normalized_args=[]`, `result_type=ipc_stop`,
   `result_version=1` and `result.ipc_stopped=true`.
   STOP is an IPC acknowledgement on the worker, so
   `exec_tid=0` is expected; it is not a DM API execution receipt. The normal
   MCP catalog does not expose STOP. A missing/invalid receipt is unresolved
   and must be investigated. Allow the host cleanup callback to complete and
   confirm the experimental pipe/window are gone; an acknowledgement alone
   does not establish every cleanup postcondition.
   The one-shot trial oracles additionally bind the receipt PID to their own
   actual `os.getpid()` and match STOP to the original request record. Missing
   old evidence remains UNVERIFIED. For continuing observations in a preserved
   old session, follow [the unlock checklist](UNLOCK_CHECKLIST.md); its explicit
   `observe_legacy_stop` mode can never produce a qualification PASS.
   The separate `DM_NATIVE_ORACLE_PROTOCOL=NB1_LEGACY` setting is only for
   read-only inspection of historical NB1 evidence; the STOP helper never
   sends NB1 or backfills a missing original record.
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
