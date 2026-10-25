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
`DM_IMAGE_PYTHON`. Only the eleven image tools are exposed; DM is not contacted.
Alternatively, an explicit `DM_IMAGE_WORKSPACE` adds these tools alongside the
chosen Python/native catalog. It does not change how any `dm_*` tool executes.
No installer or client configuration is silently changed.

## Composable tools

| Tool | Action |
| --- | --- |
| `image_open` | Inspect TIFF page metadata or validate a saved DM capture |
| `image_frame` | Read one explicit zero-based page, retaining its uint16 values |
| `image_info` / `image_result` | Inspect an object / query a pre-saved request |
| `image_preview` | Render a full plane or half-open pixel ROI with a display recipe |
| `image_compare` | Compare 2..4 same-grid planes/ROIs with one shared gray range |
| `image_fft` | Explicit external FFT, with optional mean subtraction/Hann window |
| `image_measure` | Pixel-centre displacement, pixel distance and image-coordinate angle |
| `image_context` | Create a revision of sourced user interpretation/calibration |
| `image_annotate` | Create a new overlay revision; replace or retract annotations |
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
does not prove resolved depth. These first tools report pixel measurements;
applying supplied physical scales to measurements is a separate future feature.

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

Native `coordinate_mode:"pixel"` has separate `*_PIXEL` wire identities and
capabilities for crop/filter/Fourier. The implementation and offline substitutes
preserve the old physical-mode contract, exact ABI, numeric-calibration safety,
dtype, size and ownership checks. **Native pixel qualifications remain disabled
pending their own synthetic real-host trial.** The existing loaded DLL must not
be overwritten. An offline PASS does not admit a native call. Current numeric
native calibration requirements are a remaining engineering limit, not a
scientific need for a physical ruler.

References: [tifffile](https://pypi.org/project/tifffile/),
[NumPy FFT](https://numpy.org/doc/stable/reference/routines.fft.html),
[Pillow drawing](https://pillow.readthedocs.io/en/stable/reference/ImageDraw.html).
