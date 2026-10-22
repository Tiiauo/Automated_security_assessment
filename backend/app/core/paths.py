from pathlib import Path

from app.core.config import BASE_DIR, get_settings


def data_root() -> Path:
    root = Path(get_settings().data_root)
    if not root.is_absolute():
        root = BASE_DIR / root
    return root.resolve()
