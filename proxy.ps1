Write-Host "🚀 正在为当前终端注入 30810 HS2 专属代理..." -ForegroundColor Yellow
$env:HTTP_PROXY="http://127.0.0.1:30810"
$env:HTTPS_PROXY="http://127.0.0.1:30810"
$env:ALL_PROXY="http://127.0.0.1:30810"
Write-Host "✅ 注入成功！请在此窗口执行 docker compose build 拉取镜像" -ForegroundColor Green