from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _load_records(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _tokenize(text: str) -> set[str]:
    return {m.group(0).lower() for m in re.finditer(r"[a-zA-Z0-9_-]+", text or "") if len(m.group(0)) >= 3}


def _infer_domains(text: str) -> set[str]:
    value = (text or "").lower()
    domains: set[str] = set()
    rules = [
        ("tasks", ("task", "todo")),
        ("teams", ("team", "collaboration")),
        ("documents", ("document", "docs")),
        ("expenses", ("expense", "budget")),
    ]
    for domain, keys in rules:
        if any(k in value for k in keys):
            domains.add(domain)
    return domains


def append_failure_memory(
    memory_path: Path,
    *,
    idea: str,
    template: str,
    modules: list[str],
    error: str,
    hint: str,
) -> None:
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    records = _load_records(memory_path)
    records.append(
        {
            "idea": str(idea or ""),
            "template": str(template or ""),
            "modules": [str(m) for m in (modules or [])],
            "error": str(error or ""),
            "hint": str(hint or ""),
        }
    )
    memory_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def get_failure_hints(idea: str, memory_path: Path) -> list[str]:
    records = _load_records(memory_path)
    if not records:
        return []

    query_tokens = _tokenize(idea)
    query_domains = _infer_domains(idea)
    hints: list[str] = []
    for rec in records:
        past_idea = str(rec.get("idea") or "")
        overlap = query_tokens & _tokenize(past_idea)
        domain_overlap = query_domains & _infer_domains(past_idea)
        if not overlap and not domain_overlap:
            continue
        hint = str(rec.get("hint") or "").strip()
        if not hint:
            modules = [str(m) for m in (rec.get("modules") or []) if str(m).strip()]
            if modules:
                hint = f"previous similar case suggested module {modules[0]}"
        if hint and hint not in hints:
            hints.append(hint)
        if len(hints) >= 3:
            break
    return hints
