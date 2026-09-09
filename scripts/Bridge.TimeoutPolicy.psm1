# Bridge.TimeoutPolicy.psm1
# Enforces bounded Worker tasks and creates durable timeout handoff artifacts.

Set-StrictMode -Version Latest

function Get-TaskBudget {
    [CmdletBinding()]
    param(
        [ValidateSet('implementation', 'verification', 'stress-test', 'live-integration')]
        [string]$TaskKind = 'implementation',
        [int]$TargetMinutes = 0,
        [int]$SoftTimeoutMinutes = 0,
        [int]$HardTimeoutMinutes = 0,
        [int]$MaxAttempts = 0
    )
    $defaults = switch ($TaskKind) {
        'implementation' { @{ target = 10; soft = 10; hard = 15; max = 1 } }
        'verification' { @{ target = 15; soft = 20; hard = 30; max = 1 } }
        'stress-test' { @{ target = 30; soft = 45; hard = 60; max = 1 } }
        'live-integration' { @{ target = 15; soft = 20; hard = 30; max = 1 } }
    }
    $target = if ($TargetMinutes -gt 0) { $TargetMinutes } else { $defaults.target }
    $soft = if ($SoftTimeoutMinutes -gt 0) { $SoftTimeoutMinutes } else { $defaults.soft }
    $hard = if ($HardTimeoutMinutes -gt 0) { $HardTimeoutMinutes } else { $defaults.hard }
    $attempts = if ($MaxAttempts -gt 0) { $MaxAttempts } else { $defaults.max }
    $maximumHard = $defaults.hard
    $issues = [System.Collections.Generic.List[string]]::new()
    if ($target -lt 1) { $null = $issues.Add('targetMinutes must be positive.') }
    if ($soft -lt 1) { $null = $issues.Add('softTimeoutMinutes must be positive.') }
    if ($hard -lt 1) { $null = $issues.Add('hardTimeoutMinutes must be positive.') }
    if ($target -gt $soft) { $null = $issues.Add('targetMinutes must not exceed softTimeoutMinutes.') }
    if ($soft -ge $hard) { $null = $issues.Add('softTimeoutMinutes must be less than hardTimeoutMinutes.') }
    if ($hard -gt $maximumHard) { $null = $issues.Add("hardTimeoutMinutes exceeds the $TaskKind limit of $maximumHard minutes.") }
    if ($attempts -ne 1) { $null = $issues.Add('maxAttempts must be 1; timed-out implementation work must continue as a new task.') }
    return [pscustomobject]@{
        Valid = ($issues.Count -eq 0)
        Issues = [string[]]@($issues.ToArray())
        PolicyVersion = 1
        TaskKind = $TaskKind
        TargetMinutes = $target
        SoftTimeoutMinutes = $soft
        HardTimeoutMinutes = $hard
        MaxAttempts = $attempts
    }
}

function Test-TaskEnvelope {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$TaskText,
        [Parameter(Mandatory)]$Budget
    )
    $issues = [System.Collections.Generic.List[string]]::new()
    if (-not $Budget.Valid) { foreach ($issue in @($Budget.Issues)) { $null = $issues.Add([string]$issue) } }
    if ([string]::IsNullOrWhiteSpace($TaskText)) { $null = $issues.Add('Task text is empty.') }
    if ($TaskText.Length -gt 12000) { $null = $issues.Add('Task text exceeds 12000 characters; split context from implementation.') }
    foreach ($heading in @('Objective', 'Required Changes', 'Acceptance Criteria', 'Deliverables')) {
        if ($TaskText -notmatch ('(?im)^#{1,6}\s+' + [regex]::Escape($heading) + '\s*$')) {
            $null = $issues.Add("Missing required heading: $heading.")
        }
    }
    $requiredSection = ''
    $match = [regex]::Match($TaskText, '(?ims)^#{1,6}\s+Required Changes\s*$\s*(.*?)(?=^#{1,6}\s+|\z)')
    if ($match.Success) { $requiredSection = $match.Groups[1].Value }
    $changeItems = @([regex]::Matches($requiredSection, '(?m)^\s*(?:[-*]|\d+\.)\s+') | ForEach-Object { $_.Value })
    if ($Budget.TaskKind -eq 'implementation' -and $changeItems.Count -gt 5) {
        $null = $issues.Add('Implementation task has more than five required changes; split it.')
    }
    $boundaryPatterns = [ordered]@{
        scheduler = '(?i)\b(scheduler|dispatcher|lease|concurrency)\b'
        policy = '(?i)\b(policy|approval|gate|finalizer)\b'
        daemon = '(?i)\b(daemon|service|supervisor|heartbeat)\b'
        remote = '(?i)\b(remote|ssh|bootstrap|bundle|worktree)\b'
        release = '(?i)\b(deploy|rollback|release|cloudsite profile)\b'
    }
    $boundaries = @($boundaryPatterns.Keys | Where-Object { $requiredSection -match $boundaryPatterns[$_] })
    if ($Budget.TaskKind -eq 'implementation' -and $boundaries.Count -gt 1) {
        $null = $issues.Add('Implementation task crosses multiple failure domains: ' + ($boundaries -join ', ') + '.')
    }
    return [pscustomobject]@{
        Valid = ($issues.Count -eq 0)
        Issues = [string[]]@($issues.ToArray())
        FailureDomains = [string[]]@($boundaries)
        RequiredChangeCount = $changeItems.Count
    }
}

function Write-Utf8NoBom {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][AllowEmptyString()][string]$Text)
    $parent = Split-Path -Parent $Path
    if ($parent) { [System.IO.Directory]::CreateDirectory($parent) | Out-Null }
    [System.IO.File]::WriteAllText($Path, $Text, [System.Text.UTF8Encoding]::new($false))
}

function New-TimeoutHandoff {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$TaskDirectory,
        [Parameter(Mandatory)][string]$TaskId,
        [Parameter(Mandatory)][int]$Attempt,
        [Parameter(Mandatory)][string]$Reason,
        [Parameter(Mandatory)][int]$ElapsedSeconds,
        [Parameter(Mandatory)][int]$HardTimeoutSeconds,
        [string]$WorktreePath,
        [string]$ProjectRoot,
        [switch]$QueueTimeout
    )
    $outbox = Join-Path $TaskDirectory 'outbox'
    [System.IO.Directory]::CreateDirectory($outbox) | Out-Null
    $checkpointPath = Join-Path $outbox 'CHECKPOINT.md'
    $assistancePath = Join-Path $outbox 'ASSISTANCE_REQUEST.md'
    $changedFileCount = $null
    if (-not [string]::IsNullOrWhiteSpace($WorktreePath) -and (Test-Path -LiteralPath $WorktreePath -PathType Container)) {
        try { $changedFileCount = @(& git -C $WorktreePath status --short 2>$null).Count } catch { $changedFileCount = $null }
    }
    if (-not (Test-Path -LiteralPath $checkpointPath -PathType Leaf)) {
        $changeText = if ($null -eq $changedFileCount) { 'Unknown; inspect the preserved workspace.' } else { "$changedFileCount changed path(s); inspect the preserved workspace." }
        $checkpoint = "# CHECKPOINT`n`nReason: $Reason`nAttempt: $Attempt`nElapsed seconds: $ElapsedSeconds`nWorkspace changes: $changeText`nSafe checkpoint: The Bridge terminated only the Worker process and preserved task files, logs, and workspace state.`n"
        Write-Utf8NoBom -Path $checkpointPath -Text $checkpoint
    }
    if (-not (Test-Path -LiteralPath $assistancePath -PathType Leaf)) {
        $nextId = $TaskId + '-part-' + ($Attempt + 1)
        $request = "# ASSISTANCE REQUEST`n`nReason: $Reason`nCompleted: See CHECKPOINT.md and preserved workspace.`nRemaining: Review the preserved diff and extract one smallest unfinished unit.`nCurrent Tests: Unknown; do not infer pass status from timeout.`nSafe Checkpoint: $checkpointPath`nSuggested Next Task: $nextId in a new Worker session. Do not resume this timed-out prompt.`n"
        Write-Utf8NoBom -Path $assistancePath -Text $request
    }
    $disposition = if ($QueueTimeout) { 'RETRYABLE' } else { 'SPLIT_REQUIRED' }
    $record = [ordered]@{
        schemaVersion = 1
        taskId = $TaskId
        attempt = $Attempt
        disposition = $disposition
        reason = $Reason
        elapsedSeconds = $ElapsedSeconds
        hardTimeoutSeconds = $HardTimeoutSeconds
        originalTaskMustNotResume = (-not $QueueTimeout)
        preservedWorktree = $WorktreePath
        projectRoot = $ProjectRoot
        createdAt = [DateTimeOffset]::Now.ToString('o')
    }
    Write-Utf8NoBom -Path (Join-Path $outbox 'TIMEOUT.json') -Text (($record | ConvertTo-Json -Depth 5) + "`n")
    $plan = [ordered]@{
        schemaVersion = 1
        parentTaskId = $TaskId
        sourceAttempt = $Attempt
        newSessionRequired = (-not $QueueTimeout)
        reusePreservedWorkspace = $true
        nextAction = if ($QueueTimeout) { 'Retry after queue health recovers.' } else { 'Architect reviews the checkpoint and creates one minimal successor task.' }
        prohibited = @('resume timed-out implementation prompt', 'increase timeout to avoid decomposition', 'discard preserved workspace')
    }
    Write-Utf8NoBom -Path (Join-Path $outbox 'CONTINUATION_PLAN.json') -Text (($plan | ConvertTo-Json -Depth 5) + "`n")
    return [pscustomobject]@{ Disposition = $disposition; CheckpointPath = $checkpointPath; AssistancePath = $assistancePath }
}

Export-ModuleMember -Function @('Get-TaskBudget', 'Test-TaskEnvelope', 'New-TimeoutHandoff')
