# Native result lifetime and complete bounded numerical handoff

This feature checkout adds explicit reference release and a thin chunked READ
runner. It keeps the default v0.6 backend, exact GMS adapter gates, scientific
operators and size/type limits. Native SaveAs, GUI ROI acquisition, native
profile/histogram and workspace activation remain unavailable.

## Release an intermediate without losing its history

New image-producing receipts include `retention.token` and
`retention.creation_request_id`. The token identifies the plugin's particular
retained reference in the current native session; an image ID alone can be reused
by the host. Save the entire creation receipt before continuing.

```json
{"name":"dm_native_result_info","arguments":{"image_id":123,"retention_token":7}}
{"name":"dm_native_release","arguments":{"image_id":123,"retention_token":7,"request_id":"release-my-intermediate-01"}}
```

The numbers above are placeholders. Use the actual image ID and token. RELEASE
requires the caller's pre-saved request ID. A missing/invalid ID or token is
refused before pipe dispatch. A wrong ownership pair never releases a source or
another result. Repeating an accepted request returns its immutable original
record; a new request for an already released pair is a no-op. Changing its
arguments under the original request ID is a conflict.

Release drops only the plugin's reference and reclaims its result-pool budget.
It does not close a DM document or release the source. A shown document may keep
the same image alive until its last owner closes. Native processing refuses a
known released input; the remaining document is not a renewed plugin reference.
Copied descendants retain their own data and creation metadata; they do not keep
every ancestor image alive merely to describe provenance.

`dm_native_result` answers what an operation completed with. It must never rewrite
an old creation result after release. `dm_native_result_info` takes the exact
image/token pair and records availability at that query's execution time. Use a
new readonly query ID for a fresh observation; querying an old INFO request is
still a historical snapshot. `native_object_existence:"not_probed"` deliberately
does not claim whether a document or some other host owner still holds an image.

Timeout/cancellation means stop waiting, not stop the host operation. Query the
original saved ID; never replay an uncertain RELEASE or creator. All records and
tokens are session-local. STOP and host exit/restart do not provide recovery.

## Export an explicit complete region without writing a pixel algorithm

The existing `dm_native_read` remains bounded to 16,384 samples per call. The
external Node runner plans deterministic nonoverlapping strips/tiles, including
right/bottom remainders, and assembles exact response bytes into one NPY. It calls
only the existing native STATUS/READ/QUERY operations. There is no Python runtime
dependency, native image allocation, scientific computation or SaveAs call.

Run from this checkout, using an existing independent workspace and a **new**
relative output directory. Replace every placeholder with the live session,
actual host PID, selected image ID and an explicit half-open pixel rectangle:

```powershell
node tools/native_region_handoff.mjs --workspace C:\analysis --output capture-01 --request-id export-my-region-01 --session <32-lowercase-hex> --host-pid <actual-pid> --image-id <selected-id> --rect 10,20,210,170
python -B tools/verify_native_region.py --capture C:\analysis\capture-01 --host-pid <original-pid> --session <original-session>
```

The independent verifier uses external Python 3.8+ and NumPy. It does not run in
GMS Python and is not a runtime dependency of the Node exporter or native backend.

This is an explicitly invoked data handoff helper, not an extra MCP tool. An
Agent can run the fixed command without reading source or writing a tile loop.
Use a unique export ID and retain its original workspace and journal. Export IDs
are scoped to that workspace; copying journals to another workspace is not a
cross-directory recovery mechanism. Each newly created capture now has a random
`capture_id` persisted before any connection; STATUS/READ IDs include that
capture's namespace. Independent directories using the same short export ID
therefore cannot retrieve one another's cached READs. The journal records
`request_namespace_version:2` and its canonical workspace. Explicit recovery
uses the saved capture ID and original wire plan, never a newly generated ID.

Completed legacy journals without that version can be verified offline only;
the returned `request_namespace_status` is `legacy_unscoped_saved_evidence_only`.
Hash agreement verifies the saved bytes, not their freshness at the old capture
time. Incomplete legacy journals are refused with `LEGACY_REGION_RECOVERY_UNSAFE`,
even with `--recover`: preserve their evidence and use a new export ID/output.
No automatic journal migration, old-ID resend or overwrite is performed.

The journal durably saves the full plan, original wire requests, session/PID,
parameters and output before the first connection. Each block becomes SENT
before dispatch. A completed response is saved and fsynced before assembly.
When READ describes a plugin-created source, the runner also queries and saves
that source's original creation record, including its normalized processing
arguments. It never reconstructs parameters from an image name or re-creates a
source to obtain them. This is the immediate producer, not a recursively complete
processing history; preserve earlier creation receipts when that history matters.

| Bound | Limit |
|---|---|
| Source and total requested 2D region | At most 4,194,304 pixels; ordinary float32 or uint32 |
| Per READ | At most 16,384 samples / 65,536 raw bytes |
| Blocks | At most 512; optional `--block-samples` may reduce each block |
| New native operation records | One STATUS plus one per block, at most 513; source-creation QUERY consumes no new operation slot |
| Scientific output | At most 16 MiB of exact `<f4` or `<u4` values plus the NPY header |
| Disk estimate/budget | Checked before reads; at most 96 MiB including saved responses and journals |
| File hashing/assembly buffers | At most 65,536 bytes per I/O block, plus bounded protocol/metadata objects |

The helper does not reserve remaining capacity in a previously used native
session. Existing requests may exhaust its 1,023 operation slots; failure leaves
an explicit partial capture. It does not evict history. Fixed buffer sizes do not
mean that the Node process's entire working set has that size; actual trial
process working sets were measured separately.

## Files, scientific interpretation and recovery

- `input.npy` contains original numeric bytes, never a display PNG or a float32
  cast of uint32 data. Row readback is checked before success.
- `input.json` retains schema 1, dtype/shape, `[y,x]` order, source ROI/identity,
  both signed spatial calibrations and original physical zero, raw intensity
  policy, creation provenance and available Fourier context.
- `read-N.json` holds each actual original completed READ receipt and values.
  `native_receipt:null` with `native_receipt_scope:"per_block"` prevents an
  invented whole-region READ receipt. `native_receipts` lists the actual blocks.
- For plugin results, `source-creation.json` stores the original completed
  creator returned by QUERY; its hash/ID/operation/arguments are bound in
  `native_source_creation_record`. Older captures without that additive record
  remain identifiable as missing those saved processing parameters. Do not
  backfill their historical qualification.
- `capture.json` must say `state:"captured"` and `complete_coverage:true`.
  A filename alone is not success. Incomplete/error writes stay partial, and
  published files are never replaced. A partially published file is not an
  accepted analysis input until the full manifest/journal verifies.

Frequency consumers must use `scientific_semantics.coordinate_axes`. Native DM
half-bin calibration stays separately preserved. Crop and READ offsets compose;
DC can be outside the ROI. Phase remains radians only when its values are an
unchanged phase component; processed phase is `processed_scalar`. IFFT does not
restore source spatial origin/intensity calibration or lossless integer pixels.
The independent verifier checks each block's bytes/placement, coverage,
host/session/request identity, axes/calibration and mathematical/native frequency
metadata against the reopened NPY. It does not attest an unchanged live source
or manufacture a vendor-operator qualification.

Same workspace/ID/parameters with a completed journal verifies existing files
without any live calls. Changed parameters or files fail. An incomplete journal
without `--recover` returns UNKNOWN_INCOMPLETE. Explicit `--recover` can query
SENT original IDs and use saved completed bytes; it never resends their READs.
Unknown/running/failed originals remain partial. A new session cannot recover
old host records. Corrupt journals, stale lock files, changed file ownership or
unverifiable partial publication require inspection; the helper does not delete
evidence or guess that an uncertain operation never started.

Keep the host idle and source unedited throughout. Each READ compares its
descriptor before/after, and the runner compares source/calibration/lineage
between blocks. Matching descriptors do **not** detect every pixel edit or prove
an atomic snapshot: `pixel_capture_atomic:false` remains mandatory. Chunking
does not enlarge FFT/filter limits and never performs per-tile FFT as a whole
image transform. The older optional single-READ mean example intentionally
refuses this multi-READ mode; external analysis may explicitly use its verified
NPY in a separate workspace and must label its own computation.

## Workspaces and native GUI measurements: explicit remaining gaps

Manual switching between prepared synthetic DM workspaces was tested with actual
native MCP calls and an independent same-process observer. DATASETS enumerates
the native registry across workspaces, including hidden utility images. Explicit
image IDs continue to select the same source after switching tabs. They are not
tab indices or a request to process the current/front image.

A first SHOW creates its result document in the active workspace in this tested
scope. Repeating SHOW of that existing result from a different workspace reuses
the document in its original workspace without activating that tab. The legacy
`document_visible`/visible-document receipt is **not proof of visibility in the
active workspace**, focus, or model viewing. The MCP facade adds `display_context`
to completed SHOW responses and their QUERY results: `scope:document_delivery_only`,
`active_workspace_visibility:unknown`, `workspace_activation_requested:false`,
`model_visual_verification:false`, and `observation:not_performed_by_mcp`.
This is a conservative interface policy, not a live workspace observation or a
mutation of the original native receipt. The tool has no workspace-targeting
parameter. Do not repeatedly SHOW or change IDs hoping to select a different tab.

| Requested capability | Reviewed interface evidence | Missing qualification; current status |
|---|---|---|
| Read a GUI rectangle/line | Vendor ImageDisplay/ROI getters and ROI IDs; related ImageUtilities methods | Exact display-to-image binding, `Gatan::DM` wrapper/ScriptObject ownership and getter ABI are not the existing `GMS::Image` ref layout. No arbitrary object cast or “no ROI means whole image”. **NOT_QUALIFIED**. |
| Native profile | ImageUtilities profile extraction/container/length candidates | Typed source/container conversion, endpoint/strip-width sampling and 1D calibration/result ownership. **NOT_QUALIFIED**. |
| Native histogram | Pinned processing module's `CalcHistogram` export; official ImageCalculateHistogram example | Independently proven 1D destination creation/layout, bin endpoints/nonfinite policy/count dtype and protocol contract. A 2D row must not impersonate a 1D scientific result. **NOT_QUALIFIED**. |
| Enumerate/activate a workspace | Vendor document workspace getter and workspace/event utility candidates; manual GUI switch observations | No qualified typed enumeration/activation entrypoint in the current profile. Utility/event helpers are not a verified switch API. Need explicit ID/ownership and current/document workspace distinctions, plus saved-ID side-effect recovery. **NOT_QUALIFIED**. |
| Native annotations | Vendor ImageDisplay component examples | Verified display/component ownership, stable annotation IDs and idempotent add/remove. Scientific pixels must stay unchanged. **NOT_QUALIFIED**. |

The matching SDK ownership definitions were not available in the reviewed
inputs. Function-name discovery or a Python/DM-Script example does not qualify a
C++ call. No candidates above were called with guessed layouts/addresses, exposed
as tools, or replaced by a Python listener/GUI-click runtime. Follow-up should
close one typed ABI contract at a time, starting with exact workspace/display/ROI
identity, before claiming native GUI measurements.

## Qualification boundaries

The exact GMS 3.53 profile passed targeted synthetic real-host release,
result-pool reuse, shown-document retention through STOP/last-close and chunked
float32/uint32 file reopening. The scientific-context P0 path also has separate
actual synthetic FFT/component/crop/READ acceptance. Every STOP used its original
pre-submission request and the observer's actual process PID. Hosts exited
normally; only manifest-owned DLLs were removed while unloaded.

An explicitly authorized, read-only experimental ADF ROI trial independently
checked native crop/reductions/arithmetic, the existing small-filter reference,
forward Fourier/components, exact exports, source protection and lifecycle. Its
inverse round trip **failed the predeclared accuracy threshold**. That failure
is retained; it does not become PASS because files and cleanup passed. No
integer-exact or universal Fourier accuracy claim is made. Private source
identities, measurements and raw receipts are not published here.

Ordinary model-client acceptance, new GMS builds, concurrent editing, GUI ROI,
profile/histogram, native workspace switching, annotations and SaveAs remain
NOT_TESTED or NOT_QUALIFIED as described above. Offline callbacks, pipe peers and
negative controls are not real-DM qualification.
