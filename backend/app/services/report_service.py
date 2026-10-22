import html
import logging
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from markdown_it import MarkdownIt
from nh3 import clean
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.agents.contracts import REPORT_SECTIONS, report_sections
from app.core.errors import AppError, NotFound
from app.core.paths import data_root
from app.models.report import Report
from app.services.events import payload
from app.services.runtime_query import selected_run

logger = logging.getLogger(__name__)


def inline(value) -> str:
    text = str(value if value is not None else "—").replace("\n", " ").replace("\r", " ")
    return re.sub(r"([\\`*_{}\[\]()#+.!|<>~-])", r"\\\1", text)


def code_block(value) -> str:
    text = str(value or "未提供")
    fence = "`" * max(3, max((len(match) + 1 for match in re.findall(r"`+", text)), default=3))
    return f"{fence}\n{text}\n{fence}"


def compose(result: dict, context: dict, *, mock: bool) -> str:
    sections = report_sections(result["markdown"])
    project, source = context["project"], context["source"]
    overview = "\n".join(
        f"- **{label}**：{inline(value)}"
        for label, value in (
            ("项目名称", project["project_name"]),
            ("源码类型", project["source_type"]),
            ("源码来源", project["source_path"]),
            ("任务说明", project["task_content"]),
            ("执行轮次", context["run_id"]),
            ("Git commit", source.get("source_revision")),
            ("初始 SHA-256", source.get("source_fingerprint")),
            ("报告前复核 SHA-256", source.get("source_fingerprint_after")),
            ("启动时间", project.get("last_started_at")),
            ("报告生成时间", datetime.now(UTC).isoformat()),
        )
    )
    execution = [
        "阶段状态为报告生成时的快照；后续运维归档和容器销毁结果以运行记录为准。",
        "\n| 阶段 | 状态 | 开始 | 结束 | 错误 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for stage in context["stages"]:
        execution.append(
            "| "
            + " | ".join(
                inline(stage.get(key))
                for key in ("stage_name", "stage_status", "started_at", "finished_at", "error_message")
            )
            + " |"
        )
    execution.extend(["\n| 角色 | 状态 | 重试次数 | 开始 | 结束 |", "| --- | --- | --- | --- | --- |"])
    for worker in context["workers"]:
        execution.append(
            "| "
            + " | ".join(
                inline(worker.get(key))
                for key in ("worker_role", "task_status", "retry_count", "started_at", "finished_at")
            )
            + " |"
        )
    if limitations := context.get("environment_limitations"):
        execution.extend(
            [
                "\n### 动态验证限制",
                "本轮在以下限制下继续静态分析，不能视为完整动态测试；未验证结论仍须人工复核。",
                *[f"- {inline(item['name'])}：{inline(item['detail'])}" for item in limitations],
            ]
        )
    vulnerabilities = context["vulnerabilities"]
    findings = []
    if not any(row["verify_status"] == "verified" for row in vulnerabilities):
        findings.append("未发现可验证漏洞。扫描覆盖范围以本轮执行记录和实际工具调用为准。")
    if any(row["verify_status"] in {"pending", "unverified"} for row in vulnerabilities):
        findings.append("本轮含待人工复核项；未验证结论不代表已排除风险，也不应视为已证实漏洞。")
    for row in vulnerabilities:
        findings.append(f"### {row['vuln_code']} {inline(row['vuln_title'])}")
        findings.append(
            "\n".join(
                f"- {label}：{inline(row.get(key))}"
                for label, key in (
                    ("风险等级", "risk_level"),
                    ("CVSS", "cvss_score"),
                    ("验证状态", "verify_status"),
                    ("文件位置", "file_path"),
                    ("所属阶段", "stage_id"),
                )
            )
        )
        for label, key in (
            ("影响说明", "impact_text"),
            ("触发条件", "condition_text"),
            ("证据内容", "evidence_text"),
            ("复现步骤", "reproduce_steps_text"),
            ("验证代码", "verify_code_text"),
        ):
            findings.append(f"**{label}**\n\n{code_block(row.get(key))}")
    paths = []
    for path in context["paths"]:
        paths.append(f"### {path['path_code']} {inline(path['path_title'])}")
        paths.append(code_block(path.get("path_summary")))
        if any(step["vuln"]["verify_status"] == "unverified" for step in path["steps"]):
            paths.append("**含待人工复核节点。**")
        for step in path["steps"]:
            vuln = step["vuln"]
            paths.append(
                f"{step['step_order']}. {vuln['vuln_code']}（{inline(vuln['verify_status'])}）"
                f"：{inline(step['step_text'])}"
            )
        paths.append("**最终影响**\n\n" + code_block(path.get("final_impact_text")))
    bodies = (
        overview,
        "\n".join(execution),
        "\n\n".join(findings),
        "\n\n".join(paths) or "未发现可串联的多步攻击路径。",
        f"整体评级：{inline(result['conclusion_rating'])}\n\n" + sections["风险结论"],
        sections["修复建议"],
    )
    title = ("[LLM_MOCK] " if mock else "") + inline(project["project_name"]) + " 安全评估报告"
    return (
        f"# {title}\n\n"
        + "\n\n".join(
            f"## {number}. {heading}\n\n{body}"
            for number, (heading, body) in enumerate(zip(REPORT_SECTIONS, bodies, strict=True), 1)
        )
        + "\n"
    )


def render_html(markdown: str, project_name: str) -> str:
    rendered = MarkdownIt("commonmark", {"html": False}).enable("table").render(markdown)
    body = clean(
        rendered,
        tags={
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "p",
            "br",
            "hr",
            "strong",
            "em",
            "blockquote",
            "pre",
            "code",
            "ul",
            "ol",
            "li",
            "table",
            "thead",
            "tbody",
            "tr",
            "th",
            "td",
            "a",
            "s",
        },
        attributes={"a": {"href", "title"}},
        url_schemes={"http", "https", "mailto"},
    )
    return (
        '<!doctype html>\n<html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>{html.escape(project_name)} 安全评估报告</title>"
        "<style>body{max-width:1100px;margin:32px auto;padding:0 24px;font-family:sans-serif;line-height:1.65}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f5f5;padding:12px}"
        "table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:6px}</style>"
        f"</head><body>{body}</body></html>\n"
    )


def report_base(project_id: int, run_id: int) -> Path:
    base = data_root() / "reports" / str(project_id) / f"report-run-{run_id}"
    if any(path.resolve() != path for path in (base, base.with_suffix(".md"), base.with_suffix(".html"))):
        raise AppError("报告路径含符号链接，拒绝访问")
    return base


def write_files(base: Path, markdown: str, rendered: str) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    temporary = []
    try:
        for extension, content in ((".md", markdown), (".html", rendered)):
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=base.parent,
                prefix=".report-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                path = Path(stream.name)
                temporary.append((path, base.with_suffix(extension)))
                stream.write(content)
        for path, target in temporary:
            os.replace(path, target)
    finally:
        for path, _ in temporary:
            path.unlink(missing_ok=True)


async def save(db, project_id: int, run_id: int, result: dict, context: dict, *, mock: bool):
    markdown = compose(result, context, mock=mock)
    rendered = render_html(markdown, context["project"]["project_name"])
    base = report_base(project_id, run_id)
    row = Report(
        project_id=project_id, run_id=run_id, report_markdown=markdown, report_html=rendered, report_file_path=str(base)
    )
    db.add(row)
    await db.flush()  # Reject duplicate reports before touching an existing artifact.
    db.sync_session.info.setdefault("report_files", []).extend([base.with_suffix(".md"), base.with_suffix(".html")])
    write_files(base, markdown, rendered)


@event.listens_for(Session, "after_rollback")
def cleanup_uncommitted(session):
    for path in session.info.pop("report_files", []):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.exception("failed to remove uncommitted report %s", path)


@event.listens_for(Session, "after_commit")
def keep_committed(session):
    session.info.pop("report_files", None)


async def get_report(db, project, run_id):
    value = await selected_run(db, project, run_id)
    row = await db.scalar(select(Report).where(Report.project_id == project.id, Report.run_id == value))
    if row is None:
        raise NotFound("报告尚未生成")
    return row


def report_payload(row):
    return {**payload(row), "report_id": row.id}
