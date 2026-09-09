# Test-Policy.ps1 - Tests for the Bridge.Policy profile engine.
# Plain PowerShell assertions (no Pester). ASCII only.
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$modulePath = Join-Path $root 'scripts\Bridge.Policy.psm1'
$schemaPath = Join-Path $root 'schemas\profile.schema.json'
$cloudsitePath = Join-Path $root 'profiles\cloudsite.example.json'
$genericPath = Join-Path $root 'profiles\generic.example.json'

foreach ($rel in @('schemas\profile.schema.json', 'scripts\Bridge.Policy.psm1', 'profiles\cloudsite.example.json', 'profiles\generic.example.json', 'protocol\PROFILE.md')) {
    $p = Join-Path $root $rel
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { throw "Missing required file: $rel" }
}

$tokens = $null; $errors = $null
[System.Management.Automation.Language.Parser]::ParseFile($modulePath, [ref]$tokens, [ref]$errors) | Out-Null
if ($errors.Count -gt 0) { throw 'Bridge.Policy.psm1 parse errors: ' + (($errors | ForEach-Object Message) -join '; ') }

$src = Get-Content -LiteralPath $modulePath -Raw
if ($src -imatch 'cloudsite') { throw 'Module source must not reference CloudSite (engine must be generic).' }

Import-Module $modulePath -Force

function Assert-True { param([string]$Label, [bool]$Cond) if (-not $Cond) { throw "ASSERT FAILED: $Label" } }
function Assert-False { param([string]$Label, [bool]$Cond) if ($Cond) { throw "ASSERT FAILED (expected false): $Label" } }
function Assert-Eq { param([string]$Label, $Expected, $Actual) if ($Expected -ne $Actual) { throw "ASSERT FAILED: $Label expected=$Expected actual=$Actual" } }
function Assert-Throws { param([string]$Label, [scriptblock]$Block) $t = $false; try { & $Block } catch { $t = $true }; Assert-True $Label $t }

Write-Output 'PASS: module parses, no CloudSite reference, imported.'

Assert-Eq 'policy version' 1 (Get-BridgePolicyVersion)
$schema = Get-Content -LiteralPath $schemaPath -Raw | ConvertFrom-Json
Assert-Eq 'schema title' 'Codex GLM Bridge Policy Profile' $schema.title
Write-Output 'PASS: version and schema metadata.'

$cs = Load-BridgeProfile -Path $cloudsitePath
$csRes = Test-BridgeProfile -Profile $cs
Assert-True 'cloudsite profile valid' $csRes.Valid
Assert-True 'cloudsite no issues' ($csRes.Issues.Count -eq 0)
$cloudsitePhaseIds = @($cs.phases | ForEach-Object { $_.id })
foreach ($requiredPhase in @('backend-test', 'frontend', 'compose-validate', 'docker-smoke', 'version-consistency', 'backup-verify', 'restore-drill', 'deploy', 'rollback')) {
    Assert-True "cloudsite phase $requiredPhase exists" ($cloudsitePhaseIds -contains $requiredPhase)
}
$cloudsiteFrontend = Get-BridgePhase -Profile $cs -PhaseId 'frontend'
$cloudsiteFrozen = @($cloudsiteFrontend.checks | Where-Object { $_.id -eq 'frozen-install' })[0]
Assert-True 'cloudsite frozen install uses pinned pnpm path' ($cloudsiteFrozen.command.executable -eq 'corepack' -and $cloudsiteFrozen.command.argv -contains '--frozen-lockfile')
$cloudsiteBackend = (Get-BridgePhase -Profile $cs -PhaseId 'backend-test').checks[0]
Assert-True 'cloudsite backend gate targets apps/api' ($cloudsiteBackend.command.workingDirectory -eq 'apps/api')
Assert-True 'cloudsite validates four compose layouts' ((Get-BridgePhase -Profile $cs -PhaseId 'compose-validate').checks.Count -eq 4)
$restoreEvidence = @((Get-BridgePhase -Profile $cs -PhaseId 'restore-drill').checks[0].requiredEvidence)
Assert-True 'cloudsite restore drill requires both sqlite databases' ($restoreEvidence -contains 'evidence/cloudsite/restore-drill/data/state.db' -and $restoreEvidence -contains 'evidence/cloudsite/restore-drill/data/index.db')

$gen = Load-BridgeProfile -Path $genericPath
$genRes = Test-BridgeProfile -Profile $gen
Assert-True 'generic profile valid' $genRes.Valid
Assert-True 'generic no issues' ($genRes.Issues.Count -eq 0)
Assert-True 'generic differs from cloudsite' ($gen.profileId -ne $cs.profileId)
$genPhaseIds = @($gen.phases | ForEach-Object { $_.id })
Assert-True 'generic has no deploy phase' ($genPhaseIds -notcontains 'deploy')
Write-Output 'PASS: both example profiles validate; engine is generic (non-CloudSite example passes).'

$frontendChecks = Select-BridgeGates -Profile $cs -PhaseId 'frontend' -Role 'developer'
Assert-True 'frontend gates count 4' ($frontendChecks.Count -eq 4)
$lintCheck = $frontendChecks[1]
$si = New-BridgeCheckStartInfo -Check $lintCheck -ProjectRoot 'C:/proj'
Assert-True 'executable is corepack' ($si.Executable -eq 'corepack')
Assert-True 'argv has pnpm' ($si.Argv -contains 'pnpm')
Assert-True 'argv has lint' ($si.Argv -contains 'lint')
Assert-True 'startinfo filename corepack' ($si.StartInfo.FileName -eq 'corepack')
Assert-True 'startinfo no shell execute' ($si.StartInfo.UseShellExecute -eq $false)
Assert-True 'startinfo redirects stdout' ($si.StartInfo.RedirectStandardOutput -eq $true)
Write-Output 'PASS: argv safety - StartInfo built from executable+argv, UseShellExecute false.'

$badCheck = [pscustomobject]@{ id = 'x'; command = 'rm -rf /' }
Assert-Throws 'string command rejected by New-BridgeCheckStartInfo' { New-BridgeCheckStartInfo -Check $badCheck }
$stringCmdProfile = [pscustomobject]@{ schemaVersion = 1; profileId = 'p'; projectId = 'p'; riskLevel = 'low'; roles = @('r'); phases = @([pscustomobject]@{ id = 'ph'; checks = @([pscustomobject]@{ id = 'c'; command = 'echo hi' }) }) }
$scRes = Test-BridgeProfile -Profile $stringCmdProfile
Assert-False 'string command invalid profile' $scRes.Valid
Assert-True 'string command issue mentions shell' (@($scRes.Issues | Where-Object { $_ -match 'shell command string' }).Count -ge 1)
Write-Output 'PASS: interpolated shell command string is rejected.'

Assert-True 'ci can run frontend gates' ((Select-BridgeGates -Profile $cs -PhaseId 'frontend' -Role 'ci').Count -eq 4)
Assert-True 'release-manager cannot run frontend gates' ((Select-BridgeGates -Profile $cs -PhaseId 'frontend' -Role 'release-manager').Count -eq 0)
Assert-True 'release-manager selects deploy gate' ((Select-BridgeGates -Profile $cs -PhaseId 'deploy' -Role 'release-manager').Count -eq 1)
Assert-True 'ci cannot select deploy gate' ((Select-BridgeGates -Profile $cs -PhaseId 'deploy' -Role 'ci').Count -eq 0)
Assert-True 'release-manager selects rollback gate' ((Select-BridgeGates -Profile $cs -PhaseId 'rollback' -Role 'release-manager').Count -eq 1)
Assert-Throws 'select throws on unknown phase' { Select-BridgeGates -Profile $cs -PhaseId 'nope' }
Assert-True 'Get-BridgePhase null for unknown' ($null -eq (Get-BridgePhase -Profile $cs -PhaseId 'nope'))
Write-Output 'PASS: role/phase selection filters by role and rejects unknown phase.'

$testCheck = (Select-BridgeGates -Profile $cs -PhaseId 'frontend' -Role 'ci')[3]
$evOk = Test-BridgeCheckResult -Check $testCheck -ExitCode 0 -EvidenceFiles @('apps/web/.next/BUILD_ID')
Assert-True 'evidence present passes' $evOk.Passed
$evMissing = Test-BridgeCheckResult -Check $testCheck -ExitCode 0 -EvidenceFiles @()
Assert-False 'missing evidence fails' $evMissing.Passed
Assert-True 'missing evidence listed' ($evMissing.MissingEvidence -contains 'apps/web/.next/BUILD_ID')
Write-Output 'PASS: required evidence evaluated correctly.'

$evBadExit = Test-BridgeCheckResult -Check $testCheck -ExitCode 1 -EvidenceFiles @('apps/web/.next/BUILD_ID')
Assert-False 'bad exit fails' $evBadExit.Passed
Assert-False 'bad exit exitOk false' $evBadExit.ExitOk
Assert-Eq 'expected exit code 0' 0 $evBadExit.ExpectedExitCode
$expectNonZero = [pscustomobject]@{ id = 'c'; command = [pscustomobject]@{ executable = 'x'; argv = @() }; expectExitCode = 2 }
$nz = Test-BridgeCheckResult -Check $expectNonZero -ExitCode 2
Assert-True 'custom expectExitCode passes' $nz.Passed
Write-Output 'PASS: exit code evaluation including custom expectExitCode.'

Assert-Eq 'default timeout 1800' 1800 (Get-BridgeTimeout -Profile $cs)
Assert-Eq 'deploy timeout 1800' 1800 (Get-BridgeTimeout -Profile $cs -PhaseId 'deploy')
Assert-Eq 'frontend timeout falls back to default' 1800 (Get-BridgeTimeout -Profile $cs -PhaseId 'frontend')
Assert-Eq 'generic default timeout 120' 120 (Get-BridgeTimeout -Profile $gen)
Write-Output 'PASS: timeout metadata resolves default/phase/check.'

$gate = Get-BridgeApprovalGate -Profile $cs -PhaseId 'deploy'
Assert-True 'deploy blocked by default' ($null -ne $gate -and $gate.Blocked)
Assert-Eq 'deploy gate name' 'cloudsite-deploy' $gate.Gate
$gateAfter = Get-BridgeApprovalGate -Profile $cs -PhaseId 'deploy' -ApprovedGates @('cloudsite-deploy')
Assert-True 'deploy unblocked after approval' ($null -eq $gateAfter)
$frontendGate = Get-BridgeApprovalGate -Profile $cs -PhaseId 'frontend'
Assert-True 'frontend has no approval gate' ($null -eq $frontendGate)
$rollbackGate = Get-BridgeApprovalGate -Profile $cs -PhaseId 'rollback'
Assert-True 'rollback blocked by default' ($null -ne $rollbackGate -and $rollbackGate.Blocked)
Assert-Eq 'rollback gate name' 'cloudsite-rollback' $rollbackGate.Gate
$genTestGate = Get-BridgeApprovalGate -Profile $gen -PhaseId 'test'
Assert-True 'generic test has no approval gate' ($null -eq $genTestGate)
Write-Output 'PASS: approval blocking - deploy blocked by default, unblocked after approval.'

$unknown = [pscustomobject]@{ schemaVersion = 1; profileId = 'p'; projectId = 'p'; riskLevel = 'low'; roles = @('r'); phases = @(); bogusField = 1 }
$uRes = Test-BridgeProfile -Profile $unknown
Assert-False 'unknown top-level field rejected' $uRes.Valid
Assert-True 'unknown field issue mentions bogusField' (@($uRes.Issues | Where-Object { $_ -match 'bogusField' }).Count -ge 1)
$phaseUnknown = [pscustomobject]@{ schemaVersion = 1; profileId = 'p'; projectId = 'p'; riskLevel = 'low'; roles = @('r'); phases = @([pscustomobject]@{ id = 'ph'; checks = @([pscustomobject]@{ id = 'c'; command = [pscustomobject]@{ executable = 'x'; argv = @() } }); extra = 1 }) }
$puRes = Test-BridgeProfile -Profile $phaseUnknown
Assert-False 'unknown phase field rejected' $puRes.Valid
Write-Output 'PASS: unknown fields rejected at profile and phase level.'

$secretVal = [pscustomobject]@{ schemaVersion = 1; profileId = 'p'; projectId = 'p'; riskLevel = 'low'; roles = @('r'); phases = @([pscustomobject]@{ id = 'ph'; checks = @([pscustomobject]@{ id = 'c'; command = [pscustomobject]@{ executable = 'x'; argv = @(); env = @([pscustomobject]@{ name = 'TOKEN'; value = 'super-secret' }) } }) }) }
$sRes = Test-BridgeProfile -Profile $secretVal
Assert-False 'secret value rejected' $sRes.Valid
Assert-True 'secret value issue forbidden' (@($sRes.Issues | Where-Object { $_ -match 'forbidden' }).Count -ge 1)
$secretNoRef = [pscustomobject]@{ schemaVersion = 1; profileId = 'p'; projectId = 'p'; riskLevel = 'low'; roles = @('r'); phases = @([pscustomobject]@{ id = 'ph'; checks = @([pscustomobject]@{ id = 'c'; command = [pscustomobject]@{ executable = 'x'; argv = @(); env = @([pscustomobject]@{ name = 'TOKEN'; from = 'secret' }) } }) }) }
$nrRes = Test-BridgeProfile -Profile $secretNoRef
Assert-False 'secret without secretRef rejected' $nrRes.Valid
Write-Output 'PASS: secret values and missing secretRef rejected.'

$composeChecks = Select-BridgeGates -Profile $cs -PhaseId 'compose-validate' -Role 'ci'
$traefikCheck = $composeChecks[1]
$bSI = New-BridgeCheckStartInfo -Check $traefikCheck -Environment @{ 'CLOUDSITE_DOMAIN' = 'cloud.example.com'; 'CI' = 'true' }
Assert-True 'allowlist resolved CLOUDSITE_DOMAIN' ($bSI.ResolvedEnv['CLOUDSITE_DOMAIN'] -eq 'cloud.example.com')
Assert-True 'allowlist excludes undeclared CI' (-not $bSI.ResolvedEnv.Contains('CI'))
Assert-True 'compose check has no secret refs' ($bSI.RequiredSecretRefs.Count -eq 0)
Assert-True 'compose allowlist has CLOUDSITE_DOMAIN' ($bSI.EnvAllowlist -contains 'CLOUDSITE_DOMAIN')

$deployCheck = (Select-BridgeGates -Profile $cs -PhaseId 'deploy' -Role 'release-manager')[0]
$dSI = New-BridgeCheckStartInfo -Check $deployCheck
$validSecretCheck = [pscustomobject]@{ id = 'secret-ref'; command = [pscustomobject]@{ executable = 'x'; argv = @(); env = @([pscustomobject]@{ name = 'DEPLOY_TOKEN'; from = 'secret'; secretRef = 'vault.cloudsite.deploy-token' }) } }
$secretSI = New-BridgeCheckStartInfo -Check $validSecretCheck -Environment @{ 'DEPLOY_TOKEN' = 'must-not-be-used' }
Assert-True 'secret ref recorded' ($secretSI.RequiredSecretRefs -contains 'vault.cloudsite.deploy-token')
Assert-True 'secret value is not inlined' (-not $secretSI.ResolvedEnv.Contains('DEPLOY_TOKEN'))
Write-Output 'PASS: allowlist env resolved from host; secret refs recorded, never inlined.'

$skipProfile = [pscustomobject]@{ schemaVersion = 1; profileId = 'p'; projectId = 'p'; riskLevel = 'low'; roles = @('r'); phases = @([pscustomobject]@{ id = 'ph'; checks = @([pscustomobject]@{ id = 'a'; command = [pscustomobject]@{ executable = 'x'; argv = @() } }, [pscustomobject]@{ id = 'b'; skip = $true; command = [pscustomobject]@{ executable = 'y'; argv = @() } }) }) }
Assert-True 'skip profile valid' (Test-BridgeProfile -Profile $skipProfile).Valid
$skipSelected = Select-BridgeGates -Profile $skipProfile -PhaseId 'ph'
Assert-True 'skipped check excluded' ($skipSelected.Count -eq 1 -and $skipSelected[0].id -eq 'a')

$dup = [pscustomobject]@{ schemaVersion = 1; profileId = 'p'; projectId = 'p'; riskLevel = 'low'; roles = @('r'); phases = @([pscustomobject]@{ id = 'ph'; checks = @([pscustomobject]@{ id = 'c'; command = [pscustomobject]@{ executable = 'x'; argv = @() } }) }, [pscustomobject]@{ id = 'ph'; checks = @([pscustomobject]@{ id = 'c'; command = [pscustomobject]@{ executable = 'y'; argv = @() } }) }) }
Assert-False 'duplicate phase id rejected' (Test-BridgeProfile -Profile $dup).Valid
Write-Output 'PASS: skip honored; duplicate phase ids rejected.'

Assert-Throws 'Assert-BridgeProfile throws on invalid' { Assert-BridgeProfile -Profile $unknown }
Assert-Throws 'Assert-BridgeProfile throws on null' { Assert-BridgeProfile -Profile $null }
Write-Output 'PASS: Assert-BridgeProfile throws on invalid input.'

$deployJoined = ($dSI.Argv -join '|')
Assert-True 'deploy argv contains Write-Output' ($deployJoined -match 'Write-Output')
Assert-True 'deploy argv contains plan only' ($deployJoined -match 'plan only')
Assert-True 'deploy argv contains no mutation' ($deployJoined -match 'no production mutation')
$rollbackCheck = (Select-BridgeGates -Profile $cs -PhaseId 'rollback' -Role 'release-manager')[0]
$rollbackSI = New-BridgeCheckStartInfo -Check $rollbackCheck
Assert-True 'rollback argv requires separate approval wording' (($rollbackSI.Argv -join '|') -match 'separate explicit approval')
Write-Output 'PASS: CloudSite deploy and rollback examples are approval-blocked and non-mutating.'

Write-Output 'PASS: Test-Policy.ps1 all tests passed.'
