[CmdletBinding()]
param(
    [Parameter(Mandatory)][string[]]$TaskId,
    [ValidateRange(1, 500)][int]$Tail = 80,
    [switch]$Follow
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$requestedTaskIds = @($TaskId)
$requestedTail = $Tail
$requestedFollow = $Follow
$bridgeRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'bridge.ps1') -Command bootstrap -BridgeTest

if ($requestedFollow -and $requestedTaskIds.Count -ne 1) {
    throw '-Follow accepts exactly one TaskId.'
}

foreach ($id in $requestedTaskIds) {
    Assert-SafeId -Value $id -Label 'TaskId'
    $taskDirectory = Join-Path (Join-Path $bridgeRoot 'tasks') $id
    $statePath = Join-Path $taskDirectory 'state.json'
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        throw "Task not found: $id"
    }
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $attempt = [Math]::Max(1, [int]$state.attempt)
    $logPath = Join-Path (Join-Path $bridgeRoot 'runtime/logs') ("{0}.attempt-{1:D3}.stdout.log" -f $id, $attempt)
    Write-Output ("=== {0} status={1} attempt={2}" -f $id, $state.status, $attempt)
    if (-not (Test-Path -LiteralPath $logPath -PathType Leaf)) {
        Write-Output '(no stdout log yet)'
        continue
    }
    Get-Content -LiteralPath $logPath -Tail $requestedTail -Wait:$requestedFollow | ForEach-Object {
        $summary = Get-JsonEventSummary -Line $_
        if ($summary) { Write-Output $summary }
    }
}
