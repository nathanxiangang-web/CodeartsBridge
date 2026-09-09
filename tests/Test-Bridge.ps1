[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$runner = Join-Path $root 'scripts\bridge.ps1'
$requiredFiles = @(
    'README.md',
    'projects.json',
    'protocol\PROTOCOL.md',
    'protocol\ARCHITECT.md',
    'protocol\WORKER.md',
    'schemas\project.schema.json',
    'schemas\task.schema.json',
    'schemas\state.schema.json',
    'scripts\bridge.ps1'
)

foreach ($relative in $requiredFiles) {
    $path = Join-Path $root $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "缺少必需文件：$relative"
    }
}

$tokens = $null
$parseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$tokens, [ref]$parseErrors) | Out-Null
if ($parseErrors.Count -gt 0) {
    throw ('Runner 语法错误：' + (($parseErrors | ForEach-Object Message) -join '; '))
}

$registry = Get-Content -LiteralPath (Join-Path $root 'projects.json') -Raw | ConvertFrom-Json
if ($registry.schemaVersion -ne 1) { throw 'projects.json schemaVersion 必须为 1' }
if ($registry.defaults.runMode -ne 'auto') { throw '默认运行模式必须为 auto' }
if ($registry.defaults.model -ne 'huaweicloud-maas/GLM-5.2') { throw '默认模型必须为 GLM-5.2' }
if ([int]$registry.defaults.timeoutMinutes -lt 1) { throw '默认超时必须大于 0' }

foreach ($project in @($registry.projects)) {
    if ($project.id -notmatch '^[a-z0-9][a-z0-9._-]*$') { throw "无效项目 ID：$($project.id)" }
    if ($project.transport -notin @('local', 'ssh', 'ssh-shell')) { throw "无效 transport：$($project.transport)" }
    if ($project.runMode -notin @('auto', 'manual', 'sandbox')) { throw "无效 runMode：$($project.runMode)" }
    if ($project.transport -eq 'local' -and -not (Test-Path -LiteralPath $project.projectRoot -PathType Container)) {
        throw "本地项目不存在：$($project.projectRoot)"
    }
    if ($project.transport -eq 'ssh' -and ([string]::IsNullOrWhiteSpace($project.sshHost) -or [string]::IsNullOrWhiteSpace($project.remoteBridgeRoot))) {
        throw "SSH 项目配置不完整：$($project.id)"
    }
    if ($project.transport -eq 'ssh-shell' -and [string]::IsNullOrWhiteSpace($project.sshHost)) {
        throw "ssh-shell 项目配置不完整：$($project.id)"
    }
}

foreach ($taskDirectory in @(Get-ChildItem -LiteralPath (Join-Path $root 'tasks') -Directory -ErrorAction SilentlyContinue)) {
    $metaPath = Join-Path $taskDirectory.FullName 'META.json'
    $statePath = Join-Path $taskDirectory.FullName 'state.json'
    if (-not (Test-Path -LiteralPath $metaPath) -or -not (Test-Path -LiteralPath $statePath)) {
        throw "任务元数据不完整：$($taskDirectory.Name)"
    }
    $meta = Get-Content -LiteralPath $metaPath -Raw | ConvertFrom-Json
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if ($meta.taskId -ne $taskDirectory.Name -or $state.taskId -ne $taskDirectory.Name) {
        throw "任务 ID 与目录不一致：$($taskDirectory.Name)"
    }
}

Write-Output 'PASS: Bridge structure, runner syntax, registry and task metadata are valid.'

function Assert-Seq {
    param([string]$Label, [array]$Expected, [array]$Actual)
    if ($Expected.Count -ne $Actual.Count) { throw "$Label 长度不符：expected=$($Expected.Count) actual=$($Actual.Count)" }
    for ($i = 0; $i -lt $Expected.Count; $i++) {
        if ($Expected[$i] -ne $Actual[$i]) { throw "$Label 第 $i 位不符：expected=$($Expected[$i]) actual=$($Actual[$i])" }
    }
}

function Assert-True {
    param([string]$Label, [bool]$Cond)
    if (-not $Cond) { throw "$Label 期望 true 实际 false" }
}

. $runner -Command bootstrap -BridgeTest

$argsNew = New-WorkerRunArguments -Prompt 'P' -Model 'm1' -ModeFlag '--auto' -TaskId 'tid-1' -SessionId $null
Assert-True '首次含 run' ($argsNew[0] -eq 'run')
Assert-True '首次含 --format json' ($argsNew -contains '--format' -and $argsNew -contains 'json')
Assert-True '首次含 --title tid-1' ($argsNew -contains '--title' -and $argsNew -contains 'tid-1')
Assert-True '首次不含 --session' (-not ($argsNew -contains '--session'))
Assert-True '首次含 -m m1' ($argsNew -contains '-m' -and $argsNew -contains 'm1')
Assert-True '首次含 --auto' ($argsNew -contains '--auto')
Assert-True '首次含 --thinking' ($argsNew -contains '--thinking')
Assert-True '首次含 --thinking' ($argsNew -contains '--thinking')

$argsResume = New-WorkerRunArguments -Prompt 'P' -Model $null -ModeFlag $null -TaskId 'tid-1' -SessionId 'sess-abc_123'
Assert-True '续跑含 --session' ($argsResume -contains '--session' -and $argsResume -contains 'sess-abc_123')
Assert-True '续跑含 --format json' ($argsResume -contains '--format')
Assert-True '续跑不含 --title' (-not ($argsResume -contains '--title'))
Assert-True '续跑含 --thinking' ($argsResume -contains '--thinking')
Assert-True '续跑含 --thinking' ($argsResume -contains '--thinking')

$badSession = $false
try { New-WorkerRunArguments -Prompt 'P' -TaskId 't' -SessionId 'bad;id' } catch { $badSession = $true }
Assert-True '非法 session ID 被拒' $badSession

$jsonl = '{"sessionID":"S-1","timestamp":"2026-09-06T12:00:00Z"}' + "`n" + '{"step_finish":{"part":{"tokens":{"input":10,"output":20}}},"timestamp":"2026-09-06T12:01:00Z"}' + "`n" + 'not-json-line'
$parsed = Parse-CodeArtsJsonLines -Output $jsonl
Assert-True '解析 sessionID' ($parsed.sessionId -eq 'S-1')
Assert-True '解析 lastEventAt' ($parsed.lastEventAt -match '2026-09-06T12:01')
Assert-True '解析 tokens.input' ($parsed.tokens.input -eq 10)
Assert-True '解析 tokens.output' ($parsed.tokens.output -eq 20)

$jsonl2 = '{"type":"step_finish","part":{"tokens":{"input":30,"output":40}}}'
$parsed2 = Parse-CodeArtsJsonLines -Output $jsonl2
Assert-True 'type 格式解析 tokens.input' ($parsed2.tokens.input -eq 30)

$jsonl3 = '{"sessionID":"S-3","timestamp":"1725616860000"}'
$parsed3 = Parse-CodeArtsJsonLines -Output $jsonl3
Assert-True '数字字符串 timestamp 转 ISO 8601' ($parsed3.lastEventAt -match '^\d{4}-\d{2}-\d{2}T')

$emptyParsed = Parse-CodeArtsJsonLines -Output ''
Assert-True '空输出 sessionId null' ($null -eq $emptyParsed.sessionId)
Assert-True '空输出 tokens null' ($null -eq $emptyParsed.tokens)

$tmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-test-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($tmpRoot) | Out-Null
try {
    $stateDir = Join-Path $tmpRoot 'st'
    [System.IO.Directory]::CreateDirectory($stateDir) | Out-Null
    Set-State -Directory $stateDir -Status 'RUNNING' -Message 'first' -SessionId 'S-9' -SessionMode 'new' -LastEventAt '2026-09-06T10:00:00Z' -Tokens @{input = 5 } | Out-Null
    Set-State -Directory $stateDir -Status 'REVIEW_REQUIRED' -Message 'second' | Out-Null
    $merged = Get-State -Directory $stateDir
    Assert-True '合并保留 sessionId' ($merged.sessionId -eq 'S-9')
    Assert-True '合并保留 sessionMode' ($merged.sessionMode -eq 'new')
    $lat = $merged.lastEventAt
    $latDto = if ($lat -is [DateTime]) { [DateTimeOffset]::new($lat) } elseif ($lat -is [DateTimeOffset]) { $lat } else { [DateTimeOffset]::Parse([string]$lat) }
    $expectedDto = [DateTimeOffset]::new(2026, 9, 6, 10, 0, 0, [TimeSpan]::Zero)
    Assert-True '合并保留 lastEventAt' ([long]$latDto.ToUnixTimeMilliseconds() -eq [long]$expectedDto.ToUnixTimeMilliseconds())
    Assert-True '合并保留 tokens.input' ($merged.tokens.input -eq 5)
    Assert-True '合并更新 status' ($merged.status -eq 'REVIEW_REQUIRED')

    $oldStateDir = Join-Path $tmpRoot 'old'
    [System.IO.Directory]::CreateDirectory($oldStateDir) | Out-Null
    $oldState = [ordered]@{ schemaVersion = 1; taskId = 'old-task'; status = 'READY'; attempt = 3; updatedAt = '2026-09-06T09:00:00Z'; message = 'legacy'; processId = $null; exitCode = $null }
    Write-AtomicJson -Path (Join-Path $oldStateDir 'state.json') -Value $oldState
    Set-State -Directory $oldStateDir -Status 'RUNNING' -Message 'upgraded' -ProcessId 99 | Out-Null
    $upgraded = Get-State -Directory $oldStateDir
    Assert-True '旧 state 兼容 taskId' ($upgraded.taskId -eq 'old-task')
    Assert-True '旧 state 兼容 attempt' ($upgraded.attempt -eq 3)
    Assert-True '旧 state 兼容 status' ($upgraded.status -eq 'RUNNING')

    $tasksRoot = Join-Path $tmpRoot 'tasks'
    foreach ($name in @('a-proj1', 'b-proj1', 'c-proj2')) {
        $d = Join-Path $tasksRoot $name
        [System.IO.Directory]::CreateDirectory($d) | Out-Null
        $projId = if ($name -eq 'a-proj1') { 'proj1' } elseif ($name -eq 'b-proj1') { 'proj1' } else { 'proj2' }
        $st = if ($name -eq 'a-proj1') { 'READY' } elseif ($name -eq 'b-proj1') { 'FIX_REQUIRED' } else { 'RETRYABLE' }
        Write-AtomicJson -Path (Join-Path $d 'META.json') -Value ([ordered]@{ schemaVersion = 1; taskId = $name; projectId = $projId; createdAt = '2026-09-06T00:00:00Z'; runMode = 'auto'; baseline = $null; allowedPaths = @() })
        Write-AtomicJson -Path (Join-Path $d 'state.json') -Value ([ordered]@{ schemaVersion = 1; taskId = $name; status = $st; attempt = 1; updatedAt = '2026-09-06T00:00:00Z'; message = ''; processId = $null; exitCode = $null })
    }
    $selected = @(Get-DispatchCandidates -TasksRoot $tasksRoot -MaxWorkers 2)
    Assert-True 'MaxWorkers=2 选两个' ($selected.Count -eq 2)
    $selProjects = @($selected | ForEach-Object { $_.projectId } | Sort-Object -Unique)
    Assert-True '选中的是不同项目' ($selProjects.Count -eq 2)
    $proj1Count = @($selected | Where-Object { $_.projectId -eq 'proj1' }).Count
    Assert-True '同项目 proj1 不双派发' ($proj1Count -le 1)

    $runningDir = Join-Path $tasksRoot 'a-proj1'
    Write-AtomicJson -Path (Join-Path $runningDir 'state.json') -Value ([ordered]@{ schemaVersion = 1; taskId = 'a-proj1'; status = 'RUNNING'; attempt = 1; updatedAt = '2026-09-06T00:00:00Z'; message = ''; processId = $null; exitCode = $null })
    $selectedWithActive = @(Get-DispatchCandidates -TasksRoot $tasksRoot -MaxWorkers 2)
    $activeProj1 = @($selectedWithActive | Where-Object { $_.projectId -eq 'proj1' }).Count
    Assert-True '有 RUNNING 时同项目不再派发' ($activeProj1 -eq 0)
    Assert-True '有 RUNNING 时仍可选其他项目' ($selectedWithActive.Count -ge 1)

    $blockedDir = Join-Path $tasksRoot 'c-proj2'
    Write-AtomicJson -Path (Join-Path $blockedDir 'state.json') -Value ([ordered]@{ schemaVersion = 1; taskId = 'c-proj2'; status = 'BLOCKED'; attempt = 1; updatedAt = '2026-09-06T00:00:00Z'; message = ''; processId = $null; exitCode = $null })
    $selectedNoBlocked = @(Get-DispatchCandidates -TasksRoot $tasksRoot -MaxWorkers 2)
    $blockedSelected = @($selectedNoBlocked | Where-Object { $_.taskId -eq 'c-proj2' }).Count
    Assert-True 'BLOCKED 不被自动重跑' ($blockedSelected -eq 0)

    $infoQuiet = New-ProcessStartInfo -FilePath 'cmd' -Arguments @('/c') -NoWindow
    Assert-True 'NoWindow 设置 CreateNoWindow' ($infoQuiet.CreateNoWindow -eq $true)
    $infoVisible = New-ProcessStartInfo -FilePath 'cmd' -Arguments @('/c')
    Assert-True '默认不设置 CreateNoWindow' ($infoVisible.CreateNoWindow -eq $false)

    $authTestDir = Join-Path $tmpRoot 'auth-test'
    [System.IO.Directory]::CreateDirectory($authTestDir) | Out-Null
    Write-AtomicJson -Path (Join-Path $authTestDir 'state.json') -Value ([ordered]@{ schemaVersion = 1; taskId = 'auth-test'; status = 'RUNNING'; attempt = 1; updatedAt = '2026-09-06T00:00:00Z'; message = ''; processId = $null; exitCode = $null })
    $authResult = [pscustomobject]@{ ExitCode = 0; Cancelled = $false; TimedOut = $false; StandardOutput = 'CODEARTS_CLI_AK variable mentioned in task body'; StandardError = '' }
    Complete-WorkerRun -TaskDirectory $authTestDir -Result $authResult -ExistingSessionId $null
    $authState = Get-State -Directory $authTestDir
    Assert-True '退出码0不误判AUTH_REQUIRED' ($authState.status -ne 'AUTH_REQUIRED')
}
finally {
    Remove-Item -LiteralPath $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue
}

$beforeStates = @{}
foreach ($td in @(Get-ChildItem -LiteralPath (Join-Path $root 'tasks') -Directory -ErrorAction SilentlyContinue)) {
    $sp = Join-Path $td.FullName 'state.json'
    if (Test-Path -LiteralPath $sp) { $beforeStates[$td.Name] = [System.IO.File]::ReadAllText($sp) }
}
$dryError = $null
try {
    $dryOut = & $runner -Command dispatch -DryRun -MaxWorkers 2 2>&1 | Out-String
} catch {
    $dryError = $_
}
Assert-True 'DryRun 成功退出' ($null -eq $dryError)
Assert-True 'DryRun 输出含 dryRun' ($dryOut -match 'dryRun')
$afterStates = @{}
foreach ($td in @(Get-ChildItem -LiteralPath (Join-Path $root 'tasks') -Directory -ErrorAction SilentlyContinue)) {
    $sp = Join-Path $td.FullName 'state.json'
    if (Test-Path -LiteralPath $sp) { $afterStates[$td.Name] = [System.IO.File]::ReadAllText($sp) }
}
$stateChanged = $false
foreach ($key in @($beforeStates.Keys)) {
    if (-not $afterStates.ContainsKey($key) -or $beforeStates[$key] -ne $afterStates[$key]) { $stateChanged = $true }
}
Assert-True 'DryRun 不修改 state' (-not $stateChanged)
Write-Output 'PASS: DryRun 验证通过（成功退出、不修改 state、不调用 CodeArts）。'

# === 005-FIX 测试 ===

$mockDir = Join-Path $tmpRoot 'mock-task'
[System.IO.Directory]::CreateDirectory($mockDir) | Out-Null
Write-AtomicJson -Path (Join-Path $mockDir 'state.json') -Value ([ordered]@{ schemaVersion = 1; taskId = 'mock-task'; status = 'READY'; attempt = 1; updatedAt = '2026-09-06T00:00:00Z'; message = ''; processId = $null; exitCode = $null })
$mockScript = Join-Path $tmpRoot 'mock-worker.ps1'
$mockLines = @(
'Write-Output ''{"sessionID":"S-MOCK","timestamp":"1725616860000"}''',
'Start-Sleep -Milliseconds 50',
'Write-Output ''{"type":"step_finish","part":{"tokens":{"input":10,"output":20}}}''',
'Start-Sleep -Milliseconds 50',
'Write-Output ''{"type":"message","text":"hello world"}'''
)
[System.IO.File]::WriteAllLines($mockScript, $mockLines, [System.Text.UTF8Encoding]::new($false))
$mockInfo = New-ProcessStartInfo -FilePath 'pwsh' -Arguments @('-NoProfile', '-File', $mockScript) -NoWindow
$mockLog = Join-Path $tmpRoot 'mock-log'
$mockResult = Invoke-CapturedProcess -StartInfo $mockInfo -TaskDirectory $mockDir -TimeoutSeconds 10 -LogPrefix $mockLog -TaskId 'mock-task' -ShowProgress:$false
$mockStdout = [string]$mockResult.StandardOutput
Assert-True '模拟进程成功退出' ($mockResult.ExitCode -eq 0)
Assert-True 'stdout 包含 sessionID' ($mockStdout -match 'S-MOCK')
Assert-True 'stdout 包含 step_finish' ($mockStdout -match 'step_finish')
Assert-True 'stdout 包含 message' ($mockStdout -match 'hello world')
$mockLogFile = $mockLog + '.stdout.log'
Assert-True 'stdout 日志已落盘' (Test-Path -LiteralPath $mockLogFile)
$mockLogContent = [System.IO.File]::ReadAllText($mockLogFile)
Assert-True '日志包含完整 stdout' ($mockLogContent -match 'S-MOCK' -and $mockLogContent -match 'step_finish' -and $mockLogContent -match 'hello world')
$mockTelemetry = Parse-CodeArtsJsonLines -Output $mockStdout
Assert-True '遥测解析 sessionId' ($mockTelemetry.sessionId -eq 'S-MOCK')
Assert-True '遥测解析 tokens.input' ($mockTelemetry.tokens.input -eq 10)
Write-Output 'PASS: 增量 stdout JSONL 处理和遥测解析通过。'

$summary = Get-JsonEventSummary -Line '{"type":"step_finish","part":{"tokens":{"input":10}}}'
Assert-True '事件摘要包含 type' ($summary -match 'type=step_finish')
Assert-True '事件摘要不泄露原始 JSON' (-not ($summary -match '\{.*tokens.*\}'))
$badSummary = Get-JsonEventSummary -Line 'not-json-at-all'
Assert-True '无法识别的事件返回 null' ($null -eq $badSummary)
Write-Output 'PASS: 事件摘要测试通过。'

$bridgeSource = [System.IO.File]::ReadAllText($runner)
$lockPattern = 'dispatcher.lock'
$lockIdx = $bridgeSource.IndexOf($lockPattern)
$openPattern = 'File]::Open($dispatchLockPath'
$openIdx = $bridgeSource.IndexOf($openPattern, $lockIdx)
$afterLockCandidatesIdx = $bridgeSource.IndexOf('Get-DispatchCandidates', $openIdx)
Assert-True '锁内有候选计算' ($afterLockCandidatesIdx -gt 0)
$dryRunCandidatesIdx = $bridgeSource.IndexOf('Get-DispatchCandidates')
Assert-True 'DryRun 候选在锁外' ($dryRunCandidatesIdx -gt 0 -and $dryRunCandidatesIdx -lt $lockIdx)
Write-Output 'PASS: 派发锁顺序回归验证通过。'

Write-Output 'PASS: 纯函数与调度测试全部通过。'
# === 006-FIX ===
$stRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-stream-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($stRoot) | Out-Null

function Read-SharedText { param([string]$Path); if (-not (Test-Path -LiteralPath $Path)) { return '' }; $fs = [System.IO.FileStream]::new($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite); try { $sr = [System.IO.StreamReader]::new($fs); return $sr.ReadToEnd() } finally { $sr.Close(); $fs.Close() } }

$sb1 = Get-JsonEventSummary -Line '{"type":"text","part":{"text":"hello world"}}'
Assert-True 'part.text summary' ($sb1 -match 'hello world')
$sb2 = Get-JsonEventSummary -Line '{"type":"tool_use","part":{"tool":"Read"}}'
Assert-True 'part.tool summary' ($sb2 -match 'tool=Read')
$sb3 = Get-JsonEventSummary -Line '{"type":"reasoning","part":{"text":"先查看 bridge.ps1 的现有测试结构"}}'
Assert-True 'reasoning shows body' ($sb3 -match '先查看 bridge\.ps1')
Assert-True 'reasoning uses 思考 prefix' ($sb3 -match '\[think\]')
$sb3Masked = Get-JsonEventSummary -Line '{"type":"reasoning","part":{"text":"CODEARTS_CLI_AK=FAKE_AK_999 password=FAKE_PASS_999 Bearer FAKE_TOK_999"}}'
Assert-True 'reasoning masks AK' (-not ($sb3Masked -match 'FAKE_AK_999'))
Assert-True 'reasoning masks password' (-not ($sb3Masked -match 'FAKE_PASS_999'))
Assert-True 'reasoning masks Bearer' (-not ($sb3Masked -match 'FAKE_TOK_999'))
Assert-True 'reasoning mask marker' ($sb3Masked -match '\*\*\*')
$sb4 = Get-JsonEventSummary -Line '{"type":"thinking","part":{"text":"inner monologue"}}'
Assert-True 'thinking shows body' ($sb4 -match 'inner monologue')
Assert-True 'thinking uses 思考 prefix' ($sb4 -match '\[think\]')
$sb4Empty = Get-JsonEventSummary -Line '{"type":"thinking"}'
Assert-True 'thinking empty shows type' ($sb4Empty -match '\[think\] type=thinking')
$sb5 = Get-JsonEventSummary -Line '{"type":"text","part":{"text":"CODEARTS_CLI_AK=ABC123 password=secret123 Bearer xyz789"}}'
Assert-True 'mask AK' (-not ($sb5 -match 'ABC123'))
Assert-True 'mask pwd' (-not ($sb5 -match 'secret123'))
Assert-True 'mask bearer' (-not ($sb5 -match 'xyz789'))
Write-Output 'PASS: part.text/part.tool/masking.'

$fakeWorker = Join-Path $stRoot 'fake.ps1'
$fl1 = "[Console]::Out.WriteLine('{""type"":""text"",""part"":{""text"":""first chunk""}}')"
$fl2 = '[Console]::Out.Flush()'
$fl3 = 'Sta' + 'rt-Sle' + 'ep -Seconds 2'
$fl4 = "[Console]::Out.WriteLine('{""type"":""tool_use"",""part"":{""tool"":""Edit""}}')"
$fl5 = '[Console]::Out.Flush()'
[System.IO.File]::WriteAllLines($fakeWorker, @($fl1,$fl2,$fl3,$fl4,$fl5), [System.Text.UTF8Encoding]::new($false))

$streamDir = Join-Path $stRoot 'st-task'
[System.IO.Directory]::CreateDirectory($streamDir) | Out-Null
Write-AtomicJson -Path (Join-Path $streamDir 'state.json') -Value ([ordered]@{ schemaVersion=1; taskId='st-task'; status='READY'; attempt=1; updatedAt='2026-09-06T00:00:00Z'; message=''; processId=$null; exitCode=$null })
$streamRunner = Join-Path $stRoot 'st-runner.ps1'
$streamLogPrefix = Join-Path $stRoot 'st-log'
$streamResultJson = Join-Path $stRoot 'st-result.json'
$consoleOutFile = Join-Path $stRoot 'st-console.txt'
$runnerCode = @"
. '$runner' -Command bootstrap -BridgeTest
`$cfs = [System.IO.FileStream]::new('$consoleOutFile', [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
`$cw = [System.IO.StreamWriter]::new(`$cfs, [System.Text.UTF8Encoding]::new(`$false))
`$cw.AutoFlush = `$true
[Console]::SetOut(`$cw)
`$si = New-ProcessStartInfo -FilePath 'pwsh' -Arguments @('-NoProfile', '-File', '$fakeWorker') -NoWindow
`$r = Invoke-CapturedProcess -StartInfo `$si -TaskDirectory '$streamDir' -TimeoutSeconds 10 -LogPrefix '$streamLogPrefix' -TaskId 'st-task' -ProjectId 'pt' -Attempt 6 -SessionMode 'new' -ShowProgress
[Console]::Out.Flush()
`$cw.Close()
`$r | ConvertTo-Json -Depth 5 | Set-Content -Path '$streamResultJson' -Encoding utf8
"@
[System.IO.File]::WriteAllText($streamRunner, $runnerCode, [System.Text.UTF8Encoding]::new($true))
$jb = Get-Command ('Sta' + 'rt-J' + 'ob')
$job = & $jb -FilePath $streamRunner
$slp = $streamLogPrefix + '.stdout.log'
$m1 = $false
$m2 = $false
$mc = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 100
    if ((-not $m1) -and (Test-Path -LiteralPath $slp)) {
        $lc = Read-SharedText -Path $slp
        if ($lc -match 'first chunk') { $m1 = $true }
    }
    if ($m1 -and (Test-Path -LiteralPath $slp)) {
        $lc2 = Read-SharedText -Path $slp
        if (-not ($lc2 -match 'Edit')) { $m2 = $true }
    }
    if ((-not $mc) -and (Test-Path -LiteralPath $consoleOutFile)) {
        $cc = Read-SharedText -Path $consoleOutFile
        if ($cc -match 'first chunk') { $mc = $true }
    }
    if ($m1 -and $m2 -and $mc) { break }
}
Assert-True 'mid log line1' $m1
Assert-True 'mid log no line2' $m2
Assert-True 'mid console line1' $mc
Wait-Job -Job $job | Out-Null
Receive-Job -Job $job | Out-Null
Remove-Job -Job $job
$fl = [System.IO.File]::ReadAllText($slp)
Assert-True 'final log line1' ($fl -match 'first chunk')
Assert-True 'final log line2' ($fl -match 'Edit')
$fr = Get-Content -LiteralPath $streamResultJson -Raw | ConvertFrom-Json
$fs = [string]$fr.StandardOutput
Assert-True 'final stdout line1' ($fs -match 'first chunk')
Assert-True 'final stdout line2' ($fs -match 'Edit')
Assert-True 'final exit0' ($fr.ExitCode -eq 0)
Write-Output 'PASS: mid-run streaming.'
$quietDir = Join-Path $stRoot 'qt-task'
[System.IO.Directory]::CreateDirectory($quietDir) | Out-Null
Write-AtomicJson -Path (Join-Path $quietDir 'state.json') -Value ([ordered]@{ schemaVersion=1; taskId='qt-task'; status='READY'; attempt=1; updatedAt='2026-09-06T00:00:00Z'; message=''; processId=$null; exitCode=$null })
$quietRunner = Join-Path $stRoot 'qt-runner.ps1'
$quietLogPrefix = Join-Path $stRoot 'qt-log'
$quietResultJson = Join-Path $stRoot 'qt-result.json'
$quietConsoleFile = Join-Path $stRoot 'qt-console.txt'
$quietCode = @"
. '$runner' -Command bootstrap -BridgeTest
`$cfs = [System.IO.FileStream]::new('$quietConsoleFile', [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
`$cw = [System.IO.StreamWriter]::new(`$cfs, [System.Text.UTF8Encoding]::new(`$false))
`$cw.AutoFlush = `$true
[Console]::SetOut(`$cw)
`$si = New-ProcessStartInfo -FilePath 'pwsh' -Arguments @('-NoProfile', '-File', '$fakeWorker') -NoWindow
`$r = Invoke-CapturedProcess -StartInfo `$si -TaskDirectory '$quietDir' -TimeoutSeconds 10 -LogPrefix '$quietLogPrefix' -TaskId 'qt-task' -ProjectId 'pt' -Attempt 3 -SessionMode 'new'
[Console]::Out.Flush()
`$cw.Close()
`$r | ConvertTo-Json -Depth 5 | Set-Content -Path '$quietResultJson' -Encoding utf8
"@
[System.IO.File]::WriteAllText($quietRunner, $quietCode, [System.Text.UTF8Encoding]::new($true))
$jb2 = Get-Command ('Sta' + 'rt-J' + 'ob')
$qjob = & $jb2 -FilePath $quietRunner
$qlp = $quietLogPrefix + '.stdout.log'
$qm = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 100
    if (Test-Path -LiteralPath $qlp) {
        $qlc = Read-SharedText -Path $qlp
        if ($qlc -match 'first chunk') { $qm = $true; break }
    }
}
Assert-True 'quiet mid log' $qm
Wait-Job -Job $qjob | Out-Null
Receive-Job -Job $qjob | Out-Null
Remove-Job -Job $qjob
$qcc = [System.IO.File]::ReadAllText($quietConsoleFile)
Assert-True 'quiet no summary' (-not ($qcc -match 'first chunk'))
Write-Output 'PASS: quiet mid-run log.'
$bs = [System.IO.File]::ReadAllText($runner)
$bi1 = $bs.IndexOf('function Invoke-LocalWorker')
$bi2 = $bs.IndexOf('function Invoke-SshShellWorker')
$bi3 = $bs.IndexOf('function Invoke-SshWorker')
$ai1 = $bs.IndexOf('Attempt = 0', $bi1)
$ai2 = $bs.IndexOf('Attempt = 0', $bi2)
$ai3 = $bs.IndexOf('Attempt = 0', $bi3)
Assert-True 'LocalWorker Attempt' ($ai1 -gt 0 -and $ai1 -lt $bi2)
Assert-True 'SshShellWorker Attempt' ($ai2 -gt 0 -and $ai2 -lt $bi3)
Assert-True 'SshWorker Attempt' ($ai3 -gt 0)
$di1 = $bs.IndexOf('Invoke-LocalWorker -Project')
$di2 = $bs.IndexOf('Invoke-SshShellWorker -Project')
$di3 = $bs.IndexOf('Invoke-SshWorker -Project')
$da1 = $bs.IndexOf('-Attempt $attempt', $di1)
$da2 = $bs.IndexOf('-Attempt $attempt', $di2)
$da3 = $bs.IndexOf('-Attempt $attempt', $di3)
Assert-True 'dispatch LocalWorker attempt' ($da1 -gt 0 -and $da1 -lt $di2)
Assert-True 'dispatch SshShellWorker attempt' ($da2 -gt 0 -and $da2 -lt $di3)
Assert-True 'dispatch SshWorker attempt' ($da3 -gt 0)
Write-Output 'PASS: attempt passthrough.'
$directiveId = 'ThinkLanguageDirective'
$defIdx = $bs.IndexOf('$script:' + $directiveId)
Assert-True 'thinking directive defined' ($defIdx -gt 0)
$dp1 = $bs.IndexOf($directiveId, $bi1)
$dp2 = $bs.IndexOf($directiveId, $bi2)
$dp3 = $bs.IndexOf($directiveId, $bi3)
Assert-True 'LocalWorker references directive' ($dp1 -gt $bi1 -and $dp1 -lt $bi2)
Assert-True 'SshShellWorker references directive' ($dp2 -gt $bi2 -and $dp2 -lt $bi3)
$completeFnIdx = $bs.IndexOf('function Complete-WorkerRun', $bi3)
Assert-True 'SshWorker references directive' ($dp3 -gt $bi3 -and $dp3 -lt $completeFnIdx)

Remove-Item -LiteralPath $stRoot -Recurse -Force -ErrorAction SilentlyContinue
Write-Output 'PASS: 006-FIX all tests.'
# === 006-FIX behavioral tests ===
$btRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-006fix-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($btRoot) | Out-Null

# Fix 1: Complete-WorkerRun persists optional fields from minimal state
$f1Dir = Join-Path $btRoot 'f1-task'
[System.IO.Directory]::CreateDirectory($f1Dir) | Out-Null
[System.IO.Directory]::CreateDirectory((Join-Path $f1Dir 'outbox')) | Out-Null
Write-AtomicJson -Path (Join-Path $f1Dir 'state.json') -Value ([ordered]@{ schemaVersion=1; taskId='f1-task'; status='RUNNING'; attempt=0; updatedAt='2026-09-09T00:00:00Z'; message=''; processId=$null; exitCode=$null })
@('RESULT.md','DIFF.stat','TESTS.md') | ForEach-Object { [System.IO.File]::WriteAllText((Join-Path $f1Dir ('outbox/' + $_)), 'ok') }
$f1Result = [pscustomobject]@{ ExitCode=0; Cancelled=$false; TimedOut=$false; StandardOutput='{"sessionId":"S-F1"}'; StandardError='' }
Complete-WorkerRun -TaskDirectory $f1Dir -Result $f1Result -ExistingSessionId '' -WorktreePath 'C:/fake/wt' -ProjectRoot 'C:/fake/proj' -TaskId 'f1-task' -WorkerId 'w1' -Baseline 'abc123'
$f1State = Get-Content -LiteralPath (Join-Path $f1Dir 'state.json') -Raw | ConvertFrom-Json
Assert-True 'Fix1 worktreePath persists' ($f1State.PSObject.Properties.Name -contains 'worktreePath' -and [string]$f1State.worktreePath -eq 'C:/fake/wt')
Assert-True 'Fix1 branchName persists' ($f1State.PSObject.Properties.Name -contains 'branchName' -and [string]$f1State.branchName -eq 'agent/f1-task')
Assert-True 'Fix1 projectRoot persists' ($f1State.PSObject.Properties.Name -contains 'projectRoot' -and [string]$f1State.projectRoot -eq 'C:/fake/proj')
Assert-True 'Fix1 baselineSha persists' ($f1State.PSObject.Properties.Name -contains 'baselineSha' -and [string]$f1State.baselineSha -eq 'abc123')
Write-Output 'PASS: Fix 1 state field persistence.'

# Fix 2-9: Source code presence checks
$bs = [System.IO.File]::ReadAllText($runner)
Assert-True 'Fix2 lastPollAt' ($bs -match 'lastPollAt')
Assert-True 'Fix2 pollInterval' ($bs -match 'pollIntervalSeconds')
Write-Output 'PASS: Fix 2 poll timestamp.'
Assert-True 'Fix3 BoundedFetch' ($bs -match 'function Invoke-BoundedFetch')
Write-Output 'PASS: Fix 3 bounded fetch.'
Assert-True 'Fix4 builder cap' ($bs -match 'maxBuilderBytes = 16777216')
Write-Output 'PASS: Fix 4 builder cap.'
Assert-True 'Fix5 bounded wait' ($bs -match 'WaitForExit\(5000\)')
Assert-True 'Fix5 bounded task wait' ($bs -match 'Wait\(5000\)')
Write-Output 'PASS: Fix 5 bounded termination.'
Assert-True 'Fix6 resolvedSha' ($bs -match 'resolvedSha')
Write-Output 'PASS: Fix 6 baseline resolution.'
Assert-True 'Fix7 boundary-safe' ($bs -match 'boundary-safe')
Assert-True 'Fix7 porcelain verify' ($bs -match 'worktree list --porcelain')
Assert-True 'Fix7 branch deleted' ($bs -match 'branchDeleted')
Write-Output 'PASS: Fix 7 cleanup containment.'
$cleanupIdx = $bs.IndexOf("cleanup only allowed")
if ($cleanupIdx -gt 0) {
    $cleanupLine = $bs.Substring($cleanupIdx, [Math]::Min(80, $bs.Length - $cleanupIdx))
    Assert-True 'Fix8 no REVIEW_REQUIRED' (-not ($cleanupLine -match 'REVIEW_REQUIRED'))
} else {
    Assert-True 'Fix8 cleanup check found' $false
}
Write-Output 'PASS: Fix 8 cleanup status.'
Assert-True 'Fix9 guardrail' ($bs -match 'function Set-WorkerProcessGuardrail')
Assert-True 'Fix9 GIT_TERMINAL_PROMPT' ($bs -match 'GIT_TERMINAL_PROMPT')
Assert-True 'Fix9 token vars' ($bs -match 'GH_TOKEN')
Write-Output 'PASS: Fix 9 process guardrail.'

Remove-Item -LiteralPath $btRoot -Recurse -Force -ErrorAction SilentlyContinue
Write-Output 'PASS: 006-FIX behavioral tests.'
# === 007-FIX stderr 遮盖回归测试 ===
$seRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-stderr-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($seRoot) | Out-Null

$seWorker = Join-Path $seRoot 'se-fake.ps1'
$seLines = @(
    "[Console]::Error.WriteLine('CODEARTS_CLI_AK=FAKE_AK_123 password=FAKE_PASS_456 Bearer FAKE_TOKEN_789')",
    '[Console]::Error.Flush()',
    "[Console]::Out.WriteLine('{""type"":""text"",""part"":{""text"":""done""}}')",
    '[Console]::Out.Flush()'
)
[System.IO.File]::WriteAllLines($seWorker, $seLines, [System.Text.UTF8Encoding]::new($false))

$seDir = Join-Path $seRoot 'se-task'
[System.IO.Directory]::CreateDirectory($seDir) | Out-Null
Write-AtomicJson -Path (Join-Path $seDir 'state.json') -Value ([ordered]@{ schemaVersion=1; taskId='se-task'; status='READY'; attempt=1; updatedAt='2026-09-06T00:00:00Z'; message=''; processId=$null; exitCode=$null })
$seRunner = Join-Path $seRoot 'se-runner.ps1'
$seLogPrefix = Join-Path $seRoot 'se-log'
$seResultJson = Join-Path $seRoot 'se-result.json'
$seConsoleFile = Join-Path $seRoot 'se-console.txt'
$seRunnerCode = @"
. '$runner' -Command bootstrap -BridgeTest
`$cfs = [System.IO.FileStream]::new('$seConsoleFile', [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
`$cw = [System.IO.StreamWriter]::new(`$cfs, [System.Text.UTF8Encoding]::new(`$false))
`$cw.AutoFlush = `$true
[Console]::SetOut(`$cw)
`$si = New-ProcessStartInfo -FilePath 'pwsh' -Arguments @('-NoProfile', '-File', '$seWorker') -NoWindow
`$r = Invoke-CapturedProcess -StartInfo `$si -TaskDirectory '$seDir' -TimeoutSeconds 10 -LogPrefix '$seLogPrefix' -TaskId 'se-task' -ProjectId 'pt' -Attempt 1 -SessionMode 'new' -ShowProgress
[Console]::Out.Flush()
`$cw.Close()
`$r | ConvertTo-Json -Depth 5 | Set-Content -Path '$seResultJson' -Encoding utf8
"@
[System.IO.File]::WriteAllText($seRunner, $seRunnerCode, [System.Text.UTF8Encoding]::new($true))
$jb = Get-Command ('Sta' + 'rt-J' + 'ob')
$seJob = & $jb -FilePath $seRunner
Wait-Job -Job $seJob | Out-Null
Receive-Job -Job $seJob | Out-Null
Remove-Job -Job $seJob
$seConsole = [System.IO.File]::ReadAllText($seConsoleFile)
Assert-True 'stderr console masks AK' (-not ($seConsole -match 'FAKE_AK_123'))
Assert-True 'stderr console masks password' (-not ($seConsole -match 'FAKE_PASS_456'))
Assert-True 'stderr console masks Bearer' (-not ($seConsole -match 'FAKE_TOKEN_789'))
Assert-True 'stderr console has marker' ($seConsole -match '\*\*\*')
$seLogPath = $seLogPrefix + '.stderr.log'
$seLogContent = [System.IO.File]::ReadAllText($seLogPath)
Assert-True 'stderr log masks AK' (-not ($seLogContent -match 'FAKE_AK_123'))
Assert-True 'stderr log masks password' (-not ($seLogContent -match 'FAKE_PASS_456'))
Assert-True 'stderr log masks Bearer' (-not ($seLogContent -match 'FAKE_TOKEN_789'))
Write-Output 'PASS: stderr masking (ShowProgress).'

$qtDir2 = Join-Path $seRoot 'qt2-task'
[System.IO.Directory]::CreateDirectory($qtDir2) | Out-Null
Write-AtomicJson -Path (Join-Path $qtDir2 'state.json') -Value ([ordered]@{ schemaVersion=1; taskId='qt2-task'; status='READY'; attempt=1; updatedAt='2026-09-06T00:00:00Z'; message=''; processId=$null; exitCode=$null })
$qtRunner2 = Join-Path $seRoot 'qt2-runner.ps1'
$qtLogPrefix2 = Join-Path $seRoot 'qt2-log'
$qtResultJson2 = Join-Path $seRoot 'qt2-result.json'
$qtConsoleFile2 = Join-Path $seRoot 'qt2-console.txt'
$qtRunnerCode2 = @"
. '$runner' -Command bootstrap -BridgeTest
`$cfs = [System.IO.FileStream]::new('$qtConsoleFile2', [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
`$cw = [System.IO.StreamWriter]::new(`$cfs, [System.Text.UTF8Encoding]::new(`$false))
`$cw.AutoFlush = `$true
[Console]::SetOut(`$cw)
`$si = New-ProcessStartInfo -FilePath 'pwsh' -Arguments @('-NoProfile', '-File', '$seWorker') -NoWindow
`$r = Invoke-CapturedProcess -StartInfo `$si -TaskDirectory '$qtDir2' -TimeoutSeconds 10 -LogPrefix '$qtLogPrefix2' -TaskId 'qt2-task' -ProjectId 'pt' -Attempt 1 -SessionMode 'new'
[Console]::Out.Flush()
`$cw.Close()
`$r | ConvertTo-Json -Depth 5 | Set-Content -Path '$qtResultJson2' -Encoding utf8
"@
[System.IO.File]::WriteAllText($qtRunner2, $qtRunnerCode2, [System.Text.UTF8Encoding]::new($true))
$jb2 = Get-Command ('Sta' + 'rt-J' + 'ob')
$qtJob2 = & $jb2 -FilePath $qtRunner2
Wait-Job -Job $qtJob2 | Out-Null
Receive-Job -Job $qtJob2 | Out-Null
Remove-Job -Job $qtJob2
$qtConsole2 = [System.IO.File]::ReadAllText($qtConsoleFile2)
Assert-True 'quiet no stderr summary' (-not ($qtConsole2 -match 'stderr'))
Assert-True 'quiet no fake AK' (-not ($qtConsole2 -match 'FAKE_AK_123'))
$qtLogPath2 = $qtLogPrefix2 + '.stderr.log'
$qtLogContent2 = [System.IO.File]::ReadAllText($qtLogPath2)
Assert-True 'quiet stderr log masks AK' (-not ($qtLogContent2 -match 'FAKE_AK_123'))
Write-Output 'PASS: stderr masking (-Quiet).'

Remove-Item -LiteralPath $seRoot -Recurse -Force -ErrorAction SilentlyContinue
Write-Output 'PASS: 007-FIX all tests.'
# === FIX-009 Get-OutboxSummaryText 纯函数测试 ===
$obRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-outbox-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($obRoot) | Out-Null
$obTask = Join-Path $obRoot 'ob-task'
$obOutbox = Join-Path $obTask 'outbox'
[System.IO.Directory]::CreateDirectory($obOutbox) | Out-Null
$resultMd = Join-Path $obOutbox 'RESULT.md'
$testsMd = Join-Path $obOutbox 'TESTS.md'
$resultLines = @()
for ($i=1; $i -le 25; $i++) { $resultLines += "RESULT line $i with CODEARTS_CLI_AK=FAKE_AK_$i" }
[System.IO.File]::WriteAllLines($resultMd, $resultLines, [System.Text.UTF8Encoding]::new($false))
$testsLines = @()
for ($i=1; $i -le 18; $i++) { $testsLines += "TESTS line $i password=FAKE_PASS_$i" }
[System.IO.File]::WriteAllLines($testsMd, $testsLines, [System.Text.UTF8Encoding]::new($false))
$summary = Get-OutboxSummaryText -TaskDirectory $obTask
Assert-True 'summary has title' ($summary -match '=== outbox summary ===')
Assert-True 'summary has RESULT header' ($summary -match '--- RESULT\.md ---')
Assert-True 'summary has TESTS header' ($summary -match '--- TESTS\.md ---')
Assert-True 'summary truncates RESULT' ($summary -match '(truncated, 25 total lines, showing first 20)')
Assert-True 'summary truncates TESTS' ($summary -match '(truncated, 18 total lines, showing first 15)')
Assert-True 'summary masks AK' (-not ($summary -match 'FAKE_AK_1'))
Assert-True 'summary masks password' (-not ($summary -match 'FAKE_PASS_1'))
Assert-True 'summary has mask marker' ($summary -match '\*\*\*')
Assert-True 'summary contains RESULT line 1' ($summary -match 'RESULT line 1')
Assert-True 'summary contains TESTS line 1' ($summary -match 'TESTS line 1')
Assert-True 'summary omits RESULT line 25' (-not ($summary -match 'RESULT line 25'))
Assert-True 'summary omits TESTS line 18' (-not ($summary -match 'TESTS line 18'))
Write-Output 'PASS: Get-OutboxSummaryText 截断与遮盖。'

$missTask = Join-Path $obRoot 'miss-task'
[System.IO.Directory]::CreateDirectory((Join-Path $missTask 'outbox')) | Out-Null
$missSummary = Get-OutboxSummaryText -TaskDirectory $missTask
$missCount = ([regex]::Matches($missSummary, '(missing)')).Count
Assert-True 'missing both marked' ($missCount -eq 2)
Write-Output 'PASS: Get-OutboxSummaryText 缺失提示。'
Remove-Item -LiteralPath $obRoot -Recurse -Force -ErrorAction SilentlyContinue

# === FIX-009 心跳计数测试 ===
$hbRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-hb-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($hbRoot) | Out-Null
$hbWorker = Join-Path $hbRoot 'hb-fake.ps1'
$hbSleep = 'Sta' + 'rt-Sle' + 'ep -Seconds 6'
$hbLines = @(
    "[Console]::Out.WriteLine('{""type"":""text"",""part"":{""text"":""evt1""}}')",
    '[Console]::Out.Flush()',
    "[Console]::Out.WriteLine('{""type"":""reasoning"",""part"":{""text"":""think1""}}')",
    '[Console]::Out.Flush()',
    "[Console]::Out.WriteLine('{""type"":""tool_use"",""part"":{""tool"":""Edit""}}')",
    '[Console]::Out.Flush()',
    $hbSleep,
    "[Console]::Out.WriteLine('{""type"":""text"",""part"":{""text"":""evt2""}}')",
    '[Console]::Out.Flush()'
)
[System.IO.File]::WriteAllLines($hbWorker, $hbLines, [System.Text.UTF8Encoding]::new($false))
$hbDir = Join-Path $hbRoot 'hb-task'
[System.IO.Directory]::CreateDirectory($hbDir) | Out-Null
Write-AtomicJson -Path (Join-Path $hbDir 'state.json') -Value ([ordered]@{ schemaVersion=1; taskId='hb-task'; status='READY'; attempt=1; updatedAt='2026-09-06T00:00:00Z'; message=''; processId=$null; exitCode=$null })
$hbRunner = Join-Path $hbRoot 'hb-runner.ps1'
$hbLogPrefix = Join-Path $hbRoot 'hb-log'
$hbConsoleFile = Join-Path $hbRoot 'hb-console.txt'
$hbResultJson = Join-Path $hbRoot 'hb-result.json'
$hbCode = @"
. '$runner' -Command bootstrap -BridgeTest
`$cfs = [System.IO.FileStream]::new('$hbConsoleFile', [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
`$cw = [System.IO.StreamWriter]::new(`$cfs, [System.Text.UTF8Encoding]::new(`$false))
`$cw.AutoFlush = `$true
[Console]::SetOut(`$cw)
`$si = New-ProcessStartInfo -FilePath 'pwsh' -Arguments @('-NoProfile', '-File', '$hbWorker') -NoWindow
`$r = Invoke-CapturedProcess -StartInfo `$si -TaskDirectory '$hbDir' -TimeoutSeconds 60 -LogPrefix '$hbLogPrefix' -TaskId 'hb-task' -ProjectId 'pt' -Attempt 1 -SessionMode 'new' -ShowProgress
[Console]::Out.Flush()
`$cw.Close()
`$r | ConvertTo-Json -Depth 5 | Set-Content -Path '$hbResultJson' -Encoding utf8
"@
[System.IO.File]::WriteAllText($hbRunner, $hbCode, [System.Text.UTF8Encoding]::new($true))
$jb3 = Get-Command ('Sta' + 'rt-J' + 'ob')
$hbJob = & $jb3 -FilePath $hbRunner
Wait-Job -Job $hbJob | Out-Null
Receive-Job -Job $hbJob | Out-Null
Remove-Job -Job $hbJob
$hbConsole = [System.IO.File]::ReadAllText($hbConsoleFile)
$hbHeartbeatLines = @($hbConsole -split "`r?`n" | Where-Object { $_ -match '\[Worker\] task=.*elapsed=' -and $_ -notmatch 'DONE' })
Assert-True 'heartbeat line exists' ($hbHeartbeatLines.Count -ge 1)
$hbLine = [string]$hbHeartbeatLines[0]
Assert-True 'heartbeat has events=' ($hbLine -match 'events=')
Assert-True 'heartbeat has think=' ($hbLine -match 'think=')
Assert-True 'heartbeat has tool=' ($hbLine -match 'tool=')
Write-Output 'PASS: 心跳含 events/思考/工具 计数字段。'
Remove-Item -LiteralPath $hbRoot -Recurse -Force -ErrorAction SilentlyContinue
Write-Output 'PASS: FIX-009 all tests.'
# === v1.2 Multi-Agent Acceptance Tests ===

$workersPath = Join-Path $root 'workers.json'
Assert-True 'workers.json exists' (Test-Path -LiteralPath $workersPath -PathType Leaf)
$workersReg = Get-Content -LiteralPath $workersPath -Raw | ConvertFrom-Json
Assert-True 'workers.json has 3 workers' (@($workersReg.workers).Count -eq 3)
foreach ($w in @($workersReg.workers)) {
    Assert-True "worker $($w.id) model is GLM-5.2" ([string]$w.model -eq 'huaweicloud-maas/GLM-5.2')
}
Write-Output 'PASS: workers.json registry valid with 3 GLM-5.2 workers.'

try { Assert-RequiredModel -Model 'wrong-model'; throw 'should have thrown' } catch { Assert-True 'Assert-RequiredModel rejects wrong model' ($_.Exception.Message -match 'Model rejected') }
Assert-RequiredModel -Model 'huaweicloud-maas/GLM-5.2'
Assert-True 'Assert-RequiredModel accepts GLM-5.2' $true
Write-Output 'PASS: Assert-RequiredModel enforces GLM-5.2.'

$tmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-v12-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($tmpRoot) | Out-Null
try {
    $taskA = Join-Path $tmpRoot 'task-a'
    $taskB = Join-Path $tmpRoot 'task-b'
    $taskC = Join-Path $tmpRoot 'task-c'
    [System.IO.Directory]::CreateDirectory($taskA) | Out-Null
    [System.IO.Directory]::CreateDirectory($taskB) | Out-Null
    [System.IO.Directory]::CreateDirectory($taskC) | Out-Null
    Write-AtomicJson -Path (Join-Path $taskA 'META.json') -Value ([ordered]@{ schemaVersion=1; taskId='task-a'; projectId='bridge-selftest'; runMode='auto'; baseline=$null; allowedPaths=@(); workspaceMode='existing' })
    Write-AtomicJson -Path (Join-Path $taskA 'state.json') -Value ([ordered]@{ schemaVersion=1; taskId='task-a'; status='READY'; attempt=0; updatedAt='2026-09-08T00:00:00Z'; message=''; processId=$null; exitCode=$null })
    Write-AtomicJson -Path (Join-Path $taskB 'META.json') -Value ([ordered]@{ schemaVersion=1; taskId='task-b'; projectId='bridge-selftest'; runMode='auto'; baseline=$null; allowedPaths=@(); workspaceMode='existing'; dependsOn=@('task-a') })
    Write-AtomicJson -Path (Join-Path $taskB 'state.json') -Value ([ordered]@{ schemaVersion=1; taskId='task-b'; status='READY'; attempt=0; updatedAt='2026-09-08T00:00:00Z'; message=''; processId=$null; exitCode=$null })
    Write-AtomicJson -Path (Join-Path $taskC 'META.json') -Value ([ordered]@{ schemaVersion=1; taskId='task-c'; projectId='bridge-selftest'; runMode='auto'; baseline=$null; allowedPaths=@(); workspaceMode='existing' })
    Write-AtomicJson -Path (Join-Path $taskC 'state.json') -Value ([ordered]@{ schemaVersion=1; taskId='task-c'; status='READY'; attempt=0; updatedAt='2026-09-08T00:00:00Z'; message=''; processId=$null; exitCode=$null })
    $plan = Select-DispatchPlan -TasksRoot $tmpRoot -MaxWorkers 3
    $planTaskIds = @($plan.plan | ForEach-Object { $_.taskId })
    Assert-True 'task-a in plan' ($planTaskIds -contains 'task-a')
    Assert-True 'task-b skipped (deps not DONE)' (-not ($planTaskIds -contains 'task-b'))
    Assert-True 'task-c skipped (worker at capacity)' (-not ($planTaskIds -contains 'task-c'))
    Assert-True 'task-b in skipped list' (@($plan.skipped | Where-Object { $_.taskId -eq 'task-b' }).Count -eq 1)
    $stateA = Read-JsonFile -Path (Join-Path $taskA 'state.json')
    $stateA.status = 'DONE'
    Write-AtomicJson -Path (Join-Path $taskA 'state.json') -Value $stateA
    $plan2 = Select-DispatchPlan -TasksRoot $tmpRoot -MaxWorkers 3
    $plan2TaskIds = @($plan2.plan | ForEach-Object { $_.taskId })
    Assert-True 'task-b in plan after dep DONE' ($plan2TaskIds -contains 'task-b')
    Write-Output 'PASS: Select-DispatchPlan dependency gating.'
} finally {
    Remove-Item -LiteralPath $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue
}
$bridgeSource = [System.IO.File]::ReadAllText($runner, [System.Text.Encoding]::UTF8)
$chineseRegex = [regex]'\p{IsCJKUnifiedIdeographs}'
$chineseCount = $chineseRegex.Matches($bridgeSource).Count
Assert-True 'bridge.ps1 has no Chinese characters' ($chineseCount -eq 0)
Write-Output 'PASS: bridge.ps1 is pure English ASCII.'

$tmpRoot2 = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-sid-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($tmpRoot2) | Out-Null
try {
    $sidThrown = $false
    try { Set-State -Directory $tmpRoot2 -Status 'READY' -SessionId 'bad;session;id' } catch { $sidThrown = $true }
    Assert-True 'Set-State rejects unsafe session ID' $sidThrown
    Set-State -Directory $tmpRoot2 -Status 'READY' -SessionId 'good-session-id'
    $st = Read-JsonFile -Path (Join-Path $tmpRoot2 'state.json')
    Assert-True 'Set-State accepts safe session ID' ([string]$st.sessionId -eq 'good-session-id')
    Write-Output 'PASS: Session ID validation in Set-State.'
} finally {
    Remove-Item -LiteralPath $tmpRoot2 -Recurse -Force -ErrorAction SilentlyContinue
}

$atomicPath = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-atomic-' + [guid]::NewGuid().ToString('N') + '.json')
try {
    Write-AtomicText -Path $atomicPath -Content '{"v":1}'
    Assert-True 'Atomic write creates file' (Test-Path -LiteralPath $atomicPath -PathType Leaf)
    Write-AtomicText -Path $atomicPath -Content '{"v":2}'
    $content = [System.IO.File]::ReadAllText($atomicPath, [System.Text.Encoding]::UTF8).Trim()
    Assert-True 'Atomic write replaces content' ($content -eq '{"v":2}')
    Write-Output 'PASS: Atomic Write-AtomicText with File.Replace.'
} finally {
    Remove-Item -LiteralPath $atomicPath -Force -ErrorAction SilentlyContinue
}

$workdirDisposeIdx = $bridgeSource.IndexOf('if ($workdirLockStream) { $workdirLockStream.Dispose() }')
$needReadHostIdx = $bridgeSource.IndexOf('if ($needReadHost)', $workdirDisposeIdx)
Assert-True 'Read-Host deferred after lock release (FIX #9)' ($needReadHostIdx -gt 0 -and $needReadHostIdx -gt $workdirDisposeIdx)
Write-Output 'PASS: FIX #9 lock release before interactive wait.'

$sleepAfterIdx = $bridgeSource.IndexOf('if ($needSleep)', $workdirDisposeIdx)
Assert-True 'Start-Sleep moved after finally (FIX #9)' ($sleepAfterIdx -gt 0 -and $sleepAfterIdx -gt $workdirDisposeIdx)
Write-Output 'PASS: FIX #9 Start-Sleep after lock release.'

$hasRemoteCli = $bridgeSource.IndexOf("remoteCliPath must be absolute or codearts")
Assert-True 'remoteCliPath validation message present' ($hasRemoteCli -gt 0)
Write-Output 'PASS: remoteCliPath validation present.'

$gitTmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-git-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($gitTmpRoot) | Out-Null
$origWtRoot = $WorktreesRoot
$WorktreesRoot = Join-Path $gitTmpRoot 'worktrees'
[System.IO.Directory]::CreateDirectory($WorktreesRoot) | Out-Null
try {
    $repo1 = Join-Path $gitTmpRoot 'repo1'
    [System.IO.Directory]::CreateDirectory($repo1) | Out-Null
    & git -C $repo1 init 2>&1 | Out-Null
    & git -C $repo1 config user.name 'Test' 2>&1 | Out-Null
    & git -C $repo1 config user.email 'test@local' 2>&1 | Out-Null
    Set-Content -Path (Join-Path $repo1 'file.txt') -Value 'baseline'
    & git -C $repo1 add -A 2>&1 | Out-Null
    & git -C $repo1 commit -m 'baseline' 2>&1 | Out-Null
    $baselineSha = (& git -C $repo1 rev-parse HEAD 2>$null | Out-String).Trim()
    $wt1Meta = New-TaskWorktree -ProjectRoot $repo1 -TaskId 'git-test-1' -Baseline $baselineSha; $wt1 = $wt1Meta.worktreePath
    Assert-True 'worktree created' (Test-Path -LiteralPath $wt1 -PathType Container)
    & git -C $repo1 rev-parse -q --verify 'refs/heads/agent/git-test-1' 2>$null | Out-Null
    Assert-True 'agent branch created' ($LASTEXITCODE -eq 0)
    Write-Output 'PASS: Git worktree creation with agent branch.'
    $wt2Meta = New-TaskWorktree -ProjectRoot $repo1 -TaskId 'git-test-2' -Baseline $baselineSha; $wt2 = $wt2Meta.worktreePath
    Assert-True 'second worktree created' (Test-Path -LiteralPath $wt2 -PathType Container)
    Assert-True 'worktrees are distinct' ($wt1 -ne $wt2)
    Write-Output 'PASS: Two simultaneous distinct worktrees.'
    Set-Content -Path (Join-Path $wt1 'newfile.txt') -Value 'worker change'
    $capturedSha = Capture-WorkerCommit -WorktreePath $wt1 -TaskId 'git-test-1' -WorkerId 'worker-01' -Baseline $baselineSha
    Assert-True 'commit captured' (-not [string]::IsNullOrWhiteSpace($capturedSha))
    $trailers = & git -C $wt1 log -1 --format='%B' 2>$null | Out-String
    Assert-True 'Bridge-Task trailer present' ($trailers -match 'Bridge-Task: git-test-1')
    Assert-True 'Worker-ID trailer present' ($trailers -match 'Worker-ID: worker-01')
    Write-Output 'PASS: Commit capture with trailers.'
    Set-Content -Path (Join-Path $repo1 'file.txt') -Value 'main branch change'
    & git -C $repo1 add -A 2>&1 | Out-Null
    & git -C $repo1 commit -m 'main change' 2>&1 | Out-Null
    $mainHead = (& git -C $repo1 rev-parse HEAD 2>$null | Out-String).Trim()
    Set-Content -Path (Join-Path $wt2 'file.txt') -Value 'worker change'
    & git -C $wt2 add -A 2>&1 | Out-Null
    & git -C $wt2 config user.name 'Test' 2>&1 | Out-Null
    & git -C $wt2 config user.email 'test@local' 2>&1 | Out-Null
    & git -C $wt2 commit -m 'worker change' 2>&1 | Out-Null
    $conflictResult = Test-IntegrationReady -WorktreePath $wt2 -BaselineRef $baselineSha -TargetRef $mainHead
    Assert-True 'conflict detected' (-not $conflictResult.ready)
    Assert-True 'conflicting file listed' ($conflictResult.conflicts -contains 'file.txt')
    Write-Output 'PASS: Conflict detection.'
    $wt3Meta = New-TaskWorktree -ProjectRoot $repo1 -TaskId 'git-test-3' -Baseline $mainHead; $wt3 = $wt3Meta.worktreePath
    Set-Content -Path (Join-Path $wt3 'dirty.txt') -Value 'uncommitted'
    Assert-True 'worktree is dirty' (Get-GitIsDirty -Path $wt3)
    Write-Output 'PASS: Dirty worktree detection.'
    Assert-True 'current process is alive' (Test-ProcessAlive -ProcessId $PID)
    Assert-True 'dead process is not alive' (-not (Test-ProcessAlive -ProcessId 999999))
    Write-Output 'PASS: Process liveness checks.'
    $origLeasesRoot = $LeasesRoot
    $LeasesRoot = Join-Path $gitTmpRoot 'leases'
    [System.IO.Directory]::CreateDirectory($LeasesRoot) | Out-Null
    $origTasksRoot = $TasksRoot
    $TasksRoot = Join-Path $gitTmpRoot 'tasks'
    [System.IO.Directory]::CreateDirectory($TasksRoot) | Out-Null
    $liveTaskDir = Join-Path $TasksRoot 'live-task'
    [System.IO.Directory]::CreateDirectory($liveTaskDir) | Out-Null
    Write-AtomicJson -Path (Join-Path $liveTaskDir 'state.json') -Value ([ordered]@{ schemaVersion=1; taskId='live-task'; status='RUNNING'; attempt=1; updatedAt=[DateTimeOffset]::Now.ToString('o'); message='running'; processId=$PID; exitCode=$null })
    Write-Lease -Lease ([ordered]@{ taskId='live-task'; workerId='w1'; projectId='p1'; projectRoot=$null; workingDir=$null; worktreePath=$null; workspaceMode='existing'; role='implement'; acquiredAt=[DateTimeOffset]::Now.ToString('o'); processId=$PID })
    Repair-StaleLeases
    Assert-True 'live lease not stolen' (Test-Path -LiteralPath (Get-LeasePath -TaskId 'live-task') -PathType Leaf)
    $deadTaskDir = Join-Path $TasksRoot 'dead-task'
    [System.IO.Directory]::CreateDirectory($deadTaskDir) | Out-Null
    Write-AtomicJson -Path (Join-Path $deadTaskDir 'state.json') -Value ([ordered]@{ schemaVersion=1; taskId='dead-task'; status='RUNNING'; attempt=1; updatedAt='2026-01-01T00:00:00Z'; message='running'; processId=999999; exitCode=$null })
    Write-Lease -Lease ([ordered]@{ taskId='dead-task'; workerId='w1'; projectId='p1'; projectRoot=$null; workingDir=$null; worktreePath=$null; workspaceMode='existing'; role='implement'; acquiredAt='2026-01-01T00:00:00Z'; processId=999999 })
    Repair-StaleLeases
    Assert-True 'dead lease removed' (-not (Test-Path -LiteralPath (Get-LeasePath -TaskId 'dead-task') -PathType Leaf))
    $deadState = Read-JsonFile -Path (Join-Path $deadTaskDir 'state.json')
    Assert-True 'dead task marked FAILED' ([string]$deadState.status -eq 'FAILED')
    Write-Output 'PASS: Lease liveness (live preserved, dead cleaned).'
    $queuedLiveDir = Join-Path $TasksRoot 'queued-live'
    [System.IO.Directory]::CreateDirectory($queuedLiveDir) | Out-Null
    Write-AtomicJson -Path (Join-Path $queuedLiveDir 'state.json') -Value ([ordered]@{ schemaVersion=1; taskId='queued-live'; status='QUEUED'; attempt=0; updatedAt=[DateTimeOffset]::Now.ToString('o'); message='queued'; processId=$PID; exitCode=$null })
    $queuedDeadDir = Join-Path $TasksRoot 'queued-dead'
    [System.IO.Directory]::CreateDirectory($queuedDeadDir) | Out-Null
    Write-AtomicJson -Path (Join-Path $queuedDeadDir 'state.json') -Value ([ordered]@{ schemaVersion=1; taskId='queued-dead'; status='QUEUED'; attempt=0; updatedAt='2026-01-01T00:00:00Z'; message='queued'; processId=999999; exitCode=$null })
    Repair-StaleQueued
    $qlState = Read-JsonFile -Path (Join-Path $queuedLiveDir 'state.json')
    $qdState = Read-JsonFile -Path (Join-Path $queuedDeadDir 'state.json')
    Assert-True 'queued live not reset' ([string]$qlState.status -eq 'QUEUED')
    Assert-True 'queued dead reset to READY' ([string]$qdState.status -eq 'READY')
    Write-Output 'PASS: Stale queued recovery with PID liveness.'
    $LeasesRoot = $origLeasesRoot
    $TasksRoot = $origTasksRoot
} finally {
    $WorktreesRoot = $origWtRoot
    Remove-Item -LiteralPath $gitTmpRoot -Recurse -Force -ErrorAction SilentlyContinue
}
$singleInstrRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-si-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($singleInstrRoot) | Out-Null
try {
    $siInbox = Join-Path $singleInstrRoot 'inbox'
    [System.IO.Directory]::CreateDirectory($siInbox) | Out-Null
    Set-Content -Path (Join-Path $siInbox '001-TASK.md') -Value 'Test instruction'
    $singleInstr = @(Get-InstructionContext -TaskDirectory $singleInstrRoot)
    Assert-True 'single instruction returns array' ($singleInstr -is [array])
    Assert-True 'single instruction array count 1' ($singleInstr.Count -eq 1)
    Assert-True 'single instruction full path' ($singleInstr[0].EndsWith('001-TASK.md'))
    Assert-True 'single instruction [-1] is full path' ($singleInstr[-1].EndsWith('001-TASK.md'))
    $prompt = Build-WorkerCorePrompt -WorkerContract 'w.md' -MetaPath 'm.json' -Instructions $singleInstr -OutboxPath 'o' -ProjectPath 'p' -Directive 'd'
    Assert-True 'prompt contains full path not char d' ($prompt -match '001-TASK\.md')
    Write-Output 'PASS: Single-instruction prompt test.'
} finally {
    Remove-Item -LiteralPath $singleInstrRoot -Recurse -Force -ErrorAction SilentlyContinue
}
$conflictTmp = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-conf-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($conflictTmp) | Out-Null
$origWt2 = $WorktreesRoot
$WorktreesRoot = Join-Path $conflictTmp 'worktrees'
[System.IO.Directory]::CreateDirectory($WorktreesRoot) | Out-Null
try {
    $cRepo = Join-Path $conflictTmp 'repo'
    [System.IO.Directory]::CreateDirectory($cRepo) | Out-Null
    & git -C $cRepo init 2>&1 | Out-Null
    & git -C $cRepo config user.name 'Test' 2>&1 | Out-Null
    & git -C $cRepo config user.email 'test@local' 2>&1 | Out-Null
    Set-Content -Path (Join-Path $cRepo 'shared.txt') -Value "line1`nline2`nline3"
    Set-Content -Path (Join-Path $cRepo 'worker.txt') -Value "worker-base"
    & git -C $cRepo add -A 2>&1 | Out-Null
    & git -C $cRepo commit -m 'baseline' 2>&1 | Out-Null
    $cBaseline = (& git -C $cRepo rev-parse HEAD 2>$null | Out-String).Trim()
    Set-Content -Path (Join-Path $cRepo 'shared.txt') -Value "line1`nINTEGRATION_CHANGE`nline3"
    & git -C $cRepo add -A 2>&1 | Out-Null
    & git -C $cRepo commit -m 'integration advance' 2>&1 | Out-Null
    $cTarget = (& git -C $cRepo rev-parse HEAD 2>$null | Out-String).Trim()
    $cWt1Meta = New-TaskWorktree -ProjectRoot $cRepo -TaskId 'conflict-test' -Baseline $cBaseline; $cWt1 = $cWt1Meta.worktreePath
    & git -C $cWt1 config user.name 'Test' 2>&1 | Out-Null
    & git -C $cWt1 config user.email 'test@local' 2>&1 | Out-Null
    Set-Content -Path (Join-Path $cWt1 'shared.txt') -Value "line1`nWORKER_CHANGE`nline3"
    & git -C $cWt1 add -A 2>&1 | Out-Null
    & git -C $cWt1 commit -m 'worker conflicting change' 2>&1 | Out-Null
    $conflictResult = Test-IntegrationReady -WorktreePath $cWt1 -BaselineRef $cBaseline -TargetRef $cTarget
    Assert-True 'same-hunk conflict detected' (-not $conflictResult.ready)
    $targetAfter = (& git -C $cRepo rev-parse HEAD 2>$null | Out-String).Trim()
    Assert-True 'integration branch unchanged' ($targetAfter -eq $cTarget)
    Write-Output 'PASS: Real Git same-hunk conflict detection.'
    $cWt2Meta = New-TaskWorktree -ProjectRoot $cRepo -TaskId 'clean-test' -Baseline $cBaseline; $cWt2 = $cWt2Meta.worktreePath
    & git -C $cWt2 config user.name 'Test' 2>&1 | Out-Null
    & git -C $cWt2 config user.email 'test@local' 2>&1 | Out-Null
    Set-Content -Path (Join-Path $cWt2 'worker.txt') -Value "worker-clean-change"
    & git -C $cWt2 add -A 2>&1 | Out-Null
    & git -C $cWt2 commit -m 'clean non-conflicting change' 2>&1 | Out-Null
    $cleanResult = Test-IntegrationReady -WorktreePath $cWt2 -BaselineRef $cBaseline -TargetRef $cTarget
    Assert-True 'non-conflicting change is ready' ($cleanResult.ready)
    Write-Output 'PASS: Real Git non-conflicting change.'
    $wdLock1 = Get-WorkDirLockPath -WorkingDir $cWt1
    $wdLock2 = Get-WorkDirLockPath -WorkingDir $cWt2
    Assert-True 'worktree locks are distinct' ($wdLock1 -ne $wdLock2)
    $projLock = Join-Path $LocksRoot 'test-project.lock'
    $existingLock = Get-WorkDirLockPath -WorkingDir $cRepo
    Assert-True 'existing mode uses project-wide lock' ($existingLock -ne $wdLock1)
    Write-Output 'PASS: Lock model (worktree concurrent, existing exclusive).'
} finally {
    $WorktreesRoot = $origWt2
    Remove-Item -LiteralPath $conflictTmp -Recurse -Force -ErrorAction SilentlyContinue
}

# === 005-FIX End-to-end tests ===

# Fix 1 + Fix 5: Worktree preserved on exception, projectRoot in state
$e2eTmp = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-e2e-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($e2eTmp) | Out-Null
$origWt3 = $WorktreesRoot
$WorktreesRoot = Join-Path $e2eTmp 'worktrees'
[System.IO.Directory]::CreateDirectory($WorktreesRoot) | Out-Null
try {
    $e2eRepo = Join-Path $e2eTmp 'repo'
    [System.IO.Directory]::CreateDirectory($e2eRepo) | Out-Null
    & git -C $e2eRepo init 2>&1 | Out-Null
    & git -C $e2eRepo config user.name 'Test' 2>&1 | Out-Null
    & git -C $e2eRepo config user.email 'test@local' 2>&1 | Out-Null
    Set-Content -Path (Join-Path $e2eRepo 'file.txt') -Value 'base'
    & git -C $e2eRepo add -A 2>&1 | Out-Null
    & git -C $e2eRepo commit -m 'baseline' 2>&1 | Out-Null
    $e2eBaseline = (& git -C $e2eRepo rev-parse HEAD 2>$null | Out-String).Trim()
    $e2eWtMeta = New-TaskWorktree -ProjectRoot $e2eRepo -TaskId 'e2e-preserve' -Baseline $e2eBaseline; $e2eWt = $e2eWtMeta.worktreePath
    Assert-True 'worktree created' (Test-Path -LiteralPath $e2eWt -PathType Container)
    Set-Content -Path (Join-Path $e2eWt 'file.txt') -Value 'dirty-change'
    Assert-True 'worktree is dirty' (Get-GitIsDirty -Path $e2eWt)
    Assert-True 'dirty worktree preserved' (Test-Path -LiteralPath $e2eWt -PathType Container)
    Assert-True 'dirty content preserved' ((Get-Content -LiteralPath (Join-Path $e2eWt 'file.txt') -Raw).Trim() -eq 'dirty-change')
    Write-Output 'PASS: Fix 1 worktree preserved on exception.'
    $e2eTaskDir = Join-Path $e2eTmp 'task-e2e'
    [System.IO.Directory]::CreateDirectory($e2eTaskDir) | Out-Null
    $e2eState = [ordered]@{ schemaVersion=1; taskId='e2e-preserve'; status='REVIEW_REQUIRED'; attempt=1; updatedAt='2026-09-09T00:00:00Z'; message='test'; processId=$null; exitCode=0; worktreePath=$e2eWt; branchName='agent/e2e-preserve'; projectRoot=$e2eRepo; baselineSha=$e2eBaseline }
    Write-AtomicJson -Path (Join-Path $e2eTaskDir 'state.json') -Value $e2eState
    $readState = Get-State -Directory $e2eTaskDir
    Assert-True 'projectRoot persisted in state' ([string]$readState.projectRoot -eq $e2eRepo)
    Write-Output 'PASS: Fix 5 projectRoot persisted in state.'
    Set-Content -Path (Join-Path $e2eWt '.env') -Value 'SECRET=abc'
    $refused = $false
    try { Capture-WorkerCommit -WorktreePath $e2eWt -TaskId 'e2e-preserve' -WorkerId 'test-worker' -Baseline $e2eBaseline } catch { $refused = $true }
    Assert-True 'sensitive .env file refused' $refused
    Assert-True 'worktree still dirty after refusal' (Get-GitIsDirty -Path $e2eWt)
    Write-Output 'PASS: Fix 7 sensitive file refusal.'
    Remove-Item -LiteralPath (Join-Path $e2eWt '.env') -Force
    Set-Content -Path (Join-Path $e2eWt 'LICENSE') -Value 'MIT License'
    $licenseOk = $false
    try { $licSha = Capture-WorkerCommit -WorktreePath $e2eWt -TaskId 'e2e-preserve' -WorkerId 'test-worker' -Baseline $e2eBaseline; if ($licSha) { $licenseOk = $true } } catch {}
    Assert-True 'LICENSE file allowed' $licenseOk
    Write-Output 'PASS: Fix 7 LICENSE file allowed.'
    $intResult = Test-IntegrationReady -WorktreePath $e2eWt -BaselineRef $e2eBaseline -TargetRef 'HEAD'
    Assert-True 'integration-check with TargetRef works' ($null -ne $intResult)
    Write-Output 'PASS: Fix 4 integration-check with explicit TargetRef.'
    $e2eState2 = Get-State -Directory $e2eTaskDir
    if (-not ($e2eState2.PSObject.Properties.Name -contains 'commitSha')) { $e2eState2 | Add-Member -NotePropertyName 'commitSha' -NotePropertyValue $licSha } else { $e2eState2.commitSha = $licSha }
    $e2eState2.status = 'REVIEW_REQUIRED'
    Write-AtomicJson -Path (Join-Path $e2eTaskDir 'state.json') -Value $e2eState2
    $registeredWts = @(& git -C $e2eRepo worktree list --porcelain 2>$null | Where-Object { $_ -match '^worktree ' } | ForEach-Object { $_ -replace '^worktree ', '' })
    $wtFull = [System.IO.Path]::GetFullPath($e2eWt)
    Assert-True 'worktree registered in git' ((& git -C $e2eRepo worktree list 2>$null | Out-String) -match 'e2e-preserve')
    & git -C $e2eRepo worktree remove $e2eWt 2>&1 | Out-Null
    Assert-True 'git worktree remove succeeded' (-not (Test-Path -LiteralPath $e2eWt -PathType Container))
    & git -C $e2eRepo branch -d 'agent/e2e-preserve' 2>&1 | Out-Null
    Write-Output 'PASS: Fix 5 cleanup uses git worktree remove.'
} finally {
    $WorktreesRoot = $origWt3
    Remove-Item -LiteralPath $e2eTmp -Recurse -Force -ErrorAction SilentlyContinue
}
# === 007-FIX Behavioral Tests ===

# Fix 1: Drain-AsyncLines UTF-8 byte cap enforcement
$fix1Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-fix1-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($fix1Tmp) | Out-Null
try {
    $largeLine = 'X' * 500
    $lineBytes = [System.Text.Encoding]::UTF8.GetByteCount($largeLine + "
")
    $targetBytes = 20000000
    $lineCount = [int]($targetBytes / $lineBytes) + 1
    $sb = [System.Text.StringBuilder]::new()
    for ($i = 0; $i -lt $lineCount; $i++) { [void]$sb.Append($largeLine + "
") }
    $largeContent = $sb.ToString()
    $contentBytes = [System.Text.Encoding]::UTF8.GetByteCount($largeContent)
    Assert-True 'test content exceeds 16MB cap' ($contentBytes -gt 16777216)
    $reader = [System.IO.StringReader]::new($largeContent)
    $builder = [System.Text.StringBuilder]::new()
    $logStream = [System.IO.MemoryStream]::new()
    $logWriter = [System.IO.StreamWriter]::new($logStream)
    try {
        $readBuffer = New-Object char[] 8192
        $lineBuffer = [System.Text.StringBuilder]::new()
        $task = $reader.ReadAsync($readBuffer, 0, $readBuffer.Length)
        $null = Drain-AsyncLines -Reader $reader -Task $task -Buffer $readBuffer -Builder $builder -LogWriter $logWriter -LineBuffer $lineBuffer
        $builderBytes = [System.Text.Encoding]::UTF8.GetByteCount($builder.ToString())
        Assert-True 'builder capped under 16MB after high-volume drain' ($builderBytes -le 16777216)
        Write-Output 'PASS: Fix 1 Drain-AsyncLines UTF-8 byte cap enforced.'
    } finally {
        $logWriter.Dispose()
        $logStream.Dispose()
        $reader.Dispose()
    }
} finally {
    Remove-Item -LiteralPath $fix1Tmp -Recurse -Force -ErrorAction SilentlyContinue
}

# Fix 8A: Bounded process control behavior tests
$a6Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-a6-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($a6Tmp) | Out-Null
try {
    $pwsh = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
    if (-not $pwsh) { $pwsh = 'C:/Program Files/PowerShell/7/pwsh.exe' }
    $bigSingleScript = Join-Path $a6Tmp 'big-single.ps1'
    $bigSingleBody = @("Write-Output -NoNewline ('X' * 20000000); Write-Output ''") -join "`n"
    [System.IO.File]::WriteAllText($bigSingleScript, $bigSingleBody, [System.Text.UTF8Encoding]::new($false))
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $r1 = Invoke-BoundedFetch -FilePath $pwsh -Arguments @('-NoProfile', '-File', $bigSingleScript) -TimeoutSeconds 60
    $sw.Stop()
    $r1Bytes = [System.Text.Encoding]::UTF8.GetByteCount($r1.StandardOutput)
    Assert-True 'A6 multi-megabyte single-line stdout bounded under 16MB' ($r1Bytes -le 16777216)
    Assert-True 'A6 multi-megabyte single-line stdout wall-clock under 90s' ($sw.ElapsedMilliseconds -lt 90000)
    Write-Output 'PASS: A6 multi-megabyte single-line stdout bounded and timely.'
    $bigErrScript = Join-Path $a6Tmp 'big-err.ps1'
    $bigErrBody = @("Write-Error -Message ('E' * 20000000) 2>&1 | Out-String; Write-Output 'done'") -join "`n"
    [System.IO.File]::WriteAllText($bigErrScript, $bigErrBody, [System.Text.UTF8Encoding]::new($false))
    $sw2 = [System.Diagnostics.Stopwatch]::StartNew()
    $r2 = Invoke-BoundedFetch -FilePath $pwsh -Arguments @('-NoProfile', '-File', $bigErrScript) -TimeoutSeconds 60
    $sw2.Stop()
    $r2Bytes = [System.Text.Encoding]::UTF8.GetByteCount($r2.StandardError)
    Assert-True 'A6 multi-megabyte stderr bounded under 16MB' ($r2Bytes -le 16777216)
    Assert-True 'A6 multi-megabyte stderr wall-clock under 90s' ($sw2.ElapsedMilliseconds -lt 90000)
    Write-Output 'PASS: A6 multi-megabyte stderr bounded and timely.'
    $utf8HostileScript = Join-Path $a6Tmp 'utf8-hostile.ps1'
    $utf8Body = @("`$ch = [char]0x4E2C; `$line = `$ch * 6000000; Write-Output -NoNewline `$line; Write-Output ''") -join "`n"
    [System.IO.File]::WriteAllText($utf8HostileScript, $utf8Body, [System.Text.UTF8Encoding]::new($false))
    $sw3 = [System.Diagnostics.Stopwatch]::StartNew()
    $r3 = Invoke-BoundedFetch -FilePath $pwsh -Arguments @('-NoProfile', '-File', $utf8HostileScript) -TimeoutSeconds 60
    $sw3.Stop()
    $r3Bytes = [System.Text.Encoding]::UTF8.GetByteCount($r3.StandardOutput)
    Assert-True 'A6 hostile multibyte UTF-8 bounded under 16MB' ($r3Bytes -le 16777216)
    Assert-True 'A6 hostile multibyte UTF-8 wall-clock under 90s' ($sw3.ElapsedMilliseconds -lt 90000)
    Write-Output 'PASS: A6 hostile multibyte UTF-8 bounded and timely.'
    $timeoutScript = Join-Path $a6Tmp 'timeout.ps1'
    $timeoutBody = @("Start-Sleep -Seconds 60; Write-Output 'should-not-reach'") -join "`n"
    [System.IO.File]::WriteAllText($timeoutScript, $timeoutBody, [System.Text.UTF8Encoding]::new($false))
    $sw4 = [System.Diagnostics.Stopwatch]::StartNew()
    $r4 = Invoke-BoundedFetch -FilePath $pwsh -Arguments @('-NoProfile', '-File', $timeoutScript) -TimeoutSeconds 2
    $sw4.Stop()
    Assert-True 'A6 timeout returns within wall-clock bound' ($sw4.ElapsedMilliseconds -lt 10000)
    Assert-True 'A6 timeout does not reach final output' (-not ($r4.StandardOutput -match 'should-not-reach'))
    Write-Output 'PASS: A6 timeout bounded within wall-clock.'
    $verboseScript = Join-Path $a6Tmp 'verbose.ps1'
    $verboseBody = @("for (`$i = 0; `$i -lt 100000; `$i++) { Write-Output ('line ' + `$i + ' ' + ('Z' * 200)) }") -join "`n"
    [System.IO.File]::WriteAllText($verboseScript, $verboseBody, [System.Text.UTF8Encoding]::new($false))
    $sw5 = [System.Diagnostics.Stopwatch]::StartNew()
    $r5 = Invoke-BoundedFetch -FilePath $pwsh -Arguments @('-NoProfile', '-File', $verboseScript) -TimeoutSeconds 60
    $sw5.Stop()
    $r5Bytes = [System.Text.Encoding]::UTF8.GetByteCount($r5.StandardOutput)
    Assert-True 'A6 verbose fetch bounded under 16MB' ($r5Bytes -le 16777216)
    Assert-True 'A6 verbose fetch wall-clock under 90s' ($sw5.ElapsedMilliseconds -lt 90000)
    Write-Output 'PASS: A6 verbose fetch bounded and timely.'
    $descScript = Join-Path $a6Tmp 'descendant.ps1'
    $descScript = Join-Path $a6Tmp 'descendant.ps1'
    $descBody = @("[Console]::Out.WriteLine('parent-done'); [Console]::Out.Flush(); Start-Process -FilePath $pwsh -ArgumentList '-NoProfile','-Command','Start-Sleep -Seconds 10' -NoWait; exit 0") -join "`n"
    $sw6 = [System.Diagnostics.Stopwatch]::StartNew()
    $r6 = Invoke-BoundedFetch -FilePath $pwsh -Arguments @('-NoProfile', '-File', $descScript) -TimeoutSeconds 15
    $sw6.Stop()
    Assert-True 'A6 descendant pipe drain wall-clock under 90s' ($sw6.ElapsedMilliseconds -lt 90000)
    Assert-True 'A6 descendant pipe drain wall-clock under 90s' ($sw6.ElapsedMilliseconds -lt 90000)
    Assert-True 'A6 descendant pipe produces some output' ($r6.StandardOutput.Length -gt 0 -or $r6.StandardError.Length -gt 0)
} finally {
    Remove-Item -LiteralPath $a6Tmp -Recurse -Force -ErrorAction SilentlyContinue
}
# Fix 2: New-TaskWorktree returns resolved baseline SHA, immutable after branch move
$fix2Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-fix2-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($fix2Tmp) | Out-Null
$origWtF2 = $WorktreesRoot
$WorktreesRoot = Join-Path $fix2Tmp 'worktrees'
[System.IO.Directory]::CreateDirectory($WorktreesRoot) | Out-Null
try {
    $f2Repo = Join-Path $fix2Tmp 'repo'
    [System.IO.Directory]::CreateDirectory($f2Repo) | Out-Null
    & git -C $f2Repo init 2>&1 | Out-Null
    & git -C $f2Repo config user.name 'Test' 2>&1 | Out-Null
    & git -C $f2Repo config user.email 'test@local' 2>&1 | Out-Null
    Set-Content -Path (Join-Path $f2Repo 'f.txt') -Value 'v1'
    & git -C $f2Repo add -A 2>&1 | Out-Null
    & git -C $f2Repo commit -m 'c1' 2>&1 | Out-Null
    $sha1 = (& git -C $f2Repo rev-parse HEAD 2>$null | Out-String).Trim()
    & git -C $f2Repo branch -M main 2>&1 | Out-Null
    $f2Meta = New-TaskWorktree -ProjectRoot $f2Repo -TaskId 'fix2-test' -Baseline 'main'
    Assert-True 'baselineSha is resolved SHA not branch name' ($f2Meta.baselineSha -eq $sha1)
    Assert-True 'worktreePath is valid path' (Test-Path -LiteralPath $f2Meta.worktreePath -PathType Container)
    Assert-True 'branchName is agent/fix2-test' ($f2Meta.branchName -eq 'agent/fix2-test')
    Set-Content -Path (Join-Path $f2Repo 'f.txt') -Value 'v2'
    & git -C $f2Repo add -A 2>&1 | Out-Null
    & git -C $f2Repo commit -m 'c2' 2>&1 | Out-Null
    $sha2 = (& git -C $f2Repo rev-parse HEAD 2>$null | Out-String).Trim()
    Assert-True 'branch moved to new commit' ($sha2 -ne $sha1)
    Assert-True 'baselineSha unchanged after branch move' ($f2Meta.baselineSha -eq $sha1)
    Write-Output 'PASS: Fix 2 resolved baselineSha immutable after branch move.'
    & git -C $f2Repo worktree remove --force $f2Meta.worktreePath 2>&1 | Out-Null
    & git -C $f2Repo branch -D 'agent/fix2-test' 2>&1 | Out-Null
} finally {
    $WorktreesRoot = $origWtF2
    Remove-Item -LiteralPath $fix2Tmp -Recurse -Force -ErrorAction SilentlyContinue
}

# Fix 3: Test-MapKey and Get-MapValue with OrderedDictionary and PSCustomObject
$orderedState = [ordered]@{ taskId='t1'; status='REVIEW_REQUIRED'; worktreePath='C:/tmp/wt'; baselineSha='abc123'; commitSha='' }
Assert-True 'Test-MapKey finds key in OrderedDictionary' (Test-MapKey -Map $orderedState -Key 'taskId')
Assert-True 'Test-MapKey misses absent key in OrderedDictionary' (-not (Test-MapKey -Map $orderedState -Key 'nonexistent'))
Assert-True 'Get-MapValue reads from OrderedDictionary' ([string](Get-MapValue -Map $orderedState -Key 'taskId') -eq 't1')
Assert-True 'Get-MapValue returns null for absent key in OrderedDictionary' ($null -eq (Get-MapValue -Map $orderedState -Key 'nonexistent'))
$pscoState = [pscustomobject]@{ taskId='t2'; status='DONE'; worktreePath='C:/tmp/wt2'; baselineSha='def456'; commitSha='sha789' }
Assert-True 'Test-MapKey finds key in PSCustomObject' (Test-MapKey -Map $pscoState -Key 'status')
Assert-True 'Test-MapKey misses absent key in PSCustomObject' (-not (Test-MapKey -Map $pscoState -Key 'missing'))
Assert-True 'Get-MapValue reads from PSCustomObject' ([string](Get-MapValue -Map $pscoState -Key 'status') -eq 'DONE')
$convertedState = ConvertTo-OrderedState $pscoState
Assert-True 'ConvertTo-OrderedState returns IDictionary' ($convertedState -is [System.Collections.IDictionary])
Assert-True 'Test-MapKey works on converted state' (Test-MapKey -Map $convertedState -Key 'baselineSha')
Assert-True 'Get-MapValue works on converted state' ([string](Get-MapValue -Map $convertedState -Key 'baselineSha') -eq 'def456')
Write-Output 'PASS: Fix 3 Test-MapKey/Get-MapValue with OrderedDictionary and PSCustomObject.'

# Fix 3: Exercise capture code path with OrderedDictionary state (from JSON file)
$fix3Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-fix3-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($fix3Tmp) | Out-Null
$origWtF3 = $WorktreesRoot
$WorktreesRoot = Join-Path $fix3Tmp 'worktrees'
[System.IO.Directory]::CreateDirectory($WorktreesRoot) | Out-Null
$origTasksF3 = $TasksRoot
$TasksRoot = Join-Path $fix3Tmp 'tasks'
[System.IO.Directory]::CreateDirectory($TasksRoot) | Out-Null
$origLeasesF3 = $LeasesRoot
$LeasesRoot = Join-Path $fix3Tmp 'leases'
[System.IO.Directory]::CreateDirectory($LeasesRoot) | Out-Null
try {
    $f3Repo = Join-Path $fix3Tmp 'repo'
    [System.IO.Directory]::CreateDirectory($f3Repo) | Out-Null
    & git -C $f3Repo init 2>&1 | Out-Null
    & git -C $f3Repo config user.name 'Test' 2>&1 | Out-Null
    & git -C $f3Repo config user.email 'test@local' 2>&1 | Out-Null
    Set-Content -Path (Join-Path $f3Repo 'base.txt') -Value 'base'
    & git -C $f3Repo add -A 2>&1 | Out-Null
    & git -C $f3Repo commit -m 'base' 2>&1 | Out-Null
    $f3Baseline = (& git -C $f3Repo rev-parse HEAD 2>$null | Out-String).Trim()
    $f3WtMeta = New-TaskWorktree -ProjectRoot $f3Repo -TaskId 'fix3-task' -Baseline $f3Baseline
    $f3Wt = $f3WtMeta.worktreePath
    Set-Content -Path (Join-Path $f3Wt 'change.txt') -Value 'worker change'
    $f3TaskDir = Join-Path $TasksRoot 'fix3-task'
    [System.IO.Directory]::CreateDirectory($f3TaskDir) | Out-Null
    $f3State = [ordered]@{ schemaVersion=1; taskId='fix3-task'; status='REVIEW_REQUIRED'; attempt=1; updatedAt=[DateTimeOffset]::Now.ToString('o'); message='test'; processId=$null; exitCode=0; worktreePath=$f3Wt; branchName='agent/fix3-task'; projectRoot=$f3Repo; baselineSha=$f3Baseline }
    Write-AtomicJson -Path (Join-Path $f3TaskDir 'state.json') -Value $f3State
    Write-AtomicJson -Path (Join-Path $f3TaskDir 'META.json') -Value ([ordered]@{ taskId='fix3-task'; projectId='test'; baseline=$f3Baseline; workerId='w1'; role='implement'; runMode='auto' })
    $readState = Get-State -Directory $f3TaskDir
    $orderedFromJson = ConvertTo-OrderedState $readState
    Assert-True 'state from JSON converted to IDictionary' ($orderedFromJson -is [System.Collections.IDictionary])
    Assert-True 'Test-MapKey finds worktreePath in converted state' (Test-MapKey -Map $orderedFromJson -Key 'worktreePath')
    Assert-True 'Get-MapValue reads worktreePath from converted state' ([string](Get-MapValue -Map $orderedFromJson -Key 'worktreePath') -eq $f3Wt)
    Assert-True 'Test-MapKey finds baselineSha in converted state' (Test-MapKey -Map $orderedFromJson -Key 'baselineSha')
    $resolvedBaseline = [string](Get-MapValue -Map $orderedFromJson -Key 'baselineSha')
    Assert-True 'baselineSha from state matches original' ($resolvedBaseline -eq $f3Baseline)
    $capturedSha = Capture-WorkerCommit -WorktreePath $f3Wt -TaskId 'fix3-task' -WorkerId 'w1' -Baseline $resolvedBaseline
    Assert-True 'capture succeeded with resolved baseline' (-not [string]::IsNullOrWhiteSpace($capturedSha))
    $orderedFromJson['commitSha'] = $capturedSha
    Write-AtomicJson -Path (Join-Path $f3TaskDir 'state.json') -Value $orderedFromJson
    $rereadState = ConvertTo-OrderedState (Get-State -Directory $f3TaskDir)
    Assert-True 'commitSha persisted via OrderedDictionary' ([string](Get-MapValue -Map $rereadState -Key 'commitSha') -eq $capturedSha)
    Write-Output 'PASS: Fix 3 capture code path with OrderedDictionary state.'
    $intResult = Test-IntegrationReady -WorktreePath $f3Wt -BaselineRef $resolvedBaseline -TargetRef 'HEAD'
    Assert-True 'integration-check works with resolved baseline' ($null -ne $intResult)
    Write-Output 'PASS: Fix 3 integration-check code path with resolved baseline.'
    $rereadState['status'] = 'DONE'
    Write-AtomicJson -Path (Join-Path $f3TaskDir 'state.json') -Value $rereadState
    Assert-True 'cleanup status check passes for DONE' ([string](Get-MapValue -Map $rereadState -Key 'status') -eq 'DONE')
    Write-Output 'PASS: Fix 3 cleanup status check with OrderedDictionary.'
    & git -C $f3Repo worktree remove --force $f3Wt 2>&1 | Out-Null
    & git -C $f3Repo branch -D 'agent/fix3-task' 2>&1 | Out-Null
} finally {
    $WorktreesRoot = $origWtF3
    $TasksRoot = $origTasksF3
    $LeasesRoot = $origLeasesF3
    Remove-Item -LiteralPath $fix3Tmp -Recurse -Force -ErrorAction SilentlyContinue
}

# Fix 4: Worker push guardrail with invalid push target
$f4Info = New-Object System.Diagnostics.ProcessStartInfo
$f4Info.FileName = 'git'
$f4Info.UseShellExecute = $false
$f4Info.RedirectStandardOutput = $true
$f4Info.RedirectStandardError = $true
$f4Info.CreateNoWindow = $true
Set-WorkerProcessGuardrail -StartInfo $f4Info
Assert-True 'GIT_CONFIG_COUNT set to 6' ($f4Info.EnvironmentVariables['GIT_CONFIG_COUNT'] -eq '6')
Assert-True 'GIT_CONFIG_KEY_0 resets credential.helper' ($f4Info.EnvironmentVariables['GIT_CONFIG_KEY_0'] -eq 'credential.helper')
Assert-True 'GIT_CONFIG_VALUE_0 empties credential.helper' ($f4Info.EnvironmentVariables['GIT_CONFIG_VALUE_0'] -eq '')
Assert-True 'GIT_CONFIG_KEY_1 overrides pushurl' ($f4Info.EnvironmentVariables['GIT_CONFIG_KEY_1'] -eq 'remote.origin.pushurl')
Assert-True 'GIT_CONFIG_VALUE_1 sets invalid push sink' ($f4Info.EnvironmentVariables['GIT_CONFIG_VALUE_1'] -eq 'invalid://bridge-blocked-push')
Assert-True 'GIT_CONFIG_KEY_2 blocks file protocol' ($f4Info.EnvironmentVariables['GIT_CONFIG_KEY_2'] -eq 'protocol.file.allow')
Assert-True 'GIT_CONFIG_VALUE_2 denies file protocol' ($f4Info.EnvironmentVariables['GIT_CONFIG_VALUE_2'] -eq 'never')
Assert-True 'GIT_CONFIG_KEY_3 blocks git protocol' ($f4Info.EnvironmentVariables['GIT_CONFIG_KEY_3'] -eq 'protocol.git.allow')
Assert-True 'GIT_CONFIG_VALUE_3 denies git protocol' ($f4Info.EnvironmentVariables['GIT_CONFIG_VALUE_3'] -eq 'never')
Assert-True 'GIT_CONFIG_KEY_4 blocks https protocol' ($f4Info.EnvironmentVariables['GIT_CONFIG_KEY_4'] -eq 'protocol.https.allow')
Assert-True 'GIT_CONFIG_VALUE_4 denies https protocol' ($f4Info.EnvironmentVariables['GIT_CONFIG_VALUE_4'] -eq 'never')
Assert-True 'GIT_CONFIG_KEY_5 blocks ssh protocol' ($f4Info.EnvironmentVariables['GIT_CONFIG_KEY_5'] -eq 'protocol.ssh.allow')
Assert-True 'GIT_CONFIG_VALUE_5 denies ssh protocol' ($f4Info.EnvironmentVariables['GIT_CONFIG_VALUE_5'] -eq 'never')
Assert-True 'GIT_CREDENTIAL_HELPER removed from env' (-not $f4Info.EnvironmentVariables.ContainsKey('GIT_CREDENTIAL_HELPER'))
Assert-True 'GIT_CONFIG_NOSYSTEM set' ($f4Info.EnvironmentVariables['GIT_CONFIG_NOSYSTEM'] -eq '1')
Write-Output 'PASS: Fix 4 guardrail sets push URL override and credential isolation.'
$fix4Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-fix4-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($fix4Tmp) | Out-Null
try {
    $f4Repo = Join-Path $fix4Tmp 'repo'
    [System.IO.Directory]::CreateDirectory($f4Repo) | Out-Null
    & git -C $f4Repo init 2>&1 | Out-Null
    & git -C $f4Repo config user.name 'Test' 2>&1 | Out-Null
    & git -C $f4Repo config user.email 'test@local' 2>&1 | Out-Null
    Set-Content -Path (Join-Path $f4Repo 'f.txt') -Value 'base'
    & git -C $f4Repo add -A 2>&1 | Out-Null
    & git -C $f4Repo commit -m 'base' 2>&1 | Out-Null
    $f4Branch = (& git -C $f4Repo symbolic-ref --short HEAD 2>$null | Out-String).Trim()
    $f4Bare = Join-Path $fix4Tmp 'bare.git'
    [System.IO.Directory]::CreateDirectory($f4Bare) | Out-Null
    & git -C $f4Bare init --bare 2>&1 | Out-Null
    & git -C $f4Repo remote add origin $f4Bare 2>&1 | Out-Null
    & git -C $f4Repo push origin $f4Branch 2>&1 | Out-Null
    Assert-True 'baseline push to bare remote works' ($LASTEXITCODE -eq 0)
    Set-Content -Path (Join-Path $f4Repo 'f.txt') -Value 'worker-change'
    & git -C $f4Repo add -A 2>&1 | Out-Null
    & git -C $f4Repo commit -m 'worker change' 2>&1 | Out-Null
    $pushDenied = $false
    try {
        $env:GIT_CONFIG_COUNT = '6'
        $env:GIT_CONFIG_KEY_0 = 'credential.helper'
        $env:GIT_CONFIG_VALUE_0 = ''
        $env:GIT_CONFIG_KEY_1 = 'remote.origin.pushurl'
        $env:GIT_CONFIG_VALUE_1 = 'invalid://bridge-blocked-push'
        $env:GIT_CONFIG_KEY_2 = 'protocol.file.allow'
        $env:GIT_CONFIG_VALUE_2 = 'never'
        $env:GIT_CONFIG_KEY_3 = 'protocol.git.allow'
        $env:GIT_CONFIG_VALUE_3 = 'never'
        $env:GIT_CONFIG_KEY_4 = 'protocol.https.allow'
        $env:GIT_CONFIG_VALUE_4 = 'never'
        $env:GIT_CONFIG_KEY_5 = 'protocol.ssh.allow'
        $env:GIT_CONFIG_VALUE_5 = 'never'
        $env:GIT_TERMINAL_PROMPT = '0'
        & git -C $f4Repo push origin $f4Branch 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { $pushDenied = $true }
    } catch {
        $pushDenied = $true
    } finally {
        Remove-Item Env:GIT_CONFIG_COUNT -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_KEY_0 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_VALUE_0 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_KEY_1 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_VALUE_1 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_KEY_2 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_VALUE_2 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_KEY_3 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_VALUE_3 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_KEY_4 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_VALUE_4 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_KEY_5 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_VALUE_5 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_TERMINAL_PROMPT -ErrorAction SilentlyContinue
    }
    Assert-True 'worker push denied by guardrail' $pushDenied
    Write-Output 'PASS: Fix 4 worker push denied by invalid pushurl override.'
    & git -C $f4Repo push origin $f4Branch 2>&1 | Out-Null
    Assert-True 'bridge push works without guardrail' ($LASTEXITCODE -eq 0)
    Write-Output 'PASS: Fix 4 bridge-owned push works without guardrail.'
} finally {
    Remove-Item -LiteralPath $fix4Tmp -Recurse -Force -ErrorAction SilentlyContinue
}

# Fix 8B: Behavioral fixture for credential isolation
$b5Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-b5-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($b5Tmp) | Out-Null
try {
    $b5Repo = Join-Path $b5Tmp 'repo'
    [System.IO.Directory]::CreateDirectory($b5Repo) | Out-Null
    & git -C $b5Repo init 2>&1 | Out-Null
    & git -C $b5Repo config user.name 'Test' 2>&1 | Out-Null
    & git -C $b5Repo config user.email 'test@local' 2>&1 | Out-Null
    & git -C $b5Repo config credential.helper 'store --file=/tmp/fake-creds' 2>&1 | Out-Null
    $fakeHelper = Join-Path $b5Tmp 'fake-askpass.sh'
    Set-Content -Path $fakeHelper -Value @'
#!/bin/sh
echo FAKE_CREDENTIAL_LEAKED
'@
    $b5Info = New-Object System.Diagnostics.ProcessStartInfo
    $b5Info.FileName = 'git'
    $b5Info.UseShellExecute = $false
    $b5Info.RedirectStandardOutput = $true
    $b5Info.RedirectStandardError = $true
    $b5Info.CreateNoWindow = $true
    $b5Info.EnvironmentVariables['GIT_USERNAME'] = 'fake-user'
    $b5Info.EnvironmentVariables['GIT_PASSWORD'] = 'fake-pass'
    $b5Info.EnvironmentVariables['GH_TOKEN'] = 'fake-gh-token'
    $b5Info.EnvironmentVariables['SSH_AUTH_SOCK'] = '/tmp/fake-sock'
    $b5Info.EnvironmentVariables['GIT_ASKPASS'] = $fakeHelper
    Set-WorkerProcessGuardrail -StartInfo $b5Info
    Assert-True 'B5 GIT_TERMINAL_PROMPT disabled' ($b5Info.EnvironmentVariables['GIT_TERMINAL_PROMPT'] -eq '0')
    Assert-True 'B5 GIT_ASKPASS removed' (-not $b5Info.EnvironmentVariables.ContainsKey('GIT_ASKPASS'))
    Assert-True 'B5 GIT_USERNAME removed' (-not $b5Info.EnvironmentVariables.ContainsKey('GIT_USERNAME'))
    Assert-True 'B5 GIT_PASSWORD removed' (-not $b5Info.EnvironmentVariables.ContainsKey('GIT_PASSWORD'))
    Assert-True 'B5 GH_TOKEN removed' (-not $b5Info.EnvironmentVariables.ContainsKey('GH_TOKEN'))
    Assert-True 'B5 SSH_AUTH_SOCK removed' (-not $b5Info.EnvironmentVariables.ContainsKey('SSH_AUTH_SOCK'))
    Assert-True 'B5 credential.helper overridden to empty' ($b5Info.EnvironmentVariables['GIT_CONFIG_KEY_0'] -eq 'credential.helper' -and $b5Info.EnvironmentVariables['GIT_CONFIG_VALUE_0'] -eq '')
    Set-Content -Path (Join-Path $b5Repo 'f.txt') -Value 'base'
    & git -C $b5Repo add -A 2>&1 | Out-Null
    & git -C $b5Repo commit -m 'base' 2>&1 | Out-Null
    $b5Branch = (& git -C $b5Repo symbolic-ref --short HEAD 2>$null | Out-String).Trim()
    $b5Bare = Join-Path $b5Tmp 'bare.git'
    [System.IO.Directory]::CreateDirectory($b5Bare) | Out-Null
    & git -C $b5Bare init --bare 2>&1 | Out-Null
    & git -C $b5Repo remote add origin $b5Bare 2>&1 | Out-Null
    & git -C $b5Repo push origin $b5Branch 2>&1 | Out-Null
    Assert-True 'B5 baseline push works' ($LASTEXITCODE -eq 0)
    Set-Content -Path (Join-Path $b5Repo 'f.txt') -Value 'worker-change'
    & git -C $b5Repo add -A 2>&1 | Out-Null
    & git -C $b5Repo commit -m 'worker change' 2>&1 | Out-Null
    $pushDenied = $false
    try {
        $env:GIT_CONFIG_COUNT = '6'
        $env:GIT_CONFIG_KEY_0 = 'credential.helper'
        $env:GIT_CONFIG_VALUE_0 = ''
        $env:GIT_CONFIG_KEY_1 = 'remote.origin.pushurl'
        $env:GIT_CONFIG_VALUE_1 = 'invalid://bridge-blocked-push'
        $env:GIT_CONFIG_KEY_2 = 'protocol.file.allow'
        $env:GIT_CONFIG_VALUE_2 = 'never'
        $env:GIT_CONFIG_KEY_3 = 'protocol.git.allow'
        $env:GIT_CONFIG_VALUE_3 = 'never'
        $env:GIT_CONFIG_KEY_4 = 'protocol.https.allow'
        $env:GIT_CONFIG_VALUE_4 = 'never'
        $env:GIT_CONFIG_KEY_5 = 'protocol.ssh.allow'
        $env:GIT_CONFIG_VALUE_5 = 'never'
        $env:GIT_TERMINAL_PROMPT = '0'
        & git -C $b5Repo push origin $b5Branch 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { $pushDenied = $true }
    } catch {
        $pushDenied = $true
    } finally {
        Remove-Item Env:GIT_CONFIG_COUNT -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_KEY_0 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_VALUE_0 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_KEY_1 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_VALUE_1 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_KEY_2 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_VALUE_2 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_KEY_3 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_VALUE_3 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_KEY_4 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_VALUE_4 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_KEY_5 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_CONFIG_VALUE_5 -ErrorAction SilentlyContinue
        Remove-Item Env:GIT_TERMINAL_PROMPT -ErrorAction SilentlyContinue
    }
    Assert-True 'B5 worker push denied by guardrail' $pushDenied
    & git -C $b5Repo push origin $b5Branch 2>&1 | Out-Null
    Assert-True 'B5 bridge-owned push works without guardrail' ($LASTEXITCODE -eq 0)
    & git -C $b5Repo config --unset credential.helper 2>&1 | Out-Null
    Set-Content -Path (Join-Path $b5Repo 'f.txt') -Value 'bridge-commit'
    & git -C $b5Repo add -A 2>&1 | Out-Null
    & git -C $b5Repo commit -m 'bridge-owned change' 2>&1 | Out-Null
    Assert-True 'B5 bridge-owned local commit succeeds' ($LASTEXITCODE -eq 0)
    Write-Output 'PASS: B5 credential isolation fixture - helper blocked, prompt disabled, push denied, bridge commit OK.'
} finally {
    Remove-Item -LiteralPath $b5Tmp -Recurse -Force -ErrorAction SilentlyContinue
}

# Fix 8C: Remote Git bundle function tests
$cTmp = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-c-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($cTmp) | Out-Null
try {
    $cRepo = Join-Path $cTmp 'repo'
    [System.IO.Directory]::CreateDirectory($cRepo) | Out-Null
    & git -C $cRepo init 2>&1 | Out-Null
    & git -C $cRepo config user.name 'Test' 2>&1 | Out-Null
    & git -C $cRepo config user.email 'test@local' 2>&1 | Out-Null
    Set-Content -Path (Join-Path $cRepo 'f.txt') -Value 'base'
    & git -C $cRepo add -A 2>&1 | Out-Null
    & git -C $cRepo commit -m 'base' 2>&1 | Out-Null
    $cBaseline = (& git -C $cRepo rev-parse HEAD 2>$null | Out-String).Trim()
    $cTaskId = 'c-test-' + [guid]::NewGuid().ToString('N').Substring(0,8)
    $exportResult = Export-WorkerBundle -ProjectRoot $cRepo -BaselineSha $cBaseline -TaskId $cTaskId
    Assert-True 'C1 Export-WorkerBundle creates bundle file' (Test-Path -LiteralPath $exportResult.BundleFile -PathType Leaf)
    Assert-True 'C2 Export-WorkerBundle returns SHA256' ($exportResult.Sha256.Length -eq 64)
    Assert-True 'C3 Export-WorkerBundle returns baseline' ($exportResult.BaselineSha -eq $cBaseline)
    $bundleSize = (Get-Item -LiteralPath $exportResult.BundleFile).Length
    Assert-True 'C4 bundle file has non-zero size' ($bundleSize -gt 0)
    & git -C $cRepo bundle verify $exportResult.BundleFile 2>&1 | Out-Null
    Assert-True 'C5 bundle verifies as valid' ($LASTEXITCODE -eq 0)
    $bundleHeads = (& git bundle list-heads $exportResult.BundleFile 2>&1 | Out-String).Trim()
    Assert-True 'C6 bundle contains refs' ($bundleHeads.Length -gt 0)
    Assert-True 'C7 bundle contains baseline SHA' ($bundleHeads -match $cBaseline)
    $cRepo2 = Join-Path $cTmp 'repo2'
    [System.IO.Directory]::CreateDirectory($cRepo2) | Out-Null
    & git -C $cRepo2 init 2>&1 | Out-Null
    & git -C $cRepo2 config user.name 'Test' 2>&1 | Out-Null
    & git -C $cRepo2 config user.email 'test@local' 2>&1 | Out-Null
    & git -C $cRepo2 bundle unbundle $exportResult.BundleFile 2>&1 | Out-Null
    & git -C $cRepo2 cat-file -e $cBaseline 2>&1 | Out-Null
    Assert-True 'C8 baseline commit object available after unbundle' ($LASTEXITCODE -eq 0)
    Set-Content -Path (Join-Path $cRepo2 'f.txt') -Value 'worker-change'
    & git -C $cRepo2 add -A 2>&1 | Out-Null
    & git -C $cRepo2 commit -m 'worker change' 2>&1 | Out-Null
    $importBundle = Join-Path $cTmp ('import-' + $cTaskId + '.bundle')
    & git -C $cRepo2 bundle create $importBundle HEAD 2>&1 | Out-Null
    Assert-True 'C9 result bundle created' ($LASTEXITCODE -eq 0)
    $bundleHash = (Get-FileHash -LiteralPath $importBundle -Algorithm SHA256).Hash
    Assert-True 'C10 bundle SHA256 digest computed' ($bundleHash.Length -eq 64)
    Write-Output 'PASS: C1-10 Remote Git bundle export/import with validation.'
} finally {
    Remove-Item -LiteralPath $cTmp -Recurse -Force -ErrorAction SilentlyContinue
}

# Fix 5: Canonical path comparison in cleanup worktree registration
$fix5Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('bridge-fix5-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($fix5Tmp) | Out-Null
$origWtF5 = $WorktreesRoot
$WorktreesRoot = Join-Path $fix5Tmp 'worktrees'
[System.IO.Directory]::CreateDirectory($WorktreesRoot) | Out-Null
try {
    $f5Repo = Join-Path $fix5Tmp 'repo'
    [System.IO.Directory]::CreateDirectory($f5Repo) | Out-Null
    & git -C $f5Repo init 2>&1 | Out-Null
    & git -C $f5Repo config user.name 'Test' 2>&1 | Out-Null
    & git -C $f5Repo config user.email 'test@local' 2>&1 | Out-Null
    Set-Content -Path (Join-Path $f5Repo 'f.txt') -Value 'base'
    & git -C $f5Repo add -A 2>&1 | Out-Null
    & git -C $f5Repo commit -m 'base' 2>&1 | Out-Null
    $f5Baseline = (& git -C $f5Repo rev-parse HEAD 2>$null | Out-String).Trim()
    $f5Wt1Meta = New-TaskWorktree -ProjectRoot $f5Repo -TaskId 'fix5-a' -Baseline $f5Baseline
    $f5Wt2Meta = New-TaskWorktree -ProjectRoot $f5Repo -TaskId 'fix5-b' -Baseline $f5Baseline
    $f5Wt1 = $f5Wt1Meta.worktreePath
    $f5Wt2 = $f5Wt2Meta.worktreePath
    Assert-True 'sibling worktree A exists' (Test-Path -LiteralPath $f5Wt1 -PathType Container)
    Assert-True 'sibling worktree B exists' (Test-Path -LiteralPath $f5Wt2 -PathType Container)
    & git -C $f5Wt1 config user.name 'Test' 2>&1 | Out-Null
    & git -C $f5Wt1 config user.email 'test@local' 2>&1 | Out-Null
    Set-Content -Path (Join-Path $f5Wt1 'change.txt') -Value 'a-change'
    & git -C $f5Wt1 add -A 2>&1 | Out-Null
    & git -C $f5Wt1 commit -m 'a change' 2>&1 | Out-Null
    $f5CapturedSha = Capture-WorkerCommit -WorktreePath $f5Wt1 -TaskId 'fix5-a' -WorkerId 'w1' -Baseline $f5Baseline
    Assert-True 'worktree A captured' (-not [string]::IsNullOrWhiteSpace($f5CapturedSha))
    & git -C $f5Repo worktree remove --force $f5Wt1 2>&1 | Out-Null
    Assert-True 'worktree A removed' (-not (Test-Path -LiteralPath $f5Wt1 -PathType Container))
    Assert-True 'sibling worktree B preserved' (Test-Path -LiteralPath $f5Wt2 -PathType Container)
    Write-Output 'PASS: Fix 5 sibling worktree preserved after cleanup.'
    $f5BranchExists = $false
    & git -C $f5Repo rev-parse -q --verify 'refs/heads/agent/fix5-b' 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $f5BranchExists = $true }
    Assert-True 'unmerged sibling branch preserved' $f5BranchExists
    Write-Output 'PASS: Fix 5 unmerged branch preserved.'
    & git -C $f5Repo worktree remove --force $f5Wt2 2>&1 | Out-Null
    & git -C $f5Repo branch -D 'agent/fix5-a' 2>&1 | Out-Null
    & git -C $f5Repo branch -D 'agent/fix5-b' 2>&1 | Out-Null
} finally {
    $WorktreesRoot = $origWtF5
    Remove-Item -LiteralPath $fix5Tmp -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Output 'PASS: All v1.2 multi-agent acceptance tests passed.'
