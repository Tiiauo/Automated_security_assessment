import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator
from markdown_it import MarkdownIt

STAGES = {
    "environment_scan": ("env_inspector", "ops_assistant"),
    "code_analysis": ("orchestrator", "code_analyst"),
    "vulnerability_verify": ("vuln_verifier", "code_analyst"),
    "report_generate": ("report_writer", "orchestrator"),
    "done": ("ops_assistant", "orchestrator"),
}

_SCHEMA_IDS = {
    ("environment_scan", "env_inspector"): 5,
    ("environment_scan", "ops_assistant"): 6,
    ("code_analysis", "code_analyst"): 1,
    ("vulnerability_verify", "vuln_verifier"): 2,
    ("vulnerability_verify", "code_analyst"): 3,
    ("report_generate", "report_writer"): 4,
    ("done", "ops_assistant"): 6,
}
SCHEMAS = {
    number: json.loads((Path(__file__).parents[1] / "schemas" / "roles" / f"d{number}.json").read_text("utf-8"))
    for number in range(1, 7)
}
ENV_CHECKS = tuple(SCHEMAS[5]["properties"]["checks"]["items"]["properties"]["name"]["enum"])


def output_schema(stage: str, role: str) -> dict | None:
    number = _SCHEMA_IDS.get((stage, role))
    return SCHEMAS[number] if number else None


class InvalidOutput(ValueError):
    pass


REPORT_SECTIONS = ("项目概述", "执行过程", "漏洞汇总", "攻击路径", "风险结论", "修复建议")


def report_sections(markdown: str) -> dict[str, str]:
    tokens = MarkdownIt().parse(markdown)
    headings = []
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == "h2" and token.level == 0:
            text = "".join(
                child.content for child in tokens[index + 1].children or [] if child.type in {"text", "code_inline"}
            )
            title = re.sub(r"^\s*\d+[.、．]\s*", "", text).strip()
            headings.append((title, token.map))
    if [title for title, _ in headings] != list(REPORT_SECTIONS):
        raise InvalidOutput("$.markdown: 必须按顺序包含且仅包含六个二级标题：" + "、".join(REPORT_SECTIONS))
    lines = markdown.splitlines()
    sections = {
        title: "\n".join(
            lines[bounds[1] : headings[index + 1][1][0] if index + 1 < len(headings) else len(lines)]
        ).strip()
        for index, (title, bounds) in enumerate(headings)
    }
    if any(not body for body in sections.values()):
        raise InvalidOutput("$.markdown: 六个章节均须提供内容，不得只输出空标题")
    return sections


def validate_output(stage: str, role: str, text: str, context: dict) -> dict | str:
    schema = output_schema(stage, role)
    if schema is None:
        if not text.strip():
            raise InvalidOutput("$: 摘要不能为空")
        return text
    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidOutput(
            f"$: JSON 解析失败（第 {exc.lineno} 行，第 {exc.colno} 列）：{exc.msg}；"
            "必须返回完整 JSON 对象，不得包含 Markdown 围栏或解释文字；"
            "若输出过长，请压缩重复描述并保留必填字段、必要证据及全部输入编号后重新输出。"
        ) from exc
    except TypeError as exc:
        raise InvalidOutput("$: 必须返回完整 JSON 对象，不得包含 Markdown 围栏或解释文字") from exc
    errors = sorted(Draft202012Validator(schema).iter_errors(result), key=lambda e: str(list(e.path)))
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path)
        raise InvalidOutput(f"$.{path}: {error.message}"[:2000])
    if role == "env_inspector" and {check["name"] for check in result["checks"]} != set(ENV_CHECKS):
        raise InvalidOutput("$.checks: 五项基础检查必须全部提供且不得重复")
    if stage == "report_generate" and role == "report_writer":
        report_sections(result["markdown"])
        known = {v["vuln_code"] for v in context.get("vulnerabilities", [])}
        known.update(p["path_code"] for p in context.get("paths", []))
        referenced = set(re.findall(r"\b(?:VULN|PATH)-[0-9]{3,}\b", result["markdown"]))
        if referenced - known:
            raise InvalidOutput("$.markdown: 引用了不存在于本轮的漏洞或路径编号")
    if stage == "vulnerability_verify":
        vulnerabilities = {v["vuln_code"]: v for v in context.get("vulnerabilities", [])}
        if role == "vuln_verifier":
            codes = [v["vuln_code"] for v in result["verdicts"]]
            if len(codes) != len(set(codes)) or set(codes) != set(vulnerabilities):
                raise InvalidOutput("$.verdicts: 必须恰好覆盖本轮所有候选编号，不得重复或引用其他轮次")
        else:
            for path in result["paths"]:
                for step in path["steps"]:
                    vuln = vulnerabilities.get(step["vuln_code"])
                    if vuln is None or vuln["verify_status"] not in {"verified", "unverified"}:
                        raise InvalidOutput("$.paths.steps.vuln_code: 只能引用本轮已判定且非误报的漏洞")
    return result
