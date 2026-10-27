param(
    [string]$SkillsDirectory = '',
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
# This is explicit opt-in installation, independent of MCP registration. It
# copies the existing three Skills as siblings so their relative links survive.
if (-not $SkillsDirectory) {
    $codexBase = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
    $SkillsDirectory = Join-Path $codexBase 'skills'
}
if (-not [IO.Path]::IsPathRooted($SkillsDirectory) -or $SkillsDirectory -match '^[A-Za-z]:[^\\/]' -or ($env:OS -eq 'Windows_NT' -and [IO.Path]::GetPathRoot($SkillsDirectory) -in @('\','/'))) {
    throw 'SkillsDirectory must be an absolute directory.'
}
$destination = [IO.Path]::GetFullPath($SkillsDirectory)
if ((Test-Path -LiteralPath $destination) -and -not (Test-Path -LiteralPath $destination -PathType Container)) {
    throw 'SkillsDirectory is not a directory.'
}
$source = Join-Path $PSScriptRoot '..\skills\scientific-agent'
$names = @('microscopy-router', 'microscopy-observe-revise', 'crystallography-compare')
foreach ($skillName in $names) {
    if (-not (Test-Path -LiteralPath (Join-Path $source "$skillName\SKILL.md") -PathType Leaf)) { throw "Missing source Skill: $skillName" }
    if (Test-Path -LiteralPath (Join-Path $destination $skillName)) { throw "Skill '$skillName' already exists; nothing was overwritten. Use a different explicit -SkillsDirectory or review the existing installation." }
}
if ($CheckOnly) { Write-Output 'Skill preflight passed. No files were copied.'; return }
$null = New-Item -ItemType Directory -Path $destination -Force
$staging = Join-Path $destination ('.mcp-dm-skills-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $staging
try {
    foreach ($skillName in $names) { Copy-Item -LiteralPath (Join-Path $source $skillName) -Destination $staging -Recurse }
    foreach ($skillName in $names) {
        # Directory.Move refuses a racing existing target instead of merging.
        [IO.Directory]::Move((Join-Path $staging $skillName), (Join-Path $destination $skillName))
    }
} finally {
    # Only remove the exact fresh staging directory created above, never a
    # pre-existing Skill or the destination directory.
    $stagingAbsolute = [IO.Path]::GetFullPath($staging)
    $destinationPrefix = $destination.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $stagingAbsolute.StartsWith($destinationPrefix, [StringComparison]::OrdinalIgnoreCase) -or (Split-Path $stagingAbsolute -Leaf) -notmatch '^\.mcp-dm-skills-[0-9a-f]{32}$') {
        throw 'Staging cleanup target failed its directory safety check.'
    }
    if (Test-Path -LiteralPath $stagingAbsolute) { Remove-Item -LiteralPath $stagingAbsolute -Recurse -Force }
}
Write-Output "Installed the three microscopy Skills under $destination. Existing Skills were preserved. Refresh the client's Skill discovery; copying does not prove model invocation."
