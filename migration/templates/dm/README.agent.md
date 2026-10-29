# Agent guide: standalone MCP-DM

This checkout is the optional **DigitalMicrograph-only** provider. Read
[README](README.md), [DM reference](REFERENCE.en.md) and
[qualification contract](DM_QUALIFICATION_CONTRACT.md) before host operations.
Historical combined-product instructions in the preserved contract are not
installation instructions for this package; the current [AGENTS](AGENTS.md)
defines the provider boundary.

## Register without changing other providers

On the authorized Windows host, use Node >=18 and the user's installed Codex.
The [registration helper](setup/register_codex.ps1) supports only `python` and
`native`. It refuses duplicate names and has a read-only preflight:

```powershell
./setup/register_codex.ps1 -Backend python -CheckOnly
./setup/register_codex.ps1 -Backend python
# Use a real session ID from the explicitly started, qualified native build:
./setup/register_codex.ps1 -Name digitalmicrograph-native -Backend native -NativeSession '<32-lowercase-hex>' -CheckOnly
```

Replace the placeholder before using it. After review, omit `-CheckOnly` to
register native mode. The helper does not start DM, load a DLL, install packages,
change approval policy or qualify a native build. No shared science-repository
installation is needed. `AnalysisPython` is an optional independent interpreter
for retained legacy DM preview/analysis helpers, not a way to enable image tools.

For default Python/TCP mode, explicitly start the existing
[bridge launcher](setup/start_bridge.ps1), then inspect `dm_status`. Do not treat
a mock backend or a discovered tool catalog as a live DM connection.
For native mode, preserve the actual build, session and capability gates in
[the native adapter documentation](experiments/native-bridge/mvp/ADAPTERS.md).
Do not fabricate a session ID or rebuild/load plugins merely to register an MCP.

## Operate the correct provider

Only `dm_*` tool names are provided here. Use `tools/list` from the actual
connection; do not assume a historical catalog defines the current host's
qualified operators. There is no `images` backend and no image/structure/context
workspace configuration in this registrar. For standalone TIFF, FFT, GUI or CIF
work, register the independent science MCP alongside this one in the client.
No failure automatically switches providers.

Keep source images and calibration unchanged unless a particular authorized
operation creates a new result. Before writes, save the original request ID.
A timeout/connection loss is not a failed operation: query its original result,
using `dm_native_result` or the corresponding provider result tool, without
blindly resubmitting. Native session restart does not promise old result recovery.

Numeric transfer uses explicit files with provenance; PNG is display, not a
scientific array. See [handoff](docs/SCIENTIFIC_HANDOFF.md) and
[numerical relay limits](docs/DM_NUMERIC_RELAY.md). Remote networking and new
native qualification are not part of registration or migration.
