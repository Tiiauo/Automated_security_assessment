from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 仓库根目录：backend/app/core/config.py -> parents[3]
BASE_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """运行环境配置，对应 PRD 附录 E。业务配置在 system_configs 中，不在此处。"""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://sec_eval:change_me@127.0.0.1:5432/sec_eval"
    jwt_secret: str = "change-me"
    data_encryption_key: str = ""
    data_root: str = "./data"
    cookie_secure: bool = True
    llm_mock: bool = False
    cors_allow_origins: str = ""
    docker_host: str | None = None
    log_level: str = "info"


@lru_cache
def get_settings() -> Settings:
    return Settings()
