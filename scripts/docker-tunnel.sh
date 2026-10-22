#!/usr/bin/env bash
# 建立到 Docker 虚拟机的 SSH 隧道（PRD 15.6）
# 用法：VM_USER=ubuntu ./scripts/docker-tunnel.sh
set -euo pipefail

VM_HOST="${VM_HOST:-192.168.10.22}"
: "${VM_USER:?请设置 VM_USER，例如：VM_USER=ubuntu ./scripts/docker-tunnel.sh}"
DOCKER_PORT="${DOCKER_PORT:-2375}"
DB_PORT="${DB_PORT:-5432}"

echo "Docker API : 127.0.0.1:${DOCKER_PORT} -> ${VM_HOST}:/var/run/docker.sock"
echo "PostgreSQL : 127.0.0.1:${DB_PORT} -> ${VM_HOST}:127.0.0.1:5432"
echo "保持此窗口开启，Ctrl+C 结束。"
echo
echo "在另一个终端执行："
echo "  Git Bash  : export DOCKER_HOST=tcp://127.0.0.1:${DOCKER_PORT}"
echo "  PowerShell: \$env:DOCKER_HOST=\"tcp://127.0.0.1:${DOCKER_PORT}\""

exec ssh -N \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -L "${DOCKER_PORT}:/var/run/docker.sock" \
  -L "${DB_PORT}:127.0.0.1:5432" \
  "${VM_USER}@${VM_HOST}"
