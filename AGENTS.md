# AGENTS.md

本文件指导 Codex 在本仓库中的工作方式，适用于整个仓库。根据 `CLAUDE.md` 整理；业务需求与实现契约仍以 `PRD.md` 为准。

## 项目定位与技术栈

自动化安全评估系统：接入源码项目，在 Docker 隔离环境中由 6 类大模型角色完成环境检查、代码分析、漏洞验证、攻击路径整理与报告生成。

- 前端：React + TypeScript + Vite；通过 Vite 代理 `/api`（含 WebSocket）保持同源。
- 后端：Python 3.12 + FastAPI + SQLAlchemy 2.0（async）+ Alembic；使用仓库根目录的 `pyproject.toml`、`uv.lock` 与 `.venv/`。
- 数据库：PostgreSQL 16，遵循 PRD 的 `TIMESTAMPTZ` / `TEXT` / `BIGSERIAL` 类型约定。
- 隔离环境：Docker Engine 位于虚拟机 `192.168.10.22`，经 SSH 隧道 `tcp://127.0.0.1:2375` 访问；镜像为 `sec-eval-sandbox:latest`。
- 模型：OpenAI 兼容协议（本期 DeepSeek），仅使用原生 function calling。

## 权威文档与任务顺序

1. `PRD.md` 是业务需求、数据模型、接口与实现契约的唯一权威；重点参考第 7 章、第 15 章、附录 D（角色 JSON Schema）及附录 E（环境变量）。当前文档为冻结的 v1.11。
2. `项目规划.md` 定义 WP-1 ~ WP-8、M1 ~ M4、依赖关系与验收用例。按工作包顺序实施，不跨包提前实现；前置未完成时不得进入下游工作包。
3. 修改契约必须先改 PRD，再同步代码、调用方与测试；代码与 PRD 不一致视为缺陷。
4. `CLAUDE.md`、README 和规划中的进度记录可能滞后。开始任务时对照相关代码、测试与验收记录核实状态，不能仅凭文件存在或前端演示页面认定工作包完成。

## Codex 工作约定

- 默认用中文沟通；开始时简要说明工作范围，结束时说明改动、验证结果和未验证项。
- 修改前读取涉及的代码和契约，使用 `rg` / `rg --files` 查找实现与所有调用方，确认对接口、数据模型、前后端、迁移、测试和配置的影响。
- 优先复用现有服务、组件和工具，完成需求所需的最小改动；不顺带重构，不引入未要求的功能或无必要的新依赖。
- 保留用户已有修改，不覆盖或回滚无关文件；不擅自提交、推送或清理仓库。
- 提交范围由根目录 `.gitignore` 管理：保留源码、迁移、锁文件、内置示例与交付文档；排除运行数据、自接入源码、本机助手配置和历史原型。不用强制添加绕过忽略规则。
- 修复根因并同步受影响的调用方。新增非平凡逻辑或修复缺陷时，补充有意义的测试，保留原有校验与错误处理。
- 遵循 `.editorconfig`：UTF-8、LF、文件末尾换行；Python 缩进 4 空格，其余默认 2 空格。PowerShell 读取中文文档时显式使用 `-Encoding UTF8`。
- 缺少数据库、SSH 隧道、镜像或凭据时，明确记录无法执行的检查，不把跳过或 mock 结果报告为真实验收通过。

## 目录与复用入口

| 路径 | 职责 |
| --- | --- |
| `backend/app/api/` | HTTP 路由与接口入口 |
| `backend/app/core/` | 配置、数据库、安全、鉴权依赖与统一错误 |
| `backend/app/models/` | SQLAlchemy 数据模型 |
| `backend/app/schemas/` | Pydantic 请求响应与 `roles/` 中的 JSON Schema |
| `backend/app/services/` | 业务逻辑、源码准备、沙箱服务与运行编排 |
| `backend/app/agents/` | 角色执行引擎、提示词、输出校验与 mock |
| `backend/app/sandbox/` | Docker 连接、容器、命名卷与容器内工具 |
| `backend/tests/` | 后端自动化测试及可选实机集成测试 |
| `frontend/src/` | `pages/` 页面、`components/` 公共组件、`api/` 请求、`hooks/` 组合逻辑、`auth/` 登录态 |
| `db/migrations/` | Alembic 数据库迁移 |
| `sandbox/` | 沙箱镜像与说明 |
| `scripts/` | SSH 隧道、连通性检查与专项验收脚本 |
| `data/` | 源码副本、工作区、报告、日志与允许接入的用户源码 |

运行数据只写入 `data/` 下的对应目录，禁止写入源码目录；测试使用现有 fixture 分配的临时数据目录。

## 常用命令（Windows PowerShell）

除前端命令外，均在仓库根目录执行。先按 `.env.example` 配置本地 `.env`；不要覆盖已有配置或输出真实凭据。开发期本地 HTTP 使用 `COOKIE_SECURE=false`。

```powershell
# 安装后端依赖，虚拟环境位于仓库根目录
uv sync

# 在独立终端建立隧道并保持开启；替换为实际虚拟机用户名
.\scripts\docker-tunnel.ps1 -VmUser '实际虚拟机用户名'
```

在另一个终端执行：

```powershell
# 每个运行 Docker CLI / compose 的终端均须显式设置
$env:DOCKER_HOST = 'tcp://127.0.0.1:2375'
docker compose -f docker-compose.dev.yml up -d db

# 与 db/init.sh 等价，幂等执行迁移
uv run alembic upgrade head

# 构建远程沙箱镜像
docker build -t sec-eval-sandbox:latest sandbox

# 启动后端（保持运行）
uv run uvicorn app.main:app --app-dir backend --reload --port 8000
```

前端在独立终端执行，默认地址为 `http://localhost:5173`：

```powershell
Set-Location frontend
npm install
npm run dev
```

Bash 环境可使用 `VM_USER=<虚拟机用户名> ./scripts/docker-tunnel.sh` 建立隧道，使用 `export DOCKER_HOST=tcp://127.0.0.1:2375` 设置连接，并通过 `./db/init.sh` 执行迁移。

## 实现契约与安全边界

- 所有接口遵循 PRD 7.1 的统一响应结构与错误码；所有项目级接口和 WebSocket 必须校验项目归属。
- 角色输出必须按附录 D 校验，包括 mock 输出；禁止跳过校验或将失败标记为成功。
- 编排采用进程内 asyncio，数据库是唯一状态源；同阶段角色串行执行。轮次选择、重试、停止、恢复与终态清理均遵守 PRD。
- 时间统一使用带时区时间，接口返回 ISO 8601。
- `LLM_MOCK=1` 用于链路联调与自动化测试，不得代替真实模型验收演示；前端演示数据不代表后端已联通。
- 源码准备经 Docker API 上传至命名卷，源码卷在容器中只读挂载至 `/src`，轮次工作卷可写挂载至 `/workspace`；工具通过容器内 `docker exec` 操作，不直接访问远端文件系统。
- 禁止使用 `--privileged`，禁止向沙箱挂载 Docker Socket 或宿主机敏感目录，禁止在沙箱运行时开启外网，默认 `--network=none`。
- 禁止把 Docker API 暴露在虚拟机对外网卡上；隧道不可用时禁止回退到本机 Docker。PostgreSQL 仅绑定虚拟机回环地址。
- 禁止在远端路径或资源名称中拼接未经校验的用户输入，只使用数字 `project_id` / `run_id`。
- 禁止绕过 `sandbox.allowed_source_root` 白名单访问任意宿主机路径；禁止删除或改写 `data/allowed_sources/` 下的用户源码。
- 禁止提交 `.env`、密钥或真实凭据；日志、报告和最终回复也不得泄露凭据。

## 验证与完成标准

代码提交前在仓库根目录执行：

```powershell
uv run ruff check backend
uv run pytest
npm --prefix frontend run lint
npm --prefix frontend run build
```

- `pytest` 在收集阶段即连接 PostgreSQL，使用按进程隔离的 `sec_eval_test_<pid>` 库；fixture 创建测试表并在退出时删除该测试库。需有可用数据库和建库权限，不能把业务数据放入此测试库。
- 默认测试替代真实沙箱；真实 Docker 集成用例需显式设置 `SANDBOX_INTEGRATION=1`，并准备隧道与镜像。未运行时应单独说明，不能把默认跳过计为实机验证通过。
- 编排测试使用 `LLM_MOCK=1` 覆盖阶段推进、失败与重试、停止、落库及 WebSocket 推送；按当前工作包实际范围执行。
- WP-4 专项实机验收入口为 `uv run python scripts/verify-wp4.py`，默认使用 mock；`--real-model` 会调用已配置模型并发送脚本生成的测试源码，仅在任务包含真实模型验收时使用。
- 每个工作包完成后立即核对 `项目规划.md` 中的验收用例与 DoD，不推迟至里程碑末尾；区分代码实现、自动化测试通过和真实验收通过。
- 纯文档改动核对路径、命令与差异即可，无需启动数据库或运行应用全量测试。最终说明实际执行的检查与限制，不声明未运行的检查已通过。

## 维护说明

业务规则变更时先更新 PRD，再同步本文件及相关文档；保持与 `CLAUDE.md` 的共享约束一致，避免复制经常变化的进度结论。

本文件采用 Codex 的仓库指引约定，参见 [OpenAI 官方 AGENTS.md 文档](https://learn.chatgpt.com/docs/agent-configuration/agents-md)。
