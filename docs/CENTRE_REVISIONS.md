# Continue measurements after a centre or scale correction

Image tools retain immutable inputs and explicit revisions. The selected wrapper
is the current input for an operation; the tools do not guess a global latest
image, frame, calibration or analysis. Querying an old `image_result` reviews
that historical result and never observes a changed DM image.
For continuing through constrained registration and comparison, see
[the connected tool example](CONTINUING_DIFFRACTION.md).

## Reciprocal centre correction

`image_center` accepts `object_id`, `center_xy`,
`coordinate_space:"source_array_indices"`, the user's actual `source_text`, and
a request ID saved before dispatch. Its input must be an established reciprocal
scalar image with an image-scoped calibration record. Coordinates are centres
in that immutable source grid, including the original capture/ROI mapping;
they are not PNG coordinates. Out-of-bounds/nonfinite values are refused.

The result is a new calibration wrapper. It keeps signed XY scale, source
identity and the original native calibration evidence, and records the new
`dc_index_xy`, `centre_revision_id`, user source and previous calibration ID.
Effective physical zero is `-centre_index * signed_scale`. Raw native axes stay
historical evidence, not a claim that DM's metadata was edited. Existing
measurements/exports remain unchanged and require remeasurement for the new
centre. A subsequent scale-only revision preserves this centre using the
already merged calibration contract.

An external complex FFT and a tracked native Fourier scalar have fixed
mathematical DC. This tool refuses to move it without changing the spectrum;
frequency zoom and camera/display motion do not change DC either. An arbitrary
two-peak difference remains a difference period, not a centre-to-reflection
d-spacing.

## Reuse saved points

`image_remeasure` takes the selected current `object_id`, a prior
`measurement_object_id`, and a pre-saved request ID. It returns a new `measure`
object with standard geometry plus `remeasurement` provenance. It verifies the
old manifest and original request, original scientific array hash, source/frame,
ROI, dtype/shape and FFT producer/grid. A fresh capture is a different fixed
input even if its current pixels happen to match; silently borrowing points
across captures or frames is refused.

With omitted `points`, saved positions are reused. If the original measurement
explicitly had DC as one endpoint, that endpoint follows the selected corrected
centre; the peak endpoint stays fixed. Reversing endpoint order is preserved.
For a non-DC difference, both points stay fixed. Supplying corrected `points`
requires the actual correction `source_text`; supplied points are used exactly
and are not additionally shifted. No point is rounded or clipped.

New geometry binds the selected calibration and centre revisions. Withdrawn
scale keeps pixel exploration and saved point history but supplies no physical
frequency/d-spacing. A recorded DC endpoint keeps its index role while scale
is withdrawn, so another centre correction can still update that endpoint
before a later scale restoration. Native/user provenance and unknown uncertainties remain
explicit. Saved complex FFT bytes are read, never recomputed or rewritten.
Recover a completed operation through `image_result` with its original ID;
changed arguments conflict and incomplete records are never automatically
replayed. Revision depth and input size are bounded.

## Previously unknown scalar input

For a genuinely unknown scalar image, `image_calibrate` may explicitly use
`declare_reciprocal:true`, `coordinate_domain:"reciprocal_space"`, `scope:"image"`,
inverse-length `xy_scale` and the actual user statement. The declaration is
separate sourced evidence; source pixels and file metadata are unchanged.
It is not automatic inference from a filename, contrast or intensity value.

No flag overrides known real-space/native units or Fourier lineage, an existing
calibration domain, or an existing reconstruction/data-meaning statement. The
declaration applies to one exact frame and cannot implicitly expand to its
sequence or another capture. Without this explicit declaration, unknown input
continues in pixel mode; descriptive context alone never enables physical
reciprocal measurements.

Offline fixtures, actual stdio MCP, live DM capture and researcher edits have
separate acceptance scopes. None of these geometry tools establishes a phase,
changes diffraction intensities or qualifies concurrent DM editing.
