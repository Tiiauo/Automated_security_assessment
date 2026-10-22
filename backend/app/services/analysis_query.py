from sqlalchemy import select

from app.core.errors import NotFound
from app.models.analysis import AttackPath, AttackPathItem, Vulnerability
from app.services.events import payload
from app.services.monitoring import page_rows
from app.services.runtime_query import selected_run


async def vulnerabilities(db, project, run_id, risk_level, verify_status, keyword, page, page_size):
    value = await selected_run(db, project, run_id)
    conditions = [Vulnerability.project_id == project.id, Vulnerability.run_id == value]
    if risk_level:
        conditions.append(Vulnerability.risk_level == risk_level)
    if verify_status:
        conditions.append(Vulnerability.verify_status == verify_status)
    if keyword:
        conditions.append(
            Vulnerability.vuln_title.ilike(f"%{keyword}%")
            | Vulnerability.vuln_code.ilike(f"%{keyword}%")
            | Vulnerability.file_path.ilike(f"%{keyword}%")
        )
    return await page_rows(db, Vulnerability, conditions, page, page_size)


async def vulnerability(db, project, vuln_id):
    row = await db.get(Vulnerability, vuln_id)
    if row is None or row.project_id != project.id:
        raise NotFound("漏洞不存在")
    return payload(row)


async def paths(db, project, run_id, page, page_size):
    value = await selected_run(db, project, run_id)
    result = await page_rows(
        db, AttackPath, [AttackPath.project_id == project.id, AttackPath.run_id == value], page, page_size
    )
    steps = await path_steps(db, [row["id"] for row in result["items"]])
    for row in result["items"]:
        row["steps"] = steps.get(row["id"], [])
        row["step_count"] = len(row["steps"])
        row["vulns"] = [step["vuln"] for step in row["steps"]]
    return result


async def path_steps(db, ids):
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(AttackPathItem, Vulnerability)
            .join(Vulnerability, Vulnerability.id == AttackPathItem.vuln_id)
            .join(AttackPath, AttackPath.id == AttackPathItem.path_id)
            .where(
                AttackPathItem.path_id.in_(ids),
                Vulnerability.project_id == AttackPath.project_id,
                Vulnerability.run_id == AttackPath.run_id,
            )
            .order_by(AttackPathItem.path_id, AttackPathItem.step_order)
        )
    ).all()
    grouped = {}
    for item, vuln in rows:
        grouped.setdefault(item.path_id, []).append(
            {"step_order": item.step_order, "step_text": item.step_text, "vuln": payload(vuln)}
        )
    return grouped


async def path(db, project, path_id):
    row = await db.get(AttackPath, path_id)
    if row is None or row.project_id != project.id:
        raise NotFound("攻击路径不存在")
    steps = (await path_steps(db, [path_id])).get(path_id, [])
    return {**payload(row), "steps": steps, "step_count": len(steps), "vulns": [s["vuln"] for s in steps]}
