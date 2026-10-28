# MCP-DM — optional independent DigitalMicrograph provider

This package owns **only `dm_*` tools**, DM Python/C++ integration, GMS version and
capability checks, native request recovery and bounded numerical handoff.
It does not require Microscopy Core, ASE/diffsims, its GUI or scientific Skills.
Independent TIFF/FFT/structure analysis belongs to the separate science MCP;
Windows users do not need DM for that workflow.

Use Node >=18. For the default backend start `bridge/dm_bridge.py` in the supported
DigitalMicrograph embedded Python environment, then register `node server.mjs`
in your MCP client. The independent external Python used by optional preview/
legacy analysis helpers must not replace or modify GMS-managed Python.
`DM_MCP_BACKEND=python` is default. `DM_MCP_BACKEND=native` explicitly selects
qualified Windows GMS native integration with `DM_NATIVE_SESSION`; all exact
build, dtype, geometry, lifetime and qualification gates remain unchanged.
`DM_MCP_BACKEND=images` is intentionally rejected here: use Microscopy Core.

Run `npm test` for the packaged catalog/protocol/selected native validation tests.
These do not connect to a real DM host and do not establish new native capability
qualification. Current qualified native scope remains Windows x64 GMS
3.53.4137.0, bounded per-operation subsets; retained experimental documentation
contains historical FAIL/NOT_TESTED evidence as well as scoped passes.
Never build/load the retired probe or replace a loaded DLL.

Original `dm_*` names and schemas and the `digitalmicrograph` server identity are
retained. Arbitrary DM-Script remains disabled by default. There is no microscope
hardware control, remote network exposure or automatic NumPy fallback.

`MIGRATION_MANIFEST.json` records all source hashes and the small shared protocol
snapshot. Legacy DM-bound Python arithmetic/helpers stay here for compatibility;
this does not make them the general science core. Do not automatically replace
the existing repository with this candidate: first accept the new science repo,
then review the old combined entry's deprecation/removal in a separate PR.
