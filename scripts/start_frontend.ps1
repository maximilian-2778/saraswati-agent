# Start the React/Vite development server from the project root.
# Run npm install in the frontend directory before the first launch.
$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendPath = Join-Path $projectRoot "frontend"

if (-not (Test-Path -LiteralPath (Join-Path $frontendPath "node_modules"))) {
    throw "Frontend dependencies not found. Run npm install in frontend first."
}

Set-Location -LiteralPath $frontendPath
npm run dev
