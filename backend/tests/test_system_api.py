from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import init_admin, login


async def test_status_before_init(client: AsyncClient) -> None:
    response = await client.get("/api/system/status")
    assert response.status_code == 200
    assert response.json()["data"]["initialized"] is False


async def test_init_and_duplicate_init(client: AsyncClient) -> None:
    data = await init_admin(client)
    assert data["admin_user_id"] > 0

    response = await client.get("/api/system/status")
    assert response.json()["data"]["initialized"] is True

    again = await client.post(
        "/api/system/init",
        json={"username": "other", "password": "Admin@12345", "create_demo_user": False},
    )
    assert again.status_code == 409
    assert again.json()["code"] == 40901


async def test_init_with_demo_user(client: AsyncClient) -> None:
    response = await client.post(
        "/api/system/init",
        json={"username": "admin", "password": "Admin@12345", "create_demo_user": True},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["demo_username"] == "demo_user"
    await login(client, "demo_user", data["demo_password"])


async def test_login_and_logout(client: AsyncClient) -> None:
    await init_admin(client)
    await login(client, "admin", "Admin@12345")
    assert client.cookies.get("access_token")

    config = await client.get("/api/system/config")
    assert config.status_code == 200

    logout = await client.post("/api/system/logout")
    assert logout.status_code == 200
    assert logout.json()["data"]["logged_out"] is True

    after = await client.get("/api/system/config")
    assert after.status_code == 401
    assert after.json()["code"] == 40101


async def test_wrong_password(client: AsyncClient) -> None:
    await init_admin(client)
    response = await client.post(
        "/api/system/login", json={"username": "admin", "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert response.json()["message"] == "用户名或密码错误"


async def test_login_lockout(client: AsyncClient) -> None:
    await init_admin(client)
    for _ in range(5):
        response = await client.post(
            "/api/system/login", json={"username": "admin", "password": "wrong-password"}
        )
        assert response.status_code == 401

    locked = await client.post(
        "/api/system/login", json={"username": "admin", "password": "Admin@12345"}
    )
    assert locked.status_code == 429
    assert locked.json()["code"] == 42901


async def test_non_admin_forbidden(client: AsyncClient) -> None:
    response = await client.post(
        "/api/system/init",
        json={"username": "admin", "password": "Admin@12345", "create_demo_user": True},
    )
    demo_password = response.json()["data"]["demo_password"]

    await login(client, "demo_user", demo_password)
    forbidden = await client.get("/api/system/config")
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == 40301
    assert (await client.get("/api/system/sandboxes")).status_code == 403


async def test_sandbox_admin_api(client: AsyncClient, monkeypatch) -> None:
    from app.services import sandbox_service

    await init_admin(client)
    await login(client, "admin", "Admin@12345")

    removed: list[str] = []

    async def fake_list(db):
        return {
            "containers": [
                {
                    "id": "abc123",
                    "name": "sec-eval-1-r1",
                    "status": "running",
                    "image": "sec-eval-sandbox:latest",
                    "project_id": 1,
                    "project_name": "demo",
                    "run_id": 1,
                    "created_at": "2026-10-22T00:00:00Z",
                }
            ],
            "volumes": [{"name": "sec-eval-src-1", "labels": {}}],
            "cleanup_pending_projects": [
                {
                    "id": 2,
                    "project_name": "broken",
                    "cleanup_error": "boom",
                    "updated_at": "2026-10-22T00:00:00Z",
                }
            ],
        }

    async def fake_remove(reference: str) -> None:
        removed.append(reference)

    monkeypatch.setattr(sandbox_service, "list_sandboxes", fake_list)
    monkeypatch.setattr(sandbox_service, "force_remove", fake_remove)

    listing = await client.get("/api/system/sandboxes")
    assert listing.status_code == 200
    data = listing.json()["data"]
    assert data["items"][0]["sandbox_id"] == "abc123"
    assert data["items"][0]["project_name"] == "demo"
    assert data["cleanup_pending"][0]["project_id"] == 2

    destroyed = await client.delete("/api/system/sandboxes/abc123")
    assert destroyed.status_code == 200
    assert destroyed.json()["data"] == {"cleaned": True}
    assert removed == ["abc123"]

    invalid = await client.delete(f"/api/system/sandboxes/{'x' * 129}")
    assert invalid.status_code == 400


async def test_disable_user_revokes_sessions(client: AsyncClient) -> None:
    await init_admin(client)
    await login(client, "admin", "Admin@12345")

    created = await client.post(
        "/api/system/users", json={"username": "worker", "password": "Worker@12345"}
    )
    assert created.status_code == 200, created.text
    user_id = created.json()["data"]["user_id"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as user_client:
        await login(user_client, "worker", "Worker@12345")
        before = await user_client.get("/api/system/users")
        assert before.status_code == 403

    # 同一依赖覆盖下，user_client 的 cookie 已失效；重新登录后禁用
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as user_client:
        await login(user_client, "worker", "Worker@12345")
        disabled = await client.patch(f"/api/system/users/{user_id}", json={"status": "disabled"})
        assert disabled.status_code == 200
        after = await user_client.get("/api/system/users")
        assert after.status_code == 401


async def test_cannot_disable_self(client: AsyncClient) -> None:
    await init_admin(client)
    await login(client, "admin", "Admin@12345")
    me = await client.get("/api/system/users")
    admin_id = me.json()["data"]["items"][0]["id"]
    response = await client.patch(f"/api/system/users/{admin_id}", json={"status": "disabled"})
    assert response.status_code == 400


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/api/system/health")
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["db"] == "ok"
    assert body["data"]["status"] in {"ok", "degraded"}


async def test_delete_user(client: AsyncClient) -> None:
    await init_admin(client)
    await login(client, "admin", "Admin@12345")

    created = await client.post(
        "/api/system/users", json={"username": "temporary", "password": "Temp@12345"}
    )
    assert created.status_code == 200
    user_id = created.json()["data"]["user_id"]

    deleted = await client.delete(f"/api/system/users/{user_id}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["data"] == {"user_id": user_id, "deleted": True}

    listing = await client.get("/api/system/users")
    assert all(item["username"] != "temporary" for item in listing.json()["data"]["items"])

    again = await client.delete(f"/api/system/users/{user_id}")
    assert again.status_code == 404

    me = await client.get("/api/system/users")
    admin_id = me.json()["data"]["items"][0]["id"]
    self_delete = await client.delete(f"/api/system/users/{admin_id}")
    assert self_delete.status_code == 400


async def test_delete_user_forbidden_for_non_admin(client: AsyncClient) -> None:
    response = await client.post(
        "/api/system/init",
        json={"username": "admin", "password": "Admin@12345", "create_demo_user": True},
    )
    demo_password = response.json()["data"]["demo_password"]
    await login(client, "demo_user", demo_password)

    listing = await client.get("/api/system/users")
    assert listing.status_code == 403
    attempt = await client.delete("/api/system/users/1")
    assert attempt.status_code == 403, attempt.text
