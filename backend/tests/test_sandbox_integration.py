import asyncio
import json
import os
import secrets
import time

import pytest

from app.sandbox import archive, containers, volumes
from app.sandbox.client import docker_http_url, get_client
from app.sandbox.names import source_volume_name, workspace_volume_name
from app.sandbox.tools import SandboxTools
from app.services import sandbox_service

_REAL_INTERRUPT = sandbox_service.interrupt_run

pytestmark = pytest.mark.skipif(
    os.environ.get("SANDBOX_INTEGRATION") != "1",
    reason="设置 SANDBOX_INTEGRATION=1 以在真实 Docker 虚拟机上运行",
)

PROJECT_ID = 9_000_000_000 + secrets.randbelow(999_999_999)
RUN_ID = 1
IMAGE = "sec-eval-sandbox:latest"


async def test_sandbox_roundtrip(tmp_path) -> None:
    (tmp_path / "hello.txt").write_text("sandbox-ok", encoding="utf-8")
    source_volume = source_volume_name(PROJECT_ID)
    workspace_volume = workspace_volume_name(PROJECT_ID, RUN_ID)
    tar_path = archive.create_source_tar(tmp_path)

    client = None
    helper = None
    container = None
    try:
        client = await asyncio.to_thread(get_client)

        await asyncio.to_thread(volumes.remove_volume, client, source_volume)
        await asyncio.to_thread(volumes.remove_volume, client, workspace_volume)
        await asyncio.to_thread(volumes.ensure_volume, client, source_volume, project_id=PROJECT_ID)
        await asyncio.to_thread(
            volumes.ensure_volume,
            client,
            workspace_volume,
            project_id=PROJECT_ID,
            run_id=RUN_ID,
        )

        helper = await asyncio.to_thread(
            containers.create_helper,
            client,
            IMAGE,
            {
                source_volume: {"bind": "/src", "mode": "rw"},
                workspace_volume: {"bind": "/workspace", "mode": "rw"},
            },
            ["sh", "-c", "chown -R 1001:1001 /src /workspace && chmod -R a+rX /src && ln -s /etc/passwd /src/escape"],
        )
        await archive.upload_tar(helper.id, tar_path, "/src", docker_http_url())
        await asyncio.to_thread(containers.start_and_wait, helper, 120)
        await asyncio.to_thread(containers.remove_container, helper)
        helper = None

        kwargs = containers.build_create_kwargs(
            project_id=PROJECT_ID,
            run_id=RUN_ID,
            image=IMAGE,
            cpu_limit=1.0,
            memory_limit_mb=512,
            network_enabled=False,
            source_volume=source_volume,
            workspace_volume=workspace_volume,
        )
        container = await asyncio.to_thread(containers.create_container, client, kwargs)
        await asyncio.to_thread(container.start)

        read = await asyncio.to_thread(container.exec_run, ["sh", "-lc", "cat /src/hello.txt"])
        assert read.exit_code == 0
        assert b"sandbox-ok" in read.output

        identity = await asyncio.to_thread(container.exec_run, ["id", "-u"])
        assert identity.output.strip() == b"1001"

        write = await asyncio.to_thread(container.exec_run, ["sh", "-lc", "echo evidence > /workspace/probe.txt"])
        assert write.exit_code == 0, write.output

        blocked = await asyncio.to_thread(container.exec_run, ["sh", "-lc", "echo nope > /src/probe.txt"])
        assert blocked.exit_code != 0

        tools = SandboxTools(container.id, 60)

        async def call(name, **arguments):
            return await tools.execute(name, json.dumps(arguments))

        listing = await call("list_dir", path="/src")
        assert "/src/hello.txt" in listing["entries"], listing
        fragment = await call("read_file", path="/src/hello.txt", offset=8, limit_bytes=2)
        assert fragment["content"] == "ok", fragment
        matches = await call("search_code", pattern="sandbox", glob="*.txt")
        assert any("hello.txt:1:sandbox-ok" in match for match in matches["matches"]), matches
        for path in ("/src/escape", "/src/../etc/passwd", "/etc/passwd"):
            assert "error" in await call("read_file", path=path)
        assert "error" in await call("read_file", path="/src")
        assert "error" in await call("run_command", command="pwd", cwd="/etc")
        assert (await call("run_command", command="id -u"))["output"].strip() == "1001"
        write_result = await call("run_command", command="printf 'tool-ok' > /workspace/tool.txt")
        assert write_result["exit_code"] == 0, write_result
        output = await call("run_command", command="python -I -c \"print('x' * 1100000)\"")
        assert output["truncated"] and len(output["output"].encode()) == 1024 * 1024
        timeout = await call("run_command", command="sleep 30", timeout_seconds=1)
        assert "error" in timeout, timeout
        long_exec = asyncio.create_task(call("run_command", command="sleep 60"))
        await asyncio.sleep(0.5)
        before = time.monotonic()
        await _REAL_INTERRUPT(container.id)
        await asyncio.wait_for(long_exec, 3)
        assert time.monotonic() - before < 5
        await asyncio.to_thread(container.reload)
        assert container.status == "exited"
    finally:
        if helper is not None:
            await asyncio.to_thread(containers.remove_container, helper)
        if container is not None:
            await asyncio.to_thread(containers.remove_container, container)
        if client is not None:
            await asyncio.to_thread(volumes.remove_volume, client, source_volume)
            await asyncio.to_thread(volumes.remove_volume, client, workspace_volume)
            await asyncio.to_thread(client.close)
        archive.cleanup_tar(tar_path)
