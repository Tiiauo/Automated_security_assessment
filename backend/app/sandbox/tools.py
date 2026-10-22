import asyncio
import json
import struct
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator

from app.sandbox.client import docker_http_url

_RUNNER = Path(__file__).with_name("tool_runner.py").read_text("utf-8")


def tool_definitions(command_limit: int) -> list[dict]:
    def tool(name, description, properties, required=()):
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": properties,
                    "required": list(required),
                },
            },
        }

    path = {"type": "string", "minLength": 1, "maxLength": 4096}
    return [
        tool(
            "list_dir",
            "列出 /src 内目录",
            {
                "path": path,
                "depth": {"type": "integer", "minimum": 1, "maximum": 20, "default": 1},
                "max_entries": {"type": "integer", "minimum": 1, "maximum": 500, "default": 500},
            },
            ("path",),
        ),
        tool(
            "read_file",
            "读取 /src 内文件字节片段",
            {
                "path": path,
                "offset": {"type": "integer", "minimum": 0, "maximum": 2**40, "default": 0},
                "limit_bytes": {"type": "integer", "minimum": 1, "maximum": 65536, "default": 65536},
            },
            ("path",),
        ),
        tool(
            "search_code",
            "在 /src 中按 ripgrep 正则搜索",
            {
                "pattern": {"type": "string", "minLength": 1, "maxLength": 4096},
                "path": path,
                "glob": {"type": "string", "maxLength": 500},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 200, "default": 200},
            },
            ("pattern",),
        ),
        tool(
            "run_command",
            "在隔离容器内执行命令，写入限定 /workspace",
            {
                "command": {"type": "string", "minLength": 1, "maxLength": 65536},
                "cwd": path,
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": command_limit},
            },
            ("command",),
        ),
    ]


def _demultiplex(raw: bytes) -> bytes:
    output = bytearray()
    while raw:
        if len(raw) < 8:
            raise ValueError("Docker exec 响应帧不完整")
        length = struct.unpack(">I", raw[4:8])[0]
        if len(raw) < length + 8:
            raise ValueError("Docker exec 响应帧不完整")
        if raw[0] == 1:
            output.extend(raw[8 : 8 + length])
        raw = raw[8 + length :]
    return bytes(output)


class SandboxTools:
    def __init__(self, sandbox_id: str, command_limit: int):
        self.sandbox_id = sandbox_id
        self.command_limit = command_limit
        self.definitions = tool_definitions(command_limit)

    async def execute(self, name: str, arguments: str) -> dict:
        try:
            definition = next((t["function"] for t in self.definitions if t["function"]["name"] == name), None)
            if definition is None:
                raise ValueError("未知工具")
            args = json.loads(arguments)
            Draft202012Validator(definition["parameters"]).validate(args)
            seconds = args.get("timeout_seconds", min(60, self.command_limit)) if name == "run_command" else 60
            async with asyncio.timeout(seconds + 2):
                async with httpx.AsyncClient(base_url=docker_http_url(), timeout=seconds + 2) as client:
                    # Docker SDK exec_run 的异步等价通道，可在停止时取消连接。
                    response = await client.post(
                        f"/containers/{self.sandbox_id}/exec",
                        json={
                            "AttachStdout": True,
                            "AttachStderr": True,
                            "Tty": False,
                            "User": "sandbox",
                            "WorkingDir": "/workspace",
                            "Cmd": [
                                "timeout",
                                "-k",
                                "5",
                                str(seconds + 1),
                                "python",
                                "-I",
                                "-c",
                                _RUNNER,
                                name,
                                json.dumps(args),
                                str(self.command_limit),
                            ],
                        },
                    )
                    response.raise_for_status()
                    exec_id = response.json()["Id"]
                    data = bytearray()
                    async with client.stream(
                        "POST", f"/exec/{exec_id}/start", json={"Detach": False, "Tty": False}
                    ) as stream:
                        stream.raise_for_status()
                        async for chunk in stream.aiter_bytes():
                            data.extend(chunk)
                            if len(data) > 7 * 1024 * 1024:
                                raise ValueError("工具输出超出传输上限")
                    return json.loads(_demultiplex(bytes(data)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return {"error": {"type": type(exc).__name__, "message": str(exc)[:1000]}}
