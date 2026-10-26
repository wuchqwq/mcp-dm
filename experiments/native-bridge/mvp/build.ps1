param(
    [string]$Cxx = "clang++.exe",
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "build"),
    [switch]$OfflineOnly,
    [switch]$ImportQualificationBuild
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
Invoke-Compile @((Join-Path $PSScriptRoot "core.cpp"), (Join-Path $PSScriptRoot "read_adapter_tests.cpp"), "-lversion", "-lbcrypt", "-o", (Join-Path $OutputDirectory "read_adapter_tests.exe"))
Invoke-Compile @((Join-Path $PSScriptRoot "core.cpp"), (Join-Path $PSScriptRoot "scientific_handoff_tests.cpp"), "-lversion", "-lbcrypt", "-o", (Join-Path $OutputDirectory "scientific_handoff_tests.exe"))
Invoke-Compile @((Join-Path $PSScriptRoot "core.cpp"), (Join-Path $PSScriptRoot "result_release_tests.cpp"), "-lversion", "-lbcrypt", "-o", (Join-Path $OutputDirectory "result_release_tests.exe"))
Invoke-Compile @((Join-Path $PSScriptRoot "core.cpp"), (Join-Path $PSScriptRoot "roi_adapter_tests.cpp"), "-lversion", "-lbcrypt", "-o", (Join-Path $OutputDirectory "roi_adapter_tests.exe"))
Invoke-Compile @((Join-Path $PSScriptRoot "core.cpp"), (Join-Path $PSScriptRoot "line_profile_adapter_tests.cpp"), "-lversion", "-lbcrypt", "-o", (Join-Path $OutputDirectory "line_profile_adapter_tests.exe"))
Invoke-Compile @((Join-Path $PSScriptRoot "core.cpp"), (Join-Path $PSScriptRoot "histogram_adapter_tests.cpp"), "-lversion", "-lbcrypt", "-o", (Join-Path $OutputDirectory "histogram_adapter_tests.exe"))
Invoke-Compile @((Join-Path $PSScriptRoot "core.cpp"), (Join-Path $PSScriptRoot "frame_adapter_tests.cpp"), "-lversion", "-lbcrypt", "-o", (Join-Path $OutputDirectory "frame_adapter_tests.exe"))
Invoke-Compile @((Join-Path $PSScriptRoot "core.cpp"), (Join-Path $PSScriptRoot "import_adapter_tests.cpp"), "-lversion", "-lbcrypt", "-o", (Join-Path $OutputDirectory "import_adapter_tests.exe"))
Invoke-Compile @("-DNB_IMPORT_QUALIFICATION_BUILD=1", (Join-Path $PSScriptRoot "core.cpp"), (Join-Path $PSScriptRoot "import_adapter_tests.cpp"), "-lversion", "-lbcrypt", "-o", (Join-Path $OutputDirectory "import_candidate_tests.exe"))
Invoke-Compile @((Join-Path $PSScriptRoot "core.cpp"), (Join-Path $PSScriptRoot "pixel_adapter_tests.cpp"), "-lversion", "-lbcrypt", "-o", (Join-Path $OutputDirectory "pixel_adapter_tests.exe"))
Invoke-Compile @((Join-Path $PSScriptRoot "core.cpp"), (Join-Path $PSScriptRoot "uint32_adapter_tests.cpp"), "-lversion", "-lbcrypt", "-o", (Join-Path $OutputDirectory "uint32_adapter_tests.exe"))
Invoke-Compile @((Join-Path $PSScriptRoot "core.cpp"), (Join-Path $PSScriptRoot "uint32_operations_tests.cpp"), "-lversion", "-lbcrypt", "-o", (Join-Path $OutputDirectory "uint32_operations_tests.exe"))
Invoke-Compile @((Join-Path $PSScriptRoot "adapter_profile_tests.cpp"), "-lversion", "-lbcrypt", "-o", (Join-Path $OutputDirectory "adapter_profile_tests.exe"))
Invoke-Compile @((Join-Path $PSScriptRoot "core.cpp"), (Join-Path $PSScriptRoot "adapter_rejection_tests.cpp"), "-lversion", "-lbcrypt", "-o", (Join-Path $OutputDirectory "adapter_rejection_tests.exe"))
# Candidate POD calls are exercised only with synthetic callbacks. They are
# deliberately absent from the real-DM plugin and public protocol/catalog.
Invoke-Compile @((Join-Path $PSScriptRoot "candidate_calls.cpp"), (Join-Path $PSScriptRoot "candidate_calls_tests.cpp"), "-o", (Join-Path $OutputDirectory "candidate_calls_tests.exe"))
Invoke-Compile @((Join-Path $PSScriptRoot "core.cpp"), (Join-Path $PSScriptRoot "bridge.cpp"), (Join-Path $PSScriptRoot "fake_adapter.cpp"), (Join-Path $PSScriptRoot "fake_host.cpp"), "-ladvapi32", "-luser32", "-o", (Join-Path $OutputDirectory "fake_host.exe"))
if (-not $OfflineOnly) {
    $importFlags = @()
    if ($ImportQualificationBuild) { $importFlags = @("-DNB_IMPORT_QUALIFICATION_BUILD=1") }
    Invoke-Compile @($importFlags + @("-shared", (Join-Path $PSScriptRoot "core.cpp"), (Join-Path $PSScriptRoot "bridge.cpp"), (Join-Path $PSScriptRoot "dm_adapter.cpp"), (Join-Path $PSScriptRoot "plugin.cpp"), "-ladvapi32", "-luser32", "-lversion", "-lbcrypt", "-o", (Join-Path $OutputDirectory "dm_native_bridge.dll")))
}
Write-Output "Native artifacts built in $OutputDirectory"
