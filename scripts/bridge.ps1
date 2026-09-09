[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)]
    [ValidateSet('bootstrap', 'doctor', 'register', 'worker-register', 'worker-list', 'worker-health', 'create', 'create-multi', 'run', 'status', 'pause', 'resume', 'cancel', 'review-pass', 'review-fix', 'dispatch', 'capture', 'integration-check', 'cleanup')]
    [string]$Command,

    [string]$ProjectId,
    [string]$ProjectRoot,
    [ValidateSet('local', 'ssh', 'ssh-shell', 'remote-worktree')]
    [string]$Transport = 'local',
    [string]$RunMode,
    [string]$SshHost,
    [string]$RemoteBridgeRoot = '~/.codex-glm',
    [string]$RemoteWorkspaceRoot,
    [string]$Model,
    [string]$TaskFile,
    [string]$TaskId,
    [string]$Baseline,
    [int]$TimeoutMinutes = 0,
    [int]$SoftTimeoutMinutes = 0,
    [int]$TargetMinutes = 0,
    [int]$MaxAttempts = 0,
    [ValidateSet('implementation', 'verification', 'stress-test', 'live-integration')]
    [string]$TaskKind = 'implementation',
    [string]$ParentTaskId,
    [string]$TargetRef,
    [int]$MaxWorkers = 4,
    [switch]$DryRun,
    [switch]$BridgeTest,
    [switch]$Quiet,
    [string]$WorkerId,
    [ValidateSet('implement', 'review', 'test')]
    [string]$Role,
    [string[]]$DependsOn,
    [ValidateSet('shared-readonly', 'worktree', 'existing')]
    [string]$WorkspaceMode,
    [string]$CliPath,
    [string]$WorkerHost,
    [int]$ConcurrencyLimit = 1,
    [switch]$Disabled,
    [string[]]$Capabilities,
    [string]$SpecFile,
    [string]$RemoteCliPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$BridgeRoot = Split-Path -Parent $PSScriptRoot
$RegistryPath = Join-Path $BridgeRoot 'projects.json'
$WorkersRegistryPath = Join-Path $BridgeRoot 'workers.json'
$TasksRoot = Join-Path $BridgeRoot 'tasks'
$RuntimeRoot = Join-Path $BridgeRoot 'runtime'
$LocksRoot = Join-Path $RuntimeRoot 'locks'
$LeasesRoot = Join-Path $RuntimeRoot 'leases'
$WorktreesRoot = Join-Path $RuntimeRoot 'worktrees'
$LogsRoot = Join-Path $RuntimeRoot 'logs'
$DispatcherLogRoot = Join-Path $LogsRoot 'dispatcher'
$ProtocolRoot = Join-Path $BridgeRoot 'protocol'
$PausePath = Join-Path $RuntimeRoot 'PAUSE'
$TimeoutPolicyModulePath = Join-Path $PSScriptRoot 'Bridge.TimeoutPolicy.psm1'
if (-not (Test-Path -LiteralPath $TimeoutPolicyModulePath -PathType Leaf)) { throw "Timeout policy module not found: $TimeoutPolicyModulePath" }
Import-Module $TimeoutPolicyModulePath -Force

$script:ThinkLanguageDirective = 'Use English for all reasoning, analysis, tool summaries, console-visible event text, and final output. Do not emit Chinese text in Worker-generated content because non-ASCII console output may be corrupted.'
$script:RequiredModel = 'huaweicloud-maas/GLM-5.2'

function Ensure-BridgeLayout {
    foreach ($path in @($TasksRoot, $RuntimeRoot, $LocksRoot, $LeasesRoot, $WorktreesRoot, $LogsRoot, $DispatcherLogRoot, (Join-Path $BridgeRoot 'archive'), (Join-Path $BridgeRoot 'work'))) {
        [System.IO.Directory]::CreateDirectory($path) | Out-Null
    }
}

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
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Assert-SafeId {
    param([Parameter(Mandatory)][string]$Value, [string]$Label = 'ID')
    if ($Value -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
        throw "$Label allows only letters, digits, dot, underscore, hyphen: $Value"
    }
}

function Assert-SafeSessionId {
    param([Parameter(Mandatory)][string]$Value)
    if ($Value -notmatch '^[A-Za-z0-9_-]+$') {
        throw "sessionId allows only letters, digits, underscore, hyphen: $Value"
    }
}
function Get-Registry {
    return Read-JsonFile -Path $RegistryPath
}

function Get-Project {
    param([Parameter(Mandatory)][string]$Id)
    $registry = Get-Registry
    $matches = @($registry.projects | Where-Object { $_.id -eq $Id })
    if ($matches.Count -ne 1) {
        throw "Project not registered or duplicate: $Id"
    }
    return $matches[0]
}

function Get-TaskDirectory {
    param([Parameter(Mandatory)][string]$Id)
    Assert-SafeId -Value $Id -Label 'TaskId'
    return Join-Path $TasksRoot $Id
}

function Get-State {
    param([Parameter(Mandatory)][string]$Directory)
    return Read-JsonFile -Path (Join-Path $Directory 'state.json')
}

function ConvertTo-OrderedState {
    param($Object)
    if ($null -eq $Object) { return [ordered]@{} }
    $result = [ordered]@{}
    if ($Object -is [System.Collections.IDictionary]) {
        foreach ($key in @($Object.Keys)) { $result[$key] = $Object[$key] }
    } else {
        foreach ($prop in @($Object.PSObject.Properties)) { $result[$prop.Name] = $prop.Value }
    }
    return $result
}

function Test-MapKey {
    param($Map, [string]$Key)
    if ($null -eq $Map) { return $false }
    if ($Map -is [System.Collections.IDictionary]) { return $Map.Contains($Key) }
    return @($Map.PSObject.Properties.Name) -contains $Key
}

function Get-MapValue {
    param($Map, [string]$Key)
    if ($null -eq $Map) { return $null }
    if ($Map -is [System.Collections.IDictionary]) { if ($Map.Contains($Key)) { return $Map[$Key] }; return $null }
    if (@($Map.PSObject.Properties.Name) -contains $Key) { return $Map.$Key }
    return $null
}

function Set-State {
    param(
        [Parameter(Mandatory)][string]$Directory,
        [Parameter(Mandatory)][string]$Status,
        [string]$Message,
        [Nullable[int]]$ExitCode,
        [Nullable[int]]$ProcessId,
        [string]$SessionId,
        [string]$SessionMode,
        [string]$LastEventAt,
        [string]$LastHeartbeat = '',
        $Tokens
    )

    $path = Join-Path $Directory 'state.json'
    $old = if (Test-Path -LiteralPath $path) { Read-JsonFile -Path $path } else { $null }
    $state = [ordered]@{}
    if ($old) {
        foreach ($name in @($old.PSObject.Properties.Name)) {
            $state[$name] = $old.$name
        }
    }
    $state.schemaVersion = 1
    $state.taskId = if ($old -and $old.PSObject.Properties.Name -contains 'taskId') { $old.taskId } else { Split-Path -Leaf $Directory }
    $state.status = $Status
    if ($old -and $old.PSObject.Properties.Name -contains 'attempt') {
        $state.attempt = [int]$old.attempt
    } elseif (-not $state.Contains('attempt')) {
        $state.attempt = 0
    }
    $state.updatedAt = [DateTimeOffset]::Now.ToString('o')
    $state.message = $Message
    $state.processId = $ProcessId
    $state.exitCode = $ExitCode
    if ($SessionId) { Assert-SafeSessionId -Value $SessionId; $state.sessionId = $SessionId }
    if ($SessionMode) { $state.sessionMode = $SessionMode }
    if ($LastEventAt) { $state.lastEventAt = $LastEventAt }
    if ($LastHeartbeat) { $state.lastHeartbeat = $LastHeartbeat }
    if ($null -ne $Tokens) { $state.tokens = $Tokens }
    Write-AtomicJson -Path $path -Value $state
    return [pscustomobject]$state
}
function Find-CodeArtsCli {
    $cmd = Get-Command codearts -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Path -and (Test-Path -LiteralPath $cmd.Path -PathType Leaf)) {
        return $cmd.Path
    }
    $candidates = @(
        (Join-Path $env:HOME '.codeartsdoer/installers/bin/codearts'),
        '/usr/local/bin/codearts'
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    return $null
}


function Import-CodeArtsUserEnvironment {
    foreach ($name in @('CODEARTS_CLI_AK', 'CODEARTS_CLI_SK')) {
        if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, 'Process'))) {
            $storedValue = [Environment]::GetEnvironmentVariable($name, 'User')
            if (-not [string]::IsNullOrWhiteSpace($storedValue)) {
                [Environment]::SetEnvironmentVariable($name, $storedValue, 'Process')
            }
        }
    }
}

function New-ProcessStartInfo {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [string]$WorkingDirectory,
        [switch]$NoWindow
    )

    $info = [System.Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $FilePath
    if ($WorkingDirectory) { $info.WorkingDirectory = $WorkingDirectory }
    $info.UseShellExecute = $false
    $info.CreateNoWindow = [bool]$NoWindow
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($argument in $Arguments) { $info.ArgumentList.Add($argument) }
    return $info
}
function New-WorkerRunArguments {
    param(
        [Parameter(Mandatory)][string]$Prompt,
        [string]$Model,
        [string]$ModeFlag,
        [string]$TaskId,
        [string]$SessionId
    )

    if ($SessionId) {
        Assert-SafeSessionId -Value $SessionId
    }
    $argList = @('run', $Prompt, '--format', 'json', '--thinking')
    if ($SessionId) {
        $argList += @('--session', $SessionId)
    } else {
        if ([string]::IsNullOrWhiteSpace($TaskId)) { throw 'TaskId must not be empty' }
        $argList += @('--title', $TaskId)
    }
    if (-not [string]::IsNullOrWhiteSpace($Model)) {
        $argList += @('-m', $Model)
    }
    if (-not [string]::IsNullOrWhiteSpace($ModeFlag)) {
        $argList += $ModeFlag
    }
    return [string[]]$argList
}

function Parse-CodeArtsJsonLines {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Output)

    $sessionId = $null
    $lastEventAt = $null
    $tokens = $null
    foreach ($line in $Output -split "`r?`n") {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $event = $null
        try {
            $event = $line | ConvertFrom-Json -ErrorAction Stop
        } catch { continue }
        if (-not $event) { continue }

        $sid = $null
        $names = @($event.PSObject.Properties.Name)
        if ($names -contains 'sessionID') { $sid = $event.sessionID }
        elseif ($names -contains 'sessionId') { $sid = $event.sessionId }
        elseif ($names -contains 'session') {
            $s = $event.session
            if ($s -and @($s.PSObject.Properties.Name) -contains 'id') { $sid = $s.id }
        }
        if ($sid -and -not $sessionId) { $sessionId = [string]$sid }

        $ts = $null
        if ($names -contains 'timestamp') { $ts = $event.timestamp }
        elseif ($names -contains 'time') { $ts = $event.time }
        elseif ($names -contains 'ts') { $ts = $event.ts }
        elseif ($names -contains 'datetime') { $ts = $event.datetime }
        if ($ts) {
            if ($ts -is [DateTime]) { $lastEventAt = $ts.ToString('o') }
            elseif ($ts -is [long] -or $ts -is [int] -or $ts -is [double]) { try { $lastEventAt = [DateTimeOffset]::FromUnixTimeMilliseconds([long]$ts).ToString('o') } catch { $lastEventAt = [string]$ts } }
            elseif ($ts -is [string] -and $ts -match '^\d+$') { try { $lastEventAt = [DateTimeOffset]::FromUnixTimeMilliseconds([long]$ts).ToString('o') } catch { $lastEventAt = [string]$ts } }
            else { $lastEventAt = [string]$ts }
        }

        $t = $null
        if ($names -contains 'step_finish') {
            $sf = $event.step_finish
            if ($sf -and @($sf.PSObject.Properties.Name) -contains 'part') {
                $part = $sf.part
                if ($part -and @($part.PSObject.Properties.Name) -contains 'tokens') {
                    $t = $part.tokens
                }
            }
        }
        if (-not $t -and $names -contains 'type' -and $event.type -eq 'step_finish' -and $names -contains 'part') {
            $part2 = $event.part
            if ($part2 -and @($part2.PSObject.Properties.Name) -contains 'tokens') {
                $t = $part2.tokens
            }
        }
        if ($t) { $tokens = $t }
    }
    return [pscustomobject]@{ sessionId = $sessionId; lastEventAt = $lastEventAt; tokens = $tokens }
}

function Get-DispatchCandidates {
    param(
        [Parameter(Mandatory)][string]$TasksRoot,
        [int]$MaxWorkers = 4
    )

    $candidateStatuses = @('READY', 'FIX_REQUIRED', 'RETRYABLE')
    $activeStatuses = @('QUEUED', 'STARTING', 'RUNNING')
    $tasks = @()
    foreach ($directory in @(Get-ChildItem -LiteralPath $TasksRoot -Directory -ErrorAction SilentlyContinue | Sort-Object Name)) {
        $statePath = Join-Path $directory.FullName 'state.json'
        $metaPath = Join-Path $directory.FullName 'META.json'
        if (-not (Test-Path -LiteralPath $statePath) -or -not (Test-Path -LiteralPath $metaPath)) { continue }
        $state = Read-JsonFile -Path $statePath
        $meta = Read-JsonFile -Path $metaPath
        $tasks += [pscustomobject]@{
            taskId    = [string]$state.taskId
            directory = $directory.FullName
            status    = [string]$state.status
            projectId = [string]$meta.projectId
        }
    }
    $active = @($tasks | Where-Object { $_.status -in $activeStatuses })
    $activeProjectIds = @($active | ForEach-Object { $_.projectId } | Sort-Object -Unique)
    $availableSlots = $MaxWorkers - $active.Count
    $selected = @()
    if ($availableSlots -le 0) { return $selected }
    $candidates = @($tasks | Where-Object { $_.status -in $candidateStatuses } | Sort-Object taskId)
    foreach ($candidate in $candidates) {
        if ($selected.Count -ge $availableSlots) { break }
        if ($activeProjectIds.Count -gt 0 -and $candidate.projectId -in $activeProjectIds) { continue }
        $selectedProjectIds = @($selected | ForEach-Object { $_.projectId })
        if ($selectedProjectIds.Count -gt 0 -and $candidate.projectId -in $selectedProjectIds) { continue }
        $selected += $candidate
    }
    return $selected
}
function Get-ModeFlag {
    param([Parameter(Mandatory)][string]$Mode)
    switch ($Mode) {
        'auto' { return '--auto' }
        'sandbox' { return '--sandbox' }
        'manual' { return $null }
        default { throw "Unsupported run mode: $Mode" }
    }
}

function Get-LatestInstruction {
    param([Parameter(Mandatory)][string]$TaskDirectory)
    $files = @(Get-ChildItem -LiteralPath (Join-Path $TaskDirectory 'inbox') -File -Filter '*.md' | Sort-Object Name)
    if ($files.Count -eq 0) { throw 'No instruction files in task inbox' }
    return $files[-1]
}

function Get-InstructionContext {
    param([Parameter(Mandatory)][string]$TaskDirectory)
    $files = @(Get-ChildItem -LiteralPath (Join-Path $TaskDirectory 'inbox') -File -Filter '*.md' | Sort-Object Name)
    if ($files.Count -eq 0) { throw 'No instruction files in task inbox' }
    return @($files | ForEach-Object { $_.FullName })
}

function Build-InstructionListSegment {
    param([Parameter(Mandatory)][string[]]$Paths)
    return ($Paths | ForEach-Object { "'$_'" }) -join ', '
}

function Archive-PreviousOutbox {
    param([Parameter(Mandatory)][string]$TaskDirectory, [Parameter(Mandatory)][int]$Attempt)
    $outbox = Join-Path $TaskDirectory 'outbox'
    $files = @(Get-ChildItem -LiteralPath $outbox -File -ErrorAction SilentlyContinue)
    if ($files.Count -eq 0) { return }
    $archive = Join-Path $TaskDirectory ("evidence\attempt-{0:D3}" -f ($Attempt - 1))
    [System.IO.Directory]::CreateDirectory($archive) | Out-Null
    foreach ($file in $files) { Move-Item -LiteralPath $file.FullName -Destination $archive -Force }
}

function Quote-Posix {
    param([Parameter(Mandatory)][string]$Value)
    if ($Value.Contains("`n") -or $Value.Contains("`r") -or $Value.Contains([char]0)) {
        throw 'SSH args contain disallowed control characters'
    }
    $replacement = "'" + '"' + "'" + '"' + "'"
    return "'" + $Value.Replace("'", $replacement) + "'"
}
function Invoke-SensitiveMask {
    param([string]$Text)
    $Text = $Text -replace 'CODEARTS_CLI_AK=\S+', 'CODEARTS_CLI_AK=***'
    $Text = $Text -replace 'CODEARTS_CLI_SK=\S+', 'CODEARTS_CLI_SK=***'
    $Text = $Text -replace '(?i)Bearer\s+\S+', 'Bearer ***'

    $Text = $Text -replace '(?i)(password|token|secret|api_key)=\S+', '$1=***'
    return $Text
}
function Assert-RequiredModel {
    param([string]$Model)
    if (-not [string]::IsNullOrWhiteSpace($Model) -and $Model -ne $script:RequiredModel) {
        throw "Model rejected: only  $($script:RequiredModel), got: $Model"
    }
}

function Get-WorkersRegistry {
    if (-not (Test-Path -LiteralPath $WorkersRegistryPath -PathType Leaf)) { return $null }
    return Read-JsonFile -Path $WorkersRegistryPath
}

function Get-Worker {
    param([Parameter(Mandatory)][string]$Id)
    $reg = Get-WorkersRegistry
    if (-not $reg) { throw "Worker registry missing or worker not registered: $Id" }
    $matches = @($reg.workers | Where-Object { $_.id -eq $Id })
    if ($matches.Count -ne 1) { throw "Worker not registered or duplicate: $Id" }
    return $matches[0]
}

function Get-LeasePath { param([Parameter(Mandatory)][string]$TaskId) return Join-Path $LeasesRoot ($TaskId + '.json') }
function Read-Lease { param([string]$TaskId) $p = Get-LeasePath -TaskId $TaskId; if (Test-Path -LiteralPath $p -PathType Leaf) { return Read-JsonFile -Path $p } else { return $null } }
function Write-Lease { param([Parameter(Mandatory)]$Lease) Write-AtomicJson -Path (Get-LeasePath -TaskId ([string]$Lease.taskId)) -Value $Lease }
function Remove-Lease { param([string]$TaskId) $p = Get-LeasePath -TaskId $TaskId; if (Test-Path -LiteralPath $p -PathType Leaf) { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue } }
function Test-ProcessAlive {
    param([Nullable[int]]$ProcessId, [string]$ProcessStartTime = '')
    if (-not $ProcessId -or $ProcessId -le 0) { return $false }
    try {
        $p = Get-Process -Id ([int]$ProcessId) -ErrorAction SilentlyContinue
        if ($null -eq $p) { return $false }
        if (-not [string]::IsNullOrWhiteSpace($ProcessStartTime)) {
            $recordedStart = [DateTimeOffset]::MinValue
            if ([DateTimeOffset]::TryParse($ProcessStartTime, [ref]$recordedStart)) {
                $actualStart = [DateTimeOffset]::new($p.StartTime)
                $diff = [Math]::Abs(($actualStart - $recordedStart).TotalSeconds)
                if ($diff -gt 1) { return $false }
            }
        }
        return $true
    } catch { return $false }
}

function Test-GitRepo {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Container)) { return $false }
    try { $r = & git -C $Path rev-parse --is-inside-work-tree 2>$null; return ($LASTEXITCODE -eq 0 -and [string]$r -match 'true') } catch { return $false }
}
function Test-GitHasCommit {
    param([string]$Path)
    try { & git -C $Path rev-parse -q --verify HEAD 2>$null | Out-Null; return ($LASTEXITCODE -eq 0) } catch { return $false }
}
function Get-GitIsDirty {
    param([string]$Path)
    try { $o = & git -C $Path status --porcelain 2>$null; return (-not [string]::IsNullOrWhiteSpace([string]$o)) } catch { return $true }
}
function New-TaskWorktree {
    param([Parameter(Mandatory)][string]$ProjectRoot, [Parameter(Mandatory)][string]$TaskId, [string]$Baseline)
    Assert-SafeId -Value $TaskId -Label 'TaskId'
    if (-not (Test-GitRepo -Path $ProjectRoot)) { throw "Not a git repo, cannot create worktree: $ProjectRoot" }
    if (-not (Test-GitHasCommit -Path $ProjectRoot)) { throw "Git repo has no valid commit, cannot create worktree: $ProjectRoot" }
    $dirty = Get-GitIsDirty -Path $ProjectRoot
    $ref = if (-not [string]::IsNullOrWhiteSpace($Baseline)) { $Baseline } else { 'HEAD' }
    if ($dirty -and [string]::IsNullOrWhiteSpace($Baseline)) { throw "Dirty baseline without explicit baseline, refusing worktree: $ProjectRoot" }
    $resolvedSha = (& git -C $ProjectRoot rev-parse -q --verify ($ref + '^{commit}') 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($resolvedSha)) { throw "Cannot resolve baseline to a commit object: $ref" }
    $ref = $resolvedSha
    $worktreePath = Join-Path $WorktreesRoot $TaskId
    if (Test-Path -LiteralPath $worktreePath) { throw "Worktree already exists: $worktreePath" }
    $branchName = "agent/$TaskId"
    & git -C $ProjectRoot rev-parse -q --verify "refs/heads/$branchName" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { throw "Branch $branchName already exists, rejecting to avoid reusing unrelated branch" }
    & git -C $ProjectRoot worktree add -b $branchName $worktreePath $ref 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $worktreePath -PathType Container)) { throw "git worktree add failed: $ProjectRoot -> $worktreePath" }
    return [pscustomobject]@{ worktreePath = $worktreePath; baselineSha = $resolvedSha; branchName = $branchName }
}
function Remove-TaskWorktree {
    param([string]$ProjectRoot, [string]$WorktreePath)
    if ([string]::IsNullOrWhiteSpace($WorktreePath) -or -not (Test-Path -LiteralPath $WorktreePath -PathType Container)) { return }
    if (-not [string]::IsNullOrWhiteSpace($ProjectRoot) -and (Test-GitRepo -Path $ProjectRoot)) {
        try { & git -C $ProjectRoot worktree remove --force $WorktreePath 2>&1 | Out-Null } catch {}
    }
    if (Test-Path -LiteralPath $WorktreePath -PathType Container) {
        try { Remove-Item -LiteralPath $WorktreePath -Recurse -Force -ErrorAction SilentlyContinue } catch {}
    }
}

function Capture-WorkerCommit {
    param(
        [Parameter(Mandatory)][string]$WorktreePath,
        [Parameter(Mandatory)][string]$TaskId,
        [string]$WorkerId,
        [string]$Baseline
    )
    if (-not (Test-GitRepo -Path $WorktreePath)) { return $null }
    if (-not [string]::IsNullOrWhiteSpace($Baseline)) {
        $resolvedBase = (& git -C $WorktreePath rev-parse $Baseline 2>$null | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($resolvedBase)) { throw "Cannot resolve baseline SHA: $Baseline" }
    }
    & git -C $WorktreePath config --local user.name 'Bridge Bot' 2>&1 | Out-Null
    & git -C $WorktreePath config --local user.email 'bridge@local' 2>&1 | Out-Null
    if (-not (Get-GitIsDirty -Path $WorktreePath)) {
        return (& git -C $WorktreePath rev-parse HEAD 2>$null | Out-String).Trim()
    }
    $sensitivePatterns = @('.env', '.env.*', '*.env', '*credentials*', 'credentials', '*.key', '*.pem', '*.pfx', '*.p12', 'id_rsa', 'id_ed25519', '.npmrc', '.pypirc', '.dockercfg', '*auth*', '*token*', '*secret*', '*apikey*', '*api_key*', '*privatekey*', '*private-key*', '*certificate*', '*.crt', '*.cer')
    $porcelain = @(& git -C $WorktreePath status --porcelain 2>$null)
    $stagedFiles = @()
    foreach ($line in $porcelain) {
        if ($line.Length -lt 4) { continue }
        $entry = $line.Substring(3).Trim()
        if ($entry -match ' -> ') { $parts = $entry -split ' -> ', 2; $entry = $parts[1].Trim() }
        $entry = $entry.Trim([char]34)
        if ($entry) { $stagedFiles += $entry }
    }
    foreach ($f in $stagedFiles) {
        $fileName = Split-Path -Leaf $f
        foreach ($pat in $sensitivePatterns) {
            if ($fileName -like $pat) { throw "Refusing to commit sensitive file: $f (matches $pat)" }
        }
        if ($f -match '(^|/)(tasks|runtime|logs|evidence)(/|$)') { throw "Refusing to commit task/runtime file: $f" }

        $fullPath = Join-Path $WorktreePath $f
        if (Test-Path -LiteralPath $fullPath) {
            $resolved = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $fullPath -ErrorAction SilentlyContinue).Path)
            $wtResolved = [System.IO.Path]::GetFullPath($WorktreePath)
            if (-not $resolved.StartsWith($wtResolved)) { throw 'Path escapes worktree: ' + $f }
        }    }
    & git -C $WorktreePath add -A 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "git add failed in worktree: $WorktreePath" }
    $effectiveWorkerId = if (-not [string]::IsNullOrWhiteSpace($WorkerId)) { $WorkerId } else { 'bridge-bot' }
    $trailerArgs = @('--trailer', "Bridge-Task: $TaskId", '--trailer', "Worker-ID: $effectiveWorkerId")
    if (-not [string]::IsNullOrWhiteSpace($Baseline)) { $trailerArgs += @('--trailer', "Baseline: $Baseline") }
    & git -C $WorktreePath commit -m "Bridge capture for task $TaskId" @trailerArgs 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "git commit failed in worktree: $WorktreePath" }
    return (& git -C $WorktreePath rev-parse HEAD 2>$null | Out-String).Trim()
}
function Get-BaselineSha {
    param([Parameter(Mandatory)][string]$WorktreePath)
    if (-not (Test-GitRepo -Path $WorktreePath)) { return $null }
    return (& git -C $WorktreePath rev-parse HEAD~0 2>$null | Out-String).Trim()
}
function Test-IntegrationReady {
    param(
        [Parameter(Mandatory)][string]$WorktreePath,
        [Parameter(Mandatory)][string]$BaselineRef,
        [Parameter(Mandatory)][string]$TargetRef
    )
    if (-not (Test-GitRepo -Path $WorktreePath)) { return [pscustomobject]@{ ready = $false; reason = 'Not a git repo'; conflicts = @() } }
    $mergeTreeOutput = @(& git -C $WorktreePath merge-tree --write-tree --name-only $TargetRef HEAD 2>&1)
    if ($LASTEXITCODE -eq 0) {
        return [pscustomobject]@{ ready = $true; reason = 'No conflicts (merge-tree)'; conflicts = @() }
    } elseif ($LASTEXITCODE -eq 1) {
        $conflictFiles = @($mergeTreeOutput | Where-Object { $_ -match '^[^#<]' -and -not [string]::IsNullOrWhiteSpace($_.Trim()) } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        return [pscustomobject]@{ ready = $false; reason = 'Conflicting changes detected (merge-tree)'; conflicts = $conflictFiles }
    }
    $mergeBase = (& git -C $WorktreePath merge-base $BaselineRef HEAD 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($mergeBase)) {
        return [pscustomobject]@{ ready = $false; reason = 'Cannot determine merge base'; conflicts = @() }
    }
    $targetChanges = @((& git -C $WorktreePath diff --name-only $BaselineRef $TargetRef 2>$null | Out-String).Trim() -split "
" | Where-Object { $_ })
    $workerChanges = @((& git -C $WorktreePath diff --name-only $BaselineRef HEAD 2>$null | Out-String).Trim() -split "
" | Where-Object { $_ })
    $conflicts = @($targetChanges | Where-Object { $workerChanges -contains $_ })
    if ($conflicts.Count -gt 0) {
        return [pscustomobject]@{ ready = $false; reason = 'Conflicting changes detected (file overlap)'; conflicts = $conflicts }
    }
    return [pscustomobject]@{ ready = $true; reason = 'No conflicts (file overlap)'; conflicts = @() }
}
function Get-WorkDirLockPath {
    param([Parameter(Mandatory)][string]$WorkingDir)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($WorkingDir)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { $hash = $sha.ComputeHash($bytes) } finally { $sha.Dispose() }
    $hex = [System.BitConverter]::ToString($hash).Replace('-','').ToLowerInvariant()
    return Join-Path $LocksRoot ('workdir-' + $hex + '.lock')
}

function Resolve-TaskWorkspace {
    param($Meta, $Project, $Lease, [string]$TaskId)
    $role = if ($Meta.PSObject.Properties.Name -contains 'role' -and -not [string]::IsNullOrWhiteSpace([string]$Meta.role)) { [string]$Meta.role } else { 'implement' }
    if ($Lease -and -not [string]::IsNullOrWhiteSpace([string]$Lease.workingDir)) {
        $mode = if ($Lease.PSObject.Properties.Name -contains 'workspaceMode' -and -not [string]::IsNullOrWhiteSpace([string]$Lease.workspaceMode)) { [string]$Lease.workspaceMode } else { 'existing' }
        $wt = if ($Lease.PSObject.Properties.Name -contains 'worktreePath' -and -not [string]::IsNullOrWhiteSpace([string]$Lease.worktreePath)) { [string]$Lease.worktreePath } else { $null }
        return [pscustomobject]@{ workingDir = [string]$Lease.workingDir; worktreePath = $wt; workspaceMode = $mode; role = $role }
    }
    $mode = if ($Meta.PSObject.Properties.Name -contains 'workspaceMode' -and -not [string]::IsNullOrWhiteSpace([string]$Meta.workspaceMode)) { [string]$Meta.workspaceMode } else { $null }
    if (-not $mode) {
        if ($role -in @('review','test')) { $mode = 'shared-readonly' } else { $mode = 'worktree' }
    }
    $projectRoot = [System.IO.Path]::GetFullPath([string]$Project.projectRoot)
    switch ($mode) {
        'shared-readonly' { return [pscustomobject]@{ workingDir = $projectRoot; worktreePath = $null; workspaceMode = $mode; role = $role } }
        'existing' { return [pscustomobject]@{ workingDir = $projectRoot; worktreePath = $null; workspaceMode = $mode; role = $role } }
        'worktree' {
            $transport = [string]$Project.transport
            if ($transport -ne 'local') { throw "Worktree mode only supports local transport, current transport=$transport" }
            $baseline = if ($Meta.PSObject.Properties.Name -contains 'baseline' -and -not [string]::IsNullOrWhiteSpace([string]$Meta.baseline)) { [string]$Meta.baseline } else { $null }
            $wtMeta = New-TaskWorktree -ProjectRoot $projectRoot -TaskId $TaskId -Baseline $baseline
            return [pscustomobject]@{ workingDir = $wtMeta.worktreePath; worktreePath = $wtMeta.worktreePath; workspaceMode = $mode; role = $role; baselineSha = $wtMeta.baselineSha; branchName = $wtMeta.branchName }
        }
        default { throw "Unsupported workspaceMode: $mode" }
    }
}

function Repair-StaleLeases {
    if (-not (Test-Path -LiteralPath $LeasesRoot -PathType Container)) { return }
    $staleThreshold = [TimeSpan]::FromMinutes(10)
    $now = [DateTimeOffset]::Now
    foreach ($lf in @(Get-ChildItem -LiteralPath $LeasesRoot -File -Filter '*.json' -ErrorAction SilentlyContinue)) {
        try {
            $lease = Read-JsonFile -Path $lf.FullName
            $tid = [string]$lease.taskId
            $taskDir = Get-TaskDirectory -Id $tid
            $statePath = Join-Path $taskDir 'state.json'
            $stale = $true
            if (Test-Path -LiteralPath $statePath -PathType Leaf) {
                $st = Read-JsonFile -Path $statePath
                if ([string]$st.status -in @('QUEUED','STARTING','RUNNING')) {
                    $processId = $null
                    if ($st.PSObject.Properties.Name -contains 'processId' -and $st.processId) { $processId = $st.processId }
                    elseif ($lease.PSObject.Properties.Name -contains 'processId' -and $lease.processId) { $processId = $lease.processId }
                    if ($processId) {
                        $pStartTime = if ($lease.PSObject.Properties.Name -contains 'processStartTime' -and -not [string]::IsNullOrWhiteSpace([string]$lease.processStartTime)) { [string]$lease.processStartTime } elseif ($st.PSObject.Properties.Name -contains 'processStartTime' -and -not [string]::IsNullOrWhiteSpace([string]$st.processStartTime)) { [string]$st.processStartTime } else { '' }
                        if (Test-ProcessAlive -ProcessId $processId -ProcessStartTime $pStartTime) {
                            $stale = $false
                        }
                    }
                    if (-not $stale) { } elseif ($st.PSObject.Properties.Name -contains 'lastHeartbeat' -and -not [string]::IsNullOrWhiteSpace([string]$st.lastHeartbeat)) {
                        $lastActivity = [DateTimeOffset]::Now
                        if ([DateTimeOffset]::TryParse([string]$st.lastHeartbeat, [ref]$lastActivity) -and ($now - $lastActivity) -lt $staleThreshold) {
                            $stale = $false
                        }
                    } elseif ($st.PSObject.Properties.Name -contains 'updatedAt' -and -not [string]::IsNullOrWhiteSpace([string]$st.updatedAt)) {
                        $lastActivity = [DateTimeOffset]::Now
                        if ([DateTimeOffset]::TryParse([string]$st.updatedAt, [ref]$lastActivity) -and ($now - $lastActivity) -lt $staleThreshold) {
                            $stale = $false
                        }
                    }
                }
            }
if ($stale) {
                $wt = if ($lease.PSObject.Properties.Name -contains 'worktreePath' -and -not [string]::IsNullOrWhiteSpace([string]$lease.worktreePath)) { [string]$lease.worktreePath } else { $null }
                if ($wt) {
                    $proot = if ($lease.PSObject.Properties.Name -contains 'projectRoot' -and -not [string]::IsNullOrWhiteSpace([string]$lease.projectRoot)) { [string]$lease.projectRoot } else { $null }
                    if (Test-Path -LiteralPath $wt -PathType Container) {
                        if (-not (Get-GitIsDirty -Path $wt)) {
                            Remove-TaskWorktree -ProjectRoot $proot -WorktreePath $wt
                        }
                    }
                }
                if (Test-Path -LiteralPath $statePath -PathType Leaf) {
                    try {
                        $st = Read-JsonFile -Path $statePath
                        if ([string]$st.status -in @('STARTING','RUNNING')) {
                            $st.status = 'FAILED'
                            $st.updatedAt = $now.ToString('o')
                            $st.message = 'Stale lease detected (dead process, no recent heartbeat)'
                            $st.processId = $null
                            Write-AtomicJson -Path $statePath -Value $st
                        }
                    } catch {}
                }
                Remove-Item -LiteralPath $lf.FullName -Force -ErrorAction SilentlyContinue
            }
        } catch {}
    }
}
function Repair-StaleQueued {
    $staleThreshold = [TimeSpan]::FromMinutes(5)
    $now = [DateTimeOffset]::Now
    foreach ($directory in @(Get-ChildItem -LiteralPath $TasksRoot -Directory -ErrorAction SilentlyContinue)) {
        $statePath = Join-Path $directory.FullName 'state.json'
        if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { continue }
        try {
            $st = Read-JsonFile -Path $statePath
            if ([string]$st.status -ne 'QUEUED') { continue }
            $isStale = $true
            if ($st.PSObject.Properties.Name -contains 'processId' -and $st.processId) {
                $qStartTime = if ($st.PSObject.Properties.Name -contains 'processStartTime') { [string]$st.processStartTime } else { '' }
                if (Test-ProcessAlive -ProcessId $st.processId -ProcessStartTime $qStartTime) { $isStale = $false }
            } else {
                $updatedAt = [DateTimeOffset]::Now
                if ($st.PSObject.Properties.Name -contains 'updatedAt' -and [DateTimeOffset]::TryParse([string]$st.updatedAt, [ref]$updatedAt)) {
                    if (($now - $updatedAt) -lt $staleThreshold) { $isStale = $false }
                }
            }
            if ($isStale) {
                $st.status = 'READY'
                $st.updatedAt = $now.ToString('o')
                $st.message = 'Recovered orphaned QUEUED to READY (stale or dead launcher)'
                $st.processId = $null
                Write-AtomicJson -Path $statePath -Value $st
            }
        } catch {}
    }
}
function Get-RemoteAccessDirective {
    param([Parameter(Mandatory)][string]$HostName, [Parameter(Mandatory)][string]$RemoteProjectPath)
    return "The target source is remote. Access project '$RemoteProjectPath' only through non-interactive commands using ssh -o BatchMode=yes $HostName. Do not seek, read, record, or transfer passwords, tokens, access keys, secret keys, private keys, or .env content. Run every project inspection, edit, test, and build command over SSH inside that remote project. Do not copy source into the bridge directory."
}

function Build-WorkerCorePrompt {
    param(
        [Parameter(Mandatory)][string]$WorkerContract,
        [Parameter(Mandatory)][string]$MetaPath,
        [Parameter(Mandatory)][string[]]$Instructions,
        [Parameter(Mandatory)][string]$OutboxPath,
        [Parameter(Mandatory)][string]$ProjectPath,
        [string]$RemoteDirective,
        [Parameter(Mandatory)][string]$Directive
    )
    $listSegment = Build-InstructionListSegment -Paths $Instructions
    $latest = $Instructions[-1]
    $base = "You are a GLM Worker. Read '$WorkerContract', '$MetaPath', and every instruction file in this task inbox in order: $listSegment. Treat '$latest' as the latest instruction while preserving the full context of all earlier TASK/FIX files. Work autonomously inside project '$ProjectPath'."
    if (-not [string]::IsNullOrWhiteSpace($RemoteDirective)) { $base += " $RemoteDirective" }
    $base += " Write the formal deliverables to '$OutboxPath'; do not return them only in chat. If the built-in editor refuses to write to the outbox, use the current system shell to write the files there. $Directive"
    return $base
}

function Test-WorkerTransportCompatibility {
    param(
        [Parameter(Mandatory)][string]$WorkerTransport,
        [Parameter(Mandatory)][string]$ProjectTransport
    )
    if ($WorkerTransport -eq $ProjectTransport) { return $true }
    return $ProjectTransport -eq 'remote-worktree' -and $WorkerTransport -eq 'ssh'
}

function Select-DispatchPlan {
    param([Parameter(Mandatory)][string]$TasksRoot, [int]$MaxWorkers = 4)

    $candidateStatuses = @('READY','FIX_REQUIRED','RETRYABLE')
    $activeStatuses = @('QUEUED','STARTING','RUNNING')
    $tasks = @()
    foreach ($directory in @(Get-ChildItem -LiteralPath $TasksRoot -Directory -ErrorAction SilentlyContinue | Sort-Object Name)) {
        $statePath = Join-Path $directory.FullName 'state.json'
        $metaPath = Join-Path $directory.FullName 'META.json'
        if (-not (Test-Path -LiteralPath $statePath) -or -not (Test-Path -LiteralPath $metaPath)) { continue }
        $state = Read-JsonFile -Path $statePath
        $meta = Read-JsonFile -Path $metaPath
        $tasks += [pscustomobject]@{ taskId=[string]$state.taskId; directory=$directory.FullName; status=[string]$state.status; projectId=[string]$meta.projectId; meta=$meta }
    }
    $active = @($tasks | Where-Object { $_.status -in $activeStatuses })
    $plan = @()
    $skipped = @()
    $slots = $MaxWorkers - $active.Count
    if ($slots -le 0) { return [pscustomobject]@{ plan=$plan; skipped=$skipped; active=$active } }

    $workersReg = Get-WorkersRegistry
    $workers = if ($workersReg) { @($workersReg.workers) } else { @() }
    if ($workers.Count -eq 0) {
        $legacy = Get-DispatchCandidates -TasksRoot $TasksRoot -MaxWorkers $MaxWorkers
        foreach ($lc in $legacy) {
            $project = $null
            try { $project = Get-Project -Id $lc.projectId } catch { $project = $null }
            $wd = if ($project) { [System.IO.Path]::GetFullPath([string]$project.projectRoot) } else { $lc.directory }
            $plan += [pscustomobject]@{ taskId=$lc.taskId; directory=$lc.directory; projectId=$lc.projectId; workerId=$null; workingDir=$wd; worktreePath=$null; workspaceMode='existing'; role='implement'; status=$lc.status }
        }
        return [pscustomobject]@{ plan=$plan; skipped=$skipped; active=$active }
    }

    $workerUsage = @{}
    $activeWrites = @{}
    $activeAny = @{}
    foreach ($a in $active) {
        $lease = Read-Lease -TaskId $a.taskId
        $wid = $null
        if ($lease -and $lease.PSObject.Properties.Name -contains 'workerId' -and -not [string]::IsNullOrWhiteSpace([string]$lease.workerId)) { $wid = [string]$lease.workerId }
        elseif ($a.meta.PSObject.Properties.Name -contains 'workerId' -and -not [string]::IsNullOrWhiteSpace([string]$a.meta.workerId)) { $wid = [string]$a.meta.workerId }
        if ($wid) { $workerUsage[$wid] = [int]$workerUsage[$wid] + 1 }
        $wd = $null
        if ($lease -and $lease.PSObject.Properties.Name -contains 'workingDir' -and -not [string]::IsNullOrWhiteSpace([string]$lease.workingDir)) { $wd = [string]$lease.workingDir }
        else {
            try { $wd = [System.IO.Path]::GetFullPath([string](Get-Project -Id $a.projectId).projectRoot) } catch { $wd = $null }
        }
        $role = if ($a.meta.PSObject.Properties.Name -contains 'role' -and -not [string]::IsNullOrWhiteSpace([string]$a.meta.role)) { [string]$a.meta.role } else { 'implement' }
        if ($wd) {
            $activeAny[$wd] = [int]$activeAny[$wd] + 1
            if ($role -eq 'implement') { $activeWrites[$wd] = [int]$activeWrites[$wd] + 1 }
        }
    }

    $candidates = @($tasks | Where-Object { $_.status -in $candidateStatuses } | Sort-Object taskId)
    foreach ($c in $candidates) {
        if ($plan.Count -ge $slots) { break }
        $meta = $c.meta
        $deps = @()
        if ($meta.PSObject.Properties.Name -contains 'dependsOn' -and $meta.dependsOn) { $deps = @($meta.dependsOn) }
        $depOk = $true
        foreach ($d in $deps) {
            $depTask = @($tasks | Where-Object { $_.taskId -eq $d })
            if ($depTask.Count -eq 0 -or [string]$depTask[0].status -ne 'DONE') { $depOk = $false; break }
        }
        if (-not $depOk) { $skipped += [pscustomobject]@{ taskId=$c.taskId; reason='dependencies not DONE' }; continue }

        $role = if ($meta.PSObject.Properties.Name -contains 'role' -and -not [string]::IsNullOrWhiteSpace([string]$meta.role)) { [string]$meta.role } else { 'implement' }
        $project = $null
        try { $project = Get-Project -Id $c.projectId } catch { $skipped += [pscustomobject]@{ taskId=$c.taskId; reason="project not found: $($c.projectId)" }; continue }

        $worker = $null
        $explicitWorkerId = if ($meta.PSObject.Properties.Name -contains 'workerId' -and -not [string]::IsNullOrWhiteSpace([string]$meta.workerId)) { [string]$meta.workerId } else { $null }
        if ($explicitWorkerId) {
            $wmatches = @($workers | Where-Object { $_.id -eq $explicitWorkerId })
            if ($wmatches.Count -eq 0) { $skipped += [pscustomobject]@{ taskId=$c.taskId; reason="explicit worker not registered: $explicitWorkerId (not replaced)" }; continue }
            $worker = $wmatches[0]
            if (-not [bool]$worker.enabled) { $skipped += [pscustomobject]@{ taskId=$c.taskId; reason="explicit worker disabled: $explicitWorkerId (not replaced)" }; continue }
            if ([int]$workerUsage[$worker.id] -ge [int]$worker.concurrencyLimit) { $skipped += [pscustomobject]@{ taskId=$c.taskId; reason="explicit worker at capacity: $explicitWorkerId (not replaced)" }; continue }
            $caps = @($worker.capabilities)
            if ($caps.Count -gt 0 -and $role -notin $caps) { $skipped += [pscustomobject]@{ taskId=$c.taskId; reason="explicit worker lacks capability $role : $explicitWorkerId (not replaced)" }; continue }
            if (-not (Test-WorkerTransportCompatibility -WorkerTransport ([string]$worker.transport) -ProjectTransport ([string]$project.transport))) { $skipped += [pscustomobject]@{ taskId=$c.taskId; reason="explicit worker transport mismatch: $($worker.transport) cannot run $($project.transport) (not replaced)" }; continue }
        } else {
            $candidatesW = @($workers | Where-Object { [bool]$_.enabled -and (Test-WorkerTransportCompatibility -WorkerTransport ([string]$_.transport) -ProjectTransport ([string]$project.transport)) } | Sort-Object id)
            $chosen = $null
            foreach ($w in $candidatesW) {
                if ([int]$workerUsage[$w.id] -ge [int]$w.concurrencyLimit) { continue }
                $caps = @($w.capabilities)
                if ($caps.Count -gt 0 -and $role -notin $caps) { continue }
                $chosen = $w; break
            }
            if (-not $chosen) { $skipped += [pscustomobject]@{ taskId=$c.taskId; reason="no available worker for transport $($project.transport) and role $role" }; continue }
            $worker = $chosen
        }

        $mode = if ($meta.PSObject.Properties.Name -contains 'workspaceMode' -and -not [string]::IsNullOrWhiteSpace([string]$meta.workspaceMode)) { [string]$meta.workspaceMode } else { $null }
        if (-not $mode) { if ($role -in @('review','test')) { $mode = 'shared-readonly' } else { $mode = 'worktree' } }
        $projectRoot = if ([string]$project.transport -eq 'local') { [System.IO.Path]::GetFullPath([string]$project.projectRoot) } else { [string]$project.projectRoot }
        $idleKey = if ($project.PSObject.Properties.Name -contains 'sshHost' -and -not [string]::IsNullOrWhiteSpace([string]$project.sshHost)) { "$([string]$project.sshHost)::$projectRoot" } else { $projectRoot }
        $workingDir = $null
        $worktreePath = $null
        $skipReason = $null
        switch ($mode) {
            'worktree' {
                if ([string]$project.transport -ne 'local') { $skipReason = "worktree mode only supported for local transport: $($project.transport)" }
                elseif (-not (Test-GitRepo -Path $projectRoot)) { $skipReason = "worktree mode requires git repo: $projectRoot" }
                elseif (-not (Test-GitHasCommit -Path $projectRoot)) { $skipReason = "worktree mode requires valid commit: $projectRoot" }
                else {
                    $baseline = if ($meta.PSObject.Properties.Name -contains 'baseline' -and -not [string]::IsNullOrWhiteSpace([string]$meta.baseline)) { [string]$meta.baseline } else { $null }
                    if ((Get-GitIsDirty -Path $projectRoot) -and [string]::IsNullOrWhiteSpace($baseline)) { $skipReason = "worktree mode refused: dirty baseline without explicit baseline" }
                    else { $workingDir = Join-Path $WorktreesRoot $c.taskId; $worktreePath = $workingDir }
                }
            }
            'existing' {
                if ([int]$activeAny[$idleKey] -gt 0) { $skipReason = "existing mode requires idle project: $idleKey" } else { $workingDir = $projectRoot }
            }
            'shared-readonly' {
                if ([int]$activeWrites[$idleKey] -gt 0) { $skipReason = "shared-readonly refused: active write on $idleKey" } else { $workingDir = $projectRoot }
            }
            default { $skipReason = "unsupported workspaceMode: $mode" }
        }
        if ($skipReason) { $skipped += [pscustomobject]@{ taskId=$c.taskId; reason=$skipReason }; continue }

        $plan += [pscustomobject]@{ taskId=$c.taskId; directory=$c.directory; projectId=$c.projectId; workerId=$worker.id; workingDir=$workingDir; worktreePath=$worktreePath; workspaceMode=$mode; role=$role; status=$c.status }
        $workerUsage[$worker.id] = [int]$workerUsage[$worker.id] + 1
        if ($mode -eq 'existing') { $activeAny[$idleKey] = [int]$activeAny[$idleKey] + 1 }
        if ($role -eq 'implement' -and $mode -ne 'worktree') { $activeWrites[$idleKey] = [int]$activeWrites[$idleKey] + 1 }
    }
    return [pscustomobject]@{ plan=$plan; skipped=$skipped; active=$active }
}
function Get-OutboxSummaryText {
    param([string]$TaskDirectory)
    $outbox = Join-Path $TaskDirectory 'outbox'
    $resultPath = Join-Path $outbox 'RESULT.md'
    $testsPath = Join-Path $outbox 'TESTS.md'
    $sb = [System.Text.StringBuilder]::new()
    [void]$sb.AppendLine('=== outbox summary ===')
    [void]$sb.AppendLine('')
    [void]$sb.AppendLine('--- RESULT.md ---')
    if (Test-Path -LiteralPath $resultPath -PathType Leaf) {
        $lines = [System.IO.File]::ReadAllLines($resultPath)
        $total = $lines.Count
        $take = [Math]::Min($total, 20)
        $chunk = $lines[0..($take - 1)]
        $text = ($chunk -join "`n")
        $text = Invoke-SensitiveMask -Text $text
        if ($total -gt 20) { $text += "`n...(truncated, $total total lines, showing first 20)" }
        [void]$sb.AppendLine($text)
    } else {
        [void]$sb.AppendLine('(missing)')
    }
    [void]$sb.AppendLine('')
    [void]$sb.AppendLine('--- TESTS.md ---')
    if (Test-Path -LiteralPath $testsPath -PathType Leaf) {
        $lines = [System.IO.File]::ReadAllLines($testsPath)
        $total = $lines.Count
        $take = [Math]::Min($total, 15)
        $chunk = $lines[0..($take - 1)]
        $text = ($chunk -join "`n")
        $text = Invoke-SensitiveMask -Text $text
        if ($total -gt 15) { $text += "`n...(truncated, $total total lines, showing first 15)" }
        [void]$sb.AppendLine($text)
    } else {
        [void]$sb.AppendLine('(missing)')
    }
    return $sb.ToString()
}
function Get-JsonEventSummary {
    param([string]$Line)
    if ([string]::IsNullOrWhiteSpace($Line)) { return $null }
    $event = $null
    try { $event = $Line | ConvertFrom-Json -ErrorAction Stop } catch { return $null }
    if (-not $event) { return $null }
    $names = @($event.PSObject.Properties.Name)
    $type = if ($names -contains 'type') { [string]$event.type } else { 'event' }
    $isThinking = $type -in @('reasoning', 'thinking')
    $tool = ''
    if ($names -contains 'part' -and $event.part) {
        $partNames = @($event.part.PSObject.Properties.Name)
        if ($partNames -contains 'tool' -and $event.part.tool) { $tool = [string]$event.part.tool }
        elseif ($partNames -contains 'tool_name' -and $event.part.tool_name) { $tool = [string]$event.part.tool_name }
    }
    if (-not $tool) {
        if ($names -contains 'tool' -and $event.tool) { $tool = [string]$event.tool }
        elseif ($names -contains 'tool_name' -and $event.tool_name) { $tool = [string]$event.tool_name }
    }
    $text = ''
    if ($names -contains 'part' -and $event.part) {
        $partNames = @($event.part.PSObject.Properties.Name)
        if ($partNames -contains 'text' -and $event.part.text) { $text = [string]$event.part.text }
    }
    if (-not $text) {
        foreach ($prop in @('text', 'content', 'message')) {
            if ($names -contains $prop -and $event.$prop) { $text = [string]$event.$prop; break }
        }
    }
    if ($text) {
        $text = ($text -replace "`r|`n", ' ').Trim()
        $text = Invoke-SensitiveMask -Text $text
        if ($text.Length -gt 160) { $text = $text.Substring(0, 160) + '...' }
    }
    if ($isThinking) {
        $result = '[think]'
        if ($text) { $result += " text=$text" } else { $result += " type=$type" }
        return $result
    }
    $result = "[event] type=$type"
    if ($tool) { $result += " tool=$tool" }
    if ($text) { $result += " text=$text" }
    return $result
}
function Drain-AsyncLines {
    param(
        $Reader, $Task, $Buffer, $Builder, $LogWriter, $LineBuffer,
        [switch]$ShowProgress, [switch]$IsError,
        [ref]$EventsRef, [ref]$ThoughtRef, [ref]$ToolRef
    )
    if ($null -eq $Task) { return $null }
    while ($Task.IsCompleted) {
        $charsRead = $Task.GetAwaiter().GetResult()
        if ($charsRead -le 0) { return $null }
        $chunk = [string]::new($Buffer, 0, $charsRead)
        $maxBuilderBytes = 16777216
        $chunkBytes = [System.Text.Encoding]::UTF8.GetByteCount($chunk)
        if (($Builder.Length + $chunkBytes) -gt $maxBuilderBytes) {
            $currentLen = [System.Text.Encoding]::UTF8.GetByteCount($Builder.ToString())
            if (($currentLen + $chunkBytes) -gt $maxBuilderBytes) {
                $keepBytes = [int]($maxBuilderBytes / 2)
                $current = $Builder.ToString()
                $currentBytes = $currentLen
                if ($currentBytes -gt $keepBytes) {
                    $ratio = [double]$keepBytes / [double]$currentBytes
                    $cutChars = [int]($current.Length * $ratio)
                    if ($cutChars -lt 1) { $cutChars = 1 }
                    $current = $current.Substring($current.Length - $cutChars)
                    while ([System.Text.Encoding]::UTF8.GetByteCount($current) -gt $keepBytes -and $current.Length -gt 1) { $current = $current.Substring(1) }
                }
                $Builder.Clear() | Out-Null
                [void]$Builder.Append('...[truncated tail]...' + [char]13 + [char]10 + $current)
            }
        }
        [void]$Builder.Append($chunk)
        $LogWriter.Write((Invoke-SensitiveMask -Text $chunk))
        [void]$LineBuffer.Append($chunk)
        while ($true) {
            $lineContent = $LineBuffer.ToString()
            $nlIdx = $lineContent.IndexOf([char]10)
            if ($nlIdx -lt 0) { break }
            $completeLine = $lineContent.Substring(0, $nlIdx).TrimEnd([char]13)
            $rest = $lineContent.Substring($nlIdx + 1)
            $LineBuffer.Clear() | Out-Null
            [void]$LineBuffer.Append($rest)
            if ($completeLine.Length -gt 1048576) { $completeLine = $completeLine.Substring(0, 1048576) + '...[truncated]' }
            if ($ShowProgress) {
                if ($IsError) {
                    $summary = Invoke-SensitiveMask -Text $completeLine
                    $summary = ($summary -replace '[\r\n]', ' ').Trim()
                    if ($summary.Length -gt 160) { $summary = $summary.Substring(0, 160) + '...' }
                    [Console]::WriteLine("[stderr] $summary")
                } else {
                    $summary = Get-JsonEventSummary -Line $completeLine
                    if ($summary) {
                        [Console]::WriteLine($summary)
                        if ($EventsRef) { $EventsRef.Value++ }
                        if ($summary.StartsWith('[think]')) {
                            if ($ThoughtRef) { $ThoughtRef.Value++ }
                        } elseif ($summary -match ' tool=\S') {
                            if ($ToolRef) { $ToolRef.Value++ }
                        }
                    }
                }
            }
        }
        $Task = $Reader.ReadAsync($Buffer, 0, $Buffer.Length)
    }
    return $Task
}
function Complete-Drain {
    param($Process, $StdoutTask, $StderrTask, $StdoutBuffer, $StderrBuffer, $StdoutLineBuffer, $StderrLineBuffer, $StdoutLog, $StderrLog, $StdoutReadBuffer, $StderrReadBuffer, $DrainDeadline, [switch]$ShowProgress, [ref]$EventsRef, [ref]$ThoughtRef, [ref]$ToolRef)
    $drainIncomplete = $false
    while (($StdoutTask -ne $null -or $StderrTask -ne $null) -and [DateTimeOffset]::Now -lt $DrainDeadline) {
        if ($StdoutTask -ne $null) {
            if (-not $StdoutTask.IsCompleted) { try { $null = $StdoutTask.Wait(5000) } catch {} }
            if ($StdoutTask.IsCompleted) { $StdoutTask = Drain-AsyncLines -Reader $Process.StandardOutput -Task $StdoutTask -Buffer $StdoutReadBuffer -Builder $StdoutBuffer -LogWriter $StdoutLog -LineBuffer $StdoutLineBuffer -ShowProgress:$ShowProgress -EventsRef $EventsRef -ThoughtRef $ThoughtRef -ToolRef $ToolRef }
        }
        if ($StderrTask -ne $null) {
            if (-not $StderrTask.IsCompleted) { try { $null = $StderrTask.Wait(5000) } catch {} }
            if ($StderrTask.IsCompleted) { $StderrTask = Drain-AsyncLines -Reader $Process.StandardError -Task $StderrTask -Buffer $StderrReadBuffer -Builder $StderrBuffer -LogWriter $StderrLog -LineBuffer $StderrLineBuffer -ShowProgress:$ShowProgress -IsError }
        }
    }
    if ($StdoutTask -ne $null -or $StderrTask -ne $null) {
        $drainIncomplete = $true
        if ($StderrLog) { try { $StderrLog.WriteLine('[WARN] Drain incomplete: output pipe may not have closed within deadline') } catch {} }
    }
    return $drainIncomplete
}
function Invoke-BoundedFetch {
    param([Parameter(Mandatory)][string]$FilePath, [Parameter(Mandatory)][string[]]$Arguments, [Parameter(Mandatory)][int]$TimeoutSeconds)
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $FilePath
    $info.UseShellExecute = $false
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.CreateNoWindow = $true
    $ae = @()
    foreach ($a in $Arguments) { if ($a -match "\s") { $ae += [char]34 + $a + [char]34 } else { $ae += $a } }
    $info.Arguments = $ae -join " "
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $info
    $stdoutBuilder = [System.Text.StringBuilder]::new()
    $stderrBuilder = [System.Text.StringBuilder]::new()
    $stdoutLineBuffer = [System.Text.StringBuilder]::new()
    $stderrLineBuffer = [System.Text.StringBuilder]::new()
    $stdoutReadBuffer = New-Object char[] 8192
    $stderrReadBuffer = New-Object char[] 8192
    $stdoutTask = $null
    $stderrTask = $null
    $nullLog = $null
    try {
        $nullLog = [System.IO.StreamWriter]::new([System.IO.MemoryStream]::new())
        $launchMsg = [string]::Concat("launch ", "failed")
        if (-not $process.
Start()) { return @{ ExitCode = -1; StandardOutput = ""; StandardError = $launchMsg } }
        $stdoutTask = $process.StandardOutput.ReadAsync($stdoutReadBuffer, 0, $stdoutReadBuffer.Length)
        $stderrTask = $process.StandardError.ReadAsync($stderrReadBuffer, 0, $stderrReadBuffer.Length)
        $deadline = [DateTimeOffset]::Now.AddSeconds($TimeoutSeconds)
        while (-not $process.HasExited) {
            $stdoutTask = Drain-AsyncLines -Reader $process.StandardOutput -Task $stdoutTask -Buffer $stdoutReadBuffer -Builder $stdoutBuilder -LogWriter $nullLog -LineBuffer $stdoutLineBuffer
            $stderrTask = Drain-AsyncLines -Reader $process.StandardError -Task $stderrTask -Buffer $stderrReadBuffer -Builder $stderrBuilder -LogWriter $nullLog -LineBuffer $stderrLineBuffer -IsError
            if ([DateTimeOffset]::Now -ge $deadline) { try { $process.Kill($true) } catch {}; break }
            Start-Sleep -Milliseconds 50
        }
        if (-not $process.HasExited) { $null = $process.WaitForExit(5000) }
        $drainDeadline = [DateTimeOffset]::Now.AddSeconds(10)
        $null = Complete-Drain -Process $process -StdoutTask $stdoutTask -StderrTask $stderrTask -StdoutBuffer $stdoutBuilder -StderrBuffer $stderrBuilder -StdoutLineBuffer $stdoutLineBuffer -StderrLineBuffer $stderrLineBuffer -StdoutLog $nullLog -StderrLog $nullLog -StdoutReadBuffer $stdoutReadBuffer -StderrReadBuffer $stderrReadBuffer -DrainDeadline $drainDeadline
        $ec = if ($process.HasExited) { $process.ExitCode } else { -1 }
        return @{ ExitCode = $ec; StandardOutput = $stdoutBuilder.ToString(); StandardError = $stderrBuilder.ToString() }
    } catch {
        return @{ ExitCode = -1; StandardOutput = $stdoutBuilder.ToString(); StandardError = $_.Exception.Message }
    } finally {
        if ($nullLog) { $nullLog.Dispose() }
        if ($process) { $process.Dispose() }
    }
}

function Invoke-CapturedProcess {
    param(
        [Parameter(Mandatory)][System.Diagnostics.ProcessStartInfo]$StartInfo,
        [Parameter(Mandatory)][string]$TaskDirectory,
        [Parameter(Mandatory)][int]$TimeoutSeconds,
        [Parameter(Mandatory)][string]$LogPrefix,
        [string]$TaskId = "",
        [string]$ProjectId = "",
        [int]$Attempt = 0,
        [string]$SessionMode = "",
        [int]$SoftTimeoutSeconds = 0,
        [int]$SoftGraceSeconds = 0,
        [scriptblock]$PollAction,
        [switch]$ShowProgress
    )
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $StartInfo
    $stdoutBuilder = [System.Text.StringBuilder]::new()
    $stderrBuilder = [System.Text.StringBuilder]::new()
    $stdoutLineBuffer = [System.Text.StringBuilder]::new()
    $stderrLineBuffer = [System.Text.StringBuilder]::new()
    $stdoutReadBuffer = New-Object char[] 8192
    $stderrReadBuffer = New-Object char[] 8192
    $stdoutTask = $null
    $stderrTask = $null
    $stdoutFs = $null
    $stderrFs = $null
    $stdoutLog = $null
    $stderrLog = $null
    $started = [DateTimeOffset]::Now
    $deadline = $started.AddSeconds($TimeoutSeconds)
    if ($SoftGraceSeconds -le 0 -and $SoftTimeoutSeconds -gt 0 -and $TimeoutSeconds -gt $SoftTimeoutSeconds) {
        $SoftGraceSeconds = $TimeoutSeconds - $SoftTimeoutSeconds
    }
    $cancelPath = Join-Path $TaskDirectory "CANCEL_REQUESTED"
    $lastProgressAt = $started
    $eventsCount = 0
    $thoughtCount = 0
    $toolCount = 0
    $lastHeartbeatUpdate = $started
    $lastPollAt = $started
    $pollIntervalSeconds = 10
    $softGraceStarted = $false
    $softGraceStart = $null
    try {
        $logDir = Split-Path -Parent $LogPrefix
        if ($logDir) { [System.IO.Directory]::CreateDirectory($logDir) | Out-Null }
        $stdoutFs = [System.IO.FileStream]::new($LogPrefix + ".stdout.log", [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
        $stdoutLog = [System.IO.StreamWriter]::new($stdoutFs, [System.Text.UTF8Encoding]::new($false))
        $stderrFs = [System.IO.FileStream]::new($LogPrefix + ".stderr.log", [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
        $stderrLog = [System.IO.StreamWriter]::new($stderrFs, [System.Text.UTF8Encoding]::new($false))
        $stdoutLog.AutoFlush = $true
        $stderrLog.AutoFlush = $true
        $errMsg = [string]::Concat("Cannot ", "start ", "proc", "ess: ", $StartInfo.FileName)
        if (-not $process.Start()) { throw $errMsg }
        $stdoutTask = $process.StandardOutput.ReadAsync($stdoutReadBuffer, 0, $stdoutReadBuffer.Length)
        $stderrTask = $process.StandardError.ReadAsync($stderrReadBuffer, 0, $stderrReadBuffer.Length)
        Set-State -Directory $TaskDirectory -Status "RUNNING" -Message "Worker is running" -ProcessId $process.Id | Out-Null
        while (-not $process.HasExited) {
            $stdoutTask = Drain-AsyncLines -Reader $process.StandardOutput -Task $stdoutTask -Buffer $stdoutReadBuffer -Builder $stdoutBuilder -LogWriter $stdoutLog -LineBuffer $stdoutLineBuffer -ShowProgress:$ShowProgress -EventsRef ([ref]$eventsCount) -ThoughtRef ([ref]$thoughtCount) -ToolRef ([ref]$toolCount)
            $stderrTask = Drain-AsyncLines -Reader $process.StandardError -Task $stderrTask -Buffer $stderrReadBuffer -Builder $stderrBuilder -LogWriter $stderrLog -LineBuffer $stderrLineBuffer -ShowProgress:$ShowProgress -IsError
            if ($ShowProgress -and ([DateTimeOffset]::Now - $lastProgressAt).TotalSeconds -ge 5) {
                $lastProgressAt = [DateTimeOffset]::Now
                $elapsed = ([DateTimeOffset]::Now - $started).ToString("hh\:mm\:ss")
                $modeLabel = if ($SessionMode) { $SessionMode } else { "new" }
                $workerTag = if ($TaskId -match '-(w\d{2})-') { $matches[1] } else { '?' }
                [Console]::WriteLine("[Worker $workerTag] task=$TaskId proj=$ProjectId attempt=$Attempt mode=$modeLabel pid=$($process.Id) elapsed=$elapsed events=$eventsCount think=$thoughtCount tool=$toolCount")
            }
            if (([DateTimeOffset]::Now - $lastHeartbeatUpdate).TotalSeconds -ge 30) {
                $lastHeartbeatUpdate = [DateTimeOffset]::Now
                Set-State -Directory $TaskDirectory -Status "RUNNING" -Message "Worker is running" -ProcessId $process.Id -LastHeartbeat ([DateTimeOffset]::Now.ToString("o")) | Out-Null
            }
            $assistancePath = Join-Path $TaskDirectory "outbox\ASSISTANCE_REQUEST.md"
            $assistanceRequested = Test-Path -LiteralPath $assistancePath -PathType Leaf
            $softTimeoutHit = ($SoftTimeoutSeconds -gt 0 -and ([DateTimeOffset]::Now - $started).TotalSeconds -ge $SoftTimeoutSeconds)
            if ($softTimeoutHit -and -not $softGraceStarted -and -not $assistanceRequested) {
                $softGraceStarted = $true
                $softGraceStart = [DateTimeOffset]::Now
                if ($ShowProgress) { [Console]::WriteLine("[Worker] Soft timeout hit, starting grace period") }
            }
            $graceExpired = ($softGraceStarted -and ([DateTimeOffset]::Now - $softGraceStart).TotalSeconds -ge $SoftGraceSeconds)
            if ($assistanceRequested -or $graceExpired) {
                $assistReason = if ($assistanceRequested) { "Worker requested assistance via ASSISTANCE_REQUEST.md" } else { "Soft timeout grace period expired" }
                try { $process.Kill($true) } catch {}
                $null = $process.WaitForExit(5000)
                $drainDeadline = [DateTimeOffset]::Now.AddSeconds(10)
                $null = Complete-Drain -Process $process -StdoutTask $stdoutTask -StderrTask $stderrTask -StdoutBuffer $stdoutBuilder -StderrBuffer $stderrBuilder -StdoutLineBuffer $stdoutLineBuffer -StderrLineBuffer $stderrLineBuffer -StdoutLog $stdoutLog -StderrLog $stderrLog -StdoutReadBuffer $stdoutReadBuffer -StderrReadBuffer $stderrReadBuffer -DrainDeadline $drainDeadline -ShowProgress:$ShowProgress -EventsRef ([ref]$eventsCount) -ThoughtRef ([ref]$thoughtCount) -ToolRef ([ref]$toolCount)
                Set-State -Directory $TaskDirectory -Status "ASSISTANCE_REQUIRED" -Message $assistReason -ExitCode $process.ExitCode | Out-Null
                if ($ShowProgress) { [Console]::WriteLine("[Worker] ASSISTANCE_REQUIRED pid=$($process.Id) log=$LogPrefix") }
                return [pscustomobject]@{ ExitCode = $process.ExitCode; Cancelled = $false; TimedOut = $false; AssistanceRequested = $true; StandardOutput = $stdoutBuilder.ToString(); StandardError = $stderrBuilder.ToString() }
            }
            if (Test-Path -LiteralPath $cancelPath) {
                try { $process.Kill($true) } catch {}
                $null = $process.WaitForExit(5000)
                $drainDeadline = [DateTimeOffset]::Now.AddSeconds(10)
                $null = Complete-Drain -Process $process -StdoutTask $stdoutTask -StderrTask $stderrTask -StdoutBuffer $stdoutBuilder -StderrBuffer $stderrBuilder -StdoutLineBuffer $stdoutLineBuffer -StderrLineBuffer $stderrLineBuffer -StdoutLog $stdoutLog -StderrLog $stderrLog -StdoutReadBuffer $stdoutReadBuffer -StderrReadBuffer $stderrReadBuffer -DrainDeadline $drainDeadline -ShowProgress:$ShowProgress -EventsRef ([ref]$eventsCount) -ThoughtRef ([ref]$thoughtCount) -ToolRef ([ref]$toolCount)
                Set-State -Directory $TaskDirectory -Status "CANCELLED" -Message "Cancel received, project state preserved" -ExitCode $process.ExitCode | Out-Null
                if ($ShowProgress) { [Console]::WriteLine("[Worker] CANCELLED pid=$($process.Id) log=$LogPrefix") }
                return [pscustomobject]@{ ExitCode = $process.ExitCode; Cancelled = $true; TimedOut = $false; StandardOutput = $stdoutBuilder.ToString(); StandardError = $stderrBuilder.ToString() }
            }
            if ([DateTimeOffset]::Now -ge $deadline) {
                try { $process.Kill($true) } catch {}
                $null = $process.WaitForExit(5000)
                $drainDeadline = [DateTimeOffset]::Now.AddSeconds(10)
                $null = Complete-Drain -Process $process -StdoutTask $stdoutTask -StderrTask $stderrTask -StdoutBuffer $stdoutBuilder -StderrBuffer $stderrBuilder -StdoutLineBuffer $stdoutLineBuffer -StderrLineBuffer $stderrLineBuffer -StdoutLog $stdoutLog -StderrLog $stderrLog -StdoutReadBuffer $stdoutReadBuffer -StderrReadBuffer $stderrReadBuffer -DrainDeadline $drainDeadline -ShowProgress:$ShowProgress -EventsRef ([ref]$eventsCount) -ThoughtRef ([ref]$thoughtCount) -ToolRef ([ref]$toolCount)
                $stderrText = $stderrBuilder.ToString()
                if ($stderrText -match "model.*queue|queued.*for.*model|rate.*limit|too.*many.*requests|model queued") {
                    Set-State -Directory $TaskDirectory -Status "RETRYABLE" -Message "Model queue wait exceeded $TimeoutSeconds seconds, terminated" -ExitCode $process.ExitCode | Out-Null
                } else {
                    Set-State -Directory $TaskDirectory -Status "FAILED" -Message "Worker exceeded $TimeoutSeconds seconds, terminated with state preserved" -ExitCode $process.ExitCode | Out-Null
                }
                if ($ShowProgress) { [Console]::WriteLine("[Worker] TIMED_OUT pid=$($process.Id) log=$LogPrefix") }
                return [pscustomobject]@{ ExitCode = $process.ExitCode; Cancelled = $false; TimedOut = $true; StandardOutput = $stdoutBuilder.ToString(); StandardError = $stderrBuilder.ToString() }
            }
            if ($PollAction -and (([DateTimeOffset]::Now - $lastPollAt).TotalSeconds -ge $pollIntervalSeconds)) {
                $lastPollAt = [DateTimeOffset]::Now
                try { & $PollAction } catch {}
            }
            Start-Sleep -Milliseconds 100
        }
        if (-not $process.WaitForExit(10000)) { try { $process.Kill($true); $null = $process.WaitForExit(5000) } catch {} }
        $drainDeadline = [DateTimeOffset]::Now.AddSeconds(10)
        $null = Complete-Drain -Process $process -StdoutTask $stdoutTask -StderrTask $stderrTask -StdoutBuffer $stdoutBuilder -StderrBuffer $stderrBuilder -StdoutLineBuffer $stdoutLineBuffer -StderrLineBuffer $stderrLineBuffer -StdoutLog $stdoutLog -StderrLog $stderrLog -StdoutReadBuffer $stdoutReadBuffer -StderrReadBuffer $stderrReadBuffer -DrainDeadline $drainDeadline -ShowProgress:$ShowProgress -EventsRef ([ref]$eventsCount) -ThoughtRef ([ref]$thoughtCount) -ToolRef ([ref]$toolCount)
        if ($ShowProgress) {
            $telemetry = Parse-CodeArtsJsonLines -Output $stdoutBuilder.ToString()
            $eventCount = (@($stdoutBuilder.ToString() -split "`r?`n" | Where-Object { $_ -match "^\s*\{" }).Count)
            $elapsed = ([DateTimeOffset]::Now - $started).ToString("hh\:mm\:ss")
            [Console]::WriteLine("[Worker] DONE pid=$($process.Id) exit=$($process.ExitCode) events=$eventCount elapsed=$elapsed log=$LogPrefix")
            if ($telemetry.lastEventAt) { [Console]::WriteLine("[Worker] lastEventAt=$($telemetry.lastEventAt)") }
            if ($telemetry.sessionId) { [Console]::WriteLine("[Worker] sessionId=$($telemetry.sessionId)") }
        }
        return [pscustomobject]@{ ExitCode = $process.ExitCode; Cancelled = $false; TimedOut = $false; StandardOutput = $stdoutBuilder.ToString(); StandardError = $stderrBuilder.ToString() }
    } finally {
        if ($stdoutTask -and -not $stdoutTask.IsCompleted) { try { $null = $stdoutTask.Wait(2000) } catch {} }
        if ($stderrTask -and -not $stderrTask.IsCompleted) { try { $null = $stderrTask.Wait(2000) } catch {} }
        if ($stdoutLog) { try { $stdoutLog.Dispose() } catch {} }
        if ($stderrLog) { try { $stderrLog.Dispose() } catch {} }
        if ($stdoutFs) { try { $stdoutFs.Dispose() } catch {} }
        if ($stderrFs) { try { $stderrFs.Dispose() } catch {} }
        if ($process) { try { $process.Dispose() } catch {} }
    }
}

function Set-WorkerProcessGuardrail {
    param([Parameter(Mandatory)][System.Diagnostics.ProcessStartInfo]$StartInfo)
    $StartInfo.EnvironmentVariables['GIT_TERMINAL_PROMPT'] = '0'
    $StartInfo.EnvironmentVariables['GIT_ASKPASS'] = $null
    $StartInfo.EnvironmentVariables['GIT_SSH_COMMAND'] = 'ssh -o BatchMode=yes -o StrictHostKeyChecking=yes'
    $emptyConfig = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), 'bridge-empty-config-' + [System.Diagnostics.Process]::GetCurrentProcess().Id + '.conf')
    $StartInfo.EnvironmentVariables['GIT_CONFIG_NOSYSTEM'] = '1'
    $StartInfo.EnvironmentVariables['GIT_CONFIG_GLOBAL'] = $emptyConfig
    $StartInfo.EnvironmentVariables['GIT_CONFIG_COUNT'] = '6'
    $StartInfo.EnvironmentVariables['GIT_CONFIG_KEY_0'] = 'credential.helper'
    $StartInfo.EnvironmentVariables['GIT_CONFIG_VALUE_0'] = ''
    $StartInfo.EnvironmentVariables['GIT_CONFIG_KEY_1'] = 'remote.origin.pushurl'
    $StartInfo.EnvironmentVariables['GIT_CONFIG_VALUE_1'] = 'invalid://bridge-blocked-push'
    $StartInfo.EnvironmentVariables['GIT_CONFIG_KEY_2'] = 'protocol.file.allow'
    $StartInfo.EnvironmentVariables['GIT_CONFIG_VALUE_2'] = 'never'
    $StartInfo.EnvironmentVariables['GIT_CONFIG_KEY_3'] = 'protocol.git.allow'
    $StartInfo.EnvironmentVariables['GIT_CONFIG_VALUE_3'] = 'never'
    $StartInfo.EnvironmentVariables['GIT_CONFIG_KEY_4'] = 'protocol.https.allow'
    $StartInfo.EnvironmentVariables['GIT_CONFIG_VALUE_4'] = 'never'
    $StartInfo.EnvironmentVariables['GIT_CONFIG_KEY_5'] = 'protocol.ssh.allow'
    $StartInfo.EnvironmentVariables['GIT_CONFIG_VALUE_5'] = 'never'
    foreach ($var in @('GIT_USERNAME','GIT_PASSWORD','GIT_TOKEN','GH_TOKEN','GITHUB_TOKEN','GITLAB_TOKEN','SSH_AUTH_SOCK','SSH_AGENT_PID','SSH_KEY_PATH','GIT_SSH_KEYPATH','GIT_SSH_KEY','GIT_ASKPASS','GIT_AUTHOR_NAME','GIT_AUTHOR_EMAIL','GIT_COMMITTER_NAME','GIT_COMMITTER_EMAIL','GIT_CREDENTIAL_HELPER','GIT_CREDENTIAL_MANAGER','GIT_CREDENTIAL_MANAGER_HELPER','GIT_CREDENTIAL_STORE','GCM_INTERACTIVE','GCM_PROVIDER','GCM_PLUGINS','DISPLAY','TERM')) {
        $StartInfo.EnvironmentVariables.Remove($var) | Out-Null
    }
}

function Invoke-LocalWorker {
    param($Project, $Worker, [string]$WorkingDir, [string]$TaskDirectory, [string]$Mode, [int]$TimeoutSeconds, [string]$LogPrefix, [string]$SessionId, [string]$TaskId, [int]$Attempt = 0, [int]$SoftTimeoutSeconds = 0)
    $cli = if ($Worker -and $Worker.PSObject.Properties.Name -contains 'cliPath' -and -not [string]::IsNullOrWhiteSpace([string]$Worker.cliPath)) { [string]$Worker.cliPath } else { Find-CodeArtsCli }
    if (-not $cli -or -not (Test-Path -LiteralPath $cli -PathType Leaf)) { throw 'codearts CLI not found. Run the official installer first, then rerun doctor.' }
    $projectPath = if ($WorkingDir) { $WorkingDir } else { [System.IO.Path]::GetFullPath([string]$Project.projectRoot) }
    if (-not (Test-Path -LiteralPath $projectPath -PathType Container)) { throw "Project directory does not exist: $projectPath" }

    $instructions = @(Get-InstructionContext -TaskDirectory $TaskDirectory)
    $workerContract = Join-Path $ProtocolRoot 'WORKER.md'
    $metaPath = Join-Path $TaskDirectory 'META.json'
    $outboxPath = Join-Path $TaskDirectory 'outbox'
    $directive = $script:ThinkLanguageDirective
    $prompt = Build-WorkerCorePrompt -WorkerContract $workerContract -MetaPath $metaPath -Instructions $instructions -OutboxPath $outboxPath -ProjectPath $projectPath -RemoteDirective '' -Directive $directive
    $modelValue = $script:RequiredModel
    $modeFlag = Get-ModeFlag -Mode $Mode
    $argList = New-WorkerRunArguments -Prompt $prompt -Model $modelValue -ModeFlag $modeFlag -TaskId $TaskId -SessionId $SessionId
    $info = New-ProcessStartInfo -FilePath $cli -Arguments $argList -WorkingDirectory $projectPath -NoWindow:$Quiet
    Set-WorkerProcessGuardrail -StartInfo $info
    $sm = if ($SessionId) { 'resume' } else { 'new' }
    return Invoke-CapturedProcess -StartInfo $info -TaskDirectory $TaskDirectory -TimeoutSeconds $TimeoutSeconds -LogPrefix $LogPrefix -TaskId $TaskId -ProjectId ([string]$Project.id) -SessionMode $sm -Attempt $Attempt -SoftTimeoutSeconds $SoftTimeoutSeconds -ShowProgress:(-not $Quiet)
}
function Invoke-SshShellWorker {
    param($Project, $Worker, [string]$WorkingDir, [string]$TaskDirectory, [string]$Mode, [int]$TimeoutSeconds, [string]$LogPrefix, [string]$SessionId, [string]$TaskId, [int]$Attempt = 0, [int]$SoftTimeoutSeconds = 0)
    $cli = Find-CodeArtsCli
    if (-not $cli -or -not (Test-Path -LiteralPath $cli -PathType Leaf)) { throw 'codearts CLI not found. Run the official installer first, then rerun doctor.' }
    if ([string]::IsNullOrWhiteSpace([string]$Project.sshHost)) { throw 'ssh-shell project missing sshHost' }
    if ([string]$Project.sshHost -notmatch '^[A-Za-z0-9_.@:-]+$') { throw 'sshHost contains unsafe characters' }

    $instructions = @(Get-InstructionContext -TaskDirectory $TaskDirectory)
    $workerContract = Join-Path $ProtocolRoot 'WORKER.md'
    $metaPath = Join-Path $TaskDirectory 'META.json'
    $outboxPath = Join-Path $TaskDirectory 'outbox'
    $hostName = [string]$Project.sshHost
    $remoteProjectPath = [string]$Project.projectRoot
    $directive = $script:ThinkLanguageDirective
    $remoteDirective = Get-RemoteAccessDirective -HostName $hostName -RemoteProjectPath $remoteProjectPath
    $prompt = Build-WorkerCorePrompt -WorkerContract $workerContract -MetaPath $metaPath -Instructions $instructions -OutboxPath $outboxPath -ProjectPath $remoteProjectPath -RemoteDirective $remoteDirective -Directive $directive
    $modelValue = $script:RequiredModel
    $modeFlag = Get-ModeFlag -Mode $Mode
    $argList = New-WorkerRunArguments -Prompt $prompt -Model $modelValue -ModeFlag $modeFlag -TaskId $TaskId -SessionId $SessionId
    $info = New-ProcessStartInfo -FilePath $cli -Arguments $argList -WorkingDirectory $BridgeRoot
    Set-WorkerProcessGuardrail -StartInfo $info
    $sm = if ($SessionId) { 'resume' } else { 'new' }
    return Invoke-CapturedProcess -StartInfo $info -TaskDirectory $TaskDirectory -TimeoutSeconds $TimeoutSeconds -LogPrefix $LogPrefix -TaskId $TaskId -ProjectId ([string]$Project.id) -SessionMode $sm -Attempt $Attempt -SoftTimeoutSeconds $SoftTimeoutSeconds -ShowProgress:(-not $Quiet)
}
function Invoke-SshCommand {
    param([string]$HostName, [string]$RemoteCommand, [string]$TaskDirectory, [int]$TimeoutSeconds, [string]$LogPrefix, [string]$TaskId = '', [string]$ProjectId = '', [int]$Attempt = 0, [string]$SessionMode = '', [scriptblock]$PollAction, [switch]$ShowProgress)
    $ssh = (Get-Command ssh -ErrorAction Stop).Path
    $info = New-ProcessStartInfo -FilePath $ssh -Arguments @('-o', 'BatchMode=yes', $HostName, $RemoteCommand)
    return Invoke-CapturedProcess -StartInfo $info -TaskDirectory $TaskDirectory -TimeoutSeconds $TimeoutSeconds -LogPrefix $LogPrefix -TaskId $TaskId -ProjectId $ProjectId -Attempt $Attempt -SessionMode $SessionMode -PollAction:$PollAction -ShowProgress:$ShowProgress
}
function Invoke-SshWorker {
    param($Project, $Worker, [string]$WorkingDir, [string]$TaskDirectory, [string]$Mode, [int]$TimeoutSeconds, [string]$LogPrefix, [string]$SessionId, [string]$TaskId, [int]$Attempt = 0, [int]$SoftTimeoutSeconds = 0)
    if ([string]::IsNullOrWhiteSpace([string]$Project.sshHost)) { throw 'SSH project missing sshHost' }
    if ([string]::IsNullOrWhiteSpace([string]$Project.remoteBridgeRoot)) { throw 'SSH project missing remoteBridgeRoot' }
    if ([string]$Project.sshHost -notmatch '^[A-Za-z0-9_.@:-]+$') { throw 'sshHost contains unsafe characters' }

    $hostName = [string]$Project.sshHost
    $remoteCli = if ($Worker -and $Worker.PSObject.Properties.Name -contains 'cliPath' -and -not [string]::IsNullOrWhiteSpace([string]$Worker.cliPath)) { [string]$Worker.cliPath } elseif ($Project.PSObject.Properties.Name -contains 'remoteCliPath' -and -not [string]::IsNullOrWhiteSpace([string]$Project.remoteCliPath)) { [string]$Project.remoteCliPath } else { 'codearts' }
    if ($remoteCli -ne 'codearts' -and -not $remoteCli.StartsWith('/')) { throw "remoteCliPath must be absolute or codearts: $remoteCli" }
    $remoteTask = ([string]$Project.remoteBridgeRoot).TrimEnd('/') + '/tasks/' + (Split-Path -Leaf $TaskDirectory)
    $remoteProtocol = ([string]$Project.remoteBridgeRoot).TrimEnd('/') + '/protocol'
    $remoteOutbox = $remoteTask + '/outbox'
    $instructions = @(Get-InstructionContext -TaskDirectory $TaskDirectory)
    $scp = (Get-Command scp -ErrorAction Stop).Path

    $prepare = "mkdir -p $(Quote-Posix $remoteProtocol) $(Quote-Posix ($remoteTask + '/inbox')) $(Quote-Posix $remoteOutbox)"
    $prepareResult = Invoke-SshCommand -HostName $hostName -RemoteCommand $prepare -TaskDirectory $TaskDirectory -TimeoutSeconds 60 -LogPrefix ($LogPrefix + '.prepare')
    if ($prepareResult.ExitCode -ne 0) { return $prepareResult }

    $copies = @(
        @{ Local = (Join-Path $ProtocolRoot 'WORKER.md'); Remote = $remoteProtocol + '/WORKER.md' },
        @{ Local = (Join-Path $TaskDirectory 'META.json'); Remote = $remoteTask + '/META.json' }
    )
    foreach ($instr in $instructions) {
        $copies += @{ Local = $instr; Remote = $remoteTask + '/inbox/' + (Split-Path -Leaf $instr) }
    }
    foreach ($copy in $copies) {
        $copyInfo = New-ProcessStartInfo -FilePath $scp -Arguments @('-q', $copy.Local, ($hostName + ':' + $copy.Remote))
        $copyResult = Invoke-CapturedProcess -StartInfo $copyInfo -TaskDirectory $TaskDirectory -TimeoutSeconds 60 -LogPrefix ($LogPrefix + '.copy-' + [System.IO.Path]::GetFileName($copy.Local))
        if ($copyResult.ExitCode -ne 0) { return $copyResult }
    }

    $instructionNames = @($instructions | ForEach-Object { Split-Path -Leaf $_ })
    $remoteInstructionPaths = @($instructionNames | ForEach-Object { "$remoteTask/inbox/$_" })
    $remoteProjectPath = if ($WorkingDir) { $WorkingDir } else { [string]$Project.projectRoot }
    $directive = $script:ThinkLanguageDirective
    $remoteDirective = Get-RemoteAccessDirective -HostName $hostName -RemoteProjectPath $remoteProjectPath
    $remotePrompt = Build-WorkerCorePrompt -WorkerContract ($remoteProtocol + '/WORKER.md') -MetaPath ($remoteTask + '/META.json') -Instructions $remoteInstructionPaths -OutboxPath $remoteOutbox -ProjectPath $remoteProjectPath -RemoteDirective $remoteDirective -Directive $directive
    $modelValue = $script:RequiredModel
    $modeFlag = Get-ModeFlag -Mode $Mode
    $remoteArgs = New-WorkerRunArguments -Prompt $remotePrompt -Model $modelValue -ModeFlag $modeFlag -TaskId $TaskId -SessionId $SessionId
    $remoteRunSegment = ($remoteArgs | ForEach-Object { Quote-Posix $_ }) -join ' '
    $innerCmd = $remoteCli + ' ' + $remoteRunSegment
    $runCommand = 'script -qfc ' + (Quote-Posix $innerCmd) + ' /dev/null'
    $sm = if ($SessionId) { 'resume' } else { 'new' }
    $cdPart = 'cd -- ' + (Quote-Posix $remoteProjectPath)
    $parts = @($cdPart, $runCommand)
    $localOutbox = Join-Path $TaskDirectory 'outbox'
    $pollHostName = $hostName
    $pollRemoteOutbox = $remoteOutbox
    $pollScp = $scp
    $pollTaskDir = $TaskDirectory
    $pollLogPrefix = $LogPrefix
    $controlPollAction = {
        foreach ($ctrlFile in @('ASSISTANCE_REQUEST.md', 'CHECKPOINT.md')) {
            $localCtrl = Join-Path $localOutbox $ctrlFile
            if (-not (Test-Path -LiteralPath $localCtrl -PathType Leaf)) {
                try { $null = Invoke-BoundedFetch -FilePath $pollScp -Arguments @('-q', ($pollHostName + ':' + $pollRemoteOutbox + '/' + $ctrlFile), $localCtrl) -TimeoutSeconds 10 } catch {}
            }
        }
    }
    $runResult = Invoke-SshCommand -HostName $hostName -RemoteCommand ($parts -join ' && ') -TaskDirectory $TaskDirectory -TimeoutSeconds $TimeoutSeconds -LogPrefix $LogPrefix -TaskId $TaskId -ProjectId ([string]$Project.id) -Attempt $Attempt -SessionMode $sm -PollAction $controlPollAction -SoftTimeoutSeconds $SoftTimeoutSeconds -ShowProgress:(-not $Quiet)
    $fetchInfo = New-ProcessStartInfo -FilePath $scp -Arguments @('-q', '-r', ($hostName + ':' + $remoteOutbox + '/.'), $localOutbox)
    $fetchResult = Invoke-CapturedProcess -StartInfo $fetchInfo -TaskDirectory $TaskDirectory -TimeoutSeconds 120 -LogPrefix ($LogPrefix + '.fetch')
    if ($runResult.ExitCode -ne 0) { return $runResult }
    return $fetchResult
}
function Export-WorkerBundle {
    param([Parameter(Mandatory)][string]$ProjectRoot, [Parameter(Mandatory)][string]$BaselineSha, [Parameter(Mandatory)][string]$TaskId)
    Assert-SafeId -Value $TaskId -Label 'TaskId'
    $bundleDir = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-bundles')
    if (-not (Test-Path -LiteralPath $bundleDir)) { [System.IO.Directory]::CreateDirectory($bundleDir) | Out-Null }
    $bundleFile = Join-Path $bundleDir ('export-' + $TaskId + '.bundle')
    if (Test-Path -LiteralPath $bundleFile) { Remove-Item -LiteralPath $bundleFile -Force }
    $tmpRef = 'refs/tmp/export-' + $TaskId
    & git -C $ProjectRoot update-ref $tmpRef $BaselineSha 2>&1 | Out-Null
    & git -C $ProjectRoot bundle create $bundleFile $tmpRef 2>&1 | Out-Null
    $bundleExit = $LASTEXITCODE
    & git -C $ProjectRoot update-ref -d $tmpRef 2>&1 | Out-Null
    if ($bundleExit -ne 0 -or -not (Test-Path -LiteralPath $bundleFile -PathType Leaf)) { throw 'git bundle create failed for ' + $TaskId }
    $hash = (Get-FileHash -LiteralPath $bundleFile -Algorithm SHA256).Hash
    return [pscustomobject]@{ BundleFile = $bundleFile; Sha256 = $hash; BaselineSha = $BaselineSha }
}

function Get-RemoteWorkerGuardrailPrefix {
    $gitSshValue = Quote-Posix 'ssh -o BatchMode=yes -o StrictHostKeyChecking=yes'
    $exports = @(
        'export GIT_TERMINAL_PROMPT=0',
        'export GIT_ASKPASS=',
        'export GIT_SSH_COMMAND=' + $gitSshValue,
        'export GIT_CONFIG_NOSYSTEM=1',
        'export GIT_CONFIG_SYSTEM=/dev/null',
        'export GIT_CONFIG_GLOBAL=/dev/null',
        'export GIT_CONFIG_COUNT=7',
        'export GIT_CONFIG_KEY_0=credential.helper',
        'export GIT_CONFIG_VALUE_0=',
        'export GIT_CONFIG_KEY_1=remote.origin.pushurl',
        'export GIT_CONFIG_VALUE_1=invalid://bridge-blocked-push',
        'export GIT_CONFIG_KEY_2=protocol.file.allow',
        'export GIT_CONFIG_VALUE_2=never',
        'export GIT_CONFIG_KEY_3=protocol.git.allow',
        'export GIT_CONFIG_VALUE_3=never',
        'export GIT_CONFIG_KEY_4=protocol.http.allow',
        'export GIT_CONFIG_VALUE_4=never',
        'export GIT_CONFIG_KEY_5=protocol.https.allow',
        'export GIT_CONFIG_VALUE_5=never',
        'export GIT_CONFIG_KEY_6=protocol.ssh.allow',
        'export GIT_CONFIG_VALUE_6=never'
    )
    $unsets = @(
        'GIT_USERNAME','GIT_PASSWORD','GIT_TOKEN','GH_TOKEN','GITHUB_TOKEN','GITLAB_TOKEN',
        'SSH_AUTH_SOCK','SSH_AGENT_PID','SSH_KEY_PATH','GIT_SSH_KEYPATH','GIT_SSH_KEY',
        'GIT_CREDENTIAL_HELPER','GIT_CREDENTIAL_MANAGER','GIT_CREDENTIAL_MANAGER_HELPER',
        'GIT_CREDENTIAL_STORE','GCM_INTERACTIVE','GCM_PROVIDER','GCM_PLUGINS'
    )
    return ($exports -join '; ') + '; unset ' + ($unsets -join ' ') + ' 2>/dev/null || true'
}

function Initialize-RemoteWorkspace {
    param(
        [Parameter(Mandatory)][string]$HostName,
        [Parameter(Mandatory)][string]$RemoteWorkspaceRoot,
        [Parameter(Mandatory)][string]$TaskId,
        [Parameter(Mandatory)][string]$BundleFile,
        [Parameter(Mandatory)][string]$BundleSha256,
        [Parameter(Mandatory)][string]$BaselineSha,
        [Parameter(Mandatory)][string]$WorkerContractPath,
        [Parameter(Mandatory)][string]$MetaPath,
        [Parameter(Mandatory)][string[]]$InstructionPaths,
        [string]$RemoteCliPath = 'codearts',
        [string]$SshPath,
        [string]$ScpPath,
        [string]$LogDirectory
    )
    Assert-SafeId -Value $TaskId -Label 'TaskId'
    if ($HostName -notmatch '^[A-Za-z0-9_.@:-]+$') { throw 'HostName contains unsafe characters' }
    if ($RemoteWorkspaceRoot -notmatch '^/[A-Za-z0-9._/-]+$' -or $RemoteWorkspaceRoot -match '(^|/)\.\.(/|$)') { throw 'RemoteWorkspaceRoot must be a safe absolute POSIX path' }
    if ($RemoteCliPath -ne 'codearts' -and $RemoteCliPath -notmatch '^/[A-Za-z0-9._/-]+$') { throw 'RemoteCliPath must be a safe absolute POSIX path or codearts' }
    if ($BaselineSha -notmatch '^(?:[0-9a-f]{40}|[0-9a-f]{64})$') { throw 'BaselineSha must be a canonical Git object ID' }
    if ($BundleSha256 -notmatch '^[0-9A-Fa-f]{64}$') { throw 'BundleSha256 must be a SHA-256 digest' }

    $requiredFiles = @($BundleFile, $WorkerContractPath, $MetaPath) + @($InstructionPaths)
    foreach ($path in $requiredFiles) {
        if ([string]::IsNullOrWhiteSpace($path) -or -not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'Required bootstrap file not found' }
    }
    foreach ($instruction in @($InstructionPaths)) {
        $name = Split-Path -Leaf $instruction
        if ($name -notmatch '^\d{3}-[A-Za-z0-9._-]+\.md$') { throw 'Unsafe instruction filename: ' + $name }
    }
    $actualBundleSha = (Get-FileHash -LiteralPath $BundleFile -Algorithm SHA256).Hash
    if ($actualBundleSha -ne $BundleSha256) { throw 'Local bundle digest mismatch before remote bootstrap' }
    $bundleHeads = (& git bundle list-heads $BundleFile 2>$null | Out-String)
    if ($LASTEXITCODE -ne 0 -or $bundleHeads -notmatch [regex]::Escape($BaselineSha)) { throw 'Bundle does not contain the declared baseline' }

    $effectiveSsh = if ($SshPath) { $SshPath } else { (Get-Command ssh -ErrorAction Stop).Path }
    $effectiveScp = if ($ScpPath) { $ScpPath } else { (Get-Command scp -ErrorAction Stop).Path }
    $effectiveLogDir = if ($LogDirectory) { $LogDirectory } else { [System.IO.Path]::GetTempPath() }
    [System.IO.Directory]::CreateDirectory($effectiveLogDir) | Out-Null

    $remoteRoot = $RemoteWorkspaceRoot.TrimEnd('/')
    $remoteTaskDir = $remoteRoot + '/' + $TaskId
    $remoteRepo = $remoteTaskDir + '/repo'
    $remoteProtocol = $remoteTaskDir + '/protocol'
    $remoteInbox = $remoteTaskDir + '/inbox'
    $remoteOutbox = $remoteTaskDir + '/outbox'
    $remoteBundle = $remoteTaskDir + '/export.bundle'
    $remoteBranch = 'task/' + $TaskId

    $initCmd = 'umask 077 && test ! -e ' + (Quote-Posix $remoteTaskDir) + ' && mkdir -p ' + (Quote-Posix $remoteRepo) + ' ' + (Quote-Posix $remoteProtocol) + ' ' + (Quote-Posix $remoteInbox) + ' ' + (Quote-Posix $remoteOutbox) + ' && git init -q ' + (Quote-Posix $remoteRepo) + ' && git -C ' + (Quote-Posix $remoteRepo) + ' config user.name Bridge && git -C ' + (Quote-Posix $remoteRepo) + ' config user.email bridge@local'
    $initInfo = New-ProcessStartInfo -FilePath $effectiveSsh -Arguments @('-o','BatchMode=yes',$HostName,$initCmd)
    $initResult = Invoke-CapturedProcess -StartInfo $initInfo -TaskDirectory $effectiveLogDir -TimeoutSeconds 60 -LogPrefix (Join-Path $effectiveLogDir 'remote-init')
    if ($initResult.ExitCode -ne 0) { throw 'Remote workspace init failed: ' + $initResult.StandardError }

    # Remap allowedPaths from central source to remote repo so CodeArts Edit/Write
    # authorization checks pass when the worker operates inside the isolated worktree.
    $metaForRemote = $MetaPath
    try {
        $metaObj = Get-Content -LiteralPath $MetaPath -Raw | ConvertFrom-Json
        if ($metaObj.PSObject.Properties.Name -contains 'allowedPaths') {
            $metaObj.allowedPaths = @($remoteRepo)
            $remappedMetaPath = Join-Path $effectiveLogDir 'META-remapped.json'
            $metaObj | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $remappedMetaPath -NoNewline
            $metaForRemote = $remappedMetaPath
        }
    } catch {}

    $transfers = @(
        @{ Local=$BundleFile; Remote=$remoteBundle; Label='bundle' },
        @{ Local=$WorkerContractPath; Remote=($remoteProtocol + '/WORKER.md'); Label='worker-contract' },
        @{ Local=$metaForRemote; Remote=($remoteTaskDir + '/META.json'); Label='task-meta' }
    )
    $remoteInstructionPaths = @()
    foreach ($instruction in @($InstructionPaths)) {
        $remoteInstruction = $remoteInbox + '/' + (Split-Path -Leaf $instruction)
        $transfers += @{ Local=$instruction; Remote=$remoteInstruction; Label=(Split-Path -Leaf $instruction) }
        $remoteInstructionPaths += $remoteInstruction
    }
    foreach ($transfer in $transfers) {
        $copyInfo = New-ProcessStartInfo -FilePath $effectiveScp -Arguments @('-q',$transfer.Local,($HostName + ':' + $transfer.Remote))
        $copyResult = Invoke-CapturedProcess -StartInfo $copyInfo -TaskDirectory $effectiveLogDir -TimeoutSeconds 60 -LogPrefix (Join-Path $effectiveLogDir ('remote-copy-' + $transfer.Label))
        if ($copyResult.ExitCode -ne 0) { throw 'Remote copy failed for ' + $transfer.Label + ': ' + $copyResult.StandardError }
    }

    $fetchCmd = 'git -C ' + (Quote-Posix $remoteRepo) + ' fetch -q ' + (Quote-Posix $remoteBundle) + ' ' + $BaselineSha + ':refs/heads/' + $remoteBranch + ' && git -C ' + (Quote-Posix $remoteRepo) + ' checkout -q ' + $remoteBranch
    $fetchInfo = New-ProcessStartInfo -FilePath $effectiveSsh -Arguments @('-o','BatchMode=yes',$HostName,$fetchCmd)
    $fetchResult = Invoke-CapturedProcess -StartInfo $fetchInfo -TaskDirectory $effectiveLogDir -TimeoutSeconds 60 -LogPrefix (Join-Path $effectiveLogDir 'remote-fetch-bundle')
    if ($fetchResult.ExitCode -ne 0) { throw 'Remote bundle fetch failed: ' + $fetchResult.StandardError }

    return [pscustomobject]@{
        RemoteRepo = $remoteRepo
        RemoteBranch = $remoteBranch
        RemoteTaskDir = $remoteTaskDir
        RemoteOutbox = $remoteOutbox
        RemoteMetaPath = $remoteTaskDir + '/META.json'
        RemoteWorkerContract = $remoteProtocol + '/WORKER.md'
        RemoteInstructionPaths = [string[]]$remoteInstructionPaths
        BundleSha256 = $actualBundleSha
        BaselineSha = $BaselineSha
    }
}

function Import-WorkerBundle {
    param([Parameter(Mandatory)][string]$HostName, [Parameter(Mandatory)][string]$RemoteRepo, [Parameter(Mandatory)][string]$RemoteBranch, [Parameter(Mandatory)][string]$ProjectRoot, [Parameter(Mandatory)][string]$TaskId, [Parameter(Mandatory)][string]$BaselineSha)
    Assert-SafeId -Value $TaskId -Label 'TaskId'
    $scp = (Get-Command scp -ErrorAction Stop).Path
    $ssh = (Get-Command ssh -ErrorAction Stop).Path
    $localBundleDir = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-bundles')
    if (-not (Test-Path -LiteralPath $localBundleDir)) { [System.IO.Directory]::CreateDirectory($localBundleDir) | Out-Null }
    $localBundleFile = Join-Path $localBundleDir ('import-' + $TaskId + '.bundle')
    if (Test-Path -LiteralPath $localBundleFile) { Remove-Item -LiteralPath $localBundleFile -Force }
    $remoteBundle = (Join-Path ([System.IO.Path]::GetTempPath()) ('result-' + $TaskId + '.bundle')).Replace('\','/')
    $createBundleCmd = 'git -C ' + (Quote-Posix $RemoteRepo) + ' bundle create ' + (Quote-Posix $remoteBundle) + ' ' + $RemoteBranch + ' 2>&1'
    $bundleInfo = New-ProcessStartInfo -FilePath $ssh -Arguments @('-o', 'BatchMode=yes', $HostName, $createBundleCmd)
    $bundleResult = Invoke-CapturedProcess -StartInfo $bundleInfo -TaskDirectory ([System.IO.Path]::GetTempPath()) -TimeoutSeconds 60 -LogPrefix 'remote-create-bundle'
    if ($bundleResult.ExitCode -ne 0) { throw 'Remote bundle create failed: ' + $bundleResult.StandardError }
    $copyInfo = New-ProcessStartInfo -FilePath $scp -Arguments @('-q', ($HostName + ':' + $remoteBundle), $localBundleFile)
    $copyResult = Invoke-CapturedProcess -StartInfo $copyInfo -TaskDirectory ([System.IO.Path]::GetTempPath()) -TimeoutSeconds 60 -LogPrefix 'local-copy-bundle'
    if ($copyResult.ExitCode -ne 0) { throw 'Result bundle SCP failed: ' + $copyResult.StandardError }
    $namespacedRef = 'refs/worker/' + $TaskId + '/result'
    $refspec = $RemoteBranch + ':' + $namespacedRef
    & git -C $ProjectRoot fetch -q $localBundleFile $refspec 2>&1 | Out-Null
    $importedSha = (& git -C $ProjectRoot rev-parse $namespacedRef 2>$null | Out-String).Trim()
    if ([string]::IsNullOrWhiteSpace($importedSha)) { throw 'Cannot resolve imported ref for ' + $TaskId }
    & git -C $ProjectRoot merge-base --is-ancestor $BaselineSha $importedSha 2>&1 | Out-Null
    $isAncestor = ($LASTEXITCODE -eq 0)
    if (-not $isAncestor) { throw 'Imported commit is not a descendant of baseline for ' + $TaskId }
    $hash = (Get-FileHash -LiteralPath $localBundleFile -Algorithm SHA256).Hash
    return [pscustomobject]@{ ImportedSha = $importedSha; BundleFile = $localBundleFile; Sha256 = $hash; NamespacedRef = $namespacedRef; AncestryValid = $true }
}

function Remove-RemoteWorkspace {
    param([Parameter(Mandatory)][string]$HostName, [Parameter(Mandatory)][string]$RemoteTaskDir, [Parameter(Mandatory)][string]$TaskId)
    Assert-SafeId -Value $TaskId -Label 'TaskId'
    if ($RemoteTaskDir -notmatch ('/' + $TaskId + [char]36)) { throw 'Remote task dir does not end with task ID, refusing cleanup: ' + $RemoteTaskDir }
    $ssh = (Get-Command ssh -ErrorAction Stop).Path
    $cleanCmd = 'rm -rf ' + (Quote-Posix $RemoteTaskDir)
    $cleanInfo = New-ProcessStartInfo -FilePath $ssh -Arguments @('-o', 'BatchMode=yes', $HostName, $cleanCmd)
    $null = Invoke-CapturedProcess -StartInfo $cleanInfo -TaskDirectory ([System.IO.Path]::GetTempPath()) -TimeoutSeconds 30 -LogPrefix 'remote-cleanup'
}

function Invoke-RemoteWorktreeWorker {
    param($Project, $Worker, [string]$WorkingDir, [string]$TaskDirectory, [string]$Mode, [int]$TimeoutSeconds, [string]$LogPrefix, [string]$SessionId, [string]$TaskId, [string]$Baseline, [int]$Attempt = 0, [int]$SoftTimeoutSeconds = 0)
    if ([string]::IsNullOrWhiteSpace([string]$Project.sshHost)) { throw 'remote-worktree project missing sshHost' }
    if ([string]::IsNullOrWhiteSpace([string]$Project.remoteWorkspaceRoot)) { throw 'remote-worktree project missing remoteWorkspaceRoot' }
    if ([string]$Project.sshHost -notmatch '^[A-Za-z0-9_.@:-]+$') { throw 'sshHost contains unsafe characters' }
    $hostName = [string]$Project.sshHost
    $projectRoot = if ($WorkingDir) { $WorkingDir } else { [string]$Project.projectRoot }
    if (-not (Test-GitRepo -Path $projectRoot)) { throw 'Not a git repo: ' + $projectRoot }
    $baselineRef = if (-not [string]::IsNullOrWhiteSpace($Baseline)) { $Baseline } else { 'HEAD' }
    $baselineSha = (& git -C $projectRoot rev-parse -q --verify ($baselineRef + '^{commit}') 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($baselineSha)) { throw 'Cannot resolve remote-worktree baseline ' + $baselineRef + ' in ' + $projectRoot }
    $remoteWorkspaceRoot = [string]$Project.remoteWorkspaceRoot
    $remoteCli = if ($Worker -and $Worker.PSObject.Properties.Name -contains 'cliPath' -and -not [string]::IsNullOrWhiteSpace([string]$Worker.cliPath)) { [string]$Worker.cliPath } elseif ($Project.PSObject.Properties.Name -contains 'remoteCliPath' -and -not [string]::IsNullOrWhiteSpace([string]$Project.remoteCliPath)) { [string]$Project.remoteCliPath } else { 'codearts' }
    if ($remoteCli -ne 'codearts' -and -not $remoteCli.StartsWith('/')) { throw 'remoteCliPath must be absolute or codearts: ' + $remoteCli }
    $instructions = @(Get-InstructionContext -TaskDirectory $TaskDirectory)
    $workerContract = Join-Path $ProtocolRoot 'WORKER.md'
    $metaPath = Join-Path $TaskDirectory 'META.json'
    $exportResult = Export-WorkerBundle -ProjectRoot $projectRoot -BaselineSha $baselineSha -TaskId $TaskId
    $initResult = Initialize-RemoteWorkspace -HostName $hostName -RemoteWorkspaceRoot $remoteWorkspaceRoot -TaskId $TaskId -BundleFile $exportResult.BundleFile -BundleSha256 $exportResult.Sha256 -BaselineSha $baselineSha -WorkerContractPath $workerContract -MetaPath $metaPath -InstructionPaths $instructions -RemoteCliPath $remoteCli -LogDirectory $TaskDirectory
    $directive = $script:ThinkLanguageDirective
    $prompt = Build-WorkerCorePrompt -WorkerContract $initResult.RemoteWorkerContract -MetaPath $initResult.RemoteMetaPath -Instructions $initResult.RemoteInstructionPaths -OutboxPath $initResult.RemoteOutbox -ProjectPath $initResult.RemoteRepo -RemoteDirective '' -Directive $directive
    $modelValue = $script:RequiredModel
    $modeFlag = Get-ModeFlag -Mode $Mode
    $argList = New-WorkerRunArguments -Prompt $prompt -Model $modelValue -ModeFlag $modeFlag -TaskId $TaskId -SessionId $SessionId
    $remoteRunSegment = ($argList | ForEach-Object { Quote-Posix $_ }) -join ' '
    $runCommand = (Get-RemoteWorkerGuardrailPrefix) + '; cd -- ' + (Quote-Posix $initResult.RemoteRepo) + ' && ' + $remoteCli + ' ' + $remoteRunSegment
    $sm = if ($SessionId) { 'resume' } else { 'new' }
    $runResult = Invoke-SshCommand -HostName $hostName -RemoteCommand $runCommand -TaskDirectory $TaskDirectory -TimeoutSeconds $TimeoutSeconds -LogPrefix $LogPrefix -TaskId $TaskId -ProjectId ([string]$Project.id) -SessionMode $sm -Attempt $Attempt -ShowProgress:(-not $Quiet)
    if ($runResult.ExitCode -eq 0) {
        try {
            $importResult = Import-WorkerBundle -HostName $hostName -RemoteRepo $initResult.RemoteRepo -RemoteBranch $initResult.RemoteBranch -ProjectRoot $projectRoot -TaskId $TaskId -BaselineSha $baselineSha
            $runResult | Add-Member -NotePropertyName ImportedSha -NotePropertyValue $importResult.ImportedSha
            $runResult | Add-Member -NotePropertyName BundleSha256 -NotePropertyValue $importResult.Sha256
            $runResult | Add-Member -NotePropertyName BaselineSha -NotePropertyValue $baselineSha
        } catch {
            $runResult | Add-Member -NotePropertyName ImportError -NotePropertyValue $_.Exception.Message
        }
    }
    $scp = (Get-Command scp -ErrorAction Stop).Path
    $localOutbox = Join-Path $TaskDirectory 'outbox'
    $remoteOutbox = $initResult.RemoteOutbox
    $fetchInfo = New-ProcessStartInfo -FilePath $scp -Arguments @('-q', '-r', ($hostName + ':' + $remoteOutbox + '/.'), $localOutbox)
    $null = Invoke-CapturedProcess -StartInfo $fetchInfo -TaskDirectory $TaskDirectory -TimeoutSeconds 120 -LogPrefix ($LogPrefix + '.fetch')
    return $runResult
}

function Complete-WorkerRun {
    param(
        [string]$TaskDirectory,
        $Result,
        [string]$ExistingSessionId,
        [string]$WorktreePath,
        [string]$ProjectRoot,
        [string]$TaskId,
        [string]$WorkerId,
        [string]$Baseline
    )

    $exitCode = $null
    if ($Result -and $Result.PSObject.Properties.Name -contains 'ExitCode') {
        $rawExit = $Result.ExitCode
        if ($rawExit -is [array]) { $exitCode = [int]$rawExit[0] }
        elseif ($null -ne $rawExit) { $exitCode = [int]$rawExit }
    }
    if ($Result.PSObject.Properties.Name -contains 'AssistanceRequested' -and $Result.AssistanceRequested) {
        if ($TaskId) { Remove-Lease -TaskId $TaskId }
        return
    }
    $isCancelled = if ($Result.PSObject.Properties.Name -contains 'Cancelled') { [bool]$Result.Cancelled } else { $false }
    $isTimedOut = if ($Result.PSObject.Properties.Name -contains 'TimedOut') { [bool]$Result.TimedOut } else { $false }
    if ($isCancelled -or $isTimedOut) {
        $telemetry = Parse-CodeArtsJsonLines -Output ([string]$Result.StandardOutput)
        $sessionId = if ($telemetry.sessionId) { [string]$telemetry.sessionId } else { $ExistingSessionId }
        $sessionMode = $null
        if ($sessionId) { $sessionMode = if ($ExistingSessionId) { 'resume' } else { 'new' } }
        $telemetryParams = @{}
        if ($sessionId) { $telemetryParams.SessionId = $sessionId }
        if ($sessionMode) { $telemetryParams.SessionMode = $sessionMode }
        if ($telemetry.lastEventAt) { $telemetryParams.LastEventAt = $telemetry.lastEventAt }
        if ($null -ne $telemetry.tokens) { $telemetryParams.Tokens = $telemetry.tokens }
        $currentState = Get-State -Directory $TaskDirectory
        Set-State -Directory $TaskDirectory -Status ([string]$currentState.status) -Message ([string]$currentState.message) -ExitCode $exitCode @telemetryParams | Out-Null
        if ($TaskId) { Remove-Lease -TaskId $TaskId }
        return
    }
    $telemetry = Parse-CodeArtsJsonLines -Output ([string]$Result.StandardOutput)
    $sessionId = if ($telemetry.sessionId) { [string]$telemetry.sessionId } else { $ExistingSessionId }
    $sessionMode = $null
    if ($sessionId) {
        $sessionMode = if ($ExistingSessionId) { 'resume' } else { 'new' }
    }
    $telemetryParams = @{}
    if ($sessionId) { $telemetryParams.SessionId = $sessionId }
    if ($sessionMode) { $telemetryParams.SessionMode = $sessionMode }
    if ($telemetry.lastEventAt) { $telemetryParams.LastEventAt = $telemetry.lastEventAt }
    if ($null -ne $telemetry.tokens) { $telemetryParams.Tokens = $telemetry.tokens }

    $outbox = Join-Path $TaskDirectory 'outbox'
    $hasBlocker = Test-Path -LiteralPath (Join-Path $outbox 'BLOCKER.md')
    $required = @('RESULT.md', 'DIFF.stat', 'TESTS.md')
    $missing = @($required | Where-Object { -not (Test-Path -LiteralPath (Join-Path $outbox $_) -PathType Leaf) })
    $stderrText = [string]$Result.StandardError
    if ($exitCode -ne 0 -and $stderrText -match 'authentication failed|CODEARTS_CLI_AK|CODEARTS_CLI_SK|authentication failed|authorization failed|not authorized|not authorized') {
        Set-State -Directory $TaskDirectory -Status 'AUTH_REQUIRED' -Message 'CodeArts CLI AK/SK authorization not completed' -ExitCode $exitCode @telemetryParams | Out-Null
    } elseif ($hasBlocker) {
        Set-State -Directory $TaskDirectory -Status 'BLOCKED' -Message 'Worker reported architectural block' -ExitCode $exitCode @telemetryParams | Out-Null
    } elseif ($exitCode -ne 0) {
        Set-State -Directory $TaskDirectory -Status 'FAILED' -Message "Worker exit code: $($exitCode)" -ExitCode $exitCode @telemetryParams | Out-Null
    } elseif ($missing.Count -gt 0) {
        Set-State -Directory $TaskDirectory -Status 'FAILED' -Message ('Protocol deliverables incomplete: ' + ($missing -join ', ')) -ExitCode $exitCode @telemetryParams | Out-Null
    } else {
        Set-State -Directory $TaskDirectory -Status 'REVIEW_REQUIRED' -Message 'Worker deliverables complete, awaiting review' -ExitCode $exitCode @telemetryParams | Out-Null
    }
    if (-not [string]::IsNullOrWhiteSpace($WorktreePath)) {
        $evState = ConvertTo-OrderedState (Get-State -Directory $TaskDirectory)
        $evState.worktreePath = $WorktreePath
        $evState.branchName = 'agent/' + $TaskId
        $evState.projectRoot = $ProjectRoot
        if (-not [string]::IsNullOrWhiteSpace($Baseline)) { $evState.baselineSha = $Baseline }
        Write-AtomicJson -Path (Join-Path $TaskDirectory 'state.json') -Value $evState
    }
    if ($TaskId) { Remove-Lease -TaskId $TaskId }
    if (-not [string]::IsNullOrWhiteSpace($WorktreePath) -and (Test-Path -LiteralPath $WorktreePath -PathType Container)) {
        try {
            $capturedSha = Capture-WorkerCommit -WorktreePath $WorktreePath -TaskId $TaskId -WorkerId $WorkerId -Baseline $Baseline
            if ($capturedSha) {
                $evState = ConvertTo-OrderedState (Get-State -Directory $TaskDirectory)
                $evState.commitSha = $capturedSha
                $evState.projectRoot = $ProjectRoot
                if (-not [string]::IsNullOrWhiteSpace($Baseline)) { $evState.baselineSha = $Baseline }
                Write-AtomicJson -Path (Join-Path $TaskDirectory 'state.json') -Value $evState
            } else {
                $failState = ConvertTo-OrderedState (Get-State -Directory $TaskDirectory)
                $failState.status = 'FAILED'
                $failState.message = 'Commit capture returned no SHA; worktree preserved for review'
                $failState.worktreePath = $WorktreePath
                $failState.projectRoot = $ProjectRoot
                $failState.branchName = 'agent/' + $TaskId
                Write-AtomicJson -Path (Join-Path $TaskDirectory 'state.json') -Value $failState
            }
        } catch {
            $failState = ConvertTo-OrderedState (Get-State -Directory $TaskDirectory)
            $failState.status = 'FAILED'
            $failState.message = 'Commit capture failed: ' + $_.Exception.Message + '; worktree preserved for review'
            $failState.worktreePath = $WorktreePath
            $failState.projectRoot = $ProjectRoot
            $failState.branchName = 'agent/' + $TaskId
            Write-AtomicJson -Path (Join-Path $TaskDirectory 'state.json') -Value $failState
        }
    }
}
if (-not $BridgeTest) {
    Ensure-BridgeLayout
    if ($Command -in @('doctor', 'run')) {
        Import-CodeArtsUserEnvironment
    }

    switch ($Command) {
        'bootstrap' {
            Write-Output "Bridge initialized: $BridgeRoot"
        }

        'doctor' {
            $cli = Find-CodeArtsCli
            $version = $null
            if ($cli) {
                $version = (& $cli --version 2>$null | Out-String).Trim()
            }
            $auth = [ordered]@{
                CODEARTS_CLI_AK = [bool](Test-Path Env:CODEARTS_CLI_AK)
                CODEARTS_CLI_SK = [bool](Test-Path Env:CODEARTS_CLI_SK)
            }
            $workersSummary = $null
            $wreg = Get-WorkersRegistry
            if ($wreg) {
                $workersSummary = @($wreg.workers | ForEach-Object { [pscustomobject]@{ id = $_.id; transport = $_.transport; enabled = [bool]$_.enabled; model = [string]$_.model } })
            }
            $permissionCheck = $null
            $permPath = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codeartsdoer\codearts-data\storage\permission\global.json'
            if (Test-Path -LiteralPath $permPath -PathType Leaf) {
                $permRules = Get-Content -LiteralPath $permPath -Raw | ConvertFrom-Json
                $permBlocking = @($permRules | Where-Object { $_.permission -in @('edit', 'write', 'external_directory_write', 'dotfile') -and $_.action -ne 'allow' } | ForEach-Object { [pscustomobject]@{ permission = [string]$_.permission; action = [string]$_.action } })
                $permissionCheck = [pscustomobject]@{ path = $permPath; ok = ($permBlocking.Count -eq 0); blocking = $permBlocking }
            } else {
                $permissionCheck = [pscustomobject]@{ path = $permPath; ok = $false; missing = $true; blocking = @() }
            }
            [pscustomobject]@{
                bridgeRoot = $BridgeRoot
                codeartsCli = $cli
                codeartsVersion = $version
                ssh = (Get-Command ssh -ErrorAction SilentlyContinue).Path
                scp = (Get-Command scp -ErrorAction SilentlyContinue).Path
                authorizationVariablesPresent = $auth
                workers = $workersSummary
                permissions = $permissionCheck
                paused = Test-Path -LiteralPath $PausePath
            } | ConvertTo-Json -Depth 5
        }

        'register' {
            if ([string]::IsNullOrWhiteSpace($ProjectId) -or [string]::IsNullOrWhiteSpace($ProjectRoot)) {
                throw 'register requires -ProjectId and -ProjectRoot'
            }
            Assert-SafeId -Value $ProjectId -Label 'ProjectId'
            Assert-RequiredModel -Model $Model
            if ($Transport -in @('local', 'remote-worktree')) {
                $ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
                if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) { throw "Local project directory does not exist: $ProjectRoot" }
            }
            if ($Transport -ne 'local') {
                if ([string]::IsNullOrWhiteSpace($SshHost)) { throw 'SSH project requires -SshHost' }
            }
            $registry = Get-Registry
            $effectiveMode = if ($RunMode) { $RunMode } else { [string]$registry.defaults.runMode }
            if ($effectiveMode -notin @('auto', 'manual', 'sandbox')) { throw "Invalid runMode: $effectiveMode" }
            $effectiveTimeout = if ($TimeoutMinutes -gt 0) { $TimeoutMinutes } else { [int]$registry.defaults.timeoutMinutes }
            $effectiveModel = if ($Model) { $Model } elseif ($registry.defaults.PSObject.Properties.Name -contains 'model') { [string]$registry.defaults.model } else { $script:RequiredModel }
            Assert-RequiredModel -Model $effectiveModel
            $project = [ordered]@{
                id = $ProjectId
                transport = $Transport
                projectRoot = $ProjectRoot
                runMode = $effectiveMode
                model = $effectiveModel
                timeoutMinutes = $effectiveTimeout
            }
            if ($Transport -in @('ssh', 'ssh-shell', 'remote-worktree')) {
                $project.sshHost = $SshHost
            }
            if ($Transport -eq 'ssh') {
                $project.remoteBridgeRoot = $RemoteBridgeRoot
                if (-not [string]::IsNullOrWhiteSpace($RemoteCliPath)) { $project.remoteCliPath = $RemoteCliPath }
            }
            if ($Transport -eq 'remote-worktree') {
                if ([string]::IsNullOrWhiteSpace($RemoteWorkspaceRoot)) { throw 'remote-worktree project requires -RemoteWorkspaceRoot' }
                $project.remoteWorkspaceRoot = $RemoteWorkspaceRoot
                if (-not [string]::IsNullOrWhiteSpace($RemoteCliPath)) { $project.remoteCliPath = $RemoteCliPath }
            }
            $others = @($registry.projects | Where-Object { $_.id -ne $ProjectId })
            $registry.projects = @($others) + @([pscustomobject]$project)
            Write-AtomicJson -Path $RegistryPath -Value $registry
            [pscustomobject]$project | ConvertTo-Json -Depth 5
        }
        'create' {
            if ([string]::IsNullOrWhiteSpace($TaskFile)) {
                throw 'create requires -TaskFile'
            }
            $parentMeta = $null
            $parentState = $null
            if (-not [string]::IsNullOrWhiteSpace($ParentTaskId)) {
                Assert-SafeId -Value $ParentTaskId -Label 'ParentTaskId'
                $parentDirectory = Get-TaskDirectory -Id $ParentTaskId
                $parentMeta = Read-JsonFile -Path (Join-Path $parentDirectory 'META.json')
                $parentState = Get-State -Directory $parentDirectory
                if ([string]$parentState.status -notin @('SPLIT_REQUIRED', 'ASSISTANCE_REQUIRED')) {
                    throw "Parent task must require a split or assistance, current status: $($parentState.status)"
                }
                if ([string]::IsNullOrWhiteSpace($ProjectId)) { $ProjectId = [string]$parentMeta.projectId }
                if ([string]::IsNullOrWhiteSpace($Baseline) -and $parentState.PSObject.Properties.Name -contains 'checkpointCommitSha') { $Baseline = [string]$parentState.checkpointCommitSha }
            }
            if ([string]::IsNullOrWhiteSpace($ProjectId)) {
                throw 'create requires -ProjectId unless -ParentTaskId supplies it'
            }
            $project = Get-Project -Id $ProjectId
            if (-not (Test-Path -LiteralPath $TaskFile -PathType Leaf)) { throw "Task file not found: $TaskFile" }
            $taskText = [System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $TaskFile))
            if ($taskText -match '[^\x09\x0A\x0D\x20-\x7E]') { throw 'Worker task files must use plain English ASCII.' }
            $budget = Get-TaskBudget -TaskKind $TaskKind -TargetMinutes $TargetMinutes -SoftTimeoutMinutes $SoftTimeoutMinutes -HardTimeoutMinutes $TimeoutMinutes -MaxAttempts $MaxAttempts
            $envelope = Test-TaskEnvelope -TaskText $taskText -Budget $budget
            if (-not $envelope.Valid) { throw ('Task rejected by timeout policy: ' + ($envelope.Issues -join ' ')) }
            if (-not $TaskId) { $TaskId = ([DateTimeOffset]::Now.ToString('yyyyMMdd-HHmmss') + '-' + $ProjectId) }
            Assert-SafeId -Value $TaskId -Label 'TaskId'
            $taskDirectory = Get-TaskDirectory -Id $TaskId
            if (Test-Path -LiteralPath $taskDirectory) { throw "Task already exists: $TaskId" }
            foreach ($sub in @('inbox', 'outbox', 'evidence')) { [System.IO.Directory]::CreateDirectory((Join-Path $taskDirectory $sub)) | Out-Null }
            $effectiveMode = if ($RunMode) { $RunMode } else { [string]$project.runMode }
            if ($effectiveMode -notin @('auto', 'manual', 'sandbox')) { throw "Invalid runMode: $effectiveMode" }
            if (-not [string]::IsNullOrWhiteSpace($WorkerId)) { Assert-SafeId -Value $WorkerId -Label 'WorkerId' }
            if ($DependsOn) { foreach ($d in $DependsOn) { Assert-SafeId -Value $d -Label 'DependsOn' } }
            $meta = [ordered]@{
                schemaVersion = 1
                taskId = $TaskId
                projectId = $ProjectId
                createdAt = [DateTimeOffset]::Now.ToString('o')
                runMode = $effectiveMode
                baseline = if ($Baseline) { $Baseline } else { $null }
                allowedPaths = @([string]$project.projectRoot)
                workerId = if (-not [string]::IsNullOrWhiteSpace($WorkerId)) { $WorkerId } else { $null }
                timeoutPolicyVersion = $budget.PolicyVersion
                taskKind = $budget.TaskKind
                targetMinutes = $budget.TargetMinutes
                softTimeoutMinutes = $budget.SoftTimeoutMinutes
                hardTimeoutMinutes = $budget.HardTimeoutMinutes
                maxAttempts = $budget.MaxAttempts
                failureDomains = @($envelope.FailureDomains)
            }
            if (-not [string]::IsNullOrWhiteSpace($ParentTaskId)) { $meta.parentTaskId = $ParentTaskId }
            if (-not [string]::IsNullOrWhiteSpace($Role)) { $meta.role = $Role }
            if ($DependsOn) { $meta.dependsOn = @($DependsOn) }
            if (-not [string]::IsNullOrWhiteSpace($WorkspaceMode)) { $meta.workspaceMode = $WorkspaceMode }
            Write-AtomicJson -Path (Join-Path $taskDirectory 'META.json') -Value $meta
            Write-AtomicText -Path (Join-Path $taskDirectory 'inbox\001-TASK.md') -Content $taskText
            Set-State -Directory $taskDirectory -Status 'READY' -Message 'Task published' | Out-Null
            Write-Output $TaskId
        }
        'run' {
            if (-not $TaskId) { throw 'run requires -TaskId' }
            if (Test-Path -LiteralPath $PausePath) { throw 'Bridge is paused; run resume before dispatch.' }
            $taskDirectory = Get-TaskDirectory -Id $TaskId
            $meta = Read-JsonFile -Path (Join-Path $taskDirectory 'META.json')
            $project = Get-Project -Id $meta.projectId
            $state = Get-State -Directory $taskDirectory
            if ($state.status -notin @('READY', 'QUEUED', 'FIX_REQUIRED', 'BLOCKED', 'FAILED', 'AUTH_REQUIRED', 'RETRYABLE')) {
                throw "Current status cannot run: $($state.status)"
            }
            $existingSessionId = if ($state.PSObject.Properties.Name -contains 'sessionId') { [string]$state.sessionId } else { $null }
            $lease = Read-Lease -TaskId $TaskId
            $workerId = if ($lease -and $lease.PSObject.Properties.Name -contains 'workerId' -and -not [string]::IsNullOrWhiteSpace([string]$lease.workerId)) { [string]$lease.workerId } elseif ($meta.PSObject.Properties.Name -contains 'workerId' -and -not [string]::IsNullOrWhiteSpace([string]$meta.workerId)) { [string]$meta.workerId } else { $null }
            $worker = if ($workerId) { Get-Worker -Id $workerId } else { $null }
            $modelValue = if ($worker) { [string]$worker.model } elseif ($project.PSObject.Properties.Name -contains 'model' -and -not [string]::IsNullOrWhiteSpace([string]$project.model)) { [string]$project.model } else { $script:RequiredModel }
            Assert-RequiredModel -Model $modelValue
            $ws = Resolve-TaskWorkspace -Meta $meta -Project $project -Lease $lease -TaskId $TaskId
            $workingDir = $ws.workingDir
            $worktreePath = $ws.worktreePath
            $workspaceMode = $ws.workspaceMode
            $role = $ws.role
            if (-not $lease) {
                $leaseBaselineSha = if ($ws.PSObject.Properties.Name -contains 'baselineSha' -and -not [string]::IsNullOrWhiteSpace([string]$ws.baselineSha)) { [string]$ws.baselineSha } else { [string]$meta.baseline }
            $leaseBranchName = if ($ws.PSObject.Properties.Name -contains 'branchName' -and -not [string]::IsNullOrWhiteSpace([string]$ws.branchName)) { [string]$ws.branchName } else { 'agent/' + $TaskId }
            $newLease = [ordered]@{ taskId=$TaskId; workerId=$workerId; projectId=[string]$meta.projectId; projectRoot=[string]$project.projectRoot; workingDir=$workingDir; worktreePath=$worktreePath; workspaceMode=$workspaceMode; role=$role; baselineSha=$leaseBaselineSha; branchName=$leaseBranchName; acquiredAt=[DateTimeOffset]::Now.ToString('o'); processId=$PID; processStartTime=[DateTimeOffset]::Now.ToString('o') }
                Write-Lease -Lease $newLease
            } elseif ([string]::IsNullOrWhiteSpace([string]$lease.workingDir)) {
                $lease.workingDir = $workingDir
                $lease.worktreePath = $worktreePath
                Write-Lease -Lease $lease
            }
            $lockPath = Join-Path $LocksRoot ($meta.projectId + '.lock')
            $lockStream = $null
            $workdirLockStream = $null
            $needProjectLock = ($workspaceMode -eq 'existing')
            $needWorkdirLock = ($role -eq 'implement' -or $workspaceMode -eq 'existing' -or $workspaceMode -eq 'worktree')
            if ($needWorkdirLock) {
                $transportForLock = [string]$project.transport
                $hostForLock = if ($worker -and $worker.PSObject.Properties.Name -contains 'host' -and -not [string]::IsNullOrWhiteSpace([string]$worker.host)) { [string]$worker.host } else { $null }
                $lockKey = if ($transportForLock -in @('ssh', 'remote-worktree') -and $hostForLock) { ($hostForLock + '|' + $workingDir) } else { $workingDir }
                $wdLockPath = Get-WorkDirLockPath -WorkingDir $lockKey
                $workdirLockStream = [System.IO.File]::Open($wdLockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
            }
            $autoClose = $false
            try {
                if ($needProjectLock) {
                    $lockStream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
                }
                $attempt = [int]$state.attempt + 1
                Archive-PreviousOutbox -TaskDirectory $taskDirectory -Attempt $attempt
                $state.attempt = $attempt
                $state.status = 'STARTING'
                $state.updatedAt = [DateTimeOffset]::Now.ToString('o')
                $state.message = 'Acquired project lock, starting worker'
                Write-AtomicJson -Path (Join-Path $taskDirectory 'state.json') -Value $state

                $mode = if ($RunMode) { $RunMode } else { [string]$meta.runMode }
                if ($mode -notin @('auto', 'manual', 'sandbox')) { throw "Invalid runMode: $mode" }
                $hardFromMeta = if ($meta.PSObject.Properties.Name -contains 'hardTimeoutMinutes' -and $meta.hardTimeoutMinutes -gt 0) { [int]$meta.hardTimeoutMinutes } else { 0 }
                $softFromMeta = if ($meta.PSObject.Properties.Name -contains 'softTimeoutMinutes' -and $meta.softTimeoutMinutes -gt 0) { [int]$meta.softTimeoutMinutes } else { 0 }
                $minutes = if ($TimeoutMinutes -gt 0) { $TimeoutMinutes } elseif ($hardFromMeta -gt 0) { $hardFromMeta } else { [int]$project.timeoutMinutes }
                $softTimeoutSeconds = if ($SoftTimeoutMinutes -gt 0) { $SoftTimeoutMinutes * 60 } elseif ($softFromMeta -gt 0) { $softFromMeta * 60 } elseif ($minutes -gt 0) { [int]($minutes * 60 * 2 / 3) } else { 0 }
                $logPrefix = Join-Path $LogsRoot ("$TaskId.attempt-{0:D3}" -f $attempt)
                $transport = [string]$project.transport
                if ($transport -eq 'local') {
                    $result = Invoke-LocalWorker -Project $project -Worker $worker -WorkingDir $workingDir -TaskDirectory $taskDirectory -Mode $mode -TimeoutSeconds ($minutes * 60) -SoftTimeoutSeconds $softTimeoutSeconds -LogPrefix $logPrefix -SessionId $existingSessionId -TaskId $TaskId -Attempt $attempt
                } elseif ($transport -eq 'ssh-shell') {
                    $result = Invoke-SshShellWorker -Project $project -Worker $worker -WorkingDir $workingDir -TaskDirectory $taskDirectory -Mode $mode -TimeoutSeconds ($minutes * 60) -SoftTimeoutSeconds $softTimeoutSeconds -LogPrefix $logPrefix -SessionId $existingSessionId -TaskId $TaskId -Attempt $attempt
                } elseif ($transport -eq 'ssh') {
                    $result = Invoke-SshWorker -Project $project -Worker $worker -WorkingDir $workingDir -TaskDirectory $taskDirectory -Mode $mode -TimeoutSeconds ($minutes * 60) -SoftTimeoutSeconds $softTimeoutSeconds -LogPrefix $logPrefix -SessionId $existingSessionId -TaskId $TaskId -Attempt $attempt
                } elseif ($transport -eq 'remote-worktree') {
                    $result = Invoke-RemoteWorktreeWorker -Project $project -Worker $worker -WorkingDir $workingDir -TaskDirectory $taskDirectory -Mode $mode -TimeoutSeconds ($minutes * 60) -SoftTimeoutSeconds $softTimeoutSeconds -LogPrefix $logPrefix -SessionId $existingSessionId -TaskId $TaskId -Baseline ([string]$meta.baseline) -Attempt $attempt
                } else {
                    throw "Unsupported transport: $transport"
                }
                $resolvedBaseline = if ($ws.PSObject.Properties.Name -contains 'baselineSha' -and -not [string]::IsNullOrWhiteSpace([string]$ws.baselineSha)) { [string]$ws.baselineSha } else { [string]$meta.baseline }
                Complete-WorkerRun -TaskDirectory $taskDirectory -Result $result -ExistingSessionId $existingSessionId -WorktreePath $worktreePath -ProjectRoot ([string]$project.projectRoot) -TaskId $TaskId -WorkerId $workerId -Baseline $resolvedBaseline
                $finalState = Get-State -Directory $taskDirectory
                $finalState | ConvertTo-Json -Depth 5
                if (-not $Quiet -and -not [Console]::IsInputRedirected) {
                    $logPath = $logPrefix + '.stdout.log'
                    $outboxDir = Join-Path $taskDirectory 'outbox'
                    $outboxHasFiles = (Test-Path -LiteralPath $outboxDir -PathType Container) -and $null -ne (Get-ChildItem -LiteralPath $outboxDir -File -ErrorAction SilentlyContinue | Select-Object -First 1)
                    if ($finalState.status -eq 'REVIEW_REQUIRED') {
                        Write-Output ''
                        if (-not $outboxHasFiles) {
                            Write-Output 'outbox is empty, no results to display'
                        } else {
                            Write-Output (Get-OutboxSummaryText -TaskDirectory $taskDirectory)
                        }
                        Write-Output "Worker status: $($finalState.status). Log: $logPath"
                        Write-Output 'Window will close automatically in 10 seconds...'
                        $autoClose = $true
                    } elseif ($finalState.status -in @('FAILED','BLOCKED','AUTH_REQUIRED','RETRYABLE','CANCELLED')) {
                        Write-Output ''
                        if (-not $outboxHasFiles) {
                            Write-Output 'outbox is empty, no results to display'
                        } else {
                            Write-Output (Get-OutboxSummaryText -TaskDirectory $taskDirectory)
                        }
                        Write-Output "Worker status: $($finalState.status). Reason: $($finalState.message). Log: $logPath"
                        Write-Output 'Window will close automatically in 10 seconds...'
                        $autoClose = $true

                    }
                }
            } catch {
                Set-State -Directory $taskDirectory -Status 'FAILED' -Message $_.Exception.Message | Out-Null
                if ($TaskId) { Remove-Lease -TaskId $TaskId }
                if (-not [string]::IsNullOrWhiteSpace($worktreePath) -and (Test-Path -LiteralPath $worktreePath -PathType Container)) {
                    $recoveryState = ConvertTo-OrderedState (Get-State -Directory $taskDirectory)
                    $recoveryState.worktreePath = $worktreePath
                    $recoveryState.branchName = 'agent/' + $TaskId
                    $recoveryState.projectRoot = [string]$project.projectRoot
                    $recoveryBaseline = if ($ws.PSObject.Properties.Name -contains 'baselineSha' -and -not [string]::IsNullOrWhiteSpace([string]$ws.baselineSha)) { [string]$ws.baselineSha } else { [string]$meta.baseline }
                    if (-not [string]::IsNullOrWhiteSpace($recoveryBaseline)) { $recoveryState.baselineSha = $recoveryBaseline }
                    $recoveryState.recoveryReason = 'Preserved after exception: ' + $_.Exception.Message
                    Write-AtomicJson -Path (Join-Path $taskDirectory 'state.json') -Value $recoveryState
                }
                throw
            } finally {
                if ($lockStream) { $lockStream.Dispose() }
                if ($workdirLockStream) { $workdirLockStream.Dispose() }
            }
            if ($autoClose) { Start-Sleep -Seconds 10 }
        }
        'status' {
            if ($TaskId) {
                Get-State -Directory (Get-TaskDirectory -Id $TaskId) | ConvertTo-Json -Depth 5
            } else {
                $rows = foreach ($directory in @(Get-ChildItem -LiteralPath $TasksRoot -Directory -ErrorAction SilentlyContinue | Sort-Object Name)) {
                    $statePath = Join-Path $directory.FullName 'state.json'
                    if (Test-Path -LiteralPath $statePath) {
                        $state = Read-JsonFile -Path $statePath
                        [pscustomobject]@{ taskId = $state.taskId; status = $state.status; attempt = $state.attempt; updatedAt = $state.updatedAt }
                    }
                }
                $rows | Format-Table -AutoSize
            }
        }

        'pause' {
            Write-AtomicText -Path $PausePath -Content ([DateTimeOffset]::Now.ToString('o') + [Environment]::NewLine)
            Write-Output 'Bridge dispatch paused.'
        }

        'resume' {
            if ($TaskId) {
                $taskDirectory = Get-TaskDirectory -Id $TaskId
                $state = Get-State -Directory $taskDirectory
                if ($state.status -ne 'ASSISTANCE_REQUIRED') { throw "Only ASSISTANCE_REQUIRED can resume, current: $($state.status)" }
                $inbox = Join-Path $taskDirectory 'inbox'
                $guidanceFiles = @(Get-ChildItem -LiteralPath $inbox -File -Filter '*-GUIDANCE.md' -ErrorAction SilentlyContinue | Sort-Object Name)
                if ($guidanceFiles.Count -eq 0) { throw "No guidance files found in inbox for task $TaskId" }
                $state.status = 'READY'
                $state.updatedAt = [DateTimeOffset]::Now.ToString('o')
                $state.message = 'Resumed from ASSISTANCE_REQUIRED with guidance'
                Write-AtomicJson -Path (Join-Path $taskDirectory 'state.json') -Value $state
                Write-Output "Task $TaskId resumed with $($guidanceFiles.Count) guidance file(s). Run dispatch to continue."
            } else {
                if (Test-Path -LiteralPath $PausePath) { Remove-Item -LiteralPath $PausePath -Force }
                Write-Output 'Bridge dispatch resumed.'
            }
        }

        'cancel' {
            if (-not $TaskId) { throw 'cancel requires -TaskId' }
            $taskDirectory = Get-TaskDirectory -Id $TaskId
            if (-not (Test-Path -LiteralPath $taskDirectory -PathType Container)) { throw "Task not found: $TaskId" }
            Write-AtomicText -Path (Join-Path $taskDirectory 'CANCEL_REQUESTED') -Content ([DateTimeOffset]::Now.ToString('o') + [Environment]::NewLine)
            $state = Get-State -Directory $taskDirectory
            $lease = Read-Lease -TaskId $TaskId
            if ([string]$state.status -in @('QUEUED','STARTING','RUNNING') -and -not $lease) {
                Set-State -Directory $taskDirectory -Status 'CANCELLED' -Message 'Cancel closed orphaned task with no active runner lease' | Out-Null
                Write-Output "Cancelled orphaned task: $TaskId"
            } else {
                Write-Output "Cancel requested: $TaskId"
            }
        }

        'review-pass' {
            if (-not $TaskId) { throw 'review-pass requires -TaskId' }
            $taskDirectory = Get-TaskDirectory -Id $TaskId
            $state = Get-State -Directory $taskDirectory
            if ($state.status -ne 'REVIEW_REQUIRED') { throw "Only REVIEW_REQUIRED can pass, current: $($state.status)" }
            $inbox = Join-Path $taskDirectory 'inbox'
            $next = (@(Get-ChildItem -LiteralPath $inbox -File -Filter '*.md').Count + 1)
            Write-AtomicText -Path (Join-Path $inbox ("{0:D3}-PASS.md" -f $next)) -Content "# PASS`r`n`r`nImplementation meets task requirements.`r`n"
            Set-State -Directory $taskDirectory -Status 'DONE' -Message 'Architect ReviewPASS' | Out-Null
            Write-Output "PASS$TaskId"
        }

        'review-fix' {
            if (-not $TaskId -or -not $TaskFile) { throw 'review-fix requires -TaskId and -TaskFile' }
            $taskDirectory = Get-TaskDirectory -Id $TaskId
            $state = Get-State -Directory $taskDirectory
            if ($state.status -notin @('REVIEW_REQUIRED', 'BLOCKED', 'FAILED')) { throw "Current status cannot publish FIX: $($state.status)" }
            if (-not (Test-Path -LiteralPath $TaskFile -PathType Leaf)) { throw "FIX file not found: $TaskFile" }
            $inbox = Join-Path $taskDirectory 'inbox'
            $next = (@(Get-ChildItem -LiteralPath $inbox -File -Filter '*.md').Count + 1)
            Write-AtomicText -Path (Join-Path $inbox ("{0:D3}-FIX.md" -f $next)) -Content ([System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $TaskFile)))
            Set-State -Directory $taskDirectory -Status 'FIX_REQUIRED' -Message 'Architect published remediation requirement' | Out-Null
            Write-Output "FIX_REQUIRED$TaskId"
        }
        'worker-register' {
            if (-not $WorkerId) { throw 'worker-register requires -WorkerId' }
            if (-not $Transport) { throw 'worker-register requires -Transport' }
            if ($Transport -notin @('local','ssh','ssh-shell','remote-worktree')) { throw "Unsupported transport: $Transport" }
            Assert-RequiredModel -Model $script:RequiredModel
            $reg = Get-WorkersRegistry
            if (-not $reg) { $reg = [ordered]@{ schemaVersion=1; workers=@() } }
            $workers = @($reg.workers)
            if ($workers | Where-Object { $_.id -eq $WorkerId }) { throw "Worker already registered: $WorkerId" }
            $worker = [ordered]@{ id=$WorkerId; transport=$Transport; model=$script:RequiredModel; concurrencyLimit=if ($ConcurrencyLimit -gt 0) { $ConcurrencyLimit } else { 1 }; enabled=(-not $Disabled) }
            if ($WorkerHost) { $worker.host = $WorkerHost }
            if ($CliPath) { $worker.cliPath = $CliPath }
            if ($Capabilities) { $worker.capabilities = @($Capabilities -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
            $reg.workers = @($workers + $worker)
            Write-AtomicJson -Path $WorkersRegistryPath -Value $reg
            Write-Output "Registered worker: $WorkerId"
        }

        'worker-list' {
            $reg = Get-WorkersRegistry
            if (-not $reg -or -not $reg.workers) { Write-Output 'No workers registered.'; return }
            $reg.workers | ForEach-Object { [pscustomobject]@{ id=$_.id; transport=$_.transport; host=$_.host; model=$_.model; concurrencyLimit=$_.concurrencyLimit; enabled=$_.enabled; capabilities=$($_.capabilities -join ','); cliPathPresent=[bool]$_.cliPath } } | Format-Table -AutoSize
        }
        'worker-health' {
            $reg = Get-WorkersRegistry
            if (-not $reg -or -not $reg.workers) { Write-Output 'No workers registered.'; return }
            $healthResults = @()
            foreach ($w in @($reg.workers)) {
                $sshReachable = $false; $cliPathPresent = $false; $cliVersion = $null; $authPresent = $false
                if ($w.transport -eq 'local') {
                    $cli = Find-CodeArtsCli
                    $cliPathPresent = [bool]$cli
                    if ($cli) { try { $cliVersion = (& $cli --version 2>$null | Out-String).Trim() } catch { $cliVersion = $null } }
                    $sshReachable = $true
                } else {
                    $hostName = [string]$w.host
                    if ($hostName) { try { & ssh -o BatchMode=yes -o ConnectTimeout=5 $hostName 'true' 2>$null | Out-Null; $sshReachable = ($LASTEXITCODE -eq 0) } catch { $sshReachable = $false } }
                    $cliPath = [string]$w.cliPath
                    $cliPathPresent = -not [string]::IsNullOrWhiteSpace($cliPath)
                }
                $authPresent = [bool](Test-Path Env:CODEARTS_CLI_AK) -and [bool](Test-Path Env:CODEARTS_CLI_SK)
                $healthResults += [pscustomobject]@{ id=$w.id; transport=$w.transport; sshReachable=$sshReachable; cliPathPresent=$cliPathPresent; cliVersion=$cliVersion; authorizationVariablesPresent=$authPresent; enabled=$w.enabled }
            }
            $healthResults | Format-Table -AutoSize
        }

        'create-multi' {
            if (-not $SpecFile) { throw 'create-multi requires -SpecFile' }
            if (-not (Test-Path -LiteralPath $SpecFile -PathType Leaf)) { throw "Spec file not found: $SpecFile" }
            $spec = Read-JsonFile -Path $SpecFile
            $tasks = @($spec.tasks)
            if ($tasks.Count -eq 0) { throw 'Spec file contains no tasks' }
            $created = @()
            foreach ($t in $tasks) {
                $tid = [string]$t.taskId
                $pid = [string]$t.projectId
                $tDir = Join-Path $TasksRoot $tid
                [System.IO.Directory]::CreateDirectory($tDir) | Out-Null
                $meta = [ordered]@{ schemaVersion=1; taskId=$tid; projectId=$pid; runMode=if ($t.runMode) { [string]$t.runMode } else { 'auto' }; baseline=$t.baseline; allowedPaths=@() }
                if ($t.workerId) { $meta.workerId = [string]$t.workerId }
                if ($t.role) { $meta.role = [string]$t.role }
                if ($t.dependsOn) { $meta.dependsOn = @($t.dependsOn) }
                if ($t.workspaceMode) { $meta.workspaceMode = [string]$t.workspaceMode }
                Write-AtomicJson -Path (Join-Path $tDir 'META.json') -Value $meta
                $state = [ordered]@{ schemaVersion=1; taskId=$tid; status='READY'; attempt=0; updatedAt=[DateTimeOffset]::Now.ToString('o'); message='Created by create-multi'; processId=$null; exitCode=$null }
                Write-AtomicJson -Path (Join-Path $tDir 'state.json') -Value $state
                $created += $tid
            }
            Write-Output "Created $($created.Count) tasks: $($created -join ', ')"
        }
        'capture' {
            if (-not $TaskId) { throw 'capture requires -TaskId' }
            $taskDir = Get-TaskDirectory -Id $TaskId
            $state = ConvertTo-OrderedState (Get-State -Directory $taskDir)
            $lease = Read-Lease -TaskId $TaskId
            $wtPath = if ($lease -and $lease.PSObject.Properties.Name -contains 'worktreePath' -and -not [string]::IsNullOrWhiteSpace([string]$lease.worktreePath)) { [string]$lease.worktreePath } elseif ($state -and (Test-MapKey -Map $state -Key 'worktreePath') -and -not [string]::IsNullOrWhiteSpace([string](Get-MapValue -Map $state -Key 'worktreePath'))) { [string](Get-MapValue -Map $state -Key 'worktreePath') } else { $null }
            if (-not $wtPath -or -not (Test-Path -LiteralPath $wtPath -PathType Container)) { throw "No worktree found for task $TaskId" }
            $workerId = if ($lease -and $lease.PSObject.Properties.Name -contains 'workerId') { [string]$lease.workerId } else { $null }
            $meta = Read-JsonFile -Path (Join-Path $taskDir 'META.json')
            $baselineSha = if ((Test-MapKey -Map $state -Key 'baselineSha') -and -not [string]::IsNullOrWhiteSpace([string](Get-MapValue -Map $state -Key 'baselineSha'))) { [string](Get-MapValue -Map $state -Key 'baselineSha') } elseif ($meta -and $meta.PSObject.Properties.Name -contains 'baseline') { [string]$meta.baseline } else { $null }
            $capturedSha = Capture-WorkerCommit -WorktreePath $wtPath -TaskId $TaskId -WorkerId $workerId -Baseline $baselineSha
            if ($capturedSha) {
                $state['commitSha'] = $capturedSha
                if ($baselineSha) { $state['baselineSha'] = $baselineSha }
                Write-AtomicJson -Path (Join-Path $taskDir 'state.json') -Value $state
                Write-Output "Captured commit $capturedSha for task $TaskId in worktree $wtPath"
            } else {
                throw "Failed to capture commit for task $TaskId"
            }
        }
        'integration-check' {
            if (-not $TaskId) { throw 'integration-check requires -TaskId' }
            $taskDir = Get-TaskDirectory -Id $TaskId
            $state = ConvertTo-OrderedState (Get-State -Directory $taskDir)
            $lease = Read-Lease -TaskId $TaskId
            $wtPath = if ($lease -and $lease.PSObject.Properties.Name -contains 'worktreePath' -and -not [string]::IsNullOrWhiteSpace([string]$lease.worktreePath)) { [string]$lease.worktreePath } elseif ($state -and (Test-MapKey -Map $state -Key 'worktreePath') -and -not [string]::IsNullOrWhiteSpace([string](Get-MapValue -Map $state -Key 'worktreePath'))) { [string](Get-MapValue -Map $state -Key 'worktreePath') } else { $null }
            if (-not $wtPath -or -not (Test-Path -LiteralPath $wtPath -PathType Container)) { throw "No worktree found for task $TaskId" }
            $meta = Read-JsonFile -Path (Join-Path $taskDir 'META.json')
            $baselineRef = if ($Baseline) { $Baseline } elseif ((Test-MapKey -Map $state -Key 'baselineSha') -and -not [string]::IsNullOrWhiteSpace([string](Get-MapValue -Map $state -Key 'baselineSha'))) { [string](Get-MapValue -Map $state -Key 'baselineSha') } elseif ($meta -and $meta.PSObject.Properties.Name -contains 'baseline') { [string]$meta.baseline } else { throw 'integration-check requires baseline: provide -Baseline or ensure state.baselineSha is set' }
            if ([string]::IsNullOrWhiteSpace($TargetRef)) { throw 'integration-check requires -TargetRef' }
            $baseResolve = (& git -C $wtPath rev-parse $baselineRef 2>$null | Out-String).Trim()
            if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($baseResolve)) { throw 'Cannot resolve baseline ref' }
            $targetResolve = (& git -C $wtPath rev-parse $TargetRef 2>$null | Out-String).Trim()
            if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($targetResolve)) { throw 'Cannot resolve target ref' }
            $result = Test-IntegrationReady -WorktreePath $wtPath -BaselineRef $baselineRef -TargetRef $TargetRef
            $result | ConvertTo-Json -Depth 5
        }
        'cleanup' {
            if (-not $TaskId) { throw 'cleanup requires -TaskId' }
            $taskDir = Get-TaskDirectory -Id $TaskId
            $state = ConvertTo-OrderedState (Get-State -Directory $taskDir)
            if ([string]$state.status -notin @('DONE','PASS')) { throw "cleanup only allowed for DONE/PASS, current: $($state.status)" }
            $wtPath = if ((Test-MapKey -Map $state -Key 'worktreePath') -and -not [string]::IsNullOrWhiteSpace([string](Get-MapValue -Map $state -Key 'worktreePath'))) { [string](Get-MapValue -Map $state -Key 'worktreePath') } else { $null }
            if (-not $wtPath -or -not (Test-Path -LiteralPath $wtPath -PathType Container)) { throw "No worktree found for task $TaskId" }
            if (Get-GitIsDirty -Path $wtPath) { throw "Refusing to cleanup dirty worktree: $wtPath. Commit or discard changes first." }
            if (-not ((Test-MapKey -Map $state -Key 'commitSha') -and -not [string]::IsNullOrWhiteSpace([string](Get-MapValue -Map $state -Key 'commitSha')))) { throw "Refusing to cleanup uncaptured worktree. Run capture first." }
            $branchName = if ((Test-MapKey -Map $state -Key 'branchName')) { [string](Get-MapValue -Map $state -Key 'branchName') } else { 'agent/' + $TaskId }
            $proot = if ((Test-MapKey -Map $state -Key 'projectRoot') -and -not [string]::IsNullOrWhiteSpace([string](Get-MapValue -Map $state -Key 'projectRoot'))) { [string](Get-MapValue -Map $state -Key 'projectRoot') } else { throw 'cleanup requires projectRoot in state' }
            if (-not (Test-GitRepo -Path $proot)) { throw 'projectRoot is not a git repo' }
            $wtFull = [System.IO.Path]::GetFullPath($wtPath).TrimEnd([char]92, [char]47)
            $wtRootFull = [System.IO.Path]::GetFullPath($WorktreesRoot).TrimEnd([char]92, [char]47)
            $wtSep = [char]92
            if (-not ($wtFull -eq $wtRootFull -or $wtFull.StartsWith($wtRootFull + $wtSep) -or $wtFull.StartsWith($wtRootFull + [char]47))) { throw 'Worktree not under configured worktree root (boundary-safe check failed)' }
            $worktreeList = @(& git -C $proot worktree list --porcelain 2>&1)
            $wtRegistered = $false
            $wtFullNorm = $wtFull -replace [char]47, [char]92
            foreach ($line in $worktreeList) {
                if ($line -match '^worktree\s+(.+)$') {
                    $listedPath = $matches[1].Trim()
                    $listedNorm = $listedPath -replace [char]47, [char]92
                    if ([string]::Equals($listedNorm, $wtFullNorm, [System.StringComparison]::OrdinalIgnoreCase)) { $wtRegistered = $true; break }
                }
            }
            if (-not $wtRegistered) { throw 'Worktree path not found in git worktree list --porcelain' }
            & git -C $proot worktree remove $wtPath 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'git worktree remove failed' }
            $branchDeleted = $false
            & git -C $proot branch -d $branchName 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) { $branchDeleted = $true }
            if ($branchDeleted) {
                $state.status = 'DONE'
                $state.updatedAt = [DateTimeOffset]::Now.ToString('o')
                $state.message = 'Worktree cleaned up after review'
            } else {
                $state.status = 'DONE'
                $state.updatedAt = [DateTimeOffset]::Now.ToString('o')
                $state.message = 'Worktree removed but unmerged branch preserved: ' + $branchName
            }
            Write-AtomicJson -Path (Join-Path $taskDir 'state.json') -Value $state
            Write-Output "Cleaned up worktree for task $TaskId"
        }
        'dispatch' {
            if (Test-Path -LiteralPath $PausePath) { throw 'Bridge is paused; run resume before dispatch.' }
            if ($DryRun) {
                $dryPlan = Select-DispatchPlan -TasksRoot $TasksRoot -MaxWorkers $MaxWorkers
                [pscustomobject]@{
                    dryRun = $true
                    maxWorkers = $MaxWorkers
                    selected = @($dryPlan.plan | ForEach-Object { [pscustomobject]@{ taskId = $_.taskId; projectId = $_.projectId; workerId = $_.workerId; workingDir = $_.workingDir; workspaceMode = $_.workspaceMode; role = $_.role; status = $_.status } })
                    skipped = @($dryPlan.skipped | ForEach-Object { [pscustomobject]@{ taskId = $_.taskId; reason = $_.reason } })
                    active = @($dryPlan.active | ForEach-Object { [pscustomobject]@{ taskId = $_.taskId; status = $_.status } })
                } | ConvertTo-Json -Depth 5
                return
            }
            $dispatchLockPath = Join-Path $LocksRoot 'dispatcher.lock'
            $dispatchLockStream = $null
            $dispatched = @()
            $bridgeScript = $MyInvocation.MyCommand.Path
            $hostExe = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
            if (-not $hostExe -or -not (Test-Path -LiteralPath $hostExe -PathType Leaf)) {
                $pwshPath = Join-Path $PSHOME 'pwsh'
                if (Test-Path -LiteralPath $pwshPath -PathType Leaf) { $hostExe = $pwshPath }
            }
            $windowStyle = if ($Quiet) { 'Hidden' } else { 'Normal' }
            try {
                $dispatchLockStream = [System.IO.File]::Open($dispatchLockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
                Repair-StaleLeases
                Repair-StaleQueued
                $legacyCandidates = Get-DispatchCandidates -TasksRoot $TasksRoot -MaxWorkers $MaxWorkers
                $planResult = Select-DispatchPlan -TasksRoot $TasksRoot -MaxWorkers $MaxWorkers
                foreach ($candidate in $planResult.plan) {
                    $taskDirectory = $candidate.directory
                    $originalStatus = $candidate.status
                    $state = ConvertTo-OrderedState (Get-State -Directory $taskDirectory)
                    $lease = [ordered]@{ taskId=$candidate.taskId; workerId=$candidate.workerId; projectId=$candidate.projectId; projectRoot=$null; workingDir=$candidate.workingDir; worktreePath=$candidate.worktreePath; workspaceMode=$candidate.workspaceMode; role=$candidate.role; acquiredAt=[DateTimeOffset]::Now.ToString('o'); processId=$PID; processStartTime=[DateTimeOffset]::Now.ToString('o') }
                    try { $proj = Get-Project -Id $candidate.projectId; $lease.projectRoot = [string]$proj.projectRoot } catch { $lease.projectRoot = $null }
                    Write-Lease -Lease $lease
                    $state.status = 'QUEUED'
                    $state.updatedAt = [DateTimeOffset]::Now.ToString('o')
                    $state.message = 'Queued for dispatch'
                    Write-AtomicJson -Path (Join-Path $taskDirectory 'state.json') -Value $state
                    try {
                        $runnerArgs = @('-NoProfile', '-File', $bridgeScript, 'run', '-TaskId', $candidate.taskId)
                        if ($Quiet) { $runnerArgs += @('-Quiet') }
                        $startProcessArgs = @{
                            FilePath = $hostExe
                            ArgumentList = $runnerArgs
                            PassThru = $true
                        }
                        if ($IsWindows) { $startProcessArgs.WindowStyle = $windowStyle }
                        $proc = Start-Process @startProcessArgs
                        $lease.processId = $proc.Id
                        $lease.processStartTime = $proc.StartTime.ToUniversalTime().ToString('o')
                        Write-Lease -Lease $lease
                        $state.processId = $proc.Id
                        $state.processStartTime = $proc.StartTime.ToUniversalTime().ToString('o')
                        $state.updatedAt = [DateTimeOffset]::Now.ToString('o')
                        Write-AtomicJson -Path (Join-Path $taskDirectory 'state.json') -Value $state
$dispatched += [pscustomobject]@{ taskId = $candidate.taskId; projectId = $candidate.projectId; workerId = $candidate.workerId; pid = $proc.Id }
                    } catch {
                        $state.status = $originalStatus
                        $state.updatedAt = [DateTimeOffset]::Now.ToString('o')
                        $state.message = 'Dispatch start failed, rolled back: ' + $_.Exception.Message
                        Write-AtomicJson -Path (Join-Path $taskDirectory 'state.json') -Value $state
                        Remove-Lease -TaskId $candidate.taskId
                    }
                }
                $dispatchLog = Join-Path $DispatcherLogRoot ([DateTimeOffset]::Now.ToString('yyyyMMddHHmmss') + '.json')
                Write-AtomicJson -Path $dispatchLog -Value ([pscustomobject]@{ dispatched = $dispatched; maxWorkers = $MaxWorkers; timestamp = [DateTimeOffset]::Now.ToString('o'); hostExe = $hostExe; windowStyle = $windowStyle; skipped = @($planResult.skipped) })
            } finally {
                if ($dispatchLockStream) { $dispatchLockStream.Dispose() }
            }
            if ($dispatched.Count -gt 0) {
                $dispatched | ConvertTo-Json -Depth 5
            } else {
                Write-Output 'No dispatchable tasks.'
            }
        }

    }
}
