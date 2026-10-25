# Explicit native sequence-frame working copies

Qualification: **LIMITED_SYNTHETIC_REAL_HOST_PASS** for the separately
accepted final artifact. The selected profile admits `native_frame` within
that bounded scope. Offline callbacks, an available symbol or another
operator's PASS do not qualify a changed artifact or another host build. Only the exact supported Windows x64 GMS profile
may admit it; the existing module fingerprints and default v0.6 backend remain
unchanged.

## Input, coordinates and native computation

`dm_native_frame(image_id, frame_index, request_id)` accepts an explicitly
identified ordinary-packed **rank-three uint16** sequence, native type code 10.
All three parameters are required. The index is zero-based on **DM dimension 2 /
NumPy axis 0**: `shape:[sequence,Y,X]`, `dm_dimensions:[X,Y,sequence]`.
The source axis role is `unspecified_sequence`; neither its name nor a TIFF
stack proves time, spatial Z, displacement, phase or another experimental axis.

The operation takes the complete XY plane at that index, using DM's native
slice-copy function, then calls DM's native image conversion to create a new
ordinary **2D float32** working image. All uint16 values from 0 through 65535 are
exactly representable in float32. The receipt separately identifies source
storage, output storage and this lossless value conversion. No bridge pixel
kernel, summation, projection, normalization, arithmetic identity operation or
Python fallback performs it. The original sequence and source file are not
written.

The bridge does not inspect or claim the GUI current frame, latest window,
workspace or automatically generated summed image. A caller must choose the
explicit source ID and frame index. Existing 2D operations still reject the
whole uint16 sequence; they use the returned float32 result ID where eligible.

Bounds are checked before either image allocation:

- Source storage: at most `UINT32_MAX` bytes; nonzero dimensions and a valid
  frame index are required.
- Complete XY plane: at most 1,048,576 pixels; there is no implicit crop, padding
  or downsampling.
- Temporary peak: two new native objects and 6 bytes per selected pixel, covering
  the uint16 plane plus float32 working copy, within the existing 16 MiB/32-object
  shared retained-result pool. The final retained output uses 4 bytes per pixel.

## Calibration and source identity

The receipt retains the full three-axis source metadata and selected frame-axis
index, count, raw calibration and unit. The XY result copies native origins,
calibrated values at pixel zero, signed scales and units. Recognized missing or
invalid spatial calibration remains explicit through `calibration_complete`,
per-axis `usable` and `issue`; it does not prevent this data copy. Unknown units
do not become nm or phase units. The frame-axis calibrated value is reported
only when its native numeric calibration is usable numerically, and never
substitutes for a known physical interpretation.

Source and output raw intensity calibration are copied and reported separately.
`intensity_calibration_applied:false` and
`intensity_semantics:"raw pixel intensity"` remain mandatory. The bridge does
not multiply pixels by an intensity scale or attach an inferred physical unit.
Native object/ABI/read failures remain errors rather than missing-calibration
diagnostics.

Identity, dimensions and calibration are checked around the operation. These
checks do not make a live image atomic: use serialized requests on an idle host
and do not edit the source or working image concurrently. Independent acceptance
must compare full synthetic source pixels and calibration before/after, rather
than treating `source_write_requested:false` as unchanged-source proof.

## Requests, ownership and follow-on operations

Save the session, source ID, frame index and caller-generated `request_id`
**before** submitting FRAME. NB2 records original operation `FRAME`, normalized
arguments `[image_id,frame_index]`, result type `native_frame_copy`, version 1.
Same ID/same parameters returns the original record; changing a parameter under
that ID is a conflict. Timeout, cancellation or disconnect may leave the
operation running: query that original ID with `dm_native_result`, without
resubmitting. Recovery is limited to the same still-queryable native session;
STOP, host exit and a new session do not promise old-record recovery.

The result has an independent image ID and retention token. The temporary
uint16 reference is released before final output retention commits. SHOW hands
the exact final result to a document under its own capability and saved-ID
contract. RELEASE drops only the plugin reference; normal STOP also releases
plugin-owned results. A shown document can continue holding the same result
until it is normally closed. SHOW is not file persistence or proof that a model
has seen the image. Do not close unrelated documents or replace a loaded DLL.

The returned float32 ID can enter supported raw mean, SUMMARY, preview or READ
operations. Crop, arithmetic, filter, FFT/components and GUI measurements retain
their own calibration, shape, dtype, lineage and memory gates. FRAME does not
qualify whole-frame arbitrary-size FFT, larger filters or physical measurements
without reliable calibration. Never silently crop or pad to satisfy another
operator.

## Numerical handoff

Use existing bounded `dm_native_read` plus the explicit saved-response or
complete-region NPY encoder. READ remains a 2D interface with at most 16,384
samples/65,536 raw bytes per block; larger eligible planes use the existing
explicit tiled handoff. NPY contains the **actual float32** output bytes,
not mislabeled uint16 storage or a display PNG. Encoding is data handoff, not a
claim that DM native SaveAs was called. New output paths refuse overwrite.

READ from a known frame-derived result includes frozen `frame_ancestry`:
the original FRAME request, source/selected-frame identity, conversion and
calibration. Its embedded FRAME payload precedes retention/native-receipt
decoration. Single-parent crop, unary, filter and Fourier/component operations
can retain that original identity when their own source metadata matches.
Mixed or changed lineage is explicitly unresolved and scientific export refuses
to interpret it as a tracked frame. The current READ still has its own source,
ROI, dtype and scientific semantics; original frame ancestry does not claim the
current pixels are an immutable source copy or replace subsequent coordinates.

See [data handoff](NATIVE_WORKFLOW.md) and
[reference lifecycle and complete-region export](../../../docs/NATIVE_LIFECYCLE_HANDOFF.md).
The final artifact independently passed bounded synthetic native/MCP frame
copying, exact values and copied calibration, original-ID recovery, unchanged
sources, NPY reopening, temporary-registry cleanup, document delivery and
RELEASE/STOP with independent idle-reference checks, followed by normal exit
and manifest-owned cleanup. An earlier exception during cleanup remains a
failed/incomplete attempt; the clean passing session does not rewrite it.
Known invalid numeric-calibration controls retain their offline scope unless
separately qualified. Ordinary model-client acceptance remains **NOT_TESTED**;
showing a document or generating PNG/NPY is not model visual acceptance.
