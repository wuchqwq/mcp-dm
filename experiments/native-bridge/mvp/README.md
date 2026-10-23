# Native bridge MVP

Mainline integration note: this snapshot retains the reviewed `3c9715c` native implementation. Native `dm_crop` now requires the caller to save and supply `request_id` before dispatch; read-only tool IDs remain optional. Later SHOW delivery and raw-mean policy changes stay on the feature branch until their separate acceptance is complete. See [merge scope](../../../docs/NATIVE_MERGE_SCOPE.md).

An opt-in, build-pinned C++ backend for a small set of DigitalMicrograph
post-acquisition operations. The target is Windows x64 GMS **3.53.4137.0**.
Exact host/module identities are checked before image operations. Core status,
metadata and native mean have passed limited real-DM acceptance with synthetic
inputs, including strict MCP calls and unchanged-source checks. Native crop
also passed separate real-host MCP and independent pixel/calibration checks
with ASCII fixture names. A separate post-STOP check verified release of the
plugin-retained crop and removal of the experimental pipe/window, with ordinary
Python still usable.
The test host subsequently exited normally and manifest-based removal restored
the prior plugin inventory by removing only this experiment's owned DLL.
Existing client configuration remained unchanged.
Offline tests use an explicitly synthetic host and do not
load Gatan code; their PASS remains separate from real-host acceptance.

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
| `dm_crop` | Experimental explicit-ID half-open crop into a separate plugin-retained image; limited real-host numerical/copy acceptance PASS |

This is not the complete `dm_stats` interface. Export, preview, arbitrary
script execution, spectrum/4D tools and hardware controls are not exposed in
the native catalog. A cropped image is retained by bounded plugin-owned
references until native STOP/cleanup. No visible document, displayed image or
model visual acceptance is implied by its returned ID.

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
without units need not prevent other datasets from being listed. Numerical
operations still require usable calibration. The mean reports raw intensity,
with no intensity-calibration application.

## Short tasks for a connected agent

These prompts use the published tools and need no Skill installation or source
reading. They are suggested client acceptance tasks, not evidence that
WorkBuddy or another model client has passed:

1. "Check `dm_status`. Report the actual backend, readiness, build gate and
   receipt identity. Continue only with `digitalmicrograph-native` ready."
2. "List datasets and use my specified numeric image ID for a native mean.
   Report its shape, dtype, complete physical calibration and raw mean; mark
   unknown units or unsupported inputs explicitly."
3. "For my specified image ID and half-open rectangle, make a separate native
   crop. Save its request ID, report the new image ID, and compare its dtype,
   dimensions, signed scales and physical pixel-zero shift with the source.
   Do not claim a visible window or an unchanged-source proof from the receipt
   alone. If the wait expires, query that same request ID."
4. "Check a safe invalid parameter such as a fractional image ID. Confirm an
   explicit error, inspect both RPC and tool-error status, and ensure no
   fallback or successful-image claim is reported."

## Protocol and lifecycle

Each connection carries one ASCII request ending in LF:

```text
NB1 <32-lowercase-hex-session> <request-id> <operation> [uint32 arguments]
```

The complete request is at most 512 bytes including LF. IDs match
`[A-Za-z0-9_-]{1,64}`. Fields use one space; argument counts, integer syntax and
overflow are checked exactly. Supported transport forms are `STATUS`,
`DATASETS`, `INFO image_id`, `MEAN image_id`, `CROP image_id x0 y0 x1 y1`,
`QUERY` and `STOP`. Rectangular upper bounds are exclusive. INFO is a direct
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

A client timeout, cancellation or disconnect stops only the client's wait.
It does not cancel a native operation or free its record. Treat an unresolved
outcome as `unknown`, retain its session/ID, and query it; never automatically
resubmit an operation. `unknown` is not success or proof of cancellation.

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

Separate real-host crop acceptance verified strict MCP creation of a new image
ID, identical results for a repeated request ID and safe rejection of an
out-of-bounds ROI. An independent one-shot GMS Python oracle verified every
cropped pixel, dtype, shape, separate memory, signed calibration and unchanged
source pixels/calibration. It did not rely on the native mean alone. The
post-crop STOP ownership check separately confirmed that the hidden crop ID
became invalid after cleanup and ordinary Python remained usable. This does
not establish hot-unload safety or general concurrent API behavior.

Real-host acceptance verified ordinary one-shot Python after native work,
without a resident Python listener. It also verified rejection of an ID after
the synthetic document and its remaining Python references were released.
These observations do not establish concurrent script/native image safety,
general invalid-pointer recovery, real experimental-data support or other
GMS-build compatibility. WorkBuddy and model visual acceptance remain
**NOT_TESTED**. See [RESULTS.md](../RESULTS.md) for initial failures and corrected
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
node --test tests/native-bridge.test.mjs tests/native-mcp.test.mjs
```

Omit `-OfflineOnly` to build `dm_native_bridge.dll` as well. Build output paths
can be changed with `-OutputDirectory`; pass the matching `--exe` path to the
Python transport tests. Neither compilation nor these tests installs a plugin,
starts DM or proves real-host execution. `fake_host.exe` and the adapter tests
use synthetic callbacks, not Gatan modules.

See [the validation matrix](../RESULTS.md), [ABI contracts](../ABI_NOTES.md),
[installation and rollback](INSTALL.md), and the concise
[continuation handoff](HANDOFF.md). The root-level
[native MCP configuration example](../../../mcp.native.json.example) is opt-in;
it does not change client configuration automatically.
