# Optional local image interaction panel

The regular `image_*` MCP tools return PNG content plus scientific coordinates.
They do not currently receive mouse selections from every MCP client. This
optional browser panel supplies that gesture surface using the **same actual
stdio MCP server**, external Python worker, immutable objects and annotation
IDs. It is not a chat application, native DM display or a second analysis engine.

## Open an existing image object

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
- Click a peak/location, draw a line or short arrow, give it a stable ID and
  save. Select an existing ID, choose **拖动已有标注**, and drag a handle or
  the whole shape. **保存这条标记** submits one sparse update, retaining every
  other mark and its anchor. Color and candidate/confirmed/retracted status
  remain separate. Orange is a proposed second-phase display convention only.
- A line can be measured; an FFT point is measured relative to mathematical
  DC `[0,0]`, even when DC lies outside a zoom. A period is geometric evidence,
  not a phase identification. Active XY calibration determines whether physical
  values can be returned; no scale means pixel/cycles-per-pixel results only.
- Gamma and display limits update a **PNG approximation draft** immediately.
  Quantization and clipping in the existing PNG cannot be recovered locally.
  Clicking **提交显示调整** invokes `image_preview` once, re-rendering the saved
  scientific array; it does not execute another FFT. The saved rendering is
  authoritative. Annotations in the temporary draft may also change brightness.
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

Zooming the canvas and scrolling pan the **display**, leaving scientific
coordinates unchanged. Imported scalar frequency arrays without a full FFT
grid retain array-index semantics; the panel does not invent original
frequency/real-space mapping. A selection must remain in one exact panel.

## Return the current choice to the Agent

Click **把选择交给 Agent** after selecting. The latest record contains the
current immutable object ID, original spatial/frequency coordinates, exact
panel mapping and last operation. The Agent reads the printed `selection_path`:

```powershell
node tools/image_panel.mjs --selection 'C:\analysis\image-workspace\panel-journals\SESSION\current-selection.json'
```

The Agent can then call `image_info` on that object and compose its next tool
call. Users do not type object IDs or JSON for routine gestures after launch.
Initial launch still needs the Agent/terminal to provide an existing ID and
paths; the panel is not yet registered as an MCP launch tool. Reading a record
does not automatically trigger an Agent turn or send a message.

An Agent that already has the private panel URL can use same-origin typed
`POST /api/action` with `X-Panel-Token`, `expected_object_id`, `action:"show"`
and `params:{object_id:NEW_ID}` to display an explicit existing revision. There
is no global mutable "latest image": external Agent-created objects are not
silently substituted for a user's current view. Competing browser edits to
the same old view return HTTP 409; refresh and inspect rather than overwrite.

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
