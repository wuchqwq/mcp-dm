# MCP-DM: standalone DM provider reference

This package provides only `dm_*` operations through explicit Python/TCP or
native backends. It has no independent image/structure workspace or GUI.
Inspect the connected `tools/list` for schemas and the actual status/build/
capability gates before invoking a host operation. A catalog is not qualification.

- [Installation and limits](README.md)
- [Agent operations and registration](README.agent.md)
- [DM-only registrar](setup/register_codex.ps1): `python` / `native`; use `-CheckOnly` first
- [Original qualification contract](DM_QUALIFICATION_CONTRACT.md): historical combined-product sections do not establish availability here
- [Native adapter gates](experiments/native-bridge/mvp/ADAPTERS.md)
- [Scientific handoff](docs/SCIENTIFIC_HANDOFF.md)
- [Bounded numerical relay](docs/DM_NUMERIC_RELAY.md)

Arbitrary DM-Script is disabled by default. Preserve source ownership, array
meaning, signed calibration and original request/session identities. Query the
original result after an uncertain operation; never silently replay or switch
to another engine. Register the independent science provider separately for
TIFF/FFT/annotation/structure work. No microscope hardware control is added.
