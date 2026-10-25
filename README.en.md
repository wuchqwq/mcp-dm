# mcp-dm

**Let an AI assistant work with DigitalMicrograph. Spend less time repeating GUI steps and moving data by hand.**

[中文](README.md) · [Agent setup and usage guide](README.agent.md) · [Technical reference](REFERENCE.en.md) · [Contributor instructions](AGENTS.md)

View images, crop regions and inspect FFTs in DM. Export to Python when the analysis becomes more specialized. `mcp-dm` is built around that workflow.

It connects a local Gatan DigitalMicrograph (DM) instance to MCP-capable AI assistants. Through explicit tools, an assistant can inspect image information, perform supported operations and retrieve calibrated results. You keep using DM; you do not have to write a script in its editor for every repetitive task.

**This is not another chat application or a model that decides what your images mean. It is an interface that lets an agent use DM.**

## What can you use it for?

Once connected, start with a specific task. These examples target the default Python backend on main; the experimental C++ backend supports a different set of tools.

| Your task | An example request |
|---|---|
| Understand the open data | “List the images in DM, with dimensions, data types and calibration. Do not change anything.” |
| Compare regions | “Measure intensity statistics for these two specified regions. Keep the ROI coordinates with the results.” |
| Inspect a profile or periodic signal | “Take a profile between these endpoints and inspect the FFT of this region. Flag incomplete calibration.” |
| Check a selection | “Show a preview with the proposed region overlaid, and let me check it before continuing.” |
| Continue outside DM | “Export this region with its original numerical values and calibration, then fit the data in a separate working directory. Leave the source unchanged.” |

The last example requires an agent that can work with files and execute code: **the MCP handles data handoff; an external script performs the additional calculation, with its origin made explicit.** This is not a built-in automatic fitting tool.

FFT frequency peaks are not confirmed lattice planes or phases. Whether the model can actually see a preview depends on the client; producing a PNG does not establish model vision.

## Keep your workflow. Remove the repetitive steps.

Keep inspecting data and selecting regions in DM. Delegate repeated measurements, crops and result organization to an agent. When a different scientific library is needed, export the data explicitly and continue there.

```text
Your request → Agent calls MCP → Data and supported processing in DM
                                           ↓
                              Values, coordinates and calibration
                                           ↓
                              Inspect, or continue in external Python
```

Reports and replay are optional, not mandatory steps for every measurement. Nor does every algorithm belong inside this plugin. Current data handoff covers reading, capture and export; arbitrary external-result round trips back into DM are not an implemented general capability.

The priorities are straightforward: use the intended image, do not silently change the ROI, preserve units, and never report a failed operation as a success.

## What works today?

| Path | Current scope | What to know |
|---|---|---|
| **Default on main: v0.6 Python backend** | Images and metadata, 2D statistics, profiles, FFT summaries, cropping, scientific exports, and optional capture/preview | Connects through DM's embedded Python. Some numerical operations use NumPy. Previews require a separate environment. |
| **Optional experimental native C++ backend** | Nineteen tools in this checkout: native summaries, crop, bounded arithmetic/FFT/filters, GUI rectangle/line identity, limited 1D profiles and histograms, PNG preview, visible documents and numerical handoff | Exact Windows x64 GMS **3.53.4137.0** fingerprints and per-operation dtype/size limits. NPY handoff is not native DM file saving; see the [native workflow](experiments/native-bridge/mvp/NATIVE_WORKFLOW.md). |
| **Next stage** | More general line profiles, native saving and workspace switching | See the [official-feature comparison and priorities](docs/NATIVE_NEXT_STAGE.md). Planned items are not current capabilities. |

**For a first trial, use the default backend on main.** Read the [native guide and build restrictions](experiments/native-bridge/mvp/README.md) before trying the C++ experiment. Do not use it on an unrecognized GMS build.

Existing spectroscopy and 4D-STEM interfaces are retained with narrow data-layout limits. Real EDS/EELS quantification, general 4D compatibility and reconstruction are not qualified capabilities. Test your environment with small synthetic inputs before using experimental data.

## Getting started

You need **Windows x64, DigitalMicrograph/GMS with embedded Python enabled, Node.js 18 or later**, and an MCP-capable agent client. The project does not require replacing DM or creating a separate project account.

### Ask your agent to help install it

Give an agent with local-machine tools the repository address and this request:

> Follow README.agent.md in https://github.com/wuchqwq/mcp-dm to install and connect the default DigitalMicrograph MCP. Check the environment and existing configuration first. Do not overwrite other MCP entries or upgrade GMS Python. Then verify the real DM backend and list open images without modifying experimental data.

Installation may still require your confirmation or client-side setup; not every client can perform it automatically.

### Set it up yourself

Get the code and start the default bridge from the repository root:

```powershell
git clone https://github.com/wuchqwq/mcp-dm.git
Set-Location .\mcp-dm
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup\start_bridge.ps1
```

The Node server has no npm runtime dependencies. Next, adapt the [MCP configuration example](mcp.json.example) with the absolute repository path and register it in your client. Environment checks, Codex registration, stopping and troubleshooting are in the [agent guide](README.agent.md) and [technical reference](REFERENCE.en.md).

**For previews**, create a separate external Python environment, install [requirements-preview.txt](requirements-preview.txt), and configure its interpreter path. Do not install these dependencies into the GMS-managed environment. Basic inspection and measurements do not require this optional step.

For your first request, ask: “Verify the real DM connection, then only list images and their calibration.” Configuration, tool discovery and successful host execution are separate checks.

## Before using it

**Protect the original data.** Start with copies or synthetic inputs, select the image and ROI explicitly, and export to a new path. An image ID identifies an object; it does not freeze its pixels. Do not edit the source during processing.

**The default bridge occupies DM's Python script slot.** Before running another DM Python script, disconnect clients and stop the bridge normally; restart it afterwards. Do not force-terminate DM. The native C++ path aims to avoid this persistent occupation, but currently has strict build and feature limits.

**A local connection is not a guarantee that data stays local.** The client may send previews, metadata, paths or numerical results to its model provider. Follow your laboratory's data policy when selecting and configuring that service.

**No microscope hardware is controlled.** This project is for post-acquisition work, not cameras, the electron beam, the stage or microscope optics. AI explanations are not scientific validation.

## Further reading

The [agent guide](README.agent.md) covers setup, data targeting, errors and handoff. The [technical reference](REFERENCE.en.md) preserves detailed installation commands, tool parameters and numerical conventions. Read [AGENTS.md](AGENTS.md) before changing code; see [ROADMAP.md](ROADMAP.md) for development direction.

The agent-assisted multi-version compatibility generator is an [independent proposal](https://github.com/wuchqwq/mcp-dm/pull/3), not a working automatic adapter.

Project code is licensed under the [MIT License](LICENSE). DigitalMicrograph/GMS, Gatan runtimes, vendor documentation and experimental datasets are not distributed here. This is not an official Gatan product.

Native Fourier metadata: [scientific handoff and validation scope](docs/SCIENTIFIC_HANDOFF.md).

This checkout adds [explicit result release and complete bounded numerical handoff](docs/NATIVE_LIFECYCLE_HANDOFF.md), retaining the experimental build/type/size limits. SHOW does not guarantee active-workspace visibility; native workspace activation is not implemented.

The experimental native backend can [read an explicitly identified image’s GUI rectangle](docs/NATIVE_GUI_ROI.md), [extract width-one integer horizontal/vertical profiles](docs/NATIVE_LINE_PROFILE.md), and [compute bounded native histograms](docs/NATIVE_HISTOGRAM.md). Eligible 1D results can reach DM documents and true 1D NPY/metadata, within their separate qualification scopes. Diagonal/wide profiles and general physical-intensity conversion remain unsupported. See the [GUI measurement workflow](docs/NATIVE_GUI_MEASUREMENTS.md) for explicit selection and export.
