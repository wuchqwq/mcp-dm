# Coordinate-bound overlays and multi-turn rendering

Use the existing `image_preview` and `image_annotate` tools to observe, mark and
revise an image without changing scientific values. This is the explicit external
image route; drawing and PNG encoding do not call DM. `image_fft` uses NumPy,
whereas `dm_native_fft` remains a separately selected DM operation. Neither a
missing physical scale nor absence of a phase identification blocks these tools.

## Coordinates and identity

Inspect the referenced view's `panels`. Select its exact `source_object_id` and
one of these coordinate spaces:

| `coordinate_space` | Coordinates and scope |
| --- | --- |
| `source_pixels` | Original scalar image coordinates, x right / y down. Composed ROI offsets retain the original frame identity. |
| `frequency_cycles_per_pixel` | Signed fx/fy on an external complex FFT, bound to the original spectrum ID. DC is zero; each axis has its own size and step. |
| `source_array_indices` | Imported scalar frequency data whose full frequency grid is unavailable: array indices only, with upstream metadata retained. |
| `rendered_image_pixels` (default) | Current PNG coordinates. A mark inside exactly one panel gains a source anchor automatically. |

`point`, `text`, `line` and `arrow` use pixel/bin centres. A line or arrow takes
`[x0,y0,x1,y1]`. `rectangle` uses half-open pixel edges; `polygon` takes 3..32
edge-coordinate xy pairs in a flat array. Use a line to trace a proposed streak,
or a polygon to outline a band. These are overlays, not automatic segmentation,
area measurements or evidence of a twin/defect. Fourier coordinates never become
nm/Angstrom values without separately sourced scale and aspect information.

For a source ROI `[20,12,140,84]` displayed at 60 by 36 pixels, the line
`[40,30,100,66]` in source pixels maps to `[9.75,8.75,39.75,26.75]` in the PNG.
At 120 by 72 it maps to `[20,18,80,54]`; its stored source anchor is unchanged.
Centres and edges use distinct half-pixel transforms. Non-square images and
odd-sized FFTs use their actual per-axis dimensions.

## Revisions

1. Save a fresh operation `request_id` before each call. Create a view or FFT,
   then call `image_annotate` on that view with an explicit annotation list.
2. Give a mark an optional stable `annotation_id` such as `stripe-a`. This is a
   label identity reusable across revisions, **not** an `image_result` query ID.
3. Pass the annotated object directly to `image_preview` to change gamma,
   display limits, FFT representation or thumbnail size. Values are re-rendered
   from saved arrays; anchors are projected afresh. FFT is not recomputed.
4. To move or retract marks, call `image_annotate` with the replacement list.
   Use each saved mark's `anchor` fields as input coordinates. `[]` removes all
   marks. The prior objects and their statuses remain queryable and exportable.

`hypothesized`, `user_confirmed` and `retracted` stay explicit. A display revision
never promotes a hypothesis to a user confirmation. A confirmation should state
what was confirmed (for example, location rather than scientific interpretation).
Retracted marks remain in metadata and are not drawn. A new ROI excluding an
existing anchor retains it with `visibility:outside_view` and does not clip or
move it to another object. Changing the ROI does not imply image registration.

A legacy PNG annotation crossing two comparison panels has no unique anchor.
It can still be recorded, but direct re-rendering rejects it with a specific
error. Replace it with one explicit mark per source or remove it first.
Unrelated frame/spectrum IDs and spatial/frequency domain mismatches reject.

## Export and validation

`image_export` writes to a new directory only: original-dtype scalar NPY or exact
complex128 FFT NPY, the current PNG, display/annotation parameters and a bounded
immutable provenance history. Overlays never enter scientific arrays. The PNG
is a display rendering, not a scientific intensity or phase file. All operation
request IDs, preprocessing, frame/ROI identity and user-context revisions stay
traceable. User context remains interpretation; operational user-stated XY
calibration is a separate versioned record, described below.

Synthetic tests cover offset/nested ROIs, independent x/y resizing, odd FFT
bins, display-only FFT changes, two-panel mapping, out-of-view/retracted marks,
wrong source/domain and export reopening. Node stdio tests require actual MCP
image content and fresh-client recovery. A separate source-blind Agent trial
uses the tool catalog and returned images on authorized read-only TIFF data;
detailed private inputs/results are kept outside this repository. This does not
qualify every client's image UI or DM native annotations.

## User-stated XY calibration

`image_calibrate` creates a new immutable wrapper around an explicit object.
For a new statement supply `scope:"image"` (one frozen frame) or
`scope:"sequence"` (one exact opened TIFF source), `xy_scale:{x,y,unit}` and
the actual user `source_text`. Both signed, nonzero axes are required; equal
X/Y is accepted only when supplied. Supported real-space units are `m`, `mm`,
`um`, `nm` and `angstrom` (`Å` and common micrometre symbols normalize).
Optional `uncertainty_x`/`uncertainty_y` are absolute scale standard
uncertainties. Omission means unknown, never zero; geometric measurement
uncertainty remains unknown without point-localization/covariance evidence.
Intensity units, diffraction calibration and frame/depth scales are separate.

The result's `xy_calibration` records the calibration ID, revision, previous
ID, source statement and exact `applies_to` identity. It is explicitly
`user_statement_not_independently_verified`. It does not alter the TIFF,
NPY, raw imported metadata or stored uint16 interpretation. Existing
`image_context.xy_scale` remains descriptive for backward compatibility.

Continue with the new wrapper ID. A sequence wrapper can feed `image_frame`;
its selected frames/views/FFT inherit the record. For an older saved frame or
complex FFT, call `image_calibrate` with `object_id` plus
`calibration_object_id` referencing an existing calibration wrapper. Do not
combine attach mode with a new statement. Different frame/sequence identities
are refused, even if filenames match. An image-scoped record cannot leak into
a different frame.

`image_measure` accepts original `source_pixels` for scalar images, or
`frequency_cycles_per_pixel` for a saved complex FFT. Cropped spatial views
retain original source-pixel coordinates; no clipping or coordinate guessing
is performed. For a signed real-space scale `(sx,sy)`, displacement is
`(dx*sx,dy*sy)`, and physical frequency is `(fx/sx,fy/sy)` in cycles/unit.
Physical length/frequency magnitude uses both axes before calculating an
angle or reciprocal period. No `2π` factor is introduced. A frequency vector
explicitly referenced to DC can report `d_spacing=1/|g|`; two non-DC points
report their frequency-difference period without claiming a lattice spacing.
DC has no finite period. Geometry alone never assigns an hkl or phase.

Spatial previews show a horizontal scale bar when active calibration is
present and the display is large enough (`scale_bar:false` hides it).
`spectrum_axes:true` labels saved FFT axes in cycles/unit under active
calibration, otherwise cycles/pixel. Scientific FFT axes and annotation
anchors always retain their original cycles/pixel; PNG frequency zoom never
re-centres DC or recomputes FFT. `physical_frequency_axes`, bar geometry and
`calibration_dependency` retain the precise conversion record.

Revise using a new statement on the calibrated object. Withdraw with explicit
`xy_scale:null`, the same scope, actual withdrawal text and a fresh request ID.
Both create a new record. Physical measurements retain their original
calibration dependency; a changed wrapper marks them stale and candidate
interpretations as requiring review. Pixel anchors and scientific status are
not silently changed. Call `image_preview` on the new wrapper to redraw
scale/axes, then remeasure. Annotation/export refuses an old PNG paired with
a different selected calibration (`STALE_CALIBRATION_DISPLAY`). Old requests,
PNGs, measurements and exports remain immutable and independently traceable.
Without an active scale, pixel measurements and FFT exploration continue;
no physical distance, true angle, intensity phase unit or depth is invented.

## Readable spectrum figures

Start ordinary FFT presentation with `image_preview(display_preset:"fft_detail")`.
This reusable recipe reads the saved complex spectrum, selects log amplitude,
disables smoothing/background subtraction and large axis frames, sets gamma 0.8,
enlarges to a 512-pixel display and uses the 5th/99.8th percentiles as display
limits. Explicit fields override the recipe. Those percentiles are a starting
point, not a claim that every weak feature is visible; inspect the actual image
and revise limits when needed. Changing only gamma/size later inherits the
computed limits. `display_range:null` explicitly requests full min/max instead.
The recipe never changes FFT computation or scientific values.
Recipe revision 2 slightly darkens midtones through `normalized**(1/0.8)`;
it does not subtract background, smooth, mask or threshold scientific data.
New explicit preset calls record `display_preset_revision:2`. Existing saved
views retain their original recipe, and omitted fields still inherit that view.
To darken an existing view while preserving its exact limits, change only
`gamma:0.8` rather than requesting a fresh automatic range.

## Frequency-region zoom

Use the same `image_preview` tool with `frequency_rect:[x0,y0,x1,y1]` to enlarge
a selected region of a saved complex FFT. These are **absolute, integer,
half-open bin edges in the original fftshift grid**, not PNG pixels, spatial
ROI coordinates or offsets within the last zoom. Check the spectrum shape and
`panels` before selecting. The old `rect` remains a spatial selection and is
rejected on FFT views, preventing a silent coordinate-domain change.

For a synthetic full spectrum of shape `[55,95]`, a view of `[38,22,58,34]`
shows only those original bins. Frequencies still use `(bin-floor(N/2))/N`
with N=95 or 55. The original DC bin stays `[47,27]`; it can lie outside a
different frequency window and is never recentered. Axis ticks describe the
original signed frequencies, including when the window excludes zero.

Omit `frequency_rect` to keep the saved window; use another absolute rectangle
to pan and `frequency_rect:null` to return to the full spectrum. Display limits,
gamma and optional filter settings inherit, so zooming alone does not change
contrast. An explicit `display_range:null` recalculates from the **full**
spectrum. Optional presentation filtering also runs on the full spectrum before
the display crop, preserving its original-bin sigma and boundary behavior.

The returned panel includes the original `fft_shape_yx` and visible
`fft_rect_xyxy`. Annotation anchors remain on the original spectrum ID and
cycles/pixel grid; resized or panned windows project them anew. Marks outside
the view remain in metadata as `outside_view` and reappear on return, without
being clipped or rebound to another bright spot. Add sparse small guides near
the visible evidence, using the paper examples below only as style references.

Zooming enlarges a display selection and adds no measured resolution. It does
not execute FFT, replace the spatial input ROI, perform inverse FFT or create
a new scientific spectrum. Export still contains the **full original complex
NPY**, plus the cropped PNG, visible bin rectangle, display recipe, annotations
and provenance. Preserve a full-spectrum reference alongside a zoom.

`interpolation:"nearest"` displays the original sampled bins as discrete cells
when enlarging, making coarse frequency sampling visible without interpolation
blur. `interpolation:"lanczos"` retains the existing smoother presentation.
Both resize the PNG only; neither creates new frequency information. This
choice inherits across revisions and is saved in exports. Keep enlargement
moderate and shorten a local guide if a full-spectrum arrow becomes too long.

Representative microscopy figures retain granular background, compact spots
and continuous streaks, with sparse thin arrows/circles or restrained labels.
See Fig. 3b in [Németh et al., 2014](https://doi.org/10.1038/ncomms6447), Fig. 1
in [Németh et al., 2020](https://doi.org/10.1021/acs.nanolett.0c00556), and Fig. 3
in [Németh et al., 2022](https://doi.org/10.1073/pnas.2203672119).
These are visual references, not interchangeable processing recipes. A
frequency mask used to reconstruct a real-space amplitude image is different
from smoothing the FFT's displayed amplitude. Do not copy a paper's mask width,
physical scale, indexing or phase conclusion onto uncalibrated data.

For a small saved FFT, use `image_preview` with `upscale:true`, `max_size:640`
and `spectrum_axes:true` (axes need a budget of at least 256). Axes are signed
cycles/pixel with y down, not a claim of physical reciprocal scale. Insets and
axis margins are included in `panels.image_rect_xyxy`; annotations continue to
use the same spectrum identity and frequency coordinates. Enlargement changes
display sampling, not the measured frequency resolution.

An optional `spectrum_filter` requires explicit `smooth_sigma_bins` (0..4) and
`background_sigma_bins` (1..64, larger than the smoothing sigma). It operates on
the selected amplitude/power/log-amplitude representation: Gaussian smoothing,
Gaussian background subtraction, then clamp negative display values to zero.
The implementation uses [SciPy gaussian_filter](https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.gaussian_filter.html)
in binary64 with `mode:reflect`, `truncate:4`; sigmas refer to the original FFT
bins, before display resizing. This can suppress weak features as well as noise;
retain the unfiltered view for comparison and use original arrays for measurement.
The filter is explicitly external and display-only, not a DM filter or a second
FFT. Its library/version/parameters are saved with the view and export.

Filter changes recalculate the display range unless a range is supplied.
Omitted filter settings inherit; `spectrum_filter:null` removes the filter.
Shared limits/gamma/filter parameters help compare frames without mistaking a
different rendering for a structural change. This route uses the independent
`requirements-images.txt` environment, including SciPy and Pillow >=10.1; do
not install or upgrade these packages inside GMS Python.

New arrows default to short, thicker cyan guides: `line_width:3`,
`arrowhead_size:6` and `arrow_length:24` (maximum shaft length in display
pixels, including the head). The actual direction and tip remain anchored to
image/frequency coordinates. Only the rendered tail is shortened; an already
short segment is never extended. `coordinates`, `anchor` and source mappings
retain the original segment; `arrow_render_coordinates` records the displayed
segment, and its text starts at the displayed tail. Resizing or frequency zoom
keeps the cap in display pixels. Both original endpoints must still lie in the
view; a hidden anchored segment stays `outside_view` until brought back.

Set `color:"orange"` for an explicitly proposed second-phase candidate. This
is a display convention, not detection or confirmation of a second phase;
`hypothesized`, `user_confirmed` and `retracted` remain separate. Cyan is the
default arrow color for every status, so confirmation does not silently recolor
an arrow. Explicit `white`, `amber`, `green` and other supported choices remain
available. Non-arrow defaults retain their existing status palette and width.

Override width/head as needed, or set `arrow_length:null` to draw the full
anchored segment (`4..128` display pixels are accepted for an explicit cap).
Existing saved revisions keep their recorded styles; old arrows without a
length cap re-render with their original full shaft. Stop arrow tips outside
bright features, use few marks, and keep labels at the outer tail so the evidence
remains visible. This presentation change never filters or changes FFT values.
Preserve earlier renders when a user requests filtered/enlarged views or
smaller arrows. Human approval of the revised figure is a separate step,
not inferred from successful tool calls.
