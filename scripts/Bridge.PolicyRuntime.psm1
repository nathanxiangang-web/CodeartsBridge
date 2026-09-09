# Bridge.PolicyRuntime.psm1
# Generic policy runtime and production-safe bounded process collector.
# Extracted and hardened from bridge.ps1 W02 accepted logic.
# No monolithic scheduler dependency. May import Bridge.Policy.psm1 for
# profile/gate helpers but does not copy scheduler code.
# Plain ASCII. No Pester. No third-party dependencies. No network access.

Set-StrictMode -Version Latest

$script:CommitShaPattern = '^(?:[0-9a-f]{40}|[0-9a-f]{64})$'
$script:MaxDrainSeconds = 5
$script:PolicyModulePath = Join-Path $PSScriptRoot 'Bridge.Policy.psm1'
if (-not (Test-Path -LiteralPath $script:PolicyModulePath -PathType Leaf)) {
    throw "Policy module not found: $script:PolicyModulePath"
}
Import-Module $script:PolicyModulePath -Force

function Get-PolicyRuntimeVersion { return 1 }
function Write-AtomicText {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][AllowEmptyString()][string]$Content
    )
    $directory = Split-Path -Parent $Path
    [System.IO.Directory]::CreateDirectory($directory) | Out-Null
    $tempPath = Join-Path $directory ('.' + [System.IO.Path]::GetFileName($Path) + '.' + [guid]::NewGuid().ToString('N') + '.tmp')
    [System.IO.File]::WriteAllText($tempPath, $Content, [System.Text.UTF8Encoding]::new($false))
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $backupPath = $tempPath + '.bak'
        [System.IO.File]::Replace($tempPath, $Path, $backupPath)
        [System.IO.File]::Delete($backupPath)
    } else {
        [System.IO.File]::Move($tempPath, $Path)
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
    $text = [System.IO.File]::ReadAllText($Path, [System.Text.UTF8Encoding]::new($false))
    if ([string]::IsNullOrWhiteSpace($text)) { throw "Empty JSON: $Path" }
    return ($text | ConvertFrom-Json)
}
function Test-PathDescendant {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Root)
    try {
        $fullPath = [System.IO.Path]::GetFullPath($Path)
        $fullRoot = [System.IO.Path]::GetFullPath($Root)
    } catch { return $false }
    $sep = [System.IO.Path]::DirectorySeparatorChar
    $platIsWin = ($PSVersionTable.Platform -ne 'Unix')
    $cmp = if ($platIsWin) { [System.StringComparison]::OrdinalIgnoreCase } else { [System.StringComparison]::Ordinal }
    $rootWithSep = if ($fullRoot.EndsWith($sep)) { $fullRoot } else { $fullRoot + $sep }
    if (-not [string]::Equals($fullPath, $fullRoot, $cmp) -and -not $fullPath.StartsWith($rootWithSep, $cmp)) { return $false }
    $segToCheck = $fullRoot
    while ($segToCheck -ne $fullPath) {
        $child = $fullPath
        while ($true) {
            $parent = [System.IO.Path]::GetDirectoryName($child)
            if ($null -eq $parent -or [string]::Equals($parent, $segToCheck, $cmp)) { break }
            $child = $parent
        }
        if (-not [string]::Equals($child, $segToCheck, $cmp)) {
            $nextSeg = if ([string]::Equals($child, $fullPath, $cmp)) { $fullPath } else { $child }
        } else { $nextSeg = $fullPath }
        if (Test-Path -LiteralPath $nextSeg -ErrorAction SilentlyContinue) {
            try {
                $item = Get-Item -LiteralPath $nextSeg -ErrorAction SilentlyContinue
                if ($item -and $item.LinkType) { return $false }
            } catch { return $false }
        }
        $segToCheck = $nextSeg
        if ([string]::Equals($segToCheck, $fullPath, $cmp)) { break }
    }
    return $true
}
function Test-GateNameSafe {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Gate)
    if ([string]::IsNullOrWhiteSpace($Gate)) { return $false }
    if ($Gate -match '[/\\]' -or $Gate -match '\.\.' -or $Gate -match '[<>|:*?"'']') { return $false }
    return $true
}

function Test-CommitSha {
    param([Parameter(Mandatory)][string]$Sha)
    return $Sha -match $script:CommitShaPattern
}

function Resolve-BaselineCommit {
    param([Parameter(Mandatory)][string]$ProjectRoot)
    if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) { return $null }
    $headResult = & git -C $ProjectRoot rev-parse HEAD 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    $sha = ([string]$headResult).Trim()
    if (-not (Test-CommitSha -Sha $sha)) { return $null }
    $null = & git -C $ProjectRoot cat-file -e "$sha^{commit}" 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    return $sha
}

function Get-AttemptEvidenceDir {
    param([Parameter(Mandatory)][string]$TaskDirectory, [Parameter(Mandatory)][int]$Attempt)
    $dir = Join-Path $TaskDirectory (Join-Path 'evidence' ("attempt-{0:D3}" -f $Attempt))
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) {
        [System.IO.Directory]::CreateDirectory($dir) | Out-Null
    }
    return $dir
}
function Get-FileSha256 {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-','').ToLower() }
    finally { $sha.Dispose() }
}

function Get-ProfileDigest {
    param([Parameter(Mandatory)][string]$ProfilePath)
    $profileBytes = [System.IO.File]::ReadAllBytes($ProfilePath)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha256.ComputeHash($profileBytes)).Replace('-','').ToLower() }
    finally { $sha256.Dispose() }
}

function Get-ApprovalRecord {
    param([Parameter(Mandatory)][string]$TaskDirectory, [Parameter(Mandatory)][string]$Gate)
    if (-not (Test-GateNameSafe -Gate $Gate)) { return $null }
    $approvalPath = Join-Path $TaskDirectory (Join-Path 'approvals' ("$Gate.json"))
    if (-not (Test-Path -LiteralPath $approvalPath -PathType Leaf)) { return $null }
    try { return Read-JsonFile -Path $approvalPath } catch { return $null }
}
function Test-ApprovalRecordValid {
    param(
        [Parameter(Mandatory)]$Record,
        [Parameter(Mandatory)][string]$ExpectedGate,
        [Parameter(Mandatory)][string]$ExpectedTaskId,
        [Parameter(Mandatory)][string]$ExpectedProfileDigest,
        [Parameter(Mandatory)][string]$ExpectedPhase,
        [string]$ExpectedBaselineSha
    )
    $errs = @()
    $props = @($Record.PSObject.Properties.Name)
    if ($props -notcontains 'gate' -or [string]$Record.gate -ne $ExpectedGate) { $errs += 'gate mismatch' }
    if ($props -notcontains 'taskId' -or [string]$Record.taskId -ne $ExpectedTaskId) { $errs += 'taskId mismatch' }
    if ($props -notcontains 'profileDigest' -or [string]$Record.profileDigest -ne $ExpectedProfileDigest) { $errs += 'profileDigest mismatch' }
    if ($props -notcontains 'phase' -or [string]$Record.phase -ne $ExpectedPhase) { $errs += 'phase mismatch' }
    if ($props -notcontains 'baselineSha' -or [string]::IsNullOrWhiteSpace([string]$Record.baselineSha)) { $errs += 'baselineSha missing' }
    elseif (-not [string]::IsNullOrWhiteSpace($ExpectedBaselineSha) -and [string]$Record.baselineSha -ne $ExpectedBaselineSha) { $errs += 'baselineSha mismatch' }
    if ($props -notcontains 'approver' -or [string]::IsNullOrWhiteSpace([string]$Record.approver)) { $errs += 'approver missing' }
    $issuedAt = $null
    if ($props -contains 'issuedAt') {
        try { $issuedAt = [DateTimeOffset]::Parse([string]$Record.issuedAt) } catch { $errs += 'issuedAt malformed' }
    } elseif ($props -contains 'timestamp') {
        try { $issuedAt = [DateTimeOffset]::Parse([string]$Record.timestamp) } catch { $errs += 'timestamp malformed' }
    } else { $errs += 'issuedAt missing' }
    if ($null -ne $issuedAt) {
        $now = [DateTimeOffset]::Now
        if ($issuedAt -gt $now.AddHours(1)) { $errs += 'issuedAt future-dated' }
    }
    if ($props -contains 'expiry') {
        try { $expTime = [DateTimeOffset]::Parse([string]$Record.expiry); if ($expTime -lt [DateTimeOffset]::Now) { $errs += 'expired' } } catch { $errs += 'expiry malformed' }
    } else { $errs += 'expiry missing' }
    return [string[]]@($errs)
}
function Test-NoInlineSecrets {
    param([Parameter(Mandatory)]$StartInfo)
    $issues = @()
    $envList = $null
    if ($StartInfo.PSObject.Properties.Name -contains 'EnvEntries') { $envList = $StartInfo.EnvEntries }
    if ($null -ne $envList) {
        foreach ($e in @($envList)) {
            $eProps = @($e.PSObject.Properties.Name)
            foreach ($k in $eProps) {
                if ($k -eq 'value' -or $k -eq 'secretValue' -or $k -eq 'literal' -or $k -eq 'inline') {
                    $issues += "Inline secret value forbidden in env entry: $k"
                }
            }
        }
    }
    return [pscustomobject]@{ Safe = ($issues.Count -eq 0); Issues = [string[]]@($issues) }
}

function Test-SecretRefFailClosed {
    param([Parameter(Mandatory)]$StartInfo)
    $issues = @()
    $refs = $null
    if ($StartInfo.PSObject.Properties.Name -contains 'RequiredSecretRefs') { $refs = $StartInfo.RequiredSecretRefs }
    if ($null -ne $refs -and @($refs).Count -gt 0) {
        $issues += "Unresolved secret references: ($(@($refs) -join ', '))"
    }
    return [pscustomobject]@{ Safe = ($issues.Count -eq 0); Issues = [string[]]@($issues) }
}

function Test-LaunchPreconditions {
    param([Parameter(Mandatory)]$StartInfo)
    $inline = Test-NoInlineSecrets -StartInfo $StartInfo
    $secretRef = Test-SecretRefFailClosed -StartInfo $StartInfo
    $allIssues = @()
    $allIssues += $inline.Issues
    $allIssues += $secretRef.Issues
    return [pscustomobject]@{ Safe = ($allIssues.Count -eq 0); Issues = [string[]]@($allIssues) }
}

function Invoke-BoundedProcessCollector {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][System.Diagnostics.ProcessStartInfo]$StartInfo,
        [Parameter(Mandatory)][int]$TimeoutSeconds,
        [int]$StdOutCapBytes = 1048576,
        [int]$StdErrCapBytes = 1048576,
        [int]$DrainDeadlineSeconds = 5
    )
    if ($TimeoutSeconds -lt 1) { throw 'TimeoutSeconds must be positive' }
    if ($StdOutCapBytes -lt 1 -or $StdErrCapBytes -lt 1) { throw 'Output caps must be positive' }
    $DrainDeadlineSeconds = [Math]::Max(1, [Math]::Min($DrainDeadlineSeconds, $script:MaxDrainSeconds))

    $proc = [System.Diagnostics.Process]::new()
    $stdoutStream = $null
    $stderrStream = $null
    $stdoutTask = $null
    $stderrTask = $null
    $stdoutBytes = [System.Collections.Generic.List[byte]]::new()
    $stderrBytes = [System.Collections.Generic.List[byte]]::new()
    $stdoutTruncated = $false
    $stderrTruncated = $false
    $drainIncomplete = $false
    $timedOut = $false
    $exitCode = -1

    try {
        $StartInfo.RedirectStandardOutput = $true
        $StartInfo.RedirectStandardError = $true
        $StartInfo.UseShellExecute = $false
        $proc.StartInfo = $StartInfo
        if (-not $proc.Start()) { throw 'Failed to start process' }
        $stdoutStream = $proc.StandardOutput.BaseStream
        $stderrStream = $proc.StandardError.BaseStream
        $bufSize = 8192
        $stdoutBuf = [byte[]]::new($bufSize)
        $stderrBuf = [byte[]]::new($bufSize)
        $stdoutTask = $stdoutStream.ReadAsync($stdoutBuf, 0, $bufSize)
        $stderrTask = $stderrStream.ReadAsync($stderrBuf, 0, $bufSize)
        $stdoutDone = $false
        $stderrDone = $false
        $processExited = $false
        $processDeadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
        $drainDeadline = [DateTimeOffset]::MaxValue

        while (-not ($stdoutDone -and $stderrDone)) {
            $now = [DateTimeOffset]::UtcNow
            if (-not $processExited) {
                if ($proc.HasExited) {
                    $processExited = $true
                    $drainDeadline = $now.AddSeconds($DrainDeadlineSeconds)
                } elseif ($now -ge $processDeadline) {
                    $timedOut = $true
                    try { $proc.Kill($true) } catch { try { $proc.Kill() } catch {} }
                    $processExited = $true
                    $drainDeadline = $now.AddSeconds($DrainDeadlineSeconds)
                }
            }
            if ($processExited -and $now -ge $drainDeadline) {
                if (-not $stdoutDone -or -not $stderrDone) { $drainIncomplete = $true }
                break
            }

            if (-not $stdoutDone -and $stdoutTask.IsCompleted) {
                try { $n = $stdoutTask.GetAwaiter().GetResult() } catch { $n = 0 }
                if ($n -le 0) {
                    $stdoutDone = $true
                } else {
                    $room = $StdOutCapBytes - $stdoutBytes.Count
                    if ($room -gt 0) {
                        $copyCount = [Math]::Min($n, $room)
                        $stdoutBytes.AddRange([byte[]]@($stdoutBuf[0..($copyCount - 1)]))
                    }
                    if ($n -gt $room) { $stdoutTruncated = $true }
                    $stdoutTask = $stdoutStream.ReadAsync($stdoutBuf, 0, $bufSize)
                }
            }
            if (-not $stderrDone -and $stderrTask.IsCompleted) {
                try { $n = $stderrTask.GetAwaiter().GetResult() } catch { $n = 0 }
                if ($n -le 0) {
                    $stderrDone = $true
                } else {
                    $room = $StdErrCapBytes - $stderrBytes.Count
                    if ($room -gt 0) {
                        $copyCount = [Math]::Min($n, $room)
                        $stderrBytes.AddRange([byte[]]@($stderrBuf[0..($copyCount - 1)]))
                    }
                    if ($n -gt $room) { $stderrTruncated = $true }
                    $stderrTask = $stderrStream.ReadAsync($stderrBuf, 0, $bufSize)
                }
            }
            if (-not ($stdoutDone -and $stderrDone)) { [System.Threading.Thread]::Sleep(2) }
        }
        if (-not $timedOut -and $proc.HasExited) { $exitCode = $proc.ExitCode }
        if ($timedOut) { $exitCode = -124 }
    }
    finally {
        if ($null -ne $stdoutStream) { try { $stdoutStream.Dispose() } catch {} }
        if ($null -ne $stderrStream) { try { $stderrStream.Dispose() } catch {} }
        try {
            if (-not $proc.HasExited) {
                try { $proc.Kill($true) } catch { try { $proc.Kill() } catch {} }
            }
        } catch {}
        $proc.Dispose()
    }

    $enc = [System.Text.UTF8Encoding]::new($false)
    $stdout = $enc.GetString($stdoutBytes.ToArray())
    $stderr = $enc.GetString($stderrBytes.ToArray())
    return [pscustomobject]@{
        ExitCode = $exitCode
        StdOut = $stdout
        StdErr = $stderr
        StdOutBytes = $stdoutBytes.Count
        StdErrBytes = $stderrBytes.Count
        StdOutTruncated = $stdoutTruncated
        StdErrTruncated = $stderrTruncated
        DrainIncomplete = $drainIncomplete
        TimedOut = $timedOut
    }
}
function Write-PolicyReport {
    param(
        [Parameter(Mandatory)][string]$ReportPath,
        [Parameter(Mandatory)][string]$TaskId,
        [Parameter(Mandatory)][int]$Attempt,
        [Parameter(Mandatory)][string]$ProfileDigest,
        [Parameter(Mandatory)][string]$Phase,
        [Parameter(Mandatory)][string]$Role,
        [Parameter(Mandatory)][string]$BaselineSha,
        [string]$ApprovalRecordDigest,
        [Parameter(Mandatory)]$Checks
    )
    $reportObj = [pscustomobject]@{
        Timestamp = [DateTimeOffset]::Now.ToString('o')
        TaskId = $TaskId
        Attempt = $Attempt
        ProfileDigest = $ProfileDigest
        Phase = $Phase
        Role = $Role
        BaselineSha = $BaselineSha
        ApprovalRecordDigest = $ApprovalRecordDigest
        Checks = [object[]]@($Checks)
    }
    Write-AtomicJson -Path $ReportPath -Value $reportObj
    $reportDigest = Get-FileSha256 -Path $ReportPath
    Write-AtomicText -Path ($ReportPath + '.sha256') -Content ($reportDigest + [Environment]::NewLine)
}
function Test-PolicyReportIntegrity {
    param(
        [Parameter(Mandatory)][string]$ReportPath,
        [Parameter(Mandatory)][string]$TaskDirectory
    )
    if (-not (Test-Path -LiteralPath $ReportPath -PathType Leaf)) { return @($false, @('Report file not found')) }
    $digestPath = $ReportPath + '.sha256'
    if (-not (Test-Path -LiteralPath $digestPath -PathType Leaf)) { return @($false, @('Report digest file not found')) }
    $expectedReportDigest = ([System.IO.File]::ReadAllText($digestPath)).Trim().ToLowerInvariant()
    if ($expectedReportDigest -notmatch '^[0-9a-f]{64}$') { return @($false, @('Report digest is malformed')) }
    if ((Get-FileSha256 -Path $ReportPath) -ne $expectedReportDigest) { return @($false, @('Report file modified after creation')) }
    try { $report = Read-JsonFile -Path $ReportPath } catch { return @($false, @('Report file malformed')) }
    $errs = @()
    $props = @($report.PSObject.Properties.Name)
    if ($props -notcontains 'TaskId') { $errs += 'Report missing TaskId' }
    if ($props -notcontains 'Attempt') { $errs += 'Report missing Attempt' }
    if ($props -notcontains 'ProfileDigest') { $errs += 'Report missing ProfileDigest' }
    if ($props -notcontains 'Phase') { $errs += 'Report missing Phase' }
    if ($props -notcontains 'BaselineSha') { $errs += 'Report missing BaselineSha' }
    if ($errs.Count -gt 0) { return @($false, $errs) }
    $reportAttempt = [int]$report.Attempt
    $expectedEvidenceDir = Join-Path $TaskDirectory (Join-Path 'evidence' ("attempt-{0:D3}" -f $reportAttempt))
    if (-not (Test-Path -LiteralPath $expectedEvidenceDir -PathType Container)) { $errs += 'Evidence directory for attempt not found' }
    if ($props -contains 'ApprovalRecordDigest' -and -not [string]::IsNullOrWhiteSpace([string]$report.ApprovalRecordDigest)) {
        $approvalDigest = [string]$report.ApprovalRecordDigest
        $approvalDir = Join-Path $TaskDirectory 'approvals'
        $foundApproval = $false
        if (Test-Path -LiteralPath $approvalDir -PathType Container) {
            $approvalFiles = @(Get-ChildItem -LiteralPath $approvalDir -File -Filter '*.json' -ErrorAction SilentlyContinue)
            foreach ($af in $approvalFiles) {
                $afSha = Get-FileSha256 -Path $af.FullName
                if ($afSha -eq $approvalDigest) { $foundApproval = $true; break }
            }
        }
        if (-not $foundApproval) { $errs += 'Approval record digest mismatch - approval record modified or deleted' }
    }
    if ($props -contains 'Checks') {
        $checks = @($report.Checks)
        foreach ($chk in $checks) {
            $chkProps = @($chk.PSObject.Properties.Name)
            $chkId = if ($chkProps -contains 'Id') { [string]$chk.Id } else { 'unknown' }
            if ($chkProps -contains 'EvidenceDigests' -and $null -ne $chk.EvidenceDigests) {
                $storedDigests = $chk.EvidenceDigests
                $chkEvidenceDir = Join-Path $expectedEvidenceDir $chkId
                if (-not (Test-Path -LiteralPath $chkEvidenceDir -PathType Container)) {
                    if ($storedDigests.PSObject.Properties.Name.Count -gt 0) {
                        $errs += "Check '$chkId' evidence directory missing but digests recorded"
                    }
                    continue
                }
                $storedNames = @($storedDigests.PSObject.Properties.Name)
                foreach ($storedName in $storedNames) {
                    $storedSha = [string]($storedDigests.$storedName)
                    $efName = [System.IO.Path]::GetFileName($storedName)
                    $efPath = Join-Path $chkEvidenceDir $efName
                    if (-not (Test-Path -LiteralPath $efPath -PathType Leaf)) {
                        $errs += "Check '$chkId' evidence file deleted: $efName"
                        continue
                    }
                    if (-not (Test-PathDescendant -Path $efPath -Root $expectedEvidenceDir)) {
                        $errs += "Check '$chkId' evidence path escape: $efName"
                        continue
                    }
                    $currentSha = Get-FileSha256 -Path $efPath
                    if ($currentSha -ne $storedSha) {
                        $errs += "Check '$chkId' evidence file modified: $efName"
                    }
                }
                $actualFiles = @(Get-ChildItem -LiteralPath $chkEvidenceDir -File -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
                $storedFileNames = @($storedNames | ForEach-Object { [System.IO.Path]::GetFileName($_) })
                foreach ($af in $actualFiles) {
                    if ($storedFileNames -notcontains $af) {
                        $errs += "Check '$chkId' unexpected extra evidence file: $af"
                    }
                }
            }
        }
    }
    if ($errs.Count -gt 0) { return @($false, $errs) }
    return @($true, @())
}
function Get-PreCheckDigests {
    param([Parameter(Mandatory)][string]$Outbox)
    $dict = @{}
    if (Test-Path -LiteralPath $Outbox -PathType Container) {
        @(Get-ChildItem -LiteralPath $Outbox -File -Recurse -ErrorAction SilentlyContinue) | ForEach-Object {
            $dict[$_.FullName] = (Get-FileSha256 -Path $_.FullName)
        }
    }
    return $dict
}

function Get-FreshEvidence {
    param(
        [Parameter(Mandatory)][string]$Outbox,
        [Parameter(Mandatory)][string]$EvidenceRoot,
        $PreCheckDigests
    )
    $fresh = @()
    if (-not (Test-Path -LiteralPath $Outbox -PathType Container)) { return [string[]]@($fresh) }
    @(Get-ChildItem -LiteralPath $Outbox -File -Recurse -ErrorAction SilentlyContinue) | ForEach-Object {
        $fpath = $_.FullName
        $newSha = Get-FileSha256 -Path $fpath
        $oldSha = if ($null -ne $PreCheckDigests -and $PreCheckDigests.ContainsKey($fpath)) { $PreCheckDigests[$fpath] } else { $null }
        if ($null -eq $oldSha -or $oldSha -ne $newSha) {
            if (Test-PathDescendant -Path $fpath -Root $Outbox) {
                $fresh += $fpath
            }
        }
    }
    return [string[]]@($fresh)
}
function Copy-EvidenceFiles {
    param(
        [Parameter(Mandatory)][string]$EvidenceDir,
        [Parameter(Mandatory)][string[]]$Files
    )
    $digests = @{}
    if (-not (Test-Path -LiteralPath $EvidenceDir -PathType Container)) {
        [System.IO.Directory]::CreateDirectory($EvidenceDir) | Out-Null
    }
    foreach ($ef in $Files) {
        if (-not (Test-Path -LiteralPath $ef -PathType Leaf)) { continue }
        $efSha = Get-FileSha256 -Path $ef
        $efName = [System.IO.Path]::GetFileName($ef)
        $efDest = Join-Path $EvidenceDir $efName
        $digests[$ef] = $efSha
        [System.IO.File]::Copy($ef, $efDest, $true)
    }
    return $digests
}

function Get-PolicyProp {
    param($Object, [Parameter(Mandatory)][string]$Name)
    if ($null -eq $Object) { return $null }
    if ($Object -is [System.Collections.IDictionary]) {
        if ($Object.Contains($Name)) { return $Object[$Name] }
        return $null
    }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -ne $property) { return $property.Value }
    return $null
}

function Get-DeclaredEvidenceSnapshot {
    param($Check, [Parameter(Mandatory)][string]$ProjectRoot)
    $snapshot = @{}
    foreach ($item in @((Get-PolicyProp -Object $Check -Name 'requiredEvidence'))) {
        if ([string]::IsNullOrWhiteSpace([string]$item)) { continue }
        $candidate = if ([System.IO.Path]::IsPathRooted([string]$item)) { [string]$item } else { Join-Path $ProjectRoot ([string]$item) }
        if (-not (Test-PathDescendant -Path $candidate -Root $ProjectRoot)) { throw "Evidence path escapes project root: $item" }
        $snapshot[$candidate] = Get-FileSha256 -Path $candidate
    }
    return $snapshot
}

function Get-FreshDeclaredEvidence {
    param($Check, [Parameter(Mandatory)][string]$ProjectRoot, [Parameter(Mandatory)]$Before)
    $fresh = [System.Collections.Generic.List[string]]::new()
    foreach ($item in @((Get-PolicyProp -Object $Check -Name 'requiredEvidence'))) {
        if ([string]::IsNullOrWhiteSpace([string]$item)) { continue }
        $candidate = if ([System.IO.Path]::IsPathRooted([string]$item)) { [string]$item } else { Join-Path $ProjectRoot ([string]$item) }
        if (-not (Test-PathDescendant -Path $candidate -Root $ProjectRoot)) { throw "Evidence path escapes project root: $item" }
        $afterDigest = Get-FileSha256 -Path $candidate
        $beforeDigest = if ($Before.ContainsKey($candidate)) { $Before[$candidate] } else { $null }
        if ($null -ne $afterDigest -and ($null -eq $beforeDigest -or $beforeDigest -ne $afterDigest)) { $null = $fresh.Add($candidate) }
    }
    return [string[]]@($fresh.ToArray())
}

function Invoke-PolicyCheckSet {
    param(
        [Parameter(Mandatory)][object[]]$Checks,
        [Parameter(Mandatory)][ValidateSet('check', 'finally')][string]$Kind,
        [Parameter(Mandatory)]$Profile,
        [Parameter(Mandatory)]$Phase,
        [Parameter(Mandatory)][string]$PhaseId,
        [Parameter(Mandatory)][string]$ProjectRoot,
        [Parameter(Mandatory)][string]$TaskDirectory,
        [Parameter(Mandatory)][string]$EvidenceRoot
    )
    $rows = [System.Collections.Generic.List[object]]::new()
    $blockingMessages = [System.Collections.Generic.List[string]]::new()
    $secretRefs = [System.Collections.Generic.List[string]]::new()
    $outbox = Join-Path $TaskDirectory 'outbox'
    foreach ($check in $Checks) {
        $checkId = [string](Get-PolicyProp -Object $check -Name 'id')
        $started = [DateTimeOffset]::Now
        $launched = $false
        $procResult = $null
        $evidenceDigests = @{}
        $passed = $false
        $reasons = @()
        $exitCode = -1
        try {
            $outboxBefore = Get-PreCheckDigests -Outbox $outbox
            $declaredBefore = Get-DeclaredEvidenceSnapshot -Check $check -ProjectRoot $ProjectRoot
            $start = New-BridgeCheckStartInfo -Check $check -ProjectRoot $ProjectRoot
            foreach ($secretRef in @($start.RequiredSecretRefs)) { $null = $secretRefs.Add([string]$secretRef) }
            $preconditions = Test-LaunchPreconditions -StartInfo $start
            if (-not $preconditions.Safe) { throw ($preconditions.Issues -join '; ') }
            $workingDirectory = [string]$start.StartInfo.WorkingDirectory
            if (-not [string]::IsNullOrWhiteSpace($workingDirectory) -and -not (Test-PathDescendant -Path $workingDirectory -Root $ProjectRoot)) {
                throw "Check '$checkId' working directory escapes project root"
            }
            $timeout = Get-BridgeTimeout -Profile $Profile -PhaseId $PhaseId -CheckId $checkId
            if ($null -eq $timeout -or [int]$timeout -lt 1) { $timeout = 300 }
            $procResult = Invoke-BoundedProcessCollector -StartInfo $start.StartInfo -TimeoutSeconds ([int]$timeout)
            $launched = $true
            $exitCode = [int]$procResult.ExitCode
            $fresh = @(
                @(Get-FreshEvidence -Outbox $outbox -EvidenceRoot $EvidenceRoot -PreCheckDigests $outboxBefore)
                @(Get-FreshDeclaredEvidence -Check $check -ProjectRoot $ProjectRoot -Before $declaredBefore)
            ) | Select-Object -Unique
            $checkResult = Test-BridgeCheckResult -Check $check -ExitCode $exitCode -EvidenceFiles $fresh
            $passed = [bool]$checkResult.Passed -and -not $procResult.DrainIncomplete
            $reasons = @($checkResult.Reasons)
            if ($procResult.DrainIncomplete) { $reasons += 'Output drain did not complete before the bounded deadline.' }
            $evidenceDigests = Copy-EvidenceFiles -EvidenceDir (Join-Path $EvidenceRoot $checkId) -Files $fresh
        } catch {
            $reasons = @($_.Exception.Message)
        }
        $row = [pscustomobject]@{
            Id = $checkId
            Kind = $Kind
            Passed = $passed
            ExitCode = $exitCode
            Reasons = [string[]]@($reasons)
            Timestamp = $started.ToString('o')
            EndTime = [DateTimeOffset]::Now.ToString('o')
            Launched = $launched
            TimedOut = if ($null -ne $procResult) { [bool]$procResult.TimedOut } else { $false }
            DrainIncomplete = if ($null -ne $procResult) { [bool]$procResult.DrainIncomplete } else { $false }
            StdOutBytes = if ($null -ne $procResult) { [int]$procResult.StdOutBytes } else { 0 }
            StdErrBytes = if ($null -ne $procResult) { [int]$procResult.StdErrBytes } else { 0 }
            StdOutTruncated = if ($null -ne $procResult) { [bool]$procResult.StdOutTruncated } else { $false }
            StdErrTruncated = if ($null -ne $procResult) { [bool]$procResult.StdErrTruncated } else { $false }
            EvidenceDigests = $evidenceDigests
        }
        $null = $rows.Add($row)
        if (-not $passed) {
            $phaseRisk = [string](Get-PolicyProp -Object $Phase -Name 'riskLevel')
            $checkRisk = [string](Get-PolicyProp -Object $check -Name 'riskLevel')
            $onFailure = [string](Get-PolicyProp -Object $Phase -Name 'onFailure')
            $mustBlock = ($Kind -eq 'finally' -or $PhaseId -in @('deploy', 'rollback') -or $phaseRisk -eq 'critical' -or $checkRisk -eq 'critical' -or $onFailure -eq 'block' -or [string]::IsNullOrWhiteSpace($onFailure))
            if ($mustBlock) { $null = $blockingMessages.Add("$Kind '$checkId' failed: $($reasons -join '; ')") }
        }
    }
    return [pscustomobject]@{ Rows = [object[]]@($rows.ToArray()); BlockingMessages = [string[]]@($blockingMessages.ToArray()); SecretRefs = [string[]]@($secretRefs.ToArray()) }
}

function Invoke-BridgePolicyPhase {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ProfilePath,
        [Parameter(Mandatory)][string]$ProjectRoot,
        [Parameter(Mandatory)][string]$TaskDirectory,
        [Parameter(Mandatory)][string]$TaskId,
        [Parameter(Mandatory)][string]$PhaseId,
        [Parameter(Mandatory)][string]$Role,
        [Parameter(Mandatory)][int]$Attempt,
        [string]$ExpectedProjectId
    )
    $profile = Load-BridgeProfile -Path $ProfilePath
    Assert-BridgeProfile -Profile $profile
    if (-not [string]::IsNullOrWhiteSpace($ExpectedProjectId) -and [string]$profile.projectId -ne $ExpectedProjectId) {
        throw "Profile projectId mismatch: $($profile.projectId) vs $ExpectedProjectId"
    }
    $phase = Get-BridgePhase -Profile $profile -PhaseId $PhaseId
    if ($null -eq $phase) { throw "Unknown policy phase: $PhaseId" }
    $phaseRoles = @((Get-PolicyProp -Object $phase -Name 'roles'))
    if ($phaseRoles.Count -gt 0 -and $phaseRoles -notcontains $Role) { throw "Role '$Role' is not authorized for phase '$PhaseId'" }
    $profileDigest = Get-ProfileDigest -ProfilePath $ProfilePath
    $baselineSha = Resolve-BaselineCommit -ProjectRoot $ProjectRoot
    $critical = ([string](Get-PolicyProp -Object $phase -Name 'riskLevel') -eq 'critical' -or $PhaseId -in @('deploy', 'rollback'))
    if ($critical -and [string]::IsNullOrWhiteSpace($baselineSha)) { throw 'Critical phase requires a valid Git baseline commit.' }
    if ([string]::IsNullOrWhiteSpace($baselineSha)) { $baselineSha = 'unversioned' }

    $approvalDigest = $null
    $gate = Get-BridgeApprovalGate -Profile $profile -PhaseId $PhaseId -ApprovedGates @()
    if ($null -ne $gate -and $gate.Blocked) {
        if (-not (Test-GateNameSafe -Gate ([string]$gate.Gate))) { throw 'Approval gate name failed containment validation.' }
        $record = Get-ApprovalRecord -TaskDirectory $TaskDirectory -Gate ([string]$gate.Gate)
        if ($null -eq $record) {
            return [pscustomobject]@{ Blocked = $true; State = 'APPROVAL_REQUIRED'; Message = [string]$gate.Reason; CheckResults = @(); SecretRefs = @(); ReportPath = $null }
        }
        $approvalErrors = Test-ApprovalRecordValid -Record $record -ExpectedGate ([string]$gate.Gate) -ExpectedTaskId $TaskId -ExpectedProfileDigest $profileDigest -ExpectedPhase $PhaseId -ExpectedBaselineSha $baselineSha
        if (@($approvalErrors).Count -gt 0) {
            return [pscustomobject]@{ Blocked = $true; State = 'APPROVAL_REQUIRED'; Message = ('Approval record invalid: ' + ($approvalErrors -join '; ')); CheckResults = @(); SecretRefs = @(); ReportPath = $null }
        }
        $approvalPath = Join-Path $TaskDirectory (Join-Path 'approvals' (([string]$gate.Gate) + '.json'))
        $approvalDigest = Get-FileSha256 -Path $approvalPath
    }

    $evidenceRoot = Get-AttemptEvidenceDir -TaskDirectory $TaskDirectory -Attempt $Attempt
    $normal = @((Select-BridgeGates -Profile $profile -PhaseId $PhaseId -Role $Role))
    $finalizers = @((Select-BridgeFinalizers -Profile $profile -PhaseId $PhaseId -Role $Role))
    $normalResult = $null
    $finalResult = $null
    try {
        $normalResult = Invoke-PolicyCheckSet -Checks $normal -Kind 'check' -Profile $profile -Phase $phase -PhaseId $PhaseId -ProjectRoot $ProjectRoot -TaskDirectory $TaskDirectory -EvidenceRoot $evidenceRoot
    } finally {
        $finalResult = Invoke-PolicyCheckSet -Checks $finalizers -Kind 'finally' -Profile $profile -Phase $phase -PhaseId $PhaseId -ProjectRoot $ProjectRoot -TaskDirectory $TaskDirectory -EvidenceRoot $evidenceRoot
    }
    $rows = @($normalResult.Rows) + @($finalResult.Rows)
    $blocking = @($normalResult.BlockingMessages) + @($finalResult.BlockingMessages)
    $secretRefs = @($normalResult.SecretRefs) + @($finalResult.SecretRefs) | Select-Object -Unique
    $reportPath = Join-Path $evidenceRoot 'policy-report.json'
    Write-PolicyReport -ReportPath $reportPath -TaskId $TaskId -Attempt $Attempt -ProfileDigest $profileDigest -Phase $PhaseId -Role $Role -BaselineSha $baselineSha -ApprovalRecordDigest $approvalDigest -Checks $rows
    if ($blocking.Count -gt 0) {
        return [pscustomobject]@{ Blocked = $true; State = 'POLICY_FAILED'; Message = ($blocking -join '; '); CheckResults = $rows; SecretRefs = [string[]]@($secretRefs); ReportPath = $reportPath }
    }
    return [pscustomobject]@{ Blocked = $false; State = 'POLICY_PASSED'; Message = 'Policy checks and finalizers passed.'; CheckResults = $rows; SecretRefs = [string[]]@($secretRefs); ReportPath = $reportPath }
}

Export-ModuleMember -Function @(
    'Get-PolicyRuntimeVersion',
    'Write-AtomicText', 'Write-AtomicJson', 'Read-JsonFile',
    'Test-PathDescendant', 'Test-GateNameSafe', 'Test-CommitSha',
    'Resolve-BaselineCommit', 'Get-AttemptEvidenceDir', 'Get-FileSha256',
    'Get-ProfileDigest', 'Get-ApprovalRecord', 'Test-ApprovalRecordValid',
    'Test-NoInlineSecrets', 'Test-SecretRefFailClosed', 'Test-LaunchPreconditions',
    'Invoke-BoundedProcessCollector',
    'Write-PolicyReport', 'Test-PolicyReportIntegrity',
    'Get-PreCheckDigests', 'Get-FreshEvidence', 'Copy-EvidenceFiles',
    'Invoke-BridgePolicyPhase'
) -Variable @()
