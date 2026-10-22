import asyncio
import json
import re

import httpx
import pytest

from app.agents.contracts import SCHEMAS, STAGES, InvalidOutput, validate_output
from app.agents.engine import CallFailed, ModelClient, RoleEngine, RoleFailed
from app.agents.mock import mock_output
from app.core.config import BASE_DIR
from app.sandbox.tools import SandboxTools
from app.services.config_service import SPECS


def config(**overrides):
    raw = {key: spec.default for key, spec in SPECS.items()}
    raw.update(overrides)
    return raw


class ScriptedModel:
    def __init__(self, values):
        self.values = iter(values)
        self.messages = []
        self.tools = []

    async def complete(self, messages, tools, **kwargs):
        self.messages.append(json.loads(json.dumps(messages)))
        self.tools.append(tools)
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, str):
            value = {"role": "assistant", "content": value}
        return {"message": value, "tokens": 7, "model": "scripted"}


class FakeTools:
    definitions = []

    def __init__(self):
        self.calls = []

    async def execute(self, name, arguments):
        self.calls.append((name, arguments))
        return {"content": "print('safe')"}


async def run_engine(model, *, stage="environment_scan", role="env_inspector", raw=None, context=None):
    events, tools = [], FakeTools()

    async def observe(event, **data):
        events.append((event, data))

    result = await RoleEngine(raw or config(), mock=True, model=model).execute(
        stage=stage,
        role=role,
        task="test",
        context=context or {},
        tools=tools,
        observe=observe,
        cancel=asyncio.Event(),
    )
    return result, events, tools


def test_schemas_match_frozen_prd():
    text = (BASE_DIR / "PRD.md").read_text("utf-8")
    for number, body in re.findall(r"### D([1-6]) .*?```json\n(.*?)\n```", text, re.S):
        assert SCHEMAS[int(number)] == json.loads(body)


def test_all_mock_roles_pass_schema():
    context = {
        "vulnerabilities": [
            {"vuln_code": "VULN-001", "verify_status": "unverified"},
            {"vuln_code": "VULN-002", "verify_status": "unverified"},
        ]
    }
    for stage, roles in STAGES.items():
        for role in roles:
            validate_output(stage, role, mock_output(stage, role, context), context)


@pytest.mark.parametrize("invalid", ["missing", "duplicate", "renamed", "no-limitations"])
def test_environment_contract_cannot_skip_base_checks(invalid):
    result = json.loads(mock_output("environment_scan", "env_inspector", {}))
    if invalid == "missing":
        result["checks"].pop()
    elif invalid == "duplicate":
        result["checks"][-1] = dict(result["checks"][0])
    elif invalid == "renamed":
        result["checks"][0]["name"] = "dependencies_installed"
    else:
        result.pop("limitations")
    with pytest.raises(InvalidOutput):
        validate_output("environment_scan", "env_inspector", json.dumps(result), {})


async def test_environment_probe_has_six_round_budget():
    call = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "probe",
                "type": "function",
                "function": {"name": "list_dir", "arguments": '{"path":"/src"}'},
            }
        ],
    }
    model = ScriptedModel([call] * 7)
    with pytest.raises(RoleFailed, match="角色轮次上限 6"):
        await run_engine(model, raw=config(**{"llm.max_turns": "30", "llm.max_retries": "0"}))
    assert len(model.messages) == 6
    assert model.tools[-1] == []


async def test_environment_final_turn_can_return_schema_output():
    call = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "probe",
                "type": "function",
                "function": {"name": "list_dir", "arguments": '{"path":"/src"}'},
            }
        ],
    }
    model = ScriptedModel([call] * 5 + [mock_output("environment_scan", "env_inspector", {})])
    result, _, _ = await run_engine(model, raw=config(**{"llm.max_turns": "6", "llm.max_retries": "0"}))
    assert result["checks"] and model.tools[-1] == []


async def test_analysis_keeps_configured_round_budget():
    call = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "read",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"/src/main.py"}'},
            }
        ],
    }
    model = ScriptedModel([call] * 7 + [mock_output("code_analysis", "code_analyst", {})])
    result, _, _ = await run_engine(
        model, stage="code_analysis", role="code_analyst", raw=config(**{"llm.max_turns": "8"})
    )
    assert result["candidates"] and len(model.messages) == 8


@pytest.mark.parametrize("text", ["```json\n{}\n```", "{}", "null", '{"summary":"ok","candidates":[],"extra":1}'])
def test_invalid_candidate_output(text):
    with pytest.raises(InvalidOutput):
        validate_output("code_analysis", "code_analyst", text, {})


async def test_schema_repair_preserves_raw_and_retry():
    final = mock_output("environment_scan", "env_inspector", {})
    model = ScriptedModel(["not-json", final])
    result, events, _ = await run_engine(model)
    assert result["checks"][0]["passed"]
    assert [data["retry_count"] for event, data in events if event == "retry"] == [1]
    assert events[0][1]["message"]["content"] == "not-json"
    assert "schema_invalid" in model.messages[1][-1]["content"]


@pytest.mark.parametrize("failures", [1, 2])
async def test_final_output_repair_keeps_evidence_without_repeating_invalid_output(monkeypatch, failures):
    monkeypatch.setattr(FakeTools, "definitions", SandboxTools("not-used", 60).definitions)
    call = {
        "role": "assistant",
        "tool_calls": [{
            "id": "read", "type": "function",
            "function": {"name": "read_file", "arguments": '{"path":"/src/main.py"}'},
        }],
    }
    invalid = '{"summary":"' + "x" * 23000
    final = mock_output("environment_scan", "env_inspector", {})
    model = ScriptedModel([call, *([invalid] * failures), final])
    result, events, tools = await run_engine(model)
    assert result == json.loads(final)
    assert model.tools[:2] == [FakeTools.definitions, FakeTools.definitions]
    assert model.tools[-1] == []
    assert all(item.get("content") != invalid for item in model.messages[-1])
    assert any(item.get("tool_call_id") == "read" for item in model.messages[-1])
    assert sum(data.get("message", {}).get("content") == invalid for _, data in events) == failures
    assert len(tools.calls) == 1
    assert [data["retry_count"] for event, data in events if event == "retry"] == list(range(1, failures + 1))
    assert all(len(messages) < 7 for messages in model.messages)


async def test_output_repair_cannot_execute_more_tools(monkeypatch):
    monkeypatch.setattr(FakeTools, "definitions", SandboxTools("not-used", 60).definitions)
    call = {
        "role": "assistant",
        "tool_calls": [{
            "id": "unexpected", "type": "function",
            "function": {"name": "read_file", "arguments": '{"path":"/src/main.py"}'},
        }],
    }
    final = mock_output("environment_scan", "env_inspector", {})
    model = ScriptedModel(["bad-json", call, final])
    result, events, tools = await run_engine(model)
    assert result == json.loads(final)
    assert not tools.calls
    assert model.tools[1:] == [[], []]
    assert [data["retry_count"] for event, data in events if event == "retry"] == [1, 2]
    assert all("tool_calls" not in item for item in model.messages[-1])


async def test_call_and_schema_failures_share_budget():
    model = ScriptedModel([CallFailed("network"), "bad-json", CallFailed("HTTP 500")])
    with pytest.raises(RoleFailed, match="call_failed.*HTTP 500"):
        await run_engine(model)
    assert len(model.messages) == 3


def test_truncated_json_reports_parse_location():
    with pytest.raises(InvalidOutput, match="JSON 解析失败（第 1 行，第 12 列）.*Unterminated string"):
        validate_output("code_analysis", "code_analyst", '{"summary":"unfinished', {})


@pytest.mark.parametrize("truncated", ["json", "complete-json", "tool-call"])
async def test_model_length_finish_retries_without_accepting_partial_output(monkeypatch, truncated):
    monkeypatch.setattr(FakeTools, "definitions", SandboxTools("not-used", 60).definitions)
    final = mock_output("environment_scan", "env_inspector", {})
    message = {"role": "assistant", "content": final if truncated == "complete-json" else final[:-20]}
    if truncated == "tool-call":
        message = {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "partial", "function": {"name": "read_file", "arguments": '{"path":'}}],
        }
    received = []

    def handler(request):
        received.append(json.loads(request.content))
        first = len(received) == 1
        return httpx.Response(200, json={
            "choices": [{
                "message": message if first else {"role": "assistant", "content": final},
                "finish_reason": "length" if first else "stop",
            }],
            "usage": {"total_tokens": 42},
        })

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    raw = config(**{"llm.base_url": "https://model.test/v1", "llm.model": "configured", "llm.api_key": "fake"})
    result, events, tools = await run_engine(ModelClient(raw, mock=False))
    assert result == json.loads(final)
    assert [data["finish_reason"] for event, data in events if event == "response"] == ["length", "stop"]
    assert [data["retry_count"] for event, data in events if event == "retry"] == [1]
    assert next(data for event, data in events if event == "response")["message"] == message
    assert "schema_invalid" in received[1]["messages"][-1]["content"]
    assert "finish_reason=length" in received[1]["messages"][-1]["content"]
    assert "全部输入候选编号" in received[1]["messages"][-1]["content"]
    assert all(payload["max_tokens"] == 32768 for payload in received)
    assert not tools.calls
    assert all("tool_calls" not in item for item in received[1]["messages"])
    assert ("tools" in received[1]) == (truncated == "tool-call")

    received.clear()
    with pytest.raises(RoleFailed, match="schema_invalid.*finish_reason=length"):
        await run_engine(ModelClient(raw, mock=False), raw=config(**{"llm.max_retries": "0"}))
    assert len(received) == 1


async def test_native_tools_loop_and_reasoning_roundtrip():
    call = {
        "role": "assistant",
        "content": None,
        "reasoning_content": "inspect source",
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"/src/main.py"}'},
            }
        ],
    }
    model = ScriptedModel([call, mock_output("environment_scan", "env_inspector", {})])
    _, events, tools = await run_engine(model)
    assert len(tools.calls) == 1
    assert model.messages[1][-2]["reasoning_content"] == "inspect source"
    assert model.messages[1][-1]["role"] == "tool"
    assert model.messages[1][-1]["tool_call_id"] == "call-1"
    assert [event for event, _ in events] == ["response", "tool", "tool_result", "response"]


async def test_turn_exhaustion_cannot_succeed():
    call = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "c", "type": "function", "function": {"name": "list_dir", "arguments": '{"path":"/src"}'}}
        ],
    }
    with pytest.raises(RoleFailed, match="max_turns"):
        await run_engine(ScriptedModel([call]), raw=config(**{"llm.max_turns": "1", "llm.max_retries": "0"}))


async def test_tool_errors_are_returned_not_raised():
    tools = SandboxTools("not-used", 60)
    for name, arguments in (
        ("unknown", "{}"),
        ("read_file", "not-json"),
        ("read_file", '{"path":"/src/a","limit_bytes":65537}'),
        ("run_command", '{"command":"true","timeout_seconds":61}'),
    ):
        assert "error" in await tools.execute(name, arguments)


async def test_cancel_interrupts_model_wait():
    entered = asyncio.Event()

    class WaitingModel:
        async def complete(self, *args, **kwargs):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(run_engine(WaitingModel()))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)


async def test_real_report_uses_model_without_mock():
    async def observe(*args, **kwargs):
        pass

    markdown = "\n\n".join(
        f"## {title}\n真实模型结果"
        for title in ("项目概述", "执行过程", "漏洞汇总", "攻击路径", "风险结论", "修复建议")
    )
    model = ScriptedModel([json.dumps({"markdown": markdown, "conclusion_rating": "info"})])
    result = await RoleEngine(config(), mock=False, model=model).execute(
        stage="report_generate",
        role="report_writer",
        task="x",
        context={},
        tools=FakeTools(),
        observe=observe,
        cancel=asyncio.Event(),
    )
    assert result["markdown"] == markdown and len(model.messages) == 1


async def test_probe_disables_thinking_and_has_tool_budget(monkeypatch):
    from app.services.llm_probe import probe_llm

    received = []

    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [{"id": "probe", "function": {"name": "__probe__", "arguments": "{}"}}],
                        }
                    }
                ]
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    result = await probe_llm(base_url="https://model.test/v1", model="configured", api_key="fake", timeout_seconds=10)
    assert result["tools_ok"]
    assert received[0]["thinking"] == {"type": "disabled"} and received[0]["max_tokens"] >= 128


async def test_model_adapter_uses_config_and_preserves_reasoning(monkeypatch):
    received = []

    def handler(request):
        received.append(request)
        return httpx.Response(
            200,
            json={
                "model": "actual-version",
                "usage": {"total_tokens": 42},
                "choices": [{"message": {"role": "assistant", "content": "ok", "reasoning_content": "reason"}}],
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    model = ModelClient(
        config(
            **{
                "llm.base_url": "https://model.test/v1",
                "llm.model": "configured",
                "llm.api_key": "fake",
                "llm.thinking_enabled": "true",
                "llm.max_tokens": "16384",
            }
        ),
        mock=False,
    )
    result = await model.complete([], [], stage="code_analysis", role="orchestrator", context={})
    assert result["model"] == "actual-version" and result["tokens"] == 42
    assert result["message"]["reasoning_content"] == "reason"
    payload = json.loads(received[0].content)
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["max_tokens"] == 16384
    assert "tools" not in payload
    assert received[0].headers["Authorization"] == "Bearer fake"
