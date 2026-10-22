from typing import Literal

from pydantic import BaseModel, Field


class ProjectCreateRequest(BaseModel):
    project_name: str = Field(min_length=1, max_length=100)
    source_type: Literal["local_path", "git_repo"]
    source_path: str = Field(min_length=1, max_length=500)
    task_content: str = Field(min_length=1, max_length=5000)
    sandbox_type: Literal["docker"] = "docker"
