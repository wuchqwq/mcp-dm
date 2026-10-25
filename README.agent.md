# Agent guide: install and use mcp-dm

[中文项目介绍](README.md) · [English overview](README.en.md) · [技术参考](REFERENCE.md) · [Technical reference](REFERENCE.en.md) · [Coding instructions](AGENTS.md)

This is the entry point for an agent helping a researcher install or use the MCP. For code changes, also read AGENTS.md and the relevant implementation/tests. Do not treat instructions for using tools as permission to modify the repository, install dependencies, upload data or change unrelated client settings.

For Fourier-derived READ/NPY data, preserve both native DM calibration and
`scientific_semantics.coordinate_axes`; see [scientific handoff](docs/SCIENTIFIC_HANDOFF.md).
Unknown context is not permission to guess the frequency origin or phase units.
Native Fourier keeps its base 4..256 scope; v2 extension up to power-of-two
axes 1024/1,048,576 pixels requires per-operation/source-lineage large
capabilities and the unchanged 16 MiB shared pool (1024² IFFT exceeds it;
large uint32 IFFT remains unqualified). FILTER stays 5..256 and READ stays
16,384 samples per block; see [Fourier limits](experiments/native-bridge/mvp/FFT_READINESS.md).

## 1. User goal and division of work

The researcher may normally work through DM's GUI and use external Python for specialized analysis. Do not require them to learn DM scripting or force every request through a capture/report pipeline.

- Use the connected backend's actual tools for supported DM operations.
- When additional analysis is requested, explicitly hand off an authorized, bounded numerical export to the agent's external workspace. Keep the exported input read-only; save the script, parameters and new outputs there.
- Label external computations as external. Never use them to make an unsupported native operation look successful, and never silently switch backends.
- Do not add another scientific calculation engine to the native bridge. Data conversion, preview encoding and provenance handling are engineering support, not permission to invent unqualified scientific algorithms.
- Returning an externally generated image to DM requires an independently supported import path. Do not claim an automatic round trip merely because an export succeeded.

Reports and replay are optional. A profile request needs a correct profile, not a mandatory full report.

## 2. Resolve the installed checkout and backend first

Inspect the actual checkout, branch and configuration. Do not reset or overwrite a user's checkout to match this document. The live tool catalog and status describe the connected implementation, not capabilities mentioned in a different branch's README.

| Backend | Scope in this checkout | Required handling |
|---|---|---|
| Default Python/TCP | 21 catalog tools, with arbitrary DM-Script disabled by default; core 2D operations, bounded exports/capture and optional preview/report paths | A genuine host reports backend `digitalmicrograph`; `mock` is synthetic. Numerical kernels may use NumPy; do not label every result DM-native. |
| Opt-in native | Twenty catalog entries in this feature checkout; direct-image GUI rectangle/line identity and width-one horizontal/vertical profiles have limited synthetic-host qualification. Existing bounded native operations, preview, READ and document delivery retain their own scope; FRAME has its own qualification. | Select explicitly with `DM_MCP_BACKEND=native`. Require backend `digitalmicrograph-native`, readiness, exact supported build/module identity, available capability and matching session. No Python fallback. |
| Other feature checkouts | May contain additional native tools and different acceptance scope | Read that checkout's native HANDOFF/RESULTS and inspect tools/list. Development evidence does not change main automatically. |

This feature checkout's native catalog has twenty
tools, including qualified limited arithmetic, Fourier/components, filters,
sampled PNG preview and bounded float32/uint32 READ. The exact Windows x64 3.53 profile
is selected before ABI calls; other builds remain unsupported. Inspect
`native_capabilities` and its reason fields, not the tool count alone. See the
[workflow](experiments/native-bridge/mvp/NATIVE_WORKFLOW.md) for the complete
native crop/processing → numeric READ → explicit NPY handoff → external example.
The new [lifecycle/chunked handoff guide](docs/NATIVE_LIFECYCLE_HANDOFF.md) covers exact retention tokens, `dm_native_result_info`/`dm_native_release`, pre-saved IDs, a fixed complete-region export command, original source-creation parameters, and the independent file verifier. Its multi-READ mode is separate from the older optional single-READ mean example.
The integration remains experimental and is not a stable native release.

For a rank-three ordinary uint16 sequence, the explicit
[`dm_native_frame`](experiments/native-bridge/mvp/NATIVE_FRAME.md) contract selects
zero-based `frame_index` on DM dimension2 / NumPy axis0. It creates a separate
float32 XY working copy through DM native slice/cast operations; values 0..65535
remain exact. Save `request_id` before submission. Do not select a summed image
or infer the currently displayed frame, time, spatial Z or physical units.
Unknown units may remain unknown. READ/NPY preserves the converted dtype and
original frame ancestry; SHOW and later processing retain their own gates.
FRAME has **LIMITED_SYNTHETIC_REAL_HOST_PASS** within its recorded scope; tool discovery alone
does not authorize a call when `native_frame` is unavailable.

The new read-only `dm_native_rois` links an explicit image ID to document/display
and rectangle ROI identities; inspect `native_gui_rois` before using it. Its
corrected direct-image source-layout/mapping has limited synthetic real-host
qualification, including a separate qualified-artifact session and final-reference
confirmation.
Never choose the latest window or round an ineligible
rectangle. `slice_ids` identifies slices, not axes; only the verified direct
canonical-XY image source and admitted normalized mapping qualify. See
[GUI ROI identity and coordinates](docs/NATIVE_GUI_ROI.md).

ROIS v2 also preserves raw line endpoints; historical ROIS v1 is QUERY-only.
For `dm_native_profile`, save the session, request ID, complete image/document/
display/ROI identity and `expected_line` **before** submission. Width is explicitly
1; endpoints must be integer source pixel centres on a horizontal/vertical line.
The source must have equal nonzero signed scales and units on both axes. Geometry
eligibility alone does not prove that a source meets the profile calibration
contract. Read the actual capability and any rejection reason.
The result contains a true 1D float64 image and immutable numeric bytes; QUERY
recovers the original result without another extraction. Use the existing
saved-response encoder for real `shape:[N]` NPY and calibrated sidecar, preserving
native signed axis coordinates separately from ordered source trajectory/path
distance. This is data handoff, not DM SaveAs. Native READ remains 2D; SHOW admits
retained PROFILE/HISTOGRAM results through separate qualified 1D groups, preserving
their actual rank and dtype. See [line/profile use and limits](docs/NATIVE_LINE_PROFILE.md).

`dm_native_histogram` admits bounded ordinary float32 2D sources and 2..4096 bins,
including more bins than pixels. Save the request ID and binary32 range before
submission; the range must cover the whole source. DM computes the counts.
The native image and NPY use uint32; the immutable wire payload uses exact
binary64 values. Raw bin edges/range are retained separately from the native
axis. Non-identity source intensity calibration stays unapplied with `bin_index`;
only identity calibration and an explicit unit may admit the checked native
intensity axis. Do not claim general physical-intensity conversion or DM SaveAs. See [histogram handoff](docs/NATIVE_HISTOGRAM.md).
Reference release was verified after the one-shot returned to an idle host;
the earlier immediate same-stack destruction assertion failed and is preserved.
Do not turn a completed QUERY or a local wrapper release into a promise that
all document-held or stack-held objects have already been destroyed.

The initial uint32 subset covers ordinary-packed 2D metadata, raw mean/SUMMARY,
same-dtype crop, preview and READ. Mean/SUMMARY stop at 2,097,152 pixels; uint32
crop sources stop at 4,194,304 pixels and outputs at 4 MiB (1,048,576 pixels),
with complete spatial calibration. Preview permits at most 4,194,304 source
pixels and 128x128 display samples. READ permits that source bound and at most
16,384 ROI samples, preserving exact little-endian uint32 bytes as `<u4` NPY
through the explicit encoder. The optional external example records an exact
integer sum and a binary64 fractional mean, without float32 conversion.
The prepared trial and its STOP/normal-exit/removal evidence are separate from
the final production qualification; use [the uint32 acceptance status](experiments/native-bridge/mvp/UINT32_ACCEPTANCE.md).
The separate [uint32 operations qualification](experiments/native-bridge/mvp/UINT32_OPERATIONS_ACCEPTANCE.md)
covers native arithmetic, filters, Fourier and eligible retained-result SHOW.
Arithmetic produces float32; Smooth/Sharpen produce saturating/truncated uint32;
Sobel/Laplace produce float32; FFT first rounds to binary32 and produces complex64.
Inspect the actual capability and `dtype_semantics`; these operations are not
lossless integer processing. Export the actual result dtype, never its ancestor's.
Other integer types, native 4D and model-client acceptance remain outside this extension; native SaveAs is still unavailable. A bounded authorized real-input trial does not qualify arbitrary experimental datasets; its inverse round trip failed the predeclared tolerance, so do not claim lossless uint32 Fourier round trips.

New complete-region exports persist a per-capture request namespace before dispatch. Resume only the original journal in its original workspace; incomplete legacy unscoped journals are refused, never migrated or replayed. Completed old packages remain offline evidence, not newly verified source reads.

Native DATASETS includes images across workspaces. Use an explicit image ID, never infer it from the active tab. SHOW does not target/activate a workspace: an existing result may remain on an inactive tab. Its receipt does not prove active-workspace visibility or model viewing. MCP SHOW/QUERY adds `display_context` with active-workspace visibility explicitly unknown; this does not probe or activate a workspace. GUI rectangle ROI and limited line profiles are the separately gated work above; diagonal/wide profiles and native workspace enumeration/activation remain unqualified. [Fourier precision attribution](docs/NATIVE_FFT_PRECISION.md) distinguishes direct DM agreement from a retained numerical accuracy FAIL; it does not promise lossless integer round trips.

Native main targets Windows x64 GMS 3.53.4137.0 with exact binary gates. Do not relax a fingerprint check or reuse an unqualified ABI for another build. A missing optional feature is not an instruction to enable arbitrary scripts.

The previous long-form READMEs are preserved as REFERENCE.md and REFERENCE.en.md, with their installation instructions, numerical conventions and historical validation boundaries intact. Historical feature-branch HOLD notes there describe that integration snapshot; for subsequent development, consult the actual feature checkout's current handoff rather than reopening a closed historical session.

## 3. Default-backend setup

### Inspect before writing

Check Windows x64, the chosen repository path, Node >=18, the existing DM installation and its GMS-managed Python. The host bridge is Python 3.7 / NumPy 1.18 API-compatible; do not replace GMS's runtime with an external interpreter. `import DigitalMicrograph` is a host operation, not an external-Python health check.

Read the client's existing MCP configuration before changing it. Preserve unrelated entries. If `digitalmicrograph` already exists, identify its checkout/backend and obtain an intentional choice instead of overwriting it. Registering a client does not start DM.

The detailed default-backend environment/startup instructions are in [REFERENCE.md](REFERENCE.md) and [REFERENCE.en.md](REFERENCE.en.md). They cover Gatan's existing offline Python installer when the vendor component is genuinely absent. Do not install or upgrade that component simply because an external Python import fails.

### Start the bridge

From the repository root, after the environment and user permission are established:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup\start_bridge.ps1
```

Use the documented executable/path options for non-default installations. Do not kill DM, launch competing hosts or replace the bridge just to resolve a connection failure. The default listener uses loopback TCP on port 8765.

If a synthetic fixture is needed, create it before the resident bridge starts. The bridge occupies DM's ordinary Python execution slot. To run another host Python script, disconnect clients, stop the bridge normally with `setup/start_bridge.ps1 -Stop`, confirm exit, run the one-shot script, then restart. Do not inject a second script into an occupied slot. Existing images do not require fixture creation.

### Register the client

Adapt [mcp.json.example](mcp.json.example), replacing `__ABS_REPO_PATH__` with the absolute checkout path. Use an absolute Node path when the client cannot see the shell's PATH. Keep `DM_MCP_ALLOW_DMSCRIPT=0`. JSON examples are not Codex TOML.

For an explicitly requested Codex registration, use the repository's [register_codex.ps1](setup/register_codex.ps1), after inspecting any existing entry. Follow the reference guide for timeout settings; do not duplicate tables or discard existing disabled tools. Refresh the client's MCP connection after configuration changes as needed.

### Optional preview environment

Use external Python 3.10+ and a new environment outside GMS:

```powershell
python -m venv .analysis-env
.\.analysis-env\Scripts\python.exe -m pip install -r requirements-preview.txt
$analysisPython = (Resolve-Path .\.analysis-env\Scripts\python.exe).Path
```

Configure this interpreter via the documented `AnalysisPython` option or the preview configuration example in the reference. Do not recreate/overwrite an existing environment or MCP entry blindly. Matplotlib/requirements-analysis.txt is optional and needed only for the report workflow, not the lightweight preview or core measurements.

### Prove the connection

Check three separate stages: configuration, tool discovery, actual execution. Call `dm_status`, verify the intended real backend, then use `dm_datasets`. A mock response, installed DLL, existing pipe or discovered tool alone does not prove a real-DM operation worked.

Check both JSON-RPC errors and MCP `isError`. Use a small synthetic first task when numerical behavior must be validated. Do not state that real experimental data or model vision is qualified merely because protocol calls succeeded.

## 4. Operate on the correct data

Resolve the target once to an explicit image ID. Ask for a selection when ambiguous rather than guessing by window recency or brightness. An ID binds an object, not an immutable snapshot. Work on an idle host without simultaneous source edits.

For 2D ROIs, use source-image `[x0,y0,x1,y1]`, zero-based, upper-exclusive. Reject invalid or out-of-range regions; do not round or clip to make a call succeed. DM dimensions are x,y,... while exported NumPy shapes reverse that order. Preserve dtype and distinguish display pixels from scientific values.

Physical coordinates follow `calibrated_value_at_pixel_zero + index * signed_scale`. The raw DM origin is a separate field. Missing calibration must be reported, not invented; use each connected tool's declared requirements rather than assuming all backends share one rule.

`dm_metadata` reads a requested subtree. Inspect path status, `complete` and `issues`; an unavailable or budget-limited read does not establish that a field is absent.

## 5. Common task paths

| Request | Default-backend path | Important boundary |
|---|---|---|
| Inspect open data | `dm_status` → `dm_datasets`, then `dm_metadata` as needed | Return the explicit image identity and available calibration. |
| Compare ROIs | Separate `dm_stats` calls with explicit coordinates | This is a statistics summary, not a complete histogram. |
| Profile/FFT | `dm_profile` or `dm_fft` | Preserve sampling/frequency conventions. FFT peaks do not identify a phase. |
| Check a proposed selection | `dm_2d_capture` → `dm_2d_preview` | Same bounded captured input; overlay source coordinates. PNG is display-only. |
| External analysis | `dm_export` or `dm_2d_capture` → agent-owned external script | Read exported numerical values plus sidecar/calibration; never calculate from the preview PNG. |
| Optional report/replay | `dm_2d_analyze` → `dm_2d_result` | Use new output directories and retain provenance. Not required for ordinary measurements. |

Native tools are a separate catalog. The mainline baseline's crop returns a
retained hidden image. In this feature, explicitly use qualified show, preview
or READ as appropriate: show hands the exact result to a document, preview
returns display pixels, and READ returns numerical bytes with calibration.
Scientific persistence uses the explicit saved-response NPY encoder; it is not
DM SaveAs. For uint32, use an explicit ID/ROI and the separately qualified
operation, then SHOW or READ its returned ID. Preserve native dtype/precision
semantics and export uint32 as `<u4`, float32 as `<f4`. For a complex spectrum,
request an eligible real/imaginary component before the scalar READ interface.
Setup and rollback remain in [the native guide](experiments/native-bridge/mvp/README.md)
and [INSTALL.md](experiments/native-bridge/mvp/INSTALL.md).

Do not equate a document visible in DM with an MCP image received by the model, or either with a permanent scientific file.

## 6. Data handoff and provenance

Use a new output path; never overwrite a source, export or sidecar. Check the numerical format supports the required dtype and shape. Retain axis roles/order, units, both origin conventions where available, signed scales, source region, source identity, operation parameters and available input/output hashes.

For external work, use a separate environment, the exported data and a saved script. State the library/method and whether intensity calibration was applied. Do not claim the plugin natively supports a specialized algorithm because the agent wrote one. Ask before adding dependencies or sharing private data beyond the user's authorization.

Reopening an exported file and comparing its pixels/calibration is stronger evidence than merely receiving a path. Record which checks actually ran. Do not promise every format or scientific dataset has been validated.

## 7. Timeout, cancellation and cleanup

Cancellation stops waiting; it does not prove DM stopped. Never automatically repeat a dispatched operation with side effects.

For native crop, save and supply `request_id` before dispatch, together with the session and parameters. Query `dm_native_result` with that original ID in the same live session. Preserve `queued`, `running`, `failed` and `unknown` as distinct outcomes. There is no promised recovery after native STOP, host exit or a different session.

The same requirement applies to native frame, show, unary, binary, FFT, complex and
filter calls, and the separate file encoder's handoff ID. NB2 QUERY retains the
original operation, normalized arguments and result schema. Save the original
records; do not infer operation identity from a few result fields. Use the
matching NB2 DLL; an old NB1 plugin is rejected without protocol downgrade.

Do not transfer native recovery guarantees to the default backend. Use only its documented result mechanism; optional 2D result packages have `dm_2d_result`, but not every default operation has a retained native-style record.

Normal native STOP releases plugin-owned resources, not the whole DM process. Follow the ownership manifest and installation guide for removal after normal host exit; do not hot-replace DLLs or close unrelated documents. On any source/identity inconsistency or native fault, stop the affected path and preserve evidence instead of improvising a retry.

## 8. Boundaries and reporting

No camera, beam, stage or optical controls. Arbitrary DM-Script stays disabled by default. Real EDS/EELS quantification, general 4D layouts and reconstruction are not implied by existing basic tools. Keep calculations, scientific interpretation and required human confirmation separate.

A local bridge may return information that the client sends to a remote model provider. Respect the researcher's data policy; do not upload experimental files, private logs or vendor software by default.

Conclude a task with the target data/ROI, actual backend and computation origin, results and file/object references, source-protection checks actually performed, and unresolved limitations. Do not bury a failed or incomplete step inside a polished success report.

## 9. For agents modifying this repository

Use [AGENTS.md](AGENTS.md), [scope decisions](docs/SCOPE_AUDIT.md) and the actual branch's native documentation. Preserve the human-first README: describe user tasks and availability there; put schemas, ABI details, recovery contracts and test logs in dedicated references. Keep both human-language versions aligned.

Prefer finishing an end-to-end researcher task over adding unused operator names. DM-native capabilities stay native; explicitly requested external analysis stays a separate, provenance-preserving workflow. The [compatibility-generator RFC](https://github.com/wuchqwq/mcp-dm/pull/3) is future work and must not interrupt current native feature development.

For the explicit GUI selection → native 1D measurement → document/NPY handoff,
follow [the short workflow](docs/NATIVE_GUI_MEASUREMENTS.md). Preserve every
side-effect request ID before submission; histogram raw bins, native uint32
counts and binary64 transport are distinct.

For diffraction/lattice tasks, use the optional [crystallography companion](docs/CRYSTALLOGRAPHY_WORKFLOW.md)
after a bounded native numerical handoff. Run ASE/NumPy/SciPy in a separate
environment through the documented checkout CLI; this is external computation,
not an added MCP/native tool or a fallback. Prefer automatic spots and a
qualified Friedel-pair centre; use mathematical grid DC for native FFT exports.
Only ask for missing calibration, unresolved centre/identity or additional
scientific evidence. Compare FCC/BCC/HCP jointly, retain P ambiguity, unknown
uncertainties, measured vectors and alternatives. A complete run is not a unique
chemical phase identification. Preserve request IDs and use verify for existing
files; do not overwrite or automatically resubmit an unknown DM operation.
