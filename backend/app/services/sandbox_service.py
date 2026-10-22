import asyncio
import logging

import httpx
from docker.errors import ImageNotFound, NotFound
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import SandboxError
from app.models.project import Project, ProjectRun
from app.sandbox import archive, containers, volumes
from app.sandbox.client import docker_http_url, get_client
from app.sandbox.names import source_volume_name, workspace_volume_name
from app.services import config_service, source_service
from app.services.audit import audit

logger = logging.getLogger(__name__)


async def _retry(func, *args, attempts: int = 3, delay: float = 1.0, **kwargs):
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return await asyncio.to_thread(func, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - 失败后按 NFR-R03 重试
            last_error = exc
            if attempt < attempts - 1:
                await asyncio.sleep(delay)
    assert last_error is not None
    raise last_error


async def _create_container_with_retry(client, kwargs: dict):
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            return await asyncio.to_thread(containers.create_container, client, kwargs)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            try:
                stale = await asyncio.to_thread(containers.get_container, client, kwargs["name"])
                await asyncio.to_thread(containers.remove_container, stale)
            except Exception:  # noqa: BLE001 - 不存在同名容器时忽略
                pass
            if attempt < 2:
                await asyncio.sleep(1)
    assert last_error is not None
    raise last_error


async def start_run(db: AsyncSession, project: Project, run_id: int, *, raw: dict[str, str] | None = None) -> None:
    """准备源码与隔离环境：上传源码卷、创建工作区卷并启动容器。"""
    raw = raw if raw is not None else await config_service.get_config_raw(db)
    prepared = await source_service.prepare_source(
        db,
        project_id=project.id,
        source_type=project.source_type,
        source_path=project.source_path,
        raw=raw,
    )

    if project.sandbox_id:
        await asyncio.to_thread(_remove_container_sync, project.sandbox_id)
        project.sandbox_id = None
        await db.commit()

    source_volume = source_volume_name(project.id)
    workspace_volume = workspace_volume_name(project.id, run_id)

    client = None
    helper = None
    container = None
    tar_path = None
    try:
        client = await asyncio.to_thread(get_client)
        try:
            await asyncio.to_thread(client.images.get, raw["sandbox.image"])
        except ImageNotFound as exc:
            raise SandboxError(f"隔离环境镜像 {raw['sandbox.image']} 不存在，请先构建 sandbox 镜像") from exc

        await asyncio.to_thread(volumes.remove_volume, client, source_volume)
        await _retry(volumes.ensure_volume, client, source_volume, project_id=project.id)
        await _retry(
            volumes.ensure_volume,
            client,
            workspace_volume,
            project_id=project.id,
            run_id=run_id,
        )

        tar_path = await asyncio.to_thread(archive.create_source_tar, prepared.directory)
        helper = await _retry(
            containers.create_helper,
            client,
            raw["sandbox.image"],
            {
                source_volume: {"bind": "/src", "mode": "rw"},
                workspace_volume: {"bind": "/workspace", "mode": "rw"},
            },
            ["sh", "-c", "chown -R 1001:1001 /src /workspace && chmod -R a+rX /src"],
        )
        try:
            await archive.upload_tar(helper.id, tar_path, "/src", docker_http_url())
            await asyncio.to_thread(containers.start_and_wait, helper, 300)
        finally:
            await asyncio.to_thread(containers.remove_container, helper)
            helper = None

        kwargs = containers.build_create_kwargs(
            project_id=project.id,
            run_id=run_id,
            image=raw["sandbox.image"],
            cpu_limit=float(raw["sandbox.cpu_limit"]),
            memory_limit_mb=int(raw["sandbox.memory_limit_mb"]),
            network_enabled=raw["sandbox.network_enabled"] == "true",
            source_volume=source_volume,
            workspace_volume=workspace_volume,
        )
        container = await _create_container_with_retry(client, kwargs)
        await _retry(container.start)
    except Exception:
        if helper is not None:
            await asyncio.to_thread(containers.remove_container, helper)
        if container is not None:
            await asyncio.to_thread(containers.remove_container, container)
        if client is not None:
            try:
                await asyncio.to_thread(volumes.remove_volume, client, source_volume)
                await asyncio.to_thread(volumes.remove_volume, client, workspace_volume)
            except Exception:  # noqa: BLE001 - 清理失败不覆盖原始错误
                logger.warning("failed to clean sandbox volumes", exc_info=True)
        raise
    finally:
        if tar_path is not None:
            await asyncio.to_thread(archive.cleanup_tar, tar_path)
        if client is not None:
            await asyncio.to_thread(client.close)

    await db.refresh(project)
    if project.project_status != "running" or project.current_run_id != run_id:
        # 准备环境期间收到停止信号：绝不将迟到的容器绑定到下一轮。
        await asyncio.to_thread(_remove_container_sync, container.id)
        return
    project.sandbox_id = container.id
    run = await db.get(ProjectRun, (project.id, run_id))
    if run is not None:
        run.source_revision = prepared.revision
        run.source_fingerprint = prepared.fingerprint
    await db.commit()


def _remove_container_sync(reference: str) -> None:
    client = get_client()
    try:
        try:
            container = containers.get_container(client, reference)
        except NotFound:
            return
        containers.remove_container(container)
    finally:
        client.close()


def _stop_sync(reference: str) -> None:
    client = get_client()
    try:
        try:
            container = containers.get_container(client, reference)
        except NotFound:
            return
        containers.stop_container(container)
    finally:
        client.close()


async def stop_run(db: AsyncSession, project: Project) -> None:
    if not project.sandbox_id:
        return
    try:
        await asyncio.to_thread(_stop_sync, project.sandbox_id)
    except Exception as exc:  # noqa: BLE001 - 停止环境失败记录告警，不阻断状态更新
        await audit(
            db,
            "sandbox_stop_failed",
            detail={"project_id": project.id, "error": str(exc)},
            level="warning",
        )
        await db.commit()


def _cleanup_sync(project_id: int, sandbox_id: str | None) -> None:
    client = get_client()
    try:
        if sandbox_id:
            try:
                container = containers.get_container(client, sandbox_id)
                containers.remove_container(container)
            except NotFound:
                pass
        for volume in volumes.list_volumes(client, f"sec-eval-ws-{project_id}-"):
            volumes.remove_volume(client, volume["name"])
        volumes.remove_volume(client, source_volume_name(project_id))
    finally:
        client.close()


async def cleanup_project(project: Project) -> None:
    await asyncio.to_thread(_cleanup_sync, project.id, project.sandbox_id)


def _list_sync() -> dict:
    client = get_client()
    try:
        return {
            "containers": containers.list_sandbox_containers(client),
            "volumes": volumes.list_volumes(client, "sec-eval-"),
        }
    finally:
        client.close()


async def list_sandboxes(db: AsyncSession) -> dict:
    data = await asyncio.to_thread(_list_sync)

    project_ids = {item["project_id"] for item in data["containers"] if item.get("project_id")}
    if project_ids:
        projects = (await db.scalars(select(Project).where(Project.id.in_(project_ids)))).all()
        names = {project.id: project.project_name for project in projects}
        for item in data["containers"]:
            item["project_name"] = names.get(item.get("project_id"))

    pending = (await db.scalars(select(Project).where(Project.cleanup_pending.is_(True)))).all()
    data["cleanup_pending_projects"] = [
        {
            "id": project.id,
            "project_name": project.project_name,
            "cleanup_error": project.cleanup_error,
            "updated_at": project.updated_at.isoformat() if project.updated_at else None,
        }
        for project in pending
    ]
    return data


def _force_remove_sync(reference: str) -> None:
    client = get_client()
    try:
        try:
            container = containers.get_container(client, reference)
        except NotFound:
            return
        containers.remove_container(container)
    finally:
        client.close()


async def force_remove(reference: str) -> None:
    await asyncio.to_thread(_force_remove_sync, reference)


async def interrupt_run(reference: str) -> None:
    """立即终止所有 exec 进程并停止但保留容器；不等待 Docker 的 10 秒优雅停止。"""
    try:
        async with httpx.AsyncClient(base_url=docker_http_url(), timeout=2) as client:
            response = await client.post(f"/containers/{reference}/kill", params={"signal": "SIGKILL"})
            if response.status_code not in {204, 304, 404, 409}:
                response.raise_for_status()
    except Exception:
        logger.warning("failed to interrupt sandbox %s", reference, exc_info=True)


async def destroy_run(reference: str) -> None:
    """仅在 done 的两个角色成功后销毁；工作区卷保持不变。"""
    await _retry(_stop_and_remove_sync, reference)


def _stop_and_remove_sync(reference: str) -> None:
    client = get_client()
    try:
        try:
            container = containers.get_container(client, reference)
        except NotFound:
            return
        containers.stop_container(container, timeout=10)
        containers.remove_container(container)
    finally:
        client.close()
