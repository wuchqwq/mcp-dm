param(
    [Parameter(Mandatory=$true)][string]$SessionDirectory,
    [Parameter(Mandatory=$true)][ValidateRange(1,2147483647)][int]$ExpectedDmPid,
    [Parameter(Mandatory=$true)]
    [ValidateSet('register','after_return','second','after_second','cleanup','after_cleanup','verify','release','external')]
    [string]$Step,
    [ValidatePattern('^[0-9a-f]{32}$')][string]$RequestId,
    [switch]$AllowUnvalidatedForwarding
)
# Read-only preflight. The failed /ef transport is retired, including its override.
# No process launch, script dispatch, window input, DM API, or session write.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $SessionDirectory).Path
$hosts = @(Get-Process -Name DigitalMicrograph -ErrorAction SilentlyContinue)
$observed = @($hosts | ForEach-Object {
    @{pid=$_.Id; responding=[bool]$_.Responding;
      has_main_window=($_.MainWindowHandle -ne 0)}
})
$reasons = @('ef_transport_retired_after_native_failure', 'python_slot_unknown')
$bridgeListening = $null
try {
    $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.LocalPort -eq 8765 })
    $bridgeListening = ($listeners.Count -gt 0)
} catch { $reasons += 'bridge_port_query_failed_unknown' }
if ($hosts.Count -ne 1) { $reasons += 'missing_or_multiple_dm_processes' }
$expected = @($hosts | Where-Object { $_.Id -eq $ExpectedDmPid })
if ($expected.Count -ne 1) { $reasons += 'expected_host_missing' }
elseif (-not $expected[0].Responding -or $expected[0].MainWindowHandle -eq 0) {
    $reasons += 'expected_host_not_interactive'
}
if ($bridgeListening -eq $true) { $reasons += 'bridge_port_listening_slot_conflict_or_unknown' }
if ($AllowUnvalidatedForwarding) { $reasons += 'legacy_override_no_longer_permitted' }
$registration = Join-Path $root 'registered.json'
if (Test-Path -LiteralPath $registration -PathType Leaf) {
    $state = Get-Content -LiteralPath $registration -Raw | ConvertFrom-Json
    if ($state.host_pid -ne $ExpectedDmPid) { $reasons += 'registration_host_mismatch' }
    # A matching receipt is historical evidence, never current slot/liveness proof.
}
@{state='refused_not_dispatched'; dispatched=$false; step=$Step;
  observed_hosts=$observed; bridge_port_listening=$bridgeListening;
  python_slot='unknown'; reasons=$reasons} | ConvertTo-Json -Depth 5
exit 2
