# Start the FastAPI development server from the project root.
# Port 8010 avoids stale development processes left on port 8000.
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
& $pythonPath -m uvicorn backend.main:app --reload --host 127.0.0.1 --port $backendPort
