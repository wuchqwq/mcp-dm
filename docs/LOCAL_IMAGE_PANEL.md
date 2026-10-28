# Optional local image interaction panel

Researchers can now open a local TIFF, recover multiple measurements and export
their table without a model session: see the [Researcher Data Inspector](RESEARCHER_DATA_INSPECTOR.md).

For independent editable labels, diffraction typography, domain layers and
publication SVG/PNG output, see [Microscopy annotations and figure export](PUBLICATION_ANNOTATIONS.md).

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
- The canvas tools sit beside the image; the inspector starts closed. Select a
  mark to open its properties, or open settings for display, calibration, FFT
  options and recovery diagnostics. The source badge uses recorded provenance;
  synthetic demonstrations are identified explicitly.
- Click a peak/location, draw a line or short arrow and save; its internal ID
  is generated automatically. In the default selection mode, directly click
  and drag an existing mark or its small endpoint handles. Releasing a drag or
  changing a field automatically submits a sparse edit, retaining every
  other mark and its anchor. Color and candidate/confirmed/retracted status
  remain separate. Orange is a proposed second-phase display convention only.
  After saving a single new/edited mark, that exact visible mark remains the
  current scientific selection and `last_operation.annotation_ids` identifies
  it. The researcher can say “recalculate” without clicking the peak again.
  Retracted/out-of-view marks and multi-mark edits are not guessed selections.
  Saving an annotation or revising display preserves the camera when the
  scientific grid and its view mapping are compatible. Switching source/frame
  or an incompatible crop fits the new view. Failed saves keep local edits;
  use the original request recovery before retrying an unknown write.
  Undoing an automatically saved edit creates a compensating immutable revision;
  it does not delete history. Unsaved gesture/display undo stays local.
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
- Calibrated reciprocal scalar captures also support line measurement and
  point-to-recorded-DC measurement through the same backend. A point requires
  an active scale and an explicit recorded centre; the panel never guesses one.
  Uncalibrated/withdrawn reciprocal arrays still permit two-point pixel geometry.
  The current record's domain and signed units are retained in calibration edits;
  this is not a way to reinterpret an unknown array as a diffraction image.
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

Pointer moves paint locally on the next animation frame. Draft delivery keeps
only the newest unsent snapshot and uses small acknowledgements, without
returning image Base64 on every move. Gesture boundaries retain immediate
durable protection; intermediate convenience snapshots coalesce. A late Agent
result stays queued while there is an active gesture or unsaved draft.

## Reproduce the interaction fixture

In an independent analysis Python environment (NumPy, Pillow, tifffile), run:

```powershell
python examples/panel_workbench_fixture.py --output C:\analysis\panel-demo
```

The printed manifest supplies the workspace and object for the opening command
above. This creates a calibrated synthetic periodic texture with 28 marks
(24 points, two ROIs and two lines), not an experimental TEM image.

The interaction refresh was exercised in the actual local browser with this
fixture: zoom/pan, automatic point drag save, ROI FFT, peak measurement and
handoff, display revision, queued Agent preview and export. The FFT peak example
returned 0.0555556 cycles/pixel and 0.36 nm under the stated synthetic 0.02 nm
grid. These are fixture geometry, not a material identification. The original
array and older annotation versions remained intact. Targeted UI, camera,
draft transport, concurrency and feedback tests were run; no native DM or full
Windows/Python/C++ qualification is implied.

## Return the current choice to the Agent

The bounded [twin-feedback loop](TWIN_FEEDBACK_LOOP.md) also accepts a scoped
research observation through this same panel. The researcher can state that
twinning is present; the saved `image_context` reference is returned as
`view.research_observation` by `image_panel_current`. The statement confirms
presence only, never a twin law, orientation or HKL. Synthetic demonstrations
are explicitly labeled nonhuman input. Submitting it preserves the current
image, selected peak and unsaved drafts; subsequent results use the ordinary
`image_panel_show` queue. No automatic model wake is added.

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

## Client lifetime and reconnect

Use a persistent Codex conversation/client while making selections in the
panel. The helper can survive an ordinary MCP stdin disconnect, but it is not
an operating-system service: `detached`/`unref` does not guarantee survival when
an ancestor application terminates its entire process tree. In a Windows
one-shot `codex exec` trial, the panel rendered successfully and then its
helper stopped after the command exited. A still-visible browser image was
therefore not a live selection connection; its next gesture could not reach
the backend. Do not claim a completed selection until `image_panel_current`
returns the corresponding coordinates.

Keep the interactive client or its persistent app-server running for the
human–Agent exchange. A new MCP connection may reuse a **still-live** registered
panel and its saved original request. The standalone CLI above is also useful
in an independently kept-open terminal; by itself that CLI does not create a
managed `image_panel_open` registry entry. Its selection-file option remains a
manual compatibility handoff, not a replacement for the normal panel tools.

If the helper has stopped, querying its old open request does not restart it.
Recover the saved scientific objects or named analysis, then explicitly open
a new panel on the chosen saved object with a new panel-open request. This
creates a new viewing session, not a retry of an uncertain scientific
operation. Unsaved browser drafts are not guaranteed across host termination;
the last saved arrays, calibration, annotations and original result records
remain separate from the panel lifetime.
