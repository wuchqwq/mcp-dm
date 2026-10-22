# DigitalMicrograph MCP

[中文](README.md) · [Coding-agent instructions](AGENTS.md)

**Let general-purpose agents inspect data in DigitalMicrograph, view selected images, correctly invoke common post-acquisition operations, and retrieve calibrated results they can use in further work.**

`mcp-dm` is a tool interface to a local Gatan DigitalMicrograph (DM) instance, not another chat application or an autonomous research platform. The agent chooses methods, composes tools and explains results. This project owns data targeting, coordinates, units, operation results and honest failure states. It is **post-acquisition only**, with no camera, beam, stage or microscope-optics controls.

## Project boundary

| Layer | What is provided | What is not required |
|---|---|---|
| Core MCP | Connection/status, datasets, metadata, common numerical operations, cropping and calibrated exports | No capture package, report, Skill or external plotting stack |
| Images and data handoff | Bounded 2D copies, display previews and source-coordinate mappings | Display pixels never become numerical inputs; viewing currently uses two calls: capture then preview |
| Optional workflow example | Existing 2D report, result inspection and replay helpers | Not a mandatory analysis pipeline or a scientific decision-maker |

The goal is not to wrap every DM API or promise crystallographic identification, strain, spectral quantification or reconstruction. Existing 4D-STEM interfaces retain their documented limits; expansion is deferred. Add capabilities needed for reliable access to DM, and reuse general-purpose agents and external scientific tools for the rest.

## Start with one useful operation

Ask an agent to list open images and inspect a selected calibration, take a profile through a specified region, compute an ROI FFT, or export a new calibrated file without overwriting the source. It should first verify the real backend and an explicit `image_id`, then invoke only the needed tools. An ID binds an object, not immutable pixels; capture a separate bounded copy when a multi-step task needs fixed data.

**Do not force every request through capture, statistics, profile, FFT and a report.** Success means a usable connection, correct operations and reusable results, not automatic report generation.

```text
MCP client → Node stdio server.mjs → 127.0.0.1 TCP → Python inside DM
```

The Node server has no npm runtime dependencies. The DM bridge uses the standard library and NumPy. DM/GMS, the Gatan Python runtime, plugins, manuals, and experimental data are not distributed here. The MIT license covers this repository's code, not Gatan software.

## Validation scope

| Area | Evidence and limits |
|---|---|
| 2D STEM images | Small synthetic images passed real-host ROI, calibration, capture, preview, task-A numeric and replay checks; experimental-sample coverage remains limited. |
| EDS/EELS basics | Synthetic arithmetic, fake DM APIs and a mock MCP chain were tested. **Real EDS, EELS and spectral SI remain `NOT_TESTED`.** |
| 4D-STEM | Bounded uint8 native-stream reading and virtual detector analysis verified within a limited scope. |
| Hardware, acquisition, plugin quantification, phase reconstruction | Not provided or not validated. |

The repository distributes synthetic tests and explicitly invoked host-acceptance scripts, not experimental data. Real-host records above describe earlier behavior; they do not certify the current scope/preview changes. A new machine must validate its own DM version, data types, axis order and calibration. Tests run locally; the normal Actions workflow remains manual. Isolated hosted checks provide synthetic evidence only, not real-DM acceptance.

## 1. Prerequisites

Requires Windows x64, Gatan DigitalMicrograph/GMS with embedded Python enabled, and Node.js **18 or newer**. Bridge code is compatible with Python 3.7 and NumPy 1.18 APIs; use the Python environment supplied by Gatan for your GMS installation. Put Node on the MCP client's `PATH`, or configure its absolute executable path.

```powershell
git clone https://github.com/wuchqwq/mcp-dm.git
Set-Location .\mcp-dm
node --version
# No npm runtime dependencies; npm install is unnecessary.
```

Core connection, metadata, statistics, profiles, FFT, cropping, export and capture do not need the following environment. **Only for image previews**, create a separate Python 3.10+ environment. Do not change GMS-managed Python or NumPy:

```powershell
python -m venv .analysis-env
.\.analysis-env\Scripts\python.exe -m pip install -r requirements-preview.txt
$analysisPython = (Resolve-Path .\.analysis-env\Scripts\python.exe).Path
```
Preview needs only NumPy and Pillow. Matplotlib loads only for optional report rendering; status inspection and numerical verification do not require Pillow/Matplotlib. Preview range calculation scans bounded tiles and display buffers use the requested output resolution, not the full source size. Thumbnails may miss small features; explicitly increase resolution or capture a smaller region when needed.


DM's embedded interpreter is separate from system Python. An external `import DigitalMicrograph` is not the supported route. Do not upgrade the GMS-managed NumPy to the latest version.

If GMS is installed but its Python component is missing, inspect the offline packages supplied by Gatan:

```powershell
Test-Path 'C:\ProgramData\Gatan\Python\Miniconda3.exe'
Test-Path 'C:\ProgramData\Gatan\Python\installGMSvenv.bat'
# Run only when these are the Gatan packages from your installation.
# Writing system locations may require an Administrator command prompt.
cmd /c .\setup\install_gms_python.bat
```

The script uses those offline packages and downloads no replacement runtime. Its default environment is `C:\ProgramData\Miniconda3\envs\GMS_VENV_PYTHON`. For another GMS layout, follow Gatan's installation instructions; avoid mixing interpreters from unrelated projects.

```powershell
$gmsPython = 'C:\ProgramData\Miniconda3\envs\GMS_VENV_PYTHON\python.exe'
& $gmsPython -c "import sys,numpy; print(sys.version); print(numpy.__version__)"
```

## 2. Start the real DM bridge

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup\start_bridge.ps1
```

The launcher waits for DM initialization before starting the bridge in its embedded interpreter. The default executable is `%ProgramFiles%\Gatan\DigitalMicrograph.exe`. Override it with a parameter or `DM_GMS_EXE`. Runtime logs are written to `runtime/bridge.log` by default.

```powershell
.\setup\start_bridge.ps1 -DmExecutable 'D:\Gatan\DigitalMicrograph.exe' -Port 8765
# For a custom Gatan log location, add -GatanLogDirectory 'D:\GatanLogs'.
# Disconnect MCP clients before stopping:
.\setup\start_bridge.ps1 -Stop
```

The bridge binds IPv4 loopback only. A running bridge returns its status. A listening port with no valid response is reported as busy/unknown, and the launcher refuses duplicate injection. The launcher initializes DM and the bridge in two stages. The bridge occupies a background Python execution slot and exits after one idle hour by default; rerun the launcher afterwards.

## 3. Register with Codex or another MCP client

After installing and signing into Codex:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup\register_codex.ps1
codex mcp list
codex mcp get digitalmicrograph --json
```

This script registers MCP; it does not start DM. Inspect an existing server with the same name before changing it. The equivalent manual command is:

```powershell
$nodeExe = (Get-Command node).Source
$serverFile = (Resolve-Path .\server.mjs).Path
codex mcp add digitalmicrograph --env DM_BRIDGE_HOST=127.0.0.1 --env DM_BRIDGE_PORT=8765 --env DM_MCP_TIMEOUT_MS=600000 --env DM_MCP_ALLOW_DMSCRIPT=0 -- $nodeExe $serverFile
```

2D capture and analysis may exceed the client's default wait. Add these settings to the existing `[mcp_servers.digitalmicrograph]` table when needed; do not create a duplicate TOML table. If `disabled_tools` already exists, merge `dm_run_script` into it and preserve other disabled tools:

```toml
startup_timeout_sec = 20
tool_timeout_sec = 660
disabled_tools = ["dm_run_script"]
```

The registration script refuses to replace an existing name and does not automatically edit these timeout/denylist settings. The catalog has 21 tools; Codex exposes 20 when that denylist is applied. Without client-side hiding, both execution gates still reject arbitrary scripts. Existing desktop conversations may need an MCP restart: Settings → MCP servers → Restart. [Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)

Other clients can use [mcp.json.example](mcp.json.example). Replace `__ABS_REPO_PATH__` with the absolute repository path, such as `D:/code/mcp-dm`. The JSON example is not a Codex TOML configuration.

**Registration, tool discovery and real execution are separate checks.** Call `dm_status` in the client and require `backend="digitalmicrograph"` for real DM. `backend="mock"` is synthetic. Record PID, version, source hash and output postconditions. Timeout/cancellation stops waiting; an already dispatched operation may continue. Do not automatically retry exports or other side effects.

## 4. Tools and scientific contracts

| Tools | Purpose |
|---|---|
| `dm_status`, `dm_datasets` | Backend identity and open dataset shape, dtype and per-axis calibration |
| `dm_2d_capture`, `dm_2d_preview` | Freeze a bounded 2D working input; return an image block, local PNG path and source-coordinate map |
| `dm_2d_analyze`, `dm_2d_result` | Optional combined report / independent status query; not prerequisites for other tools |
| `dm_open`, `dm_metadata` | Open 2D data and read typed metadata; inspect `complete` and issues |
| `dm_stats`, `dm_profile`, `dm_fft` | 2D statistics, calibrated profiles and Fourier frequencies |
| `dm_crop`, `dm_export` | Independent cropped images and new-file exports with calibration/provenance |
| `dm_spectrum_info`, `dm_spectrum` | Explicit energy-axis validation and ROI spectra; real spectra unverified |
| `dm_spectrum_integrate`, `dm_spectrum_export` | Raw channel-window sums and CSV; no elemental quantification |
| `dm_4dstem_open` | Read-only index of one uncompressed uint8 4D DM4 dataset; explicit canonical axes, no whole-file OpenImage |
| `dm_4dstem_read` | Bounded native Gatan-stream read into a separate small DM image with all four calibrations |
| `dm_4dstem_virtual` | Chunked BF/ADF, total intensity, summed/mean diffraction; separate native DM outputs |
| `dm_run_script` | Arbitrary scripting, disabled by default in both Node and bridge |

- **2D ROI contract change:** statistics, FFT and cropping reject out-of-bounds, empty and noninteger rectangles. No rounding or implicit clipping is performed. Omitted `rect` means the full image only for statistics/FFT; crop requires an explicit ROI. `requested_rect` preserves the request (null when omitted), `effective_rect` records the used bounds, and the legacy `rect` result remains available.
- Crop keeps native `ImageClone` and identifies its result by a fresh per-operation internal token and a new image ID, never a user display name or newest-window fallback. Missing/duplicate tokens fail without recalibrating unrelated images. The fixed synthetic path passed on the current DM host; this does not imply support for every version or sample, and is not an atomic pixel snapshot or security sandbox.
- Rectangles are zero-based `[x0,y0,x1,y1]`, with exclusive upper bounds. NumPy image shape is `[y,x]`. DM dimension 0 changes fastest; C-order NumPy's final axis changes fastest.
- Use `coordinate[i] = calibrated_value_at_pixel_zero + i * scale`. A raw DM `Origin` may be the pixel index of physical zero, not a physical offset. Cropping shifts the physical zero by `start * scale`.
- Statistics use finite values, float64 and population standard deviation (`ddof=0`); zeros are included. Mark incomplete scans explicitly before interpreting whole-frame summaries.
- FFT subtracts the mean, with no window or padding. A Fourier component alone does not establish a lattice plane, phase or atomic spacing.
- Spectra require an explicit NumPy energy axis and eV/keV units. Windows select channel centres with `low <= E < high`. Integration sums channel values without multiplying by bin width. Integer accumulation has a `2**53` precision guard. Background fitting, drift correction, thickness and elemental quantification are not established.
- The 4D core requires explicit `[scan_y,scan_x]` and `[q_y,q_x]` axes. Circular/annular windows select pixel centres with `r_inner <= r < r_outer` in matching reciprocal units. Clipped outer circles are rejected by default. Brightness and filenames do not establish HAADF; mrad conversion is never assumed.
- `dm_open` rejects whole-document opens over 512 MiB. Use the separate 4D route for large files: seek-only header indexing followed by bounded native Gatan read-only streams, budgeting memory before allocation and reads.

## Metadata subtree selection

`dm_metadata(prefix=...)` resolves the path before traversing the selected subtree, whose root has depth zero. Unrelated sibling values are not read. Both `/Acquisition/Instrument` and the existing slashless shorthand are accepted. Lists use zero-based indices; escape literal `/` and `~` as `~1` and `~0`. Omitted/empty prefix selects the root; `/` selects an empty-name tag. Whitespace and trailing slashes are no longer silently removed.

Check `path_status`: `found` establishes existence, not successful/complete value decoding; still check `complete` and `issues`. `not_found` means confirmed absence. `unavailable` means resolution was blocked by lookup limits, unreadable labels or ambiguity, not absence. Completeness applies only to the requested subtree. Lookup and subtree traversal have separate node budgets; paths have at most 64 segments. Type/size introspection failures stop before guessing a native getter.

Synthetic/fake-DM regressions and a fixed synthetic tag-tree acceptance passed on the current DM host. Native getter failure/crash injection remains **NOT_TESTED**. See [ROADMAP.md](ROADMAP.md) for current scope.

## Optional example: 2D report and replay

This is an existing composition example, not the default MCP workflow. Stop after preview when viewing is enough; use individual measurement tools for simple tasks. Only report generation needs the additional plotting dependency:

```powershell
.\.analysis-env\Scripts\python.exe -m pip install -r requirements-analysis.txt
```

`dm_2d_capture` resolves the current front image once when `image_id` is omitted, or uses an explicit ID. Optional `rect` is a strict source-pixel ROI `[x0,y0,x1,y1)`; the output directory must be new. Shape, scalar dtype and memory budget are checked before reading. Preview and calculations use the saved NPY and calibration, so later front-window changes do not change the input. DM provides no atomic pixel-plus-calibration snapshot: do not edit the source while capture runs. Oversized captures fail instead of shrinking silently.

`dm_2d_preview` returns an MCP PNG image block, a local PNG path, display range and preview-to-source pixel/edge mappings. It can overlay a source-coordinate ROI and profile strip. Display uses a linear min-max stretch over finite values; constant images are mid-gray and NaN/Inf are magenta. Preview PNGs are for visual review only, never scientific export or computational input. Confirm the client actually displays the image block; otherwise open the returned path. ROI edges are half-open; profile endpoints are pixel centers.

Example arguments, in order:

```json
{"output_dir":"C:/analysis/capture-001","image_id":1234}
{"capture_dir":"C:/analysis/capture-001","roi":[20,30,180,150],"profile":{"start":[20,90],"end":[179,90],"width":1}}
{"capture_dir":"C:/analysis/capture-001","result_dir":"C:/analysis/result-001","operation_id":"analysis-001","roi":[20,30,180,150],"profile":{"start":[20,90],"end":[179,90],"width":1}}
```

Call `dm_2d_capture`, `dm_2d_preview`, then `dm_2d_analyze`. The analysis bundle contains captured NPY and calibration, statistics/profile JSON, profile CSV, full FFT magnitude NPY and peak/frequency JSON, figures, parameters, manifest, Markdown report and `replay.py`. Run `python replay.py --verify` to recompute and compare numeric results using the manifest tolerance, or `python replay.py --output NEW_EMPTY_DIRECTORY` to create another bundle. After a timeout, query `dm_2d_result` first; `unknown` does not mean the operation stopped, so do not retry automatically.

FFT requires finite input and does not impute NaN/Inf. A frequency-grid peak is not an identified reflection, plane or phase. See the user workflow [Skill](skills/dm-2d-analysis/SKILL.md). The MCP does not upload captures; depending on the client and selected model service, previews, selections, calibration and values may be sent to that service.

## 4D-STEM examples and limits

A file `dataset_id` is separate from a native `image_id`. First call `dm_4dstem_open` to obtain the dataset ID. The native route requires NumPy order `[scan_y,scan_x,q_y,q_x]` and explicit `scan_axes=[0,1]`, `detector_axes=[2,3]`. The file must have exactly one 4D scalar dataset; only uncompressed uint8 is currently supported.

Example MCP arguments, replacing the file path and returned dataset ID with local values:

```json
{"path":"C:/data/example.dm4","scan_axes":[0,1],"detector_axes":[2,3]}
```

For a small `dm_4dstem_read` tile:

```json
{"dataset_id":"4d-1","scan_bounds":[[0,2],[0,3]]}
```

Example `dm_4dstem_virtual` arguments follow. Choose the centre/radii from returned reciprocal calibration and the actual diffraction pattern. These example values assume `1/nm` and a fully contained circle; they are not recommended hardware collection angles:

```json
{"dataset_id":"4d-1","scan_bounds":[[0,16],[0,16]],"chunk_patterns":128,"detectors":[{"label":"BF","center_q":[0,0],"r_inner":0,"r_outer":0.5},{"label":"ADF","center_q":[0,0],"r_inner":1,"r_outer":4}]}
```

A tile read is capped at 256 scan positions and 16 MiB. One virtual calculation is capped at 8,192 scan positions, with at most 128 diffraction patterns per native read. Split large scans into nonoverlapping batches and assemble by original bounds/calibration. Combine summed diffraction and sample counts before computing a global mean; do not equally average means from unequal batches. Native outputs are returned in `images` and can be exported to new files with `dm_export`.

The basic bounded native-read, axis-calibration and virtual-detector export chain has been verified.

**Unverified:** whole-document native `OpenImage` loading of large DM4 files, built-in BF/ADF plugins, other compression/packed types/dtypes/axis layouts, experimental detector-angle/HAADF correspondence, COM/DPC and phase reconstruction. Real EDS/EELS/spectral SI remain `NOT_TESTED`.

## Exports and source preservation

Sources are read-only; in-place overwrites are forbidden. NPY preserves dtype/shape, with calibration in a sidecar. Scientific TIFF is uncompressed single-channel classic TIFF with dtype preservation and calibration in its description, Gatan axis tags and sidecar. Check numerical values and calibration after export. Reject files exceeding classic TIFF format limits, unknown types and incompatible units explicitly.

DM3, other GMS/detector types and new format combinations need separate acceptance. CSV/TXT uses exact integer decimal values or 17 significant float digits. Scientific PNG intensity export is undefined; `dm_2d_preview` PNG is display-only. Scientific exports and sidecars require new paths and record source, processing history, writer and SHA-256.

An arbitrary-script switch is not a hardware sandbox. Keep `DM_MCP_ALLOW_DMSCRIPT=0`. The project provides no remotely exposed bridge or acquisition tools.

## 5. Synthetic tests: no DM or experimental data required

Use an external Python 3.10+ virtual environment for the complete synthetic suite, separate from GMS:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_*.py' -v
node --test
$env:DM_TEST_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
node selftest.mjs
```

The mock self-test uses an ephemeral loopback port and synthetic arrays, without connecting to DM. `DM_TEST_PYTHON` can select an existing interpreter; otherwise `python` is resolved from `PATH`. Core code remains compatible with Python 3.7/NumPy 1.18. The independent TIFF test needs `tifffile`; do not upgrade GMS to install it. The optional workflow contains synthetic checks only and cannot prove real DM, real spectroscopy or a fresh machine's installation.

## Contributing

Read [AGENTS.md](AGENTS.md). Add independent numerical oracles or appropriate protocol tests. Separate `PASS`, `FAIL` and `NOT_TESTED`; mock success must not expand claims about instrument support. Before submitting, run relevant tests and `git diff --check`, then inspect the staged files for data, generated images, personal absolute paths, logs and credentials. Do not upload Gatan manuals/binaries or readers with incompatible licensing.

## Optional Skill and compatibility

`skills/dm-2d-analysis/SKILL.md` is optional guidance, not installed by MCP registration. Ask an agent to read it directly, or copy the whole `dm-2d-analysis` directory into the working project's `.agents/skills/` for Codex local discovery. Inspect any existing same-name directory first; do not overwrite it. [Official Skill documentation](https://developers.openai.com/codex/skills/)

Tool names and the 21-entry catalog are retained; no new mode flag is required. In optional reports, `sampled_coordinates` now uses original-image coordinates and `sampled_coordinates_local` retains capture-relative coordinates. Intensities are explicitly raw pixel values; intensity calibration is retained as metadata, not applied. `replay.py --verify` exits nonzero for failed or unresolved verification. Existing bundles keep their own replay code and are not rewritten. New real-DM/client behavior still needs separate acceptance. See [ROADMAP.md](ROADMAP.md) and the [scope audit](docs/SCOPE_AUDIT.md).

## General-client candidate (D0 → local P0)

The core MCP does not depend on Codex. For previews use [mcp.preview.json.example](mcp.preview.json.example); [mcp.json.example](mcp.json.example) remains the core-only configuration. Replace all absolute-path placeholders and merge one server entry without overwriting other client settings.

[Local client acceptance](docs/CLIENT_ACCEPTANCE.md) provides official WorkBuddy configuration references, two manually created synthetic images and short tasks. Start a fresh session without the optional Skill, source-code reading or substitute analysis scripts. Measure whether tool descriptions alone are usable; record Skill-assisted retries separately.

D0 covers code, synthetic regression and delivery readiness only. Real DM, WorkBuddy image rendering, model vision and actual operations still require local P0 acceptance. The bridge serves one persistent client connection at a time: disconnect other MCP clients first. Busy/unknown must not trigger DM restarts or duplicate bridge injection. See [D0 handoff](docs/D0_HANDOFF.md).
