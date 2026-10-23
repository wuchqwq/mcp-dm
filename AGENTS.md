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
scientific processing belongs in DM. Native FFT readiness is tracked in
experiments/native-bridge/mvp/FFT_READINESS.md; FFT is not yet a native tool.
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
- `lib/native_bridge.mjs`: opt-in NB1 transport for `DM_MCP_BACKEND=native`; strict receipts, one submission followed by same-ID QUERY, no Python fallback.
- `experiments/native-bridge/mvp/`: fixed-build C++ plugin, explicit POD vendor adapter, synthetic host/tests and manually invoked real-host acceptance. Read its README, INSTALL and the parent RESULTS/ABI_NOTES before native changes. Never build or load the retired `nb_probe.cpp`.

The default public MCP catalog has 21 tools, including the four fixed-input 2D capture/preview/analyze/result tools and the existing 4D tools. Codex exposes 20 after `dm_run_script` is added to `disabled_tools`. Registration must refuse existing names before changing configuration. Keep file I/O, DM-native API adaptation and arithmetic separable. Do not duplicate a virtual-detector kernel for native vs NumPy input.

The separate experimental native catalog has seven tools: status, datasets,
native mean, dm_native_summary, result query, crop and experimental native show.
SUMMARY calls DM's built-in GetMinimum/GetMaximum/GetSum/GetMean directly;
it is not full dm_stats and adds no backend, preview or save feature. Its
scope is float32 2D up to 4,194,304 pixels, raw intensity without intensity
calibration, serialized idle-host execution with snapshot_atomic:false.
Its target is Windows x64 GMS 3.53.4137.0 with exact
binary gates. Earlier core idle-host metadata/mean/MCP acceptance and separate native
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
status/datasets/mean/SUMMARY tools allow an omitted ID to generate a UUID. Save
session/arguments too and recover only with same-session QUERY. Records are
volatile; STOP, host exit/restart or a new session does not promise recovery.

An earlier strict actual-host trial passed calibrated/empty-unit raw mean
metadata and safe errors, crop ID recovery/conflicts, and SHOW native receipt
and image correlation. Other invalid spatial-number cases are offline-only.
That previously retained host has now completed independent legacy observations,
normal exit and manifest-owned removal. Its missing original STOP request is
still UNVERIFIED, never repaired by later observations or cleanup. A new strict
session passed SUMMARY's real host/build gate, strict MCP and independent source
oracle, including nontrivial intensity calibration, missing spatial units,
safe errors and unchanged full pixels, both calibrations and document count.
See experiments/native-bridge/mvp/SUMMARY_ACCEPTANCE.md. The new strict session
also independently passed SHOW MCP, before/after-STOP oracles with the original
STOP request verified, actual crop-document visibility and after-close final
release: exact output ID invalid, document count restored, other sources unchanged.
Normal host exit and manifest-owned DLL removal then completed. Keep that limited
PASS separate from the older session's historical UNVERIFIED STOP identity.
Never force-close a host or remove a loaded plugin. The standalone candidate_calls
module remains synthetic-only and absent from the shipping DLL; SUMMARY's real
adapter integration does not qualify its remaining operation catalog.

Generic NB1 QUERY does not carry its original operation. An independent
acceptance client must continue validating against its pre-submission saved
tool/ID/arguments. Recognition of some SUMMARY result fields is not proof that
every malformed recovery result can be identified after all operation markers
are removed. Do not add computation or a backend fallback to fill this gap.

Experimental dm_native_show requires its own saved ID and accepts only an
existing plugin-retained crop, with no path or data-copy/file-save interface.
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
3. Use physical zero plus index times signed scale. DM raw origin conventions differ; preserve all axes and shift crop calibration correctly. Unknown units, nonfinite calibration or ambiguous axes must fail explicitly for operations using physical coordinates. A raw native intensity mean instead reports recognized unusable spatial calibration without applying it; crop still fails on that calibration.
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
