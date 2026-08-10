param(
    [string]$PythonPath = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot $PythonPath
$releaseDir = Join-Path $projectRoot "dist\SaraswatiAgent"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found: $python"
}

# Windows locks loaded .pyd/.dll files. Fail before building the frontend when an
# existing packaged client is still using the directory PyInstaller must replace.
$runningClients = @(
    Get-Process -Name "SaraswatiAgent" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Path -and
            $_.Path.StartsWith($releaseDir, [System.StringComparison]::OrdinalIgnoreCase)
        }
)
if ($runningClients.Count -gt 0) {
    $processIds = ($runningClients | ForEach-Object { $_.Id }) -join ", "
    throw "Saraswati Agent is running (PID: $processIds). Close every packaged SaraswatiAgent window, then run this script again."
}

Push-Location (Join-Path $projectRoot "frontend")
try {
    npm run build
}
finally {
    Pop-Location
}

Push-Location $projectRoot
try {
    & $python -m PyInstaller --noconfirm --clean SaraswatiAgent.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
}
finally {
    Pop-Location
}

Write-Host "Windows package created at: $releaseDir"
