from app.sandbox import containers


def _kwargs(**overrides):
    values = {
        "project_id": 7,
        "run_id": 2,
        "image": "sec-eval-sandbox:latest",
        "cpu_limit": 2.0,
        "memory_limit_mb": 2048,
        "network_enabled": False,
        "source_volume": "sec-eval-src-7",
        "workspace_volume": "sec-eval-ws-7-r2",
    }
    values.update(overrides)
    return containers.build_create_kwargs(**values)


def test_container_security_baseline() -> None:
    kwargs = _kwargs()
    assert kwargs["name"] == "sec-eval-7-r2"
    assert kwargs["user"] == "sandbox"
    assert kwargs["network_mode"] == "none"
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == ["no-new-privileges"]
    assert kwargs["pids_limit"] == 256
    assert kwargs["nano_cpus"] == 2_000_000_000
    assert kwargs["mem_limit"] == "2048m"
    assert kwargs["tmpfs"] == {"/tmp": "rw,size=256m"}
    assert kwargs["volumes"]["sec-eval-src-7"] == {"bind": "/src", "mode": "ro"}
    assert kwargs["volumes"]["sec-eval-ws-7-r2"] == {"bind": "/workspace", "mode": "rw"}
    assert kwargs["labels"]["sec-eval.project_id"] == "7"
    assert kwargs["labels"]["sec-eval.run_id"] == "2"


def test_network_toggle() -> None:
    assert _kwargs(network_enabled=True)["network_mode"] == "bridge"
