# 自动化安全评估系统

面向源码项目的自动化安全评估系统：项目接入 → 隔离环境分析 → 漏洞验证 → 攻击路径 → 报告输出。

## 文档

- [PRD.md](PRD.md)：产品需求与实现契约的唯一权威（v1.11）。
- [项目规划.md](项目规划.md)：工作包、里程碑与验收映射。
- [项目要求.md](项目要求.md)：原始要求。
- [交付说明](docs/交付说明.md)：文件范围、接口入口、演示步骤与已有验收摘要。

## 交付状态

源码接入、五阶段角色编排、实时监控、漏洞验证、攻击路径与双格式报告已实现，用户已确认完整运行成功。仓库提供有漏洞 / 无漏洞两个 Flask 示例与端到端演示脚本。

历史专项记录见 [WP-4](docs/WP-4-验收.md)、[WP-5 / WP-6](docs/WP-5-WP-6-验收.md) 和 [WP-7](docs/WP-7-验收.md)，其中的限制和测试数量对应记录当时的版本。

## 目录结构

```text
backend/          FastAPI 后端与自动化测试
frontend/         React + TypeScript + Vite 前端
db/               数据库初始化与 Alembic 迁移
sandbox/          隔离环境镜像与说明
data/             内置示例与本地运行数据
scripts/          SSH 隧道、连通性检查与专项演示脚本
docs/             验收记录与交付文档
pyproject.toml    后端依赖定义
uv.lock           后端依赖锁文件
```

## 前置依赖

| 依赖 | 版本 | 说明 |
| --- | --- | --- |
| Python | 3.12 | 由 `.python-version` 指定 |
| uv | 支持仓库锁文件的版本 | 管理后端依赖与根目录 `.venv` |
| Node.js | 20.19+（20.x）或 22.12+ | 与当前 Vite / React 插件要求一致 |
| Docker | 24+ | 运行在虚拟机 `192.168.10.22`，经 SSH 隧道访问 |
| PostgreSQL | 16 | 经 `docker-compose.dev.yml` 部署在虚拟机 |
| OpenSSH | 支持本地端口转发 | 建立 Docker 与 PostgreSQL 隧道，源码经 Docker API 上传 |

## 快速开始

以下在仓库根目录的 PowerShell 执行。首次复制配置后填写数据库密码、`DATABASE_URL`、`JWT_SECRET` 和 `DATA_ENCRYPTION_KEY`；不要覆盖已有 `.env`。本地 HTTP 开发设置 `COOKIE_SECURE=false`。

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
uv sync --locked

# 在独立终端建立 SSH 隧道并保持开启
.\scripts\docker-tunnel.ps1 -VmUser '实际虚拟机用户名'
```

在另一个终端继续：

```powershell
$env:DOCKER_HOST = 'tcp://127.0.0.1:2375'
docker compose -f docker-compose.dev.yml up -d db
uv run alembic upgrade head
docker build -t sec-eval-sandbox:latest sandbox
uv run uvicorn app.main:app --app-dir backend --reload --port 8000
```

前端在独立终端运行：

```powershell
npm --prefix frontend ci
npm --prefix frontend run dev
```

访问 `http://localhost:5173` 完成管理员初始化，在系统配置中填写模型地址、模型名称与 API Key，并测试连接。模型输出额度默认 `32768` token，须在服务端支持范围内。前端 `/api` 与 WebSocket 代理到后端 `8000` 端口。

Bash 可用 `VM_USER=<用户名> ./scripts/docker-tunnel.sh` 建立隧道、`export DOCKER_HOST=tcp://127.0.0.1:2375` 设置 Docker 连接，并通过 `./db/init.sh` 执行迁移。

## 测试

```powershell
uv run ruff check backend
uv run pytest
npm --prefix frontend run lint
npm --prefix frontend run build
```

后端测试需要可用的 PostgreSQL 及建库权限，使用按进程隔离的 `sec_eval_test_<pid>` 库，退出时删除。默认测试替代真实沙箱；实机检查须显式设置 `SANDBOX_INTEGRATION=1`，详见[交付说明](docs/交付说明.md)。

## 仓库文件

提交源码、测试、数据库迁移、依赖锁文件、配置示例、内置示例和交付文档。`.env`、虚拟环境、`node_modules`、构建产物、缓存、运行日志、报告、自接入源码及本机助手配置均由 `.gitignore` 排除。历史设计原型保留在本地，不随运行项目提交。

运行数据边界见 [data/README.md](data/README.md)。

## 安全约束

- 隔离容器禁止 `--privileged`、禁止挂载 Docker Socket、默认无外网。
- Docker API 只经 SSH 本地端口转发访问；PostgreSQL 仅绑定虚拟机回环地址。
- 源码只读挂载，后端只允许访问 `sandbox.allowed_source_root` 白名单目录。
- 模型密钥与仓库凭据加密存储，禁止提交 `.env` 或真实凭据。
