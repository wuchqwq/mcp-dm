param(
    [Parameter(Mandatory=$true)][string]$SessionDirectory,
    [Parameter(Mandatory=$true)][ValidateRange(1,2147483647)][int]$ExpectedDmPid,
    [Parameter(Mandatory=$true)]
    [ValidateSet('register','after_return','second','after_second','cleanup','after_cleanup','verify','release','external')]
    [string]$Step,
    [ValidatePattern('^[0-9a-f]{32}$')][string]$RequestId,
    [switch]$AllowUnvalidatedForwarding
)
# Quarantined experiment: observed /ef forwarding leaves a helper process alive.
# Reject a known-missing host; never kill a process, retry a dispatched step,
# or use the production MCP gate.
# /ef itself has a check-to-launch race: this is not an existing-instance-only API.
$ErrorActionPreference = 'Stop'
if (-not $AllowUnvalidatedForwarding) {
    throw 'Disabled by default: real-host /ef forwarding left a helper alive. Read FINDINGS.md; this is not reliable transport.'
}
$root = (Resolve-Path -LiteralPath $SessionDirectory).Path
if ($root -match '["\r\n]' -or $root -match '[^\x20-\x7E]') {
    throw 'Experiment paths must be ASCII without quotes or line breaks.'
}
$pythonSteps = @{
    register='01_register.py'; second='03_second_script.py'; cleanup='06_cleanup.py';
    verify='08_verify_cleanup.py'; release='09_release.py'
}
$dmSteps = @{after_return='02_after_return.s'; after_second='04_after_second.s'; after_cleanup='07_after_cleanup.s'}
if ($Step -eq 'external' -and -not $RequestId) { throw 'External step requires RequestId.' }
$label = if ($Step -eq 'external') { 'external_' + $RequestId } else { $Step }
$receipt = Join-Path $root ('dispatch_' + $label + '.json')
if (Test-Path -LiteralPath $receipt) { throw 'Already attempted; status may be unknown. Do not automatically redispatch.' }
$script = Join-Path $root ('invoke_' + $label + '.s')
if ($pythonSteps.ContainsKey($Step)) {
    $py = Join-Path $root $pythonSteps[$Step]
    if (-not (Test-Path -LiteralPath $py -PathType Leaf)) { throw 'Prepared Python step missing.' }
    $text = 'ExecutePythonScriptFile("' + $py.Replace('\','/') + '", 0)' + "`n" +
        'Result("C1 fixed Python step returned\n")' + "`n"
} else {
    $name = if ($Step -eq 'external') { 'external_' + $RequestId + '.s' } else { $dmSteps[$Step] }
    $script = (Resolve-Path -LiteralPath (Join-Path $root $name)).Path
    $text = $null
}
if ($null -ne $text) {
    $stream = [IO.File]::Open($script,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    try { $bytes=[Text.Encoding]::UTF8.GetBytes($text); $stream.Write($bytes,0,$bytes.Length) }
    finally { $stream.Dispose() }
}
$hosts = @(Get-Process -Name DigitalMicrograph -ErrorAction SilentlyContinue)
if ($hosts.Count -ne 1 -or $hosts[0].Id -ne $ExpectedDmPid) { throw 'Expected exactly the user-opened DM PID. No process started.' }
$primary = $hosts[0]
if (-not $primary.Responding -or $primary.MainWindowHandle -eq 0) { throw 'DM is not interactive; no dispatch.' }
# Any listening Bridge is a slot conflict; no unknown-thread API or second Bridge.
$tcp=[Net.Sockets.TcpClient]::new()
try {
    try { $connected=$tcp.ConnectAsync('127.0.0.1',8765).Wait(700) -and $tcp.Connected }
    catch { $connected=$false }
    if ($connected) { throw 'Bridge port is occupied. Disconnect clients and normally stop it first.' }
} finally { $tcp.Dispose() }
if ($Step -ne 'register') {
    $state=Get-Content -LiteralPath (Join-Path $root 'registered.json') -Raw | ConvertFrom-Json
    if ($state.host_pid -ne $ExpectedDmPid) { throw 'Listener belongs to another/expired host process.' }
}
$primary.Refresh()
if ($primary.HasExited -or -not $primary.Responding) { throw 'Host disappeared; no dispatch.' }
$attempt = @{step=$Step; host_pid=$ExpectedDmPid; script_sha256=(Get-FileHash -LiteralPath $script -Algorithm SHA256).Hash; state='dispatching_unknown_until_receipt'}
$stream=[IO.File]::Open($receipt,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
try { $bytes=[Text.Encoding]::UTF8.GetBytes(($attempt | ConvertTo-Json)); $stream.Write($bytes,0,$bytes.Length) }
finally { $stream.Dispose() }
# Official /ef forwards a script to the open application. No cold-start fallback.
# An unavoidable race remains if the user closes DM after the final check.
$forwarder=Start-Process -FilePath $primary.Path -ArgumentList @('/ef',('"'+$script+'"')) -WindowStyle Hidden -PassThru
$helperExited=$forwarder.WaitForExit(5000)
@{step=$Step; expected_host_pid=$ExpectedDmPid; helper_pid=$forwarder.Id;
  helper_exited=$helperExited; state='dispatched_result_requires_artifact_check'} | ConvertTo-Json
if (-not $helperExited) { throw 'Forwarding process still exists; stop further dispatch. No process was killed.' }
