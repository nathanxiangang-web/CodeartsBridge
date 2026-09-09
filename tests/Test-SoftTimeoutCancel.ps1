[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Tests for soft-timeout / grace-period / cancel-polling / drain-incomplete
# in Invoke-CapturedProcess (scripts/bridge.ps1).
#
# Tests-only change: does not modify production code.
# All fixtures live under a temp directory removed in finally.

$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$runner = Join-Path $root 'scripts\bridge.ps1'
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) { throw "Runner not found: $runner" }

# Parse-check the runner.
$tokens = $null
$parseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$tokens, [ref]$parseErrors) | Out-Null
if ($parseErrors.Count -gt 0) {
    throw 'Runner syntax errors: ' + (($parseErrors | ForEach-Object Message) -join '; ')
}

# Dot-source the runner in test mode.
. $runner -Command bootstrap -BridgeTest

function Assert-True {
    param([string]$Label, [bool]$Cond)
    if (-not $Cond) { throw "ASSERT FAILED: $Label" }
}

function Assert-False {
    param([string]$Label, [bool]$Cond)
    if ($Cond) { throw "ASSERT FAILED (expected false): $Label" }
}

# ---------------------------------------------------------------------------
# Static contract: Complete-Drain must log drain-incomplete warnings.
# ---------------------------------------------------------------------------
$bridgeSource = Get-Content -LiteralPath $runner -Raw
Assert-True 'Complete-Drain logs drain incomplete warning' ($bridgeSource -match 'Drain incomplete: output pipe')
Assert-True 'finally block waits for async task before dispose' ($bridgeSource -match 'stdoutTask\.Wait\(2000\)')
Write-Output 'PASS: Static contract - Complete-Drain logs drain incomplete and finally waits for async tasks.'

# ---------------------------------------------------------------------------
# Static contract: Initialize-RemoteWorkspace remaps allowedPaths to remote repo.
# ---------------------------------------------------------------------------
Assert-True 'allowedPaths remap to remoteRepo present' ($bridgeSource -match 'allowedPaths = @\(\$remoteRepo\)')
Assert-True 'remapped META path used in transfers' ($bridgeSource -match 'metaForRemote.*Label=.task-meta')
Write-Output 'PASS: Static contract - allowedPaths remapped to remote repo in Initialize-RemoteWorkspace.'

# ---------------------------------------------------------------------------
# Helper: create a ProcessStartInfo for a simple command.
# ---------------------------------------------------------------------------
function New-TestStartInfo {
    param([string]$FileName, [string]$Arguments = '')
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $FileName
    if ($Arguments) { $info.Arguments = $Arguments }
    $info.UseShellExecute = $false
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.CreateNoWindow = $true
    return $info
}

# Determine the sleep command for this platform.
$isWindowsHost = ($PSVersionTable.Platform -eq 'Win32NT')
$sleepCmd = if ($isWindowsHost) {
    Join-Path $PSHOME 'pwsh'
} else {
    '/bin/sleep'
}

$tmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('softcancel-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($tmpRoot) | Out-Null

try {

    # ---------------------------------------------------------------------------
    # Test 1: Soft timeout triggers grace period, then AssistanceRequested.
    # ---------------------------------------------------------------------------
    $taskDir1 = Join-Path $tmpRoot 'task1'
    [System.IO.Directory]::CreateDirectory($taskDir1) | Out-Null
    $logPrefix1 = Join-Path $taskDir1 'worker1'

    if ($isWindowsHost) {
        $si1 = New-TestStartInfo -FileName $sleepCmd -Arguments '-NoProfile -Command Start-Sleep -Seconds 30'
    } else {
        $si1 = New-TestStartInfo -FileName $sleepCmd -Arguments '30'
    }

    $sw1 = [System.Diagnostics.Stopwatch]::StartNew()
    $r1 = Invoke-CapturedProcess -StartInfo $si1 -TaskDirectory $taskDir1 -TimeoutSeconds 8 -LogPrefix $logPrefix1 -TaskId 'test-soft-w01' -ProjectId 'test' -SoftTimeoutSeconds 3 -SoftGraceSeconds 2
    $sw1.Stop()


    $hasAssist1 = $r1.PSObject.Properties.Name -contains 'AssistanceRequested'
    $assistVal1 = if ($hasAssist1) { [bool]$r1.AssistanceRequested } else { $false }
    Assert-True 'T1: AssistanceRequested is true' $assistVal1
    Assert-False 'T1: Cancelled is false' ([bool]$r1.Cancelled)
    Assert-False 'T1: TimedOut is false' ([bool]$r1.TimedOut)
    Assert-True 'T1: elapsed >= 4s (soft+grace)' ($sw1.ElapsedMilliseconds -ge 4000)
    Assert-True 'T1: elapsed < 8s (hard timeout not hit)' ($sw1.ElapsedMilliseconds -lt 8000)
    Write-Output 'PASS: Soft timeout triggers grace period then AssistanceRequested.'

    # ---------------------------------------------------------------------------
    # Test 2: CANCEL_REQUESTED file triggers cancellation.
    # ---------------------------------------------------------------------------
    $taskDir2 = Join-Path $tmpRoot 'task2'
    [System.IO.Directory]::CreateDirectory($taskDir2) | Out-Null
    $logPrefix2 = Join-Path $taskDir2 'worker2'

    if ($isWindowsHost) {
        $si2 = New-TestStartInfo -FileName $sleepCmd -Arguments '-NoProfile -Command Start-Sleep -Seconds 30'
    } else {
        $si2 = New-TestStartInfo -FileName $sleepCmd -Arguments '30'
    }

    # Launch a background process to create the cancel file after 2 seconds.
    $cancelPath2 = Join-Path $taskDir2 'CANCEL_REQUESTED'
    $pwshExe = Join-Path $PSHOME 'pwsh'
    $cancelCmd = "Start-Sleep -Seconds 2; Set-Content -LiteralPath '$cancelPath2' -Value 'cancel'"
    $cancelArgs = @('-NoProfile', '-Command', $cancelCmd)
    if ($isWindowsHost) {
        Start-Process -FilePath $pwshExe -ArgumentList $cancelArgs -WindowStyle Hidden
    } else {
        Start-Process -FilePath $pwshExe -ArgumentList $cancelArgs
    }

    $r2 = Invoke-CapturedProcess -StartInfo $si2 -TaskDirectory $taskDir2 -TimeoutSeconds 30 -LogPrefix $logPrefix2 -TaskId 'test-cancel-w02' -ProjectId 'test'

    Assert-True 'T2: Cancelled is true' ([bool]$r2.Cancelled)
    Assert-False 'T2: TimedOut is false' ([bool]$r2.TimedOut)
    $hasAssist2 = $r2.PSObject.Properties.Name -contains 'AssistanceRequested'
    $assistVal2 = if ($hasAssist2) { [bool]$r2.AssistanceRequested } else { $false }
    Assert-False 'T2: AssistanceRequested is false' $assistVal2
    Write-Output 'PASS: CANCEL_REQUESTED file triggers cancellation.'

    # ---------------------------------------------------------------------------
    # Test 3: PollAction executes periodically.
    # ---------------------------------------------------------------------------
    $taskDir3 = Join-Path $tmpRoot 'task3'
    [System.IO.Directory]::CreateDirectory($taskDir3) | Out-Null
    $logPrefix3 = Join-Path $taskDir3 'worker3'
    $pollMarker = Join-Path $taskDir3 'poll-marker.txt'
    $pollCount = 0

    if ($isWindowsHost) {
        $si3 = New-TestStartInfo -FileName $sleepCmd -Arguments '-NoProfile -Command Start-Sleep -Seconds 12'
    } else {
        $si3 = New-TestStartInfo -FileName $sleepCmd -Arguments '12'
    }

    $pollAction = {
        $script:pollCount++
        [System.IO.File]::AppendAllText($pollMarker, "poll-$pollCount`n")
    }

    $r3 = Invoke-CapturedProcess -StartInfo $si3 -TaskDirectory $taskDir3 -TimeoutSeconds 20 -LogPrefix $logPrefix3 -TaskId 'test-poll-w03' -ProjectId 'test' -PollAction $pollAction

    Assert-False 'T3: TimedOut is false' ($r3.TimedOut)
    Assert-True 'T3: poll marker file exists' (Test-Path -LiteralPath $pollMarker -PathType Leaf)
    $markerContent = Get-Content -LiteralPath $pollMarker -Raw
    Assert-True 'T3: poll count >= 1' ($markerContent -match 'poll-')
    Write-Output 'PASS: PollAction executes periodically during process run.'

    # ---------------------------------------------------------------------------
    # Test 4: Normal completion returns correct exit code.
    # ---------------------------------------------------------------------------
    $taskDir4 = Join-Path $tmpRoot 'task4'
    [System.IO.Directory]::CreateDirectory($taskDir4) | Out-Null
    $logPrefix4 = Join-Path $taskDir4 'worker4'

    if ($isWindowsHost) {
        $si4 = New-TestStartInfo -FileName $sleepCmd -Arguments '-NoProfile -Command Write-Output hello'
    } else {
        $si4 = New-TestStartInfo -FileName '/bin/echo' -Arguments 'hello'
    }

    $r4 = Invoke-CapturedProcess -StartInfo $si4 -TaskDirectory $taskDir4 -TimeoutSeconds 10 -LogPrefix $logPrefix4 -TaskId 'test-normal-w04' -ProjectId 'test'

    Assert-True 'T4: exit code 0' ($r4.ExitCode -eq 0)
    Assert-False 'T4: Cancelled is false' ($r4.Cancelled)
    Assert-False 'T4: TimedOut is false' ($r4.TimedOut)
    Assert-True 'T4: stdout contains hello' ($r4.StandardOutput -match 'hello')
    Write-Output 'PASS: Normal completion returns correct exit code and output.'

    # ---------------------------------------------------------------------------
    # Test 5: Hard timeout triggers TimedOut when no soft timeout.
    # ---------------------------------------------------------------------------
    $taskDir5 = Join-Path $tmpRoot 'task5'
    [System.IO.Directory]::CreateDirectory($taskDir5) | Out-Null
    $logPrefix5 = Join-Path $taskDir5 'worker5'

    if ($isWindowsHost) {
        $si5 = New-TestStartInfo -FileName $sleepCmd -Arguments '-NoProfile -Command Start-Sleep -Seconds 30'
    } else {
        $si5 = New-TestStartInfo -FileName $sleepCmd -Arguments '30'
    }

    $r5 = Invoke-CapturedProcess -StartInfo $si5 -TaskDirectory $taskDir5 -TimeoutSeconds 3 -LogPrefix $logPrefix5 -TaskId 'test-hard-w05' -ProjectId 'test'

    Assert-True 'T5: TimedOut is true' ($r5.TimedOut -eq $true)
    Assert-False 'T5: Cancelled is false' ($r5.Cancelled)
    Write-Output 'PASS: Hard timeout triggers TimedOut.'

    Write-Output 'PASS: All soft-timeout/cancel/poll tests passed.'

} finally {
    Remove-Item -LiteralPath $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue
}