MANAGED_LABEL = "sec-eval.managed"
KIND_LABEL = "sec-eval.kind"
PROJECT_LABEL = "sec-eval.project_id"
RUN_LABEL = "sec-eval.run_id"

SANDBOX_KIND = "sandbox"
HELPER_KIND = "helper"


def source_volume_name(project_id: int) -> str:
    return f"sec-eval-src-{project_id}"


def workspace_volume_name(project_id: int, run_id: int) -> str:
    return f"sec-eval-ws-{project_id}-r{run_id}"


def sandbox_container_name(project_id: int, run_id: int) -> str:
    return f"sec-eval-{project_id}-r{run_id}"
