# Multi-source images and explicit pixel tools

This feature branch adds a small opt-in tool surface for microscopy images.
It does not require a phase classifier, a report, DM Python or a running DM.
The existing v0.6 and native catalogs remain unchanged unless the image tools
are explicitly enabled. No native failure automatically selects this route.

## Select the source and computation explicitly

| Input | Selection and execution |
| --- | --- |
| Independent TIFF | `image_open` → `image_frame`, using external tifffile; currently ordinary grayscale uint16 pages only |
| DM sequence | Existing native DATASETS → FRAME → bounded READ/NPY handoff, with original native session and frame identity |
| Saved DM numerical capture | `image_open(source_kind:"capture")` independently validates the existing NPY/sidecar before copying a bounded plane; no diffraction declaration or indexing is required |

The common continuation is a saved object ID, explicit frame/ROI coordinates,
scientific values, metadata and view parameters. It is not a common hidden
computation engine: the receipts distinguish DM-native processing from explicit
external NumPy/Pillow operations. An image ID is not a fixed input until its
numerical snapshot has been saved.

## Enable without changing the default backend

Use Python >=3.10 in a separate environment, never GMS-managed Python:

```powershell
python -m venv .venv-images
.\.venv-images\Scripts\python -m pip install -r requirements-images.txt
```

For independent TIFF work, use the separate [configuration example](../mcp.images.json.example):
`DM_MCP_BACKEND=images`, an absolute `DM_IMAGE_WORKSPACE` and the external
`DM_IMAGE_PYTHON`. Only the image tools are exposed; DM is not contacted.
Alternatively, an explicit `DM_IMAGE_WORKSPACE` adds these tools alongside the
chosen Python/native catalog. It does not change how any `dm_*` tool executes.
No installer or client configuration is silently changed.

## Composable tools

| Tool | Action |
| --- | --- |
| `image_open` | Inspect TIFF page metadata or validate a saved DM capture |
| `image_frame` | Read one explicit zero-based page, retaining its uint16 values |
| `image_info` / `image_result` | Inspect an object / query a pre-saved request |
| `image_preview` | Render a scalar plane/ROI, or re-render a saved external FFT without recomputing it |
| `image_compare` | Compare 2..4 same-grid planes/ROIs with one shared gray range |
| `image_fft` | Explicit external FFT, with optional mean subtraction/Hann window |
| `image_measure` | Pixel/frequency geometry; physical geometry with an active versioned XY record |
| `image_probe` | Bounded nearest samples from the original saved array, through one persistent read-only worker; no pointer result records |
| `image_statistics` | Save ROI mean, population standard deviation, minimum and maximum; explicit FFT component |
| `image_profile` | Save a straight, one-pixel-wide nearest profile, requested/sample coordinates, calibrated path distance when available, NPY and CSV |
| `image_calibrate` | Create, revise, withdraw or explicitly attach an exact-scope XY record; preserve admitted native calibration and user revisions |
| `image_context` | Create a revision of user interpretation; legacy scale notes remain descriptive |
| `image_annotate` | Replace an overlay or update existing stable IDs, including retraction |
| `image_export` | Exclusively create scientific NPY, available PNG and provenance |

Every write action requires a request ID saved before submission. Same ID and
same parameters returns its original object; changed parameters conflict.
After cancellation, timeout or restart, query `image_result` using that ID.
Incomplete/failed records do not replay and are not reported as success. A new
request ID is a new operation, not recovery of an unknown operation.

TIFF opens stream a file hash and inspect at most 4096 page headers; they do not
decode the volume. Each selected plane is at most 4,194,304 pixels / 64 MiB
decoded storage. Source stat and full file hash are checked around frame reads.
Only the requested pages are decoded. RGB, ambiguous volumetric pages, other
TIFF dtypes and oversized sources reject explicitly. float32 sequences are a
future engineering extension, not a requirement for this uint16 workflow.

## Coordinates and missing calibration

Source rectangles are `[x0,y0,x1,y1]` half-open pixel edges, with no rounding or
clipping. Measurement points use pixel centres; x points right and y points
down. Unknown XY aspect means reported angles and Euclidean lengths are image
geometry, not physical angles/length ratios. No nm, Å or depth is inferred.

FFT uses NumPy's negative-exponent, unnormalised forward convention, explicitly
different from the qualified native DM forward convention. The mathematical
grid is `fftshift(fftfreq(N,d=1))`: cycles/pixel, DC at `floor(N/2)`, including
odd dimensions. No power-of-two padding is silently applied. Complex128 NPY is
scientific output; `log1p(abs(spectrum))` is only the display representation.
Frequency annotations map to Fourier bins and cycles/pixel, never to positions
inside the source ROI. The source ROI remains separate provenance.

User context keeps reconstruction type, data meaning, value unit, XY scale and
frame meaning/scale separate. User-provided calibration carries a source and
creates a new context revision; it never rewrites original metadata or applies
an intensity conversion. A uint16 value does not become radians. A frame scale
does not prove resolved depth. Operational real-space XY scale uses
`image_calibrate`, separately from descriptive context. It binds an immutable
record to one image or one exact opened sequence, with user statement, signed
X/Y scales, normalized length unit and unknown uncertainty unless supplied.
Distances use signed axis scales; saved FFT physical frequencies use the
original cycles/pixel divided by those scales, with no 2π. Scalar values and
complex arrays never change. Revised/withdrawn calibration requires a new
preview before exporting changed scale bars/axes; earlier exports remain
historical. See [the unified trial guide](UNIFIED_IMAGE_TRIAL.md) and
[coordinate/measurement contracts](IMAGE_ANNOTATIONS.md).

Internally validated native READ captures can activate their existing physical
axes in this same versioned record, with `source:"native_dm_capture"`; no repeated
user scale entry is needed. Original origins, signed scales, mixed-unit
conversion and crop offsets remain traceable. Incomplete or ambiguous axes
remain pixel-only. Reciprocal axes are distinct from real-space scales, and
changing a user scale cannot reinterpret an established coordinate domain. See
[native calibration admission](NATIVE_CALIBRATION_HANDOFF.md).

## Multi-turn example

1. Open a TIFF, inspect page metadata, choose explicit frames.
2. Preview the same ROI with an explicit shared range; receive MCP `image`
   content as well as object/parameter metadata.
3. When the user changes frames, ROI or gamma, reference the saved frame objects
   and create only the affected views. Old views and numerical inputs remain.
4. Request a local pixel FFT or measurement if useful. Add a separately labelled
   point/rectangle/text hypothesis. A revised annotation list replaces the old
   overlay; an empty list restores the original render.
5. Export to a new directory. Reopen NPY independently and preserve context,
   frame identity, parent history, display recipe and annotations with the output.

Annotations use rendered-image pixel coordinates, with stored centre/edge maps
to each panel's source coordinates. Comparison coordinates refer to the entire
horizontal composite. PNG resizing is display-only and is never quantitative
input. Fixed cross-frame range/gamma prevent per-frame automatic contrast from
masquerading as structural change; comparison does not imply registration.

## Revising context and an existing FFT display

Context attached to a frame, scalar view, FFT or FFT view is inherited by later
partial `image_context` updates. An omitted field retains its current value;
an explicit `null` withdraws that field, including after a preview. Original
objects and requests remain immutable. This is user-supplied interpretation,
not permission to invent physical calibration. Use the separate operational
record when the user has provided actual XY values and an explicit scope.

`image_preview` now accepts the `fft` object returned by `image_fft`, or a prior
`fft_view`. It reads the saved complex128 NPY rather than executing FFT again.
The new view preserves the exact complex values, original spectrum identity and
frequency axes. `representation` selects `log_amplitude` (the initial default),
`amplitude`, or `power` for **display only**; the scientific NPY remains complex.
Native scalar FFT captures remain scalar views, not reconstructed complex data.

For an existing scalar or FFT view, omitted `display_range`, `gamma` and
`max_size` inherit the existing recipe. To ask for a new automatic range, pass
`display_range:null`. Changing a spectrum's representation automatically
recalculates the range unless a new range is supplied, because amplitude, power
and log amplitude cannot share an implicit numerical range. Gamma and size
still inherit. Rendering always starts from numerical values, not from the
previous PNG, so adjustments do not compound on already-quantized pixels.

For example, call `image_fft` once, then `image_preview` on that result with
`gamma:2`; reference the returned view for a later `representation:"power"`
request. Each step needs its own saved request ID. Annotating and exporting the
new FFT view retain the original frequency-bin mapping and exact complex NPY.

FFT re-rendering accepts `frequency_rect` for display-only region enlargement
in the original shifted FFT bin grid; `null` restores the full spectrum.
The scientific NPY remains full and unchanged. The spatial `rect` is still
rejected on FFT views. Choose the spatial ROI before FFT. Annotated images
and saved comparison composites now accept direct
`image_preview` display revisions. Unambiguous annotations follow their source
coordinates automatically, including through resizing and FFT representation
changes. Comparison revisions keep the same ROI and saved arrays; use
`image_compare` for a different ROI. Arbitrary curves remain unsupported.
See [coordinate-bound annotations and frequency zoom](IMAGE_ANNOTATIONS.md).

## Validation and remaining boundaries

Synthetic tests independently check page reads, dtype, ROI, shared display,
hand-computable FFT bins, coordinate maps, context/overlay revision, no-overwrite
export, corruption and source protection. Actual Node stdio MCP tests require
image content, rather than accepting only a PNG path. The separately authorised
read-only TIFF trial returned images through actual MCP to Codex, accepted a
user-requested frame change and retained numerical data and parameters.

This tests Codex's image surface using a strict local stdio client. It does not
qualify every MCP client's image display, automatic tool discovery/reloading or
DM GUI visibility. Private trial inputs, IDs and numerical measurements are not
published. Detailed current results live in the private run evidence.

## Qualified native pixel continuation

On the exact fingerprint-matched Windows x64 GMS 3.53.4137.0 adapter,
`native_pixel_crop`, `native_pixel_filters` and `native_pixel_fft` now have
limited synthetic real-host qualification. Select `coordinate_mode:"pixel"`
explicitly on crop, filter, FFT and complex-component calls. Their distinct
`*_PIXEL` request identities preserve the existing default physical-mode
contract. Missing spatial units may remain unknown; origins/zero values must
be finite, signed scales finite and nonzero, and native getter formats
consistent. ABI/getter errors, unsupported types, nonfinite data and allocation
budgets still reject.

The qualified paths cover ordinary float32 and separately admitted uint32 2D
inputs. Uint32 filter/Fourier output dtype and rounding retain their existing
per-operation contract; pixel coordinates do not make integer FFTs lossless.
A rank-three uint16 sequence enters through qualified `dm_native_frame`
and its explicit, value-exact float32 working copy; uint16 is not globally
enabled for old 2D operators. Crop retains the existing source/output limits;
filters retain axes 5..256, and Fourier retains power-of-two dimensions and its
per-operation/dtype large-window gates. The shared 16 MiB/32-object budget is
unchanged. This does not enable arbitrary whole-frame dimensions or native
SaveAs.

Native pixel FFT reports mathematical `cycles_per_pixel` axes with DC at N/2.
Raw signed native calibration and the half-bin offset remain separate; no
physical frequency or pixel aspect is invented. Phase remains radians and
power remains squared magnitude, with DM's finite-precision output. READ and
NPY retain known Fourier context, processing history and frozen FRAME ancestry.
Scientific NPY is an explicit data handoff; a PNG remains display-only.

Save each side-effect request ID before submission. Same-ID QUERY/duplicates
recover the original object in the same live native session; changing coordinate
mode conflicts rather than creating a second result. STOP/host exit ends live
recovery. Independent source/value/calibration, document ownership, after-idle
release, normal exit and post-exit file checks passed in the synthetic scope.
The initial power check against a binary64-expression reference remains FAIL;
a separate fresh-request round passed its predeclared, exact stepwise binary32
reference. No tolerance was widened and no old result was rewritten.

An authorized uncalibrated uint16 sequence also completed explicit frame
selection, the same pixel ROI, DM-native FFT and REAL/IMAG export. Independently
reopened ROI values matched the source file exactly; the exported complex data
matched the native FFT object bitwise. Original source memory, raw calibration,
file identity and hash stayed unchanged, and released working objects became
invalid after host idle. This establishes the recorded native/data-handoff path,
not general mathematical Fourier accuracy on experimental images.

The saved native captures were explicitly imported into image_* tools for a
fixed-range comparison. An actual stdio MCP client received the PNG image block,
recovered the same view from a fresh client, and Codex viewed those pixels.
Display encoding is external and performs no replacement FFT or native fallback.
Ordinary native model-client setup/tool reloading and other clients remain
NOT_TESTED. Physical spacings, reconstruction-value units and frame depth still
require independently sourced calibration.

References: [tifffile](https://pypi.org/project/tifffile/),
[NumPy FFT](https://numpy.org/doc/stable/reference/routines.fft.html),
[Pillow drawing](https://pillow.readthedocs.io/en/stable/reference/ImageDraw.html).
