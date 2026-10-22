from typing import Any


def ok(data: Any = None) -> dict:
    return {"code": 0, "message": "ok", "data": {} if data is None else data}
