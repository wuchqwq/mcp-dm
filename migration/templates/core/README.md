# Microscopy Core

Cross-platform microscopy image analysis and scientific interaction through MCP,
with an optional local Image Panel. **Windows, macOS and Linux do not require
DigitalMicrograph or the mcp-dm repository.** A compatible Agent may connect
`microscopy-core` and the optional `mcp-dm` as two peer MCP servers.

This is a migration candidate, not a newly qualified instrument integration.
`MIGRATION_MANIFEST.json` identifies the exact reviewed source and recipe commits
and every copied/generated file. The original repository retains historical Git
attribution; this snapshot export does not rewrite or pretend to preserve blame.

Current [client setup](docs/CLIENT_SETUP.md) includes Windows and macOS/Linux
configuration; the [Agent guide](README.agent.md) defines the independent tool
boundary. Do not use the old combined DM registrar for this package.

## Install and test

Use Node >=18 and a separate Python >=3.10 environment. Install
`requirements-images.txt` there. Run `npm test` for dependency-free Node checks.
Set `MICROSCOPY_PYTHON` to the **absolute** environment interpreter, then run
`npm run test:science` for a real synthetic TIFF/FFT/NPY/HTTP round trip.
Missing Python dependencies cause failure, not a silently skipped acceptance.

Run `node server.mjs` from an MCP client's stdio configuration with:

| Variable | Meaning |
| --- | --- |
| `MICROSCOPY_PYTHON` | Absolute independent Python interpreter |
| `MICROSCOPY_IMAGE_WORKSPACE` | Absolute scientific working directory |
| `MICROSCOPY_CONTEXT_WORKSPACE` | Optional independent context directory |
| `MICROSCOPY_STRUCTURE_WORKSPACE` | Optional structure directory |
| `MICROSCOPY_STRUCTURE_PYTHON` | Optional structure interpreter |

No client settings, approval policy or Skills are changed automatically. Add
`requirements-structure-tools.txt` only for CIF/XYZ/ASE/diffsims. The optional
3Dmol viewer asset still needs its existing explicit local configuration.

For direct use without any model, run:

```sh
node tools/researcher_inspector.mjs --source /absolute/input.tiff --workspace /absolute/new-workspace --python /absolute/venv/bin/python
```

On Windows, supply the equivalent absolute paths; quoting paths with spaces is
required. The terminal prints a private loopback panel URL. Keep the process
running and stop normally with Ctrl+C. The Image Panel uses this repository's
independent server and the exact selected workspace, not a hidden DM server.

## Scope and data

Existing admitted uint16 TIFF / verified schema-1 captures, source/frame/ROI,
FFT, calibrated measurements, editable annotations and scientific exports remain
subject to their original guards. No arbitrary DM3/DM4 support, reconstruction,
unique phase identification or remote DM transport is added by this migration.
Saved native capture verification is a **read-only file-format adapter**, not a
live DM dependency. Old file-workspace schemas and names are preserved so source
hashes, original IDs and recovery records are not invalidated by a rename.

The science provider owns scientific arrays and contexts. The DM provider owns
live DM image IDs, sessions and native request state. Exchange explicit versioned
numeric captures, axes/units/domain and provenance; never share private runtime
classes or silently fall back after a failed native operation.
