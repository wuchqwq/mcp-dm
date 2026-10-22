# Instructions for coding agents

This is a Windows DigitalMicrograph MCP bridge for post-acquisition scientific analysis. Read README.md or README.en.md before changing it. Preserve scientific meaning and report evidence honestly. Do not use private experimental data in commits.

## Architecture and ownership

- `server.mjs`: zero-dependency Node >=18 stdio MCP facade, strict tool schemas, serialized loopback requests, timeouts/cancellation. Stdout is MCP JSON only; diagnostics belong on stderr.
- `bridge/dm_bridge.py`: Python 3.7-compatible host integration, a genuine DM backend and an explicit synthetic mock backend. `DigitalMicrograph` imports successfully only inside its host; do not fake a successful real backend.
- `bridge/spectroscopy.py`: explicit-axis energy calibration and bounded ROI arithmetic. Real EDS/EELS/spectral SI remain NOT_TESTED until actual representative data are accepted.
- `bridge/fourdstem.py`: bounded geometric virtual detector arithmetic. Array/memmap and native-reader entrypoints share one kernel. The reader callback initially requires canonical axes and returns small `[n,q_y,q_x]` chunks.
- `bridge/dm4_header.py`: narrow seek-only DM4 index with explicit byte/node/depth budgets; no full pixel loading and no general metadata-decoder claim.
- `bridge/native_stream.py`: bounded read-only Gatan binary streams into small native images, only canonical uncompressed uint8 4D input. Shape/dtype/offset come from the validated header index.
- `bridge/analysis2d_core.py`: shared Python 3.7 / NumPy 1.18-safe statistics, profile and FFT kernels for DM and the external 2D analysis worker.
- `tools/analysis_worker.py`: preview, result-package and replay logic in a separate Python environment. It must never import Gatan APIs or mutate DM images. `requirements-analysis.txt` is not for the GMS runtime.
- `skills/dm-2d-analysis/SKILL.md`: user-facing analysis workflow; numerical correctness and coordinate conversion remain enforced by code.
- `bridge/lossless_tiff.py`: scientific TIFF with dtype/calibration preservation. Do not replace it with a display export or silently downcast.
- `setup/`: target-GMS offline runtime installer, two-stage real-DM launcher, explicit Codex registration. These are user-run setup operations, not CI prerequisites.
- `tests/`: synthetic arrays, fake DM API and isolated mock/echo bridges only. No test should require a DM license, private sample or fixed local drive.

The public MCP catalog has 21 tools, including the four fixed-input 2D capture/preview/analyze/result tools and the existing 4D tools. Codex exposes 20 after `dm_run_script` is added to `disabled_tools`. Registration must refuse existing names before changing configuration. Keep file I/O, DM-native API adaptation and arithmetic separable. Do not duplicate a virtual-detector kernel for native vs NumPy input.

## Mandatory scientific contracts

1. Keep source data read-only and never overwrite existing exports/sidecars. Record provenance and checksums when real data are used. A source slice may map writable DM memory; do not modify it.
2. Specify axes explicitly. NumPy and DM dimension order differ. Never infer an energy or diffraction axis solely from filename, image brightness or largest dimension.
3. Use physical zero plus index times signed scale. DM raw origin conventions differ; preserve all axes and shift crop calibration correctly. Unknown units, nonfinite calibration or ambiguous axes must fail explicitly.
4. Integer reductions need an appropriate exactness/overflow bound; float64 does not represent arbitrary uint64 exactly. Report the arithmetic used. No silent 8/16-bit conversion.
5. Rectangle/bounds upper endpoints are exclusive. Two-dimensional ROI tools reject invalid types and out-of-bounds rectangles; never reintroduce rounding/clipping or crop-result selection by recency/user names. The crop result handoff requires exactly one new image with the per-operation nonce. Spectral and virtual-detector selections use documented channel/pixel centres, with lower-inclusive/upper-exclusive windows. No hidden interpolation, area weighting or energy-bin multiplication.
6. Large 4D sources must be accessed in bounded chunks. Validate shape/dtype and memory budget **before** allocation and reads. Never coerce/reshape/copy the entire cube as a shortcut. Account for native DM image copies as well as Python buffers. A full memmap alone does not prove bounded working-set residency.
7. Fourier peaks are not confirmed lattice identifications. Virtual BF/ADF are geometric windows, not proof of calibrated experimental detector angles or HAADF. Element names, quantification, camera-length conversions, COM/DPC and reconstruction need their own inputs and acceptance.
8. Keep arbitrary DM-Script disabled by default at both layers. Do not add camera, beam, stage or optical controls. The script gate is not a security sandbox.
9. Timeout/cancellation does not cancel a dispatched DM operation. Do not automatically retry operations with side effects. Busy/unknown is not proof that the bridge is stopped.

10. Resolve metadata prefixes before subtree traversal. Keep lookup and value budgets separate, preserve JSON Pointer escapes/list indices, and distinguish confirmed absence from incomplete resolution. Never guess a native getter after failed or truncated type introspection. `complete` describes the requested subtree, not the whole image metadata.
11. `dm_2d_capture` resolves the selected/front image once, validates 2D shape, supported scalar dtype, strict ROI and memory budget before copying, then records pixels plus calibration into a new capture directory. DM does not provide an atomic pixel/calibration snapshot: do not claim concurrent-edit protection. Downstream preview and analysis must use that captured NPY, never the live/front image or display PNG.
12. Preview scaling and overlays are display-only. Keep preview-to-source edge and pixel-center transforms explicit; ROI uses source-coordinate half-open edges and profile endpoints use source pixel centers. No silent clipping, resampling for analysis, or data/dtype/calibration alteration is allowed.
13. Task-A results go into a new result directory. Bind operation ID to capture hash, parameters and code hashes; preserve full FFT values and metadata from the same computation. Unknown after timeout is not success or cancellation; query the directory and do not auto-retry. Replay verifies numerical arrays/metadata within documented tolerance, not PNG byte identity.

## Validation and claims

Use PASS / FAIL / NOT_TESTED for each scope. Distinguish arithmetic unit tests, protocol tests, mock-chain checks, actual DM API execution, real-data numerical comparison, export reopening and visual review. A successful mock response does not prove real DM. `dm_status.backend` must be `digitalmicrograph` for actual host claims. Record actual version/source identity.

Run tests locally. The optional Actions workflow is manual only; hosted CI has not been verified and has no real DM or experimental data. Bounded canonical uint8 4D reads and virtual detectors have limited real-host validation. Whole-file native OpenImage and built-in BF/ADF plugins remain unverified. Real EDS/EELS/spectral SI remain NOT_TESTED. New types/layouts/versions need independent bounded-read, axis/calibration, numerical, source-invariance and memory evidence. Do not mark a failed first run as passed merely because a corrected rerun passed.

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
