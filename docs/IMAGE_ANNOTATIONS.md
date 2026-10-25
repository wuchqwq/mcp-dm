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
traceable. User context remains interpretation, not an applied calibration.

Synthetic tests cover offset/nested ROIs, independent x/y resizing, odd FFT
bins, display-only FFT changes, two-panel mapping, out-of-view/retracted marks,
wrong source/domain and export reopening. Node stdio tests require actual MCP
image content and fresh-client recovery. A separate source-blind Agent trial
uses the tool catalog and returned images on authorized read-only TIFF data;
detailed private inputs/results are kept outside this repository. This does not
qualify every client's image UI or DM native annotations.

## Readable spectrum figures

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

For sparse guides, start with `line_width:1` and `arrowhead_size:3` or `4`
(display pixels, preserved across revisions). Stop arrows outside the bright
feature, keep labels near the outer tail, and avoid drawing lines through the
evidence unless that line itself is the proposed observation. User feedback
can revise the presentation without confirming a scientific interpretation.
Preserve earlier renders when a user requests filtered/enlarged views or
smaller arrows. Human approval of the revised figure is a separate step,
not inferred from successful tool calls.
