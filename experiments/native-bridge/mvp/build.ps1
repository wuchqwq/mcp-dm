param(
    [string]$Cxx = "clang++.exe",
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "build"),
    [switch]$OfflineOnly
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$compilerPath = (Get-Command $Cxx -ErrorAction Stop).Source
$common = @("-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-static", "-D_WIN32_WINNT=0x0602", "-I", $PSScriptRoot)
function Invoke-Compile([string[]]$Arguments) {
    & $compilerPath @common @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Native build failed with exit code $LASTEXITCODE" }
}
Invoke-Compile @((Join-Path $PSScriptRoot "core.cpp"), (Join-Path $PSScriptRoot "core_tests.cpp"), "-o", (Join-Path $OutputDirectory "core_tests.exe"))
Invoke-Compile @((Join-Path $PSScriptRoot "core.cpp"), (Join-Path $PSScriptRoot "adapter_tests.cpp"), "-lversion", "-lbcrypt", "-o", (Join-Path $OutputDirectory "adapter_tests.exe"))
Invoke-Compile @((Join-Path $PSScriptRoot "core.cpp"), (Join-Path $PSScriptRoot "bridge.cpp"), (Join-Path $PSScriptRoot "fake_adapter.cpp"), (Join-Path $PSScriptRoot "fake_host.cpp"), "-ladvapi32", "-luser32", "-o", (Join-Path $OutputDirectory "fake_host.exe"))
if (-not $OfflineOnly) {
    Invoke-Compile @("-shared", (Join-Path $PSScriptRoot "core.cpp"), (Join-Path $PSScriptRoot "bridge.cpp"), (Join-Path $PSScriptRoot "dm_adapter.cpp"), (Join-Path $PSScriptRoot "plugin.cpp"), "-ladvapi32", "-luser32", "-lversion", "-lbcrypt", "-o", (Join-Path $OutputDirectory "dm_native_bridge.dll"))
}
Write-Output "Native artifacts built in $OutputDirectory"
