# 后端

FastAPI + SQLAlchemy 2.0 (async) + PostgreSQL 16。

## 目录

```text
app/
├── api/         路由（按 PRD 7.2 划分）
├── core/        配置、安全、依赖
├── models/      SQLAlchemy 模型（PRD 8.2 的 14 张表）
├── schemas/     Pydantic 请求/响应；附录 D 的 JSON Schema 校验
├── services/    业务逻辑（项目、沙箱、编排、报告）
├── agents/      6 类角色、提示词、工具调用循环
└── sandbox/     Docker SDK 封装（PRD 15.6）
tests/            pytest
```

## 运行

uv 项目根位于仓库根目录（`pyproject.toml`、`uv.lock`、`.venv`），在仓库根目录执行：

```bash
uv sync
uv run uvicorn app.main:app --app-dir backend --reload --port 8000
uv run pytest
uv run ruff check backend
```

Python 版本由 `.python-version` 固定为 3.12，uv 会自动发现本机解释器。
