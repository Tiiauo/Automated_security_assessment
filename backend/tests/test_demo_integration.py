import asyncio
import json
import os
import secrets

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import BASE_DIR
from app.models.project import Project, ProjectRun
from app.models.user import User
from app.sandbox.tools import SandboxTools
from app.services import config_service, sandbox_service, source_service

_REAL_START = sandbox_service.start_run
_REAL_CLEANUP = sandbox_service.cleanup_project

pytestmark = pytest.mark.skipif(
    os.environ.get("SANDBOX_INTEGRATION") != "1", reason="设置 SANDBOX_INTEGRATION=1 以验证内置 Flask 样本"
)

VULNERABLE_CHECK = r"""
import ast
from pathlib import Path
client = create_app('/workspace').test_client()
assert client.get('/health').status_code == 200
assert client.post('/admin/ping', json={'host': '127.0.0.1'}).status_code == 401
normal = client.get('/search?q=welcome').get_json()
assert normal == [{'title': 'welcome', 'body': 'Public training document'}]
leaked = client.get('/download', query_string={'filename': '../config.py'})
assert leaked.status_code == 200
values = {}
for item in ast.parse(leaked.get_data(as_text=True)).body:
    if isinstance(item, ast.Assign):
        values[item.targets[0].id] = ast.literal_eval(item.value)
assert values['ADMIN_PASSWORD'].startswith('FICTIONAL_')
assert client.post('/admin/login', json={
    'username': values['ADMIN_USERNAME'], 'password': values['ADMIN_PASSWORD']
}).status_code == 200
marker = Path('/workspace/demo-command-proof.txt')
marker.unlink(missing_ok=True)
executed = client.post('/admin/ping', json={
    'host': '127.0.0.1; printf DEMO_COMMAND_OK > /workspace/demo-command-proof.txt'
})
assert executed.status_code == 200 and marker.read_text() == 'DEMO_COMMAND_OK'
rows = client.get('/search', query_string={'q': "' OR 1=1 -- "}).get_json()
assert any(row['body'] == 'FICTIONAL_INTERNAL_DOCUMENT' for row in rows)
print('four vulnerabilities and three-step credential-to-command chain verified')
"""

CLEAN_CHECK = r"""
client = create_app().test_client()
assert client.get('/health').get_json() == {'status': 'ok'}
value = '<script>alert(1)</script>; echo unsafe'
response = client.get('/greet', query_string={'name': value})
assert response.content_type == 'application/json'
assert response.get_json() == {'message': 'Hello, ' + value + '!'}
for path in ('/download', '/search', '/admin/login', '/admin/ping'):
    assert client.get(path).status_code == 404
print('clean control endpoints verified')
"""


@pytest.mark.parametrize("sample", ["demo-app", "demo-clean"])
async def test_builtin_demo_in_real_sandbox(db_engine, sample):
    source = BASE_DIR / "data" / "allowed_sources" / sample
    before = source_service.compute_fingerprint(source)
    project_id = 9_000_000_000 + secrets.randbelow(999_999_999)
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as db:
        user = User(username=f"demo-{project_id}", password_hash="not-a-login", role="admin", status="active")
        db.add(user)
        await db.flush()
        await config_service.update_config(db, {"sandbox.allowed_source_root": str(source.parent)}, actor_id=user.id)
        project = Project(
            id=project_id,
            project_name=sample,
            source_type="local_path",
            source_path=str(source),
            task_content="built-in sample verification",
            project_status="running",
            sandbox_type="docker",
            current_run_id=1,
            created_by=user.id,
        )
        db.add(project)
        await db.flush()
        db.add(ProjectRun(project_id=project_id, run_id=1))
        await db.commit()
        try:
            await _REAL_START(db, project, 1)
            code = "import sys\nsys.path.insert(0, '/src')\nfrom app import create_app\n"
            code += VULNERABLE_CHECK if sample == "demo-app" else CLEAN_CHECK
            result = await SandboxTools(project.sandbox_id, 60).execute(
                "run_command", json.dumps({"command": "python - <<'PY'\n" + code + "\nPY"})
            )
            assert result.get("exit_code") == 0, result
            assert "verified" in result["output"]
            assert await asyncio.to_thread(source_service.compute_fingerprint, source) == before
        finally:
            await _REAL_CLEANUP(project)
