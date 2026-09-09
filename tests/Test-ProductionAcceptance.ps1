# Bridge v1.2 production acceptance checks.
# This suite never reads credential files or secret values.
[CmdletBinding()]
param([switch]$LiveRemote)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$requiredModel = 'huaweicloud-maas/GLM-5.2'

function Assert-True {
    param([Parameter(Mandatory)][string]$Label, [Parameter(Mandatory)][bool]$Condition)
    if (-not $Condition) { throw "FAIL: $Label" }
    Write-Output "PASS: $Label"
}

function Get-PropertyValue {
    param($Object, [Parameter(Mandatory)][string]$Name)
    if ($null -eq $Object) { return $null }
    if ($Object -is [System.Collections.IDictionary]) {
        if ($Object.Contains($Name)) { return $Object[$Name] }
        return $null
    }
    if ($Object.PSObject.Properties.Name -contains $Name) { return $Object.$Name }
    return $null
}

$sourceFiles = @(
    Get-ChildItem -LiteralPath (Join-Path $root 'scripts') -File -Recurse -ErrorAction Stop |
        Where-Object { $_.Extension -in @('.ps1', '.psm1') }
)
Assert-True 'PowerShell source files exist' ($sourceFiles.Count -gt 0)
foreach ($file in $sourceFiles) {
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$errors) | Out-Null
    Assert-True ("PowerShell parses: " + $file.Name) ($errors.Count -eq 0)
}

$runtimeFiles = @(
    Join-Path $root 'scripts\bridge.ps1'
    Join-Path $root 'scripts\Bridge.Policy.psm1'
    Join-Path $root 'scripts\bridge-daemon.ps1'
)
foreach ($path in $runtimeFiles) {
    Assert-True ("runtime source exists: " + [IO.Path]::GetFileName($path)) (Test-Path -LiteralPath $path -PathType Leaf)
    $source = [IO.File]::ReadAllText($path)
    Assert-True ("no unbounded ReadToEnd API: " + [IO.Path]::GetFileName($path)) ($source -notmatch '\.ReadToEnd(?:Async)?\s*\(')
}

$asciiFiles = @(
    Join-Path $root 'scripts\bridge.ps1'
    Join-Path $root 'scripts\bridge-daemon.ps1'
    Join-Path $root 'protocol\WORKER.md'
)
foreach ($path in $asciiFiles) {
    $text = [IO.File]::ReadAllText($path)
    Assert-True ("Worker-facing file is printable ASCII: " + [IO.Path]::GetFileName($path)) ($text -notmatch '[^\x09\x0A\x0D\x20-\x7E]')
}

$workersPath = Join-Path $root 'workers.json'
Assert-True 'workers registry exists' (Test-Path -LiteralPath $workersPath -PathType Leaf)
$workerRegistry = Get-Content -LiteralPath $workersPath -Raw | ConvertFrom-Json
$workers = @(Get-PropertyValue -Object $workerRegistry -Name 'workers')
Assert-True 'exactly three Workers registered' ($workers.Count -eq 3)
Assert-True 'all Workers use exact GLM-5.2 model' (@($workers | Where-Object { [string]$_.model -ne $requiredModel }).Count -eq 0)
Assert-True 'all Worker concurrency limits are positive' (@($workers | Where-Object { [int]$_.concurrencyLimit -lt 1 }).Count -eq 0)
$remoteWorkers = @($workers | Where-Object { [string]$_.transport -in @('ssh', 'ssh-shell') })
Assert-True 'two SSH Workers registered' ($remoteWorkers.Count -eq 2)
foreach ($worker in $remoteWorkers) {
    Assert-True ("remote Worker host is non-empty: " + [string]$worker.id) (-not [string]::IsNullOrWhiteSpace([string]$worker.host))
    Assert-True ("remote Worker CLI path is absolute: " + [string]$worker.id) ([string]$worker.cliPath -match '^/')
}

$projectsPath = Join-Path $root 'projects.json'
$projectsText = [IO.File]::ReadAllText($projectsPath)
Assert-True 'shipped project registry has no temporary Worker fixture paths' ($projectsText -notmatch '(?i)(/tmp/codex-glm-ma-|multiagent-20260908\\worker)')

$profilePath = Join-Path $root 'profiles\cloudsite.example.json'
$profile = Get-Content -LiteralPath $profilePath -Raw | ConvertFrom-Json
Assert-True 'CloudSite profile is critical' ([string]$profile.riskLevel -eq 'critical')
foreach ($phaseId in @('deploy', 'rollback')) {
    $phase = @($profile.phases | Where-Object { [string]$_.id -eq $phaseId })
    Assert-True ("CloudSite phase exists: $phaseId") ($phase.Count -eq 1)
    Assert-True ("CloudSite phase requires approval: $phaseId") ([bool]$phase[0].requiresApproval)
    Assert-True ("CloudSite phase has a dedicated approval gate: $phaseId") (-not [string]::IsNullOrWhiteSpace([string]$phase[0].approvalGate))
    $commandText = (@($phase[0].checks | ForEach-Object { @($_.command.argv) -join ' ' }) -join ' ')
    Assert-True ("CloudSite phase remains plan-only: $phaseId") ($commandText -match '(?i)plan only|no production mutation')
}
Assert-True 'CloudSite deploy and rollback use separate approval gates' (
    [string](@($profile.phases | Where-Object id -eq 'deploy')[0].approvalGate) -ne
    [string](@($profile.phases | Where-Object id -eq 'rollback')[0].approvalGate)
)

$smoke = @($profile.phases | Where-Object { [string]$_.id -eq 'docker-smoke' })
Assert-True 'CloudSite docker-smoke phase exists' ($smoke.Count -eq 1)
$finallyChecks = @(Get-PropertyValue -Object $smoke[0] -Name 'finallyChecks')
Assert-True 'docker-smoke has an unconditional cleanup check' ($finallyChecks.Count -gt 0)
$cleanupText = (@($finallyChecks | ForEach-Object { @($_.command.argv) -join ' ' }) -join ' ')
Assert-True 'docker-smoke cleanup runs compose down' ($cleanupText -match '(?i)compose.*down')
Assert-True 'docker-smoke cleanup never deletes volumes' ($cleanupText -notmatch '(^|\s)-v(\s|$)|--volumes')

$evidencePaths = @(
    foreach ($phase in @($profile.phases)) {
        foreach ($check in @($phase.checks)) {
            if ($check.PSObject.Properties.Name -contains 'requiredEvidence') { @($check.requiredEvidence) }
        }
    }
)
Assert-True 'CloudSite evidence never retains .env material' (@($evidencePaths | Where-Object { [string]$_ -match '(^|[\\/])\.env($|[\\/])' }).Count -eq 0)

$tracked = @(& git -C $root ls-files)
Assert-True 'Git index has no tracked environment file' (@($tracked | Where-Object { $_ -match '(^|/)\.env($|/)' }).Count -eq 0)
Assert-True 'Git index has no tracked credential fixture' (@($tracked | Where-Object {
    $_ -match '(?i)(^|/)(credentials?[^/]*\.(csv|json|txt)|remote-account[^/]*\.md|id_(rsa|ed25519)|[^/]*private[_-]?key[^/]*)$' -or
    $_ -match '(^|/)tests/\x8FDC\x7A0B\x8D26\x53F7\.md$'
}).Count -eq 0)

if ($LiveRemote) {
    foreach ($worker in $workers) {
        if ([string]$worker.transport -eq 'local') {
            $cli = [string]$worker.cliPath
            if ([string]::IsNullOrWhiteSpace($cli)) {
                $cmd = Get-Command codearts -ErrorAction SilentlyContinue
                if ($cmd) { $cli = $cmd.Path }
            }
            Assert-True ("local CLI exists: " + [string]$worker.id) (Test-Path -LiteralPath $cli -PathType Leaf)
            $version = (& $cli --version 2>$null | Out-String).Trim()
            Assert-True ("local CLI responds: " + [string]$worker.id) (-not [string]::IsNullOrWhiteSpace($version))
        } else {
            $hostName = [string]$worker.host
            $cliPath = [string]$worker.cliPath
            & ssh -o BatchMode=yes -o ConnectTimeout=8 $hostName "test -x '$cliPath'" 2>$null
            Assert-True ("remote CLI executable exists: " + [string]$worker.id) ($LASTEXITCODE -eq 0)
            $version = (& ssh -o BatchMode=yes -o ConnectTimeout=8 $hostName "'$cliPath' --version" 2>$null | Out-String).Trim()
            Assert-True ("remote CLI responds: " + [string]$worker.id) (-not [string]::IsNullOrWhiteSpace($version))
        }
    }
}

Write-Output 'PASS: Bridge v1.2 production acceptance checks completed.'
