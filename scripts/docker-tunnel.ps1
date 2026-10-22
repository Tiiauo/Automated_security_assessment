# 建立到 Docker 虚拟机的 SSH 隧道（PRD 15.6）
# 用法：.\scripts\docker-tunnel.ps1 -VmUser ubuntu
param(
  [Parameter(Mandatory = $true)][string]$VmUser,
  [string]$VmHost = "192.168.10.22",
  [int]$DockerPort = 2375,
  [int]$DbPort = 5432
)

Write-Host "Docker API : 127.0.0.1:$DockerPort -> ${VmHost}:/var/run/docker.sock"
Write-Host "PostgreSQL : 127.0.0.1:$DbPort -> ${VmHost}:127.0.0.1:5432"
Write-Host "保持此窗口开启，Ctrl+C 结束。"
Write-Host ""
Write-Host "在另一个 PowerShell 窗口执行："
Write-Host "  `$env:DOCKER_HOST = `"tcp://127.0.0.1:$DockerPort`""

ssh -N `
  -o ExitOnForwardFailure=yes `
  -o ServerAliveInterval=30 `
  -o ServerAliveCountMax=3 `
  -L "${DockerPort}:/var/run/docker.sock" `
  -L "${DbPort}:127.0.0.1:5432" `
  "$VmUser@$VmHost"
