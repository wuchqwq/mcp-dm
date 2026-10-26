# Optional local image interaction panel

The regular `image_*` MCP tools return PNG content plus scientific coordinates.
They do not currently receive mouse selections from every MCP client. This
optional browser panel supplies that gesture surface using the **same actual
stdio MCP server**, external Python worker, immutable objects and annotation
IDs. It is not a chat application, native DM display or a second analysis engine.

## Open an existing image object

When the opt-in image workspace is configured, the Agent calls
`image_panel_open(object_id, request_id)` and opens its returned loopback URL.
The researcher does not enter IDs, JSON or paths. The Agent retains `panel_id`
internally. The owned helper survives MCP client disconnect; querying the same
original request reuses that panel. Stopped/unknown launches are not restarted
automatically. The CLI below remains available for explicit manual setup.

Use the integration branch containing `tools/image_panel.mjs` and configure the
same independent Python environment and output workspace as the Agent's
`image_*` tools. No new browser framework or package is required. In PowerShell:

```powershell
node tools/image_panel.mjs --workspace 'C:\analysis\image-workspace' --python 'C:\analysis\image-env\Scripts\python.exe' --object EXISTING_OBJECT_ID
```

All three arguments are explicit. The object must already exist in that
workspace, having been opened through the normal MCP tools. The command prints
a loopback URL and a `selection_path`. Open that URL in a local browser; it
contains a session token in its fragment. Keep it private. Nothing is uploaded.
The service listens on `127.0.0.1` only, permits only its fixed local UI files
and typed actions, and rejects cross-origin requests. It provides no arbitrary
file, script or MCP-tool execution endpoint. Close the Node process normally
with Ctrl+C when finished; the MCP worker is closed through stdin, with no DM
process interaction.

## Point, drag, revise

- Select a frame with a human-facing frame number starting at **1**; stored
  `frame_index` remains zero-based. Existing fixed display limits and gamma
  follow frame changes. Sequence-wide user calibration follows by explicit
  scoped record attachment; an image-only scale is not applied to other frames.
- Draw a pixel ROI and choose **查看选区** or **选区 FFT**. On a saved FFT,
  **查看选区** enlarges the selected frequency bins without recomputing FFT.
  Integer processing rectangles snap outward to bin/pixel edges; the exact
  rectangle is displayed **before** submission. Scientific annotations retain
  their continuous original coordinates. There is no hidden clipping.
- Click a peak/location, draw a line or short arrow and save; its internal ID
  is generated automatically. In the default selection mode, directly click
  and drag an existing mark or its small endpoint handles. **保存这条标记** submits one sparse update, retaining every
  other mark and its anchor. Color and candidate/confirmed/retracted status
  remain separate. Orange is a proposed second-phase display convention only.
- A line can be measured; an FFT point is measured relative to mathematical
  DC `[0,0]`, even when DC lies outside a zoom. A period is geometric evidence,
  not a phase identification. Active XY calibration determines whether physical
  values can be returned; no scale means pixel/cycles-per-pixel results only.
- Gamma and display limits update a **PNG approximation draft** immediately.
  Quantization and clipping in the existing PNG cannot be recovered locally.
  Clicking **保存显示** invokes `image_preview` once, re-rendering the saved
  scientific array; it does not execute another FFT. The saved rendering is
  authoritative. A verified clean PNG, saved marks and gesture drafts use separate canvas layers;
  grayscale adjustments do not recolor the marks.
  Reopening a saved annotated object resolves its explicit render-base recipe
  through `image_info`, so gamma, limits and axes match the visible PNG. The
  separate `effective_display` and `display_source_object_id` fields identify
  that recipe; the current annotation object ID and calibration are preserved.
- Enter the actual user statement, scope, signed X/Y scale and unit to create
  a calibration revision. No experimental scale is filled in by default.
  Spatial scale-bar and FFT frequency-axis checkboxes request corresponding
  calibrated renderings through `image_preview`. Withdrawal creates a new
  version; it does not overwrite an old export or source metadata.
- **导出** writes to a fresh directory under the workspace's `exports/` folder,
  retaining scientific NPY, PNG, annotation/calibration records and parameters.
  The original source remains read-only. There is no arbitrary target-path
  browser API and existing output directories are refused by the real tool.

Mouse-centred wheel zoom and Space/middle-button drag pan the **display**, leaving scientific
coordinates unchanged. Imported scalar frequency arrays without a full FFT
grid retain array-index semantics; the panel does not invent original
frequency/real-space mapping. A selection must remain in one exact panel.

## Return the current choice to the Agent

A completed gesture publishes its exact source/frequency coordinates without
running scientific computation. Say “look here” or “continue”; the Agent calls
`image_panel_current` and chooses the next ordinary `image_*` tool. There is
**no automatic model wake**. The returned PNG is the saved view; `edit_state`
separately identifies unsaved display/annotation drafts, including a bound
`annotation_edit` with its scientific coordinate domain.

The Agent sends an existing result through `image_panel_show`, binding the
inspected object and draft revision. The browser polls a small authenticated
revision endpoint and displays a clean new result in the same panel. Dirty or
newer drafts queue it for explicit acceptance. Late worker responses cannot
switch the visible base under a newer gesture. A queued result is another saved
branch: accepting it does not merge annotations or overwrite older objects.

Undo/redo is bounded local draft history, not deletion of scientific records.
Saving a mark preserves an independent display draft. Unsaved edits are not
promised across a page reload; a surviving dirty lease requires an explicit
discard rather than silently reporting a clean view. Save requests are
serialized, while local zoom/pan/selection remain available. The original
selection-file CLI remains a compatibility path, not required for routine MCP
handoff.

Each side-effect call receives a request ID saved and flushed to a private
request journal **before dispatch**. Errors include the original ID. After a
timeout or cancelled wait, query `image_result` using that ID; the panel never
automatically re-submits an uncertain operation. `current-selection.json` is
an atomic convenience handoff snapshot, not a replacement scientific store.

## Validation scope

The dedicated tests check centre/edge mapping, signed original frequency
coordinates on odd-sized spectra, ROI snapping, invalid selections, token and
origin rejection, stale competing writes, and a real stdio MCP → external
Python → returned PNG → sparse annotation edit → fresh-client same-request
recovery → export chain with synthetic TIFF bytes unchanged. Browser rendering
and actual human drag acceptance must be reported separately from those tests.
This panel does not qualify DM-native operators, other TIFF dtypes or physical
interpretations. Private experimental paths/images must not enter public tests.
