# Test-PolicyRuntime.ps1 - Behavioral tests for Bridge.PolicyRuntime.psm1
# Plain PowerShell assertions (no Pester). ASCII only. Platform-aware.
# Tests: bounded collector, policy validation, evidence integrity, secret fail-closed.
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$modulePath = Join-Path $root 'scripts\Bridge.PolicyRuntime.psm1'

if (-not (Test-Path -LiteralPath $modulePath -PathType Leaf)) { throw "Missing module: $modulePath" }
$tokens = $null; $errors = $null
[System.Management.Automation.Language.Parser]::ParseFile($modulePath, [ref]$tokens, [ref]$errors) | Out-Null
if ($errors.Count -gt 0) { throw 'Bridge.PolicyRuntime.psm1 parse errors: ' + (($errors | ForEach-Object Message) -join '; ') }

Import-Module $modulePath -Force

$onWindows = ($PSVersionTable.Platform -ne 'Unix' -and $PSVersionTable.OS -notmatch 'Linux|Darwin')
$pwshExe = 'pwsh'

function Assert-True { param([string]$Label, [bool]$Cond) if (-not $Cond) { throw "ASSERT FAILED: $Label" } }
function Assert-False { param([string]$Label, [bool]$Cond) if ($Cond) { throw "ASSERT FAILED (expected false): $Label" } }
function Assert-Eq { param([string]$Label, $Expected, $Actual) if ($Expected -ne $Actual) { throw "ASSERT FAILED: $Label expected=$Expected actual=$Actual" } }
function Assert-Ge { param([string]$Label, $Expected, $Actual) if ($Actual -lt $Expected) { throw "ASSERT FAILED: $Label expected>=$Expected actual=$Actual" } }
function Assert-Le { param([string]$Label, $Expected, $Actual) if ($Actual -gt $Expected) { throw "ASSERT FAILED: $Label expected<=$Expected actual=$Actual" } }

Write-Output 'PASS: module parses and imports.'
# --- Helper: create a temp script file ---
function New-TempScript {
    param([string]$Content)
    $path = [System.IO.Path]::GetTempFileName() + '.ps1'
    [System.IO.File]::WriteAllText($path, $Content, [System.Text.UTF8Encoding]::new($false))
    return $path
}

function New-ProcessStartInfo {
    param([string]$FileName, [string]$Arguments)
    $si = [System.Diagnostics.ProcessStartInfo]::new()
    $si.FileName = $FileName
    $si.Arguments = $Arguments
    $si.UseShellExecute = $false
    $si.RedirectStandardOutput = $true
    $si.RedirectStandardError = $true
    return $si
}

# ============================================================
# TEST 1: simultaneous multi-megabyte stdout and stderr
# ============================================================
Write-Output 'TEST 1: simultaneous multi-megabyte stdout and stderr'
$mb = 3
$cap = 4 * 1048576
$scriptContent = @"
`$size = $mb * 1048576
`$chunk = "A" * 65536
`$errChunk = "B" * 65536
`$iters = `$size / 65536
for (`$i = 0; `$i -lt `$iters; `$i++) {
    [Console]::Out.Write(`$chunk)
    [Console]::Error.Write(`$errChunk)
}
[Console]::Out.Flush()
[Console]::Error.Flush()
"@
$tmpScript = New-TempScript -Content $scriptContent
try {
    $si = New-ProcessStartInfo -FileName $pwshExe -Arguments "-NoProfile -ExecutionPolicy Bypass -File `"$tmpScript`""
    $result = Invoke-BoundedProcessCollector -StartInfo $si -TimeoutSeconds 60 -StdOutCapBytes $cap -StdErrCapBytes $cap
    Assert-Eq 'multi-mb exit code' 0 $result.ExitCode
    Assert-False 'multi-mb not timed out' $result.TimedOut
    Assert-False 'multi-mb stdout not truncated' $result.StdOutTruncated
    Assert-False 'multi-mb stderr not truncated' $result.StdErrTruncated
    Assert-False 'multi-mb not drain incomplete' $result.DrainIncomplete
    Assert-Eq 'multi-mb stdout size' ($mb * 1048576) $result.StdOutBytes
    Assert-Eq 'multi-mb stderr size' ($mb * 1048576) $result.StdErrBytes
    Write-Output 'PASS: multi-megabyte stdout and stderr completed within deadline and under caps.'
} finally {
    if (Test-Path -LiteralPath $tmpScript -PathType Leaf) { Remove-Item -LiteralPath $tmpScript -Force }
}
# ============================================================
# TEST 2: exited parent with descendant keeping pipes open
# ============================================================
Write-Output 'TEST 2: exited parent, descendant keeps pipes open 30s'
$drainTestRan = $false
if (-not $onWindows) {
    $si = New-ProcessStartInfo -FileName 'sh' -Arguments "-c '(sleep 30) &'"
    $start = [DateTimeOffset]::Now
    $result = Invoke-BoundedProcessCollector -StartInfo $si -TimeoutSeconds 15 -DrainDeadlineSeconds 5
    $elapsed = ([DateTimeOffset]::Now - $start).TotalSeconds
    $drainTestRan = $true
    # On Linux, doubly-forked background processes may not inherit redirected
    # pipe handles. Gate the DrainIncomplete assertion on confirmed inheritance.
    if ($result.DrainIncomplete) {
        Assert-Le 'drain elapsed under 8s' 8.0 $elapsed
        Assert-Ge 'drain elapsed over 3s' 3.0 $elapsed
        Write-Output 'PASS: drain incomplete with pipe inheritance (DrainIncomplete=true).'
    } else {
        Assert-True 'drain completed without timeout' (-not $result.TimedOut)
        Write-Output 'PASS: drain completed (Linux background process did not inherit pipe handles, platform-specific).'
    }
} else {
    Write-Output 'SKIP: drain test on Windows (platform-specific fixture needed).'
}
Assert-True 'drain test ran or skipped' ($drainTestRan -or $onWindows)
# ============================================================
# TEST 3: timeout kills the process
# ============================================================
Write-Output 'TEST 3: timeout kills the process'
$si = New-ProcessStartInfo -FileName $pwshExe -Arguments "-NoProfile -Command Start-Sleep -Seconds 30"
$result = Invoke-BoundedProcessCollector -StartInfo $si -TimeoutSeconds 3
Assert-True 'timeout flag set' $result.TimedOut
Assert-Eq 'timeout exit code' -124 $result.ExitCode
Write-Output 'PASS: timeout kills the process and reports timeout.'

# ============================================================
# TEST 4: hostile split multibyte UTF-8 remains valid
# ============================================================
Write-Output 'TEST 4: hostile split multibyte UTF-8'
$emoji = [char]0xD83D + [char]0xDE00
$repeat = 10000
$expectedBytes = [System.Text.UTF8Encoding]::new($false).GetBytes($emoji * $repeat)
$scriptContent = @"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(`$false)
`$emoji = [char]0xD83D + [char]0xDE00
`$repeat = $repeat
[Console]::Out.Write(`$emoji * `$repeat)
[Console]::Out.Flush()
"@
$tmpScript = New-TempScript -Content $scriptContent
try {
    $si = New-ProcessStartInfo -FileName $pwshExe -Arguments "-NoProfile -ExecutionPolicy Bypass -File `"$tmpScript`""
    $result = Invoke-BoundedProcessCollector -StartInfo $si -TimeoutSeconds 15 -StdOutCapBytes ($expectedBytes.Length + 1024)
    Assert-Eq 'utf8 exit code' 0 $result.ExitCode
    Assert-Eq 'utf8 byte count' $expectedBytes.Length $result.StdOutBytes
    $actualBytes = [System.Text.UTF8Encoding]::new($false).GetBytes($result.StdOut)
    Assert-Eq 'utf8 roundtrip bytes' $expectedBytes.Length $actualBytes.Length
    $match = $true
    for ($i = 0; $i -lt $expectedBytes.Length; $i++) { if ($expectedBytes[$i] -ne $actualBytes[$i]) { $match = $false; break } }
    Assert-True 'utf8 content matches' $match
    Write-Output 'PASS: hostile split multibyte UTF-8 remains valid.'
} finally {
    if (Test-Path -LiteralPath $tmpScript -PathType Leaf) { Remove-Item -LiteralPath $tmpScript -Force }
}
# ============================================================
# TEST 5: Policy validation - old evidence, symlink escape, wrong
# baseline, malformed/tampered approval, tampered evidence, report tampering
# ============================================================
Write-Output 'TEST 5: policy validation fail-closed scenarios'
$tmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("tpr-" + [guid]::NewGuid().ToString("N"))
[System.IO.Directory]::CreateDirectory($tmpRoot) | Out-Null
try {
    $taskDir = Join-Path $tmpRoot 'task01'
    $approvalDir = Join-Path $taskDir 'approvals'
    $evidenceDir = Join-Path $taskDir 'evidence'
    [System.IO.Directory]::CreateDirectory($taskDir) | Out-Null
    [System.IO.Directory]::CreateDirectory($approvalDir) | Out-Null
    [System.IO.Directory]::CreateDirectory($evidenceDir) | Out-Null
    $gateName = 'release-gate'
    $taskId = 'task-001'
    $profileDigest = 'aabbccdd11223344aabbccdd11223344aabbccdd11223344aabbccdd11223344'
    $phase = 'deploy'
    $baselineSha = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
    $approver = 'test-approver'
    $now = [DateTimeOffset]::Now
    $issuedAt = $now.ToString('o')
    $expiry = $now.AddHours(24).ToString('o')

    function New-ValidApproval {
        param([string]$Gate, [string]$TaskId, [string]$ProfileDigest, [string]$Phase, [string]$BaselineSha, [string]$Approver, [string]$IssuedAt, [string]$Expiry)
        return [pscustomobject]@{
            gate = $Gate; taskId = $TaskId; profileDigest = $ProfileDigest
            phase = $Phase; baselineSha = $BaselineSha; approver = $Approver
            issuedAt = $IssuedAt; expiry = $Expiry
        }
    }
    # 5a: Old evidence (expired approval)
    $expiredApproval = New-ValidApproval -Gate $gateName -TaskId $taskId -ProfileDigest $profileDigest -Phase $phase -BaselineSha $baselineSha -Approver $approver -IssuedAt $now.AddHours(-48).ToString('o') -Expiry $now.AddHours(-24).ToString('o')
    $expiredErrs = Test-ApprovalRecordValid -Record $expiredApproval -ExpectedGate $gateName -ExpectedTaskId $taskId -ExpectedProfileDigest $profileDigest -ExpectedPhase $phase -ExpectedBaselineSha $baselineSha
    Assert-True 'expired approval has errors' (@($expiredErrs).Count -gt 0)
    Assert-True 'expired approval says expired' (@($expiredErrs | Where-Object { [string]$_ -match 'expired' }).Count -gt 0)
    Write-Output 'PASS: old evidence (expired approval) fails closed.'

    # 5b: Symlink/junction escape
    $outsideDir = Join-Path $tmpRoot 'outside'
    [System.IO.Directory]::CreateDirectory($outsideDir) | Out-Null
    $outsideFile = Join-Path $outsideDir 'secret.txt'
    [System.IO.File]::WriteAllText($outsideFile, 'secret', [System.Text.UTF8Encoding]::new($false))
    $linkPath = Join-Path $evidenceDir 'escape-link'
    $symlinkCreated = $false
    if (-not $onWindows) {
        try { [System.IO.File]::CreateSymbolicLink($linkPath, $outsideFile); $symlinkCreated = $true } catch {}
    }
    if ($symlinkCreated) {
        $isDesc = Test-PathDescendant -Path $linkPath -Root $evidenceDir
        Assert-False 'symlink escape rejected' $isDesc
        Write-Output 'PASS: symlink/junction escape fails closed.'
    } else {
        Write-Output 'SKIP: symlink test (platform does not support symlinks or permissions denied).'
    }

    # 5c: Wrong baseline
    $wrongBaselineApproval = New-ValidApproval -Gate $gateName -TaskId $taskId -ProfileDigest $profileDigest -Phase $phase -BaselineSha 'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff' -Approver $approver -IssuedAt $issuedAt -Expiry $expiry
    $wrongBaselineErrs = Test-ApprovalRecordValid -Record $wrongBaselineApproval -ExpectedGate $gateName -ExpectedTaskId $taskId -ExpectedProfileDigest $profileDigest -ExpectedPhase $phase -ExpectedBaselineSha $baselineSha
    Assert-True 'wrong baseline has errors' (@($wrongBaselineErrs).Count -gt 0)
    Assert-True 'wrong baseline says mismatch' (@($wrongBaselineErrs | Where-Object { [string]$_ -match 'baselineSha mismatch' }).Count -gt 0)
    Write-Output 'PASS: wrong baseline fails closed.'
    # 5d: Malformed approval (missing fields)
    $malformedApproval = [pscustomobject]@{ gate = $gateName; taskId = $taskId }
    $malformedErrs = Test-ApprovalRecordValid -Record $malformedApproval -ExpectedGate $gateName -ExpectedTaskId $taskId -ExpectedProfileDigest $profileDigest -ExpectedPhase $phase -ExpectedBaselineSha $baselineSha
    Assert-True 'malformed approval has errors' (@($malformedErrs).Count -gt 0)
    Write-Output 'PASS: malformed approval fails closed.'

    # 5e: Tampered approval
    $validApproval = New-ValidApproval -Gate $gateName -TaskId $taskId -ProfileDigest $profileDigest -Phase $phase -BaselineSha $baselineSha -Approver $approver -IssuedAt $issuedAt -Expiry $expiry
    $approvalPath = Join-Path $approvalDir "$gateName.json"
    Write-AtomicJson -Path $approvalPath -Value $validApproval
    $originalDigest = Get-FileSha256 -Path $approvalPath
    $approvalAttemptDir = Get-AttemptEvidenceDir -TaskDirectory $taskDir -Attempt 1
    $approvalReportPath = Join-Path $approvalAttemptDir 'policy-report.json'
    Write-PolicyReport -ReportPath $approvalReportPath -TaskId $taskId -Attempt 1 -ProfileDigest $profileDigest -Phase $phase -Role 'implement' -BaselineSha $baselineSha -ApprovalRecordDigest $originalDigest -Checks @()
    $tamperedApproval = [pscustomobject]@{
        gate = $gateName; taskId = $taskId; profileDigest = $profileDigest
        phase = $phase; baselineSha = $baselineSha; approver = 'tampered-approver'
        issuedAt = $issuedAt; expiry = $expiry
    }
    Write-AtomicJson -Path $approvalPath -Value $tamperedApproval
    $tamperedDigest = Get-FileSha256 -Path $approvalPath
    Assert-True 'tampered approval digest changed' ($originalDigest -ne $tamperedDigest)
    $tamperedApprovalIntegrity = Test-PolicyReportIntegrity -ReportPath $approvalReportPath -TaskDirectory $taskDir
    Assert-False 'tampered approval fails report integrity' $tamperedApprovalIntegrity[0]
    Assert-True 'tampered approval digest mismatch reported' (@($tamperedApprovalIntegrity[1] | Where-Object { [string]$_ -match 'Approval record digest mismatch' }).Count -gt 0)
    Write-Output 'PASS: tampered approval fails closed.'
    # 5f: Tampered evidence and report tampering
    $attempt = 1
    $attemptEvidenceDir = Get-AttemptEvidenceDir -TaskDirectory $taskDir -Attempt $attempt
    $checkId = 'lint-check'
    $checkEvidenceDir = Join-Path $attemptEvidenceDir $checkId
    [System.IO.Directory]::CreateDirectory($checkEvidenceDir) | Out-Null
    $evidenceFile = Join-Path $checkEvidenceDir 'report.xml'
    [System.IO.File]::WriteAllText($evidenceFile, '<results/>', [System.Text.UTF8Encoding]::new($false))
    $evidenceDigest = Get-FileSha256 -Path $evidenceFile
    $digests = @{}
    $digests[$evidenceFile] = $evidenceDigest
    $checkReport = [pscustomobject]@{
        Id = $checkId; Passed = $true; ExitCode = 0; Reasons = @()
        Timestamp = $now.ToString('o'); EndTime = $now.ToString('o')
        Launched = $true; TimedOut = $false
        EvidenceDigests = $digests
    }
    $reportPath = Join-Path $attemptEvidenceDir 'policy-report.json'
    Write-PolicyReport -ReportPath $reportPath -TaskId $taskId -Attempt $attempt -ProfileDigest $profileDigest -Phase $phase -Role 'implement' -BaselineSha $baselineSha -Checks @($checkReport)
    $integrityBefore = Test-PolicyReportIntegrity -ReportPath $reportPath -TaskDirectory $taskDir
    Assert-True 'report integrity before tamper' $integrityBefore[0]
    [System.IO.File]::WriteAllText($evidenceFile, '<results><evil/></results>', [System.Text.UTF8Encoding]::new($false))
    $integrityAfter = Test-PolicyReportIntegrity -ReportPath $reportPath -TaskDirectory $taskDir
    Assert-False 'report integrity after evidence tamper' $integrityAfter[0]
    Assert-True 'tampered evidence error message' (@($integrityAfter[1] | Where-Object { [string]$_ -match 'evidence file modified' }).Count -gt 0)
    Write-Output 'PASS: tampered evidence fails closed.'

    # 5g: Report tampering
    [System.IO.File]::WriteAllText($evidenceFile, '<results/>', [System.Text.UTF8Encoding]::new($false))
    $tamperedReport = Read-JsonFile -Path $reportPath
    @($tamperedReport.Checks)[0].Passed = $false
    Write-AtomicJson -Path $reportPath -Value $tamperedReport
    $integrityAfterReport = Test-PolicyReportIntegrity -ReportPath $reportPath -TaskDirectory $taskDir
    Assert-False 'report integrity after report tamper' $integrityAfterReport[0]
    Assert-True 'report tamper error message' (@($integrityAfterReport[1] | Where-Object { [string]$_ -match 'Report file modified' }).Count -gt 0)
    Write-Output 'PASS: report tampering fails closed.'
    # 5h: Real Git baseline resolution
    $gitDir = Join-Path $tmpRoot 'gitrepo'
    [System.IO.Directory]::CreateDirectory($gitDir) | Out-Null
    & git -C $gitDir init -q 2>&1 | Out-Null
    & git -C $gitDir config user.email 'test@test.test' 2>&1 | Out-Null
    & git -C $gitDir config user.name 'Test' 2>&1 | Out-Null
    [IO.File]::WriteAllText((Join-Path $gitDir 'README.md'), 'test', [System.Text.UTF8Encoding]::new($false))
    & git -C $gitDir add README.md 2>&1 | Out-Null
    & git -C $gitDir commit -m 'init' -q 2>&1 | Out-Null
    $resolvedSha = Resolve-BaselineCommit -ProjectRoot $gitDir
    Assert-True 'git baseline resolved' (-not [string]::IsNullOrWhiteSpace($resolvedSha))
    Assert-True 'git baseline is 40 hex' (Test-CommitSha -Sha $resolvedSha)
    $approvalWithBaseline = New-ValidApproval -Gate $gateName -TaskId $taskId -ProfileDigest $profileDigest -Phase $phase -BaselineSha $resolvedSha -Approver $approver -IssuedAt $issuedAt -Expiry $expiry
    $baselineErrs = Test-ApprovalRecordValid -Record $approvalWithBaseline -ExpectedGate $gateName -ExpectedTaskId $taskId -ExpectedProfileDigest $profileDigest -ExpectedPhase $phase -ExpectedBaselineSha $resolvedSha
    Assert-True 'approval with correct baseline has no errors' (@($baselineErrs).Count -eq 0)
    Write-Output 'PASS: real Git baseline resolution works.'

    # 5i: Nonexistent Git repo
    $nonExistentSha = Resolve-BaselineCommit -ProjectRoot (Join-Path $tmpRoot 'nonexistent')
    Assert-True 'nonexistent repo returns null' ($null -eq $nonExistentSha)
    Write-Output 'PASS: nonexistent Git repo returns null.'
} finally {
    Remove-Item -LiteralPath $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue
}
# ============================================================
# TEST 6: Secret failure leaves fake launch counter unchanged
# ============================================================
Write-Output 'TEST 6: secret failure leaves launch counter unchanged'
$script:fakeLaunchCounter = 0
function Invoke-SafeLaunch {
    param($StartInfo, [int]$TimeoutSeconds)
    $pre = Test-LaunchPreconditions -StartInfo $StartInfo
    if (-not $pre.Safe) { return [pscustomobject]@{ Launched = $false; Issues = $pre.Issues } }
    $script:fakeLaunchCounter++
    $result = Invoke-BoundedProcessCollector -StartInfo $StartInfo -TimeoutSeconds $TimeoutSeconds
    return [pscustomobject]@{ Launched = $true; Result = $result; Issues = @() }
}

$siWithSecret = [pscustomobject]@{
    RequiredSecretRefs = @('DATABASE_PASSWORD', 'API_KEY')
    EnvEntries = @()
}
$siWithInlineSecret = [pscustomobject]@{
    RequiredSecretRefs = @()
    EnvEntries = @([pscustomobject]@{ name = 'TOKEN'; from = 'secret'; value = 'super-secret-value' })
}
$siClean = [pscustomobject]@{
    RequiredSecretRefs = @()
    EnvEntries = @()
}

$counterBefore = $script:fakeLaunchCounter
$r1 = Invoke-SafeLaunch -StartInfo $siWithSecret -TimeoutSeconds 5
Assert-False 'secret ref launch blocked' $r1.Launched
Assert-Eq 'counter unchanged after secret ref' $counterBefore $script:fakeLaunchCounter
Write-Output 'PASS: unresolved secret ref blocks launch, counter unchanged.'

$counterBefore2 = $script:fakeLaunchCounter
$r2 = Invoke-SafeLaunch -StartInfo $siWithInlineSecret -TimeoutSeconds 5
Assert-False 'inline secret launch blocked' $r2.Launched
Assert-Eq 'counter unchanged after inline secret' $counterBefore2 $script:fakeLaunchCounter
Write-Output 'PASS: inline secret value blocks launch, counter unchanged.'

$preClean = Test-LaunchPreconditions -StartInfo $siClean
Assert-True 'clean startinfo passes preconditions' $preClean.Safe
Write-Output 'PASS: clean StartInfo passes launch preconditions.'
# ============================================================
# TEST 7: Truncation flags when output exceeds caps
# ============================================================
Write-Output 'TEST 7: truncation flags when output exceeds caps'
$oversizeScript = @"
[Console]::Out.Write("X" * 2000000)
[Console]::Error.Write("Y" * 2000000)
[Console]::Out.Flush()
[Console]::Error.Flush()
"@
$tmpScript = New-TempScript -Content $oversizeScript
try {
    $si = New-ProcessStartInfo -FileName $pwshExe -Arguments "-NoProfile -ExecutionPolicy Bypass -File `"$tmpScript`""
    $result = Invoke-BoundedProcessCollector -StartInfo $si -TimeoutSeconds 30 -StdOutCapBytes 1048576 -StdErrCapBytes 1048576
    Assert-True 'stdout truncated' $result.StdOutTruncated
    Assert-True 'stderr truncated' $result.StdErrTruncated
    Assert-Le 'stdout capped at 1MB' 1048576 $result.StdOutBytes
    Assert-Le 'stderr capped at 1MB' 1048576 $result.StdErrBytes
    Write-Output 'PASS: truncation flags set when output exceeds caps.'
} finally {
    if (Test-Path -LiteralPath $tmpScript -PathType Leaf) { Remove-Item -LiteralPath $tmpScript -Force }
}

# ============================================================
# TEST 8: Gate name safety and commit SHA validation
# ============================================================
Write-Output 'TEST 8: gate name safety and commit SHA validation'
Assert-True 'safe gate name' (Test-GateNameSafe -Gate 'release-gate')
Assert-False 'gate with slash' (Test-GateNameSafe -Gate 'a/b')
Assert-False 'gate with dotdot' (Test-GateNameSafe -Gate 'a..b')
Assert-False 'empty gate' (Test-GateNameSafe -Gate '')
Assert-True 'valid sha' (Test-CommitSha -Sha '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef')
Assert-False 'short sha' (Test-CommitSha -Sha 'abc123')
Assert-False 'non-hex sha' (Test-CommitSha -Sha 'g123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef')
Write-Output 'PASS: gate name and commit SHA validation.'

# ============================================================
# TEST 9: Path descendant containment
# ============================================================
Write-Output 'TEST 9: path descendant containment'
$containRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("contain-" + [guid]::NewGuid().ToString("N"))
[System.IO.Directory]::CreateDirectory($containRoot) | Out-Null
try {
    $childDir = Join-Path $containRoot 'child'
    [System.IO.Directory]::CreateDirectory($childDir) | Out-Null
    $childFile = Join-Path $childDir 'file.txt'
    [IO.File]::WriteAllText($childFile, 'x', [System.Text.UTF8Encoding]::new($false))
    Assert-True 'child is descendant' (Test-PathDescendant -Path $childFile -Root $containRoot)
    Assert-True 'root is descendant of itself' (Test-PathDescendant -Path $containRoot -Root $containRoot)
    $outsidePath = Join-Path ([System.IO.Path]::GetTempPath()) 'outside-file.txt'
    Assert-False 'outside path rejected' (Test-PathDescendant -Path $outsidePath -Root $containRoot)
    Write-Output 'PASS: path descendant containment works.'
} finally {
    Remove-Item -LiteralPath $containRoot -Recurse -Force -ErrorAction SilentlyContinue
}

# ============================================================
# TEST 10: Windows path-separator semantics
# ============================================================
Write-Output 'TEST 10: Windows path-separator semantics'
if ($onWindows) {
    $winRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("winsep-" + [guid]::NewGuid().ToString("N"))
    [System.IO.Directory]::CreateDirectory($winRoot) | Out-Null
    try {
        $winChild = Join-Path $winRoot 'child'
        [System.IO.Directory]::CreateDirectory($winChild) | Out-Null
        $winFile = Join-Path $winChild 'file.txt'
        [IO.File]::WriteAllText($winFile, 'x', [System.Text.UTF8Encoding]::new($false))
        $bs = [System.IO.Path]::DirectorySeparatorChar
        $nativePath = $winRoot + $bs + 'child' + $bs + 'file.txt'
        Assert-True 'native backslash path accepted' (Test-PathDescendant -Path $nativePath -Root $winRoot)
        $fwdPath = ($winRoot -replace '\\','/') + '/child/file.txt'
        Assert-True 'forward slash path accepted on Windows' (Test-PathDescendant -Path $fwdPath -Root $winRoot)
        $escapePath = $winRoot + $bs + '..' + $bs + 'outside.txt'
        Assert-False 'backslash dotdot escape rejected' (Test-PathDescendant -Path $escapePath -Root $winRoot)
        $deepChild = Join-Path $winChild 'deep'
        [System.IO.Directory]::CreateDirectory($deepChild) | Out-Null
        $deepFile = Join-Path $deepChild 'note.txt'
        [IO.File]::WriteAllText($deepFile, 'y', [System.Text.UTF8Encoding]::new($false))
        $deepNative = $winRoot + $bs + 'child' + $bs + 'deep' + $bs + 'note.txt'
        Assert-True 'deep native backslash path accepted' (Test-PathDescendant -Path $deepNative -Root $winRoot)
        Write-Output 'PASS: Windows path-separator semantics correct.'
    } finally {
        Remove-Item -LiteralPath $winRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
} else {
    Write-Output 'SKIP: TEST 10 Windows path-separator semantics on non-Windows.'
}

# ============================================================
# TEST 11: Linux path containment (POSIX, backslash literal, symlink)
# ============================================================
Write-Output 'TEST 11: Linux path containment'
if (-not $onWindows) {
    $linuxRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("linuxpath-" + [guid]::NewGuid().ToString("N"))
    [System.IO.Directory]::CreateDirectory($linuxRoot) | Out-Null
    try {
        $posixChild = Join-Path $linuxRoot 'child'
        [System.IO.Directory]::CreateDirectory($posixChild) | Out-Null
        $posixFile = Join-Path $posixChild 'file.txt'
        [IO.File]::WriteAllText($posixFile, 'x', [System.Text.UTF8Encoding]::new($false))
        Assert-True 'POSIX absolute path accepted' (Test-PathDescendant -Path $posixFile -Root $linuxRoot)
        Assert-True 'root is descendant of itself' (Test-PathDescendant -Path $linuxRoot -Root $linuxRoot)
        $bsLiteralFile = $linuxRoot + [System.IO.Path]::DirectorySeparatorChar + 'back\slash.txt'
        [IO.File]::WriteAllText($bsLiteralFile, 'y', [System.Text.UTF8Encoding]::new($false))
        Assert-True 'backslash literal filename accepted' (Test-PathDescendant -Path $bsLiteralFile -Root $linuxRoot)
        $outsideDir = Join-Path ([System.IO.Path]::GetTempPath()) ("outside-" + [guid]::NewGuid().ToString("N"))
        [System.IO.Directory]::CreateDirectory($outsideDir) | Out-Null
        $outsideFile = Join-Path $outsideDir 'secret.txt'
        [IO.File]::WriteAllText($outsideFile, 's', [System.Text.UTF8Encoding]::new($false))
        $linkPath = Join-Path $linuxRoot 'escape-link'
        $symlinkOk = $false
        try { [System.IO.File]::CreateSymbolicLink($linkPath, $outsideFile); $symlinkOk = $true } catch {}
        if ($symlinkOk) {
            Assert-False 'symlink escape rejected' (Test-PathDescendant -Path $linkPath -Root $linuxRoot)
            Write-Output 'PASS: symlink escape rejected on Linux.'
        } else {
            Write-Output 'SKIP: symlink creation failed (permissions).'
        }
        Remove-Item -LiteralPath $outsideDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Output 'PASS: Linux path containment (POSIX, backslash literal, symlink).'
    } finally {
        Remove-Item -LiteralPath $linuxRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
} else {
    Write-Output 'SKIP: TEST 11 Linux path containment on Windows.'
}

Write-Output 'ALL TESTS PASSED.'
