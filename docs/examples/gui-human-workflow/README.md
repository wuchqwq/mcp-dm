# GUI human workflow: synthetic browser evidence

These files were produced through the real Windows Chrome Image Panel and its
HTTP → stdio MCP → independent Python scientific backend. Browser gestures were
automated with Computer Use; no model session was required by the GUI. This is
not a human usability study, real-DM qualification or experimental interpretation.

- [FFT canvas and three saved results](fft-results.png)
- [Constant, uncalibrated profile](constant-profile.png)
- [Actual calibrated profile CSV](profile.csv)
- [Actual constant profile CSV](constant-profile.csv)
- [Actual current measurement CSV](measurements.csv)

The periodic uint16 fixture uses an explicitly stated synthetic scale, initially
0.02 nm per original pixel, later revised separately. Its frequencies and dragged
points are interaction controls, not material or reflection identifications.
The constant fixture contains raw uint16 values 1234 with no physical scale;
its distance axis is pixel, with no invented intensity unit. CSV samples come
from the saved scientific arrays, not PNG grayscale or interpolated values.

## Reproduce with the existing entry points

Use an independent environment with `requirements-images.txt`; do not install
dependencies in GMS Python. Create a public synthetic input with the existing
`examples/panel_workbench_fixture.py --output ABS_NEW_DIRECTORY`, or explicitly
name your own supported TIFF. The existing fixture has different dimensions from
the small acceptance controls, so do not expect identical dragged coordinates.

```powershell
node tools/researcher_inspector.mjs --workspace ABS_NEW_WORKSPACE --python ABS_EXTERNAL_PYTHON --source ABS_TIFF
```

Open the printed loopback URL and keep the process running. Set the synthetic
scale explicitly in settings, select an ROI, view it and draw a local FFT ROI.
Point to three reflections and measure them. Move one, change Gamma, undo/redo,
then use history and original-view navigation. For a spatial line, use the profile
action; for a rectangle, use statistics. Refresh, read saved samples with the
mouse/keyboard/table and download CSV. Scientific data export writes NPY and
provenance into the workspace; the paper-picture dialog downloads SVG/PNG and
`figure.json`, which can be selected again to restore its saved display recipe.

Reusing the same inspector workspace resumes its saved object. A directly reopened
ROI/FFT may have no known full-frame display recipe: **全帧（新显示）** creates
an explicitly new full-frame preview with the current calibration and neutral
spatial display. It does not claim to restore an unknown recipe or recompute FFT.

## Executed gates

| Gate | Result |
| --- | --- |
| Select A, blank ROI drag/click; coordinates and tool mode preserved | PASS |
| Both Gamma/geometry undo orders, redo, automatic numeric labels, rapid edits/selection while saving | PASS |
| Rectangle measure disabled before mark creation; valid ROI/peak/line actions | PASS |
| Saved ROI/FFT back/forward and direct reopen; spatial/FFT display separation | PASS |
| Three measurements, selective revision, mark/table selection, historical jumps | PASS |
| Separate recent profile/statistics after browser refresh; old scale/frame refusal | PASS |
| Mouse/keyboard/table samples, axes, constant and uncalibrated controls | PASS |
| Actual 1280×800 and 960×800 Chromium viewports, sidebar/tabs/results resize/scroll | PASS |
| Scientific NPY, paper SVG/PNG/recipe restore and numeric CSV, independent reopening | PASS |

Source TIFF and existing arrays stayed unchanged. Exactly one FFT was computed;
navigation, display edits and recipe restoration reused it. Its exported complex
NPY was byte-identical. Profile values/nearest indices, statistics and measurement
geometry were independently checked against original arrays and saved provenance.

Final requested six-file focused check: **100 PASS / 0 FAIL / 1 existing opt-in
SKIP**. The skipped real-render test is not counted as executed; actual browser
recipe restoration was exercised separately. The affected coordinate/panel file
also passed its four tests before the final display-name-only change. No full
Windows/Python/C++ suite or native build ran. Mac, actual DM and human usability
qualification remain **NOT_TESTED**.

Known bounds: undo/navigation are browser-session references; the two recent
numeric records belong to the live panel. They are not cross-backend-restart
multi-profile history. A long profile or narrow window uses the resizable,
scrollable results area. Historical names remain as saved; the current table and
GUI CSV use the current name only when its saved object/mark/scientific grid match.
