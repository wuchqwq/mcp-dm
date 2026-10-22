# mcp-dm scope and roadmap

## Goal

Let a general-purpose agent inspect DM data, view selected images, invoke common post-acquisition operations correctly and retrieve calibrated results for further work. This repository is a tool interface, not a scientific decision-maker or a new agent application.

## Core acceptance

- A new user can connect to the real DM backend and identify the intended data.
- Each operation targets explicit data and preserves the documented coordinate, unit, dtype and no-overwrite contracts.
- A preview corresponds to the referenced input and has an explicit coordinate mapping. Display pixels never replace numerical input.
- Values, calibration, source references and failure/unknown states can be used by another tool or the user.

A complete report is an optional integration example, not the definition of a successful MCP. An agent's ability to choose a scientifically appropriate region is evaluated separately from tool correctness.

## Existing capabilities to retain

Core metadata, ROI, crop, profile, FFT and exports; bounded 2D capture and preview; existing limited spectroscopy/4D tools. Preserve documented limitations and backward-compatible tool names. Capturing fixed input is useful for multi-step tasks but unnecessary for simple queries. A live image ID is not a pixel snapshot.

The report/replay worker remains optional. Preview needs only NumPy/Pillow in an external environment. Report rendering adds Matplotlib; status/verification do not import plotting libraries. The user-facing Skill is optional and is not installed by MCP registration.

## Next steps

1. Validate current scope/preview fixes with small synthetic inputs on the target Windows/DM/client combination. Historical host passes do not certify changed code.
2. Try small independent tasks: identify an image and its calibration; view a selected capture; take a specified profile; export a calibrated crop or FFT summary. Fix concrete usability or correctness failures without expanding the platform.
3. Gather feedback from a few research users when the core is usable. Add installation polish or another operator only when actual friction justifies it.

## Deferred, not silently completed

4D-STEM development; automated crystallographic identification, strain, EDS/EELS quantification or reconstruction; complete job scheduling; atomic snapshots; generic object versioning; arbitrary-script enablement; a report platform; new chat UI or multi-agent framework.

Local loopback is not authentication. Existing filesystem permissions and data-sharing limits remain relevant; comprehensive access controls are separate work. Normal operation timeout does not prove that DM execution stopped. See docs/SCOPE_AUDIT.md for the bounded audit and remaining risks.
