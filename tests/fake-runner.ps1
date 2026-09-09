param(
    [int]$MaxWorkers = 3,
    [string]$StateDir = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$controlPath = Join-Path $StateDir 'fake-control.json'
if (Test-Path -LiteralPath $controlPath -PathType Leaf) {
    $control = Get-Content -LiteralPath $controlPath -Raw | ConvertFrom-Json
} else {
    $control = [pscustomobject]@{ exitCode = 0; marker = ''; stderrText = ''; sleepSeconds = 0 }
}

if ($control.PSObject.Properties.Name -contains 'sleepSeconds' -and [int]$control.sleepSeconds -gt 0) {
    Start-Sleep -Seconds ([int]$control.sleepSeconds)
}

if ($control.PSObject.Properties.Name -contains 'marker' -and $control.marker) {
    $dir = Split-Path -Parent $control.marker
    if ($dir) { [System.IO.Directory]::CreateDirectory($dir) | Out-Null }
    [System.IO.File]::WriteAllText($control.marker, 'ok')
}

if ($control.PSObject.Properties.Name -contains 'stderrText' -and $control.stderrText) {
    [Console]::Error.WriteLine($control.stderrText)
}

$exit = if ($control.PSObject.Properties.Name -contains 'exitCode' -and $control.exitCode) { [int]$control.exitCode } else { 0 }
exit $exit