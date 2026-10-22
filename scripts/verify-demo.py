"""WP-8: fresh migrated database, real HTTP/WebSocket, built-in samples and real model.

Uses the development database only to read saved model settings. Never prints secrets.
Evidence remains under data/demo-runs; projects, containers and volumes are cleaned via API.
"""

import argparse
import asyncio
import base64
import json
import os
import secrets
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import httpx
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.contracts import report_sections  # noqa: E402
from app.core.db import SessionLocal, engine  # noqa: E402
from app.core.paths import data_root  # noqa: E402
from app.services import config_service, source_service  # noqa: E402


async def api(client, method, path, **kwargs):
    response = await client.request(method, path, **kwargs)
    assert response.status_code == 200, f"{method} {path}: HTTP {response.status_code}"
    body = response.json()
    assert body["code"] == 0, f"{method} {path}: {body['message']}"
    return body["data"]


async def watch(ws, seen, totals):
    async for raw in ws:
        frame = json.loads(raw)
        kind = frame["type"]
        if kind == "ping":
            await ws.send(json.dumps({"type": "pong"}))
            continue
        seen.add(kind)
        if kind == "resource_usage":
            totals["tokens"] = max(totals["tokens"], frame["data"]["token_count"])
            totals["samples"] += frame["data"]["memory_usage"] > 0


async def evaluate(client, address, sample, evidence):
    source = ROOT / "data" / "allowed_sources" / sample
    fingerprint = await asyncio.to_thread(source_service.compute_fingerprint, source)
    task = (
        "评估本轮 Flask 项目的全部 Python 源码，实际验证每条候选并整理有因果关系的攻击路径。"
        "依赖已在镜像中安装，不能联网或 pip 安装。使用 Flask test_client()，无需启动服务。"
        "通过 sys.path.insert(0, '/src') 导入 app.create_app；工厂参数与接口以实际代码为准。"
        "所有数据库、脚本和验证标记只写 /workspace，/src 只读为预期限制。"
        "仅使用虚构测试数据；验证命令执行使用 printf 或工作区标记，不访问外部目标。"
        "配置中的测试凭据在本示例管理接口实际生效，须按泄露和访问控制的真实影响验证。"
        "分析配置和所有路由，串联可证实的文件读取、凭据获取、管理访问和命令执行；"
        "不要强行串联独立问题。若代码没有相关接口或没有候选，按实际代码返回空结果。"
        "输出紧凑结论，不重复无关工具输出；运维阶段只归档已有产物。"
    )
    project = await api(
        client,
        "POST",
        "/api/projects",
        json={
            "project_name": sample,
            "source_type": "local_path",
            "source_path": str(source),
            "task_content": task,
        },
    )
    project_id = project["project_id"]
    path = f"/api/projects/{project_id}"
    seen, totals = set(), {"tokens": 0, "samples": 0}
    watcher = None
    try:
        async with connect(
            address.replace("http://", "ws://") + path + "/stream",
            origin=address,
            additional_headers={"Cookie": f"access_token={client.cookies['access_token']}"},
            proxy=None,
            max_size=8 * 1024 * 1024,
        ) as ws:
            first = json.loads(await ws.recv())
            assert first["type"] == "snapshot"
            seen.add("snapshot")
            watcher = asyncio.create_task(watch(ws, seen, totals))
            await api(client, "POST", path + "/start")
            previous = None
            async with asyncio.timeout(1800):
                while True:
                    detail = await api(client, "GET", path)
                    status = [(s["stage_name"], s["stage_status"]) for s in detail["stages"]]
                    if status != previous:
                        print(json.dumps({"sample": sample, "stages": status}, ensure_ascii=False), flush=True)
                        previous = status
                    if watcher.done():
                        await watcher
                        raise RuntimeError("WebSocket closed before completion")
                    if detail["project_status"] != "running":
                        break
                    await asyncio.sleep(1)
            assert detail["project_status"] == "completed", detail["stages"]
            assert len(detail["stages"]) == 5 and all(s["stage_status"] == "success" for s in detail["stages"])
            assert detail["sandbox_id"] is None
            await asyncio.sleep(0.3)
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        assert {
            "snapshot",
            "stage_status",
            "worker_status",
            "chat_message",
            "runtime_log",
            "resource_usage",
            "report_ready",
            "project_status",
        } <= seen, seen
        workers = (await api(client, "GET", path + "/workers"))["items"]
        assert len(workers) == 10 and all(w["task_status"] == "success" for w in workers)
        vulns = (await api(client, "GET", path + "/vulnerabilities?page_size=100"))["items"]
        paths = (await api(client, "GET", path + "/attack-paths?page_size=100"))["items"]
        path_lengths = []
        for item in paths:
            result = await api(client, "GET", path + f"/attack-paths/{item['id']}")
            path_lengths.append(len(result["steps"]))
        for item in vulns:
            result = await api(client, "GET", path + f"/vulnerabilities/{item['id']}")
            if result["verify_status"] == "verified":
                assert all(
                    result[key]
                    for key in (
                        "impact_text",
                        "condition_text",
                        "evidence_text",
                        "reproduce_steps_text",
                        "verify_code_text",
                    )
                )
        report = await api(client, "GET", path + "/report")
        assert len(report_sections(report["report_markdown"])) == 6
        assert "[LLM_MOCK]" not in report["report_markdown"]
        if sample == "demo-app":
            assert sum(v["verify_status"] == "verified" for v in vulns) >= 3, vulns
            assert path_lengths and max(path_lengths) >= 3, path_lengths
            assert "vulnerability_found" in seen
        else:
            assert not vulns and not paths
            assert "未发现可验证漏洞" in report["report_markdown"]
            assert "未发现可串联的多步攻击路径" in report["report_markdown"]
        for extension, field in (("md", "report_markdown"), ("html", "report_html")):
            response = await client.get(path + f"/report/download?run_id=1&format={extension}")
            assert response.status_code == 200 and "attachment" in response.headers["content-disposition"]
            assert response.content == report[field].encode("utf-8")
            await asyncio.to_thread((evidence / f"{sample}.{extension}").write_bytes, response.content)
        assert await asyncio.to_thread(source_service.compute_fingerprint, source) == fingerprint
        assert totals["tokens"] > 0 and totals["samples"] > 0, totals
        return {
            "sample": sample,
            "project_id": project_id,
            "status": detail["project_status"],
            "verified": sum(v["verify_status"] == "verified" for v in vulns),
            "path_steps": path_lengths,
            "events": sorted(seen),
            **totals,
            "source_unchanged": True,
            "workers": [{"role": w["worker_role"], "retries": w["retry_count"]} for w in workers],
            "report_bytes": {key: len(report[key].encode("utf-8")) for key in ("report_markdown", "report_html")},
        }
    finally:
        if watcher:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        detail = await api(client, "GET", path)
        if detail["project_status"] == "running":
            await api(client, "POST", path + "/stop")
        deleted = await api(client, "DELETE", path)
        assert deleted["deleted"] and deleted["dirs_cleaned"]


async def verify():
    async with SessionLocal() as db:
        saved = await config_service.get_config_raw(db)
    assert all(saved.get(key) for key in ("llm.base_url", "llm.model", "llm.api_key")), "先配置开发库模型连接"
    database = f"sec_eval_demo_{os.getpid()}_{secrets.token_hex(3)}"
    evidence = data_root() / "demo-runs" / database
    evidence.mkdir(parents=True)
    url = engine.url.set(database=database)
    conn = await asyncpg.connect(engine.url.set(drivername="postgresql", database="postgres").render_as_string(False))
    try:
        await conn.execute(f'CREATE DATABASE "{database}"')
    finally:
        await conn.close()
    env = {
        **os.environ,
        "DATABASE_URL": url.render_as_string(False),
        "DATA_ROOT": str(evidence / "runtime"),
        "JWT_SECRET": secrets.token_urlsafe(48),
        "DATA_ENCRYPTION_KEY": base64.b64encode(os.urandom(32)).decode(),
        "COOKIE_SECURE": "false",
        "LLM_MOCK": "0",
        "PYTHONUNBUFFERED": "1",
    }
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    server = None
    with (evidence / "backend.log").open("wb") as log:
        try:
            for _ in range(2):
                migration = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "alembic",
                    "upgrade",
                    "head",
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=log,
                    **options,
                )
                assert await migration.wait() == 0, f"迁移失败，查看 {evidence / 'backend.log'}"
            conn = await asyncpg.connect(url.set(drivername="postgresql").render_as_string(False))
            try:
                start_id = 9_000_000_000 + secrets.randbelow(900_000_000)
                await conn.execute("SELECT setval('projects_id_seq', $1, false)", start_id)
                revision = await conn.fetchval("SELECT version_num FROM alembic_version")
            finally:
                await conn.close()
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            address = f"http://127.0.0.1:{port}"
            server = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--app-dir",
                "backend",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-access-log",
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=log,
                **options,
            )
            async with httpx.AsyncClient(base_url=address, timeout=180) as client:
                async with asyncio.timeout(30):
                    while True:
                        if server.returncode is not None:
                            raise RuntimeError(f"后端启动失败，查看 {evidence / 'backend.log'}")
                        try:
                            health = await api(client, "GET", "/api/system/health")
                            assert health["status"] == "ok", health
                            break
                        except httpx.TransportError:
                            await asyncio.sleep(0.2)
                assert not (await api(client, "GET", "/api/system/status"))["initialized"]
                credentials = {"username": "demo_acceptance", "password": "Demo@" + secrets.token_urlsafe(24)}
                await api(client, "POST", "/api/system/init", json=credentials)
                assert (await client.post("/api/system/init", json=credentials)).status_code == 409
                await api(client, "POST", "/api/system/login", json=credentials)
                settings = {
                    key: value for key, value in saved.items() if key.startswith("llm.") or key == "sandbox.image"
                }
                settings.update(
                    {
                        "sandbox.allowed_source_root": str(ROOT / "data" / "allowed_sources"),
                        "monitor.resource_interval_seconds": "1",
                    }
                )
                await api(client, "PUT", "/api/system/config", json=settings)
                probe = await api(client, "POST", "/api/system/config/test-llm", json={})
                assert all(probe[key] for key in ("url_ok", "model_ok", "auth_ok", "tools_ok")), probe
                results = []
                for sample in ("demo-app", "demo-clean"):
                    results.append(await evaluate(client, address, sample, evidence))
                assert not (await api(client, "GET", "/api/projects"))["items"]
                summary = {
                    "date": datetime.now(UTC).isoformat(),
                    "database": database,
                    "revision": revision,
                    "mode": "real-model",
                    "migrations_idempotent": True,
                    "results": results,
                }
                (evidence / "summary.json").write_text(
                    json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                await api(client, "POST", "/api/system/logout")
                print(json.dumps({**summary, "evidence": str(evidence)}, ensure_ascii=False, indent=2), flush=True)
        finally:
            if server and server.returncode is None:
                server.terminate()
                try:
                    await asyncio.wait_for(server.wait(), 20)
                except TimeoutError:
                    server.kill()
                    await server.wait()
            await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-model", action="store_true", help="调用已配置模型，仅发送仓库内置示例源码")
    args = parser.parse_args()
    if not args.real_model:
        parser.error("完整演示必须显式指定 --real-model，不接受 MOCK 验收")
    asyncio.run(verify())
