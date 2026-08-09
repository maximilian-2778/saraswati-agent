# Start the React/Vite development server from the project root.
$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendPath = Join-Path $projectRoot "frontend"
$frontendPort = 5180

if (-not (Test-Path -LiteralPath (Join-Path $frontendPath "node_modules"))) {
    throw "Frontend dependencies not found. Run npm install in the frontend directory."
}

$portProbe = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    $frontendPort
)
try {
    $portProbe.Start()
}
catch {
    throw "Port $frontendPort is already in use. Stop the old frontend with Ctrl+C and try again."
}
finally {
    $portProbe.Stop()
}

Set-Location -LiteralPath $frontendPath
Write-Host "Frontend: http://localhost:$frontendPort"
npm run dev
