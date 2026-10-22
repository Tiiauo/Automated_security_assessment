import asyncio
import json
from urllib.parse import unquote

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.agents.contracts import REPORT_SECTIONS, InvalidOutput, report_sections, validate_output
from app.agents.engine import RoleEngine, RoleFailed
from app.agents.mock import mock_output
from app.main import app
from app.models.project import Project
from app.models.report import Report
from app.services import report_service
from app.services.events import subscribers
from app.services.run_store import RunStore
from tests.conftest import login
from tests.test_role_engine import ScriptedModel, config, run_engine
from tests.test_run_manager import settled, start


def output(markdown=None):
    return {
        "markdown": markdown
        or "\n\n".join(f"## {number}. {heading}\n\n模型段落" for number, heading in enumerate(REPORT_SECTIONS, 1)),
        "conclusion_rating": "info",
    }


@pytest.mark.parametrize(
    "markdown",
    [
        "## 项目概述\n缺少章节",
        "```markdown\n" + output()["markdown"] + "\n```",
        output()["markdown"].replace("## 2. 执行过程", "## 2. 项目概述"),
        output()["markdown"].replace("## 1. 项目概述", "## 1. 修复建议").replace("## 6. 修复建议", "## 6. 项目概述"),
    ],
)
def test_report_requires_real_ordered_headings(markdown):
    with pytest.raises(InvalidOutput, match="二级标题"):
        validate_output("report_generate", "report_writer", json.dumps(output(markdown)), {})


def test_report_rejects_invented_references():
    with pytest.raises(InvalidOutput, match="本轮"):
        validate_output("report_generate", "report_writer", json.dumps(output(output()["markdown"] + "\nVULN-999")), {})


def test_report_rejects_empty_sections():
    with pytest.raises(InvalidOutput, match="空标题"):
        report_sections("\n".join(f"## {heading}" for heading in REPORT_SECTIONS))


async def test_report_schema_failure_repairs_and_exhausts():
    model = ScriptedModel([json.dumps(output("## 项目概述\n缺失")), json.dumps(output())])
    result, events, _ = await run_engine(model, stage="report_generate", role="report_writer")
    assert result == output()
    assert [value["retry_count"] for name, value in events if name == "retry"] == [1]
    with pytest.raises(RoleFailed, match="schema_invalid"):
        await run_engine(
            ScriptedModel([json.dumps(output("invalid"))]),
            stage="report_generate",
            role="report_writer",
            raw=config(**{"llm.max_retries": "0"}),
        )


async def test_report_http_formats_downloads_and_permissions(client, tmp_path, manager, db_session_factory):
    project_id, _ = await start(client, tmp_path, manager)
    await settled(manager, project_id)
    base = f"/api/projects/{project_id}/report"
    response = await client.get(base)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    report = response.json()["data"]
    assert report["report_id"] and report["run_id"] == 1
    assert list(report_sections(report["report_markdown"])) == list(REPORT_SECTIONS)
    assert "含待人工复核节点" in report["report_markdown"] and "未发现可验证漏洞" in report["report_markdown"]
    assert all(
        label in report["report_markdown"] for label in ("影响说明", "触发条件", "证据内容", "复现步骤", "验证代码")
    )
    async with db_session_factory() as db:
        project = await db.get(Project, project_id)
        project.project_name = '中文报告/测试\r\n"'
        await db.commit()
    for extension, format_name, field in (("md", "markdown", "report_markdown"), ("html", "html", "report_html")):
        inline = await client.get(base, params={"format": format_name})
        download = await client.get(base + "/download", params={"format": extension})
        assert inline.status_code == download.status_code == 200
        assert inline.content == download.content == report[field].encode()
        filename = unquote(download.headers["content-disposition"])
        assert "中文报告_测试___-run-1-security-report." + extension in filename
        assert "\r" not in filename and "\n" not in filename
        assert download.headers["x-content-type-options"] == "nosniff"
        assert "default-src 'none'" in inline.headers["content-security-policy"]
    assert (await client.get(base + "?format=pdf")).status_code == 400
    assert (await client.get(base + "/download?format=pdf")).status_code == 400
    await client.post("/api/system/users", json={"username": "outsider", "password": "Outside@12345"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as outsider:
        for suffix in ("", "/download"):
            assert (await outsider.get(base + suffix)).status_code == 401
        await login(outsider, "outsider", "Outside@12345")
        for suffix in ("", "/download"):
            assert (await outsider.get(base + suffix)).status_code == 403


async def test_report_history_never_falls_back_to_previous_run(client, tmp_path, manager):
    project_id, _ = await start(client, tmp_path, manager)
    await settled(manager, project_id)
    base = f"/api/projects/{project_id}"
    first = (await client.get(base + "/report")).json()["data"]
    from tests.conftest import HoldingEngine

    manager.engine_factory = HoldingEngine
    assert (await client.post(base + "/start")).status_code == 200
    assert (await client.get(base + "/report")).status_code == 404
    assert (await client.get(base + "/report/download")).status_code == 404
    assert (await client.get(base + "/report?run_id=99")).status_code == 404
    historical = (await client.get(base + "/report?run_id=1")).json()["data"]
    assert first == historical
    assert (await client.get(base + "/report/download?run_id=1")).content == first["report_markdown"].encode()


async def test_clean_real_pipeline_finishes_and_reports(client, tmp_path, manager):
    class CleanModel:
        async def complete(self, messages, tools, *, stage, role, context):
            if stage == "code_analysis" and role == "code_analyst":
                value = '{"summary":"干净项目","candidates":[]}'
            elif role == "report_writer":
                value = json.dumps(output())
            else:
                value = mock_output(stage, role, context)
            return {"message": {"role": "assistant", "content": value}, "tokens": 1, "model": "controlled-real"}

    def factory(raw, mock):
        return RoleEngine(raw, mock=False, model=CleanModel())

    project_id, _ = await start(client, tmp_path, manager, engine=factory)
    await settled(manager, project_id)
    detail = (await client.get(f"/api/projects/{project_id}")).json()["data"]
    assert detail["project_status"] == "completed" and detail["sandbox_id"] is None
    assert detail["counts"] == {"vulnerabilities": 0, "attack_paths": 0, "reports": 1}
    report = (await client.get(f"/api/projects/{project_id}/report")).json()["data"]
    assert "未发现可验证漏洞" in report["report_markdown"] and "未发现可串联的多步攻击路径" in report["report_markdown"]


async def test_report_context_has_canonical_facts(client, tmp_path, manager, db_session_factory):
    project_id, _ = await start(client, tmp_path, manager)
    await settled(manager, project_id)
    context = await RunStore(db_session_factory, project_id, 1).context()
    assert context["source"]["source_fingerprint"] == context["source"]["source_fingerprint_after"]
    assert len(context["paths"][0]["steps"]) == 2
    markdown = report_service.compose(output(), context, mock=False)
    for vuln in context["vulnerabilities"]:
        assert vuln["vuln_code"] in markdown and vuln["evidence_text"] in markdown
    context["project"]["project_name"] = "evil\n## 7. 插入章节<script>"
    context["vulnerabilities"][0]["evidence_text"] = "```\n## 8. 伪造\n<script>alert(1)</script>"
    markdown = report_service.compose(output(), context, mock=False)
    assert len(report_sections(markdown)) == 6


def test_html_sanitization_is_standalone():
    markdown = (
        "## 项目概述\n<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n![tracking](https://bad.invalid/x)"
    )
    rendered = report_service.render_html(markdown, '<img src=x onerror="alert(2)">')
    assert '<meta charset="utf-8">' in rendered
    assert "<script" not in rendered and "<img" not in rendered and 'href="javascript:' not in rendered


async def test_report_rollback_removes_files_and_never_publishes(client, tmp_path, manager, db_session_factory):
    project_id, _ = await start(client, tmp_path, manager)
    await settled(manager, project_id)
    store = RunStore(db_session_factory, project_id, 1)
    context = await store.context()
    queue = asyncio.Queue(maxsize=20)
    subscribers[project_id].add(queue)
    context["run_id"] = 2
    from app.models.project import ProjectRun

    async with db_session_factory() as db:
        db.add(ProjectRun(project_id=project_id, run_id=2))
        await db.commit()
        await report_service.save(db, project_id, 2, output(), context, mock=False)
        base = report_service.report_base(project_id, 2)
        assert base.with_suffix(".md").is_file() and queue.empty()
        await db.rollback()
        assert not base.with_suffix(".md").exists() and not base.with_suffix(".html").exists()
        assert queue.empty()
    subscribers.pop(project_id, None)


async def test_report_disk_failure_blocks_commit(client, tmp_path, manager, db_session_factory, monkeypatch):
    project_id, _ = await start(client, tmp_path, manager)
    await settled(manager, project_id)
    context = await RunStore(db_session_factory, project_id, 1).context()
    from app.models.project import ProjectRun

    async with db_session_factory() as db:
        db.add(ProjectRun(project_id=project_id, run_id=2))
        await db.commit()
        count = 0
        original = report_service.os.replace

        def fail_second(source, target):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("disk full")
            original(source, target)

        monkeypatch.setattr(report_service.os, "replace", fail_second)
        with pytest.raises(OSError, match="disk full"):
            await report_service.save(db, project_id, 2, output(), context, mock=False)
        await db.rollback()
        base = report_service.report_base(project_id, 2)
        assert not base.with_suffix(".md").exists() and not base.with_suffix(".html").exists()
        assert not list(base.parent.glob(".report-*.tmp"))
        assert await db.scalar(select(func.count()).select_from(Report).where(Report.run_id == 2)) == 0


async def test_download_ignores_database_path_and_refuses_corruption(client, tmp_path, manager, db_session_factory):
    project_id, _ = await start(client, tmp_path, manager)
    await settled(manager, project_id)
    async with db_session_factory() as db:
        row = await db.scalar(select(Report).where(Report.project_id == project_id))
        row.report_file_path = str(tmp_path / "sensitive.txt")
        await db.commit()
    base = f"/api/projects/{project_id}/report/download"
    assert (await client.get(base)).status_code == 200
    path = report_service.report_base(project_id, 1).with_suffix(".md")
    path.write_text("modified", encoding="utf-8")
    assert (await client.get(base)).status_code == 500
    path.unlink()
    assert (await client.get(base)).status_code == 500


async def test_pipeline_write_failure_rolls_back_artifacts(client, tmp_path, manager, monkeypatch):
    def fail(base, markdown, rendered):
        base.parent.mkdir(parents=True, exist_ok=True)
        base.with_suffix(".md").write_text(markdown, encoding="utf-8")
        raise OSError("partial report failure")

    monkeypatch.setattr(report_service, "write_files", fail)
    project_id, _ = await start(client, tmp_path, manager)
    await settled(manager, project_id)
    detail = (await client.get(f"/api/projects/{project_id}")).json()["data"]
    assert detail["project_status"] == "failed" and detail["counts"]["reports"] == 0
    assert (await client.get(f"/api/projects/{project_id}/report")).status_code == 404
    base = report_service.report_base(project_id, 1)
    assert not base.with_suffix(".md").exists() and not base.with_suffix(".html").exists()


async def test_source_change_during_report_blocks_publication(client, tmp_path, manager):
    class ChangingEngine(RoleEngine):
        async def execute(self, **kwargs):
            result = await super().execute(**kwargs)
            if kwargs["role"] == "report_writer":
                source.write_text("print('changed during report')\n", encoding="utf-8")
            return result

    source = tmp_path / "app" / "main.py"
    project_id, _ = await start(client, tmp_path, manager, engine=ChangingEngine)
    await settled(manager, project_id)
    detail = (await client.get(f"/api/projects/{project_id}")).json()["data"]
    assert detail["project_status"] == "failed" and detail["counts"]["reports"] == 0
    assert "指纹" in detail["stages"][-1]["error_message"]
    assert detail["runs"][0]["source_fingerprint"] != detail["runs"][0]["source_fingerprint_after"]


async def test_duplicate_report_preserves_committed_files(client, tmp_path, manager, db_session_factory):
    from sqlalchemy.exc import IntegrityError

    project_id, _ = await start(client, tmp_path, manager)
    await settled(manager, project_id)
    context = await RunStore(db_session_factory, project_id, 1).context()
    path = report_service.report_base(project_id, 1).with_suffix(".md")
    original = path.read_bytes()
    async with db_session_factory() as db:
        with pytest.raises(IntegrityError):
            await report_service.save(db, project_id, 1, output(), context, mock=False)
        await db.rollback()
    assert path.read_bytes() == original
