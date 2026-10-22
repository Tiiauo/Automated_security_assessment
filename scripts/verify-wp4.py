"""WP-4 实机验收：独立数据库 + 数字随机项目 ID + 新建最小源码。

默认仅使用 LLM_MOCK；--real-model 显式授权发送本脚本生成的测试源码到已配置模型。
不读取 allowed_sources，不修改开发库业务记录，不输出密钥。运行数据仅写 data/。
"""

import argparse
import asyncio
import json
import os
import secrets
import socket
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import asyncpg  # noqa: E402
import uvicorn  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from websockets.asyncio.client import connect  # noqa: E402

import app.models  # noqa: E402, F401
from app.agents.engine import RoleEngine  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import (  # noqa: E402
    Base,
    SessionLocal,
    engine,
    get_db,  # noqa: E402
)
from app.core.paths import data_root  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.main import app  # noqa: E402
from app.models.analysis import AttackPath, AttackPathItem, Vulnerability  # noqa: E402
from app.models.collab import ChatMessage, ResourceUsage  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.report import Report  # noqa: E402
from app.models.runtime import RuntimeStage, WorkerTask  # noqa: E402
from app.models.user import User, UserSession  # noqa: E402
from app.services import config_service, project_service  # noqa: E402
from app.services.run_manager import RunManager  # noqa: E402

DATABASE = f"sec_eval_acceptance_{os.getpid()}"


async def verify(real_model: bool, wp6: bool = False, wp5: bool = False, wp7: bool = False, clean: bool = False):
    settings = get_settings()
    original_mock = settings.llm_mock
    settings.llm_mock = not real_model
    url = engine.url.set(database=DATABASE)
    conn = await asyncpg.connect(engine.url.set(drivername="postgresql", database="postgres").render_as_string(False))
    try:
        await conn.execute(f'CREATE DATABASE "{DATABASE}"')
    except asyncpg.DuplicateDatabaseError:
        pass
    finally:
        await conn.close()
    test_engine = create_async_engine(url)
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(test_engine, expire_on_commit=False)
    ready = asyncio.Event()

    class FirstStagesEngine(RoleEngine):
        async def execute(self, **kwargs):
            if wp5:
                await asyncio.sleep(6)
            if real_model and not wp7 and kwargs["stage"] == ("report_generate" if wp6 else "vulnerability_verify"):
                # 已完成阶段提交后走真实停止链路；报告生成留待 WP-7。
                ready.set()
                await asyncio.Event().wait()
            return await super().execute(**kwargs)

    manager = RunManager(sessions, engine_factory=FirstStagesEngine)
    previous_manager = project_service.run_manager
    project_service.run_manager = manager
    project_id = 9_000_000_000 + secrets.randbelow(999_999_999)
    project = None
    try:
        async with SessionLocal() as db:
            saved = await config_service.get_config_raw(db)
        root = data_root() / "workspace" / str(project_id) / "0" / "source"
        await asyncio.to_thread(root.mkdir, parents=True)
        await asyncio.to_thread(
            (root / "main.py").write_text,
            'def greet(name: str) -> str:\n    return f"Hello, {name}!"\n\n'
            'if __name__ == "__main__":\n    print(greet("WP4"))\n',
            "utf-8",
        )
        if wp6 or (wp7 and not clean):
            await asyncio.to_thread((root / "main.py").write_text, WP6_SOURCE, "utf-8")
        async with sessions() as db:
            user = User(username=f"wp4-{project_id}", password_hash="not-a-login", role="admin", status="active")
            db.add(user)
            await db.commit()
            updates = {key: value for key, value in saved.items() if key.startswith("llm.") or key == "sandbox.image"}
            updates["sandbox.allowed_source_root"] = str(root.parent)
            updates["monitor.resource_interval_seconds"] = 1
            await config_service.update_config(db, updates, actor_id=user.id)
            project = Project(
                id=project_id,
                project_name=f"WP4-acceptance-{project_id}",
                source_type="local_path",
                source_path=str(root),
                task_content=(
                    "这是新建的隔离验收项目，仅分析 /src/main.py。其 lookup 和 read_document 接收不可信输入，"
                    "请实际运行源码及最小验证脚本，确认候选及可串联的攻击路径。"
                    "样本所有数据都是虚构测试数据，写入仅限 /workspace；禁止外部网络。"
                    "运行只依赖 Python 标准库 sqlite3/json/pathlib，不需要 sqlite3 命令行、数据库服务、"
                    "pip 安装或构建。环境检查运行 python /src/main.py 即可；源码只读为预期安全限制。"
                    "逐一验证候选，不要把静态推测写为已验证；路径必须有实际因果关系。"
                )
                if wp6 or (wp7 and not clean)
                else (
                    "仅检查这个新建的最小 Python 测试项目，不访问外部目标。识别语言依赖并分析安全性。"
                    "用 list_dir 看目录、read_file 读取 main.py、search_code 搜索输入点、"
                    "run_command 在容器内运行 python /src/main.py；无漏洞时返回空候选。"
                ),
                project_status="created",
                sandbox_type="docker",
                created_by=user.id,
            )
            db.add(project)
            await db.commit()
            await project_service.start_project(db, project, actor=user)
            task = manager.handles[project_id].task
            monitor_summary = await verify_monitor(sessions, project_id, user) if wp5 else None
            if real_model and not wp7:
                barrier = asyncio.create_task(ready.wait())
                try:
                    done, _ = await asyncio.wait([task, barrier], timeout=600, return_when=asyncio.FIRST_COMPLETED)
                    if not done:
                        raise TimeoutError("真实模型前两阶段验收超过 600 秒")
                    if not ready.is_set():
                        await task
                        failed = (
                            await db.scalars(
                                select(WorkerTask).where(
                                    WorkerTask.project_id == project_id,
                                    WorkerTask.task_status == "failed",
                                )
                            )
                        ).all()
                        raise RuntimeError(
                            "前两阶段未完成：" + "; ".join(w.error_message or "未知错误" for w in failed)
                        )
                    await db.refresh(project)
                    await project_service.stop_project(db, project, actor=user)
                finally:
                    barrier.cancel()
                    await asyncio.gather(barrier, return_exceptions=True)
            else:
                await asyncio.wait_for(asyncio.shield(task), 900 if real_model else 120)
            await db.refresh(project)
            stages = (
                await db.scalars(
                    select(RuntimeStage).where(RuntimeStage.project_id == project_id).order_by(RuntimeStage.id)
                )
            ).all()
            workers = (
                await db.scalars(select(WorkerTask).where(WorkerTask.project_id == project_id).order_by(WorkerTask.id))
            ).all()
            limit = 3 if wp6 else 2
            expected = stages[:limit] if real_model and not wp7 else stages
            assert len(expected) == (limit if real_model and not wp7 else 5) and all(
                s.stage_status == "success" for s in expected
            ), [(s.stage_name, s.stage_status, s.error_message) for s in stages]
            calls = (
                await db.scalars(
                    select(ChatMessage).where(
                        ChatMessage.project_id == project_id,
                        ChatMessage.message_type == "tool_call",
                    )
                )
            ).all()
            tool_names = sorted(
                {
                    json.loads(row.message_text)["name"]
                    for row in calls
                    if json.loads(row.message_text)["event"] == "tool"
                }
            )
            if real_model and not wp7:
                assert set(tool_names) == {"list_dir", "read_file", "search_code", "run_command"}, tool_names
            if wp7:
                assert "run_command" in tool_names, tool_names
            tokens = await db.scalar(
                select(func.max(ResourceUsage.token_count)).where(
                    ResourceUsage.project_id == project_id,
                )
            )
            summary = {
                "mode": "real-model" if real_model else "LLM_MOCK",
                "project_id": project_id,
                "monitor": monitor_summary,
                "native_tools": tool_names,
                "total_tokens": tokens,
                "project_status": project.project_status,
                "stages": [{"name": s.stage_name, "status": s.stage_status} for s in stages],
                "workers": [
                    {"role": w.worker_role, "status": w.task_status, "retry_count": w.retry_count} for w in workers
                ],
            }
            if wp6 or (wp7 and not clean):
                vulnerabilities = (
                    await db.scalars(select(Vulnerability).where(Vulnerability.project_id == project_id))
                ).all()
                paths = (await db.scalars(select(AttackPath).where(AttackPath.project_id == project_id))).all()
                summary["vulnerabilities"] = [
                    {"code": v.vuln_code, "title": v.vuln_title, "status": v.verify_status} for v in vulnerabilities
                ]
                summary["paths"] = [{"code": p.path_code, "title": p.path_title} for p in paths]
                samples = (
                    await db.scalars(
                        select(ResourceUsage).where(
                            ResourceUsage.project_id == project_id, ResourceUsage.memory_usage > 0
                        )
                    )
                ).all()
                assert samples, "未采集到真实容器内存数据"
                assert sum(v.verify_status == "verified" for v in vulnerabilities) >= 2
                assert paths
                for path in paths:
                    steps = (
                        await db.scalars(
                            select(AttackPathItem)
                            .where(AttackPathItem.path_id == path.id)
                            .order_by(AttackPathItem.step_order)
                        )
                    ).all()
                    assert len(steps) >= 2 and [s.step_order for s in steps] == list(range(1, len(steps) + 1))
                summary["real_resource_samples"] = len(samples)
            if wp7:
                report = await db.scalar(select(Report).where(Report.project_id == project_id))
                assert report and project.project_status == "completed" and project.sandbox_id is None
                assert all(worker.task_status == "success" for worker in workers) and len(workers) == 10
                for extension, content in ((".md", report.report_markdown), (".html", report.report_html)):
                    assert await asyncio.to_thread(
                        Path(report.report_file_path + extension).read_bytes
                    ) == content.encode("utf-8")
                assert "[LLM_MOCK]" not in report.report_markdown
                if clean:
                    assert (
                        await db.scalar(
                            select(func.count())
                            .select_from(Vulnerability)
                            .where(Vulnerability.project_id == project_id)
                        )
                        == 0
                    )
                    assert "未发现可验证漏洞" in report.report_markdown
                    assert "未发现可串联的多步攻击路径" in report.report_markdown
                summary["report"] = {
                    "run_id": report.run_id,
                    "markdown_bytes": len(report.report_markdown.encode()),
                    "html_bytes": len(report.report_html.encode()),
                    "clean": clean,
                }
            print(json.dumps(summary, ensure_ascii=False, indent=2))
    except Exception:
        async with sessions() as db:
            diagnostics = (
                await db.scalars(
                    select(ChatMessage)
                    .where(ChatMessage.project_id == project_id)
                    .order_by(ChatMessage.id.desc())
                    .limit(12)
                )
            ).all()
            print(
                json.dumps(
                    {"diagnostics": [row.message_text[:4000] for row in reversed(diagnostics)]},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        raise
    finally:
        await manager.shutdown()
        if project is not None:
            async with sessions() as db:
                row = await db.get(Project, project_id)
                if row:
                    deleted, cleaned, error = await project_service.delete_project(db, row, actor=user)
                    if not deleted:
                        print(json.dumps({"cleanup_failed": True, "dirs_cleaned": cleaned, "error": error}))
        project_service.run_manager = previous_manager
        settings.llm_mock = original_mock
        await test_engine.dispose()
        await engine.dispose()


async def verify_monitor(sessions, project_id, user):
    async def override_db():
        async with sessions() as db:
            yield db

    jti = secrets.token_hex(16)
    expires = datetime.now(UTC) + timedelta(hours=1)
    async with sessions() as db:
        db.add(UserSession(jti=jti, user_id=user.id, expires_at=expires))
        await db.commit()
    token = create_access_token(user_id=user.id, role="admin", jti=jti, expires_at=expires)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    app.dependency_overrides[get_db] = override_db
    server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="warning", access_log=False))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        while not server.started:
            if task.done():
                await task
                raise RuntimeError("验收服务器未启动")
            await asyncio.sleep(0.05)
        uri = f"ws://127.0.0.1:{port}/api/projects/{project_id}/stream"
        options = {
            "origin": f"http://127.0.0.1:{port}",
            "additional_headers": {"Cookie": f"access_token={token}"},
            "proxy": None,
            "max_size": 8 * 1024 * 1024,
        }
        seen, ids = set(), set()
        loop = asyncio.get_running_loop()
        async with connect(uri, **options) as ws:
            first = json.loads(await ws.recv())
            assert first["type"] == "snapshot"
            started = loop.time()
            async with sessions() as db:
                marker = ChatMessage(
                    project_id=project_id,
                    run_id=1,
                    worker_role="orchestrator",
                    message_type="info",
                    message_text="[WP5] latency probe",
                )
                db.add(marker)
                await db.commit()
                marker_id = marker.id
            latency = None
            while loop.time() - started < 60:
                try:
                    frame = json.loads(await asyncio.wait_for(ws.recv(), 60 - (loop.time() - started)))
                except TimeoutError:
                    break
                if frame["type"] == "ping":
                    await ws.send(json.dumps({"type": "pong"}))
                    continue
                seen.add(frame["type"])
                if frame["type"] == "chat_message":
                    assert frame["data"]["id"] not in ids, "重复聊天增量消息"
                    ids.add(frame["data"]["id"])
                    if frame["data"]["id"] == marker_id:
                        latency = loop.time() - started
            assert latency is not None and latency <= 1, latency
        await asyncio.sleep(30)
        async with connect(uri, **options) as ws:
            recovered = json.loads(await ws.recv())
            assert recovered["type"] == "snapshot"
            for key in ("recent_messages", "recent_logs"):
                values = [row["id"] for row in recovered["data"][key]]
                assert len(values) == len(set(values))
            assert recovered["data"]["latest_resource"]["token_count"] > 0
        assert {"stage_status", "worker_status", "chat_message", "runtime_log", "resource_usage"} <= seen
        return {
            "observation_seconds": 60,
            "disconnection_seconds": 30,
            "push_latency_seconds": round(latency, 4),
            "event_types": sorted(seen),
            "reconnected_status": recovered["data"]["project_status"],
        }
    finally:
        server.should_exit = True
        await task
        app.dependency_overrides.pop(get_db, None)
        listener.close()


WP6_SOURCE = '''"""Local acceptance fixture. All secrets below are fictional test strings."""
import json
import sqlite3
from pathlib import Path

PUBLIC = Path("/workspace/public")
PRIVATE = Path("/workspace/private")


def prepare():
    PUBLIC.mkdir(exist_ok=True)
    PRIVATE.mkdir(exist_ok=True)
    (PUBLIC / "welcome.txt").write_text("public example", encoding="utf-8")
    (PRIVATE / "internal.txt").write_text("FICTIONAL_ACCEPTANCE_SECRET", encoding="utf-8")
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE public_docs (title TEXT, filename TEXT)")
    db.execute("INSERT INTO public_docs VALUES ('welcome', 'welcome.txt')")
    db.execute("CREATE TABLE internal_docs (title TEXT, filename TEXT)")
    db.execute("INSERT INTO internal_docs VALUES ('internal', '../private/internal.txt')")
    return db


def lookup(db, title):
    # An unauthenticated caller should only find public document names.
    return db.execute("SELECT filename FROM public_docs WHERE title = '" + title + "'").fetchall()


def read_document(filename):
    # Only files inside PUBLIC should be returned to an unauthenticated caller.
    return (PUBLIC / filename).read_text(encoding="utf-8")


if __name__ == "__main__":
    db = prepare()
    print(json.dumps(lookup(db, "welcome")))
    print(read_document("welcome.txt"))
'''


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-model", action="store_true", help="授权调用当前模型，仅发送本脚本新建的测试源码")
    parser.add_argument("--wp6", action="store_true", help="验收真实漏洞验证、攻击路径及容器资源采样")
    parser.add_argument("--wp5", action="store_true", help="60 秒真实 WebSocket 监控与 30 秒断线恢复（使用 MOCK）")
    parser.add_argument("--wp7", action="store_true", help="验收真实模型五阶段、双格式报告和正常销毁")
    parser.add_argument("--clean", action="store_true", help="WP-7 无漏洞样本验收")
    args = parser.parse_args()
    if args.wp5 and (args.real_model or args.wp6 or args.wp7):
        parser.error("--wp5 使用独立 MOCK 链路，请与真实模型验收分别运行")
    if args.wp6 and not args.real_model:
        parser.error("--wp6 验证真实漏洞产出，必须显式指定 --real-model")
    if args.wp7 and (not args.real_model or args.wp6):
        parser.error("--wp7 必须指定 --real-model，且不与 --wp6 同时使用")
    if args.clean and not args.wp7:
        parser.error("--clean 只能与 --wp7 配合使用")
    asyncio.run(verify(args.real_model, args.wp6, args.wp5, args.wp7, args.clean))
