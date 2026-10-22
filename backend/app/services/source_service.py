import asyncio
import base64
import hashlib
import ipaddress
import os
import re
import shutil
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from app.core.errors import BadRequest, SandboxError
from app.core.paths import data_root
from app.services import config_service

_SCP_LIKE = re.compile(r"^(?P<user>[A-Za-z0-9_.-]+)@(?P<host>[A-Za-z0-9.-]+):(?P<path>.+)$")
_HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$")
_GIT_TIMEOUT = 600


@dataclass
class PreparedSource:
    directory: Path
    revision: str | None
    fingerprint: str


def _within(root: Path, target: Path) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(str(root)), os.path.normcase(str(target))]) == os.path.normcase(
            str(root)
        )
    except ValueError:
        return False


def _check_source_size(target: Path, max_gb: float, max_files: int) -> None:
    max_bytes = int(max_gb * 1024 * 1024 * 1024)
    total = 0
    files = 0
    for dirpath, dirnames, filenames in os.walk(target, followlinks=False):
        dirnames[:] = [name for name in dirnames if name != ".git"]
        for filename in filenames:
            path = os.path.join(dirpath, filename)
            try:
                total += os.path.getsize(path)
            except OSError:
                continue
            files += 1
            if total > max_bytes:
                raise BadRequest(f"源码体积超过上限 {max_gb:g} GB")
            if files > max_files:
                raise BadRequest(f"源码文件数超过上限 {max_files}")


def _git_host(url: str) -> str:
    if "://" in url:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https", "ssh"}:
            raise BadRequest("仅支持 http(s) 或 SSH 仓库地址")
        if parsed.scheme in {"http", "https"} and (parsed.username or parsed.password):
            raise BadRequest("仓库地址不能包含内嵌凭据")
        if parsed.scheme == "ssh" and parsed.password:
            raise BadRequest("仓库地址不能包含内嵌凭据")
        if not parsed.hostname:
            raise BadRequest("仓库地址缺少主机名")
        return parsed.hostname.lower()

    match = _SCP_LIKE.match(url)
    if match:
        return match.group("host").lower()

    raise BadRequest("仓库地址格式不合法")


def _git_scheme(url: str) -> str:
    return urlparse(url).scheme if "://" in url else "ssh"


def _git_port(url: str) -> int:
    parsed = urlparse(url) if "://" in url else None
    if parsed is not None and parsed.port:
        return parsed.port
    scheme = _git_scheme(url)
    return {"https": 443, "http": 80, "ssh": 22}.get(scheme, 22)


def _validate_local_path(
    source_path: str, roots_value: str, *, check_size: bool, max_gb: float, max_files: int
) -> None:
    target = Path(source_path).resolve()
    roots = [Path(part.strip()).resolve() for part in roots_value.replace("，", ",").split(",") if part.strip()]
    if not target.exists() or not target.is_dir():
        raise BadRequest("源码路径不存在或不是目录")
    if not roots or not any(_within(root, target) for root in roots):
        raise BadRequest("源码路径不在允许的白名单根目录内")
    if not os.access(target, os.R_OK):
        raise BadRequest("源码路径不可读")
    if check_size:
        _check_source_size(target, max_gb, max_files)


async def validate_source(
    db, source_type: str, source_path: str, *, check_size: bool = True, raw: dict[str, str] | None = None
) -> None:
    raw = raw if raw is not None else await config_service.get_config_raw(db)

    if source_type == "local_path":
        await asyncio.to_thread(
            _validate_local_path,
            source_path,
            raw["sandbox.allowed_source_root"],
            check_size=check_size,
            max_gb=float(raw["limit.max_source_size_gb"]),
            max_files=int(raw["limit.max_source_files"]),
        )
        return

    if source_type == "git_repo":
        host = _git_host(source_path)
        allowed = [item for item in raw["git.allowed_hosts"].split(",") if item]
        if not allowed:
            raise BadRequest("管理员尚未配置 git.allowed_hosts，无法接入 Git 仓库")
        if host not in allowed:
            raise BadRequest(f"Git 主机 {host} 不在白名单内")
        return

    raise BadRequest("不支持的源码类型")


def _resolve_hosts(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise BadRequest(f"Git 主机解析失败：{host}") from exc

    addresses: list[str] = []
    for info in infos:
        raw_ip = str(info[4][0]).split("%", 1)[0]
        try:
            address = ipaddress.ip_address(raw_ip)
        except ValueError as exc:
            raise BadRequest(f"Git 主机解析到非法地址：{raw_ip}") from exc
        if (
            address.is_loopback
            or address.is_link_local
            or address.is_unspecified
            or address.is_multicast
            or address.is_reserved
        ):
            raise BadRequest(f"Git 主机解析到不允许的地址：{raw_ip}")
        addresses.append(str(address))

    if not addresses:
        raise BadRequest(f"Git 主机无法解析：{host}")
    addresses = sorted(set(addresses), key=lambda value: (":" in value, value))
    return addresses


def _curl_address(ip: str) -> str:
    return f"[{ip}]" if ":" in ip else ip


def _sanitize(message: str, secret: str) -> str:
    if secret:
        message = message.replace(secret, "***")
    return message.strip()[-800:]


async def _run_git(args: list[str], *, seconds: int) -> tuple[int, bytes, bytes]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=seconds)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise SandboxError("Git 操作超时") from None
    return process.returncode or 0, stdout, stderr


async def _clone_repo(url: str, destination: Path, raw: dict[str, str]) -> str:
    allowed = [item for item in raw["git.allowed_hosts"].split(",") if item]
    host = _git_host(url)
    if host not in allowed:
        raise BadRequest(f"Git 主机 {host} 不在白名单内")

    addresses = await asyncio.to_thread(_resolve_hosts, host, _git_port(url))
    scheme = _git_scheme(url)

    base = [
        "git",
        "clone",
        "--depth",
        "1",
        "--no-tags",
        "--single-branch",
        "-c",
        "http.followRedirects=false",
        "-c",
        "http.sslVerify=true",
    ]
    if os.name == "nt":
        # Git for Windows 默认使用 schannel；配合 http.curloptResolve 时必须显式指定
        base.extend(["-c", "http.sslBackend=schannel"])

    if scheme in {"http", "https"}:
        credential = raw["git.credential"]
        if credential:
            if ":" in credential:
                token = base64.b64encode(credential.encode("utf-8")).decode("ascii")
                auth = f"Basic {token}"
            else:
                auth = f"Bearer {credential}"
            base.extend(["-c", f"http.extraHeader=Authorization: {auth}"])
        attempts: list[str | None] = list(addresses)
    else:
        base.extend(["-c", "core.sshCommand=ssh -o BatchMode=yes -o StrictHostKeyChecking=yes"])
        attempts = [None]

    last_error = b""
    for address in attempts:
        await asyncio.to_thread(_reset_dir, destination)
        command = list(base)
        if address is not None:
            command.extend(
                [
                    "-c",
                    f"http.curloptResolve={host}:{_git_port(url)}:{_curl_address(address)}",
                ]
            )
        command.extend([url, str(destination)])
        code, _, stderr = await _run_git(command, seconds=_GIT_TIMEOUT)
        if code == 0:
            break
        last_error = stderr
    else:
        raise SandboxError(
            f"仓库拉取失败：{_sanitize(last_error.decode('utf-8', errors='replace'), raw['git.credential'])}"
        )

    code, stdout, stderr = await _run_git(["git", "-C", str(destination), "rev-parse", "HEAD"], seconds=60)
    if code != 0:
        raise SandboxError(f"读取 Git commit 失败：{_sanitize(stderr.decode('utf-8', errors='replace'), '')}")
    return stdout.decode("ascii", errors="ignore").strip()


def compute_fingerprint(directory: Path) -> str:
    digest = hashlib.sha256()
    entries: list[tuple[str, Path]] = []
    for root, dirnames, filenames in os.walk(directory, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name != ".git")
        root_path = Path(root)
        for filename in sorted(filenames):
            path = root_path / filename
            entries.append((path.relative_to(directory).as_posix(), path))

    for relative, path in sorted(entries):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"link:")
            digest.update(os.readlink(path).encode("utf-8"))
        else:
            try:
                with path.open("rb") as file:
                    while chunk := file.read(1024 * 1024):
                        digest.update(chunk)
            except OSError as exc:
                raise BadRequest(f"源码文件不可读：{relative}") from exc
        digest.update(b"\0")

    return digest.hexdigest()


def _reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _remove_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _resolve_path(source_path: str) -> Path:
    return Path(source_path).resolve()


async def prepare_source(
    db, *, project_id: int, source_type: str, source_path: str, raw: dict[str, str] | None = None
) -> PreparedSource:
    raw = raw if raw is not None else await config_service.get_config_raw(db)
    await validate_source(db, source_type, source_path, raw=raw)

    if source_type == "local_path":
        directory = await asyncio.to_thread(_resolve_path, source_path)
        revision = None
    else:
        directory = data_root() / "sources" / str(project_id)
        await asyncio.to_thread(_reset_dir, directory)
        try:
            revision = await _clone_repo(source_path, directory, raw)
        except Exception:
            await asyncio.to_thread(_remove_tree, directory)
            raise
        await asyncio.to_thread(
            _check_source_size,
            directory,
            float(raw["limit.max_source_size_gb"]),
            int(raw["limit.max_source_files"]),
        )

    fingerprint = await asyncio.to_thread(compute_fingerprint, directory)
    return PreparedSource(directory=directory, revision=revision, fingerprint=fingerprint)
