import asyncio
import shutil
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import (
    AppError,
    BadRequest,
    Conflict,
    Forbidden,
    NotFound,
    SandboxError,
    TooManyRequests,
)
from app.core.paths import data_root
from app.models.analysis import AttackPath, AttackPathItem, Vulnerability
from app.models.collab import ChatMessage, ResourceUsage, RuntimeLog
from app.models.project import Project, ProjectRun
from app.models.report import Report
from app.models.runtime import RuntimeStage, WorkerTask
from app.models.user import User
from app.schemas.project import ProjectCreateRequest
from app.services import config_service, sandbox_service, source_service
from app.services.audit import audit
from app.services.events import publish
from app.services.llm_probe import probe_llm
from app.services.run_manager import run_manager

_STARTABLE = ("created", "stopped", "failed", "completed")


def project_dirs(project_id: int) -> list[Path]:
    root = data_root()
    return [
        root / "sources" / str(project_id),
        root / "workspace" / str(project_id),
        root / "reports" / str(project_id),
        root / "runtime_logs" / str(project_id),
    ]


def _remove_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _cleanup_dirs(project_id: int) -> None:
    for path in project_dirs(project_id):
        _remove_dir(path)


async def get_visible_project(db: AsyncSession, project_id: int, user: User) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFound("项目不存在")
    if user.role != "admin" and project.created_by != user.id:
        raise Forbidden("无权访问该项目")
    return project


async def create_project(db: AsyncSession, *, user: User, payload: ProjectCreateRequest) -> Project:
    name = payload.project_name.strip()
    if not name:
        raise BadRequest("项目名称不能为空白")
    source_path = payload.source_path.strip()
    task_content = payload.task_content.strip()
    if not source_path:
        raise BadRequest("源码路径不能为空")
    if not task_content:
        raise BadRequest("任务说明不能为空")

    await source_service.validate_source(db, payload.source_type, source_path)

    exists = await db.scalar(select(Project.id).where(Project.created_by == user.id, Project.project_name == name))
    if exists is not None:
        raise Conflict("同一创建者下项目名称不能重复")

    project = Project(
        project_name=name,
        source_type=payload.source_type,
        source_path=source_path,
        task_content=task_content,
        project_status="created",
        sandbox_type=payload.sandbox_type,
        created_by=user.id,
    )
    db.add(project)
    await db.flush()
    await audit(db, "project_create", actor_id=user.id, detail={"project_id": project.id})
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("同一创建者下项目名称不能重复") from exc
    await db.refresh(project)
    return project


def _conditions(user: User, status: str | None, keyword: str | None):
    conditions = []
    if user.role != "admin":
        conditions.append(Project.created_by == user.id)
    if status:
        conditions.append(Project.project_status == status)
    if keyword:
        conditions.append(Project.project_name.ilike(f"%{keyword.strip()}%"))
    return conditions


async def list_projects(
    db: AsyncSession,
    *,
    user: User,
    status: str | None,
    keyword: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Project], int]:
    conditions = _conditions(user, status, keyword)
    total = await db.scalar(select(func.count()).select_from(Project).where(*conditions))
    rows = (
        await db.scalars(
            select(Project)
            .where(*conditions)
            .order_by(Project.updated_at.desc(), Project.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return list(rows), int(total or 0)


async def get_project_detail(db: AsyncSession, project: Project, *, run_id: int | None) -> dict:
    from app.services.monitoring import counts

    runs = (
        await db.scalars(
            select(ProjectRun).where(ProjectRun.project_id == project.id).order_by(ProjectRun.run_id.desc())
        )
    ).all()
    selected_run_id = run_id if run_id is not None else project.current_run_id
    if run_id is not None and all(item.run_id != run_id for item in runs):
        raise NotFound("指定的执行轮次不存在")

    stages = (
        await db.scalars(
            select(RuntimeStage)
            .where(
                RuntimeStage.project_id == project.id,
                RuntimeStage.run_id == selected_run_id,
            )
            .order_by(RuntimeStage.id)
        )
    ).all()
    vuln_count = await db.scalar(
        select(func.count())
        .select_from(Vulnerability)
        .where(
            Vulnerability.project_id == project.id,
            Vulnerability.run_id == selected_run_id,
        )
    )
    path_count = await db.scalar(
        select(func.count())
        .select_from(AttackPath)
        .where(AttackPath.project_id == project.id, AttackPath.run_id == selected_run_id)
    )
    report_count = await db.scalar(
        select(func.count())
        .select_from(Report)
        .where(Report.project_id == project.id, Report.run_id == selected_run_id)
    )

    if report_count:
        report_status = "ready"
    elif project.project_status == "running":
        report_status = "pending"
    else:
        report_status = "none"

    return {
        **project_payload(project),
        "selected_run_id": selected_run_id,
        "runs": [_run_payload(item) for item in runs],
        "stages": [_stage_payload(item) for item in stages],
        "counts": {
            "vulnerabilities": int(vuln_count or 0),
            "attack_paths": int(path_count or 0),
            "reports": int(report_count or 0),
        },
        "report_status": report_status,
        "vulnerability_stats": await counts(db, project.id, selected_run_id),
    }


async def _mark_failed(db: AsyncSession, project: Project, *, actor: User, message: str) -> None:
    project.project_status = "failed"
    project.updated_at = func.now()
    await audit(
        db,
        "project_start_failed",
        actor_id=actor.id,
        detail={"project_id": project.id, "error": message},
        level="error",
    )
    await db.commit()
    await db.refresh(project)


async def start_project(db: AsyncSession, project: Project, *, actor: User) -> int:
    project_id = project.id
    # 单进程准入锁同时保护同项目互斥与跨项目并发上限；实际执行不持有此锁。
    async with run_manager.admission_lock:
        await db.refresh(project)
        if project.project_status == "running":
            raise Conflict("任务执行中，不能重复启动")
        if project_id in run_manager.preparing or project_id in run_manager.handles:
            raise Conflict("上一轮任务正在收尾，请稍后重试")
        if project.cleanup_pending:
            raise Conflict("项目存在待清理目录，请先重试删除")
        raw = await config_service.get_config_raw(db)
        count = await db.scalar(select(func.count()).select_from(Project).where(Project.project_status == "running"))
        if int(count or 0) >= int(raw["limit.max_concurrent_projects"]):
            raise TooManyRequests("当前并发项目已满，请等待其他项目完成后重试")
        mock = get_settings().llm_mock
        if not mock:
            if any(not raw[key].strip() for key in ("llm.base_url", "llm.model", "llm.api_key")):
                raise BadRequest("模型配置不完整，请在系统配置中设置模型地址、名称与密钥并执行连接测试")
            probe = await probe_llm(
                base_url=raw["llm.base_url"],
                model=raw["llm.model"],
                api_key=raw["llm.api_key"],
                timeout_seconds=int(raw["llm.timeout_seconds"]),
            )
            if not all(probe[key] for key in ("url_ok", "model_ok", "auth_ok", "tools_ok")):
                raise BadRequest("模型连接测试未通过：" + probe["detail"])
        try:
            await source_service.validate_source(db, project.source_type, project.source_path, raw=raw)
        except AppError as exc:
            await _mark_failed(db, project, actor=actor, message=exc.message)
            raise
        except Exception as exc:
            await _mark_failed(db, project, actor=actor, message=exc.__class__.__name__)
            raise SandboxError(f"源码校验失败：{exc.__class__.__name__}") from exc
        result = await db.execute(
            update(Project)
            .where(
                Project.id == project_id,
                Project.project_status.in_(_STARTABLE),
                Project.cleanup_pending.is_(False),
            )
            .values(
                project_status="running",
                current_run_id=Project.current_run_id + 1,
                last_started_at=func.now(),
                updated_at=func.now(),
            )
            .returning(Project.current_run_id)
        )
        run_id = result.scalar_one_or_none()
        if run_id is None:
            raise Conflict("项目当前状态不允许启动")
        db.add(ProjectRun(project_id=project_id, run_id=run_id))
        await audit(db, "project_start", actor_id=actor.id, detail={"project_id": project_id, "run_id": run_id})
        await db.commit()
        await db.refresh(project)
        run_manager.preparing.add(project_id)
        publish("project_status", project_id, int(run_id), {
            "project_id": project_id, "project_status": "running", "run_id": int(run_id)
        })
    try:
        await sandbox_service.start_run(db, project, int(run_id), raw=raw)
        await db.refresh(project)
        if project.project_status != "running" or project.current_run_id != run_id:
            raise Conflict("任务在环境准备期间已停止")
        run_manager.launch(project_id, int(run_id), raw, mock=mock)
    except Conflict:
        raise
    except AppError as exc:
        await run_manager.finish(project_id, int(run_id), "failed", exc.message)
        raise
    except Exception as exc:
        await run_manager.finish(project_id, int(run_id), "failed", exc.__class__.__name__)
        raise SandboxError(f"隔离环境启动失败：{exc.__class__.__name__}") from exc
    finally:
        run_manager.preparing.discard(project_id)
    return int(run_id)


async def stop_project(db: AsyncSession, project: Project, *, actor: User) -> str:
    project_id, run_id = project.id, project.current_run_id
    if project.project_status == "stopped":
        return "stopped"
    if project.project_status != "running":
        raise Conflict("项目当前状态不允许停止")
    await run_manager.cancel(project_id)
    changed = await run_manager.finish(project_id, run_id, "stopped", "任务被手动停止")
    await db.refresh(project)
    if not changed and project.project_status != "stopped":
        raise Conflict("项目当前状态不允许停止")
    if changed:
        await audit(db, "project_stop", actor_id=actor.id, detail={"project_id": project_id, "run_id": run_id})
        await db.commit()
    return "stopped"


async def _cascade_delete(db: AsyncSession, project_id: int) -> None:
    path_ids = select(AttackPath.id).where(AttackPath.project_id == project_id)
    await db.execute(delete(AttackPathItem).where(AttackPathItem.path_id.in_(path_ids)))
    await db.execute(delete(AttackPath).where(AttackPath.project_id == project_id))
    await db.execute(delete(Vulnerability).where(Vulnerability.project_id == project_id))
    await db.execute(delete(RuntimeLog).where(RuntimeLog.project_id == project_id))
    await db.execute(delete(WorkerTask).where(WorkerTask.project_id == project_id))
    await db.execute(delete(ChatMessage).where(ChatMessage.project_id == project_id))
    await db.execute(delete(ResourceUsage).where(ResourceUsage.project_id == project_id))
    await db.execute(delete(Report).where(Report.project_id == project_id))
    await db.execute(delete(RuntimeStage).where(RuntimeStage.project_id == project_id))
    await db.execute(delete(ProjectRun).where(ProjectRun.project_id == project_id))
    await db.execute(delete(Project).where(Project.id == project_id))


async def delete_project(db: AsyncSession, project: Project, *, actor: User) -> tuple[bool, bool, str | None]:
    if project.id in run_manager.preparing:
        raise Conflict("源码与隔离环境仍在准备收尾，请稍后重试删除")
    try:
        await sandbox_service.cleanup_project(project)
        await asyncio.to_thread(_cleanup_dirs, project.id)
    except Exception as exc:  # noqa: BLE001 - 清理失败需要保留记录供重试
        project.cleanup_pending = True
        project.cleanup_error = str(exc)
        await audit(
            db,
            "project_delete_failed",
            actor_id=actor.id,
            detail={"project_id": project.id, "error": str(exc)},
            level="error",
        )
        await db.commit()
        return False, False, f"环境清理失败：{exc}"

    try:
        await _cascade_delete(db, project.id)
        await audit(db, "project_delete", actor_id=actor.id, detail={"project_id": project.id})
        await db.commit()
        return True, True, None
    except SQLAlchemyError as exc:
        await db.rollback()
        return False, True, f"数据库删除失败：{exc.__class__.__name__}"


def project_payload(project: Project) -> dict:
    return {
        "id": project.id,
        "project_name": project.project_name,
        "source_type": project.source_type,
        "source_path": project.source_path,
        "task_content": project.task_content,
        "project_status": project.project_status,
        "sandbox_type": project.sandbox_type,
        "sandbox_id": project.sandbox_id,
        "current_run_id": project.current_run_id,
        "last_started_at": _iso(project.last_started_at),
        "last_finished_at": _iso(project.last_finished_at),
        "cleanup_pending": project.cleanup_pending,
        "created_by": project.created_by,
        "created_at": _iso(project.created_at),
        "updated_at": _iso(project.updated_at),
    }


def _run_payload(run: ProjectRun) -> dict:
    return {
        "run_id": run.run_id,
        "source_revision": run.source_revision,
        "source_fingerprint": run.source_fingerprint,
        "source_fingerprint_after": run.source_fingerprint_after,
        "created_at": _iso(run.created_at),
    }


def _stage_payload(stage: RuntimeStage) -> dict:
    return {
        "stage_id": stage.id,
        "stage_name": stage.stage_name,
        "stage_status": stage.stage_status,
        "started_at": _iso(stage.started_at),
        "finished_at": _iso(stage.finished_at),
        "error_message": stage.error_message,
    }


def _iso(value) -> str | None:
    return value.isoformat() if value else None
