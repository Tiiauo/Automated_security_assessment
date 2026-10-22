# 数据库

- 表结构与索引以 PRD 8.2 为准（14 张表）。
- 迁移由 Alembic 管理：配置在 `alembic.ini`，脚本在 `db/migrations/`。
- 幂等初始化：`./db/init.sh`（内部执行 `alembic upgrade head`，重复执行不会破坏已有数据）。
- 默认系统配置在应用启动时补齐，也可通过 GET `/api/system/config` 触发。
- 测试使用按进程隔离的独立库 `sec_eval_test_<pid>`，由 pytest 自动创建并在退出时删除。
- `docker-compose.dev.yml` 中的 `db` 服务仅负责创建数据库实例，不负责建表。
