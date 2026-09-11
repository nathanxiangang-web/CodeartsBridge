[CmdletBinding()]
param(
    [int]$Interval = 5,
    [int]$MaxRounds = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$bridgeRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'bridge.ps1') -Command bootstrap -BridgeTest

$tasksDir = Join-Path $bridgeRoot 'tasks'
$logsDir = Join-Path $bridgeRoot 'runtime/logs'
$activeStates = @('QUEUED', 'STARTING', 'RUNNING', 'READY')

function Get-ActiveTasks {
    $result = @()
    Get-ChildItem -LiteralPath $tasksDir -Directory | ForEach-Object {
        $statePath = Join-Path $_.FullName 'state.json'
        if (Test-Path -LiteralPath $statePath -PathType Leaf) {
            $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
            if ($state.status -in $activeStates) {
                $metaPath = Join-Path $_.FullName 'META.json'
                $worker = ''
                if (Test-Path -LiteralPath $metaPath -PathType Leaf) {
                    $meta = Get-Content -LiteralPath $metaPath -Raw | ConvertFrom-Json
                    $worker = $meta.workerId
                }
                $hb = $null
                if ($state.PSObject.Properties['lastHeartbeat']) { $hb = $state.lastHeartbeat }
                $pid_val = $null
                if ($state.PSObject.Properties['processId']) { $pid_val = $state.processId }
                $hbSummary = ''
                if ($state.PSObject.Properties['heartbeatSummary']) { $hbSummary = [string]$state.heartbeatSummary }
                $hbEvents = $null
                if ($state.PSObject.Properties['heartbeatEvents']) { $hbEvents = $state.heartbeatEvents }
                $hbThink = $null
                if ($state.PSObject.Properties['heartbeatThink']) { $hbThink = $state.heartbeatThink }
                $hbTool = $null
                if ($state.PSObject.Properties['heartbeatTool']) { $hbTool = $state.heartbeatTool }
                $result += [PSCustomObject]@{
                    TaskId  = $state.taskId
                    Status  = $state.status
                    Attempt = [int]$state.attempt
                    Worker  = $worker
                    Heartbeat = $hb
                    Pid     = $pid_val
                    HbSummary = $hbSummary
                    HbEvents = $hbEvents
                    HbThink  = $hbThink
                    HbTool   = $hbTool
                }
            }
        }
    }
    return $result
}

function Get-LastEventSummary {
    param([string]$TaskId, [int]$Attempt)
    $logPath = Join-Path $logsDir ("{0}.attempt-{1:D3}.stdout.log" -f $TaskId, $Attempt)
    if (-not (Test-Path -LiteralPath $logPath -PathType Leaf)) { return '(no log yet)' }
    $lastLine = Get-Content -LiteralPath $logPath -Tail 1 -ErrorAction SilentlyContinue
    if (-not $lastLine) { return '(empty log)' }
    $summary = Get-JsonEventSummary -Line $lastLine
    return $summary
}

$round = 0
while ($true) {
    $round++
    $now = Get-Date -Format 'HH:mm:ss'
    Write-Output ("`n======== [{0}] round {1} ========" -f $now, $round)

    $tasks = @(Get-ActiveTasks)
    if ($tasks.Count -eq 0) {
        Write-Output '(no active tasks)'
    } else {
        foreach ($t in $tasks) {
            $hbShort = ''
            if ($t.Heartbeat -is [string] -and $t.Heartbeat.Length -gt 0) {
                $hbShort = $t.Heartbeat.Substring([Math]::Max(0, $t.Heartbeat.Length - 15))
            }
            $hbExtra = ''
            if ($null -ne $t.HbEvents) { $hbExtra = " ev=$($t.HbEvents) th=$($t.HbThink) tool=$($t.HbTool)" }
            Write-Output ("`n--- {0} [{1}] worker={2} attempt={3} hb={4}{5}" -f $t.TaskId, $t.Status, $t.Worker, $t.Attempt, $hbShort, $hbExtra)
            if ($t.HbSummary) { Write-Output ("    hb-event: {0}" -f $t.HbSummary) }
            $evt = Get-LastEventSummary -TaskId $t.TaskId -Attempt ([Math]::Max(1, $t.Attempt))
            Write-Output ("    last: {0}" -f $evt)
        }
    }

    if ($MaxRounds -gt 0 -and $round -ge $MaxRounds) { break }
    Start-Sleep -Seconds $Interval
}