import os

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import decrypt_secret
from app.models.config import SystemConfig
from tests.conftest import init_admin, login


async def test_config_defaults_and_masking(
    client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await init_admin(client)
    await login(client, "admin", "Admin@12345")

    response = await client.get("/api/system/config")
    assert response.status_code == 200
    config = response.json()["data"]
    assert config["sandbox.type"] == "docker"
    assert config["llm.api_key"] == ""
    assert config["llm.max_tokens"] == "32768"

    update = await client.put(
        "/api/system/config",
        json={
            "llm.base_url": "https://api.deepseek.com",
            "llm.model": "deepseek-chat",
            "llm.api_key": "sk-test-1234567890",
            "llm.max_turns": 40,
            "llm.max_tokens": 16384,
            "timeout.stage_seconds": 120,
        },
    )
    assert update.status_code == 200, update.text
    updated = update.json()["data"]
    assert updated["llm.api_key"] == "sk-****7890"
    assert updated["llm.max_turns"] == "40"
    assert updated["llm.max_tokens"] == "16384"

    async with db_session_factory() as session:
        row = await session.get(SystemConfig, "llm.api_key")
        assert row is not None
        assert row.is_secret is True
        assert decrypt_secret(row.config_value) == "sk-test-1234567890"

    # 提交掩码值表示保持不变
    masked = updated["llm.api_key"]
    kept = await client.put("/api/system/config", json={"llm.api_key": masked})
    assert kept.status_code == 200
    async with db_session_factory() as session:
        row = await session.get(SystemConfig, "llm.api_key")
        assert decrypt_secret(row.config_value) == "sk-test-1234567890"


async def test_config_validation_errors(client: AsyncClient) -> None:
    await init_admin(client)
    await login(client, "admin", "Admin@12345")

    out_of_range = await client.put("/api/system/config", json={"timeout.stage_seconds": 10})
    assert out_of_range.status_code == 400
    assert out_of_range.json()["code"] == 40001

    for value in (127, 131073, 128.5):
        invalid_tokens = await client.put("/api/system/config", json={"llm.max_tokens": value})
        assert invalid_tokens.status_code == 400

    unknown = await client.put("/api/system/config", json={"foo.bar": "1"})
    assert unknown.status_code == 400

    relative = await client.put(
        "/api/system/config", json={"sandbox.allowed_source_root": "relative/path"}
    )
    assert relative.status_code == 400

    forbidden = "C:\\Windows" if os.name == "nt" else "/etc"
    system_dir = await client.put(
        "/api/system/config", json={"sandbox.allowed_source_root": forbidden}
    )
    assert system_dir.status_code == 400

    bad_bool = await client.put("/api/system/config", json={"sandbox.network_enabled": "maybe"})
    assert bad_bool.status_code == 400


async def test_host_list_normalized(client: AsyncClient) -> None:
    await init_admin(client)
    await login(client, "admin", "Admin@12345")

    response = await client.put(
        "/api/system/config",
        json={"git.allowed_hosts": " GitHub.com , gitlab.example.com "},
    )
    assert response.status_code == 200
    assert response.json()["data"]["git.allowed_hosts"] == "github.com,gitlab.example.com"


async def test_multi_root_whitelist_normalized(client: AsyncClient, tmp_path) -> None:
    await init_admin(client)
    await login(client, "admin", "Admin@12345")

    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    response = await client.put(
        "/api/system/config",
        json={"sandbox.allowed_source_root": f"{root_a}, {root_b}，{root_a}"},
    )
    assert response.status_code == 200, response.text
    expected = f"{root_a.resolve()},{root_b.resolve()}"
    assert response.json()["data"]["sandbox.allowed_source_root"] == expected

    invalid = await client.put(
        "/api/system/config",
        json={"sandbox.allowed_source_root": f"{root_a},relative/path"},
    )
    assert invalid.status_code == 400
