# Native MVP continuation handoff

Target: Windows x64 GMS **3.53.4137.0**, with exact executable/module identity
checks. The default v0.6 Python backend and client configuration remain
unchanged. Core native work and crop numerical/copy behavior have separate
limited real-DM acceptance with ASCII-named synthetic inputs. Other unaccepted
scopes must not inherit those passes.

The native catalog is `dm_status`, `dm_datasets`, `dm_native_mean`,
`dm_native_result` and experimental `dm_crop`. There is no Python fallback.
Mean is bounded 2D float32 raw intensity, not full statistics. Crop returns a
separate image ID held by bounded plugin references until STOP/cleanup; it does
not promise a visible document, model-visible preview or WorkBuddy acceptance.
Post-crop STOP release passed an independent check: the hidden output ID became
invalid, its pipe/window disappeared and ordinary Python still ran.

Implemented lifecycle/transport: strict NB1, one immutable in-flight operation,
duplicate/conflict detection, retained IDs, query recovery, bounded UTF-8 JSON,
current-user-only local pipe, host readiness callback, cancellable I/O,
partial-startup cleanup, deferred reentrant cleanup and host cleanup after
STOP. The total record bound is 1024, reserving one slot for STOP. Submit once,
query the same ID after timeout/unknown, and never automatically replay work.

Offline core, ABI-surrogate, Windows synthetic-host, Node/MCP and installer
checks passed their stated scopes. The fake host and ABI surrogates do not
load Gatan modules. Keep the initial failures and corrections recorded in
[RESULTS.md](../RESULTS.md); do not replace them with an aggregate PASS.

Actual idle-host core acceptance passed loading/build gate/message readiness,
numeric INFO, names/dtype/signed-scale calibration, repeated native means,
strict stdio MCP calls and safe invalid parameters. Ordinary one-shot Python
after native work succeeded without a resident Python listener, and synthetic
pixels/calibration remained unchanged. After document closure and release of
Python image references, a missing old ID failed cleanly and another mean
still succeeded. STOP removed the experimental pipe/window; normal DM exit
then succeeded. These are limited build-specific observations.

Separate crop acceptance passed real stdio MCP creation of a new image ID,
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
**NOT_QUALIFIED**; its encoding cause is unresolved. Native `GetUnicodeName`
still follows the explicit UTF-16/UTF-8 path, with no heuristic conversion or
general Chinese-name repair claim.

Calibration has two distinct origin fields: `origin` is raw DM index origin;
`calibrated_value_at_pixel_zero` is physical zero. Coordinates use the latter
plus index times signed scale. Enumeration can retain a utility entry with
`calibration_complete:false`; numerical operations require usable calibration.
An image ID binds an object, not an atomic snapshot of pixels and metadata.

The retired `nb_probe.cpp` is blocked with `#error`. Its PE resolver, numeric-ID
lookup and destructive release call were wrong. See
[ABI_NOTES.md](../ABI_NOTES.md) for the corrected build-specific contracts.
Vendor access violations are not isolated. Keep the host idle and requests
serialized; no safe hot unload, concurrent image API use, hardware operation,
arbitrary script tool, other-build compatibility or real-data acceptance is
claimed. WorkBuddy/model visual acceptance remains **NOT_TESTED**.

Final normal DM exit and manifest-owned DLL removal completed successfully.
Only this experimental DLL was removed, the pre-installation inventory was
restored, and the manifest records removal; no client configuration was
changed. Next, keep any new client/visual or scientific-data acceptance
separate. Normal
agent tasks are listed in [README.md](README.md#short-tasks-for-a-connected-agent)
and do not establish WorkBuddy/visual acceptance. Keep private
receipts, manifests, scientific files, vendor binaries and build output out of
public commits. To roll back, disconnect clients, send explicit native STOP,
close DM normally, and use the same ownership manifest to remove only this
experimental DLL. Return to the unchanged default backend. Commands are in
[INSTALL.md](INSTALL.md).
