"""数据家的定位与读写。

数据家默认在 %APPDATA%\\PersonalHub，与代码目录彻底分离，
所以更新代码时数据文件连碰都不碰。用户搬过家则记在 %LOCALAPPDATA%\\PersonalHub\\location.json。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .version import APP_NAME

ENV_HOME = "PERSONALHUB_HOME"

DB_NAME = "data.db"
BACKUPS_DIRNAME = "backups"


def pointer_path() -> Path:
    """搬家记录所在的位置，必须落在数据家之外，否则就成了自我引用。"""
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".local"
    return root / APP_NAME / "location.json"


def default_data_home() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home()
    return root / APP_NAME


def data_home() -> Path:
    env = os.environ.get(ENV_HOME)
    if env:
        return Path(env).expanduser()

    pointer = pointer_path()
    if pointer.exists():
        try:
            data = json.loads(pointer.read_text(encoding="utf-8"))
            candidate = Path(data["data_home"]).expanduser()
            if candidate.parent.exists():
                return candidate
        except (OSError, ValueError, KeyError):
            pass
    return default_data_home()


def set_data_home(target: str | Path) -> Path:
    """记录用户指定的数据家。只写指针，搬文件由调用方负责。"""
    resolved = Path(target).expanduser()
    pointer = pointer_path()
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(
        json.dumps({"data_home": str(resolved)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return resolved


def clear_pointer() -> None:
    pointer = pointer_path()
    if pointer.exists():
        pointer.unlink()


def database_path() -> Path:
    return data_home() / DB_NAME


def backups_dir() -> Path:
    return data_home() / BACKUPS_DIRNAME


def logs_dir() -> Path:
    return data_home() / "logs"


def ensure_dirs() -> Path:
    home = data_home()
    (home / BACKUPS_DIRNAME).mkdir(parents=True, exist_ok=True)
    (home / "logs").mkdir(parents=True, exist_ok=True)
    return home


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
