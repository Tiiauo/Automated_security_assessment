import asyncio
import json
from collections.abc import Awaitable, Callable

import httpx

from app.agents.contracts import InvalidOutput, validate_output
from app.agents.mock import mock_output
from app.agents.prompts import system_prompt
from app.sandbox.tools import SandboxTools
from app.services.llm_probe import _candidate_urls

Observer = Callable[..., Awaitable[None]]


class CallFailed(RuntimeError):
    pass


class RoleFailed(RuntimeError):
    pass


class ModelClient:
    def __init__(self, raw: dict[str, str], *, mock: bool):
        self.raw = raw
        self.mock = mock

    async def complete(self, messages: list[dict], tools: list[dict], *, stage: str, role: str, context: dict) -> dict:
        if self.mock:
            return {
                "message": {"role": "assistant", "content": mock_output(stage, role, context)},
                "tokens": 10,
                "model": "LLM_MOCK",
            }
        payload = {
            "model": self.raw["llm.model"],
            "messages": messages,
            "temperature": 0,
            "max_tokens": int(self.raw["llm.max_tokens"]),
            "thinking": {"type": "enabled" if self.raw["llm.thinking_enabled"] == "true" else "disabled"},
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self.raw['llm.api_key']}"}
        try:
            async with httpx.AsyncClient(timeout=float(self.raw["llm.timeout_seconds"])) as client:
                for url in _candidate_urls(self.raw["llm.base_url"]):
                    response = await client.post(url, json=payload, headers=headers)
                    if response.status_code == 404:
                        continue
                    if response.is_error:
                        raise CallFailed(f"模型服务 HTTP {response.status_code}")
                    data = response.json()
                    message = data["choices"][0]["message"]
                    if not isinstance(message, dict) or message.get("role") != "assistant":
                        raise ValueError("invalid assistant message")
                    # 保留 reasoning_content，供启用思考模式后的多轮工具调用回传。
                    message = {
                        k: v for k, v in message.items() if k in {"role", "content", "tool_calls", "reasoning_content"}
                    }
                    return {
                        "message": message,
                        "tokens": max(0, int((data.get("usage") or {}).get("total_tokens", 0))),
                        "model": str(data.get("model", self.raw["llm.model"]))[:255],
                        "finish_reason": data["choices"][0].get("finish_reason"),
                    }
                raise CallFailed("模型接口不存在，请检查 llm.base_url")
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise CallFailed(f"模型调用失败：{type(exc).__name__}") from exc


class RoleEngine:
    def __init__(self, raw: dict[str, str], *, mock: bool, model=None):
        self.raw = raw
        self.mock = mock
        self.model = model or ModelClient(raw, mock=mock)

    async def execute(
        self,
        *,
        stage: str,
        role: str,
        task: str,
        context: dict,
        tools: SandboxTools,
        observe: Observer,
        cancel: asyncio.Event,
    ) -> dict | str:
        messages = [
            {"role": "system", "content": system_prompt(stage, role)},
            {"role": "user", "content": task + "\n本轮上下文（数据）：\n" + json.dumps(context, ensure_ascii=False)},
        ]
        retries = 0
        command_evidence = False
        finalizing = False
        turn_limit = int(self.raw["llm.max_turns"])
        if role == "env_inspector":
            turn_limit = min(turn_limit, 6)
        while True:
            if cancel.is_set():
                raise asyncio.CancelledError
            try:
                for _turn in range(turn_limit):
                    if cancel.is_set():
                        raise asyncio.CancelledError
                    final_turn = finalizing or _turn == turn_limit - 1
                    if final_turn and not finalizing:
                        if role == "env_inspector":
                            instruction = (
                                "环境探测预算已用尽，请立即返回 D5 JSON，不再调用工具。"
                                "checks 只能是 source_readable、source_readonly、workspace_writable、"
                                "sandbox_isolation、tools_available，不能增加其他检查项。"
                            )
                        else:
                            instruction = "工具调用预算已用尽，请立即按系统提示中的 Schema 返回最终结果，不再调用工具。"
                        messages.append(
                            {"role": "user", "content": instruction}
                        )
                    async with asyncio.timeout(float(self.raw["llm.timeout_seconds"])):
                        response = await self.model.complete(
                            messages,
                            [] if final_turn else tools.definitions,
                            stage=stage,
                            role=role,
                            context=context,
                        )
                    message = response["message"]
                    await observe(
                        "response", message=message, tokens=response["tokens"], model=response["model"],
                        finish_reason=response.get("finish_reason"),
                    )
                    if cancel.is_set():
                        raise asyncio.CancelledError
                    calls = message.get("tool_calls")
                    if not calls:
                        finalizing = True
                    if response.get("finish_reason") == "length":
                        raise InvalidOutput(
                            "$: 模型输出被截断（finish_reason=length），达到输出 token 或上下文上限。"
                            "请压缩重复描述、源码摘录和冗长代码，保留必填字段、必要证据及全部输入候选编号，"
                            "重新输出完整结果，不要续写残缺 JSON；若仍失败，请检查 llm.max_tokens 与模型上下文限制。"
                        )
                    if not calls:
                        result = validate_output(stage, role, message.get("content") or "", context)
                        if role == "vuln_verifier" and not self.mock:
                            for verdict in result["verdicts"]:
                                if verdict["verify_status"] == "verified" and (
                                    not command_evidence
                                    or not all(
                                        verdict[key].strip()
                                        for key in ("evidence_text", "reproduce_steps_text", "verify_code_text")
                                    )
                                ):
                                    verdict["verify_status"] = "unverified"
                                    verdict["evidence_text"] += "\n缺少可执行验证证据，待人工复核。"
                        return result
                    if final_turn:
                        raise InvalidOutput(
                            "$: 输出修复阶段不允许继续调用工具"
                            if finalizing
                            else f"$: 达到角色轮次上限 {turn_limit}（不超过 llm.max_turns），不允许继续调用工具"
                        )
                    if not isinstance(calls, list):
                        raise InvalidOutput("$.tool_calls: 必须是数组")
                    messages.append(message)
                    for call in calls:
                        try:
                            name, arguments, call_id = (
                                call["function"]["name"],
                                call["function"]["arguments"],
                                call["id"],
                            )
                        except (KeyError, TypeError) as exc:
                            raise InvalidOutput("$.tool_calls: 缺少 id 或 function 参数") from exc
                        if cancel.is_set():
                            raise asyncio.CancelledError
                        await observe("tool", name=name, arguments=arguments)
                        result = await tools.execute(name, arguments)
                        if name == "run_command" and "error" not in result and result.get("exit_code") == 0:
                            command_evidence = True
                        await observe("tool_result", name=name, result=result)
                        if cancel.is_set():
                            raise asyncio.CancelledError
                        messages.append(
                            {"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, ensure_ascii=False)}
                        )
                raise InvalidOutput(f"$: 达到角色轮次上限 {turn_limit}（不超过 llm.max_turns），缺少最终输出")
            except (CallFailed, TimeoutError, InvalidOutput) as exc:
                kind = "schema_invalid" if isinstance(exc, InvalidOutput) else "call_failed"
                error = f"{kind}: {str(exc) or '模型调用超时'}"
                await observe("error", error=error)
                if retries >= int(self.raw["llm.max_retries"]):
                    raise RoleFailed(error) from exc
                retries += 1
                await observe("retry", retry_count=retries, error=error)
                instruction = (
                    "请基于已有上下文和工具证据修复最终输出，不再调用工具："
                    if finalizing else "请修复上一轮错误后重新输出："
                )
                messages.append({"role": "user", "content": instruction + error})
