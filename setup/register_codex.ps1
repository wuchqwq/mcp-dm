param(
    [string]$Name = 'digitalmicrograph',
    [ValidateRange(1,65535)][int]$Port = 8765,
    [ValidateRange(100,600000)][int]$TimeoutMilliseconds = 600000,
    [string]$NodeExecutable = 'node',
    [string]$CodexExecutable = 'codex'
)
$ErrorActionPreference = 'Stop'
$nodePath = (Get-Command $NodeExecutable -ErrorAction Stop).Source
$codexPath = (Get-Command $CodexExecutable -ErrorAction Stop).Source
$serverPath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\server.mjs')).Path
# `codex mcp add` replaces an existing name silently. Fail closed before any
# write, including when the catalog cannot be read or parsed. Capture the
# catalog rather than printing other servers' environment/configuration.
$catalogJson = & $codexPath mcp list --json
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect existing Codex MCP servers; no configuration was changed.' }
if (($catalogJson -join "`n").TrimStart() -notmatch '^\[') { throw 'Unexpected Codex MCP catalog; no configuration was changed.' }
try { $catalog = @($catalogJson | ConvertFrom-Json) }
catch { throw 'Cannot parse Codex MCP catalog; no configuration was changed.' }
if ($catalog | Where-Object { $_.name -eq $Name }) {
    throw "Codex MCP server '$Name' already exists. No configuration was changed. Inspect it with codex mcp get; use a different -Name for a separate registration."
}
& $codexPath mcp add $Name --env 'DM_BRIDGE_HOST=127.0.0.1' --env "DM_BRIDGE_PORT=$Port" --env "DM_MCP_TIMEOUT_MS=$TimeoutMilliseconds" --env 'DM_MCP_ALLOW_DMSCRIPT=0' -- $nodePath $serverPath
if ($LASTEXITCODE -ne 0) { throw 'Codex registration failed. If this server name already exists, inspect it with codex mcp get before changing it.' }
& $codexPath mcp get $Name --json
if ($LASTEXITCODE -ne 0) { throw 'Codex configuration verification failed.' }
Write-Output 'Registration does not start DM. Start setup/start_bridge.ps1, refresh/restart the MCP client, then require dm_status.backend=digitalmicrograph.'
Write-Output "In the existing [mcp_servers.$Name] table of your Codex config, set tool_timeout_sec=660 and startup_timeout_sec=20 for long 4D jobs. Do not create a duplicate table."
Write-Output 'Add dm_run_script to disabled_tools in that same table, preserving any existing denylist. The two execution gates remain disabled even before this client-side hiding step.'
