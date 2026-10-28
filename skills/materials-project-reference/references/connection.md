# Optional Materials Project references for microscopy

The `materials-project-reference` Skill uses the **official MP MCP as a separate
Codex provider**. It adds no MP server, search wrapper, database or scientific
engine to mcp-dm. Without this optional connection, local TIFF/FFT, structure
tools and DM continue to work.

## Connect once

Install the official `mp-api[mcp]` in a **separate Python environment**, never
GMS Python or the existing image environment. The inspected upstream revision
`f107e6db` requires **Python >=3.12** and includes pymatgen/emmet and FastMCP;
this is a substantial optional dependency, not part of the default mcp-dm
installation. Other releases may have different Python requirements: use their
published package metadata rather than applying this pinned revision's minimum
to every version. Use the official package/version available to the user and
record it; do not assume the upstream main branch is the installed release.
Package source is BSD-3-Clause-LBNL; MP data/service usage has its own applicable
terms. This does not raise the Python requirement of the separate image tools.
See [official setup](https://docs.materialsproject.org/services/ml-and-ai-applications/mcp)
and the [inspected package metadata](https://github.com/materialsproject/api/blob/f107e6dba9601b1f84387b01e3bf1465937804f0/pyproject.toml).

Configure a distinct stdio provider whose command is the absolute executable
of that MP environment and whose arguments are:

```text
-m mp_api.mcp.server
```

Use the installed Codex version's supported configuration mechanism; preserve
all existing providers and refuse a duplicate provider name. Make `MP_API_KEY`
available through the local environment inherited by that provider. Do not put
the key in repository files, command arguments, copied setup logs or chat.
For the inspected Codex configuration, the provider block can use
`env_vars = ["MP_API_KEY"]` to inherit that variable without storing its value.
Restart/reconnect the client as required for it to discover the optional provider.
Install or reference [the Skill](../SKILL.md)
explicitly without overwriting an existing same-name Skill. It can then support:

> “Find several reference structures in this element system and compare useful
> candidates against my current reflection measurements.”

Check the connected provider's actual `tools/list` before calling it. Official
documentation and installed releases can differ; a source review is not a live
service acceptance result.

## Install only this optional Skill

`setup/install_codex_skills.ps1` deliberately installs only the three existing
microscopy Skills. It does not install `materials-project-reference` or the
Materials Project provider. To add this one optional Skill, run the following
command **from the mcp-dm repository root**, using an available independent
Python executable (no third-party packages are needed for copying):

```powershell
python -c "import os, shutil; from pathlib import Path; source = Path('skills/materials-project-reference').resolve(strict=True); home = Path(os.environ.get('CODEX_HOME') or (Path.home() / '.codex')).expanduser(); destination = home / 'skills' / 'materials-project-reference'; shutil.copytree(source, destination); print('Installed Skill:', destination)"
```

This follows the existing installer: `$CODEX_HOME/skills`, or `~/.codex/skills`
when `CODEX_HOME` is unset. Keep a configured `CODEX_HOME` absolute. For a client
with a different discovered Skill directory, have the local Agent substitute
that explicit destination instead of assuming every client uses this layout.

The complete directory is copied, including `SKILL.md`, `examples.json`,
`references/connection.md` and `scripts/save_reference.py`, so relative links and
the format helper remain available after installation. `shutil.copytree` uses
its default no-overwrite behavior: an existing same-name directory causes an
error, rather than merging with or replacing it. Other Skills and Codex
configuration are untouched. This is an opt-in copy, not an update command;
an interrupted copy may leave a partial new directory that needs inspection
before retrying. Do not bypass a duplicate refusal with an overwrite option.

The command does **not** install `mp-api`, ASE or any other dependencies,
register a provider, read an API key, or access the network. Refresh/restart the
client's Skill discovery and explicitly invoke `materials-project-reference`
once to check discovery. A successful copy does not prove that the model loaded
the Skill or that the official MP provider is connected.

## Search, select, retrieve

The inspected official [tool implementation](https://github.com/materialsproject/api/blob/f107e6dba9601b1f84387b01e3bf1465937804f0/mp_api/mcp/tools.py)
uses `search({query})` for formula, dash-separated chemical system or comma-separated
description keywords. `fetch({idx})` accepts an MP ID; formula/system fetch selects
only a stable representative. Search first, retain multiple IDs, then fetch a
small chosen subset. Do not assume an exact system query includes supersets or
that description-backed search is exhaustive. Other tools, such as `fetch_many`,
are optional until the actual provider advertises them. This Skill does not use
the unbounded all-materials retrieval operation.

Store MP ID, actual query, retrieval time, returned URL/metadata, provider version
when known and raw response hashes. User-confirmed and Agent-proposed candidates
remain distinct. Low calculated energy is reference evidence, not identification
of an observed experimental phase. No private image or measurement file needs
to leave the computer for a materials query.

## Official structure data → existing ASE tools

The inspected [response schema](https://github.com/materialsproject/api/blob/f107e6dba9601b1f84387b01e3bf1465937804f0/mp_api/mcp/_schemas.py)
provides `metadata.poscar` and structure coordinates. It does **not** promise a
CIF field. Save the exact fetched object (`id`, `metadata`, etc.) as JSON; do not
transcribe lattice numbers from text or create missing atoms. The Skill's local
format helper consumes that saved response with the existing ASE environment:

```powershell
& $StructurePython $SkillDir/scripts/save_reference.py `
  --input-json $FetchedJson --output-dir $FreshReferenceDirectory `
  --query $ActualSearchQuery --retrieved-utc $ActualRetrievalTime
```

The Agent resolves these local paths; the researcher supplies chemistry and
scientific intent. This helper has no network client or MCP endpoint. It accepts
only the official VASP5 POSCAR subset with finite full-rank cells, at most 4096
atoms and the existing 2 MiB structure-file bound. It writes the exact fetched
JSON, original POSCAR, ASE-converted CIF and a completion/provenance manifest to
a **new** directory. Existing or incomplete output directories are refused.
No success is returned before the completion record is written. Failure leaves
evidence for inspection; it does not retry an uncertain write.

CIF may canonicalize the Cartesian cell basis. The helper independently reopens
its conversion and checks the lattice metric and fractional sites at fixed
tolerances; it does not promise unchanged Cartesian orientation. Original
POSCAR bytes remain available. A structure version absent from the response
remains unknown. Every imported reference starts as `hypothesized`.

Use the returned `structure_path` with existing `structure_open`, then
`structure_orient` → `structure_view` / `structure_simulate` as appropriate.
Keep `reference.json` beside the scientific result for MP provenance. Compare
un-rasterized simulated coordinates with the current saved experimental
measurements, preserving independent scale, trial rotation and unmatched peaks.
Read [comparison guidance](https://github.com/wuchqwq/mcp-dm/blob/main/skills/scientific-agent/crystallography-compare/SKILL.md)
for scientific limitations. Do not use apparent FFT/SAED intensity similarity as
unique phase proof, and do not label proposed correspondences user-confirmed.

## Evidence boundary

Local format/identity/no-overwrite tests use synthetic fetched-response fixtures,
including a nonorthogonal cell and a real existing `structure_open` call. They
do not contact MP. Official provider authentication, database responses and a
real MP → simulation comparison require their own live acceptance when a key is
configured. Absence of a key is **NOT_TESTED**, not a reason to block image work.
