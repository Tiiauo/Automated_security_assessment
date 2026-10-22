#!/usr/bin/env bash
# 幂等的数据库初始化：重复执行只会补齐缺失的迁移
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run alembic upgrade head
