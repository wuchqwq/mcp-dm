---
name: dm-2d-analysis
description: Use a connected DigitalMicrograph MCP for explicit post-acquisition 2D image inspection, calibration, preview, profiles, FFT or export. Choose only the required tools; a full report is optional. Do not use for acquisition, hardware control, 4D analysis or unverified scientific identification.
---

# DigitalMicrograph tool-use guide

This is optional guidance for composing existing tools, not a required pipeline.
MCP registration does not install this directory. Read it directly or explicitly
copy it to a client-supported skill location; do not overwrite an installed Skill.

## Choose the shortest valid path

First confirm `dm_status.backend="digitalmicrograph"` and identify the intended
image with `dm_datasets`. Keep an explicit image ID for subsequent live calls;
stop if it disappears. An ID does not freeze pixels or calibration.

For metadata, call `dm_metadata` with the needed prefix and inspect `path_status`,
`complete` and `issues`. For a specified measurement or export, use `dm_stats`,
`dm_profile`, `dm_fft`, `dm_crop` or `dm_export` directly. Do not require a capture,
preview or report merely to read a value. Do not repeat questions the user already
answered. Refuse to invent calibration or alter the requested ROI.

For visual selection or fixed multi-step inputs, capture the intended bounded 2D
image/ROI once using `dm_2d_capture`, then view it with `dm_2d_preview`. Capture must
not overlap source editing; the DM API does not guarantee an atomic snapshot.
Use the image block or open the returned local PNG. A path or transported block
alone does not establish that you actually viewed the image. Preview is
nearest-center display sampling and may miss fine features: request a smaller
capture or explicit higher preview resolution when needed.

Convert preview coordinates using the returned mapping. Rectangles use original
source-pixel half-open edges; profile endpoints use original pixel centers, x
right and y down. Review a proposed overlay before a visual measurement. All
numerical work must use captured NPY or explicit live-image tools, never PNG.
Clearly distinguish live operations from operations on a fixed capture.

## Optional combined report

Only when the user needs the existing combined statistics/profile/FFT bundle,
call `dm_2d_analyze` with a reviewed capture, new result directory and unique stable
operation ID. Otherwise return the requested operation's numerical result or
calibrated export and let the agent/user choose subsequent tools.

For a report, inspect the real output files. `sampled_coordinates` are original
source pixel centers; `sampled_coordinates_local` and the profile calibration are
capture-relative. Intensities are raw pixels; recorded intensity scale/origin/unit
have not been applied. FFT samples are not identified reflections or phases.

Run `python replay.py --verify` when verification is requested or needed for this
report. Require both zero exit status and `state="verified"`; failed or unresolved
verification exits nonzero. Regeneration requires a new directory. Old bundles
retain their own scripts and are not rewritten in place.

## Failures and data sharing

After a timeout, query the exact capture/result directory with `dm_2d_result`.
Unknown is not stopped or succeeded. Never automatically repeat a side effect.
This result-query mechanism does not recover every arbitrary live DM operation.

Do not modify source files, close unrelated documents, enable arbitrary scripts
or call microscope hardware. The bridge is local, but a hosted client may send
preview images, metadata or values to its model provider. Respect the user's
sharing limits. Separate computed facts from interpretations and human review.
