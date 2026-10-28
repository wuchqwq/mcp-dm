---
name: crystallography-compare
description: Compose ASE structure geometry, shared zone-axis orientation, kinematic electron diffraction and evidence-preserving experimental reflection comparison. Use to examine or revise candidate structures, not to force every microscopy input through phase identification.
---

# Check a crystallographic hypothesis

Read explicit CIF/XYZ with `structure_open`; preserve its fixed snapshot. Generic
cells and cell-free XYZ can be observed. Reciprocal geometry/simulation requires
the corresponding periodic-cell evidence; do not invent a missing third axis.

When a direction is given as [uvw], call `structure_orient` using the actual
cell and reuse its orientation ID in `structure_view` and `structure_simulate`.
Do not guess Cartesian directions or RZXZ Euler angles from nonorthogonal
indices. A browser camera drag is not a scientific model rotation.

Use `structure_measure` for specified plane/direction/atom relationships. For
simulation, state voltage, reciprocal range, excitation-error bound and any
chosen approximation. `structure_simulate` uses diffsims kinematic scattering;
it is not multislice, an interface/defect scattering model or experimental counts.
An uncertified enumeration refusal stays a refusal; viewing/geometric tools
may still be useful without changing the cell or simulator behind the user.

Compare saved un-rasterized reflections/HKL with committed experimental
measurements. An HRTEM/ptychography FFT and a SAED pattern do not share a general
intensity interpretation. Prefer geometric residuals; a similar PNG is no phase
proof. Keep unmatched reflections, alternative candidates and model limitations.
For 1–3 explicit candidates with unknown HKL, the optional local batch recipe
`tools/hypothesis_explorer.py` reuses these same scientific tools with bounded
low-index zones and polar-angle trials; it produces a static overlay/table and
prospective observation target. See [Hypothesis Explorer](../../../docs/HYPOTHESIS_EXPLORER.md)
for the executed synthetic example and configuration. This is a CLI recipe,
not a newly advertised MCP tool or global orientation search. Keep all points
used to select candidates/roll/HKL labeled search evidence, not held-out validation.
When the researcher corrects a single-domain explanation with "there is twinning",
save only that scoped presence statement via `image_context` metadata.research_observation
(or read its saved reference from `image_panel_current`). Do not confirm a twin
law or HKL on their behalf. The optional [FCC twin feedback recipe](../../../docs/TWIN_FEEDBACK_LOOP.md)
retains the initial comparison, tests constrained Sigma3 alternatives and returns
A/B/shared/unexplained marks to the same Panel. Use `synthetic_fixture` for demo
input, never impersonate human confirmation; remeasure after peak/scale changes.
The Agent may propose unconfirmed structures, orientations and reflection
correspondences and test explicit geometric comparisons. Keep those proposals
as hypotheses: do not assert `user_confirmed` merely to enter a registration
tool that requires confirmed correspondences. State any explicit trial rotation
used by `structure_compare`; report fitted and independently held-out points
separately. Suggest the next discriminating observation when candidates remain.

For confirmed correspondences, `structure_register` estimates only the permitted
proper in-plane rotation with independent experiment scale fixed, zero translation
and explicitly declared screen-axis parity. Correspondence confirmation is a
caller statement. Keep fit points separate from held-out validation; no held-out
points means NOT_VALIDATED. Do not silently add mirror, strain, scale or distortion.

Use `structure_compare` with the selected current image revision for continuation.
After scale/centre/point correction, remeasure valid anchors, replace stale
registration/comparison evidence and retain old versions. Reuse unchanged FFT
bytes and reference structure/orientation when they remain applicable. Historical
review is explicit and never masquerades as fresh observation or current evidence.
When linked through AnalysisContext, a stale registration/comparison remains
historical even though its files are still valid. Persist each new measurement,
simulation or comparison at its own provider, then use the previously read
context revision to advance references. A later user correction can prevent
promotion without undoing or rerunning the already saved scientific results.
Read that revision with `analysis_read`; use `analysis_update` only after the
new provider objects have passed their own validation. Select the current
reference/orientation/simulation and updated measurement/registration/comparison
objects explicitly; the Context tool fills scoped dependency bindings.

Results can be exported or explicitly sent to a separately qualified DM import
tool, within its stated dtype/unit/size limits. Keep simulated numbers separate
from logarithmic PNG/annotation overlays and DM-native computation provenance.

Save request IDs before writes; recover only with `structure_result` in the same
configured provider scope. [Call shapes](examples.json) demonstrate composable
tools, not a mandatory sequence or unique-phase answer.
