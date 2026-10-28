# Microscopy annotations and figure export

The Image Panel keeps three related layers separate:

1. **Scientific geometry:** saved source/frequency anchors, ROI and line endpoints,
   measurements, calibration and confirmation state. Scientific arrays and old
   versions remain immutable.
2. **Annotation presentation:** a small optional `presentation` field on an
   existing annotation stores its symbol, category/layer and independent label
   text, offset, font, visibility, leader and pinned position. Moving a label
   never moves a scientific anchor or triggers measurement.
3. **Figure layout:** the preset, visible layers, legend, sourced scale bar,
   panel letter and output size are a reloadable figure recipe.

This extends the existing annotation contract; it adds no scientific database,
chat interface or new FFT engine. Existing `image_panel_open/current/show`,
original-request recovery, draft protection and twin feedback remain available.
See [opening the local panel](LOCAL_IMAGE_PANEL.md).

## Work on the canvas

Select **Real-space**, **FFT / Diffraction** or **Multi-domain** from the preset
control. Real-space favors thin ROI/measurement lines and short labels.
Diffraction uses small hollow peak circles and restrained indexing. Multi-domain
uses both shape and color: A cyan circles, B orange squares, shared double
circles and neutral unexplained diamonds. Categories are independent of color
and of confirmation; changing a preset never confirms an interpretation.
Experimental and simulated A/B layers can be viewed separately or together.
Unexplained reflections remain visible when changing these layer filters.

In **Analysis Mode**, drag the symbol or endpoint handle to revise scientific
geometry; drag its text to change only the label offset. A manually moved label
becomes pinned. Labels and geometry have separate visibility controls. Release
saves an immutable sparse edit automatically, with local changes retained on a
save failure. **Arrange labels** tries a short deterministic list of nearby
positions, respects pinned labels and saves presentation updates together. It
does not adjust peak positions; crowded noncritical text can be hidden until
hover/selection. Leaders point to the actual anchor.

Numeric labels explicitly linked to a saved measurement are hidden while their
geometry changes, then refreshed from the existing measurement tool. If the new
result lacks a trustworthy physical unit, the old numeric label stays hidden.
Independent label movement does not remeasure. Free text is not independently
verified metrology; entering a spacing or HKL does not establish its validity.

**Figure Mode** hides edit handles and selection aids and locks scientific
geometry. Labels remain draggable for final layout. The mode changes neither
measurement results nor `hypothesized`/`user_confirmed` authority.

## Crystallographic text

Use `(1 -1 1)`, `{1 -1 1}`, `[1 -1 0]` and `⟨1 -1 0⟩` (or `<1 -1 0>`) to
retain plane/family/direction distinctions. Negative indices use real editable
SVG overlines. Space-separated indices support multiple digits; compact
three/four-index forms assume single-digit components. `g1`, `g_1` and `g_{1}`
render as g₁; `d_(1 -1 1)` uses a subscript index group.

The narrow crystallographic shorthand also accepts `$...$` delimiters,
`\bar{1}`, `\overline{1}` and `\langle`/`\rangle`. It is not a general LaTeX
renderer. Unknown math commands are not typeset. No HKL is inferred: unindexed
points use g labels or numbers, and proposed indices retain their hypothesis
status. SVG text is escaped and remains text/tspan content, not a raster label.

## Save, export and reopen

Open the figure options, choose **single column 85 mm** or **double column
180 mm**, then export. The default text starting point is 8 pt; output PNGs
carry 300 dpi metadata. The local download contains four files:

| File | Contents |
| --- | --- |
| `clean.png` | Clean scientific rendering; when enabled, the legend footer is blank here. |
| `annotations.svg` | Transparent editable text, circles, lines, leaders, legend, panel letter and valid scale bar. |
| `annotated.png` | The matching combined image and annotations. |
| `figure.json` | Source/render references, exact scientific identity, saved presentation and layout preferences. |

All outputs share one viewBox/mapping, including any legend footer below the
image. The original scientific pixels are not vectorized. PNG enlargement adds
no measured resolution. Physical scale bars reuse the existing calibration
tool's 1/2/5 length choice; absent/withdrawn calibration produces no physical bar.
Saved FFT coefficients are reused, not recalculated for export. The ordinary
scientific export remains available for NPY and request/provenance records.

Keep the original image workspace. Reopen the saved source version and load
`figure.json` in the figure options to continue editing. Import checks exact
anchors, frame/grid/panel mapping, calibration and confirmation states before
queuing presentation-only updates. It cannot import foreign scientific anchors
or change confirmation. The recipe is not a self-contained replacement for the
original scientific workspace.

The file input and the collapsed paste-recipe fallback use the same checks.
Recipe loading replaces the saved presentation exactly, including removal of
later symbol overrides; ordinary MCP sparse style patches still merge omitted
fields. The transport-only `presentation_replace` flag is never stored as science.
Publication styling is drawn by the Panel SVG layer and figure exporter. The
existing MCP annotation preview PNG continues to use its legacy raster renderer;
the saved presentation metadata accompanies the scientific object.

## Reproduce the three inputs

In the independent analysis environment with `requirements-images.txt` and
`requirements-structure-tools.txt` installed, use a new absolute output folder:

```powershell
python examples/publication_annotation_fixture.py --output C:\analysis\publication-demo
```

The generated `fixture.json` lists each case's workspace and object. Open one
with the existing tool or CLI:

```powershell
node tools/image_panel.mjs --workspace WORKSPACE_FROM_MANIFEST --python ANALYSIS_PYTHON --object OBJECT_FROM_MANIFEST
```

The command prints a private loopback URL; open it locally and keep its token
private. An optional `--twin-revision` points to an existing immutable synthetic
#42 `revision.json`; otherwise the script reproduces that bounded scientific
recipe first. No private image is required or included.

## Executed browser checks

All three cases were opened in the real local browser and exported as four-file
ZIPs. Independent ZIP CRC, XML and Pillow reads confirmed matched PNG dimensions,
editable SVG text, 85 mm SVG width and approximately 300 dpi PNG metadata. Source
TIFF hashes remained unchanged. The FFT has 16 measured peaks, 12 visible in its
local crop; the other four remain saved outside that view.

The real-space endpoint drag changed the first measured distance from 0.320 nm
to 0.5177682662 nm, then 0.3498994138 nm. Old values were hidden during revision,
and the new label references the actual new measurement record. Separate text
drags retained the exact endpoints and measurement reference, including in
Figure Mode. The final label was moved clear of the sourced 2 nm scale bar.

The FFT label drag pinned its position; arrange-labels saved the remaining
layout together. A later diamond override was removed by reloading the exported
recipe through the browser paste fallback: all 18 presentations, anchors and
confirmation states matched the export, with the exact camera transform retained.
The host file-chooser automation did not return an event, so native file-picker
acceptance is unqualified here; the fallback exercised the actual UI and backend.

Twin layer filtering showed 15 experimental markers, 9 for candidate A or B
(8 simulations plus the unexplained point), and 31 in overlay. The unexplained
reflection remained visible. Figure legends export below the image rather than
covering reflections. All these interpretations remain `hypothesized`.

The executed inputs contain:

- **A:** a calibrated periodic texture, two ROIs, a descriptive synthetic
  boundary and two actual tool measurements of **0.32 nm / 0.48 nm**. Numeric
  labels link to those measurement records.
- **B:** an actual saved FFT of eight generated cosine components, **16 observed
  maxima**, 16 tool measurement records and two vectors beginning at mathematical
  DC. A local frequency crop does not redefine that origin.
- **C:** the saved two-domain synthetic diffraction recipe: **6 A-only, 6 B-only,
  2 shared and 1 unexplained** observations, with separate simulated A/B layers.
  All searched points are search evidence, not independent validation. Domain
  allocation and indices remain hypotheses; this input does not identify a
  researcher's material.

Source TIFF hashes were checked unchanged after generation and tool execution.
These are synthetic interaction/geometry cases, not real TEM image-formation,
experimental intensity or unique phase qualification.

## Current limits

Layout uses finite local candidate positions, not a global optimizer. PDF,
inset composition and full LaTeX are outside this version. Dense labels still
need researcher judgment and occasional manual positioning. Figure recipes
require the original workspace. Native DM/GMS, ABI, scientific kernels and the
full Windows/Python/C++ regression are outside this UI validation scope.


## Closeout correctness fixes

An endpoint save snapshots the annotation ID, saved anchor/panel, calibration,
confirmation state and local geometry revision. Remeasurement uses that saved
selection and the current saved scientific object, never the later global
selection. Results are accepted only while that annotation revision and its
measurement binding remain valid. Editing another mark stays available. Old
numeric labels remain hidden until a matching tool measurement succeeds.
Unknown replies retain edits; recovery queries the original journaled request
ID rather than submitting a replacement. Measuring a saved spatial view uses
its existing measurement-operand resolution, without extra context/calibration
writes before measurement. Label-only edits retain the measurement reference.

Loading figure.json first checks source, grid, calibration, exact anchors and
confirmation states. It verifies the original saved display version, restores
explicit Gamma/range and domain-specific display controls through image_preview,
and only then replaces presentation metadata. Missing or altered provenance is
refused. A new local draft or queued Agent result blocks late restoration.
No FFT or scientific array is recomputed. Pixel comparisons decode PNGs rather
than treating encoder metadata as scientific differences. Recipes need their
original workspace and complete display controls; legacy incomplete recipes
must be re-exported from their saved source version.

The synthetic twin fixture explicitly selects its existing Cu FCC [1,-1,0]
comparison. Explorer rank does not establish researcher selection or extend
the conventional monatomic FCC twin scope.
