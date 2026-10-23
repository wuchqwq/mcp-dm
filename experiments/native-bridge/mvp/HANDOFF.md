# Native MVP continuation handoff

Target: Windows x64 GMS **3.53.4137.0**, with exact executable/module identity
checks. The default v0.6 Python backend and client configuration remain
unchanged. Earlier core native work and crop numerical/copy behavior have separate
limited real-DM acceptance with ASCII-named synthetic inputs. Other unaccepted
scopes must not inherit those passes.

**Current trial: HOLD.** The revised DLL passed actual host/build gates and
strict stdio MCP checks: calibrated and empty-unit raw means/metadata,
unsupported/nonfinite/missing-image errors, required crop ID, strict
missing-unit crop rejection, immutable crop QUERY/duplicate/conflict behavior
and cropped mean. SHOW completed for the explicit crop ID; same-ID recovery
and another show ID correlated to that image. These are native API/protocol
receipts, not independent visual or full-pixel acceptance.

Offline closeout now requires the oracle's actual process PID and the original
pre-submission STOP request record. A mutually consistent record from another
host is insufficient. Missing historical `stop-request.json` remains
UNVERIFIED; never backfill it from the receipt. The explicit
`observe_legacy_stop` mode collects checks under separate observation filenames
and can never produce PASS. Start with [the unlock checklist](UNLOCK_CHECKLIST.md)
for preserved-session observations, document closure and normal cleanup.
For the later main integration, follow [the differential plan](INTEGRATION_PLAN.md),
preserving main's reviewed core and feature's Show/acceptance additions.

Desktop acceptance is pending because desktop interaction was unavailable.
This revision's independent full-pixel/source-invariance oracle, visible UI,
document count, post-STOP document ownership, new Unicode UI comparison and
last-reference release after closing only the delivered document, and normal
exit/removal remain NOT_TESTED. STOP was acknowledged and the native
pipe/window disappeared. The test host remains running with the DLL loaded
and manifest installed; IPC is stopped. Preserve the private records, complete
the post-STOP oracle when desktop access is available. Then normally close
only the delivered crop document and run [verify_trial_closed.py](verify_trial_closed.py)
while DM still runs: output ID invalid, original document count restored and
other sources unchanged. Whole-host exit cannot prove final output-reference
release. Finally close the host normally and remove only the manifest-owned DLL. Do not force termination or
remove a loaded plugin.

The native catalog is `dm_status`, `dm_datasets`, `dm_native_mean`,
`dm_native_result`, experimental `dm_crop` and the P1 `dm_native_show`
candidate. There is no Python fallback; show's visual/document acceptance is
still NOT_TESTED despite its completed native receipt.
Mean is bounded 2D float32 raw intensity, not full statistics. Crop returns a
separate image ID held by bounded plugin references until STOP/cleanup; it does
not promise a visible document or model-visible preview.
Earlier post-crop STOP release passed an independent check: the hidden output ID became
invalid, its pipe/window disappeared and ordinary Python still ran.

Implemented lifecycle/transport: strict NB1, one immutable in-flight operation,
duplicate/conflict detection, retained IDs, query recovery, bounded UTF-8 JSON,
current-user-only local pipe, host readiness callback, cancellable I/O,
partial-startup cleanup, deferred reentrant cleanup and host cleanup after
STOP. The total record bound is 1024, reserving one slot for STOP. Submit once,
query the same ID after timeout/unknown, and never automatically replay work.

Current P0 changes: crop's caller-saved request_id is mandatory before
dispatch; the old read-only tools keep optional-ID compatibility. The
operator trial saves IDs, session and arguments for every call. QUERY recovery
is only within that same running session, not after STOP or host restart.
Raw mean now tolerates recognized incomplete spatial calibration while
reporting calibration_complete:false and specific issues. Intensity remains
raw/unapplied; crop retains strict calibration. Offline surrogates passed the
new policy, including native/ABI failure propagation. The current strict
actual-host trial accepted the empty-unit case separately; other invalid
spatial-number cases remain offline-only.

Offline core, ABI-surrogate, Windows synthetic-host, Node/MCP and installer
checks passed their stated scopes. The fake host and ABI surrogates do not
load Gatan modules. Keep the initial failures and corrections recorded in
[RESULTS.md](../RESULTS.md); do not replace them with an aggregate PASS.

Earlier idle-host core acceptance passed loading/build gate/message readiness,
numeric INFO, names/dtype/signed-scale calibration, repeated native means,
strict stdio MCP calls and safe invalid parameters. Ordinary one-shot Python
after native work succeeded without a resident Python listener, and synthetic
pixels/calibration remained unchanged. After document closure and release of
Python image references, a missing old ID failed cleanly and another mean
still succeeded. STOP removed the experimental pipe/window; normal DM exit
then succeeded. These are limited build-specific observations.

Earlier separate crop acceptance passed real stdio MCP creation of a new image ID,
same-request-ID reuse and out-of-bounds rejection. A one-shot GMS Python oracle
checked all cropped pixels, dtype/shape, independent memory, signed scales,
physical pixel-zero/unit consistency and unchanged source pixels/calibration.
The cropped native mean matched independent numerical truth. Ordinary Python
remained usable. Separately, STOP was acknowledged, the experimental pipe/window
disappeared, and a one-shot DM check confirmed release of the plugin-retained
hidden crop ID. Ordinary Python remained usable after that cleanup.

The initial real run had a correct mean receipt but an overall FAIL from
utility-image units and a pipe-listener gap. A separate initial missing-ID
fixture was invalid because Python references kept the image alive. Initial
installation also required recovery from a `prepared` manifest after final
bookkeeping failed. Corrections and subsequent acceptance are distinguished
in [RESULTS.md](../RESULTS.md).

An additional non-ASCII naming fixture failed Python/native name comparison.
The original truth and failure were preserved. The same session's synthetic
names were explicitly qualified to ASCII with a separate truth record, then
core MCP and crop acceptance passed with the same implementation. The accepted
name scope is ASCII. Non-ASCII / legacy GMS Python binding interoperability is
**NOT_QUALIFIED**. Static tracing identified a legacy UTF-8/narrow-string
boundary and a vendor system-code-page default, but their indirect service
binding and the UI comparison remain unresolved. See
[ABI_NOTES.md](../ABI_NOTES.md#legacy-python-and-native-unicode-paths).
Native `GetUnicodeName`
still follows the explicit UTF-16/UTF-8 path, with no heuristic conversion or
general Chinese-name repair claim.

Calibration has two distinct origin fields: `origin` is raw DM index origin;
`calibrated_value_at_pixel_zero` is physical zero. Coordinates use the latter
plus index times signed scale. Enumeration can retain a utility entry with
`calibration_complete:false`; crop requires usable calibration, while supported
raw mean can report that limitation and still return raw intensity.
An image ID binds an object, not an atomic snapshot of pixels and metadata.

The retired `nb_probe.cpp` is blocked with `#error`. Its PE resolver, numeric-ID
lookup and destructive release call were wrong. See
[ABI_NOTES.md](../ABI_NOTES.md) for the corrected build-specific contracts.
Vendor access violations are not isolated. Keep the host idle and requests
serialized; no safe hot unload, concurrent image API use, hardware operation,
arbitrary script tool, other-build compatibility or real-data acceptance is
claimed. Model visual acceptance remains **NOT_TESTED**.

The earlier accepted session's normal DM exit and manifest-owned DLL removal
completed successfully.
Only this experimental DLL was removed, the pre-installation inventory was
restored, and the manifest records removal; no client configuration was
changed. Any further visual or scientific-data acceptance needs separate
evidence. The [acceptance procedure](TRIAL_ACCEPTANCE.md) covers protocol,
independent numerical and lifecycle checks. Keep private
receipts, manifests, scientific files, vendor binaries and build output out of
public commits. To roll back, disconnect clients, send explicit native STOP,
close DM normally, and use the same ownership manifest to remove only this
experimental DLL. Return to the unchanged default backend. Commands are in
[INSTALL.md](INSTALL.md).

P1 candidate: dm_native_show(image_id, request_id) for a plugin-retained crop
only, without another data copy, a file path or a save. A visible document is
expected to own the crop independently of the plugin; STOP must not close it.
The native Show receipt and explicit-image correlation passed the current
strict real-host MCP trial. Actual visibility, document count and post-STOP
lifetime remain NOT_TESTED; do not inherit the earlier crop oracle. Native SaveAs remains blocked by
insufficient dm_string ABI and exclusive/no-overwrite evidence. Do not equate
display with model vision or permanent file delivery.

Offline continuation now includes the real Node MCP to Win32 pipe to C++
synthetic-host recovery test, with a host execution-start event before
cancelling and a new Node client querying the saved ID. C++ creation counters
detect replay; late results, conflicts and cleanup are also checked. The
actual trial scripts have independent positive controls and fault injection
for pixels/calibration, record/host identity and document counts. Initially
accepted wrong receipts are recorded as FAIL, with the corrected checks
tested separately. Post-STOP and after-close evidence now bind the same
truth/summary/STOP files by fingerprints. Do not edit old evidence to fit the
new scripts. These offline checks do not clear the current real-host HOLD.
Commands are in [README.md](README.md#build-and-offline-tests).

The [acceptance procedure](TRIAL_ACCEPTANCE.md) preserves synthetic input
creation, `accept_trial_mcp.py`, independent oracles and the pre-recorded
STOP/process identity checks. Generated trial answers and execution evidence
stay private; protocol success does not establish visual acceptance.
