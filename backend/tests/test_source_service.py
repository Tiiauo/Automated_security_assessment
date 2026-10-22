import socket
import tarfile

import pytest

from app.core.errors import BadRequest
from app.sandbox import archive
from app.services import source_service


def test_fingerprint_stable_and_ignores_git(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.py").write_text("print(1)\n", encoding="utf-8")
    git = tmp_path / ".git"
    git.mkdir()
    (git / "config").write_text("secret", encoding="utf-8")

    first = source_service.compute_fingerprint(tmp_path)
    assert source_service.compute_fingerprint(tmp_path) == first

    (git / "config").write_text("changed", encoding="utf-8")
    assert source_service.compute_fingerprint(tmp_path) == first

    (tmp_path / "a.txt").write_text("changed", encoding="utf-8")
    assert source_service.compute_fingerprint(tmp_path) != first


def test_resolve_hosts_rejects_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host, port, type=None, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    monkeypatch.setattr(source_service.socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(BadRequest):
        source_service._resolve_hosts("example.com", 443)


def test_resolve_hosts_rejects_reserved(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host, port, type=None, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("240.0.0.1", port))]

    monkeypatch.setattr(source_service.socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(BadRequest):
        source_service._resolve_hosts("example.com", 443)


def test_resolve_hosts_allows_public(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host, port, type=None, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(source_service.socket, "getaddrinfo", fake_getaddrinfo)
    assert source_service._resolve_hosts("example.com", 443) == ["93.184.216.34"]


def test_resolve_hosts_allows_private(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host, port, type=None, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.10.22", port))]

    monkeypatch.setattr(source_service.socket, "getaddrinfo", fake_getaddrinfo)
    assert source_service._resolve_hosts("git.internal", 22) == ["192.168.10.22"]


def test_git_host_validation() -> None:
    assert source_service._git_host("https://github.com/acme/repo.git") == "github.com"
    assert source_service._git_host("git@github.com:acme/repo.git") == "github.com"
    assert source_service._git_host("ssh://git@gitlab.example.com/acme/repo.git") == "gitlab.example.com"

    with pytest.raises(BadRequest):
        source_service._git_host("file:///tmp/repo")
    with pytest.raises(BadRequest):
        source_service._git_host("https://user:pass@github.com/acme/repo.git")
    with pytest.raises(BadRequest):
        source_service._git_host("/local/path")


def test_local_path_multi_root(tmp_path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    source = root_b / "src"
    source.mkdir(parents=True)

    source_service._validate_local_path(
        str(source), f"{root_a},{root_b}", check_size=False, max_gb=1, max_files=10
    )
    with pytest.raises(BadRequest):
        source_service._validate_local_path(
            str(source), str(root_a), check_size=False, max_gb=1, max_files=10
        )


def test_source_tar_excludes_git(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref", encoding="utf-8")

    tar_path = archive.create_source_tar(tmp_path)
    try:
        with tarfile.open(tar_path) as tar:
            names = tar.getnames()
        assert "a.txt" in names
        assert all(".git" not in name for name in names)
    finally:
        archive.cleanup_tar(tar_path)
