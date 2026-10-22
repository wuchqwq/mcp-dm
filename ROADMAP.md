# mcp-dm roadmap

The goal is a reliable post-acquisition analysis interface for general-purpose agents. The project remains an MCP bridge, not a separate chat product or agent framework.

## Current state

- Strict 2D ROI validation, crop-result ownership, and bounded metadata-subtree lookup are included from the current mainline baseline.
- The 2D task-A path now captures one bounded image/ROI and calibration into a new local package, previews it with source-coordinate mappings, and computes statistics, a profile, and a full FFT from that same capture. Reports and replay inputs are stored with hashes in a new result directory.
- The current DM host passed fixed synthetic ROI, calibration, metadata, capture, preview transport, front-window-switch, numeric-output and replay checks. This is limited synthetic-host evidence; it does not establish support for every DM version, image type, or experimental dataset.
- Real EDS/EELS and spectral SI remain `NOT_TESTED`. Native getter fault/crash injection and the live Codex UI's image display/agent visual-selection loop remain `NOT_TESTED`.
- 4D-STEM implementation was not changed by this task. Existing 4D evidence is bounded to its documented format/layout; no new 4D support is promised here.

## Next work

1. Review and use task A on a representative user-owned 2D image, with no source edits during capture. Check calibration, the displayed selection overlay, output package, and replay on the target Codex client. Do not publish the data or report without consent.
2. Address only compatibility or workflow failures found in that review. Keep failure records and rerun the same numerical/source-invariance checks after fixes.
3. After the 2D workflow is independently usable, decide whether to prepare a small external-user trial. Installation polish, a doctor command, compatibility matrix, and broader security work remain separate decisions.
4. Revisit 4D task B later: data-quality checks, mean diffraction, virtual BF/ADF and mask review require independent end-to-end acceptance. Preserve bounded reads and do not expand dtype/layout support without evidence.

## Deferred

A dedicated agent framework, multi-agent orchestration, new chat UI, default arbitrary DM-Script access, full DM4 reader, general object-version database, and unverified EDS/EELS quantification, crystallographic identification, strain, ptychography or phase-reconstruction claims.