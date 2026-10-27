# Optional Materials Project references

Use the optional [materials-project-reference Skill](../skills/materials-project-reference/SKILL.md)
with a separately configured **official MP MCP provider**. It searches multiple
reference candidates and retrieves exact MP IDs, then hands official structure
data to existing ASE/diffsims tools. It adds no search service or dependency to
the default mcp-dm setup; no MP connection is needed for image or DM work.

The self-contained [connection and data-handoff guide](../skills/materials-project-reference/references/connection.md)
records the inspected official interfaces, environment-only key setup, optional
dependency/license scope and the small POSCAR→CIF helper. That helper preserves
the fetched response and source hashes and starts references as hypotheses.

Local synthetic format/contract checks are separate from a real authenticated
MP call. Missing keys or an unconnected official provider remain **NOT_TESTED**.
Candidate matches never constitute unique experimental phase identification.
