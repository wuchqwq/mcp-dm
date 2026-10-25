# Instructions for coding agents

This is a Windows DigitalMicrograph MCP bridge for post-acquisition scientific analysis. Read README.md or README.en.md before changing it. Preserve scientific meaning and report evidence honestly. Do not use private experimental data in commits.

## Product boundary

The core product is a reliable DM tool interface: inspect data, view images,
execute explicit post-acquisition operations and return calibrated results.
Do not require every task to capture, compute every operator or produce a report.
Reports/replay are optional examples retained for compatibility, not the core
acceptance gate. Keep native APIs, coordinate contracts, source protection and
honest errors. Do not add an agent framework, scheduler, report platform or
4D features as part of scope cleanup. Scope decisions are in docs/SCOPE_AUDIT.md.

For future native operations, DigitalMicrograph is the processing engine.
The MCP facade and C++ plugin adapt explicit image IDs/parameters to verified
DM built-in APIs, preserve calibration and ownership, and return bounded
results, previews or saved-file references. Do not build a second Python/C++
analysis engine or silently replace a missing DM operator with NumPy, an
external worker, a handwritten kernel or arbitrary script execution. A missing
or insufficiently qualified DM interface remains unsupported. Independent
test oracles may compute reference answers; they are never a runtime fallback.
Existing v0.6 kernels and optional report/replay paths remain compatibility
code, not a reason to expand that route for new native processing features.
Preview encoding and protocol/metadata validation belong in the bridge;
scientific processing belongs in DM. The limited native Fourier interface and
its acceptance conditions are tracked in
experiments/native-bridge/mvp/FFT_READINESS.md. Tool presence alone does not
qualify an operator, a changed implementation or another host build.
The MVP candidate_calls module and BATCH_CANDIDATES.md prepare typed synthetic
call boundaries only. Never count them as production tool support, bind them
to arbitrary vendor addresses, or add them to the shipping plugin/catalog
before per-operator ABI, scientific and ownership qualification.

## Architecture and ownership

- `server.mjs`: zero-dependency Node >=18 stdio MCP facade, strict tool schemas, serialized loopback requests, timeouts/cancellation. Stdout is MCP JSON only; diagnostics belong on stderr.
- `bridge/dm_bridge.py`: Python 3.7-compatible host integration, a genuine DM backend and an explicit synthetic mock backend. `DigitalMicrograph` imports successfully only inside its host; do not fake a successful real backend.
- `bridge/spectroscopy.py`: explicit-axis energy calibration and bounded ROI arithmetic. Real EDS/EELS/spectral SI remain NOT_TESTED until actual representative data are accepted.
- `bridge/fourdstem.py`: bounded geometric virtual detector arithmetic. Array/memmap and native-reader entrypoints share one kernel. The reader callback initially requires canonical axes and returns small `[n,q_y,q_x]` chunks.
- `bridge/dm4_header.py`: narrow seek-only DM4 index with explicit byte/node/depth budgets; no full pixel loading and no general metadata-decoder claim.
- `bridge/native_stream.py`: bounded read-only Gatan binary streams into small native images, only canonical uncompressed uint8 4D input. Shape/dtype/offset come from the validated header index.
- `bridge/analysis2d_core.py`: shared Python 3.7 / NumPy 1.18-safe statistics, profile and FFT kernels for DM and the external 2D analysis worker.
- `tools/analysis_worker.py`: lightweight preview/status plus optional report/replay helpers in a separate Python environment. It must never import Gatan APIs or mutate DM images. `requirements-preview.txt` adds NumPy/Pillow outside GMS; `requirements-analysis.txt` adds optional report rendering. Load plotting only for rendering. Neither belongs in GMS.
- `skills/dm-2d-analysis/SKILL.md`: optional tool-use guide, not a mandatory workflow; numerical correctness and coordinate conversion remain enforced by code.
- `bridge/lossless_tiff.py`: scientific TIFF with dtype/calibration preservation. Do not replace it with a display export or silently downcast.
- `setup/`: target-GMS offline runtime installer, two-stage real-DM launcher, explicit Codex registration. These are user-run setup operations, not CI prerequisites.
- `tests/`: synthetic arrays, fake DM API and isolated mock/echo bridges only. No test should require a DM license, private sample or fixed local drive.
- `lib/native_bridge.mjs`: opt-in NB2 transport for `DM_MCP_BACKEND=native`; immutable original-operation/result identities, strict typed receipts, one submission followed by same-ID QUERY, no Python fallback.
- `lib/native_preview.mjs`: bounded PNG encoding of the validated native gray8 display result; it does not process scientific pixels or save files.
- `experiments/native-bridge/mvp/`: common protocol, pipe, host-thread dispatch and retained-result lifecycle. Version selection lives in `adapter_profile.hpp`, `adapter_identity_win.hpp` and `adapter_dispatch.inc`; vendor fingerprints, POD layouts and entrypoints live under `adapters/gms_3_53_4137/`. Only the exact Windows x64 GMS 3.53.4137.0 profile is supported. Read ADAPTERS.md, README, INSTALL and the parent RESULTS/ABI_NOTES before native changes. Never build or load the retired `nb_probe.cpp`.
- `tools/native_snapshot_handoff.mjs`: explicitly invoked external encoder for a saved, validated native READ (2D float32/uint32), PROFILE (true 1D float64) or HISTOGRAM (native uint32 counts, binary64 wire) response. It exclusively creates a new NPY/schema-1 capture after persisting its own request journal; it never calls DM, submits a request or saves a DM document. Keep rank/coordinate/count validators separate. Histogram NPY is `<u4`, not the wire `<f8`; preserve both hashes and bin-index geometry without inventing an intensity axis.
- `examples/native_handoff_mean.py`: optional user-invoked NumPy example over that saved capture in an independent workspace, with software/script/input provenance. It is absent from the MCP/plugin runtime, never returns data to DM and is never a fallback for a missing DM operator.

The default public MCP catalog has 21 tools, including the four fixed-input 2D capture/preview/analyze/result tools and the existing 4D tools. Codex exposes 20 after `dm_run_script` is added to `disabled_tools`. Registration must refuse existing names before changing configuration. Keep file I/O, DM-native API adaptation and arithmetic separable. Do not duplicate a virtual-detector kernel for native vs NumPy input.

The separate experimental native catalog has nineteen entries: dm_status,
dm_datasets, dm_native_mean, dm_native_summary, dm_native_result, dm_crop,
dm_native_show, dm_native_unary, dm_native_binary, dm_native_fft,
dm_native_complex, dm_native_filter, dm_native_preview, dm_native_read, dm_native_result_info, dm_native_release, dm_native_rois, dm_native_profile and dm_native_histogram.
The corrected ROIS direct-source-layout/mapping has limited synthetic real-host
qualification and its profile admission is enabled. The final qualified artifact
also passed its separate actual-host source/ROI and final-reference checks. A catalog entry is not capability
admission. Preserve explicit image/document/display/ROI identity, raw rectangle
edges and diagnostics. `slice_ids` is not an axis list. Only exact
ImageSource_Simple class/typed image identity plus its direct canonical-XY size
contract, slice_ids:[0] and exact native binary32 reciprocal mapping admit
source-pixel-aligned integer rectangles. Do not infer axes from slice IDs or
call an axis getter to justify this direct-image layout; Sliced/Group/Summed
and other source classes remain ineligible.
Never round, clip, infer the latest window, use a Python/GUI runtime fallback or
turn getter failure into an empty selection. Same-ID QUERY is historical; a new
ID refreshes the GUI snapshot. See docs/NATIVE_GUI_ROI.md. New ROIS replies use
version 2; version 1 remains historical QUERY only. The separate
native_line_profile group admits width-one integer horizontal/vertical lines,
explicit full GUI identity/expected geometry, ordinary float32/uint32 2D input,
equal nonzero signed spatial scales/units and at most 4096 native float64 samples.
Its actual 1D image and immutable numeric snapshot use native_profile_axis;
retain native origin/physical zero/signed scale separately from source trajectory
and derived path distance. Intensity calibration is copied, not applied. Reject
known Fourier/unresolved scientific lineage until it has its own profile context.
Old READ/MEAN/crop/FFT/filter contracts do not gain 1D admission. See
docs/NATIVE_LINE_PROFILE.md. Diagonal/fractional/wide profiles and
annotations remain unqualified. Tool count alone does not qualify a capability.
A true rank-one result is delivered to a visible document only through its own
group: native_profile_display (float64 PROFILE samples) or
native_histogram_display (uint32 HISTOGRAM counts). Both reuse the already
qualified document factory/show entrypoints, but neither may enter through the
2D display group, carry an `image` 2D descriptor, or be presented as a `[1,N]`
raster. The reply keeps `rank:1`, `display_family:native_1d_image_document`,
`display_class:host_selected` and a `one_dimensional_display` block with the true
shape and one native axis; the bridge never asserts a display class name.
See docs/NATIVE_LINE_PROFILE.md and docs/NATIVE_HISTOGRAM.md.

native_histogram creates its destination with the exported
`Image::CreateImage(DataSize, type, char_range)` and fills it with the exported
`GMSImageProcessing::CalcHistogram`; there is no bridge binning kernel. Only
ordinary float32 2D sources up to 4,194,304 pixels, 2..4096 bins and a caller
range that covers the complete native source minimum/maximum are admitted, so no
undocumented under/overflow rule is ever exercised. Each bin must be an exact
non-negative integer and the counts must total the source pixel count exactly.
The bin budget is independent of the source pixel count: sparse bins and more
bins than pixels are valid. Preserve the exact original binary32 range and
requested bin geometry. The strict client and encoder validate native uint32
storage separately from exact binary64 transport. Do not retrofit current source
metadata guards onto historical v1 evidence; the external encoder does not
reobserve source pixels or descriptors.
The count axis is a bin index: `SetDimensionCalibration` is deliberately not
bound because its live read-back did not reproduce the requested physical zero.
Never relabel these counts as calibrated intensity, and never widen the range
silently.

The prepared ROI host passed explicit-ID GUI rectangle to native crop/mean/READ
and multiblock handoff with independent source/selection/calibration checks.
Preserve earlier mapping and slice-ID eligibility FAILs. Immediate same-stack
fixture destruction after document closure/reference removal also failed; a
later independent idle-host observation passed without further native calls.
Reference lifetime qualification is after host return/idle, not synchronous
destruction inside the same Python stack. Keep that FAIL separate from the
passing STOP/source-protection and later cleanup observations.
SUMMARY calls DM's built-in GetMinimum/GetMaximum/GetSum/GetMean directly;
it is not full dm_stats and does not perform preview or file saving. Its
scope is float32 2D up to 4,194,304 pixels, or ordinary uint32 2D up to
2,097,152 pixels, raw intensity without intensity
calibration, serialized idle-host execution with snapshot_atomic:false.
The shared selector rejects UNSUPPORTED_BUILD, ABI_MISMATCH and NOT_READY
before image calls; only SUPPORTED admits the selected profile. Unknown builds
are inspected using Windows metadata, without probing a vendor ABI. Preserve
all five exact module fingerprint gates. native_statistics denotes the entire
four-reduction SUMMARY group; native_mean remains a separate capability.
Result-reference release requires an exact image ID plus the creation retention token and a pre-saved caller request ID; only plugin ownership is dropped. Old creation QUERY stays immutable. A new RESULT_INFO ID records fresh availability; an old INFO QUERY remains historical.

New operation admission requires its qualified, available profile group before
entering the version implementation: native_image_arithmetic, native_fft,
native_filters, native_preview, native_read, native_line_profile or
native_histogram. There is no qualification
environment bypass; setting an old qualification variable cannot enable an
unavailable group. A missing required symbol disables that group. An available
symbol or synthetic test alone does not qualify a capability.
Earlier core idle-host metadata/mean/MCP acceptance and separate native
crop pixel/copy/calibration acceptance passed using ASCII-named synthetic
inputs. Crop output release after STOP was independently checked along with
pipe/window cleanup and continued one-shot Python use. Non-ASCII legacy
Python/native name comparison failed and remains
NOT_QUALIFIED; do not add a heuristic conversion or silently replace its truth.
Do not inherit that core PASS for changed operators or other builds. Native
mean is not full stats, and a plugin-retained crop ID is not a visible document.
Keep source images unchanged and requests serialized on an idle host; there is
no general host-activity lock or vendor crash isolation. Retain session/ID after
unknown or timeout, query it and never replay automatically. Native STOP only
ends this experiment's IPC/owned resources, not DM. Close DM normally before
manifest-based installation/removal; do not alter existing client entries.

Current native P0: raw intensity mean and SUMMARY do not require usable spatial
calibration when known missing/invalid calibration can be reported explicitly.
Keep calibration_complete:false and specific per-axis issues; never invent
units, apply intensity calibration or swallow native/ABI exceptions. Crop
continues to require valid spatial calibration. Crop and newly added
side-effect tools require a caller-saved request_id before dispatch; read-only
status/datasets/mean/SUMMARY/preview/READ tools allow an omitted ID to generate a UUID. Save
session/arguments too and recover only with same-session QUERY. Records are
volatile; STOP, host exit/restart or a new session does not promise recovery.

An earlier strict actual-host trial passed calibrated/empty-unit raw mean
metadata and safe errors, crop ID recovery/conflicts, and SHOW native receipt
and image correlation. Other invalid spatial-number cases are offline-only.
That previously retained host has now completed independent legacy observations,
normal exit and manifest-owned removal. Its missing original STOP request is
still UNVERIFIED, never repaired by later observations or cleanup. An earlier strict
session passed SUMMARY's real host/build gate, strict MCP and independent source
oracle, including nontrivial intensity calibration, missing spatial units,
safe errors and unchanged full pixels, both calibrations and document count.
See experiments/native-bridge/mvp/SUMMARY_ACCEPTANCE.md. That strict session
also independently passed SHOW MCP, before/after-STOP oracles with the original
STOP request verified, actual crop-document visibility and after-close final
release: exact output ID invalid, document count restored, other sources unchanged.
Normal host exit and manifest-owned DLL removal then completed. Keep that limited
PASS separate from the older session's historical UNVERIFIED STOP identity.
Never force-close a host or remove a loaded plugin. The standalone candidate_calls
module remains synthetic-only and absent from the shipping DLL; SUMMARY's real
adapter integration and individually qualified extensions do not qualify its
remaining candidate inventory.

Current NB2 receipts carry original_operation, normalized_args, result_type
and result_version from the immutable accepted request, including queued,
running, completed, failed and same-ID QUERY. Unknown records have all four
fields explicitly null. Select result validation from this declared identity,
not guessed payload markers. New clients reject old NB1 DLLs without downgrade.
DM_NATIVE_ORACLE_PROTOCOL=NB1_LEGACY is only an explicit read-only reader for
historical NB1 files, not a sender or current qualification. The separate
observe_legacy_stop observation mode can never produce PASS for missing
original STOP evidence. New STOP acceptance requires the original request
record durably persisted before the first connection and the oracle's actual
PID binding; never backfill that record from a receipt.

The final qualified-profile build passed limited same-host synthetic acceptance
with its loaded binary identity verified and no qualification environment
enabled: strict MCP, crop-to-square-to-READ, PNG/NPY handoff, Fourier v2,
filters and the explicitly invoked external example were independently checked.
The original pre-submission STOP record and same-process receipt were verified;
all explicitly recorded unshown outputs were released while original source
pixels/calibration/names, document count and captured file hashes stayed intact.
Normal host exit and manifest-owned DLL removal completed. Reopening the saved
NPY and running the external example again in a new directory after host exit
also passed. These are bounded synthetic/profile-specific results, not a general
GMS, data-type or vendor-fault guarantee. Preserve earlier failures and the
historical missing-STOP UNVERIFIED record separately.
Real experimental data, other builds, concurrent API use and model viewing
remain outside the qualified scope until independently accepted.

Keep the added native operation contracts narrow:
Only each operation's listed dtypes/layouts are eligible; unsupported inputs
remain errors, without silent conversion or a backend fallback.

- UNARY is negate/abs/square; BINARY is add/subtract/multiply, not divide.
  Both admit qualified float32 or uint32 sources, create bounded float32 2D
  results and require matching source dtypes and compatible
  descriptors/calibration and finite native results. All image-producing
  operations share the bounded retained-result pool; they do not edit sources.
- New FFT/complex submissions require native_fourier_operation version 2;
  version 1 remains explicitly recognizable for historical QUERY only.
  The qualified real-input scope admits float32 or separately qualified uint32,
  limited to ordinary-packing power-of-two dimensions
  4..256, full-complex output and complete spatial calibration. Forward uses
  positive exponent, no normalization and fftshift data; inverse uses negative
  exponent divided by width*height and resets spatial origin to zero. Inverse
  accepts only this plugin's retained FFT, and components only its retained
  FFT/IFFT. Phase is radians; power is squared magnitude, not amplitude.
  Use frequency_grid for mathematical bin/DC coordinates; preserve the native
  half-bin calibration offset separately. Never relabel the native calibrated
  DC as zero or claim inverse restores the source origin/intensity calibration.
- FILTER exposes only smooth/sobel/laplace/sharpen through DM operators:
  ordinary float32 or separately qualified uint32 2D, dimensions 5..256,
  bounded finite source/output, preserved spatial calibration. Uint32
  Smooth/Sharpen retain uint32 with native saturation/truncation; Sobel/Laplace
  return float32. Do not invent another kernel or infer edge behavior.
- PREVIEW reads bounded native points into at most 128x128 gray8 pixels and
  returns an MCP PNG image block plus text, also after QUERY. It is nearest
  integer-index sampling without averaging or enlargement; display-only,
  not a quantitative result or scientific export.
- READ requires an explicit half-open rect: source float32 or uint32 2D ordinary packing
  up to 4,194,304 pixels, ROI up to 16,384 samples/65,536 raw bytes. Validate
  canonical base64, exact little-endian float32/uint32, row-major [y,x] shape, exact
  source/ROI identity, translated signed calibration and immutable creation
  provenance when present. Preserve signed zero. Known missing/invalid spatial
  calibration is reported, not invented; READ does not require optional stats
  bindings, create a native image, return a PNG or write a path/file.

The separate uint32 scope is documented in UINT32_ACCEPTANCE.md. Its five
profile subgroups are native_uint32_mean, native_uint32_statistics,
native_uint32_crop, native_uint32_preview and native_uint32_read. Code 11,
ordinary packing and explicit integer/unsigned metadata must agree; these flags
describe the fixed-build dtype contract, not nonexistent native flag getters.
MEAN/SUMMARY use DM reductions with a 2,097,152-pixel conservative exact-integer
sum budget. Fractional means remain binary64. uint32 CROP admits at most
4,194,304 source pixels and 4 MiB output, preserves uint32 and requires complete
spatial calibration. Uint32 SHOW, arithmetic, Fourier and filters have four
separate profile groups and their own UINT32_OPERATIONS_ACCEPTANCE.md evidence.
Arithmetic is DM binary64 computation then float32 storage; FFT first rounds
the uint32 source to binary32 and outputs complex64. Neither is arbitrary
integer-exact computation. The bridge never casts scientific pixels. SHOW
admits only exact retained uint32 crops or qualified Smooth/Sharpen results,
and verifies the actual dtype still matches its immutable retention record
before requesting a document. Saved READ
uint32 bytes use NPY <u4. The optional external example records an exact Python
integer sum, checks NumPy uint64, and divides once for a raw binary64 mean.
Only new synthetic images qualify this extension; real ADF files remain
NOT_TESTED and must not be edited as part of that trial.

The scientific-context integration adds bridge-owned Fourier creation metadata
through retained results, READ and the saved-response encoder. Preserve native
calibration and mathematical `scientific_semantics.coordinate_axes` separately;
never derive FFT bins only from the native half-bin origin. Crop offsets compose;
postprocessed phase/power is not an unchanged component. Legacy/mixed lineage
stays explicit unknown. The metadata path has targeted synthetic real-DM
acceptance for offset crop/READ/NPY, processed phase, source protection and
normal cleanup; it does not qualify experimental data or GUI measurements.
See docs/SCIENTIFIC_HANDOFF.md.

The single-response encoder accepts only an explicit saved READ, PROFILE or HISTOGRAM. The separate tools/native_region_handoff.mjs runner remains 2D: it plans bounded live READs, saves original IDs before dispatch, assembles exact NPY/schema-1 bytes, and uses only QUERY to recover SENT IDs. It is explicit data handoff, not a scientific operator or DM SaveAs. See docs/NATIVE_LIFECYCLE_HANDOFF.md. Preserve original source-creation QUERY arguments when available; do not invent a whole-ROI receipt or recursively claim a complete history.

Only explicit saved READ, PROFILE or HISTOGRAM data may feed the single-response handoff CLI. Persist the
caller handoff ID/parameters and fsync the complete journal before creating a
new output directory. Same ID/parameters returns the existing verified receipt;
conflicts, incomplete journals or changed files never trigger automatic retry
or overwrite. Bind the NPY/metadata hashes and original NB2 READ/PROFILE/HISTOGRAM session/ID/args
and process/thread receipt. Do not describe this bridge-owned NPY encoding or
the separate explicit NumPy example as DM SaveAs or native scientific processing.

Experimental dm_native_show requires its own saved ID and accepts only an
existing plugin-retained qualified result by exact ID, with no path or
data-copy/file-save interface.
Its limited visible-document/lifetime acceptance is recorded independently of
its native completed receipt. A shown document can hold the output after plugin
STOP until the user closes it or the host exits; do not confuse that with a plugin
leak, or close unrelated documents. No model-viewing or permanent-save claim.
The SaveAsGatan string/exclusive-write contracts remain unqualified. Keep
independent trial answers private; see MVP TRIAL_ACCEPTANCE.md for the strict
protocol and host-oracle sequence. Protocol receipts do not prove UI visibility.

## Mandatory scientific contracts

1. Keep source data read-only and never overwrite existing exports/sidecars. Record provenance and checksums when real data are used. A source slice may map writable DM memory; do not modify it.
2. Specify axes explicitly. NumPy and DM dimension order differ. Never infer an energy or diffraction axis solely from filename, image brightness or largest dimension.
3. Use physical zero plus index times signed scale. DM raw origin conventions differ; preserve all axes and shift crop/READ ROI calibration correctly. Unknown units, nonfinite calibration or ambiguous axes must fail explicitly for operations using physical coordinates. Raw native mean/SUMMARY and READ instead report recognized unusable spatial calibration without applying it; crop and physical Fourier interpretation still require usable calibration.
4. Integer reductions need an appropriate exactness/overflow bound; float64 does not represent arbitrary uint64 exactly. Report the arithmetic used. No silent 8/16-bit conversion.
5. Rectangle/bounds upper endpoints are exclusive. Two-dimensional ROI tools reject invalid types and out-of-bounds rectangles; never reintroduce rounding/clipping or crop-result selection by recency/user names. The default Python crop result handoff requires exactly one new image with the per-operation nonce; native crop binds its independently owned new image ID to the immutable request receipt. Spectral and virtual-detector selections use documented channel/pixel centres, with lower-inclusive/upper-exclusive windows. No hidden interpolation, area weighting or energy-bin multiplication.
6. Large 4D sources must be accessed in bounded chunks. Validate shape/dtype and memory budget **before** allocation and reads. Never coerce/reshape/copy the entire cube as a shortcut. Account for native DM image copies as well as Python buffers. A full memmap alone does not prove bounded working-set residency.
7. Fourier peaks are not confirmed lattice identifications. Virtual BF/ADF are geometric windows, not proof of calibrated experimental detector angles or HAADF. Element names, quantification, camera-length conversions, COM/DPC and reconstruction need their own inputs and acceptance.
8. Keep arbitrary DM-Script disabled by default at both layers. Do not add camera, beam, stage or optical controls. The script gate is not a security sandbox.
9. Timeout/cancellation does not cancel a dispatched DM operation. Do not automatically retry operations with side effects. Busy/unknown is not proof that the bridge is stopped.

10. Resolve metadata prefixes before subtree traversal. Keep lookup and value budgets separate, preserve JSON Pointer escapes/list indices, and distinguish confirmed absence from incomplete resolution. Never guess a native getter after failed or truncated type introspection. `complete` describes the requested subtree, not the whole image metadata.
11. `dm_2d_capture` resolves the selected/front image once, validates 2D shape, supported scalar dtype, strict ROI and memory budget before copying, then records pixels plus calibration into a new capture directory. DM does not provide an atomic pixel/calibration snapshot: do not claim concurrent-edit protection. Downstream preview and analysis must use that captured NPY, never the live/front image or display PNG.
12. Preview scaling and overlays are display-only. Keep preview-to-source edge and pixel-center transforms explicit; ROI uses source-coordinate half-open edges and profile endpoints use source pixel centers. No silent clipping, resampling for analysis, or data/dtype/calibration alteration is allowed.
13. Task-A results go into a new result directory. Bind operation ID to capture hash, parameters and code hashes; preserve full FFT values and metadata from the same computation. Unknown after timeout is not success or cancellation; query the directory and do not auto-retry. Replay verifies numerical arrays/metadata within documented tolerance, not PNG byte identity.

## Validation and claims

Dataset enumeration may map only known native real scalar type codes to dtype,
reusing the bounded 2D capture mapping; unknown types stay null. Do not touch
pixel buffers to obtain a dtype. Optional synthetic fixtures must run before
the persistent Python Bridge, or after disconnecting clients and cleanly
stopping it; never force-restart DM for script-slot conflicts. Check both
JSON-RPC `error` and MCP tool `isError` before claiming tool success.

Use PASS / FAIL / NOT_TESTED for each scope. Distinguish arithmetic unit tests, protocol tests, mock-chain checks, actual DM API execution, real-data numerical comparison, export reopening and visual review. A successful mock response does not prove real DM. `dm_status.backend` must be `digitalmicrograph` for default-backend host claims or `digitalmicrograph-native` for native claims, with its actual build gate and process/thread receipts checked. Record actual version/source identity privately.

Run tests locally. The optional Actions workflow is manual only; hosted runs cover synthetic behavior only and have no real DM or experimental data. Bounded canonical uint8 4D reads and virtual detectors have limited real-host validation. Whole-file native OpenImage and built-in BF/ADF plugins remain unverified. Real EDS/EELS/spectral SI remain NOT_TESTED. New types/layouts/versions need independent bounded-read, axis/calibration, numerical, source-invariance and memory evidence. Do not mark a failed first run as passed merely because a corrected rerun passed.

Keep detailed acceptance reports local. Public documentation should explain installation, features and concise support limits. Do not publish experimental sample counts, dataset dimensions or file sizes, measured results, source identifiers, exact maintainer machine configuration, or private run history without explicit user approval.

## Development workflow

1. Inspect the current implementation and relevant tests. Keep production Python compatible with 3.7 and NumPy 1.18; no walrus, builtin collection generics or new-only NumPy APIs.
2. Make focused changes. Test numerical behavior with small independently hand-enumerable arrays, asymmetrical shapes, nonzero origins, signed scales, axis permutations, invalid input and nonfinite cases. Avoid tests which merely repeat the implementation.
3. Run the appropriate tests from the repository root:

```powershell
python -B -m unittest discover -s tests -p 'test_*.py' -v
node --test
$env:DM_TEST_PYTHON = (Get-Command python).Source
node selftest.mjs
```

Use an external development venv with `requirements-dev.txt` for tifffile and `requirements-analysis.txt` for the preview/report worker. Never pip-upgrade the GMS-managed runtime just to run a test. Test the core with GMS Python separately when available. CI success alone is synthetic evidence.

4. For an actual DM change, use a new output directory and small read-only representative data. Confirm DM backend, source hashes before/after, independent numerical oracle, calibration and reopened exports. Under a memory constraint, measure peak process working set in addition to explicit chunk sizes. Do not restart or close unrelated user documents casually.
5. Update human and agent documentation for behavior and validation limits. Run `git diff --check`. Inspect staged files manually; `.gitignore` is a convenience, not a privacy guarantee. No experimental `.dm3/.dm4`, arrays/images, vendor manuals/binaries, third-party GPL reader, runtime traces, credentials or personal machine paths belong in the public repository.
6. Do not publish, push, send messages or change external services unless the user has authorized that action. When preparing a release, make a reviewable artifact first and report the exact tests actually run.

Optional worker contracts: profile sampled_coordinates are source coordinates; sampled_coordinates_local and its calibration are capture-relative. Report intensity is raw, not calibrated by a unit label alone. Verification failure/unresolved state must exit nonzero. Preview allocations must be bounded before source scans/display allocation; full-frame floating/RGB intermediates are prohibited. No automatic Skill installation or overwriting user settings.

Manual synthetic workspace switching was separately observed: explicit native image IDs remain stable across tabs; DATASETS is registry-wide. SHOW can reuse a document in an inactive workspace without activating it. A SHOW receipt is not proof of active-tab visibility or model viewing. Native workspace enumeration/activation, general profiles and annotations remain unqualified; the gated rectangle and narrow axis-aligned line/profile continuations are described above. Do not expose remaining candidates or use UI automation/Python as their runtime fallback. A read-only authorized ADF ROI trial preserved original memory/file data and exact exports, but its inverse round trip failed the predeclared accuracy tolerance. A saved-input equivalent copy reproduced the historical transforms with bitwise direct-DM/MCP agreement; that is not a fresh original-file check. Preserve the numerical FAIL separately from conversion/path-equivalence and cleanup PASS; see docs/NATIVE_FFT_PRECISION.md. Do not claim lossless integer Fourier round trips or general real-data qualification.

Complete-region export requests must be isolated by a random, durably recorded
capture instance, not just the user-facing export name or mutable source ID.
New journals bind their canonical workspace and namespace version; recovery
reuses the exact saved wire IDs. Incomplete legacy unscoped journals must not
be silently migrated or replayed. Completed legacy packages are saved evidence
only and cannot be retroactively qualified as fresh reads by a hash check.
MCP SHOW/QUERY `display_context` describes document-delivery policy, not a fresh
GUI observation; preserve historical native receipts and report unknown active
workspace visibility rather than claiming a tab was activated.
