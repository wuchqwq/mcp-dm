---
name: microscopy-router
description: Choose composable microscopy observation, revision and crystallography tools for an ongoing research question, while keeping DM and external computation explicit. Use when a task crosses these domains; simple tool calls need no workflow session.
---

# Choose the next useful observation

The host Agent chooses the scientific strategy. These tools do not require a
fixed input-to-phase pipeline, an installed Skill or an analysis session.

Inspect the client's actual tool catalog before choosing a route. `dm_*` uses
the explicitly selected DM backend; `image_*` works on fixed scientific image
objects, including independent TIFF; `structure_*` reads structures and performs
external ASE/diffsims work. A failed native call never authorizes an external
replacement. A registered native tool does not qualify another GMS build/dtype.

Continue from the researcher's selected half-product rather than starting over.
When a user supplies a local TIFF path, open it and retain its IDs yourself; do
not ask the researcher to type internal IDs, request IDs or tool JSON. For an
interactive task, give them the loopback URL returned by `image_panel_open`.
After “look here” or “continue”, read `image_panel_current`: this is the actual
selection, not a cue to infer coordinates from the preview. A single live panel
may be resolved without an ID; if several are open, use the retained panel ID
instead of selecting by recency. The panel does not automatically wake Codex.

Bind the exact image/frame/ROI, scientific grid and reference structure. Reuse a
current saved analysis when one is selected; historical review stays attached
to its old immutable evidence. A live DM edit requires a new capture, never an
old request query. Do not guess the newest window or globally newest object.
When using AnalysisContext, retain the revision read before work. Scientific
providers persist their results first; advancing current references is a separate
CAS step. A lost CAS preserves a historical proposal, not permission to promote
it blindly against a newer revision or roll back another provider's result.
When the optional tools are enabled, `analysis_read` selects current or explicit
historical references. `analysis_create` names a new task; `analysis_update`
advances saved references against the previously read revision. Inspect a lost
CAS with `analysis_proposal`. No context is required for an isolated tool call.
For a task the user wants to continue later, choose a short human-readable name
and tell them that name. On reconnection read that named analysis and the retained
panel's current state before doing new work; do not recreate TIFF/FFT objects to
rebuild chat memory. An original request query recovers its historical outcome,
whereas an unqualified `analysis_read` reads current references.

- For viewing, ROI, local FFT, display or a corrected scale/point, read
  [microscopy-observe-revise](../microscopy-observe-revise/SKILL.md).
- For a CIF/XYZ, zone axis, reflection hypothesis or simulation comparison, read
  [crystallography-compare](../crystallography-compare/SKILL.md).

Ask only for scientific information that changes the requested result: a missing
physical scale, ambiguous frame meaning, or a candidate/confirmed correspondence.
Unknown scale still allows pixel-domain exploration. Do not substitute an example
calibration or infer phase radians, physical slice depth or unique phase identity.

Save each write's request ID before submission. Identify recovery by its provider,
workspace and session, as well as that ID. After timeout or cancellation query
`image_result` or `structure_result`; an incomplete outcome never authorizes
automatic replay. Optional `execution_list` / `execution_info` explain waiting
and worker closure; their observations are not durable scientific receipts.

Use [schema-checked examples](examples.json) as isolated call shapes, not a required
sequence or experimental answers. Report which values came from DM, external
computation, the user, or a candidate interpretation.
