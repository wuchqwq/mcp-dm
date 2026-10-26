# GMS native ABI evidence inventory

<!-- GENERATED FILE. Edit tools/gms_compat/evidence/abi_evidence.json and run
     python tools/gms_compat/cli.py evidence render. Hand edits are rejected
     by the evidence validator. -->

This document is a machine-verified inventory of what is known about the
fixed-build native ABI, separated from what has actually been observed in a
real host. It is not an API reference for Gatan software and it grants no
capability.

## Build identity

| Field | Value |
| --- | --- |
| Adapter profile | `gms-3.53.4137.0-windows-x64` |
| Host | `DigitalMicrograph.exe` |
| Version | `3.53.4137.0` |
| Architecture | `x64` |
| Identity source | `experiments/native-bridge/mvp/adapters/gms_3_53_4137/profile.hpp` |
| Version policy | exact version plus per-module SHA-256; no approximate version range is admitted |

| Module | SHA-256 (pinned) | Version checked |
| --- | --- | --- |
| `DigitalMicrograph.exe` | `2f03ccd751b2abc7f55d3bda5b975895c3527660a03080618005a134d6fbfddb` | yes |
| `GMSImage.dll` | `0d8e22006a1023eb9f0de2b497ef1629c5a22c562741d3e4b0405d308590da3b` | yes |
| `GMSImageProcessing.dll` | `6be3044d049b6b2184404ea5adc2588d0677ae9b2f78ceb80169d315aef82042` | yes |
| `GMS.dll` | `9056884e38c090b7fff1cefe70150dc49d10dbc1f823fed6c7a661d255c01f93` | yes |
| `mfc140.dll` | `b784303d86232a1b316c79839aa78bf631b4fc182e55d9d947688adb066dff26` | no |

Pinned fingerprints are the ones the shipping adapter gate already uses. The
inventory restates them only to detect drift; the runtime gate remains the
source of truth and is cross-checked by `evidence validate`.

## Qualification summary

| State | Count | Meaning |
| --- | --- | --- |
| `QUALIFIED_LIMITED` | 27 | bounded synthetic real-host acceptance recorded for this exact build |
| `STATIC_CANDIDATE` | 2 | static or offline evidence only; never executed in a host |
| `UNRESOLVED` | 1 | evidence insufficient or contradictory; must not be bound |
| `BLOCKED` | 4 | deliberately refused (signature, policy or superseded) |

Counts are not capability claims: a qualified ABI entry only means its call
shape and ownership were exercised for the recorded scope, not that any
operation built on it is admitted for another build or dtype.

## Entry index

| ID | Area | Bindings | Qualification | Operations |
| --- | --- | --- | --- | --- |
| `image.lookup` | image-identity | `?FindByID@Image@GMS@@SA?AV?$ref_ptr@VImage@GMS@@@Gatan@@K@Z`, `?FindByIndex@Image@GMS@@SA?AV?$ref_ptr@VImage@GMS@@@Gatan@@K@Z` | `QUALIFIED_LIMITED` | native_datasets, native_mean, native_statistics, native_crop, native_display, native_read, native_preview, native_fft, native_filters, native_image_arithmetic, native_frame, native_histogram, native_line_profile, native_gui_rois, native_numeric_import |
| `image.enumerate` | image-identity | `?CountAllImages@Image@GMS@@SAKXZ` | `QUALIFIED_LIMITED` | native_datasets |
| `image.id` | image-identity | `?GetID@Image@GMS@@QEBAKXZ` | `QUALIFIED_LIMITED` | native_datasets, native_read, native_crop, native_result_release |
| `image.dimensions` | image-descriptor | `?GetDimensions@Image@GMS@@QEBAKXZ`, `?GetNthDimension@Image@GMS@@QEBAKJ@Z` | `QUALIFIED_LIMITED` | native_datasets, native_read, native_crop, native_fft, native_filters, native_frame, native_histogram, native_line_profile |
| `image.data_type` | image-descriptor | `?GetDataType@Image@GMS@@QEBAKXZ` | `QUALIFIED_LIMITED` | native_read, native_crop, native_mean, native_statistics, native_uint32_mean, native_uint32_read, native_uint32_crop, native_line_profile, native_display |
| `image.packing` | image-descriptor | `?GetPackingStyle@Image@GMS@@QEBA?AUDataPackingStyle@Imaging@Gatan@@XZ` | `QUALIFIED_LIMITED` | native_read, native_crop, native_fft, native_filters, native_image_arithmetic, native_frame, native_uint32_read, native_uint32_crop, native_line_profile |
| `image.spatial_calibration` | calibration | `?GetDimensionCalibration@Image@GMS@@QEAAXKPEAM0PEAV?$basic_string@_WU?$char_traits@_W@std@@V?$allocator@_W@2@@std@@J@Z` | `QUALIFIED_LIMITED` | native_datasets, native_read, native_crop, native_line_profile, native_histogram_axis |
| `image.intensity_calibration` | calibration | `?GetIntensityCalibration@Image@GMS@@QEAAXAEAM0AEAV?$basic_string@_WU?$char_traits@_W@std@@V?$allocator@_W@2@@std@@@Z` | `QUALIFIED_LIMITED` | native_frame, native_line_profile, native_histogram_axis |
| `image.unicode_name` | image-identity | `?GetUnicodeName@Image@GMS@@QEBA?AV?$basic_string@_WU?$char_traits@_W@std@@V?$allocator@_W@2@@std@@XZ` | `QUALIFIED_LIMITED` | native_datasets |
| `abi.msvc_string_release` | image-memory | `#1487` | `QUALIFIED_LIMITED` | native_datasets, native_read, native_line_profile |
| `image.reference_release` | image-memory | `?ref_ptr_delete@Gatan@@YAXPEAVImage@GMS@@@Z` | `QUALIFIED_LIMITED` | native_result_release, native_crop, native_read, native_display, native_histogram, native_line_profile |
| `image.sub_slice` | image-creation | `?GetSubSliceAsImage@Image@GMS@@QEBA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBVDataSlice@Imaging@4@@Z` | `QUALIFIED_LIMITED` | native_crop, native_pixel_crop, native_uint32_crop, native_frame |
| `image.create` | image-creation | `?CreateImage@Image@GMS@@SA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBVDataSize@Imaging@4@KAEBV?$char_range_t@_WU?$char_traits@_W@std@@@4@@Z` | `QUALIFIED_LIMITED` | native_histogram, native_numeric_import |
| `image.real_value` | image-pixels | `?GetRealValue@Image@GMS@@QEBANAEBVDataIndex@Imaging@Gatan@@@Z`, `?SetRealValue@Image@GMS@@QEAAXAEBVDataIndex@Imaging@Gatan@@N@Z` | `QUALIFIED_LIMITED` | native_read, native_uint32_read, native_preview, native_histogram, native_numeric_import, native_line_profile |
| `image.set_spatial_calibration` | calibration | `?SetDimensionCalibration@Image@GMS@@QEAAXKMMAEBV?$char_range_t@_WU?$char_traits@_W@std@@@Gatan@@J@Z` | `QUALIFIED_LIMITED` | native_numeric_import, native_histogram_axis |
| `processing.reductions` | processing | `?GetMean@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z`, `?GetMinimum@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z`, `?GetMaximum@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z`, `?GetSum@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z` | `QUALIFIED_LIMITED` | native_mean, native_statistics, native_uint32_mean, native_uint32_statistics |
| `processing.histogram` | processing | `?CalcHistogram@GMSImageProcessing@@YAXAEBV?$ref_ptr@VImage@GMS@@@Gatan@@0NN@Z` | `QUALIFIED_LIMITED` | native_histogram, native_histogram_display, native_histogram_axis |
| `processing.convert` | processing | `?ImageConvert@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@K@Z` | `QUALIFIED_LIMITED` | native_frame |
| `processing.filters` | processing | `?SmoothFilter@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z`, `?SobelFilter@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z`, `?LaplaceFilter@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z`, `?SharpenFilter@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z` | `QUALIFIED_LIMITED` | native_filters, native_pixel_filters, native_uint32_filters |
| `processing.unary` | processing | `?Negate@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z`, `?Abs@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z`, `?Square@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z` | `QUALIFIED_LIMITED` | native_image_arithmetic, native_uint32_image_arithmetic |
| `processing.binary` | processing | `??HGMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z`, `??GGMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z`, `??DGMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z` | `QUALIFIED_LIMITED` | native_image_arithmetic, native_uint32_image_arithmetic |
| `processing.fourier` | processing | `?Real_FFT@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z`, `?IFFT@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z`, `?Real@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z`, `?Imag@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z`, `?Arg@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z`, `?Norm@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z` | `QUALIFIED_LIMITED` | native_fft, native_pixel_fft, native_uint32_fft, native_fft_large, native_ifft_large, native_real_large, native_imag_large, native_phase_large, native_power_large, native_uint32_fft_large, native_uint32_real_large, native_uint32_imag_large, native_uint32_phase_large, native_uint32_power_large |
| `processing.fourier_packed_candidates` | processing | `FFT`, `Packed_FFT` | `STATIC_CANDIDATE` | - |
| `processing.other_signatures` | processing | `?GetPixelCount@GMSImageProcessing@@YA_KAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z`, `?GetMeanAndVariance@GMSImageProcessing@@YAXAEBV?$ref_ptr@VImage@GMS@@@Gatan@@AEAN1@Z`, `?GetMinimumMaximum@GMSImageProcessing@@YAXAEBV?$ref_ptr@VImage@GMS@@@Gatan@@AEAN1@Z` | `BLOCKED` | - |
| `document.factory_show` | document | `image_get_or_create_document`, `image_document_show` | `QUALIFIED_LIMITED` | native_display, native_uint32_display, native_profile_display, native_histogram_display, native_numeric_import_display |
| `document.holders` | document | `destroy_document_holder`, `destroy_window` | `QUALIFIED_LIMITED` | native_display, native_profile_display, native_histogram_display |
| `roi.display_resolution` | roi | `roi_image_display_count`, `roi_image_display_at`, `roi_resolve_display`, `roi_display_image`, `roi_destroy_display_holder`, `roi_destroy_roi` | `QUALIFIED_LIMITED` | native_gui_rois, native_line_profile |
| `roi.geometry` | roi | `roi_id`, `roi_is_selected`, `roi_is_rectangle`, `roi_rectangle`, `roi_raster_count`, `roi_raster_at`, `roi_raster_dimensions`, `roi_raster_mapping`, `roi_raster_slice_id`, `roi_simple_source_count`, `roi_simple_source_slice_id`, `roi_simple_source_extents` | `QUALIFIED_LIMITED` | native_gui_rois |
| `roi.line_profile` | roi | `roi_is_line`, `roi_line`, `line_profile_extract` | `QUALIFIED_LIMITED` | native_line_profile, native_profile_display |
| `presentation.plot_style` | presentation | `plot_style_get`, `plot_style_set` | `STATIC_CANDIDATE` | native_line_plot_style |
| `blocked.save` | blocked |  | `BLOCKED` | native_save |
| `blocked.whole_file_open` | blocked |  | `BLOCKED` | - |
| `unresolved.workspace_activation` | unresolved |  | `UNRESOLVED` | - |
| `superseded.probe_lookup` | superseded | `FindImageAsObject` | `BLOCKED` | - |

## Area: blocked

### `blocked.save` — SaveAs and document saving

- Qualification: `BLOCKED` (derivation: `documented`)
- Bindings:
  - none: deliberately unbound: only partial string-construction evidence exists, and format preservation, exclusive output, source-filename mutation and error/ownership contracts are unresolved
- Call shape: unknown — no call contract is established; nothing may be bound from a partial signature
- Layout / ownership: not recorded — no object layout was derived for a refused interface

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Version isolation and additional typed operations — SaveAs and Open remain blocked and partial string evidence is not enough to call either interface
- `experiments/native-bridge/mvp/ADAPTERS.md` ## Admission and diagnostics — native_save remains unqualified

Verification:
- offline: `experiments/native-bridge/mvp/adapter_profile_tests.cpp` (native_save is reported unavailable)

Uncertainties:
- Whether an exclusive-write contract can be established at all is unknown.

Scope: operations native_save; dtypes not applicable; versions 3.53.4137.0.
- limit: refused; the explicit saved-READ NPY encoder is a separate data handoff and is not DM SaveAs

On any build change re-derive: sha256, call_shape, layout, ownership, file_semantics.

### `blocked.whole_file_open` — Whole-file native OpenImage

- Qualification: `BLOCKED` (derivation: `documented`)
- Bindings:
  - none: unresolved: no closed reader/ownership contract for arbitrary files; the supported input route is the explicit numerical handoff instead
- Call shape: unknown — no call contract is established
- Layout / ownership: not recorded — no object layout was derived

Static evidence:
- `AGENTS.md` ## Validation and claims — whole-file native OpenImage remains unverified

Verification:
- none recorded

Uncertainties:
- File-format coverage, error semantics and ownership were never closed.

Scope: operations -; dtypes not applicable; versions 3.53.4137.0.
- limit: refused

On any build change re-derive: call_shape, layout, ownership, file_semantics.

## Area: calibration

### `image.spatial_calibration` — Spatial dimension calibration getter

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `?GetDimensionCalibration@Image@GMS@@QEAAXKPEAM0PEAV?$basic_string@_WU?$char_traits@_W@std@@V?$allocator@_W@2@@std@@J@Z` in `GMSImage.dll`
- Call shape: `win64_msvc_member`, returns `void`

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `this` | `void*` | borrowed image pointer |
  | 2 | `dimension` | `uint32_t` | validated against the dimension count |
  | 3 | `origin` | `float*` | binary32 output; may be null |
  | 4 | `scale` | `float*` | binary32 signed scale; may be null |
  | 5 | `unit` | `MsvcWideString*` | MSVC string object; may be null |
  | 6 | `format` | `int32_t` | 0 returns the physical coordinate at index zero, 1 returns the stored index origin |

  Both numeric outputs are binary32. physical(i) = origin + i * scale. Negative scales are preserved and non-finite values are rejected before publication.
- Layout source: `experiments/native-bridge/ABI_NOTES.md` ## MSVC string ABI shim
  - `MsvcWideString` size 32 alignment 8: union storage at 0, length at 16, capacity at 24
- Ownership: the callee constructs the string; the bridge copies bounded UTF-16 and releases it through the paired allocator path, never through a local C++ destructor

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Descriptors, calibration, and statistics — the calibration call shape, the two binary32 outputs and the format 0/1 distinction
- `experiments/native-bridge/ABI_NOTES.md` ## MSVC string ABI shim — the 32-byte MSVC wide-string representation and its matching deallocator

Verification:
- offline: `experiments/native-bridge/mvp/read_adapter_tests.cpp` (signed calibration translation)
- offline: `experiments/native-bridge/mvp/import_adapter_tests.cpp` (calibration round-trip guards)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Earlier accepted MVP baseline

Uncertainties:
- The unit string is a vendor-owned MSVC object; any change to its layout must fail closed.
- Format 1 semantics are documented but only format 0 is exercised by the qualified paths.

Scope: operations native_datasets, native_read, native_crop, native_line_profile, native_histogram_axis; dtypes float32, uint32; versions 3.53.4137.0.
- limit: non-finite calibration is reported, never replaced

On any build change re-derive: sha256, export_name, call_shape, layout, string_allocator.

### `image.intensity_calibration` — Intensity calibration getter

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `?GetIntensityCalibration@Image@GMS@@QEAAXAEAM0AEAV?$basic_string@_WU?$char_traits@_W@std@@V?$allocator@_W@2@@std@@@Z` in `GMSImage.dll`
- Call shape: `win64_msvc_member`, returns `void`

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `this` | `void*` | borrowed image pointer |
  | 2 | `origin` | `float&` | binary32 output |
  | 3 | `scale` | `float&` | binary32 output |
  | 4 | `unit` | `MsvcWideString&` | MSVC string output |
- Layout source: `experiments/native-bridge/ABI_NOTES.md` ## MSVC string ABI shim
  - `MsvcWideString` size 32 alignment 8: union storage at 0, length at 16, capacity at 24
- Ownership: same vendor string ownership contract as the spatial getter; the value is copied, never applied to pixels

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Native one-dimensional results, image creation and histogram — the typed intensity-calibration getter verifies the native copy while the result stays unapplied
- `experiments/native-bridge/mvp/adapters/gms_3_53_4137/profile.hpp` ?GetIntensityCalibration@Image@GMS@@QEAAXAEAM0AEAV?$basic_string@_WU?$char_traits@_W@std@@V?$allocator@_W@2@@std@@@Z — required by the frame and line-profile groups

Verification:
- offline: `experiments/native-bridge/mvp/frame_adapter_tests.cpp` (copied-but-unapplied calibration)
- offline: `experiments/native-bridge/mvp/line_profile_adapter_tests.cpp` (intensity calibration preservation)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Explicit uint16 sequence-frame working copies

Uncertainties:
- Whether the vendor applies intensity calibration inside any operator is not derived from this getter.

Scope: operations native_frame, native_line_profile, native_histogram_axis; dtypes uint16, float32, uint32; versions 3.53.4137.0.
- limit: intensity_calibration_applied is always false in receipts

On any build change re-derive: sha256, export_name, call_shape, layout.

### `image.set_spatial_calibration` — Spatial calibration setter and its binary32 rounding

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `?SetDimensionCalibration@Image@GMS@@QEAAXKMMAEBV?$char_range_t@_WU?$char_traits@_W@std@@@Gatan@@J@Z` in `GMSImage.dll`
- Call shape: `win64_msvc_member`, returns `void`

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `this` | `void*` | member call |
  | 2 | `dimension` | `uint32_t` | x or y |
  | 3 | `origin` | `float` | XMM2; origin expressed in the requested format |
  | 4 | `scale` | `float` | XMM3 |
  | 5 | `unit` | `const CharRange*` | 16-byte wide-character range |
  | 6 | `format` | `int32_t` | stack argument; 0 stores -(origin / scale), 1 stores the given index origin |

  A format-0 write followed by a format-0 read is not bit-exact: the stored index origin is multiplied by the scale again.
- Layout source: `experiments/native-bridge/ABI_NOTES.md` ## Native one-dimensional results, image creation and histogram
  - `CharRange353` size 16 alignment 8: begin and end wchar_t pointers
- Ownership: caller-owned range; the host copies what it needs

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Native one-dimensional results, image creation and histogram — XMM2 origin, XMM3 scale, trailing format int, and the format-0 divide branch
- `docs/HISTOGRAM_AXIS_AUDIT.md` # Histogram axis: native arithmetic and scientific limits — the quotient and product must be modelled in binary32, not compared with an epsilon floor

Verification:
- offline: `experiments/native-bridge/mvp/histogram_adapter_tests.cpp` (axis write/read guard modelling)
- offline: `experiments/native-bridge/mvp/import_adapter_tests.cpp` (signed raw-origin calibration readback)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Histogram intensity axis and presentation: reviewed continuation

Uncertainties:
- Whole-axis drift bounds are empirical for the recorded values; no general error theorem follows.

Scope: operations native_numeric_import, native_histogram_axis; dtypes float32, uint32; versions 3.53.4137.0.
- limit: identity intensity calibration plus a nonempty unit is required for a labelled axis

On any build change re-derive: sha256, export_name, call_shape, layout, rounding_model.

## Area: document

### `document.factory_show` — Document creation and display entrypoints

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - non-exported entry contract `image_get_or_create_document` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `image_document_show` in `GMS.dll` (RVA lives only in the version profile)
- Call shape: `win64_msvc`, returns `native document holder (16 bytes) or void`

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `image` | `Image*` | the factory receives only an image and selects the display itself |
  | 2 | `document` | `void*` | the display entrypoint receives the holder produced by the factory |

  These entrypoints have no applicable public DLL exports in the inspected build. Binding requires a complete host/module hash gate followed by an executable-section and committed-page check.
- Layout source: `experiments/native-bridge/ABI_NOTES.md` ## Visible-document SHOW candidate
  - `document holder` size 16 alignment 8: 64-bit reference count followed by a native document pointer
- Ownership: each return is one owned reference; release Window first and then the document holder, calling the matched vendor final destructor only at zero

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Visible-document SHOW candidate — typed entrypoints without public exports, the 16-byte holder and the entry-page gate
- `experiments/native-bridge/ABI_NOTES.md` ## Native one-dimensional results, image creation and histogram — the same factory delivers rank-one results because it takes only an Image*

Verification:
- offline: `experiments/native-bridge/mvp/result_release_tests.cpp` (holder release ordering)
- offline: `experiments/native-bridge/mvp/histogram_adapter_tests.cpp` (rank-one display admission split)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Current feature: native operations and scientific handoff

Uncertainties:
- A receipt is not proof of active-tab visibility or model viewing.
- Saving the document remains outside this entry.

Scope: operations native_display, native_uint32_display, native_profile_display, native_histogram_display, native_numeric_import_display; dtypes float32, uint32, float64 (rank-one), uint32 counts; versions 3.53.4137.0.
- limit: explicit retained ID only
- limit: no front-image or most-recent-window selection

On any build change re-derive: sha256, rva, call_shape, layout, ownership, entry_page_gate.

### `document.holders` — Document holder and window destruction

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - non-exported entry contract `destroy_document_holder` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `destroy_window` in `GMS.dll` (RVA lives only in the version profile)
- Call shape: `win64_msvc`, returns `void`

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `object` | `void*` | the holder or window whose count has just reached zero |
- Layout source: `experiments/native-bridge/ABI_NOTES.md` ## Visible-document SHOW candidate
  - `Window (opaque)` size unknown alignment 8: only a 64-bit reference counter is proven
- Ownership: matched final destructors only; malformed layout latches the adapter disabled instead of guessing a destruction path

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Visible-document SHOW candidate — release order Window then holder, and the fail-closed rule for malformed layout

Verification:
- offline: `experiments/native-bridge/mvp/result_release_tests.cpp` (double-release and ordering guards)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Current feature: native operations and scientific handoff

Uncertainties:
- Only the reference counter of the Window object is proven; the rest stays opaque.

Scope: operations native_display, native_profile_display, native_histogram_display; dtypes not applicable; versions 3.53.4137.0.
- limit: never close unrelated user documents

On any build change re-derive: sha256, rva, call_shape, layout, ownership.

## Area: image-creation

### `image.sub_slice` — Independent rectangular pixel copy

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `?GetSubSliceAsImage@Image@GMS@@QEBA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBVDataSlice@Imaging@4@@Z` in `GMSImage.dll`
- Call shape: `win64_msvc_member_sret`, returns `pointer to the caller-provided result slot`, hidden structure-return pointer first

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `this` | `const void*` | source image, borrowed |
  | 2 | `out` | `NativeImageRef*` | receives one owned reference to a new independent image |
  | 3 | `slice` | `const NativeDataSlice*` | 176-byte caller-built slice descriptor |

  The inspected path creates a new image and copies the selected data, unlike CreateSlicedImage which retains the original backing seed.
- Layout source: `experiments/native-bridge/ABI_NOTES.md` ## Independent crop contract
  - `SliceAxis` size 24 alignment 8: source_dimension at 0, padding, length at 8, step at 16
  - `NativeDataSlice` size 176 alignment 8: source_dimensions at 0, source_start[5] at 8, output_dimensions at 48, output_axes[5] at 56 with stride 24
- Ownership: returned reference follows the image reference ownership rule; the source stays untouched

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Independent crop contract — call shape, the 176-byte slice representation and the half-open rectangle mapping
- `experiments/native-bridge/mvp/adapters/gms_3_53_4137/crop_contract.hpp` NativeDataSlice — compile-time offsets and size assertions for the slice POD

Verification:
- offline: `experiments/native-bridge/mvp/pixel_adapter_tests.cpp` (rectangle validation and calibration translation)
- offline: `experiments/native-bridge/mvp/uint32_adapter_tests.cpp` (uint32 crop bounds)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Earlier accepted MVP baseline

Uncertainties:
- Only the 2D ordinary-packing rectangle mapping is closed; other slice shapes are unverified.

Scope: operations native_crop, native_pixel_crop, native_uint32_crop, native_frame; dtypes float32, uint32, uint16 (frame source); versions 3.53.4137.0.
- limit: half-open upper edges
- limit: bounds validated before allocation

On any build change re-derive: sha256, export_name, call_shape, layout, ownership.

### `image.create` — New native image creation

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `?CreateImage@Image@GMS@@SA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBVDataSize@Imaging@4@KAEBV?$char_range_t@_WU?$char_traits@_W@std@@@4@@Z` in `GMSImage.dll`
- Call shape: `win64_msvc_static_sret`, returns `pointer to the caller-provided result slot`, hidden structure-return pointer first

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `out` | `NativeImageRef*` | argument one; the result is read from this slot, not from the returned pointer |
  | 2 | `size` | `const DataSize*` | 48-byte rank plus int64 extents |
  | 3 | `type` | `uint32_t` | scalar type code; 11 is used for uint32 histogram destinations |
  | 4 | `name` | `const CharRange*` | 16-byte begin/end wide-character range |
- Layout source: `experiments/native-bridge/ABI_NOTES.md` ## Native one-dimensional results, image creation and histogram
  - `DataSize353` size 48 alignment 8: dimensions at 0, padding, size[5] int64 at 8
  - `CharRange353` size 16 alignment 8: begin and end wchar_t pointers
- Ownership: the created image owns one reference; the bridge retains or releases it through the standard reference contract

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Native one-dimensional results, image creation and histogram — argument order, the 48-byte DataSize and the 16-byte CharRange, fixed by Check_ImageDataSize and SetUnicodeName
- `experiments/native-bridge/mvp/adapters/gms_3_53_4137/histogram_contract.hpp` DataSize353 — compile-time layout assertions for the creation PODs

Verification:
- offline: `experiments/native-bridge/mvp/histogram_adapter_tests.cpp` (creation and count validation)
- offline: `experiments/native-bridge/mvp/import_adapter_tests.cpp` (imported image creation)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Rank-one delivery and native histogram (2026-10-25 audit round)

Uncertainties:
- Only the rank-one uint32 histogram destination and the bounded float32 import destination are exercised.

Scope: operations native_histogram, native_numeric_import; dtypes uint32, float32; versions 3.53.4137.0.
- limit: bounded extents validated before the call

On any build change re-derive: sha256, export_name, call_shape, layout, ownership.

## Area: image-descriptor

### `image.dimensions` — Dimension count and per-axis size

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `?GetDimensions@Image@GMS@@QEBAKXZ` in `GMSImage.dll`
  - export `?GetNthDimension@Image@GMS@@QEBAKJ@Z` in `GMSImage.dll`
- Call shape: `win64_msvc_member`, returns `uint32_t`

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `this` | `const void*` | member call; GetDimensions takes no further arguments |
  | 2 | `dimension` | `int32_t` | GetNthDimension only; validated against the previously read count |

  DM dimension 0 is x and dimension 1 is y, so the exported row-major shape is [size_y, size_x]. No GetDimensionSize export exists in the inspected module.
- Layout / ownership: not recorded — only scalar getters are called; the descriptor itself is not dereferenced by the bridge

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Descriptors, calibration, and statistics — GetNthDimension is the native size getter and each index must be validated against the count

Verification:
- offline: `experiments/native-bridge/mvp/pixel_adapter_tests.cpp` (axis size and bound rejection)
- offline: `experiments/native-bridge/mvp/uint32_adapter_tests.cpp` (uint32 shape gates)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Earlier accepted MVP baseline

Uncertainties:
- A third or higher dimension is only meaningful for the FRAME group; other operations reject it.

Scope: operations native_datasets, native_read, native_crop, native_fft, native_filters, native_frame, native_histogram, native_line_profile; dtypes any; versions 3.53.4137.0.
- limit: axis order is z,y,x for rank three; no axis permutation is inferred

On any build change re-derive: sha256, export_name, call_shape.

### `image.data_type` — Scalar type code

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `?GetDataType@Image@GMS@@QEBAKXZ` in `GMSImage.dll`
- Call shape: `win64_msvc_member`, returns `uint32_t type code`

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `this` | `const void*` | no pixel buffer is touched |

  Only code 2 (float32), code 11 (uint32) and code 12 (float64, rank-one profile output) are mapped. Other codes remain unsupported without conversion.
- Layout / ownership: not recorded — the type code is returned as a scalar; the descriptor layout is not read by the bridge

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Descriptors, calibration, and statistics — GetDataType reads the descriptor and needs no pixel access; other codes stay unsupported

Verification:
- offline: `experiments/native-bridge/mvp/pixel_adapter_tests.cpp` (type rejection paths)
- offline: `experiments/native-bridge/mvp/uint32_adapter_tests.cpp` (code 11 admission)
- real host: `PASS_LIMITED` — `experiments/native-bridge/mvp/UINT32_ACCEPTANCE.md` ## Independent synthetic trial

Uncertainties:
- The integer/unsigned flags describe the fixed-build mapping of code 11, not additional vendor flag getters.

Scope: operations native_read, native_crop, native_mean, native_statistics, native_uint32_mean, native_uint32_read, native_uint32_crop, native_line_profile, native_display; dtypes float32, uint32, float64 (rank-one output only); versions 3.53.4137.0.
- limit: unknown codes are refused, never coerced

On any build change re-derive: sha256, export_name, call_shape, type_code_mapping.

### `image.packing` — Data packing style

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `?GetPackingStyle@Image@GMS@@QEBA?AUDataPackingStyle@Imaging@Gatan@@XZ` in `GMSImage.dll`
- Call shape: `win64_msvc_member_sret`, returns `pointer to the caller-provided four-byte result buffer`, hidden structure-return pointer first

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `this` | `const void*` | member call |
  | 2 | `out` | `DataPackingStyle*` | four-byte structure written by the callee; it is not a scalar integer return |
- Layout source: `experiments/native-bridge/ABI_NOTES.md` ## Version isolation and additional typed operations
  - `DataPackingStyle` size 4 alignment 4: four-byte structure returned through the hidden destination pointer
- Ownership: caller-owned scalar structure; no reference is created or released

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Version isolation and additional typed operations — packing is a four-byte structure returned through a destination pointer, not a scalar getter
- `experiments/native-bridge/mvp/adapters/gms_3_53_4137/profile.hpp` ?GetPackingStyle@Image@GMS@@QEBA?AUDataPackingStyle@Imaging@Gatan@@XZ — every operation capability group requires this export

Verification:
- offline: `experiments/native-bridge/mvp/pixel_adapter_tests.cpp` (ordinary-packing gate)
- offline: `experiments/native-bridge/mvp/uint32_adapter_tests.cpp` (packing 1 requirement for uint32)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Earlier accepted MVP baseline

Uncertainties:
- Non-ordinary packing values are recognized and refused; their pixel semantics are not closed.

Scope: operations native_read, native_crop, native_fft, native_filters, native_image_arithmetic, native_frame, native_uint32_read, native_uint32_crop, native_line_profile; dtypes float32, uint32, uint16 (frame source); versions 3.53.4137.0.
- limit: only ordinary packing is admitted

On any build change re-derive: sha256, export_name, call_shape, layout.

## Area: image-identity

### `image.lookup` — Numeric image lookup by ID and by index

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `?FindByID@Image@GMS@@SA?AV?$ref_ptr@VImage@GMS@@@Gatan@@K@Z` in `GMSImage.dll`
  - export `?FindByIndex@Image@GMS@@SA?AV?$ref_ptr@VImage@GMS@@@Gatan@@K@Z` in `GMSImage.dll`
- Call shape: `win64_msvc_static_sret`, returns `pointer to the caller-supplied result slot`, hidden structure-return pointer first

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `out` | `NativeImageRef*` | 8-byte caller slot; receives one owned reference or an empty reference |
  | 2 | `id` | `uint32_t` | numeric ID returned by GetID; FindByIndex takes a zero-based registry index instead |

  A missing ID or out-of-range index yields an empty reference. The adapter checks the returned object's GetID before use.
- Layout source: `experiments/native-bridge/ABI_NOTES.md` ## Image identity and ownership
  - `NativeImageRef` size 8 alignment 8: single void* image
- Ownership: a non-null result owns exactly one strong reference and must be released through image.reference_release; a borrowed pointer must never be released

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Image identity and ownership — static methods returning ref_ptr<Image> receive the hidden result pointer first and write one pointer
- `experiments/native-bridge/mvp/adapters/gms_3_53_4137/profile.hpp` ?FindByID@Image@GMS@@SA?AV?$ref_ptr@VImage@GMS@@@Gatan@@K@Z — the shipping profile requires this exact decorated export

Verification:
- offline: `experiments/native-bridge/mvp/adapter_tests.cpp` (selection and identity gates)
- offline: `experiments/native-bridge/mvp/core_tests.cpp` (protocol and lifecycle)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Earlier accepted MVP baseline

Uncertainties:
- Atomicity of the registry between calls is not established; a matching count does not prove a stable snapshot.
- FindByIndex outside the checked range can raise a host error and is never attempted.

Scope: operations native_datasets, native_mean, native_statistics, native_crop, native_display, native_read, native_preview, native_fft, native_filters, native_image_arithmetic, native_frame, native_histogram, native_line_profile, native_gui_rois, native_numeric_import; dtypes any registered image (lookup only); versions 3.53.4137.0.
- limit: idle host required
- limit: no concurrent edit protection

On any build change re-derive: sha256, export_name, call_shape, layout, ownership.

### `image.enumerate` — Bounded native registry enumeration

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `?CountAllImages@Image@GMS@@SAKXZ` in `GMSImage.dll`
- Call shape: `win64_msvc`, returns `uint32_t`

  Enumeration prefers count plus zero-based FindByIndex over the functional EnumImages callback, whose allocator-specific vector ABI is not closed.
- Layout / ownership: not recorded — no object crosses this call; only a scalar count is returned

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Bounded enumeration — count plus index lookup is the preferred bounded enumeration path
- `experiments/native-bridge/ABI_NOTES.md` ## Bounded enumeration — the registry may include images without visible document windows

Verification:
- offline: `experiments/native-bridge/mvp/adapter_tests.cpp` (duplicate-ID and count checks)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Earlier accepted MVP baseline

Uncertainties:
- Registry contents may change between the count and the individual lookups.

Scope: operations native_datasets; dtypes metadata only; versions 3.53.4137.0.
- limit: output budget enforced before any lookup

On any build change re-derive: sha256, export_name, call_shape.

### `image.id` — Numeric image identity

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `?GetID@Image@GMS@@QEBAKXZ` in `GMSImage.dll`
- Call shape: `win64_msvc_member`, returns `uint32_t`

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `this` | `const void*` | borrowed image pointer |
- Layout / ownership: not recorded — the call reads no object field through a declared layout; only this-pointer identity is used

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Descriptors, calibration, and statistics — GetDataType and the descriptor getters read the native descriptor without touching pixels

Verification:
- offline: `experiments/native-bridge/mvp/adapter_tests.cpp` (identity agreement checks)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Earlier accepted MVP baseline

Scope: operations native_datasets, native_read, native_crop, native_result_release; dtypes any; versions 3.53.4137.0.
- limit: identity only; no descriptor or pixel claim

On any build change re-derive: sha256, export_name, call_shape.

### `image.unicode_name` — UTF-16 image name getter

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `?GetUnicodeName@Image@GMS@@QEBA?AV?$basic_string@_WU?$char_traits@_W@std@@V?$allocator@_W@2@@std@@XZ` in `GMSImage.dll`
- Call shape: `win64_msvc_member_sret`, returns `pointer to the caller-provided 32-byte string object`, hidden structure-return pointer first

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `this` | `const void*` | member call receives this first |
  | 2 | `out` | `MsvcWideString*` | fresh caller storage; the callee constructs the object |

  Unlike the static lookups, this member method takes this before the hidden result pointer.
- Layout source: `experiments/native-bridge/ABI_NOTES.md` ## MSVC string ABI shim
  - `MsvcWideString` size 32 alignment 8: union storage at 0, length at 16, capacity at 24
- Ownership: exactly one release through the paired deallocator; length excludes the terminator and must be validated against capacity

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## MSVC string ABI shim — member sret order, inline-versus-heap rule and bounded UTF-16 conversion
- `experiments/native-bridge/ABI_NOTES.md` ## Legacy Python and native Unicode paths — an ASCII round trip does not establish non-ASCII interoperation

Verification:
- offline: `experiments/native-bridge/mvp/adapter_tests.cpp` (string layout and guard paths)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Earlier accepted MVP baseline

Uncertainties:
- Non-ASCII interoperation remains NOT_QUALIFIED; a correct UTF-16 conversion does not establish agreement with legacy Python name bindings.
- Lone surrogates and malformed layouts must fail closed and are only covered offline.

Scope: operations native_datasets; dtypes metadata only; versions 3.53.4137.0.
- limit: ASCII names only for qualified use

On any build change re-derive: sha256, export_name, call_shape, layout, string_allocator.

## Area: image-memory

### `abi.msvc_string_release` — Matching deallocator for MSVC wide-string output

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - ordinal `#1487` in `mfc140.dll`
- Call shape: `win64_msvc`, returns `void`

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `allocation` | `void*` | the address that was actually returned by the vendor allocator |

  Resolved by ordinal with GetProcAddress from the already-loaded module; its module identity is part of the ABI allowlist.
- Layout source: `experiments/native-bridge/ABI_NOTES.md` ## MSVC string ABI shim
  - `MsvcWideString (heap form)` size 32 alignment 8: heap pointer at 0, length at 16, capacity at 24
- Ownership: below 4096 bytes the heap pointer is released directly; at or above 4096 the exposed pointer is 32-byte aligned and the original allocation address is the pointer-sized word immediately before it (difference 8..39 bytes)

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## MSVC string ABI shim — the inspected destruction path, the alignment rule and the ordinal binding

Verification:
- offline: `experiments/native-bridge/mvp/adapter_tests.cpp` (malformed layout fails closed without double free)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Earlier accepted MVP baseline

Uncertainties:
- The allocation/deallocation pairing is layout-specific and is not a public vendor string API.
- mfc140.dll is gated by SHA-256 but not by file version.

Scope: operations native_datasets, native_read, native_line_profile; dtypes metadata only; versions 3.53.4137.0.
- limit: must be paired with the vendor allocator; never use local free/delete

On any build change re-derive: sha256, ordinal, call_shape, layout, allocator_pairing.

### `image.reference_release` — Owned image reference release

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `?ref_ptr_delete@Gatan@@YAXPEAVImage@GMS@@@Z` in `GMSImage.dll`
- Call shape: `win64_msvc`, returns `void`

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `image` | `void*` | only reachable when the intrusive count has just reached zero |

  The export is a final destructor/deallocator. Calling it on every successful lookup would destroy a live image.
- Layout source: `experiments/native-bridge/ABI_NOTES.md` ## Image identity and ownership
  - `GMS::Image (prefix only)` size 8 alignment 8: signed 64-bit intrusive reference count at offset 0; not a vtable pointer
- Ownership: decrement atomically; call ref_ptr_delete only when the new count is zero; never release a borrowed pointer and never copy an owned reference without a matching increment

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Image identity and ownership — first field is a signed 64-bit intrusive count and the export is a final deallocator
- `experiments/native-bridge/ABI_NOTES.md` ## Independent crop contract — returned references follow the same ownership rule as lookup

Verification:
- offline: `experiments/native-bridge/mvp/result_release_tests.cpp` (release guards and early-return paths)
- offline: `experiments/native-bridge/mvp/candidate_calls_tests.cpp` (synthetic ownership transfer rules)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Historical live continuation: SUMMARY and document lifecycle

Uncertainties:
- Synchronous destruction of document-held references on the same stack failed an early check; after-return idle behaviour is the qualified contract.
- The count is not a stable public API; any layout change invalidates the guard.

Scope: operations native_result_release, native_crop, native_read, native_display, native_histogram, native_line_profile; dtypes any; versions 3.53.4137.0.
- limit: one release per owned reference
- limit: never on a borrowed pointer

On any build change re-derive: sha256, export_name, layout, ownership.

## Area: image-pixels

### `image.real_value` — Element read and write through a 2D index

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `?GetRealValue@Image@GMS@@QEBANAEBVDataIndex@Imaging@Gatan@@@Z` in `GMSImage.dll`
  - export `?SetRealValue@Image@GMS@@QEAAXAEBVDataIndex@Imaging@Gatan@@N@Z` in `GMSImage.dll`
- Call shape: `win64_msvc_member`, returns `double (getter) or void (setter)`

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `this` | `const void*` | member call |
  | 2 | `index` | `const DataIndex*` | only the documented 2D prefix is constructed |
  | 3 | `value` | `double` | setter only, passed in the floating-point register |

  The 2D index prefix is dimension count at byte 0, signed X at byte 8, signed Y at byte 16. This is not a complete definition of the vendor's multidimensional class.
- Layout source: `experiments/native-bridge/ABI_NOTES.md` ## Version isolation and additional typed operations
  - `DataIndex (2D prefix only)` size 24 alignment 8: dimension count dword at 0, int64 x at 8, int64 y at 16
- Ownership: caller-owned index; no reference is created or released

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Version isolation and additional typed operations — the getter returns double and consumes only the proven 2D index prefix
- `experiments/native-bridge/mvp/adapters/gms_3_53_4137/read_contract.hpp` DataIndex — compile-time layout assertions for the index prefix

Verification:
- offline: `experiments/native-bridge/mvp/read_adapter_tests.cpp` (exact float32 encoding, signed zero, uint32 integral checks)
- offline: `experiments/native-bridge/mvp/import_adapter_tests.cpp` (write-read back validation)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Earlier accepted MVP baseline

Uncertainties:
- The full multidimensional index class is not defined; only the 2D prefix is used.
- Inexact or non-finite float32 conversions are rejected rather than rounded.

Scope: operations native_read, native_uint32_read, native_preview, native_histogram, native_numeric_import, native_line_profile; dtypes float32, uint32, float64 (rank-one read); versions 3.53.4137.0.
- limit: <=16384 samples per READ
- limit: no generic pixel-buffer mapping

On any build change re-derive: sha256, export_name, call_shape, layout.

## Area: presentation

### `presentation.plot_style` — Histogram bar styling candidate

- Qualification: `STATIC_CANDIDATE` (derivation: `static_inspection`)
- Bindings:
  - non-exported entry contract `plot_style_get` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `plot_style_set` in `GMS.dll` (RVA lives only in the version profile)
- Call shape: `win64_msvc`, returns `one byte (getter) or void (setter)`

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `display` | `LinePlotImageDisplay*` | resolved through the already qualified ROI display path |
  | 2 | `value` | `byte` | single presentation flag |

  The script layer is skipped entirely: the bridge proves the dynamic type through the object's complete object locator before calling the setter.
- Layout source: `experiments/native-bridge/ABI_NOTES.md` ## Native one-dimensional results, image creation and histogram
  - `LinePlotImageDisplay (styling field only)` size unknown alignment n/a: one byte proven by a dedicated getter/setter pair
- Ownership: the acquired image reference is balanced before any vendor setter or getter call

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Native one-dimensional results, image creation and histogram — the internal setter stores one byte and a dedicated getter returns it; no other reader or writer was found
- `AGENTS.md` ## Product boundary — histogram bar styling is a candidate that is not qualified and is disabled for shipping

Verification:
- offline: `experiments/native-bridge/mvp/histogram_adapter_tests.cpp` (display_style reports default with style_not_qualified)

Uncertainties:
- Proving the dynamic type requires reading the object's complete object locator; a decorated type name alone is not sufficient.
- Repaint behaviour is not observable in a way that this project can qualify.

Scope: operations native_line_plot_style; dtypes not applicable; versions 3.53.4137.0.
- limit: disabled for shipping; host default style is used instead

On any build change re-derive: sha256, rva, vtable_identity, layout.

## Area: processing

### `processing.reductions` — Scalar reductions over a locked layout

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `?GetMean@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z` in `GMSImageProcessing.dll`
  - export `?GetMinimum@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z` in `GMSImageProcessing.dll`
  - export `?GetMaximum@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z` in `GMSImageProcessing.dll`
  - export `?GetSum@GMSImageProcessing@@YANAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z` in `GMSImageProcessing.dll`
- Call shape: `win64_msvc`, returns `double in the normal floating-point return register`

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `image` | `const NativeImageRef*` | borrowed; the callee obtains data, locks a layout and calls the native reduction |

  No intensity calibration is fetched or applied: the value is raw pixel intensity. Each result is checked for finiteness before the next call.
- Layout / ownership: not recorded — the reduction is performed by the vendor path; the bridge only passes a reference and reads a scalar

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Descriptors, calibration, and statistics — GetMean returns binary64 in the floating-point return register and yields raw intensity
- `experiments/native-bridge/ABI_NOTES.md` ## Native SUMMARY reductions — the four exports share one const NativeRef* shape and are called sequentially

Verification:
- offline: `experiments/native-bridge/mvp/uint32_adapter_tests.cpp` (pixel-count and overflow budgets)
- offline: `experiments/native-bridge/mvp/candidate_calls_tests.cpp` (reduction callback shape)
- real host: `PASS_LIMITED` — `experiments/native-bridge/mvp/SUMMARY_ACCEPTANCE.md` ## 同宿主独立 oracle

Uncertainties:
- Sequential calls are not an atomic snapshot; snapshot_atomic is false.
- Variance, median and stddev are separate candidates with unresolved conventions.

Scope: operations native_mean, native_statistics, native_uint32_mean, native_uint32_statistics; dtypes float32, uint32; versions 3.53.4137.0.
- limit: uint32 sums bounded to 2097152 pixels
- limit: <=4194304 source pixels for float32 SUMMARY

On any build change re-derive: sha256, export_name, call_shape, dtype_budget.

### `processing.histogram` — Native histogram operator

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `?CalcHistogram@GMSImageProcessing@@YAXAEBV?$ref_ptr@VImage@GMS@@@Gatan@@0NN@Z` in `GMSImageProcessing.dll`
- Call shape: `win64_msvc`, returns `void`

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `source` | `const NativeImageRef*` | borrowed source reference |
  | 2 | `destination` | `const NativeImageRef*` | caller-created rank-one image |
  | 3 | `minimum` | `double` | requested lower range bound, binary64 |
  | 4 | `maximum` | `double` | requested upper range bound, binary64 |

  The script function ImageCalculateHistogram is a wrapper over this operator. The bridge performs no binning of its own.
- Layout / ownership: not recorded — both arguments are references to existing images; no new object layout crosses the boundary

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Native one-dimensional results, image creation and histogram — CalcHistogram is exported with a caller-created one-dimensional destination and no bridge kernel
- `docs/NATIVE_HISTOGRAM.md` ## Request and counts — counts must be exact non-negative integers whose total equals the source pixel count

Verification:
- offline: `experiments/native-bridge/mvp/histogram_adapter_tests.cpp` (range coverage, bin budget and exact-count checks)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Rank-one delivery and native histogram (2026-10-25 audit round)

Uncertainties:
- The undocumented under/overflow rule is never exercised: the caller range must cover the complete source range.
- Counts are uint32 in storage; transport is exact binary64.

Scope: operations native_histogram, native_histogram_display, native_histogram_axis; dtypes float32; versions 3.53.4137.0.
- limit: 2..4096 bins
- limit: <=4194304 source pixels
- limit: complete range coverage required

On any build change re-derive: sha256, export_name, call_shape, count_invariants.

### `processing.convert` — Native dtype conversion

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `?ImageConvert@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@K@Z` in `GMSImageProcessing.dll`
- Call shape: `win64_msvc_sret`, returns `pointer to the caller-provided result slot`, hidden structure-return pointer first

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `out` | `NativeImageRef*` | receives one owned reference |
  | 2 | `source` | `const NativeImageRef*` | borrowed |
  | 3 | `type` | `uint32_t` | target scalar type code |
- Layout / ownership: not recorded — only existing image references and a scalar type code cross the boundary

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Explicit sequence-frame copy — ImageConvert creates an independent float32 result and the temporary is released before the retained result is committed
- `experiments/native-bridge/mvp/NATIVE_FRAME.md` ## Input, coordinates and native computation — DM performs the conversion; every uint16 value remains exact in float32

Verification:
- offline: `experiments/native-bridge/mvp/frame_adapter_tests.cpp` (temporary and retained reference accounting)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Explicit uint16 sequence-frame working copies

Uncertainties:
- Only the uint16 to float32 direction is exercised.

Scope: operations native_frame; dtypes uint16 -> float32; versions 3.53.4137.0.
- limit: <=1048576 XY pixels
- limit: two-image temporary peak reserved before allocation

On any build change re-derive: sha256, export_name, call_shape, ownership.

### `processing.filters` — 3x3 convolution filters

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `?SmoothFilter@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z` in `GMSImageProcessing.dll`
  - export `?SobelFilter@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z` in `GMSImageProcessing.dll`
  - export `?LaplaceFilter@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z` in `GMSImageProcessing.dll`
  - export `?SharpenFilter@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z` in `GMSImageProcessing.dll`
- Call shape: `win64_msvc_sret`, returns `pointer to the caller-provided result slot`, hidden structure-return pointer first

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `out` | `NativeImageRef*` | receives one owned reference |
  | 2 | `source` | `const NativeImageRef*` | borrowed |

  The unary wrapper shape is shared by all four filters. uint32 Smooth/Sharpen keep uint32 with native saturation and truncation; Sobel/Laplace return float32.
- Layout / ownership: not recorded — only image references cross the boundary; no filter kernel is constructed by the bridge

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Version isolation and additional typed operations — native 3x3 convolution accumulates in binary64 and uint32 stores saturate then truncate toward zero
- `experiments/native-bridge/mvp/OPERATIONS_ACCEPTANCE.md` ## 四种滤波的已验参考 — the four filters were checked against recorded references

Verification:
- offline: `experiments/native-bridge/mvp/pixel_adapter_tests.cpp` (shape and dtype gates)
- offline: `experiments/native-bridge/mvp/uint32_operations_tests.cpp` (uint32 saturation and truncation expectations)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Current feature: native operations and scientific handoff

Uncertainties:
- Edge and boundary semantics are the vendor's; they are not re-derived or asserted.
- Only axes 5..256 are admitted.

Scope: operations native_filters, native_pixel_filters, native_uint32_filters; dtypes float32, uint32; versions 3.53.4137.0.
- limit: dimensions 5..256
- limit: smooth/sobel/laplace/sharpen only

On any build change re-derive: sha256, export_name, call_shape, dtype_semantics.

### `processing.unary` — Unary arithmetic operators

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `?Negate@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z` in `GMSImageProcessing.dll`
  - export `?Abs@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z` in `GMSImageProcessing.dll`
  - export `?Square@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z` in `GMSImageProcessing.dll`
- Call shape: `win64_msvc_sret`, returns `pointer to the caller-provided result slot`, hidden structure-return pointer first

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `out` | `NativeImageRef*` | receives one owned reference |
  | 2 | `source` | `const NativeImageRef*` | borrowed |

  uint32 inputs are zero-extended, converted to binary64, processed by the vendor operator and stored as binary32.
- Layout / ownership: not recorded — only image references cross the boundary

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Version isolation and additional typed operations — unary wrappers take one source reference and the scientific conversion is the vendor's

Verification:
- offline: `experiments/native-bridge/mvp/uint32_operations_tests.cpp` (dtype and result-shape gates)
- real host: `PASS_LIMITED` — `experiments/native-bridge/mvp/UINT32_OPERATIONS_ACCEPTANCE.md` ## Qualification stages

Uncertainties:
- uint32 arithmetic is binary64 then float32 storage; it is not integer-exact.

Scope: operations native_image_arithmetic, native_uint32_image_arithmetic; dtypes float32, uint32; versions 3.53.4137.0.
- limit: negate, abs, square only
- limit: <=4 MiB output

On any build change re-derive: sha256, export_name, call_shape, dtype_semantics.

### `processing.binary` — Paired arithmetic operators

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `??HGMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z` in `GMSImageProcessing.dll`
  - export `??GGMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z` in `GMSImageProcessing.dll`
  - export `??DGMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z` in `GMSImageProcessing.dll`
- Call shape: `win64_msvc_sret`, returns `pointer to the caller-provided result slot`, hidden structure-return pointer first

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `out` | `NativeImageRef*` | receives one owned reference |
  | 2 | `left` | `const NativeImageRef*` | borrowed |
  | 3 | `right` | `const NativeImageRef*` | borrowed |

  Only add, subtract and multiply are bound. Division is a known export but is not admitted by the shipped operation contract.
- Layout / ownership: not recorded — only image references cross the boundary

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Version isolation and additional typed operations — binary wrappers take two source references and the vendor operator performs the computation
- `experiments/native-bridge/mvp/candidate_calls.cpp` ??KGMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV12@0@Z — the divide export exists but is catalogued as an unqualified candidate

Verification:
- offline: `experiments/native-bridge/mvp/uint32_operations_tests.cpp` (descriptor compatibility and dtype matching)
- real host: `PASS_LIMITED` — `experiments/native-bridge/mvp/UINT32_OPERATIONS_ACCEPTANCE.md` ## Qualification stages

Uncertainties:
- Shape-mismatch policy is the vendor's; the bridge refuses mismatched descriptors instead of relying on it.
- Division is deliberately not admitted.

Scope: operations native_image_arithmetic, native_uint32_image_arithmetic; dtypes float32, uint32; versions 3.53.4137.0.
- limit: add, subtract, multiply only
- limit: matching dtypes and compatible descriptors required

On any build change re-derive: sha256, export_name, call_shape, dtype_semantics.

### `processing.fourier` — Forward, inverse and component Fourier operators

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - export `?Real_FFT@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z` in `GMSImageProcessing.dll`
  - export `?IFFT@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z` in `GMSImageProcessing.dll`
  - export `?Real@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z` in `GMSImageProcessing.dll`
  - export `?Imag@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z` in `GMSImageProcessing.dll`
  - export `?Arg@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z` in `GMSImageProcessing.dll`
  - export `?Norm@GMSImageProcessing@@YA?AV?$ref_ptr@VImage@GMS@@@Gatan@@AEBV23@@Z` in `GMSImageProcessing.dll`
- Call shape: `win64_msvc_sret`, returns `pointer to the caller-provided result slot`, hidden structure-return pointer first

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `out` | `NativeImageRef*` | receives one owned reference |
  | 2 | `source` | `const NativeImageRef*` | borrowed; the operator selects its own internal path |

  Contract version 2: forward uses a positive exponent, no normalization and fftshift data; inverse uses a negative exponent divided by width*height and resets the spatial origin to zero.
- Layout / ownership: not recorded — only image references cross the boundary; the complex representation is returned as a native image

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## FFT interface investigation: not qualified — the exported FFT family shares the one-pointer reference shape but imposes different descriptor and packing constraints
- `experiments/native-bridge/mvp/FFT_READINESS.md` ## v2 明确的数值与坐标 — the measured sign, normalization, centering and calibration are reported separately from mathematical bin coordinates

Verification:
- offline: `experiments/native-bridge/mvp/uint32_operations_tests.cpp` (large-shape admission and pool accounting)
- offline: `experiments/native-bridge/mvp/core_tests.cpp` (retained-result pool arithmetic)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Bounded larger Fourier operations

Uncertainties:
- The empirical small dense-FFT accuracy policy is not a general error theorem.
- An earlier binary64-expression power oracle FAIL is preserved as history and is not repaired by later passes.
- Vendor workspace memory is not bounded by the bridge.

Conflicts:
- Real_FFT input is ordinary-packed float32 or uint32-rounded binary32, not a complex image, while FFT expects a different packing; selecting by dtype alone would be wrong (resolved)

Scope: operations native_fft, native_pixel_fft, native_uint32_fft, native_fft_large, native_ifft_large, native_real_large, native_imag_large, native_phase_large, native_power_large, native_uint32_fft_large, native_uint32_real_large, native_uint32_imag_large, native_uint32_phase_large, native_uint32_power_large; dtypes float32, uint32 (rounded to binary32 on input); versions 3.53.4137.0.
- limit: power-of-two axes 4..256, or 4..1024 with a matching large capability
- limit: <=1048576 pixels in v2
- limit: uint32 IFFT large remains unqualified

On any build change re-derive: sha256, export_name, call_shape, numerical_convention, pool_budget.

### `processing.fourier_packed_candidates` — Packed and complex-first Fourier candidates

- Qualification: `STATIC_CANDIDATE` (derivation: `static_inspection`)
- Bindings:
  - plain name `FFT` in `GMSImageProcessing.dll` (decorated export name not recorded; not a binding)
  - plain name `Packed_FFT` in `GMSImageProcessing.dll` (decorated export name not recorded; not a binding)
- Call shape: `win64_msvc_sret`, returns `presumed pointer to a caller-provided result slot`, hidden structure-return pointer first

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `out` | `NativeImageRef* (presumed)` | same one-pointer reference skeleton as the qualified family |
  | 2 | `source` | `const NativeImageRef* (presumed)` | packing requirements differ from Real_FFT |

  Only a partial static skeleton is known. The decorated export names are not recorded in the shipping profile; this entry is not a binding.
- Layout / ownership: not recorded — the packed representation and the complex storage layout were not closed

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## FFT interface investigation: not qualified — bounded machine-code inspection supports the reference shape but not a production call contract
- `experiments/native-bridge/mvp/candidate_calls.cpp` FFT_WRAPPER_REVIEWED_STATIC_PARTIAL — complex, real and packed inputs differ; normalization, centering and ownership are unqualified

Verification:
- offline: `experiments/native-bridge/mvp/candidate_calls_tests.cpp` (synthetic callback coverage only)

Uncertainties:
- Exact complex storage, normalization, centering, usable reciprocal axes and workspace bounds are unresolved.
- Ordinary float32 input must not select FFT merely by dtype.

Scope: operations -; dtypes unknown; versions 3.53.4137.0.
- limit: no binding, no protocol operation, no MCP tool

On any build change re-derive: export_name, call_shape, layout, numerical_convention.

### `processing.other_signatures` — Reductions with call shapes outside the bound adapters

- Qualification: `BLOCKED` (derivation: `static_inspection`)
- Bindings:
  - export `?GetPixelCount@GMSImageProcessing@@YA_KAEBV?$ref_ptr@VImage@GMS@@@Gatan@@@Z` in `GMSImageProcessing.dll`
  - export `?GetMeanAndVariance@GMSImageProcessing@@YAXAEBV?$ref_ptr@VImage@GMS@@@Gatan@@AEAN1@Z` in `GMSImageProcessing.dll`
  - export `?GetMinimumMaximum@GMSImageProcessing@@YAXAEBV?$ref_ptr@VImage@GMS@@@Gatan@@AEAN1@Z` in `GMSImageProcessing.dll`
- Call shape: `win64_msvc`, returns `uint64_t or void with two double outputs`

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `source` | `const NativeImageRef*` | borrowed |
  | 2 | `outputs` | `double*` | two caller-provided outputs for the multi-value forms |

  These exact exports exist but their shapes do not match the bound Unary/Binary/Reduction callbacks, so they are catalogued and refused.
- Layout / ownership: not recorded — no layout is needed for a refused binding

Static evidence:
- `experiments/native-bridge/mvp/candidate_calls.cpp` EXPORTED_OTHER_SIGNATURE — known exports with signatures outside the three adapted shapes are blocked
- `experiments/native-bridge/mvp/BATCH_CANDIDATES.md` ## 已识别但没有硬套进调用层的项目 — identified items were deliberately not forced into the prepared call layer

Verification:
- offline: `experiments/native-bridge/mvp/candidate_calls_tests.cpp` (blocked entries reject invocation)

Uncertainties:
- The two-output forms would need their own qualification, including precision and non-finite conventions.

Scope: operations -; dtypes unknown; versions 3.53.4137.0.
- limit: invocation always rejected

On any build change re-derive: export_name, call_shape.

## Area: roi

### `roi.display_resolution` — Image display and ROI enumeration entrypoints

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - non-exported entry contract `roi_image_display_count` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `roi_image_display_at` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `roi_resolve_display` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `roi_display_image` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `roi_destroy_display_holder` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `roi_destroy_roi` in `GMS.dll` (RVA lives only in the version profile)
- Call shape: `win64_msvc`, returns `varies; enumeration returns a count and per-index holders`

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `image` | `Image*` | the explicit native image reference; never a front-image lookup |
  | 2 | `index` | `uint32_t` | validated against the returned count |

  An owned display holder keeps the document/component context alive while the resolved display is borrowed. Reverse image lookup must match both pointer and numeric ID.
- Layout / ownership: not recorded — display and ROI objects stay opaque; only their reference counters are proven

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ### Earlier GUI rectangle continuation: typed read-only ownership, limited qualification — display enumeration uses the explicit image reference and each acquired ROI follows the traced getter/destructor contract
- `docs/NATIVE_GUI_ROI.md` ## Identity and coordinates — IDs compose image, document, display component and ROI; they are not global names

Verification:
- offline: `experiments/native-bridge/mvp/roi_adapter_tests.cpp` (identity, geometry and ownership guards)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Earlier continuation: GUI ROI qualification and independent Fourier control

Uncertainties:
- Immediate same-stack destruction after fixture cleanup failed and is preserved as a separate FAIL; after-return idle behaviour is the qualified contract.
- Repeated reads detect changes but do not provide an atomic GUI/source lock.

Scope: operations native_gui_rois, native_line_profile; dtypes float32, uint32; versions 3.53.4137.0.
- limit: direct ImageSource_Simple layout only
- limit: slice_ids:[0] only

On any build change re-derive: sha256, rva, call_shape, layout, ownership, vtable_identity.

### `roi.geometry` — ROI geometry, raster mapping and direct source layout

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - non-exported entry contract `roi_id` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `roi_is_selected` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `roi_is_rectangle` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `roi_rectangle` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `roi_raster_count` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `roi_raster_at` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `roi_raster_dimensions` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `roi_raster_mapping` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `roi_raster_slice_id` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `roi_simple_source_count` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `roi_simple_source_slice_id` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `roi_simple_source_extents` in `GMS.dll` (RVA lives only in the version profile)
- Call shape: `win64_msvc`, returns `varies per getter`

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `roi` | `void*` | owned ROI reference |
  | 2 | `outputs` | `typed pointers` | raw top/left/bottom/right and rotation are preserved |

  Raster type and relevant vtable entries are checked before their typed getters. Direct getters retain errors instead of inheriting wrapper exception-to-zero behaviour.
- Layout source: `experiments/native-bridge/ABI_NOTES.md` ### Earlier GUI rectangle continuation: typed read-only ownership, limited qualification
  - `RasterImageDisplay vtable identity` size n/a alignment n/a: module-specific vtable RVA cross-checked against RTTI
- Ownership: each acquired ROI uses the traced owning getter/destructor contract; the bridge never creates or modifies a document, pixel or selection

Static evidence:
- `docs/NATIVE_GUI_ROI.md` ## Identity and coordinates — raw rectangle edges and rotation are preserved; only integral, finite, in-bounds unrotated rectangles become half-open analysis ROIs
- `experiments/native-bridge/ABI_NOTES.md` ### Earlier GUI rectangle continuation: typed read-only ownership, limited qualification — the selected-ID getter returns slice IDs, not dimensions or an axis permutation

Verification:
- offline: `experiments/native-bridge/mvp/roi_adapter_tests.cpp` (geometry, ineligible source classes and error retention)
- real host: `PASS_LIMITED` — `docs/NATIVE_GUI_ROI.md` ## Executed engineering checks

Uncertainties:
- Sliced, Group and Summed sources remain ineligible; only direct ImageSource_Simple plus slice_ids:[0] establishes source-pixel alignment.
- An earlier observation under the old mapping assumption failed and remains preserved.

Conflicts:
- slice IDs were once misread as axis dimensions, producing an eligibility FAIL; the contract now treats them as slice identity (resolved)

Scope: operations native_gui_rois; dtypes float32, uint32; versions 3.53.4137.0.
- limit: no rounding, clipping or most-recent-window inference

On any build change re-derive: sha256, rva, call_shape, vtable_identity, layout.

### `roi.line_profile` — GUI line extraction to a true one-dimensional image

- Qualification: `QUALIFIED_LIMITED` (derivation: `static_inspection`)
- Bindings:
  - non-exported entry contract `roi_is_line` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `roi_line` in `GMS.dll` (RVA lives only in the version profile)
  - non-exported entry contract `line_profile_extract` in `GMS.dll` (RVA lives only in the version profile)
- Call shape: `win64_msvc`, returns `new owned image pointer written through the destination slot`, hidden structure-return pointer first

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `out` | `NativeImageRef*` | receives one owned reference to a new rank-one image |
  | 2 | `source` | `const NativeImageRef*` | borrowed; retained lineage is checked before extraction |
  | 3 | `parameters` | `typed line parameters` | verified width-one integer endpoints |

  A one-shot extraction call; the name does not expose a live evaluator or a background listener.
- Layout / ownership: not recorded — the output is a normal native image; no new object layout crosses the boundary

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ### GUI line extraction and true one-dimensional handoff — the one-shot extraction returns a new owned image guarded by the existing reference RAII
- `docs/NATIVE_LINE_PROFILE.md` ## Narrow input contract — width one, axis-aligned integer centres, equal signed scales and at most 4096 samples

Verification:
- offline: `experiments/native-bridge/mvp/line_profile_adapter_tests.cpp` (eligibility, endpoint and output-rank guards)
- real host: `PASS_LIMITED` — `experiments/native-bridge/RESULTS.md` ## Current continuation: GUI line and true native 1D profile

Uncertainties:
- Diagonal, fractional and wide profiles remain unqualified.
- A prior fixture with fractional GUI coordinates failed its oracle and remains preserved.

Scope: operations native_line_profile, native_profile_display; dtypes float32, uint32 sources; float64 output; versions 3.53.4137.0.
- limit: <=4096 endpoint-inclusive samples
- limit: known Fourier lineage refused

On any build change re-derive: sha256, rva, call_shape, ownership.

## Area: superseded

### `superseded.probe_lookup` — Legacy probe object-token lookup

- Qualification: `BLOCKED` (derivation: `documented`)
- Bindings:
  - plain name `FindImageAsObject` in `GMSImage.dll` (decorated export name not recorded; not a binding)
- Call shape: `win64_msvc`, returns `reference to an image chosen by object-address token`

  | # | Parameter | Type | Notes |
  | --- | --- | --- | --- |
  | 1 | `token` | `unsigned __int64` | an object-address token, not the numeric ID returned by GetID |

  Recorded only to prevent reuse. It is not a replacement for numeric-ID lookup.
- Layout / ownership: not recorded — the token semantics were never closed and are now superseded

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ## Image identity and ownership — the older probe's FindImageAsObject compares an object-address token and is not a replacement for numeric lookup
- `AGENTS.md` ## Architecture and ownership — the retired nb_probe must never be built or loaded

Verification:
- none recorded

Uncertainties:
- Object addresses are not stable identifiers.

Scope: operations -; dtypes not applicable; versions 3.53.4137.0.
- limit: do not revive the retired PE resolver

On any build change re-derive: call_shape.

## Area: unresolved

### `unresolved.workspace_activation` — Workspace enumeration, activation and annotation UI

- Qualification: `UNRESOLVED` (derivation: `documented`)
- Bindings:
  - none: unresolved: ImageUtilities-based candidates use different object families (Gatan::DM::Image, ROI, ImageDisplay/ScriptObject) than the adapter's GMS::Image reference contract, and workspace event registration does not establish a typed enumeration or activation API
- Call shape: unknown — no typed contract or ownership definition was available
- Layout / ownership: not recorded — the candidate object families were never mapped to a proven layout

Static evidence:
- `experiments/native-bridge/ABI_NOTES.md` ### Earlier GUI and workspace boundary — workspace activation and annotations remain unqualified; no guessed casts or calls were attempted
- `experiments/native-bridge/ABI_NOTES.md` ## Bounded enumeration — manual tests only show that explicit image IDs stay stable across tabs

Verification:
- none recorded

Uncertainties:
- Whether an activation API exists at all is unknown.
- A SHOW receipt is not an active-tab or focus assertion.

Scope: operations -; dtypes not applicable; versions 3.53.4137.0.
- limit: no UI automation or Python fallback is permitted

On any build change re-derive: call_shape, layout, ownership.

