# Explicit GUI line to native 1D profile

The experimental native backend can adapt an explicitly identified GUI line to
DM's own `LiveProfile_ExtractLineProfile` interface. This is a separate operation
from the default Python backend's `dm_profile`. There is no Python listener,
scientific kernel or automatic backend fallback in the native path.

Qualification: **limited synthetic actual-host PASS** for the contract below.
Final artifact confirmation is recorded independently of the prepared trial.
The already qualified rectangle path remains available independently.

## Narrow input contract

Use `dm_native_rois` with an explicit image ID. New ROIS replies have version 2;
historical version-1 QUERY records remain historical and are not rewritten.
Line coordinates are preserved as returned by DM. A profile requires all of:

- The exact `(image_id, document_id, display_id, roi_id)` identity returned by
  ROIS, plus the caller's saved `expected_line:[x0,y0,x1,y1]`.
- An ordinary float32 or uint32 2D source, at most 4,194,304 pixels, with the
  qualified direct canonical XY raster source/mapping.
- An unrotated horizontal or vertical line with distinct integer endpoints,
  both inside the image. Coordinates denote pixel centres; **both endpoint
  samples are included**. Reversed lines preserve their requested direction.
- `width:1`, at most 4096 samples, complete spatial calibration and identical
  nonzero signed scales and units on the two source axes.

Diagonal/fractional/zero-length lines, wider integration bands, anisotropic
calibration and unsupported sources are rejected explicitly. No clipping,
rounding, latest-window selection or implicit full-image selection occurs.
The adapter rereads identity and geometry immediately around the native call;
changed state fails. This is change detection, not an atomic GUI/pixel lock.

## Invocation and recovery

Save the native session, request ID and complete arguments before submission:

```json
{
  "image_id": 123,
  "document_id": 4,
  "display_id": 9,
  "roi_id": 27,
  "expected_line": [2, 4, 17, 4],
  "width": 1,
  "request_id": "profile-line-01"
}
```

Call `dm_native_profile` once. On timeout or cancellation, use
`dm_native_result` with **the original ID**, in the same still-queryable native
session. Do not replay with a new ID. The same ID and arguments returns the
original result; changing parameters conflicts. STOP/host exit does not retain
the volatile request history.

The completed reply contains an exact output image ID, plugin retention token,
true one-dimensional metadata and bounded immutable float64 numeric bytes.
QUERY retrieves those original bytes even after explicit reference release;
it neither reruns the operation nor rereads mutable image pixels.

## Scientific coordinates and delivery

The output is a true DM one-dimensional float64 image, `shape:[N]`, not a
fabricated `[1,N]` raster. Values represent raw pixel intensity;
`intensity_calibration_applied:false`. Source intensity calibration is not a
license to relabel numbers as electrons/counts.

Preserve DM's native output axis, raw origin, physical pixel-zero, signed scale
and unit. Keep the ordered source endpoints and source sample trajectory
separately. A reversed line or a negative native scale must not silently change
the samples' order or become a positive laboratory coordinate. Distance along
the path and native-axis coordinates are distinct metadata.

The explicit external `tools/native_snapshot_handoff.mjs` encoder accepts a
saved successful PROFILE response and writes a new NPY/schema-1 package with
actual `shape:[N]`, `<f8` data and one native profile axis. It preserves the
original NB2 receipt, full GUI identity/line, source calibration and processing
parameters, and hashes the numeric/file bytes. This is bridge-owned data
handoff, **not DM SaveAs**. Existing files are never overwritten; incomplete
requests are not retried automatically. The existing READ/chunked 2D paths
retain their separate coordinate contracts.

```powershell
node tools/native_snapshot_handoff.mjs --workspace EXISTING_WORKSPACE --output NEW_PROFILE_DIR --request-id profile-file-01 --snapshot SAVED_PROFILE_RESPONSE.json
```

## Showing the one-dimensional result

The true rank-one PROFILE result can be delivered to a visible DM document with
`dm_native_show` and that exact `image_id`. This goes through a separate
admission group, `native_profile_display`; the 2D display group is never used and
the result is never relabelled as a `[1,N]` raster.

The reply keeps the honest one-dimensional identity (`rank:1`,
`display_family:"native_1d_image_document"`, `one_dimensional_display` with the
true `[N]` shape and one native axis), and `display_class` is `host_selected`
because the bridge does not assert a display class name. Writing the descriptor
under a 2D key, or presenting the samples as `[1,N]`, is rejected by the MCP
client.

Actual-host observation (synthetic line, pinned build): the profile document
appeared as a rank-one image and its display type code was 3, while the
two-dimensional source document reported type 1. That is the host's own behaviour
for a rank-one image; repeated SHOW reused the same document and window, and the
plugin reference was released independently of the document.

Not claimed: model-side visual verification, an active-tab assertion, file
saving, a stable display-class ABI, or any acceptance for 1D results that do not
come from this plugin's qualified PROFILE (or, separately, HISTOGRAM) record.

`dm_native_result_info` and `dm_native_release` use the same output ID and
retention token. Release drops only the plugin reference. The original PROFILE
receipt remains unchanged. Existing native READ/SHOW/MEAN/crop/FFT/filter tools
keep their own 2D admission; this task does not qualify them for 1D data.

DATASETS preserves the qualified one-dimensional float64 descriptor while the
exact PROFILE-created object is still held by this plugin. Enumeration does not
read its sample values or enable any 2D operator. Arbitrary/untracked code-12
images keep their previous unknown-type treatment; matching a numeric ID alone
is not enough. This descriptor-only follow-up has offline regression coverage;
it is not a new live-host qualification or 1D display capability.

## Independent acceptance

Use a new empty idle test session and
`experiments/native-bridge/mvp/create_line_profile_fixture.py` solely as a
one-shot synthetic fixture. No original experimental file is opened or edited.
The fixture includes a signed fractional-valued plane, nonlinear values, uint32
values above 2^31, negative scale and an anisotropic rejection control, plus
horizontal, vertical, reversed, boundary and explicitly unsupported lines.
After returning to host idle, run `verify_fixture_baseline` in a separate
one-shot **before any MCP submission**, to verify the fixture's original pixels,
calibration, names, complete GUI observations and document inventory. A failed
baseline must stop qualification; do not replace it after operations have run.

An early fractional-line fixture changed from fractional to integer endpoints
by its first ROIS observation and failed its full-GUI invariance check.
That FAIL is retained. It does not qualify fractional line processing or prove
which host update caused the change. The admitted integer-only fixture passed
its separate idle baseline and subsequent invariance checks. Fractional geometry
rejection remains independently tested offline.

The independent verifier must bind the original request/receipt to its actual
host PID and session; compare all source bytes/calibration/names/GUI identities;
compare true 1D output and reopened NPY against independently enumerated source
samples; check original QUERY identity; and observe unshown output release in a
separate one-shot after the host returns to idle. Record the original STOP
request before sending it. Preserve failed attempts separately. Offline ABI
substitutes and protocol clients do not prove actual DM or model-client use.
