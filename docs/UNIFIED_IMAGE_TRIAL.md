# Try the unified image tools

This is an opt-in feature branch, not a main release. Use
`feature/unified-image-interaction` for the combined trial. It includes the
PR18 annotation/zoom work, PR16 pixel tools and PR17 fixes. Do not install the
old PR17 branch separately or merge every open PR into a local checkout.
PR12/15 supply the retained native/crystallography ancestry; PR13/14 fixes and
documentation already carried into this line remain present. None of these
open PRs is implicitly merged into main by this trial.

At the initial remote check, main was `5eac70c` and PR18 was `6ecda05`.
PR12/15/16/18 were open; PR13/14 were also open but their feature-branch merges
were already in this ancestry. PR17 was merged into PR16, not main. This trial
is stacked directly on PR18; no reset, duplicate integration or main merge is
part of enabling it. Check GitHub again before integrating these branches.

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
has created a view, it can start:

```text
node tools/image_panel.mjs --workspace ABS_WORKSPACE --python ABS_EXTERNAL_PYTHON --object VIEW_OBJECT_ID
```

Open its printed loopback URL. Drag a rectangle to select an ROI, click a peak,
or choose an existing annotation and drag its position/endpoints. Review the
coordinate readout before saving. View zoom/pan and draft display adjustments
are local; pressing a save/apply button submits a bounded tool operation and
creates a new immutable object. Scientific frequency anchors always use the
original FFT grid, including when the display is zoomed away from DC.

"Hand selection to Agent" records the exact view, coordinate domain, source ID
and selection in the panel journal's `current-selection.json`; the Agent can
read it with `node tools/image_panel.mjs --selection ABS_SELECTION_JSON`.
This explicit file handoff does not automatically wake a model or send the
private image to a remote service. The panel URL contains a local session token;
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
