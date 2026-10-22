import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import BASE_DIR, get_settings
from app.core.errors import BadRequest
from app.core.security import decrypt_secret, encrypt_secret, mask_secret
from app.models.config import SystemConfig
from app.services.audit import audit

_HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$")
_FORBIDDEN_PATHS = {
    "/",
    "/bin",
    "/boot",
    "/dev",
    "/etc",
    "/proc",
    "/root",
    "/sys",
    "/usr",
    "/var",
    "c:\\",
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
}


@dataclass(frozen=True)
class ConfigSpec:
    key: str
    default: str
    description: str
    kind: str = "str"
    is_secret: bool = False
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()


def _default_source_root() -> str:
    root = Path(get_settings().data_root)
    if not root.is_absolute():
        root = BASE_DIR / root
    return str((root / "allowed_sources").resolve())


def _specs() -> list[ConfigSpec]:
    return [
        ConfigSpec("sandbox.type", "docker", "隔离环境类型", "enum", choices=("docker",)),
        ConfigSpec("sandbox.source_mount_mode", "ro", "源码挂载模式", "enum", choices=("ro",)),
        ConfigSpec(
            "sandbox.allowed_source_root",
            _default_source_root(),
            "允许接入的本地源码根目录白名单（英文逗号分隔）",
            "path_list",
        ),
        ConfigSpec("git.allowed_hosts", "", "允许拉取源码的 Git 主机名白名单", "host_list"),
        ConfigSpec("sandbox.network_enabled", "false", "隔离容器是否允许访问外网", "bool"),
        ConfigSpec("sandbox.image", "sec-eval-sandbox:latest", "隔离环境基础镜像"),
        ConfigSpec("sandbox.cpu_limit", "2.0", "单容器 CPU 核数上限", "float", minimum=0.5, maximum=16),
        ConfigSpec(
            "sandbox.memory_limit_mb",
            "2048",
            "单容器内存上限（MB）",
            "int",
            minimum=512,
            maximum=32768,
        ),
        ConfigSpec("timeout.stage_seconds", "3600", "阶段默认超时（秒）", "int", minimum=60, maximum=86400),
        ConfigSpec("timeout.worker_seconds", "900", "角色任务默认超时（秒）", "int", minimum=30, maximum=7200),
        ConfigSpec("timeout.command_seconds", "60", "容器内单条命令超时（秒）", "int", minimum=5, maximum=600),
        ConfigSpec(
            "limit.max_concurrent_projects",
            "3",
            "最大并发运行项目数",
            "int",
            minimum=1,
            maximum=10,
        ),
        ConfigSpec("limit.max_source_size_gb", "2", "单项目源码体积上限（GB）", "int", minimum=1, maximum=50),
        ConfigSpec(
            "limit.max_source_files",
            "200000",
            "单项目源码文件数量上限",
            "int",
            minimum=1000,
            maximum=1000000,
        ),
        ConfigSpec("retention.log_days", "30", "日志保留天数", "int", minimum=1, maximum=365),
        ConfigSpec("retention.resource_days", "30", "资源记录保留天数", "int", minimum=1, maximum=365),
        ConfigSpec(
            "monitor.resource_interval_seconds",
            "5",
            "资源采样周期（秒）",
            "int",
            minimum=1,
            maximum=60,
        ),
        ConfigSpec("llm.base_url", "", "模型服务地址（OpenAI 兼容）", "url"),
        ConfigSpec("llm.model", "", "默认模型名称"),
        ConfigSpec("llm.api_key", "", "模型密钥", is_secret=True),
        ConfigSpec("llm.timeout_seconds", "120", "单次模型调用超时（秒）", "int", minimum=10, maximum=600),
        ConfigSpec("llm.max_tokens", "32768", "单次模型响应输出 token 上限", "int", minimum=128, maximum=131072),
        ConfigSpec("llm.max_retries", "2", "模型调用/解析失败最大重试次数", "int", minimum=0, maximum=5),
        ConfigSpec("llm.max_turns", "30", "单角色任务工具调用最大轮次", "int", minimum=1, maximum=100),
        ConfigSpec("llm.thinking_enabled", "false", "是否启用模型思考模式", "bool"),
        ConfigSpec("git.credential", "", "私有仓库只读凭据", is_secret=True),
    ]


SPECS: dict[str, ConfigSpec] = {spec.key: spec for spec in _specs()}


async def ensure_defaults(db: AsyncSession) -> None:
    existing = set((await db.scalars(select(SystemConfig.config_key))).all())
    added = False
    for spec in SPECS.values():
        if spec.key not in existing:
            db.add(
                SystemConfig(
                    config_key=spec.key,
                    config_value=spec.default,
                    is_secret=spec.is_secret,
                    description=spec.description,
                )
            )
            added = True
    if added:
        await db.commit()


async def get_config_raw(db: AsyncSession) -> dict[str, str]:
    await ensure_defaults(db)
    rows = (await db.scalars(select(SystemConfig))).all()
    result: dict[str, str] = {}
    for row in rows:
        result[row.config_key] = (
            decrypt_secret(row.config_value) if row.is_secret else row.config_value
        )
    for key, spec in SPECS.items():
        result.setdefault(key, spec.default)
    return result


async def get_config_masked(db: AsyncSession) -> dict[str, str]:
    raw = await get_config_raw(db)
    return {
        key: mask_secret(value) if SPECS[key].is_secret else value for key, value in raw.items()
    }


async def get_value(db: AsyncSession, key: str) -> str:
    raw = await get_config_raw(db)
    return raw[key]


def _canonical_path(key: str, value: str) -> str:
    text = value.strip()
    if not text:
        raise BadRequest(f"{key} 不能为空")
    path = Path(text)
    if not path.is_absolute():
        raise BadRequest(f"{key} 必须是绝对路径")
    resolved_path = path.resolve()
    if resolved_path.parent == resolved_path:
        raise BadRequest(f"{key} 不能指向文件系统根目录")
    resolved = os.path.normcase(str(resolved_path))
    if resolved.rstrip("\\/") in _FORBIDDEN_PATHS or any(
        resolved == forbidden or resolved.startswith(forbidden + os.sep)
        for forbidden in _FORBIDDEN_PATHS
    ):
        raise BadRequest(f"{key} 不能指向系统目录")
    return str(resolved_path)


def _canonical(spec: ConfigSpec, value: object) -> str:
    text = str(value).strip()

    if spec.kind == "bool":
        lowered = text.lower()
        if lowered in {"true", "1", "yes"}:
            return "true"
        if lowered in {"false", "0", "no"}:
            return "false"
        raise BadRequest(f"{spec.key} 必须为 true 或 false")

    if spec.kind in {"int", "float"}:
        try:
            number = float(text)
        except ValueError as exc:
            raise BadRequest(f"{spec.key} 必须为数字") from exc
        if spec.kind == "int" and not number.is_integer():
            raise BadRequest(f"{spec.key} 必须为整数")
        if spec.minimum is not None and number < spec.minimum:
            raise BadRequest(f"{spec.key} 取值范围为 {spec.minimum} ~ {spec.maximum}")
        if spec.maximum is not None and number > spec.maximum:
            raise BadRequest(f"{spec.key} 取值范围为 {spec.minimum} ~ {spec.maximum}")
        return str(int(number)) if spec.kind == "int" else str(number)

    if spec.kind == "enum":
        if text not in spec.choices:
            raise BadRequest(f"{spec.key} 只能取 {', '.join(spec.choices)}")
        return text

    if spec.kind == "url":
        if not text:
            return ""
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise BadRequest(f"{spec.key} 必须是合法的 http(s) URL")
        return text

    if spec.kind == "path":
        return _canonical_path(spec.key, text)

    if spec.kind == "path_list":
        parts = [
            part.strip()
            for part in text.replace("，", ",").split(",")
            if part.strip()
        ]
        if not parts:
            raise BadRequest(f"{spec.key} 至少需要一个根目录")
        values = [_canonical_path(spec.key, part) for part in parts]
        return ",".join(dict.fromkeys(values))

    if spec.kind == "host_list":
        if not text:
            return ""
        hosts = [host.strip().lower() for host in text.split(",") if host.strip()]
        for host in hosts:
            if not _HOST_RE.match(host):
                raise BadRequest(f"{spec.key} 包含非法主机名：{host}")
        return ",".join(hosts)

    if len(text) > 500:
        raise BadRequest(f"{spec.key} 长度不能超过 500")
    return text


async def update_config(
    db: AsyncSession, updates: dict[str, object], *, actor_id: int
) -> dict[str, str]:
    unknown = [key for key in updates if key not in SPECS]
    if unknown:
        raise BadRequest(f"未知配置项：{', '.join(sorted(unknown))}")

    current_raw = await get_config_raw(db)
    for key, value in updates.items():
        spec = SPECS[key]
        if spec.is_secret:
            text = "" if value is None else str(value).strip()
            if text == mask_secret(current_raw.get(key, "")):
                continue
            stored = encrypt_secret(text)
        else:
            stored = _canonical(spec, value)

        row = await db.get(SystemConfig, key)
        if row is None:
            db.add(
                SystemConfig(
                    config_key=key,
                    config_value=stored,
                    is_secret=spec.is_secret,
                    description=spec.description,
                )
            )
        else:
            row.config_value = stored
            row.is_secret = spec.is_secret
            row.description = spec.description

    await audit(db, "config_update", actor_id=actor_id, detail={"keys": sorted(updates)})
    await db.commit()
    return await get_config_masked(db)
