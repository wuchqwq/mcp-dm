@echo off
REM ============================================================
REM  Install the GMS Python runtime that DigitalMicrograph needs.
REM  Fully offline: uses the Miniconda installer + conda packages
REM  that Gatan already placed in C:\ProgramData\Gatan\Python
REM
REM  Run this as Administrator if the non-elevated attempt fails.
REM ============================================================
setlocal enabledelayedexpansion

set "SRC=C:\ProgramData\Gatan\Python"
set "MINI=C:\ProgramData\Miniconda3"
set "VENV=%MINI%\envs\GMS_VENV_PYTHON"

echo [1/4] checking prerequisites...
if not exist "%SRC%\Miniconda3.exe" (
  echo   ERROR: %SRC%\Miniconda3.exe not found.
  exit /b 1
)
if not exist "%SRC%\installGMSvenv.bat" (
  echo   ERROR: %SRC%\installGMSvenv.bat not found.
  exit /b 1
)

echo [2/4] installing Miniconda3 to %MINI% ...
if exist "%MINI%\python.exe" (
  echo   already present, skipping
) else (
  start /wait "" "%SRC%\Miniconda3.exe" /InstallationType=JustMe /RegisterPython=0 /AddToPath=0 /S /D=%MINI%
  if not exist "%MINI%\python.exe" (
    echo   ERROR: silent install did not produce %MINI%\python.exe
    echo   Re-run this script from an Administrator command prompt.
    exit /b 2
  )
)

echo [3/4] creating GMS_VENV_PYTHON (offline conda) ...
if exist "%VENV%\python.exe" (
  echo   venv already present, skipping
) else (
  pushd "%SRC%"
  call "%SRC%\installGMSvenv.bat"
  set "INSTALL_RESULT=!errorlevel!"
  popd
  if not "!INSTALL_RESULT!"=="0" exit /b !INSTALL_RESULT!
)

echo [4/4] verifying...
if not exist "%VENV%\python.exe" (
  echo   ERROR: %VENV%\python.exe missing
  exit /b 3
)
set "PATH=%VENV%;%VENV%\Library\mingw-w64\bin;%VENV%\Library\usr\bin;%VENV%\Library\bin;%VENV%\Scripts;%PATH%"
"%VENV%\python.exe" -c "import sys, ssl, numpy; print('  python', sys.version.split()[0]); print('  numpy ', numpy.__version__); print('  ssl ', ssl.OPENSSL_VERSION)"
if errorlevel 1 (
  echo ERROR: runtime verification failed.
  exit /b 4
)

echo.
echo DONE. Next: open DigitalMicrograph, Python menu, run
echo   %~dp0..\bridge\dm_bridge.py
exit /b 0
