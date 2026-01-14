from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

NAME_ERROR_RE = re.compile(r"NameError: name '([^']+)' is not defined")
TRACE_FILE_RE = re.compile(r'File "([^"]+)", line (\d+)')
PYTEST_LOC_RE = re.compile(r"^(.+?\.py):(\d+):", re.MULTILINE)

KNOWN_IMPORTS = {
    "Path": "from pathlib import Path",
    "datetime": "from datetime import datetime",
    "Query": "from fastapi import Query",
    "Depends": "from fastapi import Depends",
    "Optional": "from typing import Optional",
    "List": "from typing import List",
    "Dict": "from typing import Dict",
    "Any": "from typing import Any",
}


@dataclass
class FixResult:
    diff: str
    reason: str


def _find_target_file(project_dir: Path, text: str) -> Optional[Path]:
    matches = TRACE_FILE_RE.findall(text)
    if not matches:
        matches = PYTEST_LOC_RE.findall(text)
    for raw_path, _ in reversed(matches):
        path = Path(raw_path)
        if not path.is_absolute():
            path = (project_dir / path).resolve()
        if _is_within_project(project_dir, path) and path.exists():
            return path
    return None


def _is_within_project(project_dir: Path, path: Path) -> bool:
    try:
        project_root = project_dir.resolve()
        return path.resolve() == project_root or project_root in path.resolve().parents
    except FileNotFoundError:
        return False


def _resolve_import_line(name: str) -> Optional[str]:
    if name in KNOWN_IMPORTS:
        return KNOWN_IMPORTS[name]
    if name.isidentifier() and name.islower():
        return f"import {name}"
    return None


def _find_insertion_index(lines: list[str]) -> int:
    idx = 0
    if lines and lines[0].startswith("#!"):
        idx = 1

    if idx < len(lines) and lines[idx].lstrip().startswith(('"""', "'''")):
        quote = lines[idx].lstrip()[:3]
        idx += 1
        while idx < len(lines):
            if quote in lines[idx]:
                idx += 1
                break
            idx += 1

    while idx < len(lines) and lines[idx].startswith("from __future__ import"):
        idx += 1

    while idx < len(lines) and (lines[idx].startswith("import ") or lines[idx].startswith("from ")):
        idx += 1

    return idx


def _build_import_patch(project_dir: Path, target: Path, import_line: str) -> str:
    original_text = target.read_text(encoding="utf-8")
    original_lines = original_text.splitlines(keepends=True)

    if import_line in original_text:
        return ""

    insert_at = _find_insertion_index(original_lines)
    new_lines = list(original_lines)
    if insert_at > 0 and not new_lines[insert_at - 1].endswith("\n"):
        new_lines[insert_at - 1] = new_lines[insert_at - 1] + "\n"
    new_lines.insert(insert_at, import_line + "\n")

    rel_path = target.resolve().relative_to(project_dir.resolve())
    diff = difflib.unified_diff(
        original_lines,
        new_lines,
        fromfile=f"a/{rel_path.as_posix()}",
        tofile=f"b/{rel_path.as_posix()}",
    )
    return "".join(diff)


def generate_patch(project_dir: Path, summary_text: str, log_text: str) -> FixResult:
    error_match = NAME_ERROR_RE.search(summary_text) or NAME_ERROR_RE.search(log_text)
    if not error_match:
        return FixResult(diff="", reason="No NameError found in logs.")

    name = error_match.group(1)
    import_line = _resolve_import_line(name)
    if not import_line:
        return FixResult(diff="", reason=f"No import rule for NameError: {name}")

    target = _find_target_file(project_dir, summary_text) or _find_target_file(project_dir, log_text)
    if not target:
        return FixResult(diff="", reason="Could not locate target file from traceback.")

    diff = _build_import_patch(project_dir, target, import_line)
    if not diff:
        return FixResult(diff="", reason="Import already present or diff empty.")

    return FixResult(diff=diff, reason=f"Added import for {name}.")
