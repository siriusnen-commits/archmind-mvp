# src/archmind/generator.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from .templates.fastapi import enforce_fastapi_runtime
from .templates.fastapi_ddd import enforce_fastapi_ddd

import shutil

import requests

from .templates.fastapi import enforce_fastapi_runtime


DEBUG_RAW_OUTPUT = Path("examples/last_raw_output.txt")
DEBUG_REPAIRED_OUTPUT = Path("examples/last_repaired_output.txt")


@dataclass
class GenerateOptions:
    out: Path
    force: bool = False
    name: Optional[str] = None
    template: str = "fastapi"
    model: str = "llama3:latest"
    ollama_base_url: str = "http://localhost:11434"
    max_retries: int = 2
    timeout_s: int = 240


def try_close_braces(s: str) -> str:
    open_cnt = s.count("{")
    close_cnt = s.count("}")
    if close_cnt < open_cnt:
        s = s + ("\n" + ("}" * (open_cnt - close_cnt)))
    return s


def fallback_spec(project_name: str) -> Dict[str, Any]:
    return {
        "project_name": project_name,
        "summary": "Fallback spec used because model output was invalid JSON.",
        "stack": {"language": "python", "framework": "fastapi", "server": "uvicorn"},
        "directories": [],
        "files": {},
    }


def call_ollama_chat(req: str, *, model: str, base_url: str, timeout_s: int) -> str:
    url = f"{base_url.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "format": "json",
        "messages": [
            {"role": "system", "content": "Return ONLY valid JSON. No markdown. No commentary."},
            {"role": "user", "content": req},
        ],
        "stream": False,
        "options": {"temperature": 0.2},
    }
    r = requests.post(url, json=payload, timeout=timeout_s)
    r.raise_for_status()
    data = r.json()
    msg = data.get("message") or {}
    return (msg.get("content") or "").strip()


def repair_json_with_model(raw: str, *, model: str, base_url: str, timeout_s: int) -> str:
    url = f"{base_url.rstrip('/')}/api/chat"
    repair_prompt = (
        "You will be given INVALID JSON. Return ONLY a repaired VALID JSON object.\n"
        "Rules:\n"
        "- Output must be valid JSON.\n"
        "- No markdown.\n"
        "- Do not add commentary.\n\n"
        "INVALID JSON:\n"
        f"{raw}\n"
    )
    payload = {
        "model": model,
        "format": "json",
        "messages": [
            {"role": "system", "content": "Return ONLY valid JSON. No markdown. No commentary."},
            {"role": "user", "content": repair_prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    r = requests.post(url, json=payload, timeout=timeout_s)
    r.raise_for_status()
    data = r.json()
    msg = data.get("message") or {}
    return (msg.get("content") or "").strip()


def parse_json_or_debug(raw: str, *, model: str, base_url: str, timeout_s: int) -> Dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        DEBUG_RAW_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        DEBUG_RAW_OUTPUT.write_text(raw + "\n", encoding="utf-8")

        # Track A: cheap auto-fix
        fixed = try_close_braces(raw)
        if fixed != raw:
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass

        # Repair via model once
        repaired = repair_json_with_model(raw, model=model, base_url=base_url, timeout_s=timeout_s)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as e2:
            DEBUG_REPAIRED_OUTPUT.write_text(repaired + "\n", encoding="utf-8")
            raise RuntimeError(
                "Model did not return valid JSON (even after repair). "
                "Saved raw to examples/last_raw_output.txt and repaired to examples/last_repaired_output.txt.\n"
                f"JSON error: {e2}"
            )


def validate_and_fix_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(spec, dict):
        raise ValueError("Spec must be a JSON object")

    # normalize keys
    spec.setdefault("project_name", "archmind_project")
    spec.setdefault("directories", [])
    spec.setdefault("files", {})
    if spec["directories"] is None:
        spec["directories"] = []
    if spec["files"] is None:
        spec["files"] = {}

    if not isinstance(spec["directories"], list):
        raise ValueError("directories must be a list")
    if not isinstance(spec["files"], dict):
        raise ValueError("files must be an object mapping path->content")

    # ensure string values
    cleaned_files: Dict[str, str] = {}
    for k, v in spec["files"].items():
        if isinstance(k, str) and isinstance(v, str):
            cleaned_files[k] = v
    spec["files"] = cleaned_files

    return spec


def safe_write_file(path: Path, content: str, force: bool):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite existing file: {path} (use --force)")
    path.write_text(content, encoding="utf-8")


def ensure_dirs(base: Path, dirs: List[str]):
    base_resolved = base.resolve()
    for d in dirs:
        p = (base / d).resolve()
        if base_resolved not in p.parents and p != base_resolved:
            raise ValueError(f"Invalid directory path escapes base: {d}")
        p.mkdir(parents=True, exist_ok=True)


def ensure_files(base: Path, files: Dict[str, str], force: bool):
    base_resolved = base.resolve()
    for rel, content in files.items():
        p = (base / rel).resolve()
        if base_resolved not in p.parents and p != base_resolved:
            raise ValueError(f"Invalid file path escapes base: {rel}")
        safe_write_file(Path(p), content, force=force)


def build_generation_request(prompt: str, idea: str, last_error: Optional[str] = None) -> str:
    correction = ""
    if last_error:
        correction = f"\n\nPrevious attempt failed due to: {last_error}\nFix the spec accordingly.\n"
    return f"{prompt}\n\nIDEA:\n{idea}\n{correction}"

def keep_only_prefixes(files: Dict[str, str], prefixes: list[str]) -> Dict[str, str]:
    allowed = {}
    for k, v in files.items():
        if any(k == p.rstrip("/") or k.startswith(p.rstrip("/") + "/") for p in prefixes):
            allowed[k] = v
    return allowed


def keep_only_exact(files: Dict[str, str], exact: set[str]) -> Dict[str, str]:
    return {k: v for k, v in files.items() if k in exact}

def generate_valid_spec(prompt: str, idea: str, opt: GenerateOptions) -> Dict[str, Any]:
    last_err: Optional[str] = None
    fallback_name = (opt.name or "archmind_project").strip() or "archmind_project"

    for attempt in range(1, opt.max_retries + 1):
        req = build_generation_request(prompt, idea, last_err)
        raw = call_ollama_chat(req, model=opt.model, base_url=opt.ollama_base_url, timeout_s=opt.timeout_s)

        try:
            spec = parse_json_or_debug(raw, model=opt.model, base_url=opt.ollama_base_url, timeout_s=opt.timeout_s)
        except RuntimeError as e:
            print(f"[WARN] Invalid JSON from model. Using fallback spec. Details: {e}")
            spec = fallback_spec(project_name=fallback_name)

        try:
            spec = validate_and_fix_spec(spec)
            return spec
        except Exception as e:
            last_err = str(e)
            print(f"[WARN] Spec validation failed (attempt {attempt}/{opt.max_retries}): {e}")

    raise RuntimeError(f"Failed to generate valid spec after {opt.max_retries} attempts: {last_err}")


def apply_template(spec: Dict[str, Any], opt: GenerateOptions) -> Dict[str, Any]:
    project_name = str(spec.get("project_name") or "archmind_project")

    files = spec.get("files")
    if not isinstance(files, dict):
        files = {}

    if opt.template == "fastapi":
        # minimal: keep model files but enforce runtime
        files = enforce_fastapi_runtime(files, project_name)

    elif opt.template == "fastapi-ddd":
        # DDD: ignore model noise; enforce clean structure
        files = enforce_fastapi_ddd({}, project_name)

        # Optional: if you want to preserve ONLY model-provided docs (rare), you could merge selectively.
        # For final quality, keep it deterministic.

        # Ensure we don't accidentally include root main.py etc.
        # (we only generate app/*, tests/*, README.md, requirements.txt)
    else:
        files = enforce_fastapi_runtime(files, project_name)

    spec["files"] = files
    return spec


def write_project(spec: Dict[str, Any], opt: GenerateOptions) -> Path:
    project_name = str(spec.get("project_name") or "archmind_project")
    project_root = opt.out / project_name

    if project_root.exists():
        if opt.force:
        # IMPORTANT: --force should remove stale files from previous generations
            shutil.rmtree(project_root)
        else:
            raise FileExistsError(
                f"Project folder already exists: {project_root}\nUse --force to overwrite files, or delete the folder."
            )
    project_root.mkdir(parents=True, exist_ok=True)
    ensure_dirs(project_root, spec.get("directories") or [])
    ensure_files(project_root, spec.get("files") or {}, force=opt.force)

    # save spec snapshot
    safe_write_file(project_root / "archmind_spec.json", json.dumps(spec, ensure_ascii=False, indent=2), force=True)
    return project_root