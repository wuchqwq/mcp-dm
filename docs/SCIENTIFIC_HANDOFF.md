# Native scientific metadata handoff

## Scope

This change preserves the scientific interpretation of a retained native Fourier
result through scalar READ, ROI cropping and explicit NPY encoding. It adds no
vendor entrypoint, changes no scientific pixels and keeps the exact GMS build
and default v0.6 backend gates. The native backend remains experimental.

The existing real-host records in `d59c0ce` qualify their original operators and
lifecycle. They do **not** constitute real-host acceptance of this additive
metadata path. Its new tests use synthetic callbacks and hand-built receipts;
a focused actual-DM continuation is still required before claiming that scope.

## Why native calibration alone is insufficient

The qualified Fourier v2 path preserves DM's native half-bin frequency-axis
calibration. Its mathematical bins instead use `f(i)=(i-dc_index)*step`. For an
8-point axis with 0.25 nm source spacing, the frequency step is 0.5 1/nm and DC
is at index 4. Native calibration labels that location -0.25 1/nm; the
mathematical frequency is zero. Both descriptions must survive export without
rewriting the original DM calibration.

READ now optionally carries `scientific_context` schema 1: the immutable v2
Fourier producer result, its original operation/request/arguments, cumulative
source-index crop offset and bounded postprocessing list. These are bridge-owned
metadata, not vendor object layouts or extra native image references. A tracked
result's changed descriptor/calibration is rejected rather than attached to
stale coordinates. This is not atomic pixel capture or edit detection.

The external encoder saves the context and a validated `scientific_semantics`
object in `input.json`. `source_calibration_dm` and `working_calibration_xy`
remain untouched. Quantitative frequency consumers must use
`scientific_semantics.coordinate_axes`, not substitute the raw DM axis. The NPY
pixel bytes, dtype and schema-1 capture layout do not change.

## Interpretation and limitations

- Direct real/imaginary, radians-phase and squared-magnitude results retain their
  exact representation, transform signs, normalization and intensity policy.
- IFFT components are spatial-domain outputs; they do not claim restoration of
  the source origin or intensity calibration.
- Cropping and then READ translates the mathematical axes by both offsets. DC
  may lie outside the saved ROI; its local index must not be clamped to zero.
- Unary/filter descendants retain coordinates but become `processed_scalar`;
  squaring phase is not mislabeled radians, nor is filtering power called an
  unmodified Fourier component. The original representation and operations remain.
- Binary mixtures of tracked science are marked `unresolved_lineage`; raw or
  legacy untracked sources are `unknown`. Inverse-looking units are not evidence
  of a Fourier origin. No synthetic mathematical grid is invented.
- A legacy direct Fourier READ lacking context is rejected by the scientific
  encoder before any output files are created (`SCIENTIFIC_CONTEXT_REQUIRED`).
  Legacy raw snapshots can still be encoded with explicit `not_recorded` science.
- Recorded context describes creation lineage. A numeric ID does not freeze
  subsequent source pixels. Use the existing idle/no-edit contract.
- Direct complex export, chunked export, result-reference release, native
  SaveAs/Open and new dimensions/types are not added by this fix.

The optional external mean example carries the context into its saved parameters;
it remains an explicit user-launched example, never a native fallback.

## Verification

`tests/native-scientific-handoff.test.mjs` covers signed scales, native/math DC,
phase versus power, cropped/out-of-ROI DC, IFFT spatial semantics, postprocessing,
legacy rejection, malformed contexts, exact NPY bytes and an independent NumPy
reopen. Existing snapshot and protocol regression remain applicable.

`scientific_handoff_tests.cpp` exercises the **actual version adapter** using
only fake vendor callbacks: producer metadata retention, crop inheritance,
READ before changed-descriptor rejection, mixed-lineage refusal and cleanup.
It can write one synthetic READ packet; set `DM_NATIVE_SCIENTIFIC_FIXTURE` to
that file when running Node tests for cross-language validation. No real DM or
physical FFT is performed by either test.

Before claiming new actual-host qualification, use a fresh authorized idle
synthetic session and explicit IDs: FFT -> phase/real -> offset crop -> READ ->
NPY; independently verify zero-frequency bins, radians/power labels, native
calibration unchanged, exact bytes, source invariance and normal cleanup.
Retain an honest NOT_TESTED boundary until those observations exist.
