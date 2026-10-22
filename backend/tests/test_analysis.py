import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.agents.contracts import InvalidOutput, validate_output
from app.agents.engine import RoleEngine
from app.agents.mock import mock_output
from app.core.paths import data_root
from app.main import app
from app.models.analysis import AttackPathItem, Vulnerability
from app.models.project import ProjectRun
from app.models.runtime import RuntimeStage
from app.services.run_store import RunStore, normalize_risk
from tests.conftest import login
from tests.test_monitoring import connect
from tests.test_projects_api import create_project, setup_admin
from tests.test_role_engine import FakeTools, ScriptedModel, config
from tests.test_run_manager import settled, start


async def test_analysis_queries_filters_history_and_ownership(client, tmp_path, manager):
    project_id, _ = await start(client, tmp_path, manager)
    await settled(manager, project_id)
    base = f"/api/projects/{project_id}"
    first = (await client.get(f"{base}/vulnerabilities?page_size=1")).json()["data"]
    assert first["total"] == 2 and len(first["items"]) == 1
    vuln_id = first["items"][0]["id"]
    detail = (await client.get(f"{base}/vulnerabilities/{vuln_id}")).json()["data"]
    assert all(
        key in detail
        for key in (
            "impact_text",
            "condition_text",
            "evidence_text",
            "reproduce_steps_text",
            "verify_code_text",
            "stage_id",
        )
    )
    assert (await client.get(f"{base}/vulnerabilities?verify_status=verified")).json()["data"]["total"] == 0
    assert (await client.get(f"{base}/vulnerabilities?keyword=VULN-001")).json()["data"]["total"] == 1
    paths = (await client.get(f"{base}/attack-paths")).json()["data"]
    path_id = paths["items"][0]["id"]
    path = (await client.get(f"{base}/attack-paths/{path_id}")).json()["data"]
    assert [step["step_order"] for step in path["steps"]] == [1, 2]
    assert all(step["vuln"]["verify_status"] == "unverified" for step in path["steps"])
    assert (await client.get(f"{base}/vulnerabilities?risk_level=invalid")).status_code == 400
    await client.post(f"{base}/start")
    await settled(manager, project_id)
    assert (await client.get(f"{base}/vulnerabilities?run_id=1")).json()["data"]["items"][0]["id"] == vuln_id
    assert all(row["run_id"] == 2 for row in (await client.get(f"{base}/vulnerabilities")).json()["data"]["items"])
    assert (await client.get(f"{base}/attack-paths?run_id=99")).status_code == 404
    await client.post("/api/system/users", json={"username": "other", "password": "Other@12345"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
        await login(other, "other", "Other@12345")
        for endpoint in (
            "vulnerabilities",
            f"vulnerabilities/{vuln_id}",
            "attack-paths",
            f"attack-paths/{path_id}",
            "messages",
            "logs",
            "resources",
        ):
            assert (await other.get(f"{base}/{endpoint}")).status_code == 403
        async with connect(other, project_id) as socket:
            assert (await socket.receive())["code"] == 4403
        assert (await other.get("/api/system/resources")).status_code == 403
        assert (await other.get("/api/system/logs")).status_code == 403


async def test_dedup_risk_and_full_evidence(client, tmp_path, db_session_factory):
    source = await setup_admin(client, tmp_path)
    project_id = (await create_project(client, source))["project_id"]
    store = RunStore(db_session_factory, project_id, 1)
    candidate = json.loads(mock_output("code_analysis", "code_analyst", {}))["candidates"][0]
    candidate.update(vuln_type="injection", cvss_score=9.4, evidence_text="中文" * 30000)
    duplicate = {**candidate, "evidence_text": "additional evidence"}
    async with db_session_factory() as db:
        db.add(ProjectRun(project_id=project_id, run_id=1))
        await db.flush()
        stage = RuntimeStage(project_id=project_id, run_id=1, stage_name="code_analysis", stage_status="running")
        db.add(stage)
        await db.flush()
        await store.persist(
            db, "code_analysis", "code_analyst", stage.id, {"candidates": [candidate, duplicate]}, mock=False
        )
        await db.commit()
        rows = (await db.scalars(select(Vulnerability).where(Vulnerability.project_id == project_id))).all()
        assert len(rows) == 1 and rows[0].vuln_code == "VULN-001"
        assert rows[0].risk_level == "critical" and len(rows[0].evidence_text.encode()) <= 65536
        assert "完整证据" in rows[0].evidence_text
        archived = (data_root() / "workspace" / str(project_id) / "1" / "VULN-001-evidence.txt").read_text("utf-8")
        assert archived == candidate["evidence_text"] + "\nadditional evidence"


async def test_real_verdict_persistence_and_step_cascade(client, tmp_path, manager, db_session_factory):
    project_id, _ = await start(client, tmp_path, manager)
    await settled(manager, project_id)
    store = RunStore(db_session_factory, project_id, 1)
    context = await store.context()
    result = json.loads(mock_output("vulnerability_verify", "vuln_verifier", context))
    result["verdicts"][0].update(verify_status="verified", cvss_score=8.5)
    async with db_session_factory() as db:
        stage = await db.scalar(
            select(RuntimeStage).where(
                RuntimeStage.project_id == project_id, RuntimeStage.stage_name == "vulnerability_verify"
            )
        )
        await store.persist(db, "vulnerability_verify", "vuln_verifier", stage.id, result, mock=False)
        await db.commit()
        vuln = await db.scalar(
            select(Vulnerability).where(Vulnerability.project_id == project_id).order_by(Vulnerability.id)
        )
        assert vuln.verify_status == "verified" and vuln.risk_level == "high"
        await db.execute(delete(Vulnerability).where(Vulnerability.id == vuln.id))
        await db.commit()
        items = (await db.scalars(select(AttackPathItem))).all()
        assert len(items) == 1 and items[0].vuln_id != vuln.id


@pytest.mark.parametrize("status", ["pending", "false_positive", "other_run"])
def test_paths_reject_unusable_vulnerabilities(status):
    context = {
        "vulnerabilities": [
            {"vuln_code": "VULN-001", "verify_status": status},
            {"vuln_code": "VULN-002", "verify_status": "verified"},
        ]
    }
    output = {
        "summary": "path",
        "paths": [
            {
                "path_title": "chain",
                "path_summary": "chain",
                "final_impact_text": "impact",
                "steps": [{"vuln_code": "VULN-001", "step_text": "one"}, {"vuln_code": "VULN-002", "step_text": "two"}],
            }
        ],
    }
    if status == "other_run":
        context["vulnerabilities"].pop(0)
    with pytest.raises(InvalidOutput):
        validate_output("vulnerability_verify", "code_analyst", json.dumps(output), context)


@pytest.mark.parametrize("executed", [False, True])
async def test_real_verifier_requires_command_evidence(executed):
    context = {"vulnerabilities": [{"vuln_code": "VULN-001", "verify_status": "pending"}]}
    output = json.loads(mock_output("vulnerability_verify", "vuln_verifier", context))
    output["verdicts"][0].update(verify_status="verified", verify_code_text="print('proof')")
    call = {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "proof",
                "type": "function",
                "function": {"name": "run_command", "arguments": '{"command":"python /workspace/proof.py"}'},
            }
        ],
    }
    model = ScriptedModel(([call] if executed else []) + [json.dumps(output)])

    class Tools(FakeTools):
        async def execute(self, name, arguments):
            return {"exit_code": 0, "output": "proof"}

    async def observe(*args, **kwargs):
        pass

    result = await RoleEngine(config(), mock=False, model=model).execute(
        stage="vulnerability_verify",
        role="vuln_verifier",
        task="verify local fixture",
        context=context,
        tools=Tools(),
        observe=observe,
        cancel=asyncio.Event(),
    )
    assert result["verdicts"][0]["verify_status"] == ("verified" if executed else "unverified")


async def test_empty_verification_and_path_succeed_without_mock():
    async def observe(*args, **kwargs):
        pass

    for role in ("vuln_verifier", "code_analyst"):
        output = mock_output("vulnerability_verify", role, {"vulnerabilities": []})
        result = await RoleEngine(config(), mock=False, model=ScriptedModel([output])).execute(
            stage="vulnerability_verify",
            role=role,
            task="clean",
            context={"vulnerabilities": []},
            tools=FakeTools(),
            observe=observe,
            cancel=asyncio.Event(),
        )
        assert result["verdicts" if role == "vuln_verifier" else "paths"] == []


@pytest.mark.parametrize(
    "score,level",
    [
        (10, "critical"),
        (9, "critical"),
        (8.9, "high"),
        (7, "high"),
        (6.9, "medium"),
        (4, "medium"),
        (3.9, "low"),
        (0.1, "low"),
        (0, "info"),
        (None, "medium"),
    ],
)
def test_cvss_boundaries(score, level):
    value = {"cvss_score": score, "evidence_text": "proof"}
    normalize_risk(value)
    assert value["risk_level"] == level
    assert ("待人工复核" in value["evidence_text"]) == (score is None)
