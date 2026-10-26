# Continue a diffraction analysis after a correction

These tools connect saved image measurements, a reference structure/orientation
and unrastered simulated reflections. They do not prescribe an analysis order
or identify a unique phase. Enable the optional image and structure routes as
described in [the Agent guide](../README.agent.md).

## Select what “current” means

Keep the returned image wrapper ID as the input for the next operation.
`current_image_object_id` means **that explicitly selected immutable wrapper**,
not the front DM window or a globally latest calibration. A caller can still
select an old wrapper; the tools cannot discover an unreported correction.

| Intention | Tool arguments / result |
|---|---|
| Continue the selected analysis | `structure_compare` with `analysis_mode:"continue_current"` and `current_image_object_id`; every measurement must match its exact scientific grid, centre and active calibration revision. |
| Propose an alignment for that revision | `structure_register` with `current_image_object_id`; no separate `analysis_mode` argument. |
| Recompute a comparison of saved historical evidence | `structure_compare` with `analysis_mode:"historical_review"`, explicit `registration`, and no `current_image_object_id`; this does not check a current image. |
| Inspect an already saved comparison/proposal | `structure_result` with its original request ID; it does not re-read DM or compute a new comparison. |

For compatibility, comparison without a current wrapper or explicit mode keeps
standalone-snapshot semantics, not a current-state guarantee. Supplying the
current wrapper defaults comparison to `continue_current`; prefer spelling the
mode out. A saved `registration_object_id` is accepted only for continuing its
exact current measurement geometry, not for a new historical-review call.

## Correct the centre, scale or a point

For an established reciprocal **scalar** image, `image_center` creates a
new sourced centre revision in original `source_array_indices`. It preserves
signed XY scale, array bytes and earlier records. Then `image_remeasure` reuses
the saved peak positions with that wrapper. Only an originally explicit DC
endpoint follows a centre correction. Explicit replacement `points` require
their correction `source_text` and are used exactly as supplied.

An external complex FFT and a tracked native Fourier scalar have fixed
mathematical DC. Do not recenter them to fit a candidate. A scale correction
uses `image_calibrate`, followed by a new preview and `image_remeasure`; the
saved complex FFT is read without recomputing it. Frequency anchors remain in
original cycles/pixel, while physical frequencies follow the new signed scale.
With withdrawn/unknown scale, pixel-domain observation can continue; physical
reflection comparison cannot. See [centre and point revisions](CENTRE_REVISIONS.md)
and [native calibration admission](NATIVE_CALIBRATION_HANDOFF.md).

The following is tool-call notation: `call` stands for the client's normal MCP
`tools/call`, returning the decoded successful text object. The variables are
previously returned objects or actual user corrections; no user needs to type
internal IDs or manifest paths. Save each request ID before dispatch.

```javascript
const corrected = await call("image_center", {
  object_id: current.object_id,
  center_xy: correctedCenterXY,
  coordinate_space: "source_array_indices",
  source_text: userCentreStatement,
  request_id: "centre-revision-2"
});
const updated = await call("image_remeasure", {
  object_id: corrected.object_id,
  measurement_object_id: previousMeasurement.object_id,
  request_id: "peak-1-remeasured-2"
});
```

Remeasure each affected saved observation in the same way. For a later scale
correction use its new calibration wrapper instead of `corrected.object_id`.
Unchanged peak anchors stay fixed; original measurements and exports stay
historical. Old centre/scale measurements or an old registration proposal
cannot pass as current evidence merely by linking their IDs.

## Fit only the permitted alignment

`structure_register` estimates one proper in-plane rotation. Independent
experimental scale stays 1, translation stays zero, and the declared screen
mapping `flip_y` stays fixed. Correct the image centre first. Do not use a
translation, guessed mirror, stretch or changed calibration to hide a mismatch.
The fit needs at least two non-collinear confirmed experimental/theoretical
reflection pairs. Specify the fixed residual tolerance in cycles/angstrom.

Keep held-out observations separate: no shared measurement, peak, HKL,
coincident projection or Friedel/conjugate equivalent may count as independent
validation. With no held-out observations it reports
`validation_status:"not_tested_no_held_out"` and a null validation outcome;
a small fit residual is not independent validation. Review
both fit and validation evidence, unmatched reflections and alternative matches.
See [constrained registration](CONSTRAINED_REGISTRATION.md) for conventions and
the numerical-independence limits.

For a **synthetic primitive-cubic fixture** whose saved [001] simulation contains
these reflections, assume `m0`, `m1`, `m2` are distinct DC-to-peak measurements
on the selected wrapper. This example does not assign these HKLs to real data:

```javascript
const measurements = [m0, m1, m2].map(m => m.manifest_path);
const proposal = await call("structure_register", {
  object_id: simulation.object_id,
  current_image_object_id: corrected.object_id,
  measurement_paths: measurements,
  fit_correspondences: [
    {measurement_index: 0, hkl: [1, 0, 0]},
    {measurement_index: 1, hkl: [0, 1, 0]}
  ],
  validation_correspondences: [
    {measurement_index: 2, hkl: [1, 1, 0]}
  ],
  screen_axes: {flip_y: false, basis: "Synthetic fixture already uses the simulation XY axes"},
  confirmation: {source: "synthetic_fixture", source_text: "Independent synthetic reference correspondences"},
  experimental_kind: "other_diffraction",
  max_residual_inv_angstrom: 1e-6,
  request_id: "synthetic-registration-2"
});
const comparison = await call("structure_compare", {
  object_id: simulation.object_id,
  current_image_object_id: corrected.object_id,
  analysis_mode: "continue_current",
  measurement_paths: measurements,
  registration_object_id: proposal.object_id,
  experimental_kind: "other_diffraction",
  max_residual_inv_angstrom: 1e-6,
  previous_comparison_id: previousComparison.object_id,
  request_id: "synthetic-comparison-2"
});
```

Omit `previous_comparison_id` for the first comparison. For real evidence,
`confirmation.source:"user_confirmed"` reports an actual researcher statement;
it is a caller assertion, not authentication or a tool-established scientific
fact. An Agent hypothesis must not be marked user-confirmed. The
`synthetic_fixture` option is reserved for synthetic evidence. Use the actual
known screen convention, experimental kind and predeclared tolerance; the
example values are not experimental parameters. A reused proposal's held-out
result is retained evidence, not a second new independent validation.

## New DM state, source changes and history

“I edited it in DM; read it again” requires a **new native READ/capture request**,
even when the DM image ID is unchanged. Querying the old request only recovers
its old snapshot. Do not mix a capture with concurrent edits; use the existing
bounded capture/source-stability contract. The external image tools neither
poll DM nor make historical captures live.

A fresh capture/frame/ROI/FFT producer is a different scientific grid, even
when its bytes match an older input. `image_remeasure` deliberately refuses
automatic point transfer across that boundary. Establish matching coordinates
and new measurements on the new capture explicitly. To link its comparison to
the prior one, pass `previous_comparison_id` and an actual `source_change_basis`
describing why the new input is the intended continuation. This records the
decision; it does not prove image registration or transfer old peak identity.
Source-change text without a previous comparison is refused.

Each linked result keeps the prior comparison ID, analysis revision, source,
calibration/centre, point and reference-simulation changes. Same-grid scale or
centre revisions can reuse the unchanged scientific array; comparison never
computes an FFT. Historical review uses saved measurements plus explicit
registration arguments, not a current wrapper. Supply only the five original
registration request fields: `rotation_deg`, `scale`,
`translation_inv_angstrom`, `flip_y` and `basis`; do not copy extra result-only
metadata into that strict argument object. Review an original saved
registration/comparison via `structure_result` rather than presenting it as a
fresh observation.

After cancellation/timeout, query `image_result` or `structure_result` with the
saved original request ID. Changed parameters need a new ID; do not resubmit an
unknown operation. Export the newly previewed wrapper and its revised metadata,
keeping old exported evidence intact. See [reflection comparison](REFLECTION_COMPARISON.md)
and [bounded numerical relay](DM_NUMERIC_RELAY.md) for the distinct geometric,
kinematic-intensity and DM import limits. None of these tools proves unique
phase identity or validates general concurrent DM editing, model-client vision
or arbitrary native write-back.
