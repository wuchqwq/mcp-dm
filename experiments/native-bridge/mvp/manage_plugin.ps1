<#
.SYNOPSIS
Install or remove only this experimental bridge DLL while DM is closed.
.DESCRIPTION
Local manifests contain private absolute source/installation paths. Keep them
outside the repository. No DM process is started, stopped, killed or restarted.
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory = $true)][ValidateSet('Install', 'Remove')][string]$Action,
    [string]$SourceDll = (Join-Path $PSScriptRoot 'build\dm_native_bridge.dll'),
    [string]$PluginDirectory = (Join-Path $env:ProgramData 'Gatan\Plugins'),
    [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string]$StateDirectory
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$project = 'mcp-dm-native-bridge-mvp'
$dllName = 'dm_native_bridge_mvp.dll'
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Absolute-Path([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { throw 'Paths must not be empty.' }
    return [IO.Path]::GetFullPath($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Value))
}
function Same-Path([string]$Left, [string]$Right) {
    return [string]::Equals($Left.TrimEnd('\', '/'), $Right.TrimEnd('\', '/'), [StringComparison]::OrdinalIgnoreCase)
}
function Assert-NoReparsePath([string]$Value) {
    $cursor = $Value
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Refusing a symbolic link or reparse-point path: $cursor"
            }
        }
        $parent = [IO.Directory]::GetParent($cursor)
        $cursor = if ($parent) { $parent.FullName } else { $null }
    }
}
function Assert-DmStopped {
    # Enumerate rather than swallowing errors from a named-process lookup.
    $hosts = @(Get-Process -ErrorAction Stop | Where-Object { $_.ProcessName -ieq 'DigitalMicrograph' })
    if ($hosts.Count -ne 0) { throw 'DigitalMicrograph is running. Close the test host normally before managing the DLL.' }
}
function Sha256([string]$Value) {
    $hashStream = [IO.File]::Open($Value, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($algorithm.ComputeHash($hashStream)).Replace('-', '').ToLowerInvariant() }
    finally { $algorithm.Dispose(); $hashStream.Dispose() }
}
function Write-NewText([string]$File, [string]$Text) {
    $stream = [IO.File]::Open($File, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $bytes = $utf8.GetBytes($Text)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally { $stream.Dispose() }
}
function Replace-Manifest($Manifest) {
    $temporary = Join-Path $statePath ('manifest-' + [guid]::NewGuid().ToString('N') + '.pending')
    $backup = Join-Path $statePath ('manifest-' + [guid]::NewGuid().ToString('N') + '.previous')
    try {
        Write-NewText $temporary ($Manifest | ConvertTo-Json -Depth 6)
        # A literal $null is converted to an empty string by some PowerShell
        # .NET binders. Use an explicit backup, retaining the previous durable
        # ownership record if an interrupted update needs manual inspection.
        [IO.File]::Replace($temporary, $manifestPath, $backup)
    } finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) { Remove-Item -LiteralPath $temporary -Force }
    }
}
function Read-Manifest {
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'No installation manifest; refusing to infer ownership from a DLL name.' }
    $record = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($record.project -cne $project -or $record.schema -ne 1 -or $record.dll_name -cne $dllName -or
        $record.install_id.Length -ne 32 -or $record.install_id -cnotmatch '^[a-f0-9]{32}$' -or
        $record.sha256.Length -ne 64 -or $record.sha256 -cnotmatch '^[a-f0-9]{64}$' -or
        @('prepared', 'installed', 'removing', 'removed', 'aborted') -cnotcontains $record.state) { throw 'Foreign or invalid installation manifest.' }
    if (-not (Same-Path (Absolute-Path $record.plugin_directory) $pluginPath) -or
        -not (Same-Path (Absolute-Path $record.owned_path) $targetPath) -or
        -not (Same-Path ([IO.Path]::GetDirectoryName((Absolute-Path $record.owned_path))) $pluginPath) -or
        [IO.Path]::GetFileName($record.owned_path) -cne $dllName) { throw 'Manifest ownership path is outside the specified plugin directory or uses a foreign filename.' }
    if (-not [IO.Path]::IsPathRooted($record.source_path) -or -not [IO.Path]::IsPathRooted($record.owned_path) -or
        -not [IO.Path]::IsPathRooted($record.plugin_directory)) { throw 'Manifest paths must be absolute.' }
    return $record
}

# Resolve every supplied path before inspection or mutation. Reject junctions,
# symlinks and aliases through existing ancestors rather than following them.
$sourcePath = Absolute-Path $SourceDll
$pluginPath = Absolute-Path $PluginDirectory
$statePath = Absolute-Path $StateDirectory
$targetPath = Absolute-Path (Join-Path $pluginPath $dllName)
$manifestPath = Absolute-Path (Join-Path $statePath 'install-manifest.json')
$lockPath = Absolute-Path (Join-Path $pluginPath '.dm_native_bridge_mvp.lock')
foreach ($entry in @($sourcePath, $pluginPath, $statePath, $targetPath, $manifestPath, $lockPath)) { Assert-NoReparsePath $entry }
if ((Same-Path $pluginPath $statePath) -or $statePath.StartsWith($pluginPath.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'StateDirectory must be outside PluginDirectory; keep local manifests private.'
}
Assert-DmStopped
Write-Output "Plugin inventory: $pluginPath"
if (Test-Path -LiteralPath $pluginPath -PathType Container) {
    Get-ChildItem -LiteralPath $pluginPath -Force | Sort-Object Name | ForEach-Object {
        Write-Output (($_ | Select-Object Name, FullName, Attributes) | ConvertTo-Json -Compress)
    }
} elseif (Test-Path -LiteralPath $pluginPath) { throw 'PluginDirectory exists but is not a directory.' }
else { Write-Output '(directory does not exist)' }

if ($Action -eq 'Install') {
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf) -or [IO.Path]::GetExtension($sourcePath) -ine '.dll') { throw 'SourceDll must be an existing built DLL.' }
    if (Test-Path -LiteralPath $targetPath) { throw 'Target DLL already exists; refusing to overwrite or claim it.' }
    if (Test-Path -LiteralPath $manifestPath) { throw 'An installation manifest already exists; use a new StateDirectory after reviewing the old record.' }
    if (Test-Path -LiteralPath $lockPath) { throw 'An installation lock already exists; inspect its associated manifest before recovery.' }
    $hash = Sha256 $sourcePath
    $record = [ordered]@{schema = 1; project = $project; install_id = [guid]::NewGuid().ToString('N'); state = 'prepared';
        dll_name = $dllName; source_path = $sourcePath; plugin_directory = $pluginPath; owned_path = $targetPath;
        sha256 = $hash; created_utc = [DateTime]::UtcNow.ToString('o')}
    $stagePath = Join-Path $pluginPath ('.dm_native_bridge_mvp.' + $record.install_id + '.pending')
    $record.staging_path = $stagePath
} else {
    $record = Read-Manifest
    if ($record.state -eq 'removed') {
        if (Test-Path -LiteralPath $targetPath) { throw 'The recorded installation was removed; any current target is foreign.' }
        Write-Output 'Already removed; no files changed.'
        return
    }
    if ($record.state -eq 'aborted' -and (Test-Path -LiteralPath $targetPath)) { throw 'Aborted installation does not own a target DLL.' }
    if (Test-Path -LiteralPath $targetPath) {
        if (-not (Test-Path -LiteralPath $targetPath -PathType Leaf) -or (Sha256 $targetPath) -cne $record.sha256) { throw 'Installed DLL changed or is not a regular file; refusing removal.' }
    } elseif ($record.state -eq 'installed') { throw 'Installed DLL is missing; inspect the local record before recovery.' }
}

if (-not $PSCmdlet.ShouldProcess($targetPath, "$Action experimental native DLL; local ownership manifest: $manifestPath")) { return }
[IO.Directory]::CreateDirectory($pluginPath) | Out-Null
[IO.Directory]::CreateDirectory($statePath) | Out-Null
$lockStream = $null
$lockOwned = $false
$stageCreated = $false
$moved = $false
try {
    Assert-DmStopped
    foreach ($entry in @($pluginPath, $statePath, $targetPath, $manifestPath, $lockPath)) { Assert-NoReparsePath $entry }
    if ($Action -eq 'Remove' -and (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
        # A live installer holds FileShare.None. Only its stale, matching lock
        # can be reused to recover a prepared manifest after interruption.
        $lockStream = [IO.File]::Open($lockPath, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        $reader = New-Object IO.StreamReader($lockStream, $utf8, $false, 1024, $true)
        try { $lock = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
        if ($lock.project -cne $project -or $lock.install_id -cne $record.install_id) { throw 'Foreign installation lock; refusing to modify it.' }
        $lockOwned = $true
    } else {
        $lockStream = [IO.File]::Open($lockPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        $lockOwned = $true
        $bytes = $utf8.GetBytes((@{project = $project; install_id = $record.install_id} | ConvertTo-Json -Compress))
        $lockStream.Write($bytes, 0, $bytes.Length); $lockStream.Flush($true)
    }
    if ($Action -eq 'Install') {
        if ((Test-Path -LiteralPath $targetPath) -or (Test-Path -LiteralPath $manifestPath)) { throw 'Target or manifest appeared during installation; refusing overwrite.' }
        # Durable ownership exists BEFORE any DLL bytes enter PluginDirectory.
        Write-NewText $manifestPath ($record | ConvertTo-Json -Depth 6)
        $sourceStream = [IO.File]::Open($sourcePath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        try {
            $stageStream = [IO.File]::Open($stagePath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            $stageCreated = $true
            try { $sourceStream.CopyTo($stageStream); $stageStream.Flush($true) } finally { $stageStream.Dispose() }
        } finally { $sourceStream.Dispose() }
        if ((Sha256 $stagePath) -cne $hash) { throw 'Source DLL changed while copying; refusing installation.' }
        Assert-DmStopped
        [IO.File]::Move($stagePath, $targetPath) # Atomic and never overwrites.
        $moved = $true
        $record.state = 'installed'
        Replace-Manifest $record
        Write-Output "Installed owned DLL; SHA256=$hash"
    } else {
        $record = Read-Manifest
        Assert-DmStopped
        Assert-NoReparsePath $targetPath
        if (Test-Path -LiteralPath $targetPath) {
            if ($record.state -notin @('prepared', 'installed', 'removing') -or (Sha256 $targetPath) -cne $record.sha256) { throw 'DLL ownership or hash changed; refusing removal.' }
            # Persist the pending removal before deletion, so an interrupted
            # final manifest update is recoverable when the DLL is now absent.
            $record.state = 'removing'
            Replace-Manifest $record
            Remove-Item -LiteralPath $targetPath -Force
        }
        $record.state = 'removed'
        $record | Add-Member -NotePropertyName removed_utc -NotePropertyValue ([DateTime]::UtcNow.ToString('o')) -Force
        Replace-Manifest $record
        Write-Output 'Removed only the owned DLL; local manifest retained as removed.'
    }
} catch {
    if ($Action -eq 'Install' -and $moved) {
        Write-Warning "DLL is present with a recoverable prepared manifest: $manifestPath. Use Remove after inspection; do not delete or overwrite the record."
    }
    throw
} finally {
    if ($stageCreated -and -not $moved -and (Test-Path -LiteralPath $stagePath -PathType Leaf)) { Remove-Item -LiteralPath $stagePath -Force }
    if ($lockStream) { $lockStream.Dispose(); if ($lockOwned) { Remove-Item -LiteralPath $lockPath -Force } }
}
