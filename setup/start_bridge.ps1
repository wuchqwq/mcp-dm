param(
    [ValidateRange(1,65535)][int]$Port = 8765,
    [string]$RuntimeDirectory = (Join-Path $PSScriptRoot '..\runtime'),
    [string]$DmExecutable = $(if ($env:DM_GMS_EXE) { $env:DM_GMS_EXE } else { Join-Path $env:ProgramFiles 'Gatan\DigitalMicrograph.exe' }),
    [string]$GatanLogDirectory = (Join-Path $env:ProgramData 'Gatan\Logs'),
    [switch]$Stop
)
$ErrorActionPreference = 'Stop'

function Invoke-Bridge([string]$Operation) {
    $client = [Net.Sockets.TcpClient]::new()
    try {
        if (-not $client.ConnectAsync('127.0.0.1', $Port).Wait(800)) { return $null }
        $client.ReceiveTimeout = 1500
        $stream = $client.GetStream()
        $request = @{id=1;op=$Operation;args=@{}} | ConvertTo-Json -Compress
        $bytes = [Text.Encoding]::UTF8.GetBytes($request + "`n")
        $stream.Write($bytes,0,$bytes.Length)
        $reader = [IO.StreamReader]::new($stream,[Text.Encoding]::UTF8)
        $reply = $reader.ReadLine() | ConvertFrom-Json
        if (-not $reply.ok) { throw $reply.error }
        return $reply.result
    } catch { return $null }
    finally { $client.Dispose() }
}

function Test-BridgePort {
    $probe = [Net.Sockets.TcpClient]::new()
    try { return ($probe.ConnectAsync('127.0.0.1',$Port).Wait(800) -and $probe.Connected) }
    catch { return $false }
    finally { $probe.Dispose() }
}

$status = Invoke-Bridge 'ping'
if ($status) {
    if ($status.backend -ne 'digitalmicrograph') { throw 'Port is occupied by a non-DM backend; refusing to use it.' }
    if ($Stop) {
        $stopped = Invoke-Bridge 'shutdown'
        if (-not $stopped.stopping) { throw 'Shutdown not acknowledged; check DM.' }
        $stopped | ConvertTo-Json
    } else { $status | ConvertTo-Json -Depth 8 }
    return
}
if (Test-BridgePort) { throw 'Bridge port is listening but did not answer (busy/unknown). Close the MCP connection and retry; no duplicate script was started.' }
if ($Stop) { Write-Output 'Bridge is already stopped.'; return }

$bridgePath = (Resolve-Path (Join-Path $PSScriptRoot '..\bridge\dm_bridge.py')).Path
$dmExe = [IO.Path]::GetFullPath($DmExecutable)
if (-not (Test-Path -LiteralPath $dmExe)) { throw "DM not installed at $dmExe" }
[IO.Directory]::CreateDirectory([IO.Path]::GetFullPath($RuntimeDirectory)) | Out-Null
$runtimePath = (Resolve-Path -LiteralPath $RuntimeDirectory).Path
if ($runtimePath.Contains('"')) { throw 'Runtime path cannot contain quotes.' }
$pythonPath = Join-Path $runtimePath 'bootstrap.py'
$scriptPath = Join-Path $runtimePath 'bootstrap.s'
$logPath = Join-Path $runtimePath 'bridge.log'
$bridgeLiteral = ConvertTo-Json -InputObject $bridgePath -Compress
$logLiteral = ConvertTo-Json -InputObject $logPath -Compress
$pythonSource = @"
import os, sys, traceback
os.environ['DM_BRIDGE_HOST'] = '127.0.0.1'
os.environ['DM_BRIDGE_PORT'] = '$Port'
os.environ['DM_BRIDGE_MOCK'] = '0'
os.environ['DM_MCP_ALLOW_DMSCRIPT'] = '0'
old_stdout, old_stderr, old_argv = sys.stdout, sys.stderr, sys.argv[:]
if not sys.argv: sys.argv = [$bridgeLiteral]
log = open($logLiteral, 'a', encoding='utf-8', buffering=1)
try:
    sys.stdout = sys.stderr = log
    namespace = {'__name__': '__main__', '__file__': $bridgeLiteral}
    with open($bridgeLiteral, 'r', encoding='utf-8') as source:
        exec(compile(source.read(), $bridgeLiteral, 'exec'), namespace)
except Exception:
    traceback.print_exc(file=log)
finally:
    sys.stdout, sys.stderr, sys.argv = old_stdout, old_stderr, old_argv
    log.close()
"@
$utf8 = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText($pythonPath,$pythonSource,$utf8)
$dmScript = 'ExecutePythonScriptFile("' + $pythonPath.Replace('\','/') + '", 1)'
[IO.File]::WriteAllText($scriptPath,$dmScript,$utf8)
$existing = @(Get-Process -Name DigitalMicrograph -ErrorAction SilentlyContinue)
if ($existing.Count -gt 1) { throw 'Multiple DM processes exist; resolve their startup/error windows first.' }
$launchArgs = @('/ef', ('"' + $scriptPath + '"'))
if (-not $existing.Count) {
    # Let plugin initialization finish before asking the embedded interpreter to
    # run a background script. Cold-start /ef was observed to fault python37.dll.
    $primary = Start-Process -FilePath $dmExe -WindowStyle Normal -PassThru
    if (-not $primary.WaitForInputIdle(30000)) { throw 'DM did not become interactive.' }
    $readyDeadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        $primary.Refresh()
        if ($primary.HasExited) { throw 'DM exited during startup.' }
        $logFile = Join-Path $GatanLogDirectory ((Get-Date -Format 'yyyy-MM-dd') + '.DM.log')
        $ready = (Test-Path -LiteralPath $logFile) -and ((Get-Content -LiteralPath $logFile -Tail 80) -match 'GMS version|Numpy version|completed CheckPythonError')
        if ($ready -and $primary.MainWindowHandle -ne 0 -and $primary.Responding) { break }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $readyDeadline)
    if (-not $ready) { throw 'DM plugins did not finish initialization.' }
    Start-Sleep -Milliseconds 1000
    $existing = @($primary)
}
$launcher = Start-Process -FilePath $dmExe -ArgumentList $launchArgs -WindowStyle Hidden -PassThru
$deadline = [DateTime]::UtcNow.AddSeconds(45)
while ([DateTime]::UtcNow -lt $deadline) {
    $status = Invoke-Bridge 'ping'
    if ($status) {
        if ($status.backend -ne 'digitalmicrograph') { throw 'Started backend is not real DM.' }
        if ($existing.Count -and $launcher.Id -ne $status.host_pid) {
            # GMS forwards /ef, then its secondary process may leave a startup
            # warning. Only this invocation's helper is terminated, never DM.
            if (-not $launcher.HasExited) { $launcher.Kill() }
        }
        $status | ConvertTo-Json -Depth 8
        return
    }
    Start-Sleep -Milliseconds 250
}
throw "Real bridge did not start. Inspect $logPath and the DM Results window; no mock fallback was used."
