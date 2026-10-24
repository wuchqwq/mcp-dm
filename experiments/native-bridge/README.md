# Experimental native DigitalMicrograph bridge

The current implementation is [mvp/](mvp/README.md). It explores a small,
build-pinned native backend for post-acquisition analysis without a resident
Python bridge. The existing Python backend remains the default.

The target is Windows x64 GMS **3.53.4137.0**, with exact host/module identity
checks. Passing those checks is a prerequisite, not a compatibility or runtime
acceptance claim. The earlier core native path passed a limited real-DM acceptance
using synthetic inputs on this target: lifecycle/readiness, metadata, native
mean, strict MCP calls, source preservation and normal cleanup. Native crop also
passed separate strict MCP and independent pixel/calibration checks with ASCII
fixture names. Post-crop STOP was separately checked to release the retained
image and remove the experimental pipe/window while ordinary Python remained
usable. Normal host exit and ownership-based DLL removal then completed,
preserving the prior inventory and client configuration. See the separate
[validation matrix](RESULTS.md).

## Current scope

The opt-in native MCP catalog includes `dm_status`, `dm_datasets`,
`dm_native_mean`, `dm_native_summary`, `dm_native_result`, `dm_crop` and
`dm_native_show`, plus limited `dm_native_unary`, `dm_native_binary`,
`dm_native_fft`, `dm_native_complex`, `dm_native_filter`, `dm_native_preview`
and `dm_native_read`. The qualified
[workflow](mvp/NATIVE_WORKFLOW.md) combines explicit native processing with
bounded NPY/calibration handoff and a separately invoked external example.
The [version matrix](mvp/ADAPTERS.md) describes safe selection; only the pinned
3.53 profile is supported. See [per-operation evidence](mvp/OPERATIONS_ACCEPTANCE.md)
for the final build's limited synthetic MCP/host/cleanup acceptance.
The new strict synthetic session independently passed SHOW
visibility/document ownership, including after STOP and final release on normal
document closure. SUMMARY directly calls DM's minimum/maximum/sum/mean for
bounded 2D float32 raw intensity; strict MCP and a same-host pixel/calibration
oracle passed. See [SUMMARY acceptance](mvp/SUMMARY_ACCEPTANCE.md).
The native mean is a raw pixel
intensity mean for a bounded two-dimensional float32 image. It is not the full
`dm_stats` interface. Unsupported operations and types fail explicitly; the
native backend never falls back to Python. Recognized incomplete spatial
calibration can be reported while raw mean still runs; crop remains strict.
Crop/show require caller-saved request IDs before dispatch. Recovery is only
same-session QUERY, not after STOP or a host restart.

Native crop creates a separate image ID held by bounded plugin-owned references
until native STOP/cleanup. Actual acceptance verified independent cropped data,
half-open bounds, signed calibration and unchanged sources; this is not a
visible DM document or a model-visible preview by itself. SHOW targets only
a qualified plugin-retained result and does not save a file. The new strict trial passed
independent full pixels/source checks, unique visible-document ownership after
STOP, final image release on document closure, normal host exit and owned DLL
removal. The older preserved session was also observed and cleaned normally,
but its missing original STOP record remains historically UNVERIFIED.
ASCII names are qualified.
Non-ASCII naming interoperability with legacy GMS Python bindings is
**NOT_QUALIFIED** after an independent comparison failed; no heuristic encoding
conversion was added. Real experimental data, model image viewing,
other GMS builds and concurrent native API use remain unverified.

A worker owns the named-pipe transport. A message-only window dispatches native
operations on the plugin startup thread. The bridge permits one queued or
running operation, preserves operation IDs after client timeouts, and uses
`QUERY` to recover the original result. Use only an idle host with serialized
analysis requests. A callback thread check does not establish safe concurrent
access with scripts, user edits or other plugins.

The pipe permits the current Windows user and rejects remote clients. This is
a local transport boundary, not process isolation. Vendor access violations or
other native faults can still terminate the host; C++ exception handling does
not provide a vendor crash sandbox. No camera, beam, stage, optics or acquisition
controls are included.

## The older probe is retired

`nb_probe.cpp` and its Python clients remain as historical source. The source
now contains a compile-time error to prevent accidental rebuilding or loading.
`build_nb.ps1` is a parameterized wrapper for the replacement MVP build.
Do not use the old clients to test the new NB1 protocol.

The old report's statement that image API execution lacked **only a ready
sampling window** was incorrect. Independent review found three material bugs:

- The manual PE resolver indexed the function table with a name-table index,
  omitting the name-to-ordinal mapping. Lack of an unresolved-symbol log did not
  prove a correct function address. The replacement uses `GetProcAddress`.
- `ref_ptr_delete(Image*)` is a final destructor/deallocator on the pinned build,
  not a release operation. Calling it after every lookup could destroy a live
  image. The replacement guards owned references, decrements the established
  intrusive count, and calls the vendor destructor only at zero.
- `FindImageAsObject` takes an object-address token rather than the numeric
  image ID used by clients. The replacement uses `FindByID(uint32)` with an
  explicit single-pointer result object and verifies identity.

The original probe also lacked per-ID retained state, reliable late-completion
isolation, cancellable pipe I/O and complete cleanup confirmation. Historical
lifecycle/PING observations are retained in [RESULTS.md](RESULTS.md); they do not
validate either the old image calls or the replacement DLL.

See [ABI_NOTES.md](ABI_NOTES.md) for the build-specific calling and ownership
contracts. No vendor binary, header or disassembly is distributed here.

## Build, installation and rollback

Use the [MVP build and offline tests](mvp/README.md#build-and-offline-tests),
then follow the [installation and rollback guide](mvp/INSTALL.md) before any
explicit host acceptance. No SDK is bundled. A toolchain with Windows headers,
import libraries and the C++ standard library is required; **no SDK dependency
does not mean no CRT dependency**. The replacement statically links its C++
runtime while retaining Windows/UCRT dependencies.

The [production repository guide](../../README.md) describes the default Python
backend. Native installation does not authorize overwriting that configuration
or upgrading GMS-managed Python.
