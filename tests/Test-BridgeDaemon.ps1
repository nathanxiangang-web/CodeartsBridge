[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$daemonScript = Join-Path $root (Join-Path 'scripts' 'bridge-daemon.ps1')
$tokens = $null
$parseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile($daemonScript, [ref]$tokens, [ref]$parseErrors) | Out-Null
if ($parseErrors.Count -gt 0) {
    throw "Daemon syntax errors: " + (($parseErrors | ForEach-Object Message) -join '; ')
}
. $daemonScript -Command run -DaemonTest
$fakeRunner = Join-Path $root (Join-Path 'tests' 'fake-runner.ps1')
$testHostExe = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
$script:PassCount = 0
$script:FailCount = 0
$script:NotRunCount = 0
function Assert-True {
    param([string]$Label, [bool]$Cond)
    if (-not $Cond) { throw "ASSERT_FALSE: $Label" }
}
function Assert-Equal {
    param([string]$Label, $Expected, $Actual)
    if ($Expected -ne $Actual) { throw "ASSERT_NEQ: $Label - expected=$Expected actual=$Actual" }
}
function Test-Pass {
    param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][scriptblock]$Body)
    try {
        & $Body
        $script:PassCount++
        Write-Output "PASS: $Name"
    } catch {
        $script:FailCount++
        Write-Output "FAIL: $Name - $($_.Exception.Message)"
    }
}
function New-TempRoot {
    $p = Join-Path ([System.IO.Path]::GetTempPath()) ('daemon-test-' + [guid]::NewGuid().ToString('N'))
    [System.IO.Directory]::CreateDirectory($p) | Out-Null
    return $p
}
function Write-Control {
    param([string]$StateDir, [int]$ExitCode = 0, [string]$Marker = '', [string]$StderrText = '', [int]$SleepSeconds = 0)
    [System.IO.Directory]::CreateDirectory($StateDir) | Out-Null
    $ctrl = [ordered]@{ exitCode = $ExitCode; marker = $Marker; stderrText = $StderrText; sleepSeconds = $SleepSeconds }
    $json = ($ctrl | ConvertTo-Json -Depth 5) + [Environment]::NewLine
    $path = Join-Path $StateDir 'fake-control.json'
    $tmp = $path + '.tmp'
    [System.IO.File]::WriteAllText($tmp, $json, [System.Text.UTF8Encoding]::new($false))
    [System.IO.File]::Copy($tmp, $path, $true)
    [System.IO.File]::Delete($tmp)
}
Write-Output '=== Test-BridgeDaemon.ps1: supervisor runtime tests ==='
Write-Output ''
Test-Pass -Name 'T01 once mode runs single iteration and writes health' -Body {
    $tmp = New-TempRoot
    try {
        $stateDir = Join-Path $tmp 'state'
        $marker = Join-Path $tmp 'marker.txt'
        Write-Control -StateDir $stateDir -ExitCode 0 -Marker $marker
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner -IntervalSeconds 1 2>&1 | Out-Null
        Assert-True 'once exited 0' ($LASTEXITCODE -eq 0)
        $healthPath = Join-Path $stateDir 'health.json'
        Assert-True 'health file exists' (Test-Path -LiteralPath $healthPath -PathType Leaf)
        $health = Get-Content -LiteralPath $healthPath -Raw | ConvertFrom-Json
        Assert-Equal 'status' 'stopped' $health.status
        Assert-Equal 'iteration' 1 $health.iteration
        Assert-True 'lastSuccessTime set' ($health.lastSuccessTime -ne '')
        Assert-True 'marker created' (Test-Path -LiteralPath $marker -PathType Leaf)
        Assert-Equal 'maxWorkers default' 3 $health.maxWorkers
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}
Test-Pass -Name 'T02 single-instance exclusion via lock' -Body {
    $tmp = New-TempRoot
    try {
        $stateDir = Join-Path $tmp 'state'
        [System.IO.Directory]::CreateDirectory($stateDir) | Out-Null
        $lockPath = Join-Path $stateDir 'daemon.lock'
        Write-Control -StateDir $stateDir -ExitCode 0
        $lockStream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        try {
            $out = & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner 2>&1 | Out-String
            Assert-True 'second instance failed' ($LASTEXITCODE -ne 0)
            Assert-True 'error mentions lock or instance' ($out -match 'lock|instance|already')
        } finally {
            $lockStream.Dispose()
        }
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}
Test-Pass -Name 'T03 graceful stop within bounded time' -Body {
    $tmp = New-TempRoot
    $proc = $null
    try {
        $stateDir = Join-Path $tmp 'state'
        Write-Control -StateDir $stateDir -ExitCode 0
        $stdoutFile = Join-Path $tmp 'd-stdout.txt'
        $stderrFile = Join-Path $tmp 'd-stderr.txt'
        $proc = Start-Process -FilePath $testHostExe -ArgumentList '-NoProfile','-File',$daemonScript,'run','-StateDir',$stateDir,'-FakeRunner',$fakeRunner,'-IntervalSeconds','1' -PassThru -RedirectStandardOutput $stdoutFile -RedirectStandardError $stderrFile
        Assert-True 'process started' ($null -ne $proc)
        $started = $false
        $wc = 0
        while (-not $started -and $wc -lt 50) {
            Start-Sleep -Milliseconds 100
            $wc = $wc + 1
            $hp = Join-Path $stateDir 'health.json'
            if (Test-Path -LiteralPath $hp -PathType Leaf) {
                $h = Get-Content -LiteralPath $hp -Raw -EA SilentlyContinue | ConvertFrom-Json -EA SilentlyContinue
                if ($h -and $h.status -eq 'running') { $started = $true }
            }
        }
        Assert-True 'daemon started' $started
        $stopOut = & $testHostExe -NoProfile -File $daemonScript stop -StateDir $stateDir -ShutdownTimeoutSeconds 15 2>&1 | Out-String
        Assert-True 'stop exited 0' ($LASTEXITCODE -eq 0)
        $proc.WaitForExit()
        Assert-True 'process exited' ($proc.HasExited)
        $fh = Get-Content (Join-Path $stateDir 'health.json') -Raw | ConvertFrom-Json
        Assert-True 'health shows stopped' ($fh.status -eq 'stopped')
    } finally {
        if ($proc -and -not $proc.HasExited) {
            try { $proc.Kill($true) } catch {}
            $proc.WaitForExit()
        }
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}
Test-Pass -Name 'T04 backoff bounds are exponential and capped' -Body {
    Assert-Equal 'no failures' 0 (Get-BackoffDelay -FailureCount 0 -Base 2 -Max 300)
    Assert-Equal 'first failure' 2 (Get-BackoffDelay -FailureCount 1 -Base 2 -Max 300)
    Assert-Equal 'second failure' 4 (Get-BackoffDelay -FailureCount 2 -Base 2 -Max 300)
    Assert-Equal 'third failure' 8 (Get-BackoffDelay -FailureCount 3 -Base 2 -Max 300)
    Assert-Equal 'capped' 300 (Get-BackoffDelay -FailureCount 20 -Base 2 -Max 300)
    Assert-True 'min 1' ((Get-BackoffDelay -FailureCount 1 -Base 0 -Max 300) -ge 1)
}
Test-Pass -Name 'T05 child failure recorded and daemon survives' -Body {
    $tmp = New-TempRoot
    try {
        $stateDir = Join-Path $tmp 'state'
        Write-Control -StateDir $stateDir -ExitCode 1 -StderrText 'something went wrong'
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner 2>&1 | Out-Null
        Assert-True 'once completed' ($LASTEXITCODE -eq 0)
        $health = Get-Content (Join-Path $stateDir 'health.json') -Raw | ConvertFrom-Json
        Assert-True 'error recorded' ($health.lastError -match 'exit code: 1')
        Assert-True 'stderr in error' ($health.lastError -match 'something went wrong')
        Assert-True 'lastSuccessTime empty' ($health.lastSuccessTime -eq '')
        Assert-Equal 'status stopped' 'stopped' $health.status
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}
Test-Pass -Name 'T06 health output has required fields and no secrets' -Body {
    $tmp = New-TempRoot
    try {
        $stateDir = Join-Path $tmp 'state'
        Write-Control -StateDir $stateDir -ExitCode 1 -StderrText 'CODEARTS_CLI_AK=FAKE_AK_999 password=FAKE_PASS'
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner 2>&1 | Out-Null
        $healthJson = Get-Content (Join-Path $stateDir 'health.json') -Raw
        $health = $healthJson | ConvertFrom-Json
        $requiredFields = @('schemaVersion','daemonVersion','status','pid','startTime','iteration','lastSuccessTime','lastError','lastErrorAt','maxWorkers','intervalSeconds','updatedAt')
        foreach ($f in $requiredFields) {
            Assert-True "field $f present" ($health.PSObject.Properties.Name -contains $f)
        }
        Assert-True 'pid is positive' ([int]$health.pid -gt 0)
        Assert-True 'startTime is ISO' ($health.startTime -is [DateTime] -or [string]$health.startTime -match '^\d{4}-\d{2}-\d{2}T')
        Assert-True 'no secrets' (-not ($healthJson -match 'FAKE_AK_999'))
        Assert-True 'no password' (-not ($healthJson -match 'FAKE_PASS'))
        Assert-True 'mask marker present' ($health.lastError -match '\*\*\*')
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}
Test-Pass -Name 'T07 stale health recovery overwrites old PID' -Body {
    $tmp = New-TempRoot
    try {
        $stateDir = Join-Path $tmp 'state'
        [System.IO.Directory]::CreateDirectory($stateDir) | Out-Null
        $staleHealth = [ordered]@{
            schemaVersion = 1; daemonVersion = '0.9.0'; status = 'running'
            pid = 999999; startTime = '2020-01-01T00:00:00Z'; iteration = 42
            lastSuccessTime = '2020-01-01T00:00:00Z'; lastError = ''; lastErrorAt = ''
            maxWorkers = 3; intervalSeconds = 30; updatedAt = '2020-01-01T00:00:00Z'
        }
        $staleJson = ($staleHealth | ConvertTo-Json -Depth 5) + [Environment]::NewLine
        [System.IO.File]::WriteAllText((Join-Path $stateDir 'health.json'), $staleJson, [System.Text.UTF8Encoding]::new($false))
        Write-Control -StateDir $stateDir -ExitCode 0
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner 2>&1 | Out-Null
        $health = Get-Content (Join-Path $stateDir 'health.json') -Raw | ConvertFrom-Json
        Assert-True 'pid updated' ([int]$health.pid -ne 999999)
        Assert-True 'pid is positive' ([int]$health.pid -gt 0)
        Assert-Equal 'iteration reset' 1 $health.iteration
        Assert-Equal 'version updated' '1.6.0' $health.daemonVersion
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}
Test-Pass -Name 'T08 no interactive waits in daemon source' -Body {
    $daemonSource = [System.IO.File]::ReadAllText($daemonScript)
    Assert-True 'no Read-Host' (-not ($daemonSource -match 'Read-Host'))
    Assert-True 'no Console Read' (-not ($daemonSource -match '\[Console\]::Read'))
}
Test-Pass -Name 'T09 default max concurrency is 3' -Body {
    $tmp = New-TempRoot
    try {
        $stateDir = Join-Path $tmp 'state'
        Write-Control -StateDir $stateDir -ExitCode 0
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner 2>&1 | Out-Null
        $health = Get-Content (Join-Path $stateDir 'health.json') -Raw | ConvertFrom-Json
        Assert-Equal 'maxWorkers default' 3 $health.maxWorkers
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}
Test-Pass -Name 'T10 status command outputs health JSON' -Body {
    $tmp = New-TempRoot
    try {
        $stateDir = Join-Path $tmp 'state'
        Write-Control -StateDir $stateDir -ExitCode 0
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner 2>&1 | Out-Null
        $statusOut = & $testHostExe -NoProfile -File $daemonScript status -StateDir $stateDir 2>&1 | Out-String
        $status = $statusOut | ConvertFrom-Json
        Assert-True 'status has pid' ($status.pid -gt 0)
        Assert-Equal 'status field' 'stopped' $status.status
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}
Test-Pass -Name 'T11 stop with no daemon exits cleanly' -Body {
    $tmp = New-TempRoot
    try {
        $stateDir = Join-Path $tmp 'state'
        $out = & $testHostExe -NoProfile -File $daemonScript stop -StateDir $stateDir -ShutdownTimeoutSeconds 5 2>&1 | Out-String
        Assert-True 'stop exited 0' ($LASTEXITCODE -eq 0)
        Assert-True 'stop mentions gracefully' ($out -match 'gracefully')
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}
Test-Pass -Name 'T12 fault injection: write failure preserves previous valid JSON' -Body {
    $tmp = New-TempRoot
    try {
        $stateDir = Join-Path $tmp 'state'
        [System.IO.Directory]::CreateDirectory($stateDir) | Out-Null
        $healthPath = Join-Path $stateDir 'health.json'
        $validJson = '{"schemaVersion":1,"status":"running","pid":12345,"iteration":5}' + "`n"
        [System.IO.File]::WriteAllText($healthPath, $validJson, [System.Text.UTF8Encoding]::new($false))
        $helperPath = Join-Path $tmp 'fault-helper.ps1'
        $helperLines = @(
            'param([string]$DaemonScript, [string]$StateDir)'
            '. $DaemonScript -Command run -DaemonTest -StateDir $StateDir'
            '$script:WriteAtomicTextOverride = {'
            '    param($Path, $Content)'
            '    if ($Path -match ''health\.json'') { throw "Injected write failure" }'
            '    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))'
            '}'
            'try { Set-DaemonHealth -Status "running" -Iteration 6 -LastSuccessTime "" -LastError "" -LastErrorAt "" -StartTime "2020-01-01T00:00:00Z" -ProcessId 999 } catch {}'
        )
        [System.IO.File]::WriteAllText($helperPath, ($helperLines -join "`n"), [System.Text.UTF8Encoding]::new($false))
        & $testHostExe -NoProfile -File $helperPath -DaemonScript $daemonScript -StateDir $stateDir 2>&1 | Out-Null
        $remainingJson = Get-Content -LiteralPath $healthPath -Raw
        Assert-True 'previous JSON intact' ($remainingJson -match '"pid":12345')
        Assert-True 'previous JSON valid' (($remainingJson | ConvertFrom-Json).pid -eq 12345)
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}

Test-Pass -Name 'T13 host executable resolution with explicit path' -Body {
    $tmp = New-TempRoot
    try {
        $stateDir = Join-Path $tmp 'state'
        Write-Control -StateDir $stateDir -ExitCode 0
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner -HostExecutable $testHostExe 2>&1 | Out-Null
        Assert-True 'once exited 0' ($LASTEXITCODE -eq 0)
        $health = Get-Content (Join-Path $stateDir 'health.json') -Raw | ConvertFrom-Json
        Assert-Equal 'status' 'stopped' $health.status
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}
Test-Pass -Name 'T13b invalid host executable fails with clear error' -Body {
    $tmp = New-TempRoot
    try {
        $stateDir = Join-Path $tmp 'state'
        Write-Control -StateDir $stateDir -ExitCode 0
        $out = & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner -HostExecutable '/nonexistent/pwsh' 2>&1 | Out-String
        Assert-True 'failed with invalid host' ($LASTEXITCODE -ne 0)
        Assert-True 'error mentions host' ($out -match 'Host executable')
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}
Test-Pass -Name 'T14 timeout enforcement kills long-running child' -Body {
    $tmp = New-TempRoot
    try {
        $stateDir = Join-Path $tmp 'state'
        Write-Control -StateDir $stateDir -ExitCode 0 -SleepSeconds 10
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner -LoopTimeoutSeconds 2 2>&1 | Out-Null
        Assert-True 'once completed' ($LASTEXITCODE -eq 0)
        $health = Get-Content (Join-Path $stateDir 'health.json') -Raw | ConvertFrom-Json
        Assert-True 'timeout error recorded' ($health.lastError -match 'timed out')
        Assert-Equal 'status stopped' 'stopped' $health.status
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}
Test-Pass -Name 'T15 real bridge dispatch DryRun with unique fixture' -Body {
    $tmp = New-TempRoot
    $fixtureId = 'daemon-test-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    $fixtureDir = Join-Path $root 'tasks' $fixtureId
    try {
        $stateDir = Join-Path $tmp 'state'
        $bridgeScript = Join-Path $root 'scripts' 'bridge.ps1'
        [System.IO.Directory]::CreateDirectory((Join-Path $fixtureDir 'inbox')) | Out-Null
        [System.IO.Directory]::CreateDirectory((Join-Path $fixtureDir 'outbox')) | Out-Null
        $state = [ordered]@{ taskId = $fixtureId; status = 'READY'; attempt = 0; updatedAt = '2026-01-01T00:00:00Z'; message = '' }
        [System.IO.File]::WriteAllText((Join-Path $fixtureDir 'state.json'), ($state | ConvertTo-Json -Depth 5) + "
", [System.Text.UTF8Encoding]::new($false))
        $meta = [ordered]@{ taskId = $fixtureId; projectId = 'codex-glm-ma-w03'; createdAt = '2026-01-01T00:00:00Z' }
        [System.IO.File]::WriteAllText((Join-Path $fixtureDir 'META.json'), ($meta | ConvertTo-Json -Depth 5) + "
", [System.Text.UTF8Encoding]::new($false))
        [System.IO.File]::WriteAllText((Join-Path $fixtureDir 'inbox' 'TASK.md'), 'test task', [System.Text.UTF8Encoding]::new($false))
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -BridgeScript $bridgeScript -DryRun -MaxWorkers 3 -LoopTimeoutSeconds 30 2>&1 | Out-Null
        Assert-True 'once exited 0' ($LASTEXITCODE -eq 0)
        $health = Get-Content (Join-Path $stateDir 'health.json') -Raw | ConvertFrom-Json
        Assert-True 'health valid' ($null -ne $health)
        Assert-Equal 'status stopped' 'stopped' $health.status
    } finally {
        Remove-Item -LiteralPath $fixtureDir -Recurse -Force -EA SilentlyContinue
        Assert-True 'fixture removed' (-not (Test-Path -LiteralPath $fixtureDir))
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}
Test-Pass -Name 'T16 concurrent writer and reader produce valid JSON' -Body {
    $tmp = New-TempRoot
    try {
        $stateDir = Join-Path $tmp 'state'
        [System.IO.Directory]::CreateDirectory($stateDir) | Out-Null
        $healthPath = Join-Path $stateDir 'health.json'
        $writerScript = Join-Path $tmp 'writer.ps1'
        $writerCode = @'
$healthPath = $args[0]
for ($i = 1; $i -le 50; $i++) {
    $j = '{"pid":' + $i + ',"status":"running","iteration":' + $i + '}'
    $dir = Split-Path -Parent $healthPath
    $tmpF = Join-Path $dir ('.' + [guid]::NewGuid().ToString('N') + '.tmp')
    [System.IO.File]::WriteAllText($tmpF, $j + "
", [System.Text.UTF8Encoding]::new($false))
    if (Test-Path -LiteralPath $healthPath) {
        $bakF = Join-Path $dir ('.' + [guid]::NewGuid().ToString('N') + '.bak')
        [System.IO.File]::Replace($tmpF, $healthPath, $bakF)
        if (Test-Path -LiteralPath $bakF) { Remove-Item -LiteralPath $bakF -Force }
    } else {
        [System.IO.File]::Move($tmpF, $healthPath)
    }
    Start-Sleep -Milliseconds 5
}
'@
        [System.IO.File]::WriteAllText($writerScript, $writerCode, [System.Text.UTF8Encoding]::new($false))
        $writerProc = Start-Process -FilePath $testHostExe -ArgumentList '-NoProfile','-File',$writerScript,$healthPath -PassThru
        $allValid = $true
        $readCount = 0
        while (-not $writerProc.HasExited -or $readCount -lt 50) {
            try {
                $raw = Get-Content -LiteralPath $healthPath -Raw -EA SilentlyContinue
                if ($raw) {
                    $j = $raw | ConvertFrom-Json
                    if (-not $j) { $allValid = $false }
                    $readCount++
                }
            } catch {
                $allValid = $false
            }
            Start-Sleep -Milliseconds 2
        }
        $writerProc.WaitForExit()
        Assert-True 'reader saw documents' ($readCount -gt 0)
        Assert-True 'all reads valid JSON' $allValid
    } finally {
        if ($writerProc -and -not $writerProc.HasExited) { try { $writerProc.Kill($true) } catch {} }
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}
Test-Pass -Name 'T17 corrupt health recovery' -Body {
    $tmp = New-TempRoot
    try {
        $stateDir = Join-Path $tmp 'state'
        [System.IO.Directory]::CreateDirectory($stateDir) | Out-Null
        [System.IO.File]::WriteAllText((Join-Path $stateDir 'health.json'), '{invalid json content', [System.Text.UTF8Encoding]::new($false))
        Write-Control -StateDir $stateDir -ExitCode 0
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner 2>&1 | Out-Null
        $health = Get-Content (Join-Path $stateDir 'health.json') -Raw | ConvertFrom-Json
        Assert-True 'health overwritten with valid JSON' ($null -ne $health)
        Assert-Equal 'status' 'stopped' $health.status
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}
Test-Pass -Name 'T18 no temp or backup files left after write' -Body {
    $tmp = New-TempRoot
    try {
        $stateDir = Join-Path $tmp 'state'
        Write-Control -StateDir $stateDir -ExitCode 0
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner 2>&1 | Out-Null
        $tmpFiles = @(Get-ChildItem -LiteralPath $stateDir -Filter '*.tmp' -EA SilentlyContinue)
        $bakFiles = @(Get-ChildItem -LiteralPath $stateDir -Filter '*.bak' -EA SilentlyContinue)
        Assert-True 'no tmp files' ($tmpFiles.Count -eq 0)
        Assert-True 'no bak files' ($bakFiles.Count -eq 0)
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}
Test-Pass -Name 'T19 parameter validation rejects invalid bounds' -Body {
    $tmp = New-TempRoot
    try {
        $stateDir = Join-Path $tmp 'state'
        Write-Control -StateDir $stateDir -ExitCode 0
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner -IntervalSeconds 0 2>&1 | Out-Null
        Assert-True 'interval 0 rejected' ($LASTEXITCODE -ne 0)
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner -MaxWorkers 0 2>&1 | Out-Null
        Assert-True 'maxworkers 0 rejected' ($LASTEXITCODE -ne 0)
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner -LoopTimeoutSeconds 0 2>&1 | Out-Null
        Assert-True 'timeout 0 rejected' ($LASTEXITCODE -ne 0)
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner -BaseBackoffSeconds 0 2>&1 | Out-Null
        Assert-True 'backoff 0 rejected' ($LASTEXITCODE -ne 0)
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}
Test-Pass -Name 'T20 bounded output prevents memory exhaustion' -Body {
    $tmp = New-TempRoot
    try {
        $stateDir = Join-Path $tmp 'state'
        $fixturePath = Join-Path $tmp 'big-output.ps1'
        $fixtureLines = @(
            'param([int]$MaxWorkers = 3, [string]$StateDir = "")'
            '$chunk = "A" * 65536'
            'for ($i = 0; $i -lt 32; $i++) { [Console]::Out.WriteLine($chunk) }'
            '$errChunk = "B" * 65536'
            'for ($i = 0; $i -lt 32; $i++) { [Console]::Error.WriteLine($errChunk) }'
            'exit 1'
        )
        [System.IO.File]::WriteAllText($fixturePath, ($fixtureLines -join "`n"), [System.Text.UTF8Encoding]::new($false))
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fixturePath -MaxOutputBytes 512 -LoopTimeoutSeconds 30 2>&1 | Out-Null
        Assert-True 'once completed' ($LASTEXITCODE -eq 0)
        $health = Get-Content (Join-Path $stateDir 'health.json') -Raw | ConvertFrom-Json
        $utf8 = [System.Text.UTF8Encoding]::new($false)
        $errBytes = $utf8.GetByteCount($health.lastError)
        Assert-True 'error byte count within cap' ($errBytes -le 512)
        Assert-True 'truncation marker present' ($health.lastError -match 'truncated')
        Assert-True 'stdout truncated flag' ($health.stdOutTruncated -eq $true)
        Assert-True 'stderr truncated flag' ($health.stdErrTruncated -eq $true)
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}

Test-Pass -Name 'T21 lock released even if final health write fails' -Body {
    $tmp = New-TempRoot
    try {
        $stateDir = Join-Path $tmp 'state'
        Write-Control -StateDir $stateDir -ExitCode 0
        $helperPath = Join-Path $tmp 'lock-helper.ps1'
        $helperLines = @(
            'param([string]$DaemonScript, [string]$StateDir, [string]$FakeRunner, [string]$HostExe)'
            '. $DaemonScript -Command run -DaemonTest -StateDir $StateDir -FakeRunner $FakeRunner -HostExecutable $HostExe'
            '$script:WriteAtomicTextOverride = {'
            '    param($Path, $Content)'
            '    if ($Path -match ''health\.json'' -and $Content -match ''stopped'') { throw "Injected stopped write failure" }'
            '    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))'
            '}'
            'Invoke-DaemonLoop -SingleRun'
        )
        [System.IO.File]::WriteAllText($helperPath, ($helperLines -join "`n"), [System.Text.UTF8Encoding]::new($false))
        & $testHostExe -NoProfile -File $helperPath -DaemonScript $daemonScript -StateDir $stateDir -FakeRunner $fakeRunner -HostExe $testHostExe 2>&1 | Out-Null
        $lockPath = Join-Path $stateDir 'daemon.lock'
        $testStream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        $testStream.Dispose()
        Assert-True 'lock released' ($true)
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}

Test-Pass -Name 'T22 inherited pipe: descendant retains pipe 30s, drain incomplete observed' -Body {
    $tmp = New-TempRoot
    $descendantPid = 0
    try {
        $stateDir = Join-Path $tmp 'state'
        $fixturePath = Join-Path $tmp 'inherited-pipe.ps1'
        $pidFilePath = Join-Path $tmp 'descendant-pid.txt'
        $fixtureB64 = 'cGFyYW0oW2ludF0kTWF4V29ya2VycyA9IDMsIFtzdHJpbmddJFN0YXRlRGlyID0gIiIpCiRwaWRGaWxlID0gSm9pbi1QYXRoICRTdGF0ZURpciAiLi4vZGVzY2VuZGFudC1waWQudHh0IgppZiAoJFBTVmVyc2lvblRhYmxlLlBsYXRmb3JtIC1lcSAiVW5peCIpIHsKICAgICRzaENtZCA9ICdzbGVlcCAzMCAmIGVjaG8gJCEgPiAiJyArICRwaWRGaWxlICsgJyInCiAgICAmIC9iaW4vc2ggLWMgJHNoQ21kCn0gZWxzZSB7CiAgICAkcHNpID0gW1N5c3RlbS5EaWFnbm9zdGljcy5Qcm9jZXNzU3RhcnRJbmZvXTo6bmV3KCkKICAgICRwc2kuRmlsZU5hbWUgPSAicGluZyIKICAgICRwc2kuQXJndW1lbnRzID0gIi1uIDMxIDEyNy4wLjAuMSIKICAgICRwc2kuVXNlU2hlbGxFeGVjdXRlID0gJGZhbHNlCiAgICAkcHNpLkNyZWF0ZU5vV2luZG93ID0gJHRydWUKICAgICRjaGlsZCA9IFtTeXN0ZW0uRGlhZ25vc3RpY3MuUHJvY2Vzc106Om5ldygpCiAgICAkY2hpbGQuU3RhcnRJbmZvID0gJHBzaQogICAgW3ZvaWRdJGNoaWxkLlN0YXJ0KCkKICAgIFtTeXN0ZW0uSU8uRmlsZV06OldyaXRlQWxsVGV4dCgkcGlkRmlsZSwgW3N0cmluZ10kY2hpbGQuSWQsIFtTeXN0ZW0uVGV4dC5VVEY4RW5jb2RpbmddOjpuZXcoJGZhbHNlKSkKfQpXcml0ZS1PdXRwdXQgcGFyZW50LW91dHB1dApleGl0IDAK'
        $fixtureContent = [System.Text.Encoding]::ASCII.GetString([Convert]::FromBase64String($fixtureB64))
        [System.IO.File]::WriteAllText($fixturePath, $fixtureContent, [System.Text.UTF8Encoding]::new($false))
        $startTime = [DateTimeOffset]::UtcNow
        $daemonOut = Join-Path $tmp 'daemon-stdout.txt'
        $daemonErr = Join-Path $tmp 'daemon-stderr.txt'
        $dproc = Start-Process $testHostExe -ArgumentList @('-NoProfile', '-File', $daemonScript, 'once', '-StateDir', $stateDir, '-FakeRunner', $fixturePath, '-LoopTimeoutSeconds', '30') -NoNewWindow -PassThru -RedirectStandardOutput $daemonOut -RedirectStandardError $daemonErr
        $dproc.WaitForExit()
        $elapsed = ([DateTimeOffset]::UtcNow - $startTime).TotalSeconds
        Assert-True 'once completed' ($dproc.ExitCode -eq 0)
        Assert-True 'completed well before 30s' ($elapsed -lt 15)
        $health = Get-Content (Join-Path $stateDir 'health.json') -Raw | ConvertFrom-Json
        Assert-True 'drain incomplete recorded' ($health.drainIncomplete -eq $true)
        Assert-True 'error mentions drain' ($health.lastError -match 'drain')
        if (Test-Path $pidFilePath) { $descendantPid = [int](Get-Content $pidFilePath -Raw).Trim() }
    } finally {
        if ($descendantPid -gt 0) {
            try { Stop-Process -Id $descendantPid -Force -EA SilentlyContinue } catch {}
        }
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}

Test-Pass -Name 'T23 hostile multibyte UTF-8 split across read chunks' -Body {
    $tmp = New-TempRoot
    try {
        $stateDir = Join-Path $tmp 'state'
        $fixturePath = Join-Path $tmp 'multibyte.ps1'
        $fixtureB64 = 'cGFyYW0oW2ludF0kTWF4V29ya2VycyA9IDMsIFtzdHJpbmddJFN0YXRlRGlyID0gIiIpDQokY2h1bmsgPSAiQSIgKiA2NTUzNg0KZm9yICgkaSA9IDA7ICRpIC1sdCAzMjsgJGkrKykgeyBbQ29uc29sZV06Ok91dC5Xcml0ZUxpbmUoJGNodW5rKSB9DQokZXJyQ2h1bmsgPSAiQiIgKiA2NTUzNg0KZm9yICgkaSA9IDA7ICRpIC1sdCAzMjsgJGkrKykgeyBbQ29uc29sZV06OkVyci5Xcml0ZUxpbmUoJGVyckNodW5rKSB9DQokdXRmOCA9IFtTeXN0ZW0uVGV4dC5VVEY4RW5jb2RpbmddOjpuZXcoJGZhbHNlKQ0KJG11bHRpID0gKFtjaGFyXTB4NEUyRCkuVG9TdHJpbmcoKSAqIDEwMA0KJGJ5dGVzID0gJHV0ZjguR2V0Qnl0ZXMoKCJhIiAqIDgyNTApICsgJG11bHRpICsgKCJhIiAqIDY1NTM2KSkNCltDb25zb2xlXTo6RXJyLldyaXRlKCR1dGY4LkdldFN0cmluZygkYnl0ZXMpKQ0KZXhpdCAx'
        $fixtureContent = [System.Text.Encoding]::ASCII.GetString([Convert]::FromBase64String($fixtureB64))
        [System.IO.File]::WriteAllText($fixturePath, $fixtureContent, [System.Text.UTF8Encoding]::new($false))
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fixturePath -MaxOutputBytes 512 -LoopTimeoutSeconds 30 2>&1 | Out-Null
        Assert-True 'once completed' ($LASTEXITCODE -eq 0)
        $health = Get-Content (Join-Path $stateDir 'health.json') -Raw | ConvertFrom-Json
        $utf8 = [System.Text.UTF8Encoding]::new($false)
        $errBytes = $utf8.GetByteCount($health.lastError)
        Assert-True 'error byte count within cap' ($errBytes -le 512)
        Assert-True 'truncation marker present' ($health.lastError -match 'truncated')
        Assert-True 'stdout truncated flag' ($health.stdOutTruncated -eq $true)
        Assert-True 'stderr truncated flag' ($health.stdErrTruncated -eq $true)
        $decoded = $utf8.GetString($utf8.GetBytes($health.lastError))
        Assert-True 'no corrupted UTF-8' ($decoded -eq $health.lastError)
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}

Test-Pass -Name 'T24 upper bound validation rejects excessive values' -Body {
    $tmp = New-TempRoot
    try {
        $stateDir = Join-Path $tmp 'state'
        Write-Control -StateDir $stateDir -ExitCode 0
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner -IntervalSeconds 86401 2>&1 | Out-Null
        Assert-True 'interval 86401 rejected' ($LASTEXITCODE -ne 0)
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner -MaxWorkers 101 2>&1 | Out-Null
        Assert-True 'maxworkers 101 rejected' ($LASTEXITCODE -ne 0)
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner -LoopTimeoutSeconds 86401 2>&1 | Out-Null
        Assert-True 'timeout 86401 rejected' ($LASTEXITCODE -ne 0)
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner -ShutdownTimeoutSeconds 3601 2>&1 | Out-Null
        Assert-True 'shutdown 3601 rejected' ($LASTEXITCODE -ne 0)
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner -MaxBackoffSeconds 86401 2>&1 | Out-Null
        Assert-True 'maxbackoff 86401 rejected' ($LASTEXITCODE -ne 0)
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner -BaseBackoffSeconds 3601 2>&1 | Out-Null
        Assert-True 'basebackoff 3601 rejected' ($LASTEXITCODE -ne 0)
        & $testHostExe -NoProfile -File $daemonScript once -StateDir $stateDir -FakeRunner $fakeRunner -MaxOutputBytes 10485761 2>&1 | Out-Null
        Assert-True 'maxoutput 10485761 rejected' ($LASTEXITCODE -ne 0)
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -EA SilentlyContinue
    }
}

Write-Output ''
Write-Output '=== Summary ==='
Write-Output "PASS: $script:PassCount"
Write-Output "FAIL: $script:FailCount"
Write-Output "NOT_RUN: $script:NotRunCount"
Write-Output "TOTAL: $($script:PassCount + $script:FailCount + $script:NotRunCount)"
if ($script:FailCount -gt 0) {
    Write-Output "FAILED: $script:FailCount test(s) failed"
    exit 1
}
Write-Output 'ALL TESTS PASSED'
exit 0
