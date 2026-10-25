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

The count image is calibrated in the source's **intensity** units when the source
has a complete, finite intensity calibration with a non-empty unit. Otherwise the
axis stays an uncalibrated bin index and `axis_mode` is `"bin_index"`.

The write follows DM's own scripting example for histograms: the left edge of
bin 0 is the origin and the bin width is the scale, written with `format = 0`
("calibrated value at pixel index 0").

What the pinned build actually does (static + live evidence):

- `Image::SetDimensionCalibration(uint32 dimension, float a, float b,
  char_range_t<wchar_t> const& unit, int32 format)` receives `a` in XMM2 as the
  origin **in the requested format** and `b` in XMM3 as the scale.
- For `format = 0` the implementation divides: it stores the negated index origin
  `-(origin / scale)`; `format = 1` stores the index origin directly. A later
  format-0 read multiplies the stored index origin by the scale again.
- Therefore the read-back can never be bit-exact for most inputs. A DM-Python
  oracle that performs the same write reports `origin = -15.499999046325684` for a
  requested `-15.5` with scale `2.796875`; the native read-back returns exactly
  the same value.

The guard is consequently a **binary32 round-trip bound**, not a data tolerance:
the observed physical zero must be within `8 ulp` of `max(|origin|, |scale|, 1)`,
the scale must match exactly (it is stored without arithmetic), and the unit must
match exactly. Any of those failing rejects the operation and releases the created
image (`native_histogram_axis_origin_mismatch`, `..._scale_mismatch`,
`..._unit_mismatch`). The receipt publishes `axis_zero_requested`,
`axis_zero_observed`, `axis_scale_observed`, `axis_roundtrip_error` and
`axis_tolerance`, so a caller can see the exact arithmetic instead of trusting a
label.

`intensity_calibration_applied` stays `false`: counts are raw pixel counts, not
electrons or calibrated intensities. Only the *axis* is expressed in intensity
units.

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

### Bar style

A count image reads better as bars than as a connected line, so delivery also
switches the host's own line plot to its bar style (`native_line_plot_style`).
That flag is a single byte inside the display object, with a two-instruction
getter and a setter that compares, stores and repaints. Because a raster display
also has a byte at that offset, the bridge refuses to touch anything it has not
proven: it reads the object's own RTTI type name through its complete object
locator and requires `.?AVLinePlotImageDisplay@@`, calls the setter only then,
and reads the byte back through the host getter.

The receipt reports `display_style` (`"histogram"` or `"default"`), a scope note
and, when it stayed `"default"`, the reason. This is presentation only: it makes
no scientific claim, it never fails the delivery, and the researcher can switch
the style back in the DM UI at any time.

## Recorded evidence

- Offline: `histogram_adapter_tests.cpp` (169 assertions) covers the admitted
  path, budget/dtype/range rejection, source-range coverage, missing output,
  descriptor mismatch, incomplete/fractional/negative/non-finite/oversized
  counts, the level-1 SHOW descriptor, and refused Fourier lineage.
- Actual host (synthetic 24x32 float32 image, raw intensity unit `arb`, 8 bins
  over a covering range): the counts matched an independent NumPy binning of the
  same pixels exactly (`[15,64,133,167,179,139,60,11]`, total 768 = pixel count);
  the result axis read back as unit `arb`, scale `2.796875` (the bin width) and
  physical zero `-15.499999046325684` for a requested `-15.5` (round-trip error
  `9.5e-07`, bounded); the source pixels and intensity calibration were unchanged;
  the result document was rank 1 with display type 3 (line plot) while the source
  raster stayed type 1, and the delivered document reported
  `display_style:"histogram"` (type name accepted, setter applied, flag read back).
- Not covered: uint32 or complex sources, ranges that do not cover the source,
  concurrent host edits, other builds, file saving and model-side visual review.
