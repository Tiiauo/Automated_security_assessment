#!/usr/bin/env bash
# 检查虚拟机与隧道连通性
# 用法：VM_USER=ubuntu ./scripts/check-vm.sh（需先启动 docker-tunnel.sh）
set -euo pipefail

VM_HOST="${VM_HOST:-192.168.10.22}"
: "${VM_USER:?请设置 VM_USER，例如：VM_USER=ubuntu ./scripts/check-vm.sh}"

echo "1) 直连虚拟机（SSH + Docker）"
ssh -o ConnectTimeout=5 -o BatchMode=yes "${VM_USER}@${VM_HOST}" \
  'docker version --format "{{.Server.Version}}" && docker info --format "{{.OperatingSystem}}"'

echo "2) 经 SSH 隧道访问 Docker API"
docker -H "${DOCKER_HOST:-tcp://127.0.0.1:2375}" version --format '{{.Server.Version}}'

echo "OK"
