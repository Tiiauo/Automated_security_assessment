import httpx

_PROBE_TOOL = {
    "type": "function",
    "function": {
        "name": "__probe__",
        "description": "连通性探测工具，调用后原样返回 ok",
        "parameters": {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        },
    },
}


def _candidate_urls(base_url: str) -> list[str]:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return [base]
    if base.endswith("/v1"):
        return [f"{base}/chat/completions"]
    return [f"{base}/chat/completions", f"{base}/v1/chat/completions"]


async def probe_llm(
    *, base_url: str, model: str, api_key: str, timeout_seconds: int
) -> dict:
    result = {
        "url_ok": False,
        "model_ok": False,
        "auth_ok": False,
        "tools_ok": False,
        "detail": "",
    }
    if not base_url:
        result["detail"] = "未配置 base_url"
        return result
    if not model:
        result["detail"] = "未配置 llm.model"
        return result

    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "请调用 __probe__ 工具，参数 ok=true，不要输出其他内容。"}
        ],
        "tools": [_PROBE_TOOL],
        "tool_choice": "auto",
        "max_tokens": 128,
        "temperature": 0,
        "thinking": {"type": "disabled"},
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    timeout = httpx.Timeout(min(max(timeout_seconds, 5), 15))
    async with httpx.AsyncClient(timeout=timeout) as client:
        for url in _candidate_urls(base_url):
            try:
                response = await client.post(url, json=payload, headers=headers)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                result["detail"] = f"无法连接模型服务：{exc.__class__.__name__}"
                return result
            except httpx.TimeoutException:
                result["detail"] = "模型服务响应超时"
                result["url_ok"] = True
                return result

            result["url_ok"] = True
            status = response.status_code

            if status == 404:
                result["detail"] = f"接口路径不存在：{url}"
                continue
            if status in {401, 403}:
                result["auth_ok"] = False
                result["detail"] = "鉴权失败，请检查 llm.api_key"
                return result
            if status == 429:
                result["auth_ok"] = True
                result["detail"] = "模型服务限流（429）"
                return result
            if status >= 500:
                result["auth_ok"] = True
                result["detail"] = f"模型服务返回 {status}"
                return result
            if status >= 400:
                result["auth_ok"] = True
                detail = response.text[:300]
                result["detail"] = f"请求被拒绝（{status}）：{detail}"
                return result

            result["auth_ok"] = True
            result["model_ok"] = True
            try:
                data = response.json()
                message = data["choices"][0]["message"]
            except (ValueError, KeyError, IndexError, TypeError):
                result["detail"] = "响应结构不是 OpenAI 兼容格式"
                return result

            if message.get("tool_calls"):
                result["tools_ok"] = True
                result["detail"] = "连接成功，支持工具调用"
            else:
                result["detail"] = "连接成功，但模型未返回工具调用（可能不支持 function calling）"
            return result

    result["detail"] = result["detail"] or "未找到可用的 /chat/completions 路径"
    return result
