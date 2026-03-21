from __future__ import annotations

from pathlib import Path
from typing import Optional

CURRENT_PROJECT_PATH_FILE = Path.home() / ".archmind_telegram_last_project"
_CURRENT_PROJECT: Optional[Path] = None


def _normalize_path(project_dir: Path) -> Path:
    return project_dir.expanduser().resolve()


def _is_existing_dir(project_dir: Path) -> bool:
    path = _normalize_path(project_dir)
    return path.exists() and path.is_dir()


def is_valid_archmind_project_dir(project_dir: Path) -> bool:
    path = _normalize_path(project_dir)
    if not _is_existing_dir(path):
        return False
    archmind_dir = path / ".archmind"
    return archmind_dir.exists() and archmind_dir.is_dir()


def set_current_project(project_dir: Path) -> None:
    global _CURRENT_PROJECT
    target = _normalize_path(project_dir)
    _CURRENT_PROJECT = target
    save_last_project_path(target)


def clear_current_project() -> None:
    global _CURRENT_PROJECT
    _CURRENT_PROJECT = None
    clear_last_project_path()


def get_current_project() -> Optional[Path]:
    global _CURRENT_PROJECT
    if _CURRENT_PROJECT is None:
        return None
    target = _normalize_path(_CURRENT_PROJECT)
    if _is_existing_dir(target):
        return target
    _CURRENT_PROJECT = None
    return None


def save_last_project_path(project_dir: Path, file_path: Path = CURRENT_PROJECT_PATH_FILE) -> None:
    target = _normalize_path(project_dir)
    file_path.expanduser().write_text(str(target), encoding="utf-8")


def clear_last_project_path(file_path: Path = CURRENT_PROJECT_PATH_FILE) -> None:
    target = file_path.expanduser()
    if not target.exists():
        return
    try:
        target.unlink()
    except Exception:
        return


def load_last_project_path(file_path: Path = CURRENT_PROJECT_PATH_FILE) -> Optional[Path]:
    target = file_path.expanduser()
    if not target.exists():
        return None
    value = target.read_text(encoding="utf-8", errors="replace").strip()
    if not value:
        return None
    return _normalize_path(Path(value))


def load_valid_last_project_path(file_path: Path = CURRENT_PROJECT_PATH_FILE) -> Optional[Path]:
    project_dir = load_last_project_path(file_path=file_path)
    if project_dir is None:
        return None
    if is_valid_archmind_project_dir(project_dir):
        return project_dir
    clear_last_project_path(file_path=file_path)
    return None


def get_validated_current_project(file_path: Path = CURRENT_PROJECT_PATH_FILE) -> Optional[Path]:
    current = get_current_project()
    if current is not None and is_valid_archmind_project_dir(current):
        return current
    if current is not None and not is_valid_archmind_project_dir(current):
        # keep persisted state in sync when in-memory selection turns invalid
        clear_current_project()
        return None
    persisted = load_valid_last_project_path(file_path=file_path)
    if persisted is None:
        return None
    global _CURRENT_PROJECT
    _CURRENT_PROJECT = persisted
    return persisted
