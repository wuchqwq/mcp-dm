# Native capture calibration in external tools

`image_open(source_kind:"capture")` reuses the existing independent native
READ/schema-1 validator before activating geometry. An internally consistent
capture with supported physical XY axes receives an immutable `xy_calibration`
revision, with `source:"native_dm_capture"`. The record binds the captured
object, original READ/session/host identities, file hashes, ROI and axis evidence.
This validates saved evidence; it does not certify metrological accuracy, live
source stability or an atomic capture.

No additional scale question is required for that admitted capture. `image_measure`
and the spatial scale bar use the same record as `image_calibrate`. Signed and
anisotropic X/Y are retained. Different recognized axis units are converted to
one record unit; raw origins, signed scales, physical zero, original units and
conversion factors remain available. Capture offsets are already included in
the local axis zero, while subsequent view crops retain the captured source grid.

Real-space length and reciprocal-space inverse length are separate domains.
Generic scalar reciprocal captures use `source_array_indices`; they return
physical frequency vectors and geometric reciprocal periods, never real-space
distances. A d-spacing requires an endpoint at an explicitly recorded DC. For
tracked native Fourier scalars, validated mathematical bin coordinates establish
DC, independently of DM's preserved half-bin calibration. No near-zero threshold
is used to guess DC. Historical external-import domains are creation evidence,
not proof of the edited current domain; a conflict without a validated current
Fourier contract leaves the capture pixel-only.

`image_calibrate` creates a new sourced user revision or withdraws the selected
record. Use explicit `coordinate_domain:"reciprocal_space"` and inverse-length
units to correct reciprocal scalar axes; a real-space nm/pixel statement cannot
relabel them. Scale revisions cannot change an established native or user
coordinate domain, including after withdrawal; this is not an array
reinterpretation interface. Unknown-domain input does not acquire a reciprocal
domain merely from an inverse-unit scale. Native and earlier user records remain immutable and exportable.
Scale uncertainty remains unknown unless supplied. Intensity, phase units,
frame depth and phase identification are not inferred from XY metadata.

A saved external complex FFT inherits its source's real-space record. Revising
or attaching a scale redraws physical frequency axes and recomputes geometry;
it does not recompute or rewrite the saved complex array. Preview the new
calibration wrapper before annotation/export so display dependencies agree.

Missing, unsupported or ambiguous axes keep browsing and pixel measurements
available, with `calibration_admission.status:"pixel_only"` and a reason.
Malformed native receipts, inconsistent arrays/axes or changed hashes still
fail import; they are not downgraded to unknown calibration. Ordinary schema-1
metadata and descriptive `image_context.xy_scale` do not automatically activate
a physical scale. New tool instances preserve original request recovery and
immutable exports.

Tests use hand-enumerable signed 3–4–5 vectors, mixed nm/µm and reciprocal units,
READ plus nested crop offsets, mathematical DC versus the raw native half-bin,
saved-FFT revision without another transform, withdrawals and changed evidence.
Offline protocol/MCP tests do not constitute real-DM or human-edit qualification.
