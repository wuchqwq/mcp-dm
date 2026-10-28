# Original-array inspection, statistics and line profiles

The independent `image_*` route now exposes three small composable tools. They
use the same immutable arrays and external environment as the researcher panel;
none reads Canvas colors, calls DM, or substitutes for a failed native tool.

| Tool | Scope and output |
| --- | --- |
| `image_probe` | 1..64 requested points in the exact saved source/frequency coordinate domain. Returns requested coordinates, nearest array indices/centres and values. Read-only; no request ID or scientific record is created. |
| `image_statistics` | A source `rect` or original FFT-bin `frequency_rect`, with half-open edges. Saves sample count, minimum, maximum, mean and **population** stddev (`ddof=0`), using binary64 reductions. |
| `image_profile` | Two endpoints, 2..4096 evenly spaced requested positions, width **1**, interpolation **nearest**. Saves requested and sampled coordinates, values, path distances, `profile.npy` and `profile.csv`. |

`component:raw` means stored scalar values. Complex arrays require an explicit
`real`, `imag`, `amplitude` or `power`; `raw` complex reads refuse. Power means
`abs(F)**2`, independently of the log-amplitude preview. The preview's Gamma,
contrast, resizing and optional display filter never enter these calculations.
Intensity calibration is not applied. A stored integer is not automatically
electron counts or phase radians.

Coordinates use the existing image contract. Real-space views use original
source pixel centres, including crop offsets; external FFTs use original signed
`cycles/pixel`. Nearest sampling rounds an array index with `floor(index+0.5)`;
out-of-bounds positions are refused, never clipped. Multiple requested points may
sample the same pixel. The requested path and actual sampled centres remain
distinct in the result. The default profile count is `ceil(pixel/bin length)+1`
up to the fixed budget; callers can request a smaller bounded count explicitly.

An active sourced signed XY record supplies an additional physical path axis.
Without it, distance stays pixel or `cycles/pixel`. A reciprocal path distance
is a frequency difference, **not** d-spacing. No physical value is inferred from
image brightness, frame number, a filename, or absent uncertainty. Scale changes
make the panel's old physical profile axis require remeasurement; the saved
older result remains historical. Display-only changes reuse the existing values.

Statistics and profile writes require a pre-saved `request_id`. Same ID and same
parameters recover the original object through `image_result`; unknown writes
are not replayed. `image_export` can exclusively export their numerical files,
manifest and provenance without inventing an image preview. They do not replace
the current panel image. A probe is a repeatable read of immutable data rather
than a recoverable scientific write.

## No-model panel use

Start the [researcher inspector](RESEARCHER_DATA_INSPECTOR.md), then expand
**原始数值、ROI 统计与强度剖面**:

1. Leave the pointer over the image to read an original-array sample. The panel
   reads only while this section is open, coalesces moves every 125 ms and keeps
   one query in flight. The exact object/revision/component/coordinate echo is
   checked before displaying a value.
2. Draw a rectangle and choose **统计当前 ROI**. The saved ROI is shown with its
   statistics; changing selection alone does not silently recalculate it.
3. Draw a straight line, choose a sample count and **读取当前线剖面**. The curve
   and first 200 rows use the saved numerical result. **剖面 CSV** downloads all
   samples and source/result/request references. The last saved profile is
   recoverable after browser refresh while its panel is live.

The probe reuses one read-only Python process per configured ImageWorkspace and
at most two immutable arrays within 128 MiB. It still validates original object
and data hashes. It creates neither a new process nor an object/journal entry
for each pointer request. Closing the module closes this owned worker via EOF.

## Actual validation and limits

An actual Windows Chrome session, with no model session, read a raw array sample,
requested ROI statistics, drew a line, inspected its curve and numerical table,
refreshed the curve, and downloaded CSV. The CSV and saved uint16 NPY were
independently reopened against the public synthetic TIFF; the source hash stayed
unchanged. [Actual browser screenshot](examples/researcher-inspector/profile-workspace.png)
and [browser CSV](examples/researcher-inspector/profile.csv) are included. The
example has no active physical calibration and makes no physical intensity claim.

Targeted actual HTTP → stdio MCP → Python tests additionally check hand-enumerated
asymmetric values and population variance, signed anisotropic path calibration,
explicit complex components, a held real old-frame response refused after a
frame switch, original-ID profile recovery and unmodified FFT/source arrays.
Separate actual-process checks prove worker reuse, no probe records, cache hash
validation, response identity refusal and EOF shutdown. Browser host-timer
binding is tested separately after the real browser exposed it.

This is **PASS within those scopes**, not DM, Mac, ordinary model-client or
human usability qualification. No complete Windows/Python/C++ suite or native
build was run. Thick/averaged/interpolated profiles, arbitrary comparison
composites, a multi-profile history browser and a cross-provider
`structure_compare` table remain unimplemented. The latter needs its own scoped
source/candidate linkage and does not block ROI/profile use.
