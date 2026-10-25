# Native intensity histogram

`dm_native_histogram` calls DM's exported `Image::CreateImage` and
`GMSImageProcessing::CalcHistogram`. DM creates a true rank-one uint32 count
image. The bridge validates and transfers counts; it does not bin pixels itself
or substitute a Python calculation.

This capability is limited to the pinned Windows x64 GMS adapter. Original ABI
trials and the current integration artifact have separate evidence; see
[RESULTS](../experiments/native-bridge/RESULTS.md). A symbol, offline surrogate or
successful receipt alone does not qualify a new artifact or its lifecycle.

## Request and counts

`dm_native_histogram(image_id, bins, min, max, request_id)` requires:

- An explicit ordinary float32 2D source, at most 4,194,304 pixels. uint32,
  complex and unresolved/Fourier lineage are refused.
- 2..4096 bins. More bins than source pixels is valid.
- A finite caller range with `min < max`, transferred as binary32 bit patterns.
  It must cover the complete native source minimum/maximum. No widening,
  clipping or undocumented underflow/overflow handling is assumed.
- A caller-saved request ID before submission. Preserve session and arguments.
  After cancellation or timeout, QUERY that ID; never replay unknown work.

The result must have a new identity, ordinary packing, rank one and exactly
`bins` uint32 elements. Every count must be finite, non-negative, integral and
at most the source pixel count; the sum must equal that pixel count exactly.
Descriptor and source metadata checks surround the native call. They do not
provide an atomic pixel lock or make concurrent editing safe. Failure releases
the newly created reference.

The range is always in **raw pixel intensity**. Source intensity calibration is
retained as context and is not applied to pixels or counts. An unapplied unit
label does not turn those raw positions into calibrated physical intensities.

## Axis and display

The result retains `requested_range`, `bin_left_edge`, `bin_width` and original
binary32 arguments. These define raw bin edges independently of display
calibration. The boundary fixture covers internal edges and the upper endpoint;
it does not establish every floating rounding case.

The default `axis_mode:"bin_index"` has zero origin/physical zero, unit scale and
unknown units. Missing or non-identity source intensity calibration keeps this
mode. A source origin/scale other than zero/one cannot justify putting raw bin
positions in its physical units.

The intensity-axis path is restricted to identity intensity calibration and a
non-empty source unit. It uses the traced typed `SetDimensionCalibration` with
format zero, checks actual stored origin/physical zero, exact scale and unit,
and reports requested/observed zero and the predefined binary32 round-trip
bound. Unrepresentable or insufficiently resolved geometry is refused. See
[the axis audit](HISTOGRAM_AXIS_AUDIT.md); the historical exact-equality failure
remains separate from fresh qualification.

`dm_native_show` delivers the exact retained image through the separate
`native_histogram_display` group; PROFILE uses `native_profile_display`. Both
remain true one-dimensional results, never `[1,N]` rasters. SHOW preserves the
creation's axis context so an arbitrary complete axis cannot pass validation.

Histogram bars are optional presentation, requiring their own capability,
pinned entry contracts and safe exact display identity. The receipt reports
whether bars were applied or why the host default remains. Styling does not
qualify scientific data, activate a workspace or prove model visual review.

## Scientific handoff

Save the successful MCP text result, including its original `native_receipt`,
then explicitly run the existing encoder in an independent workspace:

```powershell
node tools/native_snapshot_handoff.mjs --workspace C:\analysis\trial --output histogram-01 --request-id export-histogram-01 --snapshot C:\analysis\trial\histogram-response.json
```

The workspace must exist and the output directory must be new. The existing
schema-1 package has `input.npy`, `input.json` and `capture.json`. This is explicit
saved-result encoding, not DM SaveAs, another histogram calculation or a fresh
source observation.

| Representation | Type and shape | Meaning |
| --- | --- | --- |
| DM image | uint32 `[bins]`, `output_bytes = bins*4` | Native counts |
| NB2 payload | little-endian binary64, `raw_bytes = bins*8` | Exact integer transport through `GetRealValue` |
| NPY | little-endian `<u4`, true rank one | Lossless original count values |

`pixel_sha256` binds uint32 bytes and `wire_values_sha256` separately binds the
binary64 transport. The sidecar preserves axis mode/native calibration, raw bin
geometry, source spatial/intensity calibration, native descriptors, source and
result identity, processing parameters, session and process/thread receipt.
The original native response stays intact. Historical receipts do not gain later
source guards: the encoder reports `source_descriptor_reobserved:false` and
`descriptor_unchanged:null`.

The encoder fsyncs its caller-ID journal before creating files. Same ID and
parameters return the existing receipt only after verifying all files. Existing
targets, conflicts, incomplete writes and changed files refuse automatic retry
or overwrite.

## Ownership and limits

HISTOGRAM creates a plugin-held temporary image; SHOW lets an exact DM document
hold the same image. RELEASE drops only the plugin reference. STOP does not
close documents. Last-reference destruction is checked after host return/idle,
separately from receipts, while source documents remain unchanged. QUERY is
immutable same-session history; STOP, host exit and restart do not promise
request recovery. An independently reopened NPY remains usable after host exit.

uint32/complex histogram sources, non-covering ranges, arbitrary physical
intensity conversion, general profiles, concurrent edits, native SaveAs, other
GMS builds and ordinary model-client acceptance remain outside qualification.
