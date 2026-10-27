---
name: microscopy-observe-revise
description: Observe a scientific image or saved FFT, revise display/calibration/centre/points, and continue measurements using unchanged scientific arrays. Use for iterative microscopy corrections, including pixel-only TIFF exploration.
---

# Observe and revise the selected evidence

Use an explicit immutable input or obtain a new bounded DM capture. `image_info`
inspects a saved object; it is not a fresh look at a live DM image. For a TIFF use
`image_open`, then an explicit zero-based `image_frame`. Keep source/frame/ROI
identity and signed axes. A preview PNG is display data, never a measurement array.
Human frame numbers start at one: “first frame” means `frame_index:0`, not 1.

Choose only the operations needed. Request `image_preview` and actually inspect
the returned image when making visual claims. A PNG path or transported MCP image
does not alone prove a model/client viewed it. Fixed display limits make frame
comparison interpretable; per-frame auto-stretch is not structural evidence.

For mouse input, call `image_panel_open` on the selected saved view and give its
URL to the user. On “continue” call `image_panel_current`; retain `panel_id`,
`view.object.object_id`, `view.edit_state.draft_revision`, the exact selection
and its panel/source/domain. Use source-pixel ROI edges for spatial processing;
frequency coordinates are cycles per original pixel, not rendered PNG pixels.
If the user dragged a mark, inspect the bound `annotation_edit` and commit its
sparse update with `image_annotate` before measuring its changed anchor. Do not
measure a shortened displayed arrow tail or silently treat a draft as saved.

Return the saved result with `image_panel_show`, binding the previously inspected
object and draft revision. A queued result is not visible yet: preserve the
user's newer drafts and let them accept it. Read current state again after a
conflict; do not fabricate a newer revision to force presentation. Keep IDs and
tool JSON internal. If an image block cannot be inspected by the actual model,
report that limitation and keep the human-visible panel usable.

For an external local FFT, choose the source-pixel half-open ROI, window and mean
subtraction explicitly with `image_fft`. A saved FFT can be re-rendered, zoomed
with `frequency_rect` in its original fftshift-bin grid, or annotated without
recomputing the complex array. Zoom adds no measured frequency resolution.

For a user/native scale revision use the existing sourced `image_calibrate`
record, preserving scope, signed X/Y, units and unknown uncertainty. Re-render
the returned wrapper to update bars/axes, then `image_remeasure` valid saved
points on that exact grid. Do not run another FFT merely because scale changed.
Pixel-only input may still be viewed, measured and transformed; do not output
nm/Å or physical angles without the required scale/aspect-ratio evidence.

`image_center` corrects an established reciprocal scalar centre. It cannot move
the mathematical DC of an external complex FFT. `image_remeasure` moves only
an originally explicit DC endpoint with a centre correction; explicit new points
need a sourced correction. A changed source/frame/ROI/FFT producer invalidates
old grid anchors rather than silently stretching or translating them.

Keep a display-only change distinct from a scale, centre or point correction.
The former does not invalidate measurements; the latter requires updated
measurements and review of old registration/comparison evidence. A late result
may remain historical but must not advance a newer current selection.
If a selected AnalysisContext is in use, inspect active/stale slot states and
commit against the revision read before starting work. Reopening the client
reads those saved references; it does not create a new capture or reconstruct
unknown requests. A CAS conflict requires reviewing the current dependencies,
not changing only the expected revision to force an old result into the task.
Use `analysis_read` before processing and `analysis_update` afterward, selecting
saved object references by the configured image/structure aliases. The tools
resolve scope and dependency fingerprints; do not ask the user for hashes or
internal IDs. Recover an exact context mutation with its saved request ID via
`analysis_read`; query scientific operations with `image_result` separately.

Annotations remain hypotheses, caller-confirmed statements or retracted marks.
Short cyan arrows are display defaults; orange may distinguish an explicitly
proposed second candidate, never a detected phase. Export numerical NPY and
available PNG/parameters/provenance to a new directory with `image_export`.

Save request IDs first; recover through `image_result` after a stopped wait.
See [validated call shapes](examples.json). Example scales are synthetic and
must never become an experimental calibration.
