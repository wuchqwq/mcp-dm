# Compatibility entry point: builds the replacement MVP, never the retired probe.
param(
    [string]$Cxx = "clang++.exe",
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "mvp\build"),
    [switch]$OfflineOnly
)
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "mvp\build.ps1") -Cxx $Cxx -OutputDirectory $OutputDirectory -OfflineOnly:$OfflineOnly
if (-not $?) { throw "Replacement native MVP build failed" }
