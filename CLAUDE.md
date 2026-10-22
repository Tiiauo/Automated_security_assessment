# CLAUDE.md

本文件指导 Claude Code 在本仓库中的工作方式。

## 项目定位

自动化安全评估系统：接入源码项目，在 Docker 隔离环境中由 6 类大模型角色完成环境检查、代码分析、漏洞验证、攻击路径整理与报告生成。

## 权威文档与工作顺序

1. `PRD.md` 是**唯一权威**，包含业务需求、数据模型、接口、实现契约（第 15 章）与 JSON Schema（附录 D）。
2. `项目规划.md` 定义 8 个工作包（WP-1 ~ WP-8）与里程碑 M1 ~ M4；按工作包顺序实施，不跨包提前实现。
3. **修改契约的顺序永远是：先改 PRD → 再改代码**。代码与 PRD 不一致视为缺陷。
4. 项目已具备完整运行链路、两个内置示例及端到端演示脚本，用户已确认完整运行成功。交付入口见 `README.md`、`docs/交付说明.md`；历史验收记录保留各轮实际执行范围，不能替代当前版本验证。

## 技术栈

- 前端：React + TypeScript + Vite，Vite 代理 `/api`（含 WebSocket）保持同源
- 后端：Python 3.12 + FastAPI + SQLAlchemy 2.0（async）+ Alembic
- 数据库：PostgreSQL 16（`TIMESTAMPTZ` / `TEXT` / `BIGSERIAL`）
- 隔离环境：Docker Engine 运行在虚拟机 `192.168.10.22`，后端经 SSH 隧道 `tcp://127.0.0.1:2375` 访问；镜像 `sec-eval-sandbox:latest`（见 `sandbox/`）
- 模型：OpenAI 兼容协议（本期 DeepSeek），仅使用原生 function calling

## 常用命令

```bash
# 0. 建立 SSH 隧道（保持开启，Docker 与 PostgreSQL 都经此访问）
VM_USER=<虚拟机用户名> ./scripts/docker-tunnel.sh
export DOCKER_HOST=tcp://127.0.0.1:2375   # docker CLI / compose 必须显式指定

# 数据库
docker compose -f docker-compose.dev.yml up -d db
./db/init.sh                 # alembic upgrade head，幂等

# 后端（uv 项目根在仓库根目录，虚拟环境 .venv 位于仓库根目录）
uv sync
uv run uvicorn app.main:app --app-dir backend --reload --port 8000
uv run pytest
uv run ruff check backend

# 前端
cd frontend && npm ci
npm run dev
npm run build

# 沙箱镜像
docker build -t sec-eval-sandbox:latest sandbox
```

## 目录约定

- `backend/app/api/` 路由；`core/` 配置与安全；`models/` SQLAlchemy 模型；`schemas/` Pydantic 与 JSON Schema；`services/` 业务；`agents/` 角色与提示词；`sandbox/` 容器封装
- `frontend/src/pages/` 页面；`components/` 组件；`api/` 请求封装；`hooks/` 组合逻辑
- 运行数据只写 `data/` 下对应目录，禁止写入源码目录

## 开发规则

- 所有接口遵循 PRD 7.1 的统一响应结构与错误码
- 所有项目级接口与 WebSocket 必须做归属校验
- 角色输出必须按附录 D 校验，不得跳过校验或把失败标记为成功
- 编排采用进程内 asyncio，数据库是唯一状态源；同阶段角色串行
- 时间统一使用带时区时间，接口返回 ISO 8601
- `LLM_MOCK=1` 可用于全链路联调与自动化测试，但不得用于验收演示
- 提交前运行后端 `ruff` / `pytest` 与前端 `npm run build`

## 禁止事项

- 禁止在沙箱容器使用 `--privileged`，禁止向沙箱挂载 Docker Socket 或宿主机敏感目录
- 禁止把 Docker API 暴露在虚拟机对外网卡上，禁止在隧道不可用时回退到本机 Docker
- 禁止在远端路径中拼接用户输入，只能使用数字 `project_id` / `run_id`
- 禁止在沙箱运行时开启外网（默认 `--network=none`）
- 禁止删除或改写 `data/allowed_sources/` 下的用户源码
- 禁止提交 `.env`、密钥或任何真实凭据
- 仅提交必要源码、迁移、锁文件、内置示例与交付文档；运行数据、自接入源码、本机助手配置和历史原型由根目录 `.gitignore` 排除
- 禁止绕过 `sandbox.allowed_source_root` 白名单直接访问任意宿主机路径

## 测试策略

- 编排链路用 `LLM_MOCK=1` 覆盖：阶段推进、重试、停止、落库、WebSocket 推送
- 每个工作包的验收用例见 `项目规划.md` 对应章节，完成后立即验证，不推迟到里程碑末尾
