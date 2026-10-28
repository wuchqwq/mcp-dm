param(
    [string]$Name = 'digitalmicrograph',
    [ValidateRange(1,65535)][int]$Port = 8765,
    [ValidateRange(100,600000)][int]$TimeoutMilliseconds = 600000,
    [string]$NodeExecutable = 'node',
    [string]$CodexExecutable = 'codex',
    [string]$AnalysisPython = '',
    [ValidateSet('python','images')][string]$Backend = 'python',
    [string]$ImageWorkspace = '',
    [string]$ImagePython = '',
    [string]$ContextWorkspace = '',
    [string]$StructureWorkspace = '',
    [string]$StructurePython = '',
    [switch]$ExecutionObservability,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$nodePath = (Get-Command $NodeExecutable -ErrorAction Stop).Source
$codexPath = (Get-Command $CodexExecutable -ErrorAction Stop).Source
$serverPath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\server.mjs')).Path
function Resolve-OutputDirectory([string]$Value, [string]$Label) {
    # GetFullPath alone would silently turn a relative path into a different
    # workspace when Codex starts the server from another current directory.
    if (-not [IO.Path]::IsPathRooted($Value) -or $Value -match '^[A-Za-z]:[^\\/]' -or ($env:OS -eq 'Windows_NT' -and [IO.Path]::GetPathRoot($Value) -in @('\','/'))) {
        throw "$Label must be an explicit absolute output directory."
    }
    $resolved = [IO.Path]::GetFullPath($Value)
    if ((Test-Path -LiteralPath $resolved) -and -not (Test-Path -LiteralPath $resolved -PathType Container)) {
        throw "$Label identifies a file, not an output directory."
    }
    return $resolved
}
function Resolve-IndependentPython([string]$Value, [string]$Label, [string]$Imports) {
    $resolved = (Get-Command $Value -ErrorAction Stop).Source
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) { throw "$Label must identify an existing independent Python executable." }
    # Import checks only. Never install or upgrade packages, especially in GMS.
    $probe = "import sys; assert sys.version_info >= (3, 10), 'Independent Python >=3.10 required'; import $Imports"
    $null = & $resolved -c $probe
    if ($LASTEXITCODE -ne 0) { throw "$Label preflight failed. Use a separate Python >=3.10 environment with the matching requirements file; no configuration was changed." }
    return $resolved
}
if ($AnalysisPython) {
    $analysisPath = (Resolve-Path -LiteralPath $AnalysisPython).Path
    if (-not (Test-Path -LiteralPath $analysisPath -PathType Leaf)) { throw 'AnalysisPython must identify an existing Python executable.' }
}
if ($Backend -eq 'images' -and (-not $ImageWorkspace -or -not $ImagePython)) {
    throw 'Independent images mode requires both -ImageWorkspace and -ImagePython. It does not connect to DM.'
}
if ([bool]$ImageWorkspace -ne [bool]$ImagePython) { throw 'Specify both -ImageWorkspace and -ImagePython.' }
if ([bool]$StructureWorkspace -ne [bool]$StructurePython) { throw 'Specify both -StructureWorkspace and -StructurePython.' }
if ($ContextWorkspace -and -not $ImageWorkspace -and -not $StructureWorkspace) { throw '-ContextWorkspace requires an explicitly configured image or structure workspace.' }
if ($ImageWorkspace) {
    $imageDirectory = Resolve-OutputDirectory $ImageWorkspace 'ImageWorkspace'
    $imagePythonPath = Resolve-IndependentPython $ImagePython 'ImagePython' 'numpy, PIL, tifffile, scipy'
}
if ($ContextWorkspace) { $contextDirectory = Resolve-OutputDirectory $ContextWorkspace 'ContextWorkspace' }
if ($StructureWorkspace) {
    $structureDirectory = Resolve-OutputDirectory $StructureWorkspace 'StructureWorkspace'
    $structurePythonPath = Resolve-IndependentPython $StructurePython 'StructurePython' 'numpy, scipy, ase, matplotlib, diffsims'
}
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
$addArgs = @('mcp', 'add', $Name,
    '--env', "DM_MCP_BACKEND=$Backend",
    '--env', "DM_MCP_TIMEOUT_MS=$TimeoutMilliseconds",
    '--env', 'DM_MCP_ALLOW_DMSCRIPT=0')
if ($Backend -eq 'python') { $addArgs += @('--env', 'DM_BRIDGE_HOST=127.0.0.1', '--env', "DM_BRIDGE_PORT=$Port") }
if ($AnalysisPython) { $addArgs += @('--env', "DM_ANALYSIS_PYTHON=$analysisPath") }
if ($ImageWorkspace) { $addArgs += @('--env', "DM_IMAGE_WORKSPACE=$imageDirectory", '--env', "DM_IMAGE_PYTHON=$imagePythonPath") }
if ($ContextWorkspace) { $addArgs += @('--env', "DM_ANALYSIS_CONTEXT_WORKSPACE=$contextDirectory") }
if ($StructureWorkspace) { $addArgs += @('--env', "DM_STRUCTURE_WORKSPACE=$structureDirectory", '--env', "DM_STRUCTURE_PYTHON=$structurePythonPath") }
if ($ExecutionObservability) { $addArgs += @('--env', 'DM_MCP_EXECUTION_OBSERVABILITY=1') }
$addArgs += @('--', $nodePath, $serverPath)
if ($CheckOnly) {
    Write-Output "Preflight passed for '$Name' (backend=$Backend). No Codex configuration or workspace was changed."
    return
}
& $codexPath @addArgs
if ($LASTEXITCODE -ne 0) { throw 'Codex registration failed. If this server name already exists, inspect it with codex mcp get before changing it.' }
$registeredJson = & $codexPath mcp get $Name --json
if ($LASTEXITCODE -ne 0) { throw 'Codex configuration verification failed.' }
try { $registered = $registeredJson | ConvertFrom-Json }
catch { throw 'Cannot parse registered Codex configuration. Inspect this name before trying again.' }
if ($registered.name -ne $Name -or $registered.transport.command -ne $nodePath -or @($registered.transport.args)[0] -ne $serverPath) {
    throw "Registered Codex server identity differs from the requested command (name='$($registered.name)', command='$($registered.transport.command)', server='$(@($registered.transport.args)[0])'). Inspect this name before trying again."
}
Write-Output "Registered '$Name' (backend=$Backend). Existing servers were preserved. Refresh/restart the MCP connection to discover its tools."
if ($Backend -eq 'images') {
    Write-Output 'Independent images mode does not start or require DM. Ask Codex to open a local TIFF, open its image panel, and continue from the current selection.'
    Write-Output 'For a long-running call, save its request ID before dispatch and recover through image_result; reconnecting does not mean the operation stopped.'
    return
}
Write-Output 'Registration does not start DM. Start setup/start_bridge.ps1, refresh/restart the MCP client, then require dm_status.backend=digitalmicrograph.'
Write-Output "In the existing [mcp_servers.$Name] table of your Codex config, set startup_timeout_sec=20. Increase tool_timeout_sec for long analyses only when needed; after client timeout, query dm_2d_result before retrying. Do not create a duplicate table."
Write-Output 'Add dm_run_script to disabled_tools in that same table, preserving any existing denylist. The two execution gates remain disabled even before this client-side hiding step.'
