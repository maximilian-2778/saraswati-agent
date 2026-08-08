# Start the FastAPI development server from the project root.
# --reload restarts the server after Python source files change.
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Project virtual environment not found. Create .venv first."
}

Set-Location -LiteralPath $projectRoot
& $pythonPath -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
