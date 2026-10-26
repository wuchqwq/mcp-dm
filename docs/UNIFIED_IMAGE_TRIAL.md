# Try the unified image tools

The PR #12–#23 feature chain and closeout fixes are integrated into `main`.
Use a clean checkout of current main for the combined trial. Do not manually
merge the old stacked branches or reset a working tree with local changes.
This integration is not a new stable native release: default v0.6 remains
unchanged, and image/structure/native paths still require explicit opt-in.
The native adapter remains restricted to the exact supported GMS build and
per-operation scopes, including small float32 return with nm or 1/nm units.

## Connect once

In a separate checkout, fetch and select the trial branch without resetting a
dirty checkout. Use Python >=3.10 with `requirements-images.txt` in an independent
environment. Never install these dependencies in GMS Python. Configure your
MCP client using `mcp.images.json.example`, with the selected checkout's absolute
`server.mjs`, `DM_MCP_BACKEND=images`, an absolute `DM_IMAGE_WORKSPACE` for saved
objects and `DM_IMAGE_PYTHON` pointing at that environment. Reload the client and
inspect its tool list. DM need not be running, and existing `dm_*` entries need
not be changed. Scientific arrays are private local files; do not commit the
workspace or its exports.

The Agent can open a TIFF by path, select frames and keep the returned IDs.
Researchers can say, for example, "Compare these two frames using the same
display range" or "These are original pixels; both axes have this scale for
the entire sequence." The Agent must distinguish an example scale from an
actual user statement. An XY value does not supply an intensity/phase unit,
frame-depth spacing or axial resolution.

## Revise one observation

Use `image_annotate(updates:[...])` to edit an existing stable annotation ID;
omitted marks and fields persist. Coordinates are in its saved scientific
anchor domain, not the shortened displayed arrow shaft. Kind, source and domain
cannot be changed by this operation. `status:retracted` hides a hypothesis while
keeping its history. The original replacement-list interface is still available.
See [partial annotation updates](ANNOTATION_UPDATES.md).

Operational calibration is a separate versioned `image_calibrate` record.
`image_context` remains useful for interpretation and storage-value meaning;
its legacy `xy_scale` note alone does not enable physical computation. Active
real-space XY calibration feeds measurements, optional spatial scale bars and
physical FFT axes. A changed/withdrawn scale creates a new record; old exports
remain historical. Save request IDs before dispatch and query `image_result`
after a timeout rather than repeating an unknown operation.

## Point and drag locally

The optional local panel reuses the actual stdio MCP tools and saved object
IDs. It is not a chat application or another analysis backend. After the Agent
has created a view, it calls `image_panel_open` with a pre-saved request ID and
opens the returned loopback URL. IDs and configured paths remain internal. Drag a rectangle to select an ROI, click a peak,
or choose an existing annotation and drag its position/endpoints. Review the
coordinate readout before saving. View zoom/pan and draft display adjustments
are local; pressing a save/apply button submits a bounded tool operation and
creates a new immutable object. Scientific frequency anchors always use the
original FFT grid, including when the display is zoomed away from DC.

A completed gesture exposes the exact view/source/domain through
`image_panel_current`; say “look here” and the Agent can continue without a
selection-file path. `image_panel_show` offers the result to the same panel,
queuing it behind unsaved drafts. This does not automatically wake a model.
The legacy selection-file CLI remains available for manual compatibility. The panel URL contains a local session token;
keep it private. The panel binds only to loopback and has no arbitrary script
execution, general file browser or native DM controls.

## Verify rather than infer

Check that source hash, frame, ROI and exact FFT identity are retained. A display
change must report no FFT recomputation and export the same complex NPY. Check
a known displacement against signed XY scales; for a frequency vector use
`(fx/sx, fy/sy)` in cycles per length, with no extra factor of 2π. Its reciprocal
magnitude is a geometric period, not unique phase identification. Supplied
scale uncertainty and unknown localization/covariance must remain distinguishable.

Export to a new directory and independently reopen NPY, PNG and the manifest.
Keep raw pixels, calibration source/revision, display recipe, annotation status
and computation provenance together. Unknown XY scale still permits pixel
measurements, ROI and cycles/pixel FFT. A PNG returned by MCP, a model actually
viewing it, browser gesture testing, a human gesture and a live DM operation
are separate acceptance scopes; none proves the others.

## Structures, simulation and numerical return

The same checkout includes optional [structure tools](STRUCTURE_DIFFRACTION_TOOLS.md).
Install their separate requirements/environment only when needed, add
`DM_STRUCTURE_WORKSPACE`/`DM_STRUCTURE_PYTHON`, then inspect the real MCP catalog.
An optional local 3Dmol asset enables a read-only structure viewer; a projection
PNG alone is not 3D acceptance. [Native numerical import](DM_NUMERIC_RELAY.md)
has a separately qualified limited float32 ASCII-unit scope; do not expand it merely because
structure or image tests pass. No new backend is selected implicitly.
