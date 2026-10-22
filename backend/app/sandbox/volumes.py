import docker
from docker.errors import APIError, NotFound

from app.sandbox.names import MANAGED_LABEL, PROJECT_LABEL, RUN_LABEL


def ensure_volume(
    client: docker.DockerClient, name: str, *, project_id: int, run_id: int | None = None
) -> None:
    labels = {MANAGED_LABEL: "true", PROJECT_LABEL: str(project_id)}
    if run_id is not None:
        labels[RUN_LABEL] = str(run_id)
    try:
        client.volumes.create(name=name, labels=labels)
    except APIError as exc:
        if getattr(exc, "status_code", None) != 409:
            raise


def remove_volume(client: docker.DockerClient, name: str) -> None:
    try:
        client.volumes.get(name).remove(force=True)
    except NotFound:
        pass


def list_volumes(client: docker.DockerClient, prefix: str) -> list[dict]:
    volumes = client.volumes.list(filters={"name": prefix})
    return [
        {"name": volume.name, "labels": volume.attrs.get("Labels") or {}}
        for volume in volumes
        if volume.name.startswith(prefix)
    ]
