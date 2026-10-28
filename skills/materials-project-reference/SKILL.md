---
name: materials-project-reference
description: Find several Materials Project reference candidates with the separately configured official MP MCP, retrieve selected MP IDs, and hand their structures to existing ASE/diffsims tools for comparison. Use for reference searches and hypothesis checks, not automatic phase identification or ordinary image viewing.
---

# Retrieve reference candidates without deciding the phase

Inspect the actual client catalog for the independently configured official
Materials Project provider. If absent, explain the optional connection and
continue unrelated microscopy work. Never upload private images or ask for an
API key in chat. Configuration and current official contracts are in
[the connection guide](references/connection.md).

Start with the user's chemical constraints. Distinguish an exact chemical system
from “contains these elements”; do not imply the provider searched all supersets
when it searched only an exact system. Call official `search(query)` to obtain
multiple MP IDs and descriptions. Select a few relevant candidates; do not call
`fetch(formula)` and present its single most stable entry as the candidate set.
Query details with `fetch(idx)` using an exact returned MP ID. Use `fetch_many`
only when it is actually advertised; do not use unbounded `fetch_all` here.

Retain the search query, retrieval time, MP ID/URL, provider version if known,
raw fetched metadata and source hashes. Missing fields remain unknown. The
official schema currently includes `metadata.poscar`; it does not promise a
CIF field. Save the exact fetched object as JSON. For a supported POSCAR response,
run [the local format handoff](scripts/save_reference.py) in the existing
independent ASE environment, giving it that JSON, a fresh output directory,
the actual query and retrieval time. It does no network access or search and
never guesses missing atoms. If structure data are absent, report that specific
limitation rather than reconstructing them from a description.

Pass the returned `structure_path` to `structure_open`. Keep the handoff manifest
alongside that immutable structure. Use `structure_orient` for a proposed [uvw]
and reuse its orientation in `structure_view` and `structure_simulate`. Simulation
conditions are explicit trial assumptions unless the user supplied them. For
experimental evidence, reuse the current saved image measurement and independent
calibration; compare un-rasterized reflection geometry with `structure_compare`.
Read the existing crystallography comparison Skill when the task reaches this
step; avoid substituting PNG similarity for numeric evidence.

For an unconfirmed trial, `structure_compare` can use an explicit registration
whose `basis` names the Agent's hypothesis. Keep independent scale fixed at 1,
DC translation at zero and the established screen parity; state the proposed
in-plane rotation. This does not require claiming confirmed correspondences.
Use `structure_register` only after its actual confirmation conditions are met.
Retain the trial's unmatched reflections and residuals before proposing another
orientation or the next observation; do not silently refit the experimental scale.

An MP candidate, its low energy above hull, and a geometric match do not establish
the experimental phase. Keep Agent-proposed correspondences unconfirmed; do not
claim `user_confirmed` to satisfy a registration tool. Preserve unmatched peaks,
multiple orientations/candidates and held-out evidence. FFT and SAED intensities
do not share a general formation model. Present which hypotheses fit, which
conflict and one useful next observation. The user may accept, reject or defer.

Keep internal object/request IDs and local paths out of the researcher's routine
steps. Existing scientific tools retain their normal pre-saved request recovery;
the official MP provider has its own read-query semantics. MP disconnection must
never switch a failed DM operation to an external backend.
