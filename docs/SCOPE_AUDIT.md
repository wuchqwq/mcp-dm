# Scope-focused audit

Baseline: `d92cff64c7abeb8d8bd14c8d2b68fd89c6bd3695` on `feature/2d-analysis-loop`.
This is a bounded code/synthetic audit, not real-DM or security certification.

## Decision

The product is the DM tool interface. Reliable operations, calibration, preview
coordinates and honest errors are core. A report demonstrates composition but
must not dictate all requests. Keep existing tools and helper files rather than
create another framework, mode system, repository split or mandatory pipeline.

## Changes in this revision

| Finding | Action |
|---|---|
| README/server instructions presented the full task-A pipeline as the default | Rewrite Chinese/English positioning, simple-task examples, optional workflow and ownership boundaries; update roadmap and agent guidance |
| Preview and status loaded the report plotting stack at import time | Load Pillow only for preview and Matplotlib only for report rendering; provide requirements-preview.txt separately |
| Cropped-input profile coordinates were local but labeled source-relative | Return source coordinates and explicitly retain local coordinates/calibration frame; reuse conversion in report and verifier |
| Failed/unresolved verification exited successfully | Make the verification command return ok=false and nonzero status unless verified; retain successful status-query semantics |
| Full-resolution preview masks/float/RGB buffers ignored a small computation ROI | Scan display range in bounded tiles; sample only target preview pixels; check workspace before allocations; document thumbnail limitations |
| Raw values were plotted with unapplied physical intensity units | Label report/CSV values as raw; retain original intensity calibration only as metadata |
| Operation reuse did not include capture metadata identity | Bind normalized request identity to the validated input metadata hash as well as pixels/parameters/code |
| Skill was a plain file with no discovery metadata | Add name/description; document explicit optional reading/copying, no automatic install |

## Retained without redesign

Native ROI/crop/metadata fixes, shared numerical kernels, no-overwrite exports,
bounded capture and separate GMS/external environments. Existing tool names and
the 21-tool catalog are retained. No new 4D functionality or hardware controls.

## Remaining limits / deliberate deferrals

- A live image ID is not immutable; capture is independent only after completion,
  and concurrent source editing during capture is not made safe by descriptor checks.
- Viewing currently uses capture then preview. No new direct-live-preview tool is
  added just to rename or duplicate this path.
- Nearest-center display sampling can miss fine features. It is not antialiased
  measurement data. Review a higher-resolution/smaller region when necessary.
- Preview workspace estimates bound application display arrays, not total process
  RSS, page cache, DM memory or aggregate memory across simultaneous workers.
- Result manifests support the optional package workflow, not a universal DM job
  queue, atomic cancellation, crash recovery or exactly-once execution.
- Loopback remains local-only, not authenticated/sandboxed. Input/output directory
  authorization and same-user hostile edits remain outside this patch.
- Metadata hashes detect ordinary changes; they are not signatures or protection
  against a hostile writer replacing files while they are read.
- Real-DM compatibility, actual client image display, Skill discovery and model
  selection behavior require local acceptance. Historical tests do not certify
  this revision. Do not publish experimental inputs or private logs to prove it.

## Validation gate

Run the full Python, Node protocol and mock suites; add tests for dependency
isolation, coordinate frames, failed verification, bounded preview and operation
identity. Exercise preview and report-status queries in an external environment
without Matplotlib. Keep normal workflow configuration manual; isolated test
machinery must not enter the deliverable commit. A synthetic pass is not a host pass.
