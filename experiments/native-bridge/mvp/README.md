# Native bridge MVP

The historical mainline integration retained `3c9715c` plus the mandatory crop
request-ID safeguard. This feature preserves that safeguard and adds the
separately qualified work below; see [mainline scope history](../../../docs/NATIVE_MERGE_SCOPE.md).

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

**Historical limited synthetic real-host acceptance passed.** An earlier
strict session passed native SUMMARY, crop/QUERY/duplicate/conflict and SHOW,
with independent full-pixel, calibration, source and unique-document checks.
SHOW remained visible after STOP released plugin references; closing only its
document invalidated the output ID while preserving the other sources. STOP
matched its original pre-submission request record and actual oracle PID.
The test host exited normally and only its manifest-owned DLL was removed.
The preserved older session was also observed and cleaned normally, but its
missing original STOP request leaves its historical qualification UNVERIFIED.
See [HANDOFF.md](HANDOFF.md) and [RESULTS.md](../RESULTS.md) for scope limits.

NB2/profile selection, small-input arithmetic/Fourier/filter/preview and the
explicit READ-to-NPY workflow have separate synthetic real-host evidence.
Consult [operation acceptance](OPERATIONS_ACCEPTANCE.md) for the exact scope
and the distinction between prepared and final production-admission builds.
The [adapter matrix](ADAPTERS.md) lists the exact
Windows x64 GMS 3.53.4137.0 profile; no other build is supported. Status reports
`SUPPORTED`, `UNSUPPORTED_BUILD`, `ABI_MISMATCH` or `NOT_READY`. Five exact
module fingerprint gates remain required before vendor calls.
`native_statistics` means the complete four-reduction SUMMARY group;
`native_mean` is a separate capability, not a partial statistics group.

The ordinary Python backend stays the default. Selecting
`DM_MCP_BACKEND=native` selects this experimental backend and its own tool
catalog; it never starts or falls back to the resident Python bridge.

Future processing extensions call DM's own operators; the bridge handles
parameters, ownership and result delivery. It does not implement a parallel
analysis engine. Arithmetic, [FFT and components](FFT_READINESS.md), filters,
preview and bounded numeric READ are explicit tools in the nineteen-entry native
catalog. Each still requires the selected adapter's qualified capability.
Follow [the researcher workflow](NATIVE_WORKFLOW.md) for scientific handoff;
the saved-response encoder and external example never run as hidden fallbacks.

The [batch candidate inventory](BATCH_CANDIDATES.md) prepares typed calls and
synthetic ownership tests for further DM operators. That module remains
outside the product plugin. The four SUMMARY reductions now have a separate
qualified adapter path. New candidate operators still require individual
ABI, scientific, source-protection and lifecycle qualification before admission.

## Public native tools

| Tool | Scope |
|---|---|
| `dm_status` | Host readiness, build gate, native capabilities and limitations |
| `dm_datasets` | Bounded image enumeration with numeric ID, name, shape, known dtype and dimension calibration |
| `dm_native_mean` | Raw intensity mean for explicit-ID 2D float32 (at most 4,194,304 pixels) or ordinary-packed uint32 (at most 2,097,152); subject to dtype qualification below |
| `dm_native_summary` | DM's minimum, maximum, sum and mean within the same dtype/pixel limits; raw intensity, no stddev/variance |
| `dm_native_result` | Query the retained receipt using its original operation ID |
| `dm_crop` | Explicit-ID half-open crop into a separate same-dtype plugin-retained image with full spatial calibration; uint32 source at most 4,194,304 pixels, output at most 4 MiB (1,048,576 pixels) |
| `dm_native_show` | Exact qualified 2D plugin-result delivery to a visible DM document; saved request ID required; uint32 admits qualified crop/filter results, not 1D profiles; document lifetime is separate from file persistence |
| `dm_native_unary` | Native negate, absolute value and square of qualified float32/uint32 2D inputs; actual output dtype is explicit |
| `dm_native_binary` | Native add, subtract and multiply; same shape and calibration, no broadcasting |
| `dm_native_fft` | Small real forward FFT and paired inverse of the retained full-complex result; explicit Fourier v2 conventions |
| `dm_native_complex` | Real, imaginary, phase in radians or power (squared magnitude) of qualified retained Fourier results |
| `dm_native_filter` | Small qualified float32/uint32 smooth, Sobel, Laplace and sharpen with explicit output dtype and vendor borders |
| `dm_native_preview` | Ordinary float32/uint32 source at most 4,194,304 pixels, at most 128x128 display samples; PNG and source-coordinate mapping, not numeric export |
| `dm_native_read` | Ordinary float32/uint32 source at most 4,194,304 pixels, explicit half-open ROI at most 16,384 samples/64 KiB; raw little-endian bytes and calibration, no file write |
| `dm_native_result_info` | Fresh availability snapshot for exact output ID and creation retention token; old QUERY stays historical |
| `dm_native_release` | Saved-request-ID release of only the exact plugin result reference; no document closure or mutation of old records |
| `dm_native_rois` | Explicit image → document/display/ROI identity; new v2 replies preserve rectangle and line geometry with eligibility diagnostics |
| `dm_native_profile` | Saved-ID native extraction from an explicitly identified width-one integer horizontal/vertical GUI line; true 1D float64 image and frozen numeric snapshot |

The profile path has limited synthetic-host qualification, including separate
fresh-host confirmation of the final qualified artifact and its exact loaded
identity. Independent source/GUI, raw 1D values, NPY, original-ID recovery,
RELEASE/STOP, idle-reference cleanup, normal exit/removal and post-exit files
passed. These were API-created synthetic GUI lines, not model-client acceptance. It
requires matching nonzero signed spatial scales/units, complete calibration and
the qualified direct 2D source layout. Known Fourier lineage is refused. Native
profile samples include both ordered endpoints, at most 4096 samples; raw
intensity remains unapplied despite copied intensity calibration. The explicit
saved-response encoder writes actual `[N]` `<f8` NPY/schema-1 files, not a row
image or DM SaveAs. Existing 2D READ/SHOW still reject these 1D objects. See
[profile acceptance and delivery](../../../docs/NATIVE_LINE_PROFILE.md) and
[the current handoff](HANDOFF.md) for preserved failures and artifact status.

The uint32 prepared trial and its original-STOP output release, normal host exit
and manifest-owned removal have their own bounded evidence. Final production
qualification is recorded separately in [uint32 acceptance](UINT32_ACCEPTANCE.md);
earlier float32 production PASS does not qualify a changed uint32 build.
The statistics bound keeps every possible uint32 sum below 2^53; a fractional
mean is a binary64 result, not an exact rational. Missing spatial units may be
reported for raw mean/SUMMARY and READ; crop still requires complete calibration.
The explicit encoder writes exact `<u4` NPY bytes without float32 conversion.
Its optional external example records an exact integer sum and float64 mean,
script, parameters and input hashes; it is never a native fallback.
UNARY/BINARY, FFT/components, filters and eligible retained-result SHOW have
[separate uint32 qualification](UINT32_OPERATIONS_ACCEPTANCE.md), with explicit
native result types and precision. Arithmetic returns float32; Smooth/Sharpen
return saturated/truncated uint32; Sobel/Laplace return float32; FFT rounds
input to binary32 and returns complex64. They do not preserve arbitrary integer
precision. The original uint32 READ path remains exact; export processed
results using their actual dtype.
Other integers, native 4D, real experimental data and model-client acceptance
remain outside this extension. Native SaveAs/Open remains unavailable.

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

This is not the complete `dm_stats` interface. Native SaveAs/Open, arbitrary
script execution, spectrum/4D tools and hardware controls are not exposed in
the native catalog. A cropped image is retained by bounded plugin-owned
references until exact-token release or native STOP/cleanup. No visible document, displayed image or
model visual acceptance is implied by the crop ID alone.

`dm_native_show(image_id, request_id)` calls the native display path only for an existing
qualified plugin-retained result by its exact ID, without making another data copy or
accepting a file path. It requires a separately saved request ID. This
native completed receipt, same-image recovery, actual visibility and unique
document ownership passed separate limited synthetic checks. The document
retained the image after STOP; normal document closure released the last image
reference. This is session-lifetime delivery, not a file save or an MCP preview.
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
source preservation require their own evidence. The earlier limited strict-session checks
passed; historical missing evidence is not repaired by that later PASS.
Use [SUMMARY_ACCEPTANCE.md](SUMMARY_ACCEPTANCE.md) for its independent scalar,
nontrivial intensity-calibration and all-source checks. Four native reductions
are sequential, with `snapshot_atomic:false`; no concurrent-edit protection is
claimed.

## Protocol and lifecycle

Each connection carries one ASCII request ending in LF:

```text
NB2 <32-lowercase-hex-session> <request-id> <operation> [uint32 arguments]
```

The complete request is at most 512 bytes including LF. IDs match
`[A-Za-z0-9_-]{1,64}`. Fields use one space; argument counts, integer syntax and
overflow are checked exactly. Supported transport forms are `STATUS`,
`DATASETS`, `INFO image_id`, `MEAN image_id`, `SUMMARY image_id`, `CROP image_id x0 y0 x1 y1`,
`SHOW image_id`, `QUERY` and `STOP`. Rectangular upper bounds are exclusive. INFO is a direct
acceptance/client operation, not a separate public MCP tool. Native crop
support remains build-specific and experimental despite its limited acceptance.
The closed internal operation set also includes `UNARY image_id opcode`,
`BINARY lhs_id rhs_id opcode`, `FILTER image_id filter_kind`, `FFT image_id`,
`IFFT image_id`, `REAL image_id`, `IMAG image_id`, `VENDOR_ARG image_id`,
`VENDOR_NORM image_id`, `PREVIEW image_id max_width max_height` and
`READ image_id x0 y0 x1 y1`, `RESULT_INFO image_id retention_token`,
`RELEASE image_id retention_token`, `ROIS image_id` and
`PROFILE image_id document_id display_id roi_id x0 y0 x1 y1 width`.
PROFILE line endpoints are inclusive pixel centres, not half-open rectangle
edges. These fixed forms back the public tools above;
they are not an arbitrary script or symbol interface.

Each response is one UTF-8 JSON value ending in LF, bounded to 128 KiB including
LF. It includes `protocol`, `session`, `id`, `state`, `host_pid`, `worker_tid`,
`exec_tid`, queue/execute timings in `timings_us`, and the four immutable identity
fields `original_operation`, `normalized_args`, `result_type`, `result_version`.
For an accepted record, every queued/running/completed/failed receipt and QUERY
uses its original operation and normalized argument array, with result contract
version 1, except Fourier v2 and new ROIS v2 submissions. Historical v1 QUERY
records retain their original schema; they do not acquire line semantics.
QUERY does not replace that operation with `QUERY`. Unknown IDs and
unadmitted requests carry `null` in all four identity fields; an ID conflict
reports the existing record's identity. Clients validate that identity before
dispatching to an operation-specific result validator, without guessing from
payload fields. `result` appears only for
`completed`; `error` and `code` appear only for `failed`. Oversized results are
rejected explicitly instead of truncated. Negative and fractional means retain
their native double representation; nonfinite values are rejected.

New clients and the plugin speak NB2 only. An old NB1 DLL or request is
explicitly rejected; there is no protocol downgrade or backend fallback.
Read-only historical oracles may explicitly select
`DM_NATIVE_ORACLE_PROTOCOL=NB1_LEGACY` to inspect existing NB1 evidence. This
does not send NB1 requests or qualify the current NB2 implementation.

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
side-effect tools, including experimental native show, follow the same rule.
`dm_native_result` requires the original ID. Existing read-only status,
datasets, mean and read-only summary calls permit generated IDs, but
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
That earlier ownership test covered an unshown output. The later strict SHOW
test separately verified a visible DM document retaining the exact crop after
STOP, followed by final image release when only that document was closed.
This does not extend delivery to unrelated images or permanent files.

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
.\experiments\native-bridge\mvp\build\candidate_calls_tests.exe
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

The Windows E2E test connects the actual stdio MCP server, NB2 named pipe,
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
Missing old records remain UNVERIFIED. The separate
`DM_NATIVE_ORACLE_MODE=observe_legacy_stop` observation mode uses separate
outputs and cannot produce PASS; it does not relax process, pixel, calibration
or document checks. This missing-record policy is separate from the explicit
NB1_LEGACY protocol reader. [The unlock checklist](UNLOCK_CHECKLIST.md)
preserves historical continuation steps; use [the integration plan](INTEGRATION_PLAN.md)
before a future main reconciliation. The Unicode diagnostic independently
records bytes/text and exceptions without guessing a codec or qualifying UI
behavior.

See [the validation matrix](../RESULTS.md), [ABI contracts](../ABI_NOTES.md),
[installation and rollback](INSTALL.md), and the concise
[continuation handoff](HANDOFF.md). The root-level
[native MCP configuration example](../../../mcp.native.json.example) is opt-in;
it does not change client configuration automatically.

See [result lifetime and complete bounded handoff](../../../docs/NATIVE_LIFECYCLE_HANDOFF.md) for the additive release/availability tools, original-ID recovery and the explicit chunked NPY helper. Existing backend selection and installation boundaries are unchanged.
