# Native intensity histogram

The experimental native backend can compute a true intensity histogram with DM's
own operator: the destination is a native one-dimensional image created by the
exported `Image::CreateImage`, and the bin counts come from the exported
`GMSImageProcessing::CalcHistogram`. The bridge contributes no binning kernel, no
NumPy fallback and no intensity recalibration.

Qualification: **limited synthetic actual-host PASS** for the contract below, on
the pinned Windows x64 GMS 3.53.4137.0 profile only. The axis question is
explicitly open (see "Axis" below); a separate synthetic real-host trial is what
closes it, not the presence of the symbol.

## Input contract

`dm_native_histogram(image_id, bins, min, max, request_id)`

- Source: an ordinary 2D **float32** image, at most 4,194,304 pixels. uint32 and
  other dtypes are not admitted.
- `bins`: 2..4096. It is the destination dimension, so it is also the retained
  result budget (`bins * 4` bytes of native storage).
- `min`/`max`: raw intensity bin edges, transferred as binary32 bit patterns.
  They must be finite with `min < max`.
- The requested range **must cover the complete native source minimum and
  maximum**, which are read with DM's own `GetMinimum`/`GetMaximum`. This removes
  any dependence on an undocumented under/overflow rule: a value outside the
  requested interval can never be silently dropped or clamped.
- An image whose retained lineage is a Fourier or otherwise unresolved
  scientific result is refused (`native_histogram_scientific_source_context_unsupported`):
  a histogram of a complex/power image has no raw-intensity meaning here.

## Vendor calls

```text
GMSImage.dll             Image::CreateImage(DataSize const&, uint32 type, char_range_t<wchar_t> const&)
GMSImage.dll             Image::GetRealValue(DataIndex const&)
GMSImage.dll             Image::GetIntensityCalibration(...)
GMSImageProcessing.dll   GMSImageProcessing::CalcHistogram(ref_ptr<Image> const&, ref_ptr<Image> const&, double, double)
```

`DataSize` is the vendor's rank/extent POD: a `uint32` dimension count at offset
0 and `int64` extents at offset 8. `char_range_t<wchar_t>` is a begin/end pair,
not pointer+length. Both are checked at compile time in
`mvp/adapters/gms_3_53_4137/histogram_contract.hpp`; the call shapes and the
static evidence are in [ABI_NOTES.md](../ABI_NOTES.md).

## Invariants checked before publishing

1. The created image is a new identity: not the source, not already retained, and
   its live descriptor is rank 1 / uint32 / ordinary packing / exactly `bins`
   long.
2. Every bin is read as a native double. Each count must be finite, non-negative,
   integral, and not larger than the source pixel count.
3. The counts must sum to **exactly** the source pixel count. With the coverage
   requirement above this is a complete, independent consistency check: a vendor
   edge-rule surprise fails the operation instead of being reported as data.
4. Any failure releases the created image reference; no partial histogram is
   retained.

## Axis

The count image keeps an uncalibrated index axis. `axis_mode` is therefore always
`"bin_index"` and the reply carries `bin_left_edge`, `bin_width` and
`requested_range` so a caller can map bin `i` to
`[bin_left_edge + i*bin_width, bin_left_edge + (i+1)*bin_width)`.

Writing an intensity axis was attempted and **rejected by the bridge itself**: on
the pinned build `Image::SetDimensionCalibration(dimension, origin, scale, unit,
format=0)` does not read back the requested physical value at pixel zero, so the
read-back guard fails closed (`native_histogram_axis_origin_mismatch`). The setter
is therefore not bound at all in this version. DM's own scripting example
calibrates such an image with the left bin edge, which is what a future qualified
version must reproduce exactly before it may claim an intensity axis.

`intensity_calibration_applied` stays `false`: counts are raw pixel counts, not
electrons or calibrated intensities. The source intensity calibration is reported
for context only.

## Output

The reply contains the true `[bins]` uint32 shape, `counts_sum`,
`counts_complete:true`, an exact little-endian binary64 payload of the counts
(`raw_bytes = bins*8`), the native output size (`output_bytes = bins*4`) and the
usual retention receipt. `operator` is `GMSImageProcessing::CalcHistogram` and
`computation` is `DM native`.

`dm_native_show` accepts this retained rank-1 result through the separate
`native_histogram_display` group, exactly as it accepts a rank-1 PROFILE result
through `native_profile_display`. It never becomes a `[1,N]` raster, and it is
never admitted by the 2D display group.

## Recorded evidence

- Offline: `histogram_adapter_tests.cpp` (169 assertions) covers the admitted
  path, budget/dtype/range rejection, source-range coverage, missing output,
  descriptor mismatch, incomplete/fractional/negative/non-finite/oversized
  counts, the level-1 SHOW descriptor, and refused Fourier lineage.
- Actual host (synthetic 24x32 float32 image, raw intensity, 8 bins): the counts
  matched an independent NumPy binning of the same pixels exactly
  (`[15,64,133,167,179,139,60,11]`, total 768 = pixel count), the source pixels
  and intensity calibration were unchanged, and the result document was rank 1
  with display type 3 (line plot) while the source raster stayed type 1.
- Not covered: uint32 or complex sources, ranges that do not cover the source,
  concurrent host edits, other builds, file saving and model-side visual review.
