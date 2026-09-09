# Bridge.Policy.psm1
# Project-agnostic policy/profile engine for the codex-glm Bridge v1.2.
# Pure, testable functions: load/validate a profile, select gates for a role/phase,
# safely construct process start information, evaluate exit codes and required evidence,
# and identify an unmet approval gate.
# No project-specific conditionals. No third-party dependencies. No network access.
# Commands are executable plus argv arrays; environment entries are allowlist names or
# secret references, never secret values.

Set-StrictMode -Version Latest

$script:SafeIdPattern = '^[a-z0-9][a-z0-9._-]*$'
$script:SafeRolePattern = '^[A-Za-z0-9_-]+$'
$script:SafeEnvNamePattern = '^[A-Za-z_][A-Za-z0-9_]*$'
$script:SafeSecretRefPattern = '^[A-Za-z0-9_.-]+$'
$script:SafeEvidencePattern = '^[A-Za-z0-9._/ -]+$'
$script:RiskLevels = @('low', 'medium', 'high', 'critical')
$script:OnFailureModes = @('block', 'continue', 'warn')
$script:WdModes = @('projectRoot', 'subpath', 'temp')

$script:AllowedProfileKeys = @('schemaVersion', 'profileId', 'projectId', 'description', 'riskLevel', 'roles', 'defaultTimeoutSeconds', 'workingDirectory', 'phases')
$script:AllowedPhaseKeys = @('id', 'description', 'roles', 'riskLevel', 'requiresApproval', 'approvalGate', 'timeoutSeconds', 'onFailure', 'checks', 'finallyChecks')
$script:AllowedCheckKeys = @('id', 'description', 'roles', 'riskLevel', 'timeoutSeconds', 'command', 'requiredEvidence', 'expectExitCode', 'skip')
$script:AllowedCommandKeys = @('executable', 'argv', 'env', 'workingDirectory')
$script:AllowedEnvEntryKeys = @('name', 'from', 'secretRef')
$script:AllowedWdKeys = @('mode', 'subpath')

function Get-BridgePolicyVersion { return 1 }

function Get-BridgeProp {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    if ($Object -is [System.Collections.IDictionary]) {
        if ($Object.Contains($Name)) { return $Object[$Name] }
        return $null
    }
    $p = $Object.PSObject.Properties[$Name]
    if ($null -ne $p) { return $p.Value }
    return $null
}

function Get-BridgeKeys {
    param($Object)
    if ($null -eq $Object) { return @() }
    if ($Object -is [System.Collections.IDictionary]) { return @($Object.Keys) }
    return @($Object.PSObject.Properties.Name)
}

function Test-BridgeUnknownKeys {
    param($Object, [string[]]$Allowed, [string]$Path, [System.Collections.Generic.List[string]]$Issues)
    if ($null -eq $Object) { return }
    foreach ($k in (Get-BridgeKeys -Object $Object)) {
        if ($Allowed -notcontains $k) {
            $null = $Issues.Add("Unknown field '$k' at $Path.")
        }
    }
}

function Test-BridgeRoleArray {
    param($Value, [string]$Path, [System.Collections.Generic.List[string]]$Issues, [bool]$Required)
    if ($null -eq $Value) {
        if ($Required) { $null = $Issues.Add("$Path is required.") }
        return $false
    }
    $arr = @($Value)
    if ($arr.Count -lt 1) {
        if ($Required) { $null = $Issues.Add("$Path must contain at least one role.") }
        return $false
    }
    $ok = $true
    foreach ($r in $arr) {
        if ([string]::IsNullOrWhiteSpace($r)) {
            $null = $Issues.Add("$Path contains an empty role."); $ok = $false
        } elseif ($r -cnotmatch $script:SafeRolePattern) {
            $null = $Issues.Add("$Path role '$r' does not match $($script:SafeRolePattern)."); $ok = $false
        }
    }
    return $ok
}

function Test-BridgeEnvEntry {
    param($Entry, [string]$Path, [System.Collections.Generic.List[string]]$Issues)
    if ($null -eq $Entry) { $null = $Issues.Add("$Path is null."); return }
    if ($Entry -is [string]) { $null = $Issues.Add("$Path must be an object, not a string."); return }
    Test-BridgeUnknownKeys -Object $Entry -Allowed $script:AllowedEnvEntryKeys -Path $Path -Issues $Issues
    foreach ($k in (Get-BridgeKeys -Object $Entry)) {
        if ($k -eq 'value' -or $k -eq 'secretValue' -or $k -eq 'literal' -or $k -eq 'inline') {
            $null = $Issues.Add("$Path.$k is forbidden: environment entries must not contain secret values.")
        }
    }
    $name = Get-BridgeProp -Object $Entry -Name 'name'
    if ([string]::IsNullOrWhiteSpace($name)) {
        $null = $Issues.Add("$Path.name is required.")
    } elseif ($name -cnotmatch $script:SafeEnvNamePattern) {
        $null = $Issues.Add("$Path.name '$name' does not match $($script:SafeEnvNamePattern).")
    }
    $from = Get-BridgeProp -Object $Entry -Name 'from'
    if ($null -ne $from -and $from -ne 'allowlist' -and $from -ne 'secret') {
        $null = $Issues.Add("$Path.from '$from' must be 'allowlist' or 'secret'.")
    }
    $secretRef = Get-BridgeProp -Object $Entry -Name 'secretRef'
    if ($from -eq 'secret') {
        if ([string]::IsNullOrWhiteSpace($secretRef)) {
            $null = $Issues.Add("$Path.from is 'secret' but secretRef is not set.")
        } elseif ($secretRef -cnotmatch $script:SafeSecretRefPattern) {
            $null = $Issues.Add("$Path.secretRef '$secretRef' does not match $($script:SafeSecretRefPattern).")
        }
    }
    if ($from -eq 'allowlist' -and $null -ne $secretRef) {
        $null = $Issues.Add("$Path.from is 'allowlist' but secretRef is set; allowlist entries must not reference secrets.")
    }
}

function Test-BridgeHasProp {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $false }
    if ($Object -is [System.Collections.IDictionary]) { return $Object.Contains($Name) }
    return ($null -ne $Object.PSObject.Properties[$Name])
}

function Test-BridgeCommand {
    param($Command, [string]$Path, [System.Collections.Generic.List[string]]$Issues)
    if ($null -eq $Command) { $null = $Issues.Add("$Path is required."); return }
    if ($Command -is [string]) { $null = $Issues.Add("$Path must be an object with executable and argv, not a shell command string."); return }
    Test-BridgeUnknownKeys -Object $Command -Allowed $script:AllowedCommandKeys -Path $Path -Issues $Issues
    $executable = Get-BridgeProp -Object $Command -Name 'executable'
    if ([string]::IsNullOrWhiteSpace($executable)) {
        $null = $Issues.Add("$Path.executable is required and must be a non-empty string.")
    } elseif ($executable -isnot [string]) {
        $null = $Issues.Add("$Path.executable must be a string.")
    }
    if (-not (Test-BridgeHasProp -Object $Command -Name 'argv')) {
        $null = $Issues.Add(".argv is required.")
    } else {
        $argv = Get-BridgeProp -Object $Command -Name 'argv'
        foreach ($a in @($argv)) {
            if ($a -isnot [string]) { $null = $Issues.Add(".argv must contain only strings; found non-string entry.") }
        }
    }
    $env = Get-BridgeProp -Object $Command -Name 'env'
    if ($null -ne $env) {
        $envArr = @($env)
        for ($i = 0; $i -lt $envArr.Count; $i++) {
            Test-BridgeEnvEntry -Entry $envArr[$i] -Path "$Path.env[$i]" -Issues $Issues
        }
    }
    $cwd = Get-BridgeProp -Object $Command -Name 'workingDirectory'
    if ($null -ne $cwd -and $cwd -isnot [string]) {
        $null = $Issues.Add("$Path.workingDirectory must be a string.")
    }
}

function Test-BridgeCheck {
    param($Check, [string]$PhasePath, [int]$Index, [System.Collections.Generic.List[string]]$Issues, [hashtable]$SeenIds, [string]$CollectionName = 'checks')
    $path = "$PhasePath.$CollectionName[$Index]"
    if ($null -eq $Check) { $null = $Issues.Add("$path is null."); return }
    Test-BridgeUnknownKeys -Object $Check -Allowed $script:AllowedCheckKeys -Path $path -Issues $Issues
    $id = Get-BridgeProp -Object $Check -Name 'id'
    if ([string]::IsNullOrWhiteSpace($id)) {
        $null = $Issues.Add("$path.id is required.")
    } elseif ($id -cnotmatch $script:SafeIdPattern) {
        $null = $Issues.Add("$path.id '$id' does not match $($script:SafeIdPattern).")
    } else {
        if ($SeenIds.ContainsKey($id)) { $null = $Issues.Add("$path.id '$id' is duplicated.") }
        else { $null = $SeenIds.Add($id, $true) }
    }
    $checkRoles = Get-BridgeProp -Object $Check -Name 'roles'
    if ($null -ne $checkRoles) { $null = Test-BridgeRoleArray -Value $checkRoles -Path "$path.roles" -Issues $Issues -Required $false }
    $checkRisk = Get-BridgeProp -Object $Check -Name 'riskLevel'
    if ($null -ne $checkRisk -and $script:RiskLevels -notcontains $checkRisk) {
        $null = $Issues.Add("$path.riskLevel '$checkRisk' is not one of $($script:RiskLevels -join ', ').")
    }
    $timeout = Get-BridgeProp -Object $Check -Name 'timeoutSeconds'
    if ($null -ne $timeout) {
        if ($timeout -isnot [int] -and $timeout -isnot [long]) { $null = $Issues.Add("$path.timeoutSeconds must be an integer.") }
        elseif ($timeout -lt 1 -or $timeout -gt 86400) { $null = $Issues.Add("$path.timeoutSeconds must be between 1 and 86400.") }
    }
    $command = Get-BridgeProp -Object $Check -Name 'command'
    Test-BridgeCommand -Command $command -Path "$path.command" -Issues $Issues
    $requiredEvidence = Get-BridgeProp -Object $Check -Name 'requiredEvidence'
    if ($null -ne $requiredEvidence) {
        foreach ($ev in @($requiredEvidence)) {
            if ([string]::IsNullOrWhiteSpace($ev)) { $null = $Issues.Add("$path.requiredEvidence contains an empty entry.") }
            elseif ($ev -cnotmatch $script:SafeEvidencePattern) { $null = $Issues.Add("$path.requiredEvidence entry '$ev' does not match $($script:SafeEvidencePattern).") }
        }
    }
    $expectExit = Get-BridgeProp -Object $Check -Name 'expectExitCode'
    if ($null -ne $expectExit -and $expectExit -isnot [int] -and $expectExit -isnot [long]) {
        $null = $Issues.Add("$path.expectExitCode must be an integer.")
    }
    $skip = Get-BridgeProp -Object $Check -Name 'skip'
    if ($null -ne $skip -and $skip -isnot [bool]) { $null = $Issues.Add("$path.skip must be a boolean.") }
}

function Test-BridgePhase {
    param($Phase, [int]$Index, [System.Collections.Generic.List[string]]$Issues, [hashtable]$SeenIds)
    $path = "profile.phases[$Index]"
    if ($null -eq $Phase) { $null = $Issues.Add("$path is null."); return }
    Test-BridgeUnknownKeys -Object $Phase -Allowed $script:AllowedPhaseKeys -Path $path -Issues $Issues
    $id = Get-BridgeProp -Object $Phase -Name 'id'
    if ([string]::IsNullOrWhiteSpace($id)) {
        $null = $Issues.Add("$path.id is required.")
    } elseif ($id -cnotmatch $script:SafeIdPattern) {
        $null = $Issues.Add("$path.id '$id' does not match $($script:SafeIdPattern).")
    } else {
        if ($SeenIds.ContainsKey($id)) { $null = $Issues.Add("$path.id '$id' is duplicated.") }
        else { $null = $SeenIds.Add($id, $true) }
    }
    $phaseRoles = Get-BridgeProp -Object $Phase -Name 'roles'
    if ($null -ne $phaseRoles) { $null = Test-BridgeRoleArray -Value $phaseRoles -Path "$path.roles" -Issues $Issues -Required $false }
    $phaseRisk = Get-BridgeProp -Object $Phase -Name 'riskLevel'
    if ($null -ne $phaseRisk -and $script:RiskLevels -notcontains $phaseRisk) {
        $null = $Issues.Add("$path.riskLevel '$phaseRisk' is not one of $($script:RiskLevels -join ', ').")
    }
    $requiresApproval = Get-BridgeProp -Object $Phase -Name 'requiresApproval'
    if ($null -ne $requiresApproval -and $requiresApproval -isnot [bool]) { $null = $Issues.Add("$path.requiresApproval must be a boolean.") }
    $approvalGate = Get-BridgeProp -Object $Phase -Name 'approvalGate'
    if ($null -ne $approvalGate -and $approvalGate -cnotmatch $script:SafeRolePattern) {
        $null = $Issues.Add("$path.approvalGate '$approvalGate' does not match $($script:SafeRolePattern).")
    }
    if ($requiresApproval -eq $true -and [string]::IsNullOrWhiteSpace($approvalGate)) {
        $null = $Issues.Add("$path.requiresApproval is true but approvalGate is not set.")
    }
    $timeout = Get-BridgeProp -Object $Phase -Name 'timeoutSeconds'
    if ($null -ne $timeout) {
        if ($timeout -isnot [int] -and $timeout -isnot [long]) { $null = $Issues.Add("$path.timeoutSeconds must be an integer.") }
        elseif ($timeout -lt 1 -or $timeout -gt 86400) { $null = $Issues.Add("$path.timeoutSeconds must be between 1 and 86400.") }
    }
    $onFailure = Get-BridgeProp -Object $Phase -Name 'onFailure'
    if ($null -ne $onFailure -and $script:OnFailureModes -notcontains $onFailure) {
        $null = $Issues.Add("$path.onFailure '$onFailure' is not one of $($script:OnFailureModes -join ', ').")
    }
    $checks = Get-BridgeProp -Object $Phase -Name 'checks'
    if ($null -eq $checks) {
        $null = $Issues.Add("$path.checks is required.")
    } else {
        $checkArray = @($checks)
        if ($checkArray.Count -lt 1) { $null = $Issues.Add("$path.checks must contain at least one check.") }
        $seenCheckIds = @{}
        for ($i = 0; $i -lt $checkArray.Count; $i++) {
            Test-BridgeCheck -Check $checkArray[$i] -PhasePath $path -Index $i -Issues $Issues -SeenIds $seenCheckIds
        }
    }
    $finallyChecks = Get-BridgeProp -Object $Phase -Name 'finallyChecks'
    if ($null -ne $finallyChecks) {
        $finallyArray = @($finallyChecks)
        if ($finallyArray.Count -lt 1) { $null = $Issues.Add("$path.finallyChecks must contain at least one check when declared.") }
        for ($i = 0; $i -lt $finallyArray.Count; $i++) {
            Test-BridgeCheck -Check $finallyArray[$i] -PhasePath $path -Index $i -Issues $Issues -SeenIds $seenCheckIds -CollectionName 'finallyChecks'
        }
    }
}

function Test-BridgeProfile {
    [CmdletBinding()]
    param([Parameter(Mandatory)][object]$Profile)
    $issues = [System.Collections.Generic.List[string]]::new()
    if ($null -eq $Profile) { return [pscustomobject]@{ Valid = $false; Issues = @('Profile is null.') } }
    Test-BridgeUnknownKeys -Object $Profile -Allowed $script:AllowedProfileKeys -Path 'profile' -Issues $issues
    $schemaVersion = Get-BridgeProp -Object $Profile -Name 'schemaVersion'
    if ($schemaVersion -ne 1) { $null = $issues.Add('profile.schemaVersion must be 1.') }
    $profileId = Get-BridgeProp -Object $Profile -Name 'profileId'
    if ([string]::IsNullOrWhiteSpace($profileId)) { $null = $issues.Add('profile.profileId is required.') }
    elseif ($profileId -cnotmatch $script:SafeIdPattern) { $null = $issues.Add("profile.profileId '$profileId' does not match $($script:SafeIdPattern).") }
    $projectId = Get-BridgeProp -Object $Profile -Name 'projectId'
    if ([string]::IsNullOrWhiteSpace($projectId)) { $null = $issues.Add('profile.projectId is required.') }
    elseif ($projectId -cnotmatch $script:SafeIdPattern) { $null = $issues.Add("profile.projectId '$projectId' does not match $($script:SafeIdPattern).") }
    $riskLevel = Get-BridgeProp -Object $Profile -Name 'riskLevel'
    if ([string]::IsNullOrWhiteSpace($riskLevel)) { $null = $issues.Add('profile.riskLevel is required.') }
    elseif ($script:RiskLevels -notcontains $riskLevel) { $null = $issues.Add("profile.riskLevel '$riskLevel' is not one of $($script:RiskLevels -join ', ').") }
    $null = Test-BridgeRoleArray -Value (Get-BridgeProp -Object $Profile -Name 'roles') -Path 'profile.roles' -Issues $issues -Required $true
    $defaultTimeout = Get-BridgeProp -Object $Profile -Name 'defaultTimeoutSeconds'
    if ($null -ne $defaultTimeout) {
        if ($defaultTimeout -isnot [int] -and $defaultTimeout -isnot [long]) { $null = $issues.Add('profile.defaultTimeoutSeconds must be an integer.') }
        elseif ($defaultTimeout -lt 1 -or $defaultTimeout -gt 86400) { $null = $issues.Add('profile.defaultTimeoutSeconds must be between 1 and 86400.') }
    }
    $wd = Get-BridgeProp -Object $Profile -Name 'workingDirectory'
    if ($null -ne $wd) {
        Test-BridgeUnknownKeys -Object $wd -Allowed $script:AllowedWdKeys -Path 'profile.workingDirectory' -Issues $issues
        $wdMode = Get-BridgeProp -Object $wd -Name 'mode'
        if ($null -ne $wdMode -and $script:WdModes -notcontains $wdMode) { $null = $issues.Add("profile.workingDirectory.mode '$wdMode' is not one of $($script:WdModes -join ', ').") }
        $wdSub = Get-BridgeProp -Object $wd -Name 'subpath'
        if ($null -ne $wdSub -and [string]::IsNullOrWhiteSpace($wdSub)) { $null = $issues.Add('profile.workingDirectory.subpath must not be whitespace.') }
    }
    $phases = Get-BridgeProp -Object $Profile -Name 'phases'
    if ($null -eq $phases) { $null = $issues.Add('profile.phases is required.') }
    else {
        $phaseArray = @($phases)
        if ($phaseArray.Count -lt 1) { $null = $issues.Add('profile.phases must contain at least one phase.') }
        $seenPhaseIds = @{}
        for ($i = 0; $i -lt $phaseArray.Count; $i++) { Test-BridgePhase -Phase $phaseArray[$i] -Index $i -Issues $issues -SeenIds $seenPhaseIds }
    }
    return [pscustomobject]@{ Valid = ($issues.Count -eq 0); Issues = [string[]]@($issues.ToArray()) }
}

function Assert-BridgeProfile {
    [CmdletBinding()]
    param([Parameter(Mandatory)][object]$Profile)
    $result = Test-BridgeProfile -Profile $Profile
    if (-not $result.Valid) { throw "Invalid bridge profile: $($result.Issues -join ' ')" }
}

function Load-BridgeProfile {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Profile file not found: $Path" }
    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($raw)) { throw "Profile file is empty: $Path" }
    try { return ($raw | ConvertFrom-Json) }
    catch { throw "Failed to parse profile JSON at $Path : $($_.Exception.Message)" }
}

function Get-BridgePhase {
    [CmdletBinding()]
    param([Parameter(Mandatory)][object]$Profile, [Parameter(Mandatory)][string]$PhaseId)
    $phases = Get-BridgeProp -Object $Profile -Name 'phases'
    if ($null -eq $phases) { return $null }
    foreach ($phase in @($phases)) { if ((Get-BridgeProp -Object $phase -Name 'id') -eq $PhaseId) { return $phase } }
    return $null
}

function Select-BridgeGates {
    [CmdletBinding()]
    param([Parameter(Mandatory)][object]$Profile, [Parameter(Mandatory)][string]$PhaseId, [string]$Role)
    $phase = Get-BridgePhase -Profile $Profile -PhaseId $PhaseId
    if ($null -eq $phase) { throw "Phase '$PhaseId' not found in profile." }
    if (-not [string]::IsNullOrWhiteSpace($Role)) {
        $phaseRoles = Get-BridgeProp -Object $phase -Name 'roles'
        if ($null -ne $phaseRoles) {
            $phaseRoleArr = @($phaseRoles)
            if ($phaseRoleArr.Count -gt 0 -and ($phaseRoleArr -notcontains $Role)) { Write-Output -NoEnumerate ([object[]]@()); return }
        }
    }
    $checks = Get-BridgeProp -Object $phase -Name 'checks'
    if ($null -eq $checks) { Write-Output -NoEnumerate ([object[]]@()); return }
    $selected = [System.Collections.Generic.List[object]]::new()
    foreach ($check in @($checks)) {
        if ((Get-BridgeProp -Object $check -Name 'skip') -eq $true) { continue }
        if (-not [string]::IsNullOrWhiteSpace($Role)) {
            $checkRoles = Get-BridgeProp -Object $check -Name 'roles'
            if ($null -ne $checkRoles) {
                $roleArr = @($checkRoles)
                if ($roleArr.Count -gt 0 -and ($roleArr -notcontains $Role)) { continue }
            }
        }
        $null = $selected.Add($check)
    }
    Write-Output -NoEnumerate ([object[]]@($selected.ToArray()))
    return
}

function Select-BridgeFinalizers {
    [CmdletBinding()]
    param([Parameter(Mandatory)][object]$Profile, [Parameter(Mandatory)][string]$PhaseId, [string]$Role)
    $phase = Get-BridgePhase -Profile $Profile -PhaseId $PhaseId
    if ($null -eq $phase) { throw "Phase '$PhaseId' not found in profile." }
    if (-not [string]::IsNullOrWhiteSpace($Role)) {
        $phaseRoles = Get-BridgeProp -Object $phase -Name 'roles'
        if ($null -ne $phaseRoles -and @($phaseRoles).Count -gt 0 -and @($phaseRoles) -notcontains $Role) {
            Write-Output -NoEnumerate ([object[]]@()); return
        }
    }
    $selected = [System.Collections.Generic.List[object]]::new()
    foreach ($check in @((Get-BridgeProp -Object $phase -Name 'finallyChecks'))) {
        if ($null -eq $check -or (Get-BridgeProp -Object $check -Name 'skip') -eq $true) { continue }
        if (-not [string]::IsNullOrWhiteSpace($Role)) {
            $checkRoles = Get-BridgeProp -Object $check -Name 'roles'
            if ($null -ne $checkRoles -and @($checkRoles).Count -gt 0 -and @($checkRoles) -notcontains $Role) { continue }
        }
        $null = $selected.Add($check)
    }
    Write-Output -NoEnumerate ([object[]]@($selected.ToArray()))
}

function New-BridgeCheckStartInfo {
    [CmdletBinding()]
    param([Parameter(Mandatory)][object]$Check, [string]$ProjectRoot, [hashtable]$Environment)
    $command = Get-BridgeProp -Object $Check -Name 'command'
    if ($null -eq $command) { throw 'Check.command is required.' }
    if ($command -is [string]) { throw 'Check.command must be an object, not a shell command string.' }
    $executable = Get-BridgeProp -Object $command -Name 'executable'
    if ([string]::IsNullOrWhiteSpace($executable)) { throw 'Check.command.executable is required.' }
    $argv = Get-BridgeProp -Object $command -Name 'argv'
    $argvArr = @(); if ($null -ne $argv) { $argvArr = @($argv) }
    $si = [System.Diagnostics.ProcessStartInfo]::new()
    $si.FileName = [string]$executable
    $si.UseShellExecute = $false
    $si.RedirectStandardOutput = $true
    $si.RedirectStandardError = $true
    $si.CreateNoWindow = $true
    foreach ($a in $argvArr) { $null = $si.ArgumentList.Add([string]$a) }
    $cwd = Get-BridgeProp -Object $command -Name 'workingDirectory'
    if (-not [string]::IsNullOrWhiteSpace($cwd)) { $si.WorkingDirectory = [string]$cwd }
    elseif (-not [string]::IsNullOrWhiteSpace($ProjectRoot)) { $si.WorkingDirectory = [string]$ProjectRoot }
    $allowNames = [System.Collections.Generic.List[string]]::new()
    $secretRefs = [System.Collections.Generic.List[string]]::new()
    $resolved = @{}
    $env = Get-BridgeProp -Object $command -Name 'env'
    if ($null -ne $env) {
        foreach ($entry in @($env)) {
            $name = Get-BridgeProp -Object $entry -Name 'name'
            $from = Get-BridgeProp -Object $entry -Name 'from'
            if ($from -eq 'secret') {
                $null = $secretRefs.Add([string](Get-BridgeProp -Object $entry -Name 'secretRef'))
                continue
            }
            $null = $allowNames.Add([string]$name)
            $value = $null
            if ($null -ne $Environment) { if ($Environment.Contains($name)) { $value = $Environment[$name] } }
            else { $value = [System.Environment]::GetEnvironmentVariable($name) }
            if ($null -ne $value) { $resolved[[string]$name] = [string]$value }
        }
    }
    foreach ($k in $resolved.Keys) {
        try { $si.Environment[$k] = $resolved[$k] } catch { try { $si.EnvironmentVariables[$k] = $resolved[$k] } catch { } }
    }
    return [pscustomobject]@{
        StartInfo = $si
        Executable = [string]$executable
        Argv = [string[]]@($argvArr)
        EnvAllowlist = [string[]]@($allowNames.ToArray())
        ResolvedEnv = $resolved
        RequiredSecretRefs = [string[]]@($secretRefs.ToArray())
    }
}

function Test-BridgeCheckResult {
    [CmdletBinding()]
    param([Parameter(Mandatory)][object]$Check, [Parameter(Mandatory)][int]$ExitCode, [string[]]$EvidenceFiles)
    $expectedExit = Get-BridgeProp -Object $Check -Name 'expectExitCode'
    if ($null -eq $expectedExit) { $expectedExit = 0 }
    $exitOk = ($ExitCode -eq [int]$expectedExit)
    $reasons = [System.Collections.Generic.List[string]]::new()
    if (-not $exitOk) { $null = $reasons.Add("Exit code $ExitCode did not match expected $expectedExit.") }
    $missing = [System.Collections.Generic.List[string]]::new()
    $requiredEvidence = Get-BridgeProp -Object $Check -Name 'requiredEvidence'
    if ($null -ne $requiredEvidence) {
        $provided = @(); if ($null -ne $EvidenceFiles) { $provided = @($EvidenceFiles) }
        foreach ($req in @($requiredEvidence)) {
            $found = $false
            foreach ($p in $provided) {
                if ([string]::IsNullOrWhiteSpace($p)) { continue }
                if ($p -eq $req -or (Split-Path -Leaf $p) -eq $req) { $found = $true; break }
            }
            if (-not $found -and $provided.Count -eq 0) {
                if (-not (Test-Path -LiteralPath $req -PathType Leaf)) { $null = $missing.Add([string]$req) }
            } elseif (-not $found) { $null = $missing.Add([string]$req) }
        }
    }
    if ($missing.Count -gt 0) { $null = $reasons.Add("Missing required evidence: $($missing -join ', ').") }
    return [pscustomobject]@{
        Passed = ($exitOk -and $missing.Count -eq 0)
        ExitCode = $ExitCode
        ExpectedExitCode = [int]$expectedExit
        ExitOk = $exitOk
        MissingEvidence = [string[]]@($missing.ToArray())
        Reasons = [string[]]@($reasons.ToArray())
    }
}

function Get-BridgeApprovalGate {
    [CmdletBinding()]
    param([Parameter(Mandatory)][object]$Profile, [Parameter(Mandatory)][string]$PhaseId, [string[]]$ApprovedGates)
    $phase = Get-BridgePhase -Profile $Profile -PhaseId $PhaseId
    if ($null -eq $phase) { return $null }
    if ((Get-BridgeProp -Object $phase -Name 'requiresApproval') -ne $true) { return $null }
    $gate = Get-BridgeProp -Object $phase -Name 'approvalGate'
    if ([string]::IsNullOrWhiteSpace($gate)) {
        return [pscustomobject]@{ PhaseId = $PhaseId; Gate = $null; Blocked = $true; Reason = 'Approval required but no approvalGate is declared.' }
    }
    $approved = @(); if ($null -ne $ApprovedGates) { $approved = @($ApprovedGates) }
    if ($approved -contains $gate) { return $null }
    return [pscustomobject]@{ PhaseId = $PhaseId; Gate = [string]$gate; Blocked = $true; Reason = "Approval gate '$gate' for phase '$PhaseId' has not been approved." }
}

function Get-BridgeTimeout {
    [CmdletBinding()]
    param([Parameter(Mandatory)][object]$Profile, [string]$PhaseId, [string]$CheckId)
    $result = $null
    $default = Get-BridgeProp -Object $Profile -Name 'defaultTimeoutSeconds'
    if ($null -ne $default) { $result = [int]$default }
    if (-not [string]::IsNullOrWhiteSpace($PhaseId)) {
        $phase = Get-BridgePhase -Profile $Profile -PhaseId $PhaseId
        if ($null -ne $phase) {
            $pt = Get-BridgeProp -Object $phase -Name 'timeoutSeconds'
            if ($null -ne $pt) { $result = [int]$pt }
            if (-not [string]::IsNullOrWhiteSpace($CheckId)) {
                foreach ($c in @((Get-BridgeProp -Object $phase -Name 'checks')) + @((Get-BridgeProp -Object $phase -Name 'finallyChecks'))) {
                    if ((Get-BridgeProp -Object $c -Name 'id') -eq $CheckId) {
                        $ct = Get-BridgeProp -Object $c -Name 'timeoutSeconds'
                        if ($null -ne $ct) { $result = [int]$ct }
                        break
                    }
                }
            }
        }
    }
    return $result
}

Export-ModuleMember -Function @(
    'Get-BridgePolicyVersion', 'Load-BridgeProfile', 'Test-BridgeProfile', 'Assert-BridgeProfile',
    'Get-BridgePhase', 'Select-BridgeGates', 'Select-BridgeFinalizers', 'New-BridgeCheckStartInfo', 'Test-BridgeCheckResult',
    'Get-BridgeApprovalGate', 'Get-BridgeTimeout'
) -Variable @()
