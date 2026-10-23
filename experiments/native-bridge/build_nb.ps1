# Build nb_probe.dll with LLVM only (no Visual Studio, no Windows SDK).
#   powershell -ExecutionPolicy Bypass -File build_nb.ps1
$ErrorActionPreference = 'Stop'

$llvm    = 'F:\tools\clang+llvm-23.1.4-x86_64-pc-windows-msvc\bin'
$clang   = Join-Path $llvm 'clang-cl.exe'
$lld     = Join-Path $llvm 'lld-link.exe'
$dlltool = Join-Path $llvm 'llvm-dlltool.exe'
$here    = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Test-Path $clang)) { throw "clang-cl not found at $clang" }

Push-Location $here
try {
    & $dlltool -m i386:x86-64 -d kernel32.def -l kernel32.lib
    if ($LASTEXITCODE -ne 0) { throw 'llvm-dlltool (kernel32) failed' }
    & $dlltool -m i386:x86-64 -d user32.def -l user32.lib
    if ($LASTEXITCODE -ne 0) { throw 'llvm-dlltool (user32) failed' }

    # /GS- no stack cookies, no exceptions/RTTI, no CRT; -fno-builtin keeps the
    # hand-written memcpy/memset from being optimised into calls to themselves.
    & $clang /nologo /c /O2 /GS- /EHs- /GR- /std:c++17 -fno-builtin nb_probe.cpp /Fonb_probe.obj
    if ($LASTEXITCODE -ne 0) { throw 'compile failed' }

    & $lld /dll /noentry /nodefaultlib /machine:x64 /out:nb_probe.dll nb_probe.obj kernel32.lib user32.lib
    if ($LASTEXITCODE -ne 0) { throw 'link failed' }

    Write-Host "built: $here\nb_probe.dll"
} finally {
    Pop-Location
}
