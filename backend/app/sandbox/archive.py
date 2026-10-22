import asyncio
import os
import tarfile
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from app.core.errors import SandboxError

_CHUNK_SIZE = 1024 * 1024


def create_source_tar(source_dir: Path) -> Path:
    """把源码目录打包成 tar（排除 .git），返回临时文件路径。"""
    handle, name = tempfile.mkstemp(prefix="sec-eval-src-", suffix=".tar")
    os.close(handle)
    target = Path(name)
    try:
        with tarfile.open(target, "w") as archive:
            for root, dirnames, filenames in os.walk(source_dir, followlinks=False):
                dirnames[:] = sorted(name for name in dirnames if name != ".git")
                root_path = Path(root)
                relative_root = root_path.relative_to(source_dir)
                if relative_root != Path("."):
                    archive.add(root_path, arcname=relative_root.as_posix(), recursive=False)
                for filename in sorted(filenames):
                    path = root_path / filename
                    arcname = (
                        filename
                        if relative_root == Path(".")
                        else (relative_root / filename).as_posix()
                    )
                    archive.add(path, arcname=arcname, recursive=False)
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise


def cleanup_tar(path: Path) -> None:
    path.unlink(missing_ok=True)


async def _file_chunks(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as file:
        while True:
            chunk = await asyncio.to_thread(file.read, _CHUNK_SIZE)
            if not chunk:
                break
            yield chunk


async def upload_tar(container_id: str, tar_path: Path, target_path: str, docker_url: str) -> None:
    """通过 Docker API 把 tar 流解压到容器的目标路径。"""
    timeout = httpx.Timeout(connect=10, read=None, write=None, pool=None)
    try:
        async with httpx.AsyncClient(base_url=docker_url, timeout=timeout) as client:
            response = await client.put(
                f"/containers/{container_id}/archive",
                params={"path": target_path},
                content=_file_chunks(tar_path),
                headers={"Content-Type": "application/x-tar"},
            )
    except httpx.HTTPError as exc:
        raise SandboxError(f"源码上传失败：{exc.__class__.__name__}") from exc

    if response.status_code not in {200, 201, 204}:
        raise SandboxError(f"源码上传失败（HTTP {response.status_code}）")
