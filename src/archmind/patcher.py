from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


HUNK_HEADER_RE = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str]


@dataclass
class FilePatch:
    path: Path
    hunks: list[Hunk]


def _normalize_diff_path(raw: str) -> Optional[Path]:
    if raw == "/dev/null":
        return None
    path = raw.strip()
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return Path(path)


def _ensure_safe_path(project_dir: Path, rel_path: Path) -> Path:
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise ValueError(f"Unsafe patch path: {rel_path}")
    resolved = (project_dir / rel_path).resolve()
    project_root = project_dir.resolve()
    if resolved != project_root and project_root not in resolved.parents:
        raise ValueError(f"Patch path escapes project: {rel_path}")
    return resolved


def _parse_hunk_header(line: str) -> Hunk:
    match = HUNK_HEADER_RE.match(line)
    if not match:
        raise ValueError(f"Invalid hunk header: {line.strip()}")
    old_start = int(match.group(1))
    old_count = int(match.group(2) or "1")
    new_start = int(match.group(3))
    new_count = int(match.group(4) or "1")
    return Hunk(old_start=old_start, old_count=old_count, new_start=new_start, new_count=new_count, lines=[])


def _apply_hunks(original_lines: list[str], hunks: list[Hunk]) -> list[str]:
    output: list[str] = []
    idx = 1
    for hunk in hunks:
        while idx < hunk.old_start:
            output.append(original_lines[idx - 1])
            idx += 1
        for line in hunk.lines:
            if not line:
                continue
            marker = line[0]
            content = line[1:]
            if marker == " ":
                if idx > len(original_lines) or original_lines[idx - 1] != content:
                    raise ValueError("Patch context mismatch.")
                output.append(content)
                idx += 1
            elif marker == "-":
                if idx > len(original_lines) or original_lines[idx - 1] != content:
                    raise ValueError("Patch deletion mismatch.")
                idx += 1
            elif marker == "+":
                output.append(content)
            else:
                raise ValueError(f"Unknown patch marker: {marker}")

    output.extend(original_lines[idx - 1 :])
    return output


def apply_unified_diff(project_dir: Path, diff_text: str) -> list[Path]:
    if not diff_text.strip():
        raise ValueError("Empty diff.")

    lines = diff_text.splitlines(keepends=True)
    i = 0
    patches: list[FilePatch] = []

    while i < len(lines):
        line = lines[i]
        if not line.startswith("--- "):
            i += 1
            continue
        old_path_raw = line[4:].strip()
        i += 1
        if i >= len(lines) or not lines[i].startswith("+++ "):
            raise ValueError("Missing new file header in diff.")
        new_path_raw = lines[i][4:].strip()
        i += 1

        rel_path = _normalize_diff_path(new_path_raw) or _normalize_diff_path(old_path_raw)
        if rel_path is None:
            raise ValueError("Deletion patches are not supported.")
        target_path = _ensure_safe_path(project_dir, rel_path)

        hunks: list[Hunk] = []
        while i < len(lines) and lines[i].startswith("@@ "):
            hunk = _parse_hunk_header(lines[i].rstrip("\n"))
            i += 1
            while i < len(lines) and not lines[i].startswith("@@ ") and not lines[i].startswith("--- "):
                if lines[i].startswith("\\ No newline at end of file"):
                    i += 1
                    continue
                hunk.lines.append(lines[i])
                i += 1
            hunks.append(hunk)
        patches.append(FilePatch(path=target_path, hunks=hunks))

    backup_root = project_dir / ".archmind" / "patch_backups" / datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root.mkdir(parents=True, exist_ok=True)
    changed: list[Path] = []

    for patch in patches:
        if patch.path.exists():
            rel = patch.path.resolve().relative_to(project_dir.resolve())
            backup_path = backup_root / rel
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(patch.path, backup_path)
            original_lines = patch.path.read_text(encoding="utf-8").splitlines(keepends=True)
        else:
            original_lines = []

        new_lines = _apply_hunks(original_lines, patch.hunks)
        patch.path.parent.mkdir(parents=True, exist_ok=True)
        patch.path.write_text("".join(new_lines), encoding="utf-8")
        changed.append(patch.path)

    return changed
