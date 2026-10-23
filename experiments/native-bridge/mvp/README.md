# Native bridge MVP

An opt-in, build-pinned C++ backend for a small set of DigitalMicrograph
post-acquisition operations. The target is Windows x64 GMS **3.53.4137.0**.
Exact host/module identities are checked before image operations. Earlier core status,
metadata and native mean have passed limited real-DM acceptance with synthetic
inputs, including strict MCP calls and unchanged-source checks. Native crop
also passed separate real-host MCP and independent pixel/calibration checks
with ASCII fixture names. A separate post-STOP check verified release of the
plugin-retained crop and removal of the experimental pipe/window, with ordinary
Python still usable.
That earlier test host subsequently exited normally and manifest-based removal restored
the prior plugin inventory by removing only this experiment's owned DLL.
Existing client configuration remained unchanged.
Offline tests use an explicitly synthetic host and do not
load Gatan code; their PASS remains separate from real-host acceptance.

**Current revision: HOLD pending desktop acceptance.** Actual strict stdio MCP
passed calibrated/empty-unit raw means, metadata/limitations, safe failures,
crop ID recovery/conflict checks and native SHOW receipts for the explicit
crop. Independent visible-document, document-count, full-pixel/source and
post-STOP ownership checks remain NOT_TESTED. STOP acknowledged and removed
the native pipe/window; the test host is still running with the DLL loaded
and manifest installed. Complete the independent post-STOP oracle, normal
exit and ownership-based removal before declaring this trial complete. See
[HANDOFF.md](HANDOFF.md) for the continuation state.

The ordinary Python backend stays the default. Selecting
`DM_MCP_BACKEND=native` selects this experimental backend and its own tool
catalog; it never starts or falls back to the resident Python bridge.

## Public native tools

| Tool | Scope |
|---|---|
| `dm_status` | Host readiness, build gate, native capabilities and limitations |
| `dm_datasets` | Bounded image enumeration with numeric ID, name, shape, known dtype and dimension calibration |
| `dm_native_mean` | Raw pixel intensity mean for a bounded 2D float32 image selected by explicit ID |
| `dm_native_result` | Query the retained receipt using its original operation ID |
| `dm_crop` | Explicit-ID half-open crop into a separate plugin-retained image; current strict MCP checks passed, current independent full-pixel/source oracle pending; earlier copy acceptance is separate |
| `dm_native_show` | P1 exact plugin-crop display; saved request ID required, native receipt/identity passed, independent desktop acceptance NOT_TESTED |

Current P0 policy separates raw intensity from spatial calibration. A known
missing unit, zero/nonfinite spatial scale or unusable spatial origin does not
by itself prohibit a supported raw mean. The result retains
`calibration_complete:false` and specific per-axis issues; it still reports
`intensity_calibration_applied:false`, with `intensity_semantics` set to
`raw pixel intensity`. Crop continues to require usable spatial calibration. Invalid
IDs, unsupported dtype/dimensions, work budgets, nonfinite mean results and
native/ABI failures remain errors. The empty-unit case passed separate
actual-host mean/metadata checks; other invalid spatial-number cases currently
have offline surrogate coverage only.

This is not the complete `dm_stats` interface. Export, preview, arbitrary
script execution, spectrum/4D tools and hardware controls are not exposed in
the native catalog. A cropped image is retained by bounded plugin-owned
references until native STOP/cleanup. No visible document, displayed image or
model visual acceptance is implied by the crop ID alone.

P1 candidate: `dm_native_show(image_id, request_id)` calls the native display path only for an existing
plugin-retained crop by its exact ID, without making another data copy or
accepting a file path. It requires a separately saved request ID. This
candidate's native completed receipt and same-image recovery were accepted
through actual MCP. Actual visibility, document count and post-STOP document
ownership remain **NOT_TESTED**. A completed receipt without seeing the image
is not visual acceptance, a file save or proof that the model saw it.
Native saving remains unavailable: the `SaveAsGatan` string ABI and
exclusive/no-overwrite behavior are not sufficiently established. See the
[acceptance procedure](TRIAL_ACCEPTANCE.md) before treating P1 as delivered.

The accepted real-host name scope is ASCII. An independent comparison of
non-ASCII names between legacy GMS Python `SetName`/`GetName` and native
`GetUnicodeName` failed; that interoperability is **NOT_QUALIFIED**. The original
failure was preserved, and a new ASCII-qualified fixture was accepted without
overwriting its original truth. Native strings still use the explicit
UTF-16-to-UTF-8 path; no heuristic conversion or general Chinese-name fix is
claimed.

Image metadata and results are not atomic snapshots. A source can change
between calls. DM dimensions are ordered x, y, ...; row-major shapes reverse
that ordering. The calibration field `origin` is the raw DM index-origin value;
it is not a physical zero. Use `calibrated_value_at_pixel_zero + i * scale`
for the physical coordinate, preserving the sign of `scale` and the declared
unit. Enumeration marks incomplete calibration with
`calibration_complete:false` and per-axis issues, so a hidden utility image
without units need not prevent other datasets from being listed. Raw mean can
remain supported with incomplete spatial calibration, which is reported as a
limitation rather than converted to invented units. Crop still requires usable
calibration. The mean never applies intensity calibration.
`native_mean_supported` reports dtype/dimension/budget eligibility; a native
failure or nonfinite result can still reject the operation.

## Acceptance procedure

Use [TRIAL_ACCEPTANCE.md](TRIAL_ACCEPTANCE.md) for synthetic input creation,
strict stdio MCP checks, independent pixel/calibration oracles and the saved
STOP/document-lifetime sequence. Protocol receipts, actual visibility and
source preservation require their own evidence. The current HOLD remains.

## Protocol and lifecycle

Each connection carries one ASCII request ending in LF:

```text
NB1 <32-lowercase-hex-session> <request-id> <operation> [uint32 arguments]
```

The complete request is at most 512 bytes including LF. IDs match
`[A-Za-z0-9_-]{1,64}`. Fields use one space; argument counts, integer syntax and
overflow are checked exactly. Supported transport forms are `STATUS`,
`DATASETS`, `INFO image_id`, `MEAN image_id`, `CROP image_id x0 y0 x1 y1`,
`SHOW image_id`, `QUERY` and `STOP`. Rectangular upper bounds are exclusive. INFO is a direct
acceptance/client operation, not a separate public MCP tool. Native crop
support remains build-specific and experimental despite its limited acceptance.

Each response is one UTF-8 JSON value ending in LF, bounded to 128 KiB including
LF. It includes `protocol`, `session`, `id`, `state`, `host_pid`, `worker_tid`,
`exec_tid`, and queue/execute timings in `timings_us`. `result` appears only for
`completed`; `error` and `code` appear only for `failed`. Oversized results are
rejected explicitly instead of truncated. Negative and fractional means retain
their native double representation; nonfinite values are rejected.

The named pipe is session-specific, permits the current Windows user, and
rejects remote clients. A worker only handles transport/state. Native work is
dispatched through a message-only window on the startup thread. Pipe existence
is insufficient for readiness: the queued host readiness callback must run.

One operation may be queued or running. Each accepted operation has an
immutable ID/parameter binding and its own retained state. Submit once, then
`QUERY` the same ID. Repeating an identical submission returns its existing
record without executing again; reusing that ID with different parameters
fails. `QUERY` does not create a record. The session retains up to 1023 ordinary
operation records plus one STOP receipt, without eviction.

`dm_crop` requires a caller-saved `request_id` before submission; newly added
side-effect tools, including the P1 show candidate, follow the same rule.
`dm_native_result` requires the original ID. Existing read-only status,
datasets and mean calls retain optional generated IDs for compatibility, but
the operator trial supplies explicit IDs for every call. Save the original
session, operation, arguments and ID before dispatch rather than depending on
a response that cancellation might suppress.

A client timeout, cancellation or disconnect stops only the client's wait.
It does not cancel a native operation or free its record. Treat an unresolved
outcome as `unknown`, retain its session/ID, and query it; never automatically
resubmit an operation. `unknown` is not success or proof of cancellation.
Recovery is only within the same running session and its in-memory retained
records. After STOP, DM exit/restart or a new session, QUERY recovery is not
promised; an old ID must not be replayed as a new operation.

STOP ends only the experimental IPC; it does not close DM. The worker posts host cleanup, which
releases adapter references, window and events after confirming worker exit.
Native callback activity blocks close approval and defers reentrant cleanup
until the callback returns. A stopped instance does not restart automatically.
The plugin lifecycle owns its object; a window callback never deletes itself.
Normal shutdown is the supported lifecycle; hot unloading is not accepted.

Use an idle host with serialized operations. Do not invoke native image work
while a script, acquisition, another plugin or a user edit is modifying images.
The bridge has no general host activity lock. Vendor native faults are not
isolated, and C++ catches do not guarantee recovery from access violations.

Earlier separate real-host crop acceptance verified strict MCP creation of a new image
ID, identical results for a repeated request ID and safe rejection of an
out-of-bounds ROI. An independent one-shot GMS Python oracle verified every
cropped pixel, dtype, shape, separate memory, signed calibration and unchanged
source pixels/calibration. It did not rely on the native mean alone. The
post-crop STOP ownership check separately confirmed that the hidden crop ID
became invalid after cleanup and ordinary Python remained usable. This does
not establish hot-unload safety or general concurrent API behavior.
That earlier ownership test covered an unshown output. The P1 candidate is intended to let a
visible DM document retain the crop independently; STOP must not close that
document. Continued document ownership after STOP still requires its own
real-host test.

Earlier real-host acceptance verified ordinary one-shot Python after native work,
without a resident Python listener. It also verified rejection of an ID after
the synthetic document and its remaining Python references were released.
These observations do not establish concurrent script/native image safety,
general invalid-pointer recovery, real experimental-data support or other
GMS-build compatibility. Model visual acceptance remains **NOT_TESTED**.
See [RESULTS.md](../RESULTS.md) for initial failures and corrected
acceptance boundaries.

## Build and offline tests

Use a Windows x64 LLVM-MinGW toolchain with Windows headers/import libraries
and a C++17 standard library. Supply its compiler path with `-Cxx`, or put the
compiler on PATH. No Gatan SDK or vendor binary is bundled. The build uses a
static C++ runtime while retaining Windows/UCRT dependencies; it is not a
CRT-free plugin.

From the repository root:

```powershell
.\experiments\native-bridge\mvp\build.ps1 -Cxx clang++.exe -OfflineOnly
.\experiments\native-bridge\mvp\build\core_tests.exe
.\experiments\native-bridge\mvp\build\adapter_tests.exe
python -B .\experiments\native-bridge\mvp\test_transport.py
$env:DM_NATIVE_FAKE_HOST_EXE = (Resolve-Path .\experiments\native-bridge\mvp\build\fake_host.exe).Path
node --test tests/native-bridge.test.mjs tests/native-mcp.test.mjs tests/native-e2e.test.mjs
python -B -m unittest discover -s tests -p 'test_native_trial_oracles.py' -v
python -B -m unittest discover -s tests -p 'test_native_stop_helper.py' -v
python -B -m unittest discover -s tests -p 'test_native_unicode_probe.py' -v
```

Omit `-OfflineOnly` to build `dm_native_bridge.dll` as well. Build output paths
can be changed with `-OutputDirectory`; pass the matching `--exe` path to the
Python transport tests. Neither compilation nor these tests installs a plugin,
starts DM or proves real-host execution. `fake_host.exe` and the adapter tests
use synthetic callbacks, not Gatan modules.

The Windows E2E test connects the actual stdio MCP server, NB1 named pipe,
message window and C++ retained-state core. C++ emits an execution-start
event before the test cancels the MCP wait. A fresh Node client then queries
the saved ID, including after delayed completion, and C++ creation counters
check that recovery did not create another object. Its document counters are
synthetic; they do not establish actual DM visibility or ownership.

Without an explicit executable, the E2E test can build its own fake host using
the local compiler in `DM_NATIVE_TEST_CXX` (or `clang++.exe` on PATH). It never
downloads a compiler. Non-Windows runs or a missing compiler without explicit
configuration produce an explicit SKIP; a configured compiler or executable
failure fails the test. Only the fake host
recognizes the test-only `NB_FAKE_E2E` controls and per-session event gates.

The oracle fault suite runs the real one-shot scripts in isolated Python
subprocesses with a synthetic DM API. Positive controls must pass; changed
pixels, calibration, record identity and document counts must fail at their
intended checks without writing a PASS report. This checks the acceptance
scripts themselves and does not execute an oracle in DM.

The trial oracles compare native receipt identity with their actual process
PID and bind STOP to an original request record persisted before submission.
Missing old records remain UNVERIFIED. The explicit legacy observation mode
uses separate outputs and cannot produce PASS; it does not relax process,
pixel, calibration or document checks. Follow [the unlock checklist](UNLOCK_CHECKLIST.md)
for the preserved session, and [the integration plan](INTEGRATION_PLAN.md)
before a future main reconciliation. The Unicode diagnostic independently
records bytes/text and exceptions without guessing a codec or qualifying UI
behavior.

See [the validation matrix](../RESULTS.md), [ABI contracts](../ABI_NOTES.md),
[installation and rollback](INSTALL.md), and the concise
[continuation handoff](HANDOFF.md). The root-level
[native MCP configuration example](../../../mcp.native.json.example) is opt-in;
it does not change client configuration automatically.
