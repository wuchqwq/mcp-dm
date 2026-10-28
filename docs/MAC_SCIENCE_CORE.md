# Cross-platform Microscopy Core: Windows / macOS / Linux (first extraction slice)

This is the **default DM-free MCP provider on Windows, macOS and Linux**. It
requires neither DigitalMicrograph nor a Gatan SDK on any OS. It reuses the repository's already-tested
`image_*`, `image_panel_*`, and optional `structure_*` science providers,
their immutable objects, coordinate/calibration contracts and recovery journals.
It does not start DM, import a Gatan runtime, or silently execute a failed
`dm_*` operation with NumPy. `server.mjs` remains the compatible DM entry.

**Extraction stage:** this entry point and its composition graph are independent
of DM, but source files still live together in this repository for now.
This is not yet a physically separate GitHub repository or packaged desktop app.
When extracting to a new repo, move the portable modules and their tests without
forking their science logic or binding the new repo to a private DM ABI.

## Set up on macOS / Linux

Requires Node.js >=18, Python >=3.10 and Codex CLI (for the commands below).
Use a separate Python virtual environment, **never** the GMS-managed interpreter.
From a clean checkout:

```bash
git clone https://github.com/wuchqwq/mcp-dm.git
cd mcp-dm
python3 -m venv .venv-science
source .venv-science/bin/activate
python -m pip install -r requirements-images.txt
```

Check `codex mcp get microscopy-core` first: **do not overwrite** an existing
server. Once absent, while still in the repository root, register:

```bash
codex mcp add microscopy-core \
  --env "MICROSCOPY_PYTHON=$PWD/.venv-science/bin/python" \
  --env "MICROSCOPY_IMAGE_WORKSPACE=$HOME/.microscopy-core/images" \
  --env "MICROSCOPY_CONTEXT_WORKSPACE=$HOME/.microscopy-core/contexts" \
  -- node "$PWD/science-server.mjs"
codex mcp list
```

Open a new Codex session/refresh the MCP list, verify `microscopy-core`
and `image_open` / `image_frame` / `image_fft` / `image_panel_open`.
`image_panel_open` needs the absolute Python interpreter above. The local
panel is a separately opened loopback browser window; it does not by itself
send mouse edits to the model. Do not treat tool discovery as a successful
image open or a model-visible image.

For optional CIF/XYZ / ASE / diffsims analysis, install
`requirements-structure-tools.txt` into the independent environment, then
add **both** of these env entries to the same MCP server configuration:

- `MICROSCOPY_STRUCTURE_WORKSPACE=$HOME/.microscopy-core/structures`
- `MICROSCOPY_STRUCTURE_PYTHON=<absolute .venv-science/bin/python>`

Do not pre-enable these routes if dependencies are missing. The structure
worker still validates supported formats and data. Optional
`MICROSCOPY_EXECUTION_OBSERVABILITY=1` exposes transient execution observations;
`MICROSCOPY_PANEL=0` disables the local panel. Named, revision-aware analyses
require `MICROSCOPY_CONTEXT_WORKSPACE`, as configured above.

## Set up on Windows **without** DigitalMicrograph

Windows does **not** require DM for this workflow. Install Node.js >=18,
Python >=3.10 and Codex CLI, then run in PowerShell from an ordinary user
environment. `py -3` is the standard Python launcher when installed; otherwise
use the path to your own Python >=3.10 interpreter.

```powershell
git clone https://github.com/wuchqwq/mcp-dm.git
Set-Location mcp-dm
py -3 -m venv .venv-science
& .\.venv-science\Scripts\python.exe -m pip install -r requirements-images.txt
$python = (Resolve-Path .\.venv-science\Scripts\python.exe).Path
$server = (Resolve-Path .\science-server.mjs).Path
$images = Join-Path $env:USERPROFILE '.microscopy-core\images'
$contexts = Join-Path $env:USERPROFILE '.microscopy-core\contexts'
```

First check `codex mcp get microscopy-core` and **do not overwrite** a
pre-existing registration. Only if absent, run:

```powershell
codex mcp add microscopy-core `
  --env "MICROSCOPY_PYTHON=$python" `
  --env "MICROSCOPY_IMAGE_WORKSPACE=$images" `
  --env "MICROSCOPY_CONTEXT_WORKSPACE=$contexts" `
  -- node "$server"
codex mcp list
```

This is the same independent image/Panel/optional structure provider, not a
Windows-specific DM mode. The scientific capabilities and input limitations are
identical across operating systems; availability of Python wheels and interactive
client approval/rendering still need platform-specific acceptance.

## Final ownership: two independent MCP projects

**Science core is the primary product, regardless of operating system.**
This checkout is transitional; the intended physical repository split is:

| Project | Owns | Installation requirement |
| --- | --- | --- |
| `microscopy-core` (future independent repository) | `image_*`, Image Panel, `structure_*`, AnalysisContext, execution coordination, generic scientific Skills, scientific datasets and provenance | Windows/macOS/Linux; **no DM required** |
| `mcp-dm` (existing repository) | `dm_*`, DM Python/C++ adapters, version/ABI/capability qualification, host lifecycle and data handoff | Only needed on a Windows host with DigitalMicrograph; **optional**, independently usable |

After extraction, register them as **two peer MCP servers** in the chosen Agent
client, not as two mutually dependent Python packages. Without `mcp-dm`,
`microscopy-core` must still open/analyze/export a supported TIFF and run
optional CIF/diffraction comparison. Without core or Skills, the DM provider
must still expose its qualified DM tools. When both are enabled, hand off only
versioned numerical captures/manifests with explicit axes, units, source hashes,
request identity and provenance; never silently substitute a different processing
engine after an unsupported native call.

Do not import `mcp-dm` internal `bridge/` or `experiments/` modules from the
new science repository. Likewise, `mcp-dm` must not depend on the new science
repository. Any tiny transport/MCP facade code required by both should use
a standalone dependency or separately owned small protocol implementation,
not import paths crossing repository boundaries. Preserve legacy public
`image_*` and `structure_*` paths during a stated compatibility period,
then remove their old duplicated implementation once the standalone core is
installed and verified.

On a Mac, a future connection to a **remote Windows DM** host requires an
explicit, secured remote transport / Agent host. Do not expose the local-only
Python TCP listener or Windows Named Pipe directly on a network. Neither the
first extraction PR nor this document implements remote DM access.

**Current status:** `science-server.mjs` is the OS-neutral entry point but is
still located inside `mcp-dm`. A new `microscopy-core` GitHub repository has
not yet been created; this is the accepted target split, not a completed migration.

## First scientific task

Tell Codex: "Read this local multi-page uint16 TIFF without changing it.
Show frame 1 in the Image Panel. I'll select a ROI, then do a local FFT and
compare the selected peaks." `image_frame.frame_index` is zero-based.
After drawing, explicitly say "continue" so the Agent calls
`image_panel_current`. Ask to export to a **new** directory: output includes
scientific NPY, view PNG when available, and provenance. Existing data is not
overwritten. Physical calibration is only used when a sourced, scoped record
is verified or supplied; absent scale stays in pixel/cycles-per-pixel units.
See `docs/CODEX_MICROSCOPY_QUICKSTART.md` for the exact interactive flow.

The current native input is a supported uint16 TIFF or validated schema-1
capture; **arbitrary DM3/DM4, EELS/EDS, 4D data and reconstruction are not
admitted by this first entry point**. RosettaSciIO can independently parse many
DM3/DM4 files, but its coverage is incomplete; a reviewed conversion/reader
adapter is a separate task, not a hidden import path.

For a quick catalog-only check (no Python worker or DM):

```bash
node --test tests/science-server.test.mjs
```

Scientific end-to-end tests require the separate Python dependencies and
suitable synthetic TIFFs; each platform's Codex interactive usability and real specimen
file compatibility must be tested on the actual machine.
