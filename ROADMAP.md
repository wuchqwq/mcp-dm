# mcp-dm scope and roadmap

## Goal

Let a general-purpose agent inspect DM data, view selected images, invoke common post-acquisition operations correctly and retrieve calibrated results for further work. This repository is a tool interface, not a scientific decision-maker or a new agent application.

Future native processing stays inside DigitalMicrograph. The MCP/plugin layer
adapts verified built-in operations and handles data identity, parameters,
calibration, ownership and result delivery. It does not grow a parallel
Python/C++ analysis engine. Existing v0.6 and optional report paths remain
compatible; independent numerical oracles are for tests only.

## Core acceptance

- A new user can connect to the real DM backend and identify the intended data.
- Each operation targets explicit data and preserves the documented coordinate, unit, dtype and no-overwrite contracts.
- A preview corresponds to the referenced input and has an explicit coordinate mapping. Display pixels never replace numerical input.
- Values, calibration, source references and failure/unknown states can be used by another tool or the user.

A complete report is an optional integration example, not the definition of a successful MCP. An agent's ability to choose a scientifically appropriate region is evaluated separately from tool correctness.

## Existing capabilities to retain

Core metadata, ROI, crop, profile, FFT and exports; bounded 2D capture and preview; existing limited spectroscopy/4D tools. Preserve documented limitations and backward-compatible tool names. Capturing fixed input is useful for multi-step tasks but unnecessary for simple queries. A live image ID is not a pixel snapshot.

The report/replay worker remains optional. Preview needs only NumPy/Pillow in an external environment. Report rendering adds Matplotlib; status/verification do not import plotting libraries. The user-facing Skill is optional and is not installed by MCP registration.

## Next steps

1. Validate current scope/preview fixes with small synthetic inputs on the target Windows/DM/client combination. Historical host passes do not certify changed code.
2. Try small independent tasks: identify an image and its calibration; view a selected capture; take a specified profile; export a calibrated crop or FFT summary. Fix concrete usability or correctness failures without expanding the platform.
3. Gather feedback from a few research users when the core is usable. Add installation polish or another operator only when actual friction justifies it.

## Build-pinned native experiment

The default v0.6 backend stays unchanged. The opt-in native backend targets
Windows x64 GMS 3.53.4137.0 and exposes status, datasets, native mean, retained
result queries, experimental crop and the SHOW candidate. Earlier limited idle-host acceptance of the core
metadata/mean/MCP path and source preservation has passed with synthetic inputs
without a resident Python listener. Historical probe results and offline
surrogates do not certify changed native code.

Current P0 decouples raw mean from recognized incomplete spatial calibration,
while crop remains strict. Crop and new side-effect tools require a saved
request ID/session before dispatch, with same-session QUERY recovery only.
The current actual-host strict MCP trial passed calibrated/empty-unit raw
mean metadata, safe errors and immutable crop recovery/conflicts. Other
invalid spatial-number cases remain offline-only. P1 selects the bounded
`dm_native_show` native-document route for an existing plugin crop, without a
data copy or file-save interface; completed receipts and image correlation
passed. The trial remains HOLD: independent full-pixel/source checks, actual
display, document count and post-STOP document ownership are NOT_TESTED due
to pending desktop acceptance. IPC STOP/pipe/window cleanup passed; normal
host exit and owned DLL removal remain pending with the test host still open.
Native SaveAs stays deferred for insufficient string ABI and exclusive-write
evidence. The [synthetic trial](experiments/native-bridge/mvp/TRIAL_ACCEPTANCE.md)
keeps its independent answers private and separates protocol receipts from
actual host display and lifetime checks.

While the test desktop is unavailable, continue bounded static interface
review and independent acceptance design. [FFT readiness](experiments/native-bridge/mvp/FFT_READINESS.md)
tracks DM's own FFT entrypoints, unresolved complex-data/normalization and
calibration semantics, and the result-delivery requirements. Finding an export
does not qualify its ABI or add a public tool. Do not replace the loaded DLL or
use the pending host for exploratory calls; current SHOW/lifecycle HOLD remains.

Earlier native crop separately passed actual MCP and an independent one-shot GMS
Python oracle for explicit IDs, half-open bounds, every pixel, separate memory,
signed calibration, unchanged sources and duplicate-request identity. Its
output lifetime through STOP was separately accepted: the hidden crop ID
became invalid, its pipe/window disappeared and ordinary Python remained usable. The
test host then exited normally and manifest-owned DLL removal restored the
prior inventory without changing client configuration. The
qualified name scope is ASCII; the legacy Python/native non-ASCII name
comparison failed and remains NOT_QUALIFIED without heuristic conversion.
A plugin-retained result ID is not a displayed DM
document or model visual acceptance. Real experimental data, other
builds, concurrent image API use and vendor exception isolation remain
unverified. Keep the backend opt-in and the original client configuration
unchanged. See [the matrix](experiments/native-bridge/RESULTS.md) and
[native handoff](experiments/native-bridge/mvp/HANDOFF.md).

## Deferred, not silently completed

4D-STEM development; automated crystallographic identification, strain, EDS/EELS quantification or reconstruction; complete job scheduling; atomic snapshots; generic object versioning; arbitrary-script enablement; a report platform; new chat UI or multi-agent framework.

Local loopback is not authentication. Existing filesystem permissions and data-sharing limits remain relevant; comprehensive access controls are separate work. Normal operation timeout does not prove that DM execution stopped. See docs/SCOPE_AUDIT.md for the bounded audit and remaining risks.
