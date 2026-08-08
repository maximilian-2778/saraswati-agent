# 从项目根目录启动 FastAPI 开发服务器。
# --reload 会在 Python 源码变化后自动重启服务。
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Project virtual environment not found. Create .venv first."
}

Set-Location -LiteralPath $projectRoot
& $pythonPath -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
