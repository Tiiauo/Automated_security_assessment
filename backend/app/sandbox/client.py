import docker
from docker.errors import DockerException

from app.core.config import get_settings
from app.core.errors import SandboxError


def docker_http_url() -> str:
    host = (get_settings().docker_host or "").strip()
    if host.startswith("tcp://"):
        return "http://" + host[len("tcp://") :]
    if host.startswith(("http://", "https://")):
        return host
    raise SandboxError("DOCKER_HOST 必须为 tcp:// 或 http(s):// 地址（远程 Docker 模式）")


def get_client() -> docker.DockerClient:
    settings = get_settings()
    if not settings.docker_host:
        raise SandboxError("未配置 DOCKER_HOST，无法连接隔离环境")
    try:
        client = docker.DockerClient(base_url=settings.docker_host, timeout=30)
        client.ping()
        return client
    except DockerException as exc:
        raise SandboxError(f"Docker Engine 不可达：{exc.__class__.__name__}") from exc


def ping() -> bool:
    try:
        client = get_client()
    except SandboxError:
        return False
    client.close()
    return True
