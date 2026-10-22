import json

from app.agents.contracts import ENV_CHECKS


def mock_output(stage: str, role: str, context: dict) -> str:
    """仅供自动化联调；固定数据明确标识为模拟，不表示发现了真实漏洞。"""
    if role == "orchestrator":
        return f"[LLM_MOCK] {stage} 任务协调完成。"
    if role == "env_inspector":
        result = {
            "language_stack": ["mock"],
            "summary": "[LLM_MOCK] 环境就绪",
            "checks": [{"name": name, "passed": True, "detail": "模拟检查"} for name in ENV_CHECKS],
            "limitations": [],
        }
    elif role == "ops_assistant":
        result = {
            "summary": "[LLM_MOCK] 运维完成",
            "actions": [
                {
                    "action": "archive" if stage == "done" else "workspace_check",
                    "status": "success",
                    "detail": "模拟操作",
                },
            ],
        }
    elif stage == "code_analysis":
        result = {
            "summary": "[LLM_MOCK] 两条候选用于测试落库",
            "candidates": [
                {
                    "title": f"[MOCK] 候选 {n}",
                    "vuln_type": "mock",
                    "risk_level": "info",
                    "file_path": f"/src/mock-{n}.py:1",
                    "condition_text": "仅用于编排测试",
                    "evidence_text": "模拟证据",
                }
                for n in (1, 2)
            ],
        }
    elif role == "vuln_verifier":
        result = {
            "summary": "[LLM_MOCK] 模拟验证结论",
            "verdicts": [
                {
                    "vuln_code": v["vuln_code"],
                    "verify_status": "unverified",
                    "risk_level": "info",
                    "impact_text": "模拟数据，不代表实际风险",
                    "condition_text": "模拟条件",
                    "evidence_text": "未执行真实验证",
                    "reproduce_steps_text": "无实际复现",
                    "verify_code_text": "",
                }
                for v in context.get("vulnerabilities", [])
            ],
        }
    elif role == "code_analyst":
        codes = [v["vuln_code"] for v in context.get("vulnerabilities", []) if v["verify_status"] != "false_positive"]
        result = {
            "summary": "[LLM_MOCK] 模拟路径",
            "paths": [
                {
                    "path_title": "[MOCK] 测试路径",
                    "path_summary": "仅验证编排落库",
                    "final_impact_text": "不代表真实攻击路径",
                    "steps": [{"vuln_code": c, "step_text": "模拟步骤"} for c in codes[:2]],
                },
            ]
            if len(codes) >= 2
            else [],
        }
    else:
        markdown = "# [LLM_MOCK] 编排测试报告\n\n" + "\n\n".join(
            f"## {n}. {title}\n\n模拟数据，不作为安全评估结论。"
            for n, title in enumerate(("项目概述", "执行过程", "漏洞汇总", "攻击路径", "风险结论", "修复建议"), 1)
        )
        result = {"markdown": markdown, "conclusion_rating": "info"}
    return json.dumps(result, ensure_ascii=False)
