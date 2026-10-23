# Native bridge validation matrix

**PASS** means the stated scope has evidence; **FAIL** means a requirement was
observed to fail; **NOT_TESTED** means no accepted execution covers that scope.
Offline, static and historical results are kept separate from current DM
acceptance. Private run artifacts and scientific data are not distributed.

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
| WorkBuddy, model image viewing and real experimental data | NOT_TESTED | Strict MCP acceptance does not imply a client UI or visual/scientific-data acceptance |
| Concurrent native/script image calls, vendor exception isolation and other GMS builds | NOT_TESTED | Idle serialization and a pinned build remain required |
| Hot unload, arbitrary scripts, hardware or acquisition control | NOT_TESTED | No support claim; hardware and arbitrary-script tools are not exposed |

The ordinary-operation record budget is 1023 per session, plus one reserved STOP
receipt, for a total of at most 1024 retained records. No completed record is
evicted to admit a new operation.

## Current P0 policy and P1 delivery revision

**Current trial: HOLD.** The new DLL passed its actual host/build gates and
the strict stdio MCP trial below. Desktop acceptance remains pending because
desktop interaction was unavailable. The earlier passes above cover their own
implementation and inputs; they do not certify this revision automatically.

| Revision scope | Status | Boundary |
|---|---|---|
| Raw mean with missing spatial units | PASS, limited actual host | Calibrated and empty-unit synthetic inputs matched independent mean truth, metadata and limitation checks; other invalid spatial-number cases have offline coverage only |
| Safe rejection of unsupported/nonfinite/missing images | PASS, limited actual host | UINT16, nonfinite mean and missing ID returned the expected errors; native/ABI exceptions are not converted into missing-data success |
| Caller-saved crop request ID and immutable recovery | PASS, strict actual-host MCP; WorkBuddy NOT_TESTED | Missing ID rejected; same-session QUERY/duplicate kept the same crop, conflicting parameters failed, cropped mean matched truth, and missing-unit crop remained rejected |
| `dm_native_show` native receipt and image identity | PASS, limited actual host | Explicit retained crop ID completed; QUERY/duplicate preserved its receipt and a different show ID still identified that image; no data copy or path/file save |
| Visible document, document count and independent full-pixel/source oracle for this revision | NOT_TESTED | A native completed receipt does not establish visual delivery or replace the pending one-shot host oracle |
| Shown-document ownership after STOP | NOT_TESTED | STOP must not close a document; previous hidden-output release evidence does not establish shown-output lifetime |
| Last output reference after closing only the delivered document | NOT_TESTED | Prepared `verify_trial_closed.py` checks ID invalidation, original document count and unchanged remaining sources while DM still runs; whole-host exit is insufficient |
| Experimental IPC STOP | PASS, limited actual host | STOP acknowledged and the experimental pipe/window disappeared; this does not prove shown-document ownership or unload the DLL |
| Normal exit and manifest-owned removal for this revision | NOT_TESTED | Test host remains open, DLL loaded and ownership manifest installed; preserve them until normal continuation and cleanup |
| New non-ASCII UI/binding comparison | NOT_TESTED / NOT_QUALIFIED | The earlier failed name comparison is retained; no new Unicode qualification |
| Native SaveAs | Not implemented / NOT_QUALIFIED | `dm_string` ABI and exclusive/no-overwrite semantics lack adequate evidence; no permanent-file delivery claim |
| Ordinary WorkBuddy trial | NOT_TESTED | Private operator answers and the strict protocol client are separate from an actual model/client run; model viewing is not a prerequisite |

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
call. See [WORKBUDDY_TRIAL.md](mvp/WORKBUDDY_TRIAL.md) for the answer-free prompt,
independent private review and current delivery gate.

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
