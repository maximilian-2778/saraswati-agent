# 从项目根目录启动 React/Vite 开发服务器。
$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendPath = Join-Path $projectRoot "frontend"
$frontendPort = 5180

if (-not (Test-Path -LiteralPath (Join-Path $frontendPath "node_modules"))) {
    throw "没有找到前端依赖，请先进入 frontend 目录运行 npm install。"
}

$portProbe = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    $frontendPort
)
try {
    $portProbe.Start()
}
catch {
    throw "端口 $frontendPort 已被占用。请先在原前端终端按 Ctrl+C，再重新运行本脚本。"
}
finally {
    $portProbe.Stop()
}

Set-Location -LiteralPath $frontendPath
Write-Host "前端将运行在 http://localhost:$frontendPort"
npm run dev
