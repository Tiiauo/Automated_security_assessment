import docker
from docker.errors import NotFound
from docker.models.containers import Container

from app.core.errors import SandboxError
from app.sandbox.names import (
    HELPER_KIND,
    KIND_LABEL,
    MANAGED_LABEL,
    PROJECT_LABEL,
    RUN_LABEL,
    SANDBOX_KIND,
    sandbox_container_name,
)


def build_create_kwargs(
    *,
    project_id: int,
    run_id: int,
    image: str,
    cpu_limit: float,
    memory_limit_mb: int,
    network_enabled: bool,
    source_volume: str,
    workspace_volume: str,
) -> dict:
    return {
        "image": image,
        "name": sandbox_container_name(project_id, run_id),
        "command": ["sleep", "infinity"],
        "detach": True,
        "user": "sandbox",
        "working_dir": "/workspace",
        "network_mode": "bridge" if network_enabled else "none",
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges"],
        "pids_limit": 256,
        "nano_cpus": int(float(cpu_limit) * 1_000_000_000),
        "mem_limit": f"{int(memory_limit_mb)}m",
        "tmpfs": {"/tmp": "rw,size=256m"},
        "volumes": {
            source_volume: {"bind": "/src", "mode": "ro"},
            workspace_volume: {"bind": "/workspace", "mode": "rw"},
        },
        "labels": {
            MANAGED_LABEL: "true",
            KIND_LABEL: SANDBOX_KIND,
            PROJECT_LABEL: str(project_id),
            RUN_LABEL: str(run_id),
        },
    }


def create_container(client: docker.DockerClient, kwargs: dict) -> Container:
    return client.containers.create(**kwargs)


def create_helper(
    client: docker.DockerClient, image: str, volumes: dict, command: list[str]
) -> Container:
    return client.containers.create(
        image=image,
        command=command,
        volumes=volumes,
        user="root",
        network_mode="none",
        labels={MANAGED_LABEL: "true", KIND_LABEL: HELPER_KIND},
        detach=True,
    )


def start_and_wait(container: Container, timeout: int = 300) -> None:
    container.start()
    result = container.wait(timeout=timeout)
    if int(result.get("StatusCode", 1)) != 0:
        logs = container.logs().decode("utf-8", errors="replace")[-800:]
        raise SandboxError(f"隔离环境准备失败：{logs}")


def get_container(client: docker.DockerClient, reference: str) -> Container:
    return client.containers.get(reference)


def stop_container(container: Container, timeout: int = 10) -> None:
    container.stop(timeout=timeout)


def remove_container(container: Container, force: bool = True) -> None:
    try:
        container.remove(force=force)
    except NotFound:
        pass


def list_sandbox_containers(client: docker.DockerClient) -> list[dict]:
    containers = client.containers.list(
        all=True, filters={"label": f"{MANAGED_LABEL}=true"}
    )
    result = []
    for container in containers:
        labels = container.labels or {}
        if labels.get(KIND_LABEL) != SANDBOX_KIND:
            continue
        image = ""
        if container.image and container.image.tags:
            image = container.image.tags[0]
        result.append(
            {
                "id": container.id,
                "short_id": container.short_id,
                "name": container.name,
                "status": container.status,
                "image": image,
                "project_id": int(labels[PROJECT_LABEL]) if labels.get(PROJECT_LABEL) else None,
                "run_id": int(labels[RUN_LABEL]) if labels.get(RUN_LABEL) else None,
                "created_at": container.attrs.get("Created"),
            }
        )
    return result


def container_stats(container: Container) -> dict:
    raw = container.stats(stream=False)
    memory = int(raw.get("memory_stats", {}).get("usage", 0) or 0)

    cpu_stats = raw.get("cpu_stats", {}) or {}
    pre_stats = raw.get("precpu_stats", {}) or {}
    cpu_total = int((cpu_stats.get("cpu_usage", {}) or {}).get("total_usage", 0) or 0)
    pre_total = int((pre_stats.get("cpu_usage", {}) or {}).get("total_usage", 0) or 0)
    system_total = int(cpu_stats.get("system_cpu_usage", 0) or 0)
    pre_system = int(pre_stats.get("system_cpu_usage", 0) or 0)
    per_cpu = (cpu_stats.get("cpu_usage", {}) or {}).get("percpu_usage") or []
    online_cpus = int(cpu_stats.get("online_cpus") or len(per_cpu) or 1)

    cpu_delta = cpu_total - pre_total
    system_delta = system_total - pre_system
    cpu_usage = (cpu_delta / system_delta) * online_cpus * 100 if system_delta > 0 else 0.0

    return {
        "cpu_usage": round(max(cpu_usage, 0.0), 2),
        "memory_usage": memory // (1024 * 1024),
    }
