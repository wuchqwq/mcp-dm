# Standalone DM provider only. Does not install packages or start/qualify GMS.
[CmdletBinding()]
param(
    [string]$Name = 'digitalmicrograph',
    [ValidateSet('python','native')][string]$Backend = 'python',
    [string]$NativeSession = '',
    [ValidateRange(1,65535)][int]$Port = 8765,
    [ValidateRange(100,600000)][int]$TimeoutMilliseconds = 600000,
    [string]$NodeExecutable = 'node',
    [string]$CodexExecutable = 'codex',
    [string]$AnalysisPython = '',
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
if ($Name -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$') { throw 'Use a nonempty MCP name of at most 64 letters, digits, underscores or hyphens.' }
if ($Backend -eq 'native') {
    if ($NativeSession -cnotmatch '^[a-f0-9]{32}$') {
        throw 'NativeSession must be the 32 lowercase hexadecimal characters from the explicitly started qualified native session. No configuration was changed.'
    }
} elseif ($NativeSession) { throw 'NativeSession is valid only with -Backend native.' }
$nodePath = (Get-Command $NodeExecutable -ErrorAction Stop).Source
$codexPath = (Get-Command $CodexExecutable -ErrorAction Stop).Source
$serverPath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../server.mjs')).Path
if ($AnalysisPython) {
    if (-not [IO.Path]::IsPathRooted($AnalysisPython)) { throw 'AnalysisPython must be an explicit absolute executable path.' }
    $analysisPath = (Resolve-Path -LiteralPath $AnalysisPython).Path
    if (-not (Test-Path -LiteralPath $analysisPath -PathType Leaf)) { throw 'AnalysisPython must identify an existing independent Python executable.' }
}
# Refuse existing names before any configuration write; never print peer env/secrets.
$catalogJson = & $codexPath mcp list --json
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect existing MCP servers; no configuration was changed.' }
if (($catalogJson -join "`n").TrimStart() -notmatch '^\[') { throw 'Unexpected MCP catalog; no configuration was changed.' }
try { $catalog = @($catalogJson | ConvertFrom-Json) }
catch { throw 'Cannot parse MCP catalog; no configuration was changed.' }
if ($catalog | Where-Object { $_.name -eq $Name }) { throw "MCP server '$Name' already exists. No configuration was changed. Use a different name or explicitly review the existing entry." }
$addArgs = @('mcp', 'add', $Name,
    '--env', "DM_MCP_BACKEND=$Backend",
    '--env', "DM_MCP_TIMEOUT_MS=$TimeoutMilliseconds",
    '--env', 'DM_MCP_ALLOW_DMSCRIPT=0')
if ($Backend -eq 'native') { $addArgs += @('--env', "DM_NATIVE_SESSION=$NativeSession") }
else { $addArgs += @('--env', 'DM_BRIDGE_HOST=127.0.0.1', '--env', "DM_BRIDGE_PORT=$Port") }
if ($AnalysisPython) { $addArgs += @('--env', "DM_ANALYSIS_PYTHON=$analysisPath") }
$addArgs += @('--', $nodePath, $serverPath)
if ($CheckOnly) {
    Write-Output "Preflight passed for '$Name' (backend=$Backend). No configuration changed; DM host/native session not contacted or qualified."
    return
}
& $codexPath @addArgs
if ($LASTEXITCODE -ne 0) { throw 'Registration failed. Inspect this MCP name before retrying; do not blindly add it again.' }
$registeredJson = & $codexPath mcp get $Name --json
if ($LASTEXITCODE -ne 0) { throw 'Configuration verification failed after add. Inspect the saved entry; do not automatically repeat it.' }
try { $registered = $registeredJson | ConvertFrom-Json }
catch { throw 'Cannot parse saved configuration. Inspect this name before retrying.' }
if ($registered.name -ne $Name -or $registered.transport.command -ne $nodePath -or @($registered.transport.args).Count -ne 1 -or @($registered.transport.args)[0] -ne $serverPath) {
    throw 'Registered command differs from the requested provider. Inspect the saved entry; no automatic retry.'
}
Write-Output "Registered '$Name' (backend=$Backend). Existing providers preserved. Refresh the client connection."
if ($Backend -eq 'native') {
    Write-Output 'Registration is not native qualification. Verify dm_status and the exact build/capabilities; preserve original request IDs and use dm_native_result after uncertain outcomes.'
} else {
    Write-Output 'Registration does not start DM. Start setup/start_bridge.ps1 on the authorized GMS host, then verify dm_status.backend=digitalmicrograph.'
    Write-Output 'Keep dm_run_script disabled in the client, preserving existing settings. Arbitrary DM-Script remains blocked by the server gate.'
}
Write-Output 'Standalone image/structure work uses the separately registered science provider; this package contains only dm_* tools.'
