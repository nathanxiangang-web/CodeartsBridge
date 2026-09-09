[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)]
    [ValidateSet('run', 'once', 'status', 'stop')]
    [string]$Command,

    [string]$BridgeScript,
    [string]$StateDir,
    [int]$IntervalSeconds = 30,
    [int]$MaxWorkers = 4,
    [int]$MaxBackoffSeconds = 300,
    [int]$BaseBackoffSeconds = 2,
    [int]$ShutdownTimeoutSeconds = 60,
    [int]$LoopTimeoutSeconds = 600,
    [int]$MaxOutputBytes = 65536,
    [switch]$DryRun,
    [string]$FakeRunner,
    [string]$HostExecutable,
    [switch]$DaemonTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

    $script:DaemonVersion = '1.6.0'
$script:WriteAtomicTextOverride = $null
$DaemonRoot = Split-Path -Parent $PSScriptRoot

if (-not $BridgeScript) {
    $BridgeScript = Join-Path $DaemonRoot (Join-Path 'scripts' 'bridge.ps1')
}
if (-not $StateDir) {
    $StateDir = Join-Path $DaemonRoot (Join-Path 'runtime' 'daemon')
}

if (-not $HostExecutable) {
    try {
        $HostExecutable = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
    } catch {
        $HostExecutable = ''
    }
}
if (-not $HostExecutable -or -not (Test-Path -LiteralPath $HostExecutable -PathType Leaf)) {
    throw "Host executable not found or invalid: '$HostExecutable'. Pass -HostExecutable with a valid path."
}

if ($IntervalSeconds -lt 1) { throw "IntervalSeconds must be positive, got $IntervalSeconds" }
if ($IntervalSeconds -gt 86400) { throw "IntervalSeconds must be at most 86400, got $IntervalSeconds" }
if ($MaxWorkers -lt 1) { throw "MaxWorkers must be positive, got $MaxWorkers" }
if ($MaxWorkers -gt 100) { throw "MaxWorkers must be at most 100, got $MaxWorkers" }
if ($LoopTimeoutSeconds -lt 1) { throw "LoopTimeoutSeconds must be positive, got $LoopTimeoutSeconds" }
if ($LoopTimeoutSeconds -gt 86400) { throw "LoopTimeoutSeconds must be at most 86400, got $LoopTimeoutSeconds" }
if ($ShutdownTimeoutSeconds -lt 1) { throw "ShutdownTimeoutSeconds must be positive, got $ShutdownTimeoutSeconds" }
if ($ShutdownTimeoutSeconds -gt 3600) { throw "ShutdownTimeoutSeconds must be at most 3600, got $ShutdownTimeoutSeconds" }
if ($MaxBackoffSeconds -lt 1) { throw "MaxBackoffSeconds must be positive, got $MaxBackoffSeconds" }
if ($MaxBackoffSeconds -gt 86400) { throw "MaxBackoffSeconds must be at most 86400, got $MaxBackoffSeconds" }
if ($BaseBackoffSeconds -lt 1) { throw "BaseBackoffSeconds must be positive, got $BaseBackoffSeconds" }
if ($BaseBackoffSeconds -gt 3600) { throw "BaseBackoffSeconds must be at most 3600, got $BaseBackoffSeconds" }
if ($MaxOutputBytes -lt 256) { throw "MaxOutputBytes must be at least 256, got $MaxOutputBytes" }
if ($MaxOutputBytes -gt 10485760) { throw "MaxOutputBytes must be at most 10485760, got $MaxOutputBytes" }

$LockPath = Join-Path $StateDir 'daemon.lock'
$HealthPath = Join-Path $StateDir 'health.json'
$StopSentinel = Join-Path $StateDir 'STOP_REQUESTED'
function Write-AtomicText {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][AllowEmptyString()][string]$Content
    )
    if ($DaemonTest -and $script:WriteAtomicTextOverride) {
        & $script:WriteAtomicTextOverride -Path $Path -Content $Content
        return
    }
    $directory = Split-Path -Parent $Path
    [System.IO.Directory]::CreateDirectory($directory) | Out-Null
    $tempPath = Join-Path $directory ('.' + [System.IO.Path]::GetFileName($Path) + '.' + [guid]::NewGuid().ToString('N') + '.tmp')
    [System.IO.File]::WriteAllText($tempPath, $Content, [System.Text.UTF8Encoding]::new($false))
    try {
        if (Test-Path -LiteralPath $Path -PathType Leaf) {
            $backupPath = Join-Path $directory ('.' + [System.IO.Path]::GetFileName($Path) + '.' + [guid]::NewGuid().ToString('N') + '.bak')
            [System.IO.File]::Replace($tempPath, $Path, $backupPath)
            if (Test-Path -LiteralPath $backupPath -PathType Leaf) { Remove-Item -LiteralPath $backupPath -Force }
        } else {
            [System.IO.File]::Move($tempPath, $Path)
        }
    } catch {
        if (Test-Path -LiteralPath $tempPath -PathType Leaf) {
            try { Remove-Item -LiteralPath $tempPath -Force } catch {}
        }
        throw
    }
}

function Write-AtomicJson {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]$Value
    )
    Write-AtomicText -Path $Path -Content (($Value | ConvertTo-Json -Depth 12) + [Environment]::NewLine)
}

function Read-JsonFile {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Missing file: $Path"
    }
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Get-BoundedTail {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Text, [Parameter(Mandatory)][int]$MaxBytes)
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    $byteCount = $utf8.GetByteCount($Text)
    if ($byteCount -le $MaxBytes) { return $Text }
    $marker = '...[truncated]...'
    $markerBytes = $utf8.GetByteCount($marker)
    $keepBytes = $MaxBytes - $markerBytes
    if ($keepBytes -lt 1) { return $marker.Substring(0, [Math]::Min($MaxBytes, $marker.Length)) }
    $bytes = $utf8.GetBytes($Text)
    $startIdx = $bytes.Length - $keepBytes
    if ($startIdx -lt 0) { $startIdx = 0 }
    while ($startIdx -lt $bytes.Length -and $bytes[$startIdx] -ge 0x80 -and $bytes[$startIdx] -lt 0xC0) {
        $startIdx++
    }
    return $marker + $utf8.GetString($bytes, $startIdx, $bytes.Length - $startIdx)
}

function Invoke-SensitiveMask {
    param([string]$Text)
    if (-not $Text) { return '' }
    $Text = $Text -replace 'CODEARTS_CLI_AK=\S+', 'CODEARTS_CLI_AK=***'
    $Text = $Text -replace 'CODEARTS_CLI_SK=\S+', 'CODEARTS_CLI_SK=***'
    $Text = $Text -replace '(?i)Bearer\s+\S+', 'Bearer ***'
    $Text = $Text -replace '(?i)(password|token|secret|api_key)=\S+', '$1=***'
    return $Text
}

function Get-DaemonHealth {
    if (-not (Test-Path -LiteralPath $HealthPath -PathType Leaf)) { return $null }
    $maxRetries = 3
    for ($i = 0; $i -lt $maxRetries; $i++) {
        try {
            return Read-JsonFile -Path $HealthPath
        } catch {
            if ($i -eq $maxRetries - 1) { return $null }
            Start-Sleep -Milliseconds 10
        }
    }
    return $null
}

function Set-DaemonHealth {
    param(
        [Parameter(Mandatory)][string]$Status,
        [Parameter(Mandatory)][int]$Iteration,
        [string]$LastSuccessTime,
        [string]$LastError,
        [string]$LastErrorAt,
        [Parameter(Mandatory)][string]$StartTime,
        [Parameter(Mandatory)][int]$ProcessId,
        [bool]$StdOutTruncated = $false,
        [bool]$StdErrTruncated = $false,
        [bool]$DrainIncomplete = $false
    )
    $health = [ordered]@{
        schemaVersion    = 1
        daemonVersion    = $script:DaemonVersion
        status           = $Status
        pid              = $ProcessId
        startTime        = $StartTime
        iteration        = $Iteration
        lastSuccessTime  = $LastSuccessTime
        lastError        = Invoke-SensitiveMask -Text $LastError
        lastErrorAt      = $LastErrorAt
        maxWorkers       = $MaxWorkers
        intervalSeconds  = $IntervalSeconds
        stdOutTruncated  = $StdOutTruncated
        stdErrTruncated  = $StdErrTruncated
        drainIncomplete  = $DrainIncomplete
        updatedAt        = [DateTimeOffset]::Now.ToString('o')
    }
    Write-AtomicJson -Path $HealthPath -Value $health
}

function Get-BackoffDelay {
    param([int]$FailureCount, [int]$Base, [int]$Max)
    if ($FailureCount -le 0) { return 0 }
    $delay = [int]([double]$Base * [Math]::Pow(2.0, $FailureCount - 1))
    if ($delay -gt $Max) { $delay = $Max }
    if ($delay -lt 1) { $delay = 1 }
    return $delay
}


function Invoke-LoopAction {
    $runnerPath = if ($FakeRunner) { $FakeRunner } else { $BridgeScript }
    if (-not (Test-Path -LiteralPath $runnerPath -PathType Leaf)) {
        throw "Runner script not found: $runnerPath"
    }
    $argList = @('-NoProfile', '-File', $runnerPath)
    if ($FakeRunner) {
        $argList += @('-MaxWorkers', [string]$MaxWorkers, '-StateDir', $StateDir)
    } else {
        $argList += @('dispatch', '-MaxWorkers', [string]$MaxWorkers, '-Quiet')
        if ($DryRun) { $argList += @('-DryRun') }
    }
    $info = [System.Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $HostExecutable
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($a in $argList) { $info.ArgumentList.Add($a) }
    $proc = [System.Diagnostics.Process]::new()
    try {
        $proc.StartInfo = $info
        if (-not $proc.Start()) { throw 'Failed to start runner process' }
        $stdoutBase = $proc.StandardOutput.BaseStream
        $stderrBase = $proc.StandardError.BaseStream
        $utf8 = [System.Text.UTF8Encoding]::new($false)
        $marker = '...[truncated]...'
        $markerBytes = $utf8.GetByteCount($marker)
        $keepCap = [Math]::Max(1, $MaxOutputBytes - $markerBytes)
        $chunkSize = 8192
        $stdoutBuf = [byte[]]::new($chunkSize)
        $stderrBuf = [byte[]]::new($chunkSize)
        $stdoutTail = [System.IO.MemoryStream]::new()
        $stderrTail = [System.IO.MemoryStream]::new()
        $stdoutTrunc = $false
        $stderrTrunc = $false
        $stdoutDone = $false
        $stderrDone = $false
        $drainIncomplete = $false
        $stdoutTask = $stdoutBase.ReadAsync($stdoutBuf, 0, $chunkSize)
        $stderrTask = $stderrBase.ReadAsync($stderrBuf, 0, $chunkSize)
        $timeoutMs = $LoopTimeoutSeconds * 1000
        $procDeadline = [DateTimeOffset]::UtcNow.AddMilliseconds($timeoutMs)
        $drainMs = 5000
        $drainDeadline = [DateTimeOffset]::MaxValue
        $timedOut = $false
        $procExited = $false
        while (-not ($stdoutDone -and $stderrDone)) {
            if (-not $procExited) {
                if ($proc.HasExited) {
                    $procExited = $true
                    $drainDeadline = [DateTimeOffset]::UtcNow.AddMilliseconds($drainMs)
                } elseif ([DateTimeOffset]::UtcNow -gt $procDeadline) {
                    $timedOut = $true
                    $procExited = $true
                    try { $proc.Kill($true) } catch {}
                    [void]$proc.WaitForExit($drainMs)
                    $drainDeadline = [DateTimeOffset]::UtcNow.AddMilliseconds($drainMs)
                }
            }
            if ($procExited -and [DateTimeOffset]::UtcNow -gt $drainDeadline) {
                if (-not $stdoutDone -or -not $stderrDone) { $drainIncomplete = $true }
                break
            }
            if (-not $stdoutDone -and $stdoutTask.IsCompleted) {
                try { $n = $stdoutTask.GetAwaiter().GetResult() } catch { $n = 0 }
                if ($n -le 0) {
                    $stdoutDone = $true
                } else {
                    $stdoutTail.Write($stdoutBuf, 0, $n)
                    if ($stdoutTail.Length -gt ($keepCap + $chunkSize)) {
                        $stdoutTrunc = $true
                        $trimStart = [int]($stdoutTail.Length - $keepCap)
                        $stdoutTail.Position = $trimStart
                        while ($stdoutTail.Position -lt $stdoutTail.Length) {
                            $b = $stdoutTail.ReadByte()
                            if ($b -lt 0x80 -or $b -ge 0xC0) { break }
                        }
                        $keepLen = [int]($stdoutTail.Length - $stdoutTail.Position)
                        if ($keepLen -gt 0) {
                            $keepBuf = [byte[]]::new($keepLen)
                            [void]$stdoutTail.Read($keepBuf, 0, $keepLen)
                            $stdoutTail = [System.IO.MemoryStream]::new()
                            $stdoutTail.Write($keepBuf, 0, $keepLen)
                        } else {
                            $stdoutTail = [System.IO.MemoryStream]::new()
                        }
                    }
                    $stdoutTask = $stdoutBase.ReadAsync($stdoutBuf, 0, $chunkSize)
                }
            }
            if (-not $stderrDone -and $stderrTask.IsCompleted) {
                try { $n = $stderrTask.GetAwaiter().GetResult() } catch { $n = 0 }
                if ($n -le 0) {
                    $stderrDone = $true
                } else {
                    $stderrTail.Write($stderrBuf, 0, $n)
                    if ($stderrTail.Length -gt ($keepCap + $chunkSize)) {
                        $stderrTrunc = $true
                        $trimStart = [int]($stderrTail.Length - $keepCap)
                        $stderrTail.Position = $trimStart
                        while ($stderrTail.Position -lt $stderrTail.Length) {
                            $b = $stderrTail.ReadByte()
                            if ($b -lt 0x80 -or $b -ge 0xC0) { break }
                        }
                        $keepLen = [int]($stderrTail.Length - $stderrTail.Position)
                        if ($keepLen -gt 0) {
                            $keepBuf = [byte[]]::new($keepLen)
                            [void]$stderrTail.Read($keepBuf, 0, $keepLen)
                            $stderrTail = [System.IO.MemoryStream]::new()
                            $stderrTail.Write($keepBuf, 0, $keepLen)
                        } else {
                            $stderrTail = [System.IO.MemoryStream]::new()
                        }
                    }
                    $stderrTask = $stderrBase.ReadAsync($stderrBuf, 0, $chunkSize)
                }
            }
            if (-not ($stdoutDone -and $stderrDone)) { Start-Sleep -Milliseconds 10 }
        }
        if (-not $stdoutDone) { try { $stdoutBase.Close() } catch {} }
        if (-not $stderrDone) { try { $stderrBase.Close() } catch {} }
        $stdoutBytes = $stdoutTail.ToArray()
        $stderrBytes = $stderrTail.ToArray()
        $stdoutTail.Dispose()
        $stderrTail.Dispose()
        if ($stdoutBytes.Length -gt $keepCap) {
            $stdoutTrunc = $true
            $startIdx = $stdoutBytes.Length - $keepCap
            while ($startIdx -lt $stdoutBytes.Length -and $stdoutBytes[$startIdx] -ge 0x80 -and $stdoutBytes[$startIdx] -lt 0xC0) { $startIdx++ }
            if ($startIdx -ge $stdoutBytes.Length) { $stdoutBytes = [byte[]]::new(0) } else { $stdoutBytes = $stdoutBytes[$startIdx..($stdoutBytes.Length - 1)] }
        }
        if ($stderrBytes.Length -gt $keepCap) {
            $stderrTrunc = $true
            $startIdx = $stderrBytes.Length - $keepCap
            while ($startIdx -lt $stderrBytes.Length -and $stderrBytes[$startIdx] -ge 0x80 -and $stderrBytes[$startIdx] -lt 0xC0) { $startIdx++ }
            if ($startIdx -ge $stderrBytes.Length) { $stderrBytes = [byte[]]::new(0) } else { $stderrBytes = $stderrBytes[$startIdx..($stderrBytes.Length - 1)] }
        }
        $stdoutStr = $utf8.GetString($stdoutBytes)
        $stderrStr = $utf8.GetString($stderrBytes)
        if ($stdoutTrunc) { $stdoutStr = $marker + $stdoutStr }
        if ($stderrTrunc) { $stderrStr = $marker + $stderrStr }
        if ($drainIncomplete) {
            return [pscustomobject]@{
                ExitCode          = -1
                Success           = $false
                Error             = "Drain incomplete: streams still open at deadline"
                StandardOutput    = $stdoutStr
                StdOutTruncated   = $stdoutTrunc
                StdErrTruncated   = $stderrTrunc
                DrainIncomplete   = $true
            }
        }
        if ($timedOut) {
            return [pscustomobject]@{
                ExitCode          = -1
                Success           = $false
                Error             = "Loop action timed out after $LoopTimeoutSeconds seconds"
                StandardOutput    = $stdoutStr
                StdOutTruncated   = $stdoutTrunc
                StdErrTruncated   = $stderrTrunc
                DrainIncomplete   = $false
            }
        }
        return [pscustomobject]@{
            ExitCode          = $proc.ExitCode
            Success           = ($proc.ExitCode -eq 0)
            Error             = $stderrStr
            StandardOutput    = $stdoutStr
            StdOutTruncated   = $stdoutTrunc
            StdErrTruncated   = $stderrTrunc
            DrainIncomplete   = $false
        }
    } finally {
        $proc.Dispose()
    }
}

function Test-StopRequested {
    return (Test-Path -LiteralPath $StopSentinel -PathType Leaf)
}

function Clear-StopSentinel {
    if (Test-Path -LiteralPath $StopSentinel) {
        Remove-Item -LiteralPath $StopSentinel -Force
    }
}

function Start-DaemonLock {
    [System.IO.Directory]::CreateDirectory($StateDir) | Out-Null
    return [System.IO.File]::Open($LockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
}

function Invoke-DaemonLoop {
    param([switch]$SingleRun)

    $lockStream = $null
    try {
        $lockStream = Start-DaemonLock
    } catch {
        throw "Another daemon instance is already running (lock held): $LockPath"
    }

    Clear-StopSentinel
    $startTime = [DateTimeOffset]::Now.ToString('o')
    $currentPid = [System.Diagnostics.Process]::GetCurrentProcess().Id
    $iteration = 0
    $failureCount = 0
    $lastSuccessTime = ''
    $lastError = ''
    $lastErrorAt = ''
    $lastStdOutTrunc = $false
    $lastStdErrTrunc = $false
    $lastDrainIncomplete = $false

    try {
        try {
            Set-DaemonHealth -Status 'running' -Iteration 0 -LastSuccessTime '' -LastError '' -LastErrorAt '' -StartTime $startTime -ProcessId $currentPid
        } catch {}

        while ($true) {
            if (Test-StopRequested) { break }

            $iteration++
            $loopError = $null
            $actionResult = $null
            try {
                $actionResult = Invoke-LoopAction
            } catch {
                $loopError = $_
            }

            if ($loopError) {
                $lastError = [string]$loopError.Exception.Message
                $lastErrorAt = [DateTimeOffset]::Now.ToString('o')
                $failureCount++
            } elseif (-not $actionResult.Success) {
                $lastError = "Child exit code: $($actionResult.ExitCode)"
                if ($actionResult.Error) {
                    $trimmed = ($actionResult.Error -replace "[\r\n]+", " ").Trim()
                    if ($trimmed.Length -gt 200) { $trimmed = $trimmed.Substring(0, 200) + '...' }
                    $lastError += " | " + $trimmed
                }
                $lastErrorAt = [DateTimeOffset]::Now.ToString('o')
                $failureCount++
            } else {
                $lastSuccessTime = [DateTimeOffset]::Now.ToString('o')
                $failureCount = 0
                $lastError = ''
                $lastErrorAt = ''
            }

            if ($actionResult) {
                $lastStdOutTrunc = [bool]$actionResult.StdOutTruncated
                $lastStdErrTrunc = [bool]$actionResult.StdErrTruncated
                $lastDrainIncomplete = [bool]$actionResult.DrainIncomplete
            }

            try {
                Set-DaemonHealth -Status 'running' -Iteration $iteration -LastSuccessTime $lastSuccessTime -LastError $lastError -LastErrorAt $lastErrorAt -StartTime $startTime -ProcessId $currentPid -StdOutTruncated $lastStdOutTrunc -StdErrTruncated $lastStdErrTrunc -DrainIncomplete $lastDrainIncomplete
            } catch {}

            if ($SingleRun) { break }
            if (Test-StopRequested) { break }

            $sleepSeconds = if ($failureCount -gt 0) {
                Get-BackoffDelay -FailureCount $failureCount -Base $BaseBackoffSeconds -Max $MaxBackoffSeconds
            } else {
                $IntervalSeconds
            }

            $slept = 0
            while ($slept -lt $sleepSeconds) {
                if (Test-StopRequested) { break }
                $step = [Math]::Min(1, $sleepSeconds - $slept)
                Start-Sleep -Seconds $step
                $slept += $step
            }

            if (Test-StopRequested) { break }
        }
    } finally {
        try {
            Set-DaemonHealth -Status 'stopped' -Iteration $iteration -LastSuccessTime $lastSuccessTime -LastError $lastError -LastErrorAt $lastErrorAt -StartTime $startTime -ProcessId $currentPid -StdOutTruncated $lastStdOutTrunc -StdErrTruncated $lastStdErrTrunc -DrainIncomplete $lastDrainIncomplete
        } catch {}
        if ($lockStream) { $lockStream.Dispose() }
    }
}

if (-not $DaemonTest) {
    switch ($Command) {
        'run' {
            Invoke-DaemonLoop
        }
        'once' {
            Invoke-DaemonLoop -SingleRun
        }
        'status' {
            $health = Get-DaemonHealth
            if ($health) {
                $health | ConvertTo-Json -Depth 5
            } else {
                Write-Output 'No daemon health file found. Daemon may not have been started.'
            }
        }
        'stop' {
            [System.IO.Directory]::CreateDirectory($StateDir) | Out-Null
            Write-AtomicText -Path $StopSentinel -Content ([DateTimeOffset]::Now.ToString("o") + [Environment]::NewLine)

            $deadline = [DateTimeOffset]::Now.AddSeconds($ShutdownTimeoutSeconds)
            $stopped = $false
            while ([DateTimeOffset]::Now -lt $deadline) {
                Start-Sleep -Milliseconds 200
                try {
                    $testStream = [System.IO.File]::Open($LockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
                    $testStream.Dispose()
                    $stopped = $true
                    break
                } catch {}
            }
            if ($stopped) {
                Write-Output "Daemon stopped gracefully."
            } else {
                Write-Output "Stop requested but daemon did not release lock within $ShutdownTimeoutSeconds seconds."
            }
        }
    }
}
