# Codex + the existing Image Panel

This opt-in route opens independent TIFFs without DM. Computation is explicitly
external NumPy/SciPy; it does not replace a failed `dm_*` operation. Start from
any useful image, selection or saved analysis, not a required phase pipeline.

## Enable once

Ask a local Agent to resolve the checkout, Node and an independent Python with
`requirements-images.txt`. Have it run the existing registration script with a
**new** name; the default DM registration stays intact:

```powershell
.\setup\register_codex.ps1 -Backend images -Name microscopy-images `
  -ImagePython 'C:\analysis\image-env\Scripts\python.exe' `
  -ImageWorkspace 'C:\analysis\images' -ContextWorkspace 'C:\analysis\contexts' -CheckOnly
```

After successful preflight run the same command without `-CheckOnly`. Neither
command installs Python packages or starts DM. Optional structure tools require
the explicit `-StructureWorkspace` / `-StructurePython` pair with their separate
requirements. Existing MCP names are refused rather than overwritten.

Install the three existing research Skills explicitly:

```powershell
.\setup\install_codex_skills.ps1 -CheckOnly
.\setup\install_codex_skills.ps1
```

Existing same-name Skills are refused. All three remain siblings so their local
links work. Refresh/reconnect the client, then verify it exposes `image_open`,
`image_panel_open/current/show` and `analysis_read`. Installation and tool
discovery alone do not prove that the model has read a Skill or received images.

Keep the client's normal approval policy. If a noninteractive client refuses
MCP calls because approvals are unavailable, consult its supported per-provider
or per-tool approval settings; do not globally disable approvals or sandboxing.
Read-only refusal means the data has not yet been inspected. The optional
preapproval settings must be an explicit local decision, not a registration side
effect. See [Codex MCP documentation](https://developers.openai.com/learn/docs-mcp).

## Say, select, continue

1. Say: “Open this TIFF read-only, show its **first frame** in the panel and call
   this analysis ‘my lattice comparison’. This whole sequence has X/Y = … per
   original pixel.” Omit physical scale when unknown. Codex handles internal
   object/request IDs; human frame 1 means `frame_index:0`.
2. Draw a rectangle in **框 ROI**, then say “Do a local FFT here.” Codex reads
   `image_panel_current`, uses the exact source rectangle with visible window /
   mean-subtraction settings, computes `image_fft` and returns its saved preview
   to that same panel with `image_panel_show`. Use **交给 Agent** after selecting
   when a draft needs publishing. The model is not automatically awakened.
3. Choose **点选峰／位置** or draw an arrow/line; save the mark. Say “Measure this
   period.” A saved FFT point measures from mathematical DC; a line/arrow uses
   its actual endpoints. Display arrow shortening does not change those anchors.
4. Drag that mark and click **保存这条标记**, then say “Recalculate.” The saved
   changed mark remains selected; `last_operation.annotation_ids` identifies it.
   Codex measures the new coordinates, retaining the old measurement. A changed
   scale is a new sourced `image_calibrate` record; re-render/re-measure against
   that version. Display edits only call `image_preview`; neither requires
   recomputing an unchanged FFT.
5. Say “Export the current figure, scientific array and provenance, then save
   this analysis.” The Agent chooses a fresh output directory; existing exports
   are refused. Next connection: “Continue ‘my lattice comparison’.” It reads
   the named context, then inspects the live panel if one exists. A stopped
   panel needs an explicit new launch from the saved display, not a replay of an
   unknown original launch. Old objects/exports remain historical.

Dirty or newer drafts queue Agent results for explicit acceptance. A queued
result is not yet the displayed image. Do not replace a draft just to make a
demo look automatic. Scientific arrays, source/frequency coordinates, calibration
versions and computation provenance remain in the existing provider objects;
the panel and named analysis only reference them.

## Repeat with a public synthetic input

```powershell
& 'C:\analysis\image-env\Scripts\python.exe' -B .\examples\make_microscopy_trial.py 'C:\analysis\new-trial'
```

This refuses an existing directory and creates a three-frame uint16 TIFF plus
an independent fixture specification. Give Codex the TIFF path and the
**synthetic-only** statement “X/Y = 0.02 nm/px, entire sequence”; do not give the
model the numerical answer manifest. Circle an interior ROI, inspect/measure
the spectrum, move a mark, revise the synthetic scale, and reconnect/export.
An independent checker can compare the saved science with the fixture. The
fixture's scale is never a default for experimental data.

## Evidence and remaining manual steps

The researcher still draws/selects the intended region, saves a dragged mark,
says “continue”, and accepts a queued result when a draft exists. They need not
copy internal IDs, JSON or temporary paths. Exact client/image/human evidence
must be reported separately: MCP image content, model visual inspection,
browser rendering and a human gesture are different claims. This route adds no
GMS/native qualification; Materials Project is an independent optional provider.
