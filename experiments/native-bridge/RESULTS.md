# Native bridge validation matrix

## Integration follow-up: scientific metadata handoff

The reviewed native feature is integrated as an opt-in experiment; default
v0.6 remains unchanged. The new metadata-only follow-up preserves Fourier
producer context through retained results, crop/READ and NPY packaging. It does
not change vendor entrypoints, pixels, size/type limits or the build gate.
The new path has offline/synthetic validation only; the d59c0ce real-host
records below do not qualify the changed wire/metadata path. A focused actual-DM
continuation remains NOT_TESTED. See [handoff contract](../../docs/SCIENTIFIC_HANDOFF.md) and the
[next-stage official comparison](../../docs/NATIVE_NEXT_STAGE.md).


**PASS** means the stated scope has evidence; **FAIL** means a requirement was
observed to fail; **NOT_TESTED** means no accepted execution covers that scope.
Offline, static and historical results are kept separate from current DM
acceptance. Private run artifacts and scientific data are not distributed.

## Current feature: native operations and scientific handoff

The uint32 extension has a separate [qualification record](mvp/UINT32_ACCEPTANCE.md).
Its prepared synthetic real host passed raw/scalar/calibration/source/NPY checks,
original STOP release, normal exit and manifest-owned removal. The final
production artifact independently repeated those checks in a fresh host, then
the stored uint32 captures reopened unchanged after exit/removal and a new
explicit external run. The float32 records below are retained as their
own evidence. The subsequent native arithmetic, filters, Fourier and visible
delivery extension has [separate uint32 qualification](mvp/UINT32_OPERATIONS_ACCEPTANCE.md),
with native output dtype and rounding explicitly recorded. Its initial
preparation-host SHOW/STOP/last-document release and normal cleanup passed.
On 2026-10-24 the final normal-handler artifact independently passed 32 outputs
through actual Node MCP and a same-PID numerical oracle, then two-result
SHOW/STOP/last-document release, normal exit and manifest-owned removal.
Its two actual uint32/float32 captures also reopened unchanged after host exit
and removal; new explicit external runs matched the independent references.

The following scopes use only newly created synthetic data on the exact pinned
Windows x64 GMS profile, with an idle host, serial calls and no concurrent source
edits. They do not qualify real experimental files or another GMS version.

| Scope | Result | What was independently checked |
| --- | --- | --- |
| Multi-version selection architecture | PASS, limited | Final real host selects the exact adapter; synthetic unknown-version/fingerprint/symbol/ABI failures reject before vendor calls; only one GMS build is qualified |
| Native arithmetic | PASS, limited | All six supported operators against independent raw pixels and calibration; no divide or broadcasting |
| FFT/IFFT and components | PASS, limited | Predetermined real-input fixtures, native positive forward sign/centering, normalized paired inverse, phase/power and explicit vendor frequency calibration; v2 MCP integration checked separately |
| Four native filters | PASS, limited | Independent small-input kernels, float32 rounding and borders; changed filters do not inherit another operator's PASS |
| Bounded preview | PASS, display only | Exact source sampling, coordinate mapping, gray8 and PNG decoding; no model visual-understanding claim |
| Native READ and explicit NPY handoff | PASS, limited | Same actual host PID/session and original IDs; full float32 bit equality including signed zero/subnormals, ROI/axes/signed scale/origin/physical zero/units, journal and file hashes |
| Explicit external example | PASS, handoff example only | Saved script/parameters/versions/input hashes; external float64 raw mean agrees with an independent exact-rational reference; never a plugin fallback |
| Source protection | PASS, limited | Original source pixels, names, spatial/intensity calibration, independent result memory and document count before/after the workflow |
| Result lifecycle | PASS, limited | Explicit arithmetic-result document survives plugin STOP; closing it releases the final reference; later unshown handoff results release after matched original STOP while NPY files persist |
| Final cleanup and persistence | PASS, limited | Actual-PID post-STOP oracle, normal host exit, exact manifest-owned removal; capture reopened in a new external directory after host exit/removal |
| Safe errors and recovery | PASS, limited | Actual unsupported type/nonfinite/ID/bounds/filter-size/FFT-size/foreign-IFFT rejection; original-ID QUERY remains unchanged; unsupported tools do not switch backend |
| Offline engineering regression | PASS | Core and ABI surrogates, version/rejection tests, Windows synthetic pipe, real Node stdio MCP, PNG/NPY tests, default Python compatibility and targeted oracle faults; these are not host ABI evidence |
| Ordinary Agent/model client | NOT_TESTED | No model-client acceptance substitutes for the strict protocol client |
| Native SaveAs/Open, other GMS, other integer/4D native processing | NOT_TESTED / unavailable | uint32 has separately qualified per-operation scope and explicit native output precision; no guessed ABI or hidden fallback |
| Non-ASCII legacy name interoperability | NOT_QUALIFIED | Historical failure retained; no heuristic recoding fix |

New numerical qualification used prepared operator builds first, then a separate
final profile-admission build without an environment override. The latter
repeated the public MCP handoff and independent host checks. The first READ
acceptance-client run failed because its shared validator lacked the new READ
contract; the first Fourier-reference run also failed. Both original failures
remain preserved; corrected runs wrote new evidence. Historical missing STOP
identity is still UNVERIFIED and was not reconstructed.

The original 106 oracle fault injections were explicitly rerun, not inferred
from an older summary. Runtime counting also verified the expanded legacy/NB2
negative set. Exact logs, per-case errors and source/binary hashes remain local.
This uint32-operations turn executed the eight C++ offline suites, then the
final SHOW-type guard's 219 assertions and 2,014 existing adapter assertions;
110 Node tests (zero skips), 13 synthetic Windows-pipe tests, 553 Python tests
and 21 default-backend self-tests passed. The final 14-method production-oracle
suite also passed after the full run, including its later added dtype check.
These are offline results, separate
from the bounded real-host evidence above.
See [operation boundaries](mvp/OPERATIONS_ACCEPTANCE.md),
[the workflow](mvp/NATIVE_WORKFLOW.md) and [adapter matrix](mvp/ADAPTERS.md).

## Historical live continuation: SUMMARY and document lifecycle

This earlier qualification record is preserved as evidence of its own scope.
Use the Current feature section above for active capabilities and limits.

Limited acceptance on the pinned Windows x64 GMS build used only new synthetic
inputs, an idle host and serialized requests. The default v0.6 backend/configuration
was unchanged. No real experimental file was used.

| Scope | Status | Evidence boundary |
|---|---|---|
| Native SUMMARY | PASS, limited | Exact build/module gates and strict MCP; four direct DM reductions, raw intensity, bounded 2D float32 only |
| Independent SUMMARY oracle | PASS, limited | Same actual host PID/session and original request ledger; hand-known values including nontrivial intensity calibration and missing spatial units; full pixels, both calibrations, source NPYs and documents unchanged |
| SUMMARY failures and recovery | PASS, limited | Unsupported dtype, nonfinite result and missing ID fail explicitly; valid request still works; same-ID QUERY returns the original result |
| New strict crop/SHOW | PASS, limited | Presaved crop/SHOW IDs, duplicate/query/conflict checks; independent pixels, dtype, axis/calibration, separate memory and unchanged sources; exactly one document for the explicit output |
| New STOP and shown-document ownership | PASS, limited | Original request persisted before dispatch and matched actual-PID oracle; pipe/message endpoint gone; exact crop remains visible and valid after plugin reference release |
| Final output release | PASS, limited | Close only the delivered document while host lives; output ID invalid, original document count restored, other trial sources unchanged |
| Normal cleanup | PASS, limited | Test host normal exit; manifest manager removes only the owned unchanged DLL after exit; client configuration preserved |
| Older preserved session | UNVERIFIED | Independent pixel/document/release observations and normal cleanup completed, but missing original STOP request was not reconstructed or promoted to PASS |
| Offline regression | PASS | C++ core/adapter/candidate, Windows synthetic transport, complete Node/Python suites, default mock, old fault injections and GMS Python compatibility; none substitute for host acceptance |
| Native FFT/preview/file saving, other candidates | NOT_TESTED / unsupported | SUMMARY is the newly integrated scalar subset; typed synthetic calls do not establish support for the rest |
| Unicode, model image viewing, real data, concurrency | NOT_QUALIFIED / NOT_TESTED | Non-ASCII interoperation remains unqualified; no MCP preview or model-vision acceptance, real-data acceptance or concurrent-image guarantee |

The initial complete offline run failed because the older acceptance client
rejected the new explicit SUMMARY catalog entry before reaching its semantic
controls. Its allowlist/schema was updated without admitting unknown tools;
the targeted controls and subsequent complete regression passed. Original
failure logs were retained. A separate startup-time `/es` wrapper attempt
failed before fixture creation. After ordinary host initialization completed,
the one-shot fixture/oracles succeeded from the Python editor; no dependency
installation, forced termination or restart was used to make it pass.

Historical reports below retain their original pending/failure states. They
must not be read as the latest host state or silently rewritten by the later
limited passes. Reproduction: [SUMMARY](mvp/SUMMARY_ACCEPTANCE.md),
[crop/SHOW](mvp/TRIAL_ACCEPTANCE.md), [install/remove](mvp/INSTALL.md).

## Earlier accepted MVP baseline

Target: Windows x64 GMS **3.53.4137.0**, with exact binary identity checks.
The earlier core native path passed limited real-host acceptance with known
synthetic inputs in an idle, prepared session. No real experimental data was
used. This is a build-specific acceptance, not a general DM compatibility or
native concurrency guarantee.

| Scope | Status | Evidence boundary |
|---|---|---|
| C++ build, including the plugin DLL | PASS | Builds with parameterized LLVM-MinGW toolchain paths; static C++ runtime, Windows/UCRT dependencies remain |
| Core protocol and retained state | PASS | Offline assertions cover strict parsing, overflow, duplicate/conflict handling, late tokens, finite UTF-8 JSON and capacity/STOP behavior |
| Adapter ownership and ABI surrogates | PASS | Explicit synthetic POD callbacks; no Gatan module is loaded by this test |
| Windows named-pipe transport with a synthetic host | PASS | Fragmentation, unread responses, silent clients, readiness, startup failure stages, reentrant cleanup and STOP host cleanup |
| Node transport and MCP facade | PASS | Offline synthetic response identity, bounded framing, cancellation, recovery and unchanged default-backend checks |
| New DLL loaded by DM, host readiness and build gate | PASS, limited | Actual target-host lifecycle/message callback and build identity checked |
| Numeric image lookup, dimensions and dtype | PASS, limited | Explicit synthetic image IDs resolved in DM; no borrowed object-address lookup |
| ASCII dataset names and signed-scale calibration | PASS, limited | Actual host metadata matched the independently qualified fixture; missing utility-image units are reported per entry instead of aborting the list |
| Native mean and repeat access | PASS, limited | Actual `GMSImageProcessing::GetMean` matched independent synthetic truth; finite sign and fractions preserved |
| Strict stdio MCP through actual DM | PASS, limited | Initialize, catalog, status, datasets, mean and safe invalid-parameter checks passed; RPC and tool error layers checked |
| One-shot ordinary Python after native work | PASS, limited | Ordinary Python remained usable without a resident Python listener; this is serialized coexistence |
| Source preservation | PASS, limited | Full synthetic pixel and calibration fingerprints remained unchanged after native operations |
| Released image ID | PASS, limited | After closing the synthetic document and releasing Python references, its old ID failed as missing; another native mean still succeeded |
| STOP and normal host exit | PASS, limited | Experimental pipe/window disappeared; after crop ownership verification, DM exited normally without forced termination. STOP itself did not close DM |
| Manifest installation/removal and recovery | PASS, limited | Ownership-based recovery, fresh installation and final removal succeeded; only the owned DLL was removed, the prior inventory was restored and client configuration stayed unchanged |
| Native crop through strict stdio MCP | PASS, limited | Actual tools/call returned a separate image ID; repeated request ID returned the same result, and out-of-bounds ROI was rejected |
| Crop numerical correctness and independent copy | PASS, limited | Independent one-shot GMS Python checked every pixel, dtype/shape, separate memory, signed physical calibration and unchanged source pixels/calibration; native cropped mean also matched an independent oracle |
| Plugin crop output release after STOP | PASS, limited | The experimental pipe/window disappeared; an independent one-shot DM check found the hidden crop ID invalid and ordinary Python still usable |
| Non-ASCII naming / legacy Python binding interoperability | FAIL / NOT_QUALIFIED | Independent Python/native name comparison failed; no encoding repair or broader Unicode compatibility claim |
| Native export, direct pixel access and additional numeric types | NOT_TESTED | No broader native replacement claim |
| Model image viewing and real experimental data | NOT_TESTED | Strict MCP acceptance does not imply a client UI or visual/scientific-data acceptance |
| Concurrent native/script image calls, vendor exception isolation and other GMS builds | NOT_TESTED | Idle serialization and a pinned build remain required |
| Hot unload, arbitrary scripts, hardware or acquisition control | NOT_TESTED | No support claim; hardware and arbitrary-script tools are not exposed |

The ordinary-operation record budget is 1023 per session, plus one reserved STOP
receipt, for a total of at most 1024 retained records. No completed record is
evicted to admit a new operation.

## Earlier P0 policy and P1 delivery revision, before desktop closeout

**Then-current trial: HOLD.** The new DLL passed its actual host/build gates and
the strict stdio MCP trial below. Desktop acceptance remains pending because
desktop interaction was unavailable. The earlier passes above cover their own
implementation and inputs; they do not certify this revision automatically.

| Revision scope | Status | Boundary |
|---|---|---|
| Raw mean with missing spatial units | PASS, limited actual host | Calibrated and empty-unit synthetic inputs matched independent mean truth, metadata and limitation checks; other invalid spatial-number cases have offline coverage only |
| Safe rejection of unsupported/nonfinite/missing images | PASS, limited actual host | UINT16, nonfinite mean and missing ID returned the expected errors; native/ABI exceptions are not converted into missing-data success |
| Caller-saved crop request ID and immutable recovery | PASS, strict actual-host MCP | Missing ID rejected; same-session QUERY/duplicate kept the same crop, conflicting parameters failed, cropped mean matched truth, and missing-unit crop remained rejected |
| `dm_native_show` native receipt and image identity | PASS, limited actual host | Explicit retained crop ID completed; QUERY/duplicate preserved its receipt and a different show ID still identified that image; no data copy or path/file save |
| Visible document, document count and independent full-pixel/source oracle for this revision | NOT_TESTED | A native completed receipt does not establish visual delivery or replace the pending one-shot host oracle |
| Shown-document ownership after STOP | NOT_TESTED | STOP must not close a document; previous hidden-output release evidence does not establish shown-output lifetime |
| Last output reference after closing only the delivered document | NOT_TESTED | Prepared `verify_trial_closed.py` checks ID invalidation, original document count and unchanged remaining sources while DM still runs; whole-host exit is insufficient |
| Experimental IPC STOP | PASS, limited actual host | STOP acknowledged and the experimental pipe/window disappeared; this does not prove shown-document ownership or unload the DLL |
| Normal exit and manifest-owned removal for this revision | NOT_TESTED | Test host remains open, DLL loaded and ownership manifest installed; preserve them until normal continuation and cleanup |
| New non-ASCII UI/binding comparison | NOT_TESTED / NOT_QUALIFIED | The earlier failed name comparison is retained; no new Unicode qualification |
| Native SaveAs | Not implemented / NOT_QUALIFIED | `dm_string` ABI and exclusive/no-overwrite semantics lack adequate evidence; no permanent-file delivery claim |

The current native IPC is stopped. Do not remove the loaded DLL or force-close
the host to turn the pending steps into a cleanup claim. Resume with the
independent post-STOP pixel/calibration/source and document-ownership checks.
Then close only the delivered document normally and run the prepared
[closed-document oracle](mvp/verify_trial_closed.py) while DM still runs, before
normal host exit and manifest-owned removal. The default backend and
existing client configuration remain unchanged. File persistence is not
implemented; receiving a show result without seeing the image is not visual
acceptance.

Raw mean now keeps `intensity_calibration_applied:false` and raw-pixel intensity
semantics even when spatial metadata reports `calibration_complete:false`.
Crop still requires valid spatial calibration. Descriptor/dtype/work-budget
eligibility does not guarantee a finite mean or suppress native failures.
Recognized invalid numbers plus absent units report both conditions explicitly.

Request recovery uses volatile records from the same running session. STOP,
DM exit/restart or a new session does not promise QUERY recovery; saved IDs
must not be replayed in a new session. Existing read-only tools keep optional
generated IDs for compatibility, while the operator trial saves IDs for every
call. See [TRIAL_ACCEPTANCE.md](mvp/TRIAL_ACCEPTANCE.md) for the synthetic
protocol trial, independent private review and current delivery gate.

Two corrected offline runs must not obscure their initial failures:

- The first oversized-result transport test failed because the result was
  rejected with the wrong error classification. The correction distinguishes
  `response_too_large` from invalid JSON, and the corrected run passed.
- The first expanded cleanup test incorrectly required a zero change in the
  process-wide handle count. Windows lazily initializes window/security
  resources, so that total included unrelated runtime caching. The replacement
  checks the bridge's actual event/thread/pipe handles with Windows handle
  queries and verifies that its window/class are removed. Those specific
  resource checks passed. This correction is not a claim about all host memory
  or operating-system resources.

## Offline recovery and acceptance-script hardening

| Scope | Status | Evidence boundary |
|---|---|---|
| Actual Node MCP to Windows pipe to C++ synthetic host | PASS | C++ execution-start events precede cancellation; a fresh Node client recovers the original crop ID. Timeout/late completion, unknown IDs, conflicts and duplicate submissions remain distinct |
| Synthetic creation and cleanup accounting | PASS | C++ counts each crop creation and synthetic document creation; per-session event gates close and normal STOP releases the audited bridge resources. No Gatan module or DM document is involved |
| Trial oracle fault injection | Initial FAIL; corrected PASS | Some wrong nested receipts and STOP records originally produced PASS. The correction binds native host/operation identity and post-STOP records; positive controls and specific-error negative controls run the actual scripts against a fake DM API |
| Pixels, calibration and document checks in the oracle | PASS, offline | Wrong pixels with an unchanged mean, dtype/shape, aliased memory, signed scales/physical zero/units, source fingerprints and document counts are rejected. This does not execute the oracle inside DM |
| Legacy Python Unicode conversion tracing | PASS, static inspection only; interoperability NOT_QUALIFIED | UTF-8/narrow-string wrappers and a vendor system-code-page default were identified. Their exact indirect binding and UI truth remain unresolved; native UTF-16 to explicit UTF-8 conversion was not changed |
| Current real-host delivery | NOT_TESTED / HOLD unchanged | No DM process, UI, installation, client configuration or pending real-host evidence was changed by these offline tests |

The fault tests require the intended failure reason, a nonzero exit and no new
PASS evidence; an unrelated earlier failure is not accepted as coverage.
Post-STOP evidence fingerprints bind the truth, protocol summary and STOP
record used by the later closed-document oracle. They do not replace the
independent pixel/calibration checks or make previous records newly accepted.
Detailed failed runs and corrected reruns remain private.

## Oracle identity and diagnostic closeout

The strengthened oracles require the native PID to equal the actual Python
process executing the check; a consistent status/crop/SHOW/STOP bundle from
another host is insufficient. STOP's legal request ID, operation, empty
arguments, session, target PID and exact NB1 wire line must match the original
pre-submission record. The existing helper exclusively writes and flushes/
fsyncs that record before pipe construction or sending. Later receipt files
cannot recreate missing submission evidence.

Incomplete historical STOP identity remains UNVERIFIED. An explicitly selected
legacy observation mode can collect the existing independent pixel/document
and final-release checks under separate filenames, always UNVERIFIED. Strict
qualification never accepts those files as PASS prerequisites; wrong identity
or an existing invalid request record still fails in observation mode.

The Unicode probe retains getter type, exact byte hex or text code points,
surrogates and encoding/getter exceptions without guessing a conversion.
RECORDED only means diagnostics were retained; Unicode remains NOT_QUALIFIED.
These are offline code/test scopes, not newly accepted DM observations.

| Closeout scope | Status | Boundary |
|---|---|---|
| Actual-process and saved STOP identity | PASS, offline | Self-consistent foreign-host bundles, mismatched original requests and ambiguous duplicate keys are rejected; helper tests observe persistence before simulated transport |
| Existing oracle fault coverage | PASS, offline | Original negative methods retain their intended errors; expanded tests also prove strict/observation isolation and independent scientific checks |
| Typed Unicode diagnostic retention | PASS, offline; interoperability NOT_QUALIFIED | Fake getters exercise exact bytes/text, surrogate and exception retention; no real probe or UI comparison |
| Current real-host delivery and cleanup | HOLD / NOT_TESTED | No desktop, DM process interaction or loaded-DLL change was performed by this closeout |

See [the unlock checklist](mvp/UNLOCK_CHECKLIST.md) for remaining human steps
and [the integration plan](mvp/INTEGRATION_PLAN.md) for main/feature differences.

## Initial real-host failures and corrected acceptance

The first real-host run produced a correct native mean receipt but its overall
acceptance was **FAIL**. Dataset enumeration treated an uncalibrated hidden
utility image as a fatal list error, and recreating the listening pipe between
connections exposed a connection gap. A correct operator receipt did not make
that aggregate run pass. The corrected enumeration reports incomplete
calibration per image, and the transport/client changes address connection
admission without resubmitting an already sent operation. The subsequent
prepared idle-host core acceptance passed the limited scopes listed above.

An initial closed-document fixture still held Python image references, so the
old image ID remained live. That was not a valid missing-image test. After the
fixture released those references, the old ID failed as missing and the host
continued to serve another native mean. Closing a document alone must not be
described as destroying every remaining reference.

The first installation reached a durable `prepared` manifest but failed to
finalize it because a null backup argument did not bind as intended to
`File.Replace` in PowerShell. The prepared ownership record remained available
for recovery. After the bookkeeping correction, removal used that ownership
record and a new installation completed without overwriting another plugin
or clearing the directory.

An additional non-ASCII naming fixture failed independent comparison between
the legacy GMS Python name bindings and native `GetUnicodeName`; the observed
display title was also insufficient to resolve the encoding cause. The native
encoding path was not changed or guessed. The original failed truth/receipts
were preserved. Only the session's synthetic names were explicitly changed to
ASCII, a separate truth record was written, and the same implementation then
passed the full core MCP and separate crop acceptance. Thus ASCII names are
qualified while non-ASCII naming interoperability remains **NOT_QUALIFIED**.
An ASCII rerun does not convert that failed comparison into a Unicode PASS.

Detailed host receipts, binary fingerprints, source arrays and local manifests
remain private. Crop numerical/copy behavior and post-STOP output release were
accepted separately; neither certifies later implementation changes.

## Historical nb_probe T1–T5 results

These are retained observations from the retired probe, not a fresh rerun.
Its source is preserved behind a compile-time error. The historical record does
not establish that its native image calls were correct or safe, and no PASS
below is inherited by the replacement MVP.

| Historical scope | Historical status | What the record supports |
|---|---|---|
| T1 plugin lifecycle and initialization | PASS, limited | Lifecycle exports were called and a window/worker were created |
| T1 normal cleanup | First FAIL; corrected rerun PASS, limited | Initial cleanup left the worker blocked in pipe connect. A wake connection allowed the later observed exit; silent reads/writes and complete teardown were not proven |
| T1 startup failure and hot unload | NOT_TESTED | No accepted injection or hot-unload test |
| T2 idle PING round trip | PASS, limited | Requests reached a callback with the recorded startup-thread identity and returned receipts; PING performed no image API call |
| T2 malformed input and host timeout | PASS, limited | The recorded invalid-input/timeout paths returned errors or unknown; they did not prove safe late completion or request identity retention |
| T3 ordinary Python activity | PASS, limited | An ordinary script began and ended while the probe was installed, and a window callback was observed during that interval |
| T3 concurrent image calls, duplicate IDs and client disconnects | NOT_TESTED | The observation does not establish simultaneous execution, mutual exclusion or image API reentrancy safety |
| T4 numeric image lookup and dimensions | NOT_TESTED | No valid image-operation receipt was accepted |
| T4 calibration and pixels | NOT_TESTED | No accepted execution of these paths |
| T5 native mean | NOT_TESTED | No accepted native-operator result |

## Correction to the old interpretation

The retired report said that symbol resolution/call preparation was complete
and **only sampling time** remained unverified. That conclusion is withdrawn.
The absence of an `api unresolved` log is not positive evidence for correct
resolution or execution.

Independent static review found that the old PE resolver failed to apply the
export ordinal mapping; `FindImageAsObject` was the wrong lookup for numeric
IDs; and the old `ref_ptr_delete` call could destroy an image instead of
releasing an acquired reference. Its two-pointer placeholder did not specify
the proven single-pointer reference ABI. Its mean encoding could lose
fractional precision and misrepresent negative values. Shared request and
completion state could also associate a late callback with a later request.

The replacement uses standard symbol lookup, an exact build gate, explicit POD
call shapes, numeric-ID lookup, paired reference ownership, finite native
double results, immutable per-request identity and cancellable I/O. Details
are in [ABI_NOTES.md](ABI_NOTES.md). These changes made offline validation and
the separately recorded limited core DM acceptance possible. Historical probe
PASS still does not validate a changed native implementation.

The earlier suggestion to try concurrent image calls first is also withdrawn.
Acceptance starts with an idle host and serialized read-only operations.
Thread affinity and a working message pump do not establish general native
API concurrency safety or exception isolation.
