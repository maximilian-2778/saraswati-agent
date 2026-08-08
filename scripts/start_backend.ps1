# 从项目根目录启动 FastAPI 开发服务器。
# 8010 是本项目固定使用的后端开发端口，避开之前残留在 8000 的旧进程。
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$backendPort = 8010

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "没有找到项目虚拟环境，请先在项目根目录创建 .venv。"
}

# 先尝试占用端口。若失败，说明已有后端正在运行，继续启动只会造成版本混乱。
$portProbe = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    $backendPort
)
try {
    $portProbe.Start()
}
catch {
    throw "端口 $backendPort 已被占用。请先在原后端终端按 Ctrl+C，再重新运行本脚本。"
}
finally {
    $portProbe.Stop()
}

Set-Location -LiteralPath $projectRoot
Write-Host "后端将运行在 http://127.0.0.1:$backendPort"
& $pythonPath -m uvicorn backend.main:app --reload --host 127.0.0.1 --port $backendPort
