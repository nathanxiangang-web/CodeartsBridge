[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$TaskId,
    [switch]$KeepOpen,
    [ValidateRange(1, 500)][int]$Tail = 20
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# watch-remote-task.ps1 - Independent read-only observer for worker task progress.
# Reads log files by byte offset, does NOT bind to worker stdout pipe.
# Window close / Ctrl+C does NOT terminate the worker process.
# The log file is the source of truth; this window is a display layer only.

$bridgeRoot = Split-Path -Parent $PSScriptRoot
$_savedTaskId = $TaskId
$_savedKeepOpen = [bool]$KeepOpen
$_savedTail = $Tail
. (Join-Path $PSScriptRoot 'bridge.ps1') -Command bootstrap -BridgeTest
$TaskId = $_savedTaskId
$KeepOpen = $_savedKeepOpen
$Tail = $_savedTail

$finalStatuses = @('DONE','FAILED','BLOCKED','AUTH_REQUIRED','ASSISTANCE_REQUIRED','CANCELLED','REVIEW_REQUIRED','PASS','TIMED_OUT')

function Mask-Sensitive {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return '' }
    $m = $Text
    $m = $m -replace '(?i)\b(password|passwd|pwd)\b\s*[=:]\s*\S+', '$1=***'
    $m = $m -replace '(?i)\b(cookie|token|bearer|api[_-]?key|ak|sk)\b\s*[=:]\s*\S+', '$1=***'
    $m = $m -replace '(?i)Authorization:\s*Bearer\s+\S+', 'Authorization: Bearer ***'
    $m = $m -replace '(?i)\b(secret|credential)\b\s*[=:]\s*\S+', '$1=***'
    if ($m.Length -gt 160) { $m = $m.Substring(0, 160) + '...' }
    return $m
}

function Get-Phase {
    param([string]$LastTool, [int]$ThinkCount, [int]$ToolCount, [int]$OutboxCount)
    if ($OutboxCount -gt 0) { return 'delivering' }
    if ($LastTool -match 'bash|pwsh|pytest|test|npm') { return 'testing' }
    if ($LastTool -match 'edit|write|set-content|add-content') { return 'writing' }
    if ($LastTool -match 'read|grep|glob|get-content|search') { return 'reading' }
    if ($ThinkCount -gt 0 -and $ToolCount -eq 0) { return 'thinking' }
    return 'idle'
}

function Get-WorkerNum {
    param([string]$Tid)
    if ($Tid -match '-w0(\d)-') { return $matches[1] }
    return '?'
}

function Show-Category {
    param([string]$Cat, [string]$Text)
    $masked = Mask-Sensitive -Text $Text
    if ($masked) { [Console]::WriteLine("[$Cat] $masked") }
}

function Watch-SingleTask {
    param([string]$Tid)

    Assert-SafeId -Value $Tid -Label 'TaskId'
    $taskDirectory = Join-Path (Join-Path $bridgeRoot 'tasks') $Tid
    $statePath = Join-Path $taskDirectory 'state.json'
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        throw "Task not found: $Tid"
    }

    # Single-instance lock
    $lockPath = Join-Path $taskDirectory 'watcher.lock'
    $lockStream = $null
    try {
        $lockStream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    } catch {
        Write-Output "Watcher already running for $Tid. Use -KeepOpen to override."
        return
    }

    try {
        $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $attempt = [Math]::Max(1, [int]$state.attempt)
        $workerNum = Get-WorkerNum -Tid $Tid
        $projectId = if ($state.PSObject.Properties.Name -contains 'projectId') { [string]$state.projectId } else { '?' }

        $title = "Worker-$workerNum | $Tid"
        try { $Host.UI.RawUI.WindowTitle = $title } catch {}

        $logPath = Join-Path (Join-Path $bridgeRoot 'runtime/logs') ("{0}.attempt-{1:D3}.stdout.log" -f $Tid, $attempt)

        Show-Category -Cat '状态' -Text "RUNNING | task=$Tid attempt=$attempt proj=$projectId"

        $eventsCount = 0
        $thinkCount = 0
        $toolCount = 0
        $lastTool = ''
        $lastActivityAt = $null
        $byteOffset = 0
        $halfLine = ''
        $started = [DateTimeOffset]::Now
        $lastHeartbeat = $started
        $taskDone = $false
        $finalStatus = $null
        $logStableSince = $null

        # Load history from existing log
        if (Test-Path -LiteralPath $logPath -PathType Leaf) {
            $existingBytes = [System.IO.File]::ReadAllBytes($logPath)
            $byteOffset = $existingBytes.Length
            $existingText = [System.Text.Encoding]::UTF8.GetString($existingBytes)
            $allLines = @($existingText -split "`n")
            $startIdx = [Math]::Max(0, $allLines.Count - $Tail)
            for ($i = $startIdx; $i -lt $allLines.Count; $i++) {
                $line = $allLines[$i].TrimEnd("`r")
                if ([string]::IsNullOrWhiteSpace($line)) { continue }
                $summary = Get-JsonEventSummary -Line $line
                if ($summary) {
                    [Console]::WriteLine($summary)
                    $eventsCount++
                    if ($summary.StartsWith('[think]')) { $thinkCount++ }
                    elseif ($summary -match ' tool=(\S+)') { $toolCount++; $lastTool = $matches[1] }
                }
            }
            if ($eventsCount -gt 0) {
                Show-Category -Cat '状态' -Text "Loaded $eventsCount historical events"
            }
        }

        # Main observation loop
        while (-not $taskDone) {
            Start-Sleep -Milliseconds 500
            $now = [DateTimeOffset]::Now

            # Check state.json for final status
            try {
                $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
                $currentStatus = [string]$state.status
                if ($currentStatus -in $finalStatuses -and -not $finalStatus) {
                    $finalStatus = $currentStatus
                }
            } catch {}

            # Incremental log read by byte offset
            if (Test-Path -LiteralPath $logPath -PathType Leaf) {
                try {
                    $fs = [System.IO.File]::Open($logPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                    if ($byteOffset -lt $fs.Length) {
                        $fs.Seek($byteOffset, [System.IO.SeekOrigin]::Begin) | Out-Null
                        $sr = [System.IO.StreamReader]::new($fs, [System.Text.Encoding]::UTF8)
                        while (-not $sr.EndOfStream) {
                            $line = $sr.ReadLine()
                            $fullLine = $halfLine + $line
                            $halfLine = ''
                            if ([string]::IsNullOrWhiteSpace($fullLine)) { continue }
                            $summary = Get-JsonEventSummary -Line $fullLine
                            if ($summary) {
                                [Console]::WriteLine($summary)
                                $eventsCount++
                                $lastActivityAt = $now
                                if ($summary.StartsWith('[think]')) {
                                    $thinkCount++
                                    Show-Category -Cat '思考' -Text ($summary -replace '^\[think\]\s*', '')
                                } elseif ($summary -match ' tool=(\S+)') {
                                    $toolCount++
                                    $lastTool = $matches[1]
                                    Show-Category -Cat '工具' -Text $summary
                                } elseif ($summary -match '\[event\]') {
                                    Show-Category -Cat '事件' -Text $summary
                                }
                            } else {
                                $trimmed = $fullLine.TrimStart()
                                if ($trimmed.StartsWith('{') -and -not $trimmed.EndsWith('}')) {
                                    $halfLine = $fullLine
                                } elseif ($trimmed -match 'error|fail|warn|exception' -and $trimmed.Length -gt 5) {
                                    Show-Category -Cat '错误' -Text $fullLine
                                }
                            }
                        }
                        $byteOffset = $fs.Position
                        $sr.Dispose()
                    }
                    $fs.Dispose()
                } catch {}
            }

            # Heartbeat every 5 seconds
            if (($now - $lastHeartbeat).TotalSeconds -ge 5) {
                $lastHeartbeat = $now
                $elapsed = ($now - $started).ToString('mm\:ss')
                $lastAgo = if ($lastActivityAt) { [int]($now - $lastActivityAt).TotalSeconds } else { 0 }
                $outboxDir = Join-Path $taskDirectory 'outbox'
                $outboxCount = 0
                if (Test-Path -LiteralPath $outboxDir) {
                    $outboxCount = @(Get-ChildItem -LiteralPath $outboxDir -File -ErrorAction SilentlyContinue).Count
                }
                $phase = Get-Phase -LastTool $lastTool -ThinkCount $thinkCount -ToolCount $toolCount -OutboxCount $outboxCount
                [Console]::WriteLine("[心跳] $elapsed | 事件=$eventsCount 思考=$thinkCount 工具=$toolCount 产出=$outboxCount 阶段=$phase 最后活动=${lastAgo}s前")
            }

            # Final status: wait for log to stabilize 1s, then exit loop
            if ($finalStatus) {
                $currentSize = if (Test-Path -LiteralPath $logPath) { (Get-Item -LiteralPath $logPath).Length } else { 0 }
                if ($currentSize -le $byteOffset) {
                    if (-not $logStableSince) { $logStableSince = $now }
                    elseif (($now - $logStableSince).TotalSeconds -ge 1) {
                        $taskDone = $true
                    }
                } else {
                    $logStableSince = $null
                }
            }
        }

        # Final display
        [Console]::WriteLine('')
        [Console]::WriteLine("===== 任务完成: $finalStatus =====")

        $resultPath = Join-Path $taskDirectory 'outbox\RESULT.md'
        if (Test-Path -LiteralPath $resultPath -PathType Leaf) {
            [Console]::WriteLine('')
            [Console]::WriteLine('--- RESULT.md (first 20 lines) ---')
            $lines = Get-Content -LiteralPath $resultPath -Encoding UTF8 -TotalCount 20 -ErrorAction SilentlyContinue
            if ($lines) { foreach ($l in $lines) { [Console]::WriteLine($l) } }
        }

        $testsPath = Join-Path $taskDirectory 'outbox\TESTS.md'
        if (Test-Path -LiteralPath $testsPath -PathType Leaf) {
            [Console]::WriteLine('')
            [Console]::WriteLine('--- TESTS.md (first 15 lines) ---')
            $lines = Get-Content -LiteralPath $testsPath -Encoding UTF8 -TotalCount 15 -ErrorAction SilentlyContinue
            if ($lines) { foreach ($l in $lines) { [Console]::WriteLine($l) } }
        }

        $diffPath = Join-Path $taskDirectory 'outbox\DIFF.stat'
        if (Test-Path -LiteralPath $diffPath -PathType Leaf) {
            [Console]::WriteLine('')
            [Console]::WriteLine('--- DIFF.stat ---')
            $lines = Get-Content -LiteralPath $diffPath -Encoding UTF8 -ErrorAction SilentlyContinue
            if ($lines) { foreach ($l in $lines) { [Console]::WriteLine($l) } }
        }

        [Console]::WriteLine('')
        [Console]::WriteLine("Final: $finalStatus | Log: $logPath")
        [Console]::WriteLine("Events: $eventsCount  Think: $thinkCount  Tool: $toolCount")

        if (-not $KeepOpen) {
            [Console]::WriteLine('')
            for ($i = 10; $i -gt 0; $i--) {
                [Console]::Write("`r>>> ${i}s 后自动关闭... Ctrl+C 保留窗口 <<<    ")
                Start-Sleep -Seconds 1
            }
            [Console]::WriteLine('')
        }
    } finally {
        if ($lockStream) { $lockStream.Dispose() }
        if (Test-Path -LiteralPath $lockPath -ErrorAction SilentlyContinue) {
            Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
        }
    }
}

Watch-SingleTask -Tid $TaskId