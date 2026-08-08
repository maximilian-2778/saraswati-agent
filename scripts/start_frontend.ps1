# 从项目根目录启动 React/Vite 开发服务器。
$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendPath = Join-Path $projectRoot "frontend"

if (-not (Test-Path -LiteralPath (Join-Path $frontendPath "node_modules"))) {
    throw "Frontend dependencies not found. Run npm install in frontend first."
}

$existingListener = Get-NetTCPConnection -State Listen -LocalPort 5173 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existingListener) {
    Write-Host "前端已经在 http://localhost:5173 运行，请直接打开该地址。"
    Write-Host "如需重新启动，请先在原来的前端终端按 Ctrl+C。"
    exit 0
}

Set-Location -LiteralPath $frontendPath
npm run dev
