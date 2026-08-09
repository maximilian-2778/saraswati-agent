# Start one FastAPI process from the project root.
# Avoid --reload on Windows because its worker can survive Ctrl+C.
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$backendPort = 8010

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Project virtual environment not found. Create .venv first."
}

# Probe the port first so duplicate servers cannot run at the same time.
$portProbe = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    $backendPort
)
try {
    $portProbe.Start()
}
catch {
    throw "Port $backendPort is already in use. Stop the old backend with Ctrl+C and try again."
}
finally {
    $portProbe.Stop()
}

Set-Location -LiteralPath $projectRoot
Write-Host "Backend: http://127.0.0.1:$backendPort"
$serverArguments = @(
    "-m", "uvicorn",
    "backend.main:app",
    "--host", "127.0.0.1",
    "--port", "$backendPort"
)
$serverProcess = Start-Process `
    -FilePath $pythonPath `
    -ArgumentList $serverArguments `
    -NoNewWindow `
    -PassThru

try {
    Wait-Process -Id $serverProcess.Id
}
finally {
    $remainingProcess = Get-Process -Id $serverProcess.Id -ErrorAction SilentlyContinue
    if ($remainingProcess) {
        Write-Host "Stopping backend process $($serverProcess.Id)..."
        Stop-Process -Id $serverProcess.Id -Force
        Wait-Process -Id $serverProcess.Id -ErrorAction SilentlyContinue
    }
}
