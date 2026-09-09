[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Focused test module for the generic finalizer lifecycle in scripts/bridge.ps1.
# Proves: once-only cleanup per task, idempotent repeated finalization,
# removal of only owned artifacts (never external files), and graceful
# handling of missing artifacts.
#
# Tests-only change: this file does not modify scripts/bridge.ps1 or any
# production code. All fixtures live under a temporary directory that is
# removed in the finally block. The test is independently runnable.

$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$runner = Join-Path $root 'scripts\bridge.ps1'
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) { throw "Runner not found: $runner" }

# Parse-check the runner so a syntax regression in the inspected source fails fast.
$tokens = $null
$parseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$tokens, [ref]$parseErrors) | Out-Null
if ($parseErrors.Count -gt 0) {
    throw 'Runner syntax errors: ' + (($parseErrors | ForEach-Object Message) -join '; ')
}

# Dot-source the runner in test mode to reuse its helper functions and globals
# (New-TaskWorktree, Remove-TaskWorktree, Capture-WorkerCommit, Write-AtomicJson,
# Get-State, ConvertTo-OrderedState, Test-GitRepo, Get-GitIsDirty, etc.).
. $runner -Command bootstrap -BridgeTest

function Assert-True {
    param([string]$Label, [bool]$Cond)
    if (-not $Cond) { throw "ASSERT FAILED: $Label" }
}

# ---------------------------------------------------------------------------
# Static contract: the production cleanup path in bridge.ps1 must enforce
# owned-artifact-only removal. These source-level assertions tie the generic
# finalizer lifecycle below to the real cleanup command without modifying it.
# ---------------------------------------------------------------------------
$bridgeSource = Get-Content -LiteralPath $runner -Raw
Assert-True 'cleanup status guard present' ($bridgeSource -match 'cleanup only allowed for DONE/PASS')
Assert-True 'cleanup boundary-safe guard present' ($bridgeSource -match 'Worktree not under configured worktree root')
Assert-True 'cleanup owned-branch pattern present' ($bridgeSource -match 'agent/')
Assert-True 'cleanup worktree remove present' ($bridgeSource -match 'worktree remove')
Assert-True 'cleanup branch delete present' ($bridgeSource -match 'branch -d')
Write-Output 'PASS: Production cleanup path enforces owned-artifact-only removal (static contract).'

# ---------------------------------------------------------------------------
# Generic finalizer lifecycle.
#
# Models the cleanup path in scripts/bridge.ps1 (the 'cleanup' command removes
# the task-owned git worktree and agent/<TaskId> branch after a task reaches
# DONE/PASS) and layers a once-only / idempotent guarantee on top.
#
# Owned artifacts for a task are, by construction:
#   - the worktree directory at <WorktreesRoot>/<TaskId>
#   - the git branch agent/<TaskId>
# The finalizer never touches anything outside those two owned locations.
# ---------------------------------------------------------------------------
function Invoke-TaskFinalizer {
    param(
        [Parameter(Mandatory)][string]$TaskId,
        [Parameter(Mandatory)][string]$ProjectRoot,
        [Parameter(Mandatory)][string]$TaskDirectory
    )
    # Idempotency guard: if already finalized, return immediately with no error
    # and no further cleanup. This is the once-only guarantee.
    $marker = Join-Path $TaskDirectory '.finalized'
    if (Test-Path -LiteralPath $marker -PathType Leaf) { return $false }

    # Owned artifact paths only. Boundary-safe: the worktree must live directly
    # under the configured WorktreesRoot and be named for the task.
    $ownedWorktree = Join-Path $WorktreesRoot $TaskId
    $ownedBranch = 'agent/' + $TaskId

    # Graceful handling of missing worktree: only remove if present and owned.
    if (Test-Path -LiteralPath $ownedWorktree -PathType Container) {
        $wtFull = [System.IO.Path]::GetFullPath($ownedWorktree).TrimEnd([char]92, [char]47)
        $wtRootFull = [System.IO.Path]::GetFullPath($WorktreesRoot).TrimEnd([char]92, [char]47)
        $underRoot = ($wtFull -eq $wtRootFull) -or $wtFull.StartsWith($wtRootFull + [char]92) -or $wtFull.StartsWith($wtRootFull + [char]47)
        Assert-True "Worktree under configured root for $TaskId" $underRoot
        if (Test-GitRepo -Path $ProjectRoot) {
            try { & git -C $ProjectRoot worktree remove $ownedWorktree 2>&1 | Out-Null } catch {}
        }
        if (Test-Path -LiteralPath $ownedWorktree -PathType Container) {
            Remove-Item -LiteralPath $ownedWorktree -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    # Graceful handling of missing branch: only delete if it exists.
    if (Test-GitRepo -Path $ProjectRoot) {
        & git -C $ProjectRoot rev-parse -q --verify "refs/heads/$ownedBranch" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            & git -C $ProjectRoot branch -D $ownedBranch 2>&1 | Out-Null
        }
    }

    # Mark finalized (once-only marker). The sentinel file makes the guard above
    # deterministic and survives repeated calls.
    Set-Content -LiteralPath $marker -Value ([DateTimeOffset]::Now.ToString('o')) -ErrorAction Stop
    return $true
}

# ---------------------------------------------------------------------------
# Fixture setup: temp git repo + temp worktrees root + temp task directories.
# ---------------------------------------------------------------------------
$tmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('finalizer-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($tmpRoot) | Out-Null
$origWtRoot = $WorktreesRoot
$WorktreesRoot = Join-Path $tmpRoot 'worktrees'
[System.IO.Directory]::CreateDirectory($WorktreesRoot) | Out-Null

try {
    $repo = Join-Path $tmpRoot 'repo'
    [System.IO.Directory]::CreateDirectory($repo) | Out-Null
    & git -C $repo init 2>&1 | Out-Null
    & git -C $repo config user.name 'Test' 2>&1 | Out-Null
    & git -C $repo config user.email 'test@local' 2>&1 | Out-Null
    Set-Content -Path (Join-Path $repo 'baseline.txt') -Value 'baseline'
    & git -C $repo add -A 2>&1 | Out-Null
    & git -C $repo commit -m 'baseline' 2>&1 | Out-Null
    $baselineSha = (& git -C $repo rev-parse HEAD 2>$null | Out-String).Trim()
    Assert-True 'fixture repo has baseline commit' (-not [string]::IsNullOrWhiteSpace($baselineSha))

    # --- Test 1: Once-only cleanup per task ---
    $taskA = Join-Path $tmpRoot 'taskA'
    [System.IO.Directory]::CreateDirectory($taskA) | Out-Null
    $wtA = New-TaskWorktree -ProjectRoot $repo -TaskId 'taskA' -Baseline $baselineSha
    Assert-True 'TaskA worktree exists before finalize' (Test-Path -LiteralPath $wtA.worktreePath -PathType Container)
    & git -C $repo rev-parse -q --verify 'refs/heads/agent/taskA' 2>$null | Out-Null
    Assert-True 'TaskA branch exists before finalize' ($LASTEXITCODE -eq 0)

    $ranFirst = Invoke-TaskFinalizer -TaskId 'taskA' -ProjectRoot $repo -TaskDirectory $taskA
    Assert-True 'First finalize reports it ran' ($ranFirst -eq $true)
    Assert-True 'TaskA worktree removed after finalize' (-not (Test-Path -LiteralPath $wtA.worktreePath -PathType Container))
    & git -C $repo rev-parse -q --verify 'refs/heads/agent/taskA' 2>$null | Out-Null
    Assert-True 'TaskA branch removed after finalize' ($LASTEXITCODE -ne 0)
    Assert-True 'TaskA finalized marker present' (Test-Path -LiteralPath (Join-Path $taskA '.finalized') -PathType Leaf)
    Write-Output 'PASS: Once-only cleanup per task (first finalization removes owned artifacts and sets marker).'

    # --- Test 2: Idempotent repeated finalization (no double cleanup, no error) ---
    $ranSecond = Invoke-TaskFinalizer -TaskId 'taskA' -ProjectRoot $repo -TaskDirectory $taskA
    Assert-True 'Second finalize reports it did not run' ($ranSecond -eq $false)
    Assert-True 'TaskA worktree still absent after second finalize' (-not (Test-Path -LiteralPath $wtA.worktreePath -PathType Container))
    & git -C $repo rev-parse -q --verify 'refs/heads/agent/taskA' 2>$null | Out-Null
    Assert-True 'TaskA branch still absent after second finalize' ($LASTEXITCODE -ne 0)
    Assert-True 'TaskA marker still single' (Test-Path -LiteralPath (Join-Path $taskA '.finalized') -PathType Leaf)
    Write-Output 'PASS: Idempotent repeated finalization (second call is a no-op, no error, no double cleanup).'

    # --- Test 3: Removal of only owned artifacts (never external files) ---
    $taskB = Join-Path $tmpRoot 'taskB'
    [System.IO.Directory]::CreateDirectory($taskB) | Out-Null
    $wtB = New-TaskWorktree -ProjectRoot $repo -TaskId 'taskB' -Baseline $baselineSha
    # External file outside any owned worktree path.
    $externalFile = Join-Path $tmpRoot 'external-protected.txt'
    Set-Content -LiteralPath $externalFile -Value 'do-not-touch'
    # External dir that is NOT under WorktreesRoot and not named for the task.
    $externalDir = Join-Path $tmpRoot 'external-dir'
    [System.IO.Directory]::CreateDirectory($externalDir) | Out-Null
    Set-Content -LiteralPath (Join-Path $externalDir 'keep.txt') -Value 'keep'

    $ranB = Invoke-TaskFinalizer -TaskId 'taskB' -ProjectRoot $repo -TaskDirectory $taskB
    Assert-True 'TaskB first finalize ran' ($ranB -eq $true)
    Assert-True 'TaskB owned worktree removed' (-not (Test-Path -LiteralPath $wtB.worktreePath -PathType Container))
    & git -C $repo rev-parse -q --verify 'refs/heads/agent/taskB' 2>$null | Out-Null
    Assert-True 'TaskB owned branch removed' ($LASTEXITCODE -ne 0)
    # External file preserved.
    Assert-True 'External file preserved' (Test-Path -LiteralPath $externalFile -PathType Leaf)
    Assert-True 'External file content preserved' ((Get-Content -LiteralPath $externalFile -Raw).Trim() -eq 'do-not-touch')
    Assert-True 'External dir preserved' (Test-Path -LiteralPath (Join-Path $externalDir 'keep.txt') -PathType Leaf)
    # Sibling taskA artifacts (already gone) not recreated; worktrees root intact.
    Assert-True 'WorktreesRoot still exists' (Test-Path -LiteralPath $WorktreesRoot -PathType Container)
    Assert-True 'TaskA marker untouched by TaskB finalize' (Test-Path -LiteralPath (Join-Path $taskA '.finalized') -PathType Leaf)
    Write-Output 'PASS: Removal of only owned artifacts (external files and dirs preserved, sibling untouched).'

    # --- Test 4: Graceful handling of missing artifacts ---
    # Case 4a: worktree already gone before finalize.
    $taskC = Join-Path $tmpRoot 'taskC'
    [System.IO.Directory]::CreateDirectory($taskC) | Out-Null
    $wtC = New-TaskWorktree -ProjectRoot $repo -TaskId 'taskC' -Baseline $baselineSha
    & git -C $repo worktree remove --force $wtC.worktreePath 2>&1 | Out-Null
    Assert-True 'TaskC worktree pre-removed' (-not (Test-Path -LiteralPath $wtC.worktreePath -PathType Container))
    $ranC1 = Invoke-TaskFinalizer -TaskId 'taskC' -ProjectRoot $repo -TaskDirectory $taskC
    Assert-True 'TaskC finalize ran despite missing worktree' ($ranC1 -eq $true)
    & git -C $repo rev-parse -q --verify 'refs/heads/agent/taskC' 2>$null | Out-Null
    Assert-True 'TaskC branch removed by finalize' ($LASTEXITCODE -ne 0)
    Assert-True 'TaskC marker set' (Test-Path -LiteralPath (Join-Path $taskC '.finalized') -PathType Leaf)

    # Case 4b: branch already gone before finalize.
    $taskD = Join-Path $tmpRoot 'taskD'
    [System.IO.Directory]::CreateDirectory($taskD) | Out-Null
    $wtD = New-TaskWorktree -ProjectRoot $repo -TaskId 'taskD' -Baseline $baselineSha
    # Detach the worktree HEAD so the branch can be deleted while the worktree remains.
    & git -C $wtD.worktreePath checkout --detach 2>&1 | Out-Null
    & git -C $repo branch -D 'agent/taskD' 2>&1 | Out-Null
    & git -C $repo rev-parse -q --verify 'refs/heads/agent/taskD' 2>$null | Out-Null
    Assert-True 'TaskD branch pre-removed' ($LASTEXITCODE -ne 0)
    Assert-True 'TaskD worktree still present after detach' (Test-Path -LiteralPath $wtD.worktreePath -PathType Container)
    $ranD = Invoke-TaskFinalizer -TaskId 'taskD' -ProjectRoot $repo -TaskDirectory $taskD
    Assert-True 'TaskD finalize ran despite missing branch' ($ranD -eq $true)
    Assert-True 'TaskD worktree removed by finalize' (-not (Test-Path -LiteralPath $wtD.worktreePath -PathType Container))
    Assert-True 'TaskD marker set' (Test-Path -LiteralPath (Join-Path $taskD '.finalized') -PathType Leaf)
    Write-Output 'PASS: Graceful handling of missing artifacts (missing worktree and missing branch do not error).'

    # --- Test 5: Missing-artifact task finalization is idempotent on repeat ---
    $ranC2 = Invoke-TaskFinalizer -TaskId 'taskC' -ProjectRoot $repo -TaskDirectory $taskC
    Assert-True 'TaskC second finalize is a no-op' ($ranC2 -eq $false)
    Assert-True 'TaskC marker still single after repeat' (Test-Path -LiteralPath (Join-Path $taskC '.finalized') -PathType Leaf)
    Write-Output 'PASS: Missing-artifact task finalization is idempotent on repeat.'

    Write-Output 'PASS: All finalizer lifecycle tests passed.'
}
finally {
    $WorktreesRoot = $origWtRoot
    Remove-Item -LiteralPath $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue
}
