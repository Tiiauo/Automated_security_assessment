"""通过 python -I -c 在沙箱中执行；不导入用户源码，也不在后端宿主运行。"""

import json
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

OUTPUT_LIMIT = 1024 * 1024


def checked_path(value, roots):
    path = Path(value).resolve(strict=True)
    if not any(path == root or root in path.parents for root in map(Path, roots)):
        raise ValueError("路径越界或符号链接逃逸")
    return str(path)


def bounded_process(args, *, cwd=None, seconds=60, cap=OUTPUT_LIMIT):
    process = subprocess.Popen(
        args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    output = bytearray()
    truncated = False
    timed_out = False
    deadline = time.monotonic() + seconds
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                for key, _ in selector.select(timeout=min(0.1, max(0, deadline - time.monotonic()))):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    remaining = cap - len(output)
                    output.extend(chunk[:remaining])
                    truncated |= len(chunk) > remaining
            if not timed_out:
                try:
                    process.wait(timeout=max(0.001, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    timed_out = True
    finally:
        # 同时清除 shell 派生进程，避免后台命令跨工具调用残留。
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        process.stdout.close()
    result = {
        "output": output.decode("utf-8", errors="replace"),
        "exit_code": process.returncode,
        "truncated": truncated,
    }
    if timed_out:
        result["error"] = {"type": "command_timeout", "message": f"命令超过 {seconds} 秒"}
    elif process.returncode != 0 and not (args[0] == "rg" and process.returncode == 1):
        result["error"] = {"type": "command_failed", "message": f"命令退出码 {process.returncode}"}
    return result


def execute(name, args, command_limit):
    if name == "run_command":
        cwd = checked_path(args.get("cwd", "/workspace"), ["/src", "/workspace"])
        seconds = args.get("timeout_seconds", min(60, command_limit))
        return bounded_process(
            ["timeout", "-k", "5", str(seconds), "sh", "-lc", args["command"]],
            cwd=cwd,
            seconds=seconds,
        )
    path = checked_path(args.get("path", "/src"), ["/src"])
    if name == "read_file":
        if not Path(path).is_file():
            raise ValueError("只能读取常规文件")
        # cat 在容器内读取；不让完整文件先进入内存。
        process = subprocess.Popen(["cat", "--", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            remaining = args.get("offset", 0)
            while remaining:
                chunk = process.stdout.read(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)
            content = process.stdout.read(args.get("limit_bytes", 65536))
            if not content and process.wait(timeout=1) != 0:
                raise OSError(process.stderr.read(1000).decode("utf-8", errors="replace"))
        finally:
            process.kill()
            process.wait()
            process.stdout.close()
            process.stderr.close()
        return {"content": content.decode("utf-8", errors="replace"), "bytes_read": len(content)}
    if name == "list_dir":
        result = bounded_process(
            ["find", "-P", path, "-mindepth", "1", "-maxdepth", str(args.get("depth", 1)), "-print"],
            cap=65536,
        )
        entries = result.pop("output").splitlines()
        maximum = args.get("max_entries", 500)
        result["entries"] = entries[:maximum]
        result["truncated"] |= len(entries) > maximum
        return result
    if name == "search_code":
        maximum = args.get("max_results", 200)
        command = ["rg", "--no-follow", "--line-number", "--max-columns", "1000", "--max-count", str(maximum)]
        if args.get("glob"):
            command.extend(["--glob", args["glob"]])
        command.extend(["--", args["pattern"], path])
        result = bounded_process(command, cap=262144)
        matches = result.pop("output").splitlines()
        result["matches"] = matches[:maximum]
        result["truncated"] |= len(matches) > maximum
        return result
    raise ValueError("未知工具")


def _terminate(signum, frame):
    raise TimeoutError("工具执行超时")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _terminate)
    try:
        result = execute(sys.argv[1], json.loads(sys.argv[2]), int(sys.argv[3]))
    except Exception as exc:
        result = {"error": {"type": type(exc).__name__, "message": str(exc)[:1000]}}
    print(json.dumps(result, ensure_ascii=False))
