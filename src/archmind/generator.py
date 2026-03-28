# src/archmind/generator.py
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional

from .templates.fastapi import enforce_fastapi_runtime
from .templates.fastapi_ddd import enforce_fastapi_ddd
from .templates.nextjs import enforce_nextjs_runtime
from .templates.internal_tool import enforce_internal_tool
from .templates.worker_api import enforce_worker_api
from .templates.data_tool import enforce_data_tool
from .backend_runtime import detect_backend_asgi_entry, has_fastapi_app_declaration
from .reasoning import generate_reasoning_text

DEBUG_RAW_OUTPUT = Path("examples/last_raw_output.txt")
DEBUG_REPAIRED_OUTPUT = Path("examples/last_repaired_output.txt")
SUPPORTED_MODULES = ("auth", "db", "dashboard", "worker", "file-upload")


@dataclass
class GenerateOptions:
    out: Path
    force: bool = False
    name: Optional[str] = None
    template: str = "fastapi"  # "fastapi" | "fastapi-ddd"
    model: str = "llama3:latest"
    ollama_base_url: str = "http://localhost:11434"
    max_retries: int = 2
    timeout_s: int = 240


# -----------------------------
# Model I/O (Ollama)
# -----------------------------
def call_ollama_chat(req: str, *, model: str, base_url: str, timeout_s: int) -> str:
    """
    Call Ollama /api/chat and return message.content as a string.
    """
    return generate_reasoning_text(
        req,
        mode="local",
        local_model=model,
        local_base_url=base_url,
        timeout_s=timeout_s,
        system_prompt="Return ONLY valid JSON. No markdown. No commentary.",
        format_json=True,
        temperature=0.2,
    )


def repair_json_with_model(raw: str, *, model: str, base_url: str, timeout_s: int) -> str:
    """
    Ask the model to repair invalid JSON. Returns a string that should be valid JSON.
    """
    repair_prompt = (
        "You will be given INVALID JSON. Return ONLY a repaired VALID JSON object.\n"
        "Rules:\n"
        "- Output must be valid JSON.\n"
        "- No markdown.\n"
        "- Do not add commentary.\n\n"
        "INVALID JSON:\n"
        f"{raw}\n"
    )
    return generate_reasoning_text(
        repair_prompt,
        mode="local",
        local_model=model,
        local_base_url=base_url,
        timeout_s=timeout_s,
        system_prompt="Return ONLY valid JSON. No markdown. No commentary.",
        format_json=True,
        temperature=0.0,
    )


# -----------------------------
# Spec helpers
# -----------------------------
def try_close_braces(s: str) -> str:
    """
    Cheap fix: if braces are unbalanced, append missing '}' at the end.
    """
    open_cnt = s.count("{")
    close_cnt = s.count("}")
    if close_cnt < open_cnt:
        s = s + ("\n" + ("}" * (open_cnt - close_cnt)))
    return s


def fallback_spec(project_name: str) -> Dict[str, Any]:
    """
    Safe minimal spec when model output is invalid.
    """
    return {
        "project_name": project_name,
        "summary": "Fallback spec used because model output was invalid JSON.",
        "stack": {"language": "python", "framework": "fastapi", "server": "uvicorn"},
        "directories": [],
        "files": {},
    }


def _normalize_relative_path(raw: str) -> str:
    text = str(raw or "").strip().replace("\\", "/")
    if not text:
        return ""
    if len(text) >= 2 and text[1] == ":" and text[0].isalpha():
        text = text[2:]
    text = text.lstrip("/")
    if not text:
        return ""

    parts: List[str] = []
    for part in PurePosixPath(text).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def parse_json_or_debug(raw: str, *, model: str, base_url: str, timeout_s: int) -> Dict[str, Any]:
    """
    Parse JSON. If it fails:
      1) save raw output
      2) try cheap fix (close braces)
      3) ask model once to repair JSON and save repaired output if still invalid
    """
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

        # Track B: repair via model once
        repaired = repair_json_with_model(raw, model=model, base_url=base_url, timeout_s=timeout_s)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as e2:
            DEBUG_REPAIRED_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
            DEBUG_REPAIRED_OUTPUT.write_text(repaired + "\n", encoding="utf-8")
            raise RuntimeError(
                "Model did not return valid JSON (even after repair). "
                "Saved raw to examples/last_raw_output.txt and repaired to examples/last_repaired_output.txt.\n"
                f"JSON error: {e2}"
            )


def validate_and_fix_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize and validate spec structure.
    Ensures:
      - spec is dict
      - directories is list
      - files is dict[str,str]
    """
    if not isinstance(spec, dict):
        raise ValueError("Spec must be a JSON object")

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

    cleaned_dirs: List[str] = []
    seen_dirs = set()
    for item in spec["directories"]:
        if not isinstance(item, str):
            continue
        normalized = _normalize_relative_path(item)
        if not normalized or normalized in seen_dirs:
            continue
        seen_dirs.add(normalized)
        cleaned_dirs.append(normalized)

    # Keep only string->string files
    cleaned_files: Dict[str, str] = {}
    for k, v in spec["files"].items():
        if isinstance(k, str) and isinstance(v, str):
            normalized = _normalize_relative_path(k)
            if normalized:
                cleaned_files[normalized] = v
    spec["directories"] = cleaned_dirs
    spec["files"] = cleaned_files

    return spec


def build_generation_request(prompt: str, idea: str, last_error: Optional[str] = None) -> str:
    correction = ""
    if last_error:
        correction = f"\n\nPrevious attempt failed due to: {last_error}\nFix the spec accordingly.\n"
    return f"{prompt}\n\nIDEA:\n{idea}\n{correction}"


def generate_valid_spec(prompt: str, idea: str, opt: GenerateOptions) -> Dict[str, Any]:
    """
    Generate spec with retries:
      - call model
      - parse/repair JSON
      - validate structure
      - fallback spec if model keeps failing JSON
    """
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
            return validate_and_fix_spec(spec)
        except Exception as e:
            last_err = str(e)
            print(f"[WARN] Spec validation failed (attempt {attempt}/{opt.max_retries}): {e}")

    raise RuntimeError(f"Failed to generate valid spec after {opt.max_retries} attempts: {last_err}")


# -----------------------------
# Template application
# -----------------------------
def apply_template(spec: Dict[str, Any], opt: GenerateOptions) -> Dict[str, Any]:
    """
    Apply a deterministic template to make outputs reliable.
    """
    project_name = str((opt.name or spec.get("project_name") or "archmind_project"))
    spec["project_name"] = project_name

    files = spec.get("files")
    if not isinstance(files, dict):
        files = {}

    if opt.template == "fastapi":
        files = enforce_fastapi_runtime(files, project_name)

    elif opt.template == "fastapi-ddd":
        # DDD: template is the source of truth (ignore model files/dirs)
        files = enforce_fastapi_ddd({}, project_name)
        spec["directories"] = [
            "app",
            "app/db",
            "app/domain",
            "app/repositories",
            "app/services",
            "tests",
        ]

    elif opt.template == "fullstack-ddd":
        from archmind.templates.fullstack_ddd import enforce_fullstack_ddd

        files = enforce_fullstack_ddd({}, project_name)
        spec["directories"] = [
            "backend",
            "backend/app",
            "backend/app/api",
            "backend/app/api/routers",
            "backend/app/core",
            "backend/app/db",
            "backend/app/domain",
            "backend/app/repositories",
            "backend/app/services",
            "backend/tests",
            "frontend",
            "frontend/app",
            "frontend/app/ui",
            "scripts",
        ]
        spec["files"] = files
    elif opt.template == "nextjs":
        files = enforce_nextjs_runtime({}, project_name)
        spec["directories"] = [
            "app",
        ]
    elif opt.template == "internal-tool":
        files = enforce_internal_tool({}, project_name)
        spec["directories"] = [
            "app",
            "app/api",
            "app/api/routers",
            "app/core",
            "app/db",
            "app/domain",
            "app/repositories",
            "app/services",
            "tests",
            "frontend",
            "frontend/app",
            "frontend/app/ui",
            "scripts",
        ]
    elif opt.template == "worker-api":
        files = enforce_worker_api({}, project_name)
        spec["directories"] = [
            "app",
            "app/api",
            "app/api/routers",
            "app/core",
            "app/db",
            "app/domain",
            "app/repositories",
            "app/services",
            "app/workers",
            "tests",
        ]
    elif opt.template == "data-tool":
        files = enforce_data_tool({}, project_name)
        spec["directories"] = [
            "app",
            "app/api",
            "app/api/routers",
            "app/core",
            "app/db",
            "app/domain",
            "app/repositories",
            "app/services",
            "tests",
            "frontend",
            "frontend/app",
            "frontend/app/ui",
            "scripts",
        ]

    else:
        files = enforce_fastapi_runtime(files, project_name)

    spec["files"] = files
    return spec


# -----------------------------
# Safe project writing
# -----------------------------
def safe_write_file(path: Path, content: str, force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite existing file: {path} (use --force)")
    path.write_text(content, encoding="utf-8")


def ensure_dirs(base: Path, dirs: List[str]) -> None:
    base_resolved = base.resolve()
    for d_raw in dirs:
        d = _normalize_relative_path(d_raw)
        if not d:
            continue
        p = (base / d).resolve()
        if base_resolved not in p.parents and p != base_resolved:
            raise ValueError(f"Invalid directory path escapes base: {d}")
        p.mkdir(parents=True, exist_ok=True)


def ensure_files(base: Path, files: Dict[str, str], *, force: bool) -> None:
    base_resolved = base.resolve()
    normalized_files: Dict[str, str] = {}
    for rel_raw, content in files.items():
        rel = _normalize_relative_path(rel_raw)
        if rel:
            normalized_files[rel] = content

    for rel, content in normalized_files.items():
        p = (base / rel).resolve()
        if base_resolved not in p.parents and p != base_resolved:
            raise ValueError(f"Invalid file path escapes base: {rel}")
        safe_write_file(Path(p), content, force=force)


def write_project(spec: Dict[str, Any], opt: GenerateOptions) -> Path:
    project_name = str(spec.get("project_name") or "archmind_project")
    project_root = opt.out / project_name

    if project_root.exists():
        if opt.force:
            # --force should remove stale files from previous generations
            shutil.rmtree(project_root)
        else:
            raise FileExistsError(
                f"Project folder already exists: {project_root}\n"
                "Use --force to overwrite files, or delete the folder."
            )

    project_root.mkdir(parents=True, exist_ok=True)
    ensure_dirs(project_root, spec.get("directories") or [])
    ensure_files(project_root, spec.get("files") or {}, force=opt.force)

    # Save spec snapshot (always overwrite inside a newly created folder)
    safe_write_file(
        project_root / "archmind_spec.json",
        json.dumps(spec, ensure_ascii=False, indent=2),
        force=True,
    )
    return project_root


def apply_modules_to_project(project_dir: Path, template_name: str, modules: list[str]) -> None:
    """
    Sprint 2 module hook:
    - keep selected module artifact
    - create minimal module placeholder structure
    - reflect selected modules in README
    """
    seen: set[str] = set()
    requested = [str(item).strip().lower() for item in modules if str(item).strip()]
    normalized: List[str] = []
    for mod in SUPPORTED_MODULES:
        if mod in requested and mod not in seen:
            seen.add(mod)
            normalized.append(mod)
    for mod in requested:
        if mod not in seen:
            seen.add(mod)
            normalized.append(mod)
    if not normalized:
        return

    archmind_dir = project_dir / ".archmind"
    archmind_dir.mkdir(parents=True, exist_ok=True)
    (archmind_dir / "selected_modules.json").write_text(
        json.dumps({"modules": normalized}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    tmpl = str(template_name or "").strip().lower()
    backend_root = _resolve_backend_app_root(project_dir) or (project_dir / "app")
    frontend_root = project_dir / "app"
    if tmpl in {"fullstack-ddd", "internal-tool", "data-tool"}:
        frontend_root = project_dir / "frontend" / "app"
    elif tmpl == "nextjs":
        frontend_root = project_dir / "app"

    is_backend_project = tmpl in {"fastapi", "fastapi-ddd", "fullstack-ddd", "worker-api", "internal-tool", "data-tool"} or (
        backend_root / "main.py"
    ).exists()
    is_frontend_project = tmpl in {"nextjs", "fullstack-ddd", "internal-tool", "data-tool"} or (
        (project_dir / "package.json").exists() or (project_dir / "frontend" / "package.json").exists()
    )

    if "auth" in normalized:
        if is_backend_project:
            auth_router = backend_root / "auth" / "router.py"
            auth_router.parent.mkdir(parents=True, exist_ok=True)
            auth_router.write_text(
                "from fastapi import APIRouter\n\n"
                'router = APIRouter(prefix="/auth")\n\n'
                '@router.get("/login")\n'
                "def login_placeholder():\n"
                '    return {"message": "auth placeholder"}\n',
                encoding="utf-8",
            )
        if is_frontend_project:
            login_page = frontend_root / "login" / "page.tsx"
            login_page.parent.mkdir(parents=True, exist_ok=True)
            login_page.write_text(
                "export default function LoginPage() {\n"
                "  return (\n"
                "    <div>\n"
                "      <h1>Login Page</h1>\n"
                "      <p>Auth module placeholder</p>\n"
                "    </div>\n"
                "  );\n"
                "}\n",
                encoding="utf-8",
            )

    if "db" in normalized and is_backend_project:
        db_file = backend_root / "db" / "database.py"
        db_file.parent.mkdir(parents=True, exist_ok=True)
        db_file.write_text('DATABASE_URL = "env:DATABASE_URL"\n', encoding="utf-8")

        env_example = (project_dir / "backend" / ".env.example") if (project_dir / "backend" / ".env.example").exists() else (project_dir / ".env.example")
        if env_example.exists():
            env_text = env_example.read_text(encoding="utf-8")
            if "DATABASE_URL=" not in env_text:
                if env_text and not env_text.endswith("\n"):
                    env_text += "\n"
                env_text += "DATABASE_URL=\n"
                env_example.write_text(env_text, encoding="utf-8")

    if "dashboard" in normalized and is_frontend_project:
        dashboard_page = frontend_root / "dashboard" / "page.tsx"
        dashboard_page.parent.mkdir(parents=True, exist_ok=True)
        dashboard_page.write_text(
            "export default function DashboardPage() {\n"
            "  return (\n"
            "    <div>\n"
            "      <h1>Dashboard</h1>\n"
            "      <p>Dashboard module placeholder</p>\n"
            "    </div>\n"
            "  );\n"
            "}\n",
            encoding="utf-8",
        )

    if "worker" in normalized and is_backend_project:
        worker_file = backend_root / "workers" / "worker_placeholder.py"
        worker_file.parent.mkdir(parents=True, exist_ok=True)
        worker_file.write_text(
            "from __future__ import annotations\n\n"
            "def run_worker_placeholder() -> dict[str, str]:\n"
            '    return {"status": "queued", "detail": "worker placeholder"}\n',
            encoding="utf-8",
        )

    if "file-upload" in normalized:
        if is_backend_project:
            upload_router = backend_root / "uploads" / "router.py"
            upload_router.parent.mkdir(parents=True, exist_ok=True)
            upload_router.write_text(
                "from fastapi import APIRouter\n\n"
                'router = APIRouter(prefix="/uploads")\n\n'
                '@router.post("/file")\n'
                "def upload_placeholder() -> dict[str, str]:\n"
                '    return {"status": "ok", "detail": "file-upload placeholder"}\n',
                encoding="utf-8",
            )
        if is_frontend_project:
            upload_page = frontend_root / "upload" / "page.tsx"
            upload_page.parent.mkdir(parents=True, exist_ok=True)
            upload_page.write_text(
                "export default function UploadPage() {\n"
                "  return (\n"
                "    <div>\n"
                "      <h1>Upload</h1>\n"
                "      <p>File upload module placeholder</p>\n"
                "    </div>\n"
                "  );\n"
                "}\n",
                encoding="utf-8",
            )

    readme_path = project_dir / "README.md"
    if not readme_path.exists():
        return

    content = readme_path.read_text(encoding="utf-8")
    section = (
        "## Selected modules\n\n"
        + "\n".join([f"- {item}" for item in normalized])
        + "\n\n"
        + "This project was generated with modules selected by ArchMind reasoning.\n"
    )
    pattern = re.compile(r"(?ms)^## Selected modules\n.*?(?=^## |\Z)")
    if pattern.search(content):
        content = pattern.sub(section, content)
        readme_path.write_text(content, encoding="utf-8")
        return

    if content and not content.endswith("\n"):
        content += "\n"
    readme_path.write_text(content + "\n" + section, encoding="utf-8")


def _has_backend_structure(project_dir: Path) -> bool:
    root_app_dir = project_dir / "app"
    backend_app_dir = project_dir / "backend" / "app"
    return bool(
        (
            root_app_dir.is_dir() and (root_app_dir / "main.py").exists()
        )
        or (
            backend_app_dir.is_dir() and (backend_app_dir / "main.py").exists()
        )
    )


def _resolve_backend_project_root(project_dir: Path) -> Optional[Path]:
    backend_root = project_dir / "backend"
    if (backend_root / "app" / "main.py").exists():
        return backend_root
    if (project_dir / "app" / "main.py").exists():
        return project_dir
    return None


def _resolve_backend_app_root(project_dir: Path) -> Optional[Path]:
    backend_root = _resolve_backend_project_root(project_dir)
    if backend_root is None:
        return None
    app_root = backend_root / "app"
    if app_root.is_dir():
        return app_root
    return None


def _resolve_frontend_app_root(project_dir: Path) -> Optional[Path]:
    frontend_dir = project_dir / "frontend"
    if frontend_dir.is_dir() or (frontend_dir / "package.json").exists() or (frontend_dir / "app").exists():
        return frontend_dir / "app"
    if (project_dir / "package.json").exists() or (project_dir / "next.config.mjs").exists():
        return project_dir / "app"
    return None


def has_frontend_structure(project_dir: Path) -> bool:
    return _resolve_frontend_app_root(project_dir) is not None


def _entity_identity(entity_name: str) -> tuple[str, str, str]:
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "", str(entity_name or "").strip())
    if not safe_name:
        return "", "", ""
    if safe_name[0].isdigit():
        safe_name = f"entity_{safe_name}"
    class_name = safe_name[0].upper() + safe_name[1:]
    slug = re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower()
    plural = _pluralize_resource_name(slug)
    return class_name, slug, plural


def _safe_component_name(parts: list[str], suffix: str = "Page") -> str:
    normalized: list[str] = []
    for raw in parts:
        text = re.sub(r"[^a-zA-Z0-9]", " ", str(raw or ""))
        tokens = [token for token in text.split() if token]
        for token in tokens:
            normalized.append(token[:1].upper() + token[1:])
    name = "".join(normalized) or "Generated"
    if name[0].isdigit():
        name = f"P{name}"
    if suffix and not name.endswith(suffix):
        name = f"{name}{suffix}"
    return name


def _pluralize_resource_name(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text.endswith("s"):
        return text
    if text.endswith("y") and len(text) > 1 and text[-2] not in "aeiou":
        return text[:-1] + "ies"
    if text.endswith(("ch", "sh", "x", "z")):
        return text + "es"
    return text + "s"


def _normalize_resource_segment(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_-]", "", str(value or "").strip().lower())
    return text


def _canonicalize_api_path(path: str) -> str:
    raw = str(path or "").strip().replace("\\", "/")
    if not raw:
        return ""
    if not raw.startswith("/"):
        raw = "/" + raw
    raw = re.sub(r"/{2,}", "/", raw)
    if " " in raw:
        return ""
    parts = [part for part in raw.strip("/").split("/") if part]
    if not parts:
        return ""
    canonical_parts: list[str] = []
    treat_as_resource = len(parts) == 1 or (len(parts) >= 2 and parts[1].startswith("{") and parts[1].endswith("}"))
    for idx, part in enumerate(parts):
        if part.startswith("{") and part.endswith("}"):
            canonical_parts.append(part)
            continue
        normalized = _normalize_resource_segment(part)
        if not normalized:
            return ""
        if idx == 0 and treat_as_resource:
            normalized = _pluralize_resource_name(normalized)
        canonical_parts.append(normalized)
    return "/" + "/".join(canonical_parts)


def _canonicalize_page_path(raw_path: str) -> str:
    raw = str(raw_path or "").strip().replace("\\", "/")
    raw = re.sub(r"/{2,}", "/", raw).strip("/")
    if not raw or " " in raw:
        return ""
    parts = [part for part in raw.split("/") if part]
    normalized_parts: list[str] = []
    for part in parts:
        normalized = _normalize_resource_segment(part)
        if not normalized:
            return ""
        normalized_parts.append(normalized)
    if len(normalized_parts) == 1:
        return f"{_pluralize_resource_name(normalized_parts[0])}/list"
    leaf = normalized_parts[-1]
    if leaf in {"list", "detail", "new", "create", "add"}:
        normalized_parts[0] = _pluralize_resource_name(normalized_parts[0])
        if leaf in {"create", "add"}:
            normalized_parts[-1] = "new"
    return "/".join(normalized_parts)


def _singularize_resource_name(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text.endswith("ies") and len(text) > 3:
        return text[:-3] + "y"
    if text.endswith("ses") and len(text) > 3:
        return text[:-2]
    if text.endswith("s") and len(text) > 1:
        return text[:-1]
    return text


def _route_kind_from_segments(parts: list[str]) -> str:
    if not parts:
        return "root"
    leaf = parts[-1]
    if len(parts) == 1 or leaf == "list":
        return "list"
    if leaf == "new":
        return "create"
    if leaf == "detail" or "[id]" in parts:
        return "detail"
    return "other"


def _frontend_route_from_page_rel(rel: str) -> str:
    parts = [part for part in str(rel or "").split("/") if part]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    leaf = parts[-1]
    if leaf in {"list", "index"}:
        return "/".join(parts[:-1]) or parts[0]
    if leaf in {"detail", "details", "view", "show"}:
        base = "/".join(parts[:-1]) or parts[0]
        return f"{base}/[id]"
    return "/".join(parts)


def _write_if_missing(path: Path, content: str, generated: list[str], project_dir: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    generated.append(str(path.relative_to(project_dir)).replace("\\", "/"))


def _render_frontend_api_base_helper() -> str:
    return (
        '"use client";\n\n'
        'import { useEffect, useState } from "react";\n\n'
        "const ENV_API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL;\n"
        "const ENV_RUNTIME_BACKEND_URL = process.env.NEXT_PUBLIC_RUNTIME_BACKEND_URL;\n"
        'const ENV_BACKEND_PORT = process.env.NEXT_PUBLIC_BACKEND_PORT || "";\n'
        'const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);\n\n'
        "function isLoopbackHost(hostname: string) {\n"
        '  return LOOPBACK_HOSTS.has((hostname || "").trim().toLowerCase());\n'
        "}\n\n"
        "function normalizeApiBase(raw: string): string {\n"
        '  return String(raw || "").trim().replace(/\\/$/, "");\n'
        "}\n\n"
        "function rewriteLoopbackToBrowserHost(rawUrl: string, browserHost: string): string {\n"
        "  try {\n"
        "    const parsed = new URL(rawUrl);\n"
        "    if (!isLoopbackHost(parsed.hostname)) {\n"
        "      return normalizeApiBase(parsed.toString());\n"
        "    }\n"
        "    if (!browserHost || isLoopbackHost(browserHost)) {\n"
        "      return normalizeApiBase(parsed.toString());\n"
        "    }\n"
        "    parsed.hostname = browserHost;\n"
        "    return normalizeApiBase(parsed.toString());\n"
        "  } catch {\n"
        "    return normalizeApiBase(rawUrl);\n"
        "  }\n"
        "}\n\n"
        "function resolveApiBaseInBrowser(): string {\n"
        "  const explicitApiBase = String(ENV_API_BASE || \"\").trim();\n"
        "  const runtimeBackendBase = String(ENV_RUNTIME_BACKEND_URL || \"\").trim();\n"
        '  const explicitPort = String(ENV_BACKEND_PORT || "").trim();\n'
        '  const browserHost = (window.location.hostname || "").trim();\n'
        '  const browserProtocol = window.location.protocol === "https:" ? "https" : "http";\n'
        "  if (explicitApiBase) {\n"
        "    return rewriteLoopbackToBrowserHost(explicitApiBase, browserHost);\n"
        "  }\n"
        "  if (runtimeBackendBase) {\n"
        "    return rewriteLoopbackToBrowserHost(runtimeBackendBase, browserHost);\n"
        "  }\n"
        "  if (explicitPort) {\n"
        "    if (browserHost) {\n"
        "      return `${browserProtocol}://${browserHost}:${explicitPort}`;\n"
        "    }\n"
        '    return `http://127.0.0.1:${explicitPort}`;\n'
        "  }\n"
        "  if (browserHost) {\n"
        '    return `${browserProtocol}://${browserHost}:8000`;\n'
        "  }\n"
        '  return "http://127.0.0.1:8000";\n'
        "}\n\n"
        "export function useApiBaseUrl(): { apiBaseUrl: string; apiBaseLoading: boolean } {\n"
        '  const [apiBaseUrl, setApiBaseUrl] = useState("");\n'
        "  const [apiBaseLoading, setApiBaseLoading] = useState(true);\n\n"
        "  useEffect(() => {\n"
        "    if (typeof window === \"undefined\") {\n"
        "      return;\n"
        "    }\n"
        "    setApiBaseUrl(resolveApiBaseInBrowser());\n"
        "    setApiBaseLoading(false);\n"
        "  }, []);\n\n"
        "  return { apiBaseUrl, apiBaseLoading };\n"
        "}\n"
    )


def _api_base_helper_import_for_page(app_root: Path, page_file: Path) -> str:
    helper_target = app_root / "_lib" / "apiBase"
    rel = os.path.relpath(helper_target, page_file.parent).replace("\\", "/")
    if not rel.startswith("."):
        rel = f"./{rel}"
    return rel


def _ensure_frontend_api_base_helper(app_root: Path, generated: list[str], project_dir: Path) -> None:
    helper_path = app_root / "_lib" / "apiBase.ts"
    _write_if_missing(helper_path, _render_frontend_api_base_helper(), generated, project_dir)


def _frontend_nav_path(app_root: Path) -> Path:
    return app_root / "_lib" / "navigation.ts"


def _nav_label_from_href(href: str) -> str:
    normalized = _canonicalize_nav_href(href).strip("/")
    if not normalized:
        return "Home"
    parts = [part for part in normalized.split("/") if part]
    kind = _route_kind_from_segments(parts)
    if kind == "list":
        return parts[0].replace("-", " ").replace("_", " ").title()
    if kind == "create":
        entity = _singularize_resource_name(parts[0]).replace("-", " ").replace("_", " ").title()
        return f"New {entity}" if entity else "New"
    if kind == "detail":
        entity = _singularize_resource_name(parts[0]).replace("-", " ").replace("_", " ").title()
        return f"{entity} Detail" if entity else "Detail"
    leaf = parts[-1]
    return leaf.replace("-", " ").replace("_", " ").title()


def _canonicalize_nav_href(href: str) -> str:
    text = str(href or "").strip().replace("\\", "/")
    if not text:
        return ""
    if not text.startswith("/"):
        text = "/" + text
    text = re.sub(r"/{2,}", "/", text).rstrip("/")
    if not text:
        return "/"
    if " " in text:
        return ""
    rel = _canonicalize_page_path(text.strip("/"))
    if rel:
        route_rel = _frontend_route_from_page_rel(rel)
        return "/" + route_rel if route_rel else ""
    parts = [part for part in text.strip("/").split("/") if part]
    normalized_parts: list[str] = []
    for part in parts:
        if part.startswith("[") and part.endswith("]"):
            normalized_parts.append(part)
            continue
        normalized = _normalize_resource_segment(part)
        if not normalized:
            return ""
        normalized_parts.append(normalized)
    return "/" + "/".join(normalized_parts) if normalized_parts else "/"


def _discover_frontend_routes(app_root: Path) -> list[str]:
    routes: list[str] = []
    for page in sorted(app_root.rglob("page.tsx")):
        rel_dir = page.parent.relative_to(app_root)
        if str(rel_dir) == ".":
            continue
        parts = [part for part in rel_dir.parts if part and not part.startswith("_")]
        if not parts:
            continue
        if any(part.startswith("[") or part.endswith("]") for part in parts):
            continue
        route = "/" + "/".join(parts)
        if route not in routes:
            routes.append(route)
    return routes


def _render_frontend_navigation_file(hrefs: list[str]) -> str:
    unique: list[str] = []
    seen_canonical: set[str] = set()
    seen_labels: set[str] = set()
    has_non_root = any(_canonicalize_nav_href(item) not in {"", "/"} for item in hrefs)
    for href in hrefs:
        cleaned = _canonicalize_nav_href(href)
        if not cleaned:
            continue
        if has_non_root and cleaned == "/":
            continue
        parts = [part for part in cleaned.strip("/").split("/") if part]
        if _route_kind_from_segments(parts) == "detail":
            continue
        if cleaned in seen_canonical:
            continue
        label_key = _nav_label_from_href(cleaned).strip().lower()
        if label_key in seen_labels:
            continue
        seen_canonical.add(cleaned)
        seen_labels.add(label_key)
        unique.append(cleaned)
    if not unique:
        unique = ["/"]
    lines = []
    for index, href in enumerate(unique):
        label = _nav_label_from_href(href)
        primary = ", primary: true" if index == 0 else ""
        lines.append(f'  {{ href: "{href}", label: "{label}"{primary} }},')
    entries = "\n".join(lines)
    return (
        "export type AppNavLink = {\n"
        "  href: string;\n"
        "  label: string;\n"
        "  primary?: boolean;\n"
        "};\n\n"
        "export const APP_NAV_LINKS: AppNavLink[] = [\n"
        f"{entries}\n"
        "];\n"
    )


def _parse_nav_hrefs(navigation_text: str) -> list[str]:
    hrefs: list[str] = []
    for match in re.finditer(r'href:\s*"([^"]+)"', navigation_text):
        href = _canonicalize_nav_href(match.group(1))
        if href and href not in hrefs:
            hrefs.append(href)
    return hrefs


def _ensure_frontend_navigation_helper(app_root: Path, generated: list[str], project_dir: Path) -> None:
    nav_path = _frontend_nav_path(app_root)
    if nav_path.exists():
        return
    discovered = _discover_frontend_routes(app_root)
    if not discovered:
        discovered = ["/"]
    _write_if_missing(nav_path, _render_frontend_navigation_file(discovered), generated, project_dir)


def _render_frontend_layout_with_navigation(title: str) -> str:
    safe_title = str(title or "").strip() or "ArchMind App"
    return (
        'import Link from "next/link";\n'
        'import "./globals.css";\n'
        'import { APP_NAV_LINKS } from "./_lib/navigation";\n\n'
        "export const metadata = {\n"
        f'  title: "{safe_title}",\n'
        "};\n\n"
        "export default function RootLayout({ children }: { children: React.ReactNode }) {\n"
        "  return (\n"
        '    <html lang="en">\n'
        "      <body>\n"
        '        <div className="min-h-screen bg-slate-950 text-slate-100">\n'
        '          <header className="border-b border-slate-800 bg-slate-900/80">\n'
        '            <div className="mx-auto max-w-5xl px-4 py-5">\n'
        '              <div className="flex flex-wrap items-center justify-between gap-4">\n'
        "                <div>\n"
        f'                  <div className="text-lg font-semibold tracking-wide">{safe_title}</div>\n'
        '                  <div className="text-xs text-slate-300">FastAPI + Next.js workspace</div>\n'
        "                </div>\n"
        '                <nav className="flex flex-wrap items-center gap-2 text-xs">\n'
        "                  {APP_NAV_LINKS.map((link) => (\n"
        '                    <Link key={link.href} href={link.href} className="rounded-md border border-slate-700 px-2 py-1 text-slate-200 hover:bg-slate-800">\n'
        "                      {link.label}\n"
        "                    </Link>\n"
        "                  ))}\n"
        "                </nav>\n"
        "              </div>\n"
        "            </div>\n"
        "          </header>\n"
        '          <main className="mx-auto max-w-5xl px-4 py-8">{children}</main>\n'
        "        </div>\n"
        "      </body>\n"
        "    </html>\n"
        "  );\n"
        "}\n"
    )


def _render_frontend_root_with_navigation() -> str:
    return (
        '"use client";\n\n'
        'import Link from "next/link";\n'
        'import { useEffect, useMemo, useState } from "react";\n'
        'import { useRouter } from "next/navigation";\n'
        'import { useApiBaseUrl } from "./_lib/apiBase";\n'
        'import { APP_NAV_LINKS } from "./_lib/navigation";\n\n'
        "export default function Page() {\n"
        "  const router = useRouter();\n"
        "  const [checkingPrimary, setCheckingPrimary] = useState(true);\n"
        "  const { apiBaseUrl, apiBaseLoading } = useApiBaseUrl();\n"
        "  const primaryHref = useMemo(() => APP_NAV_LINKS.find((link) => link.primary)?.href || APP_NAV_LINKS[0]?.href || \"/\", []);\n\n"
        "  useEffect(() => {\n"
        "    let active = true;\n"
        "    (async () => {\n"
        "      try {\n"
        "        if (primaryHref === \"/\") {\n"
        "          setCheckingPrimary(false);\n"
        "          return;\n"
        "        }\n"
        "        const response = await fetch(primaryHref, { cache: \"no-store\" });\n"
        "        if (!active) return;\n"
        "        if (response.ok) {\n"
        "          router.replace(primaryHref);\n"
        "          return;\n"
        "        }\n"
        "      } catch {\n"
        "        // Ignore and show default landing.\n"
        "      }\n"
        "      if (active) {\n"
        "        setCheckingPrimary(false);\n"
        "      }\n"
        "    })();\n"
        "    return () => {\n"
        "      active = false;\n"
        "    };\n"
        "  }, [router, primaryHref]);\n\n"
        "  if (checkingPrimary) {\n"
        '    return <p className="text-sm text-slate-300">Loading workspace...</p>;\n'
        "  }\n\n"
        "  return (\n"
        '    <section className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900/60 p-6">\n'
        '      <h1 className="text-lg font-semibold">Project Home</h1>\n'
        '      <p className="text-xs text-slate-300">API: {apiBaseLoading ? "(resolving...)" : apiBaseUrl}</p>\n'
        '      <p className="text-sm text-slate-200">Available sections from generated pages:</p>\n'
        '      <div className="flex flex-wrap gap-2 text-sm">\n'
        "        {APP_NAV_LINKS.map((link) => (\n"
        '          <Link key={link.href} href={link.href} className="rounded-lg border border-slate-700 px-3 py-2 hover:bg-slate-800">\n'
        "            {link.label}\n"
        "          </Link>\n"
        "        ))}\n"
        "      </div>\n"
        "    </section>\n"
        "  );\n"
        "}\n"
    )


def _ensure_frontend_navigation_shell_upgrade(app_root: Path, generated: list[str], project_dir: Path) -> None:
    layout_path = app_root / "layout.tsx"
    if layout_path.exists():
        layout_text = layout_path.read_text(encoding="utf-8")
        if "APP_NAV_LINKS" not in layout_text:
            legacy_markers = (
                "FastAPI + Next.js workspace" in layout_text
                or "/ · /notes" in layout_text
                or "/ui/defects" in layout_text
                or "max-w-4xl p-6" in layout_text
            )
            if legacy_markers:
                title_match = re.search(r'title:\s*["\']([^"\']+)["\']', layout_text)
                title = title_match.group(1) if title_match else project_dir.name
                _write_if_changed(layout_path, _render_frontend_layout_with_navigation(title), generated, project_dir)

    root_page_path = app_root / "page.tsx"
    if root_page_path.exists():
        root_text = root_page_path.read_text(encoding="utf-8")
        if "APP_NAV_LINKS" not in root_text:
            legacy_markers = (
                "Open the generated domain pages" in root_text
                or 'router.replace("/notes")' in root_text
                or "__ROOT_LINKS__" in root_text
                or "ArchMind Fullstack Workspace" in root_text
                or "This scaffold is domain-neutral." in root_text
            )
            if legacy_markers:
                _write_if_changed(root_page_path, _render_frontend_root_with_navigation(), generated, project_dir)


def _register_frontend_nav_link(app_root: Path, href: str, generated: list[str], project_dir: Path) -> None:
    cleaned = _canonicalize_nav_href(href)
    if not cleaned:
        return
    nav_path = _frontend_nav_path(app_root)
    existing_hrefs: list[str] = []
    if nav_path.exists():
        existing_hrefs = _parse_nav_hrefs(nav_path.read_text(encoding="utf-8"))
    else:
        existing_hrefs = _discover_frontend_routes(app_root)
    if cleaned not in existing_hrefs:
        existing_hrefs.append(cleaned)
    content = _render_frontend_navigation_file(existing_hrefs)
    _write_if_changed(nav_path, content, generated, project_dir)


def _render_entity_router_content(slug: str, plural: str) -> str:
    return (
        "from __future__ import annotations\n\n"
        "import json\n"
        "import os\n"
        "import sqlite3\n"
        "from pathlib import Path\n"
        "from typing import Any\n\n"
        "from fastapi import APIRouter, Body, HTTPException\n\n"
        f'router = APIRouter(prefix="/{plural}", tags=["{plural}"])\n\n'
        "TABLE_NAME = "
        + repr(plural)
        + "\n\n"
        "def _project_root() -> Path:\n"
        "    return Path(__file__).resolve().parents[2]\n\n"
        "def _resolve_db_path() -> Path:\n"
        "    db_url = str(os.getenv(\"DB_URL\") or \"\").strip()\n"
        "    if db_url.startswith(\"sqlite:///\"):\n"
        "        raw = db_url.replace(\"sqlite:///\", \"\", 1)\n"
        "        candidate = Path(raw)\n"
        "        if candidate.is_absolute():\n"
        "            return candidate\n"
        "        return (_project_root() / candidate).resolve()\n"
        "    return (_project_root() / \"data\" / \"app.db\").resolve()\n\n"
        "def _connect() -> sqlite3.Connection:\n"
        "    db_path = _resolve_db_path()\n"
        "    db_path.parent.mkdir(parents=True, exist_ok=True)\n"
        "    connection = sqlite3.connect(db_path)\n"
        "    connection.row_factory = sqlite3.Row\n"
        "    return connection\n\n"
        "def _ensure_table(connection: sqlite3.Connection) -> None:\n"
        "    connection.execute(\n"
        "        f\"\"\"\n"
        "        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (\n"
        "            id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
        "            payload TEXT NOT NULL,\n"
        "            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,\n"
        "            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP\n"
        "        )\n"
        "        \"\"\"\n"
        "    )\n"
        "    connection.commit()\n\n"
        "def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:\n"
        "    payload: dict[str, Any] = {}\n"
        "    try:\n"
        "        loaded = json.loads(str(row[\"payload\"] or \"{}\"))\n"
        "        if isinstance(loaded, dict):\n"
        "            payload = loaded\n"
        "    except json.JSONDecodeError:\n"
        "        payload = {}\n"
        "    payload[\"id\"] = int(row[\"id\"])\n"
        "    payload.setdefault(\"created_at\", row[\"created_at\"])\n"
        "    payload.setdefault(\"updated_at\", row[\"updated_at\"])\n"
        "    return payload\n\n"
        '@router.get("/")\n'
        f"def list_{plural}():\n"
        "    with _connect() as connection:\n"
        "        _ensure_table(connection)\n"
        "        rows = connection.execute(\n"
        "            f\"SELECT id, payload, created_at, updated_at FROM {TABLE_NAME} ORDER BY id DESC\"\n"
        "        ).fetchall()\n"
        "    return [_row_to_item(row) for row in rows]\n\n"
        '@router.post("/")\n'
        f"def create_{slug}(payload: dict[str, Any] = Body(default_factory=dict)):\n"
        "    data = payload if isinstance(payload, dict) else {}\n"
        "    encoded = json.dumps(data, ensure_ascii=False)\n"
        "    with _connect() as connection:\n"
        "        _ensure_table(connection)\n"
        "        cursor = connection.execute(\n"
        "            f\"INSERT INTO {TABLE_NAME}(payload) VALUES (?)\",\n"
        "            (encoded,),\n"
        "        )\n"
        "        connection.commit()\n"
        "        row = connection.execute(\n"
        "            f\"SELECT id, payload, created_at, updated_at FROM {TABLE_NAME} WHERE id = ?\",\n"
        "            (int(cursor.lastrowid),),\n"
        "        ).fetchone()\n"
        "    if row is None:\n"
        "        raise HTTPException(status_code=500, detail=\"Failed to create item\")\n"
        "    return _row_to_item(row)\n\n"
        '@router.get("/{id}")\n'
        f"def get_{slug}(id: int):\n"
        "    with _connect() as connection:\n"
        "        _ensure_table(connection)\n"
        "        row = connection.execute(\n"
        "            f\"SELECT id, payload, created_at, updated_at FROM {TABLE_NAME} WHERE id = ?\",\n"
        "            (id,),\n"
        "        ).fetchone()\n"
        "    if row is None:\n"
        f'        raise HTTPException(status_code=404, detail="{slug.capitalize()} not found")\n'
        "    return _row_to_item(row)\n\n"
        '@router.patch("/{id}")\n'
        f"def update_{slug}(id: int, payload: dict[str, Any] = Body(default_factory=dict)):\n"
        "    patch = payload if isinstance(payload, dict) else {}\n"
        "    with _connect() as connection:\n"
        "        _ensure_table(connection)\n"
        "        row = connection.execute(\n"
        "            f\"SELECT id, payload, created_at, updated_at FROM {TABLE_NAME} WHERE id = ?\",\n"
        "            (id,),\n"
        "        ).fetchone()\n"
        "        if row is None:\n"
        f'            raise HTTPException(status_code=404, detail="{slug.capitalize()} not found")\n'
        "        current = _row_to_item(row)\n"
        "        current.update(patch)\n"
        "        current.pop(\"id\", None)\n"
        "        encoded = json.dumps(current, ensure_ascii=False)\n"
        "        connection.execute(\n"
        "            f\"UPDATE {TABLE_NAME} SET payload = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?\",\n"
        "            (encoded, id),\n"
        "        )\n"
        "        connection.commit()\n"
        "        updated = connection.execute(\n"
        "            f\"SELECT id, payload, created_at, updated_at FROM {TABLE_NAME} WHERE id = ?\",\n"
        "            (id,),\n"
        "        ).fetchone()\n"
        "    if updated is None:\n"
        f'        raise HTTPException(status_code=404, detail="{slug.capitalize()} not found")\n'
        "    return _row_to_item(updated)\n\n"
        '@router.delete("/{id}")\n'
        f"def delete_{slug}(id: int):\n"
        "    with _connect() as connection:\n"
        "        _ensure_table(connection)\n"
        "        cursor = connection.execute(\n"
        "            f\"DELETE FROM {TABLE_NAME} WHERE id = ?\",\n"
        "            (id,),\n"
        "        )\n"
        "        connection.commit()\n"
        "    if cursor.rowcount == 0:\n"
        f'        raise HTTPException(status_code=404, detail="{slug.capitalize()} not found")\n'
        '    return {"status": "deleted", "id": id}\n'
    )


def _ensure_named_router_registration(main_py: Path, module_name: str, router_name: str, generated: list[str], project_dir: Path) -> None:
    if not main_py.exists():
        return
    import_line = f"from app.routers.{module_name} import router as {router_name}"
    include_line = f"app.include_router({router_name})"
    text = main_py.read_text(encoding="utf-8")
    changed = False

    if import_line not in text:
        if text and not text.endswith("\n"):
            text += "\n"
        text += f"\n{import_line}\n"
        changed = True
    if include_line not in text:
        if text and not text.endswith("\n"):
            text += "\n"
        text += f"{include_line}\n"
        changed = True

    if changed:
        main_py.write_text(text, encoding="utf-8")
        rel = str(main_py.relative_to(project_dir)).replace("\\", "/")
        if rel not in generated:
            generated.append(rel)


def _ensure_main_router_registration(main_py: Path, entity_slug: str, generated: list[str], project_dir: Path) -> None:
    _ensure_named_router_registration(main_py, entity_slug, f"{entity_slug}_router", generated, project_dir)


def apply_entity_scaffold(project_dir: Path, entity_name: str) -> list[str]:
    """
    Create minimal backend CRUD scaffold placeholders for an entity.
    Returns generated or updated file paths. If backend structure is missing, returns [].
    """
    if not _has_backend_structure(project_dir):
        return []
    backend_app_root = _resolve_backend_app_root(project_dir)
    if backend_app_root is None:
        return []

    class_name, slug, plural = _entity_identity(entity_name)
    if not class_name:
        return []

    generated: list[str] = []
    models_file = backend_app_root / "models" / f"{slug}.py"
    schemas_file = backend_app_root / "schemas" / f"{slug}.py"
    routers_file = backend_app_root / "routers" / f"{slug}.py"

    _write_if_missing(
        models_file,
        f"class {class_name}:\n"
        "    pass\n",
        generated,
        project_dir,
    )
    _write_if_missing(
        schemas_file,
        f"class {class_name}Create:\n"
        "    pass\n\n"
        f"class {class_name}Read:\n"
        "    pass\n",
        generated,
        project_dir,
    )
    _write_if_changed(routers_file, _render_entity_router_content(slug, plural), generated, project_dir)

    _ensure_main_router_registration(backend_app_root / "main.py", slug, generated, project_dir)
    return generated


def apply_api_scaffold(project_dir: Path, method: str, path: str) -> list[str]:
    """
    Create or update a shared custom router with explicit API endpoints.
    Returns changed files. Backend-only check is enforced by structure presence.
    """
    if not _has_backend_structure(project_dir):
        return []
    backend_app_root = _resolve_backend_app_root(project_dir)
    if backend_app_root is None:
        return []

    method_up = str(method or "").strip().upper()
    route_path = _canonicalize_api_path(str(path or "").strip())
    if not method_up or not route_path:
        return []

    router_file = backend_app_root / "routers" / "custom.py"
    decorator = f'@router.{method_up.lower()}("{route_path}")'
    safe = route_path.strip("/").replace("/", "_").replace("{", "").replace("}", "").replace("-", "_")
    safe = re.sub(r"[^a-zA-Z0-9_]", "", safe) or "root"
    fn_name = f"{method_up.lower()}_{safe}"
    needs_id = "{id}" in route_path
    signature = "(id: int)" if needs_id else "()"
    response = f'{{"endpoint": "{method_up} {route_path}"}}'

    content = (
        "from fastapi import APIRouter\n\n"
        'router = APIRouter(tags=["custom"])\n'
    )
    if router_file.exists():
        content = router_file.read_text(encoding="utf-8")
        if decorator in content:
            generated: list[str] = []
            _ensure_named_router_registration(backend_app_root / "main.py", "custom", "custom_router", generated, project_dir)
            return generated
        if content and not content.endswith("\n"):
            content += "\n"
    else:
        router_file.parent.mkdir(parents=True, exist_ok=True)

    content += (
        "\n"
        f"{decorator}\n"
        f"def {fn_name}{signature}:\n"
        f"    return {response}\n"
    )

    generated = []
    _write_if_changed(router_file, content, generated, project_dir)
    _ensure_named_router_registration(backend_app_root / "main.py", "custom", "custom_router", generated, project_dir)
    return generated


def apply_frontend_page_scaffold(project_dir: Path, entity_name: str) -> list[str]:
    """
    Create minimal frontend list/detail page placeholders for an entity.
    Returns generated file paths. If frontend structure is missing, returns [].
    """
    app_root = _resolve_frontend_app_root(project_dir)
    if app_root is None:
        return []
    class_name, _, plural = _entity_identity(entity_name)
    if not class_name:
        return []
    plural_title = plural.replace("_", " ").title().replace(" ", "")
    list_page = app_root / plural / "page.tsx"
    detail_page = app_root / plural / "[id]" / "page.tsx"
    generated: list[str] = []
    _ensure_frontend_api_base_helper(app_root, generated, project_dir)
    _ensure_frontend_navigation_helper(app_root, generated, project_dir)
    _ensure_frontend_navigation_shell_upgrade(app_root, generated, project_dir)
    list_helper_import = _api_base_helper_import_for_page(app_root, list_page)
    detail_helper_import = _api_base_helper_import_for_page(app_root, detail_page)

    _write_if_missing(
        list_page,
        _render_frontend_entity_list_page(
            component_name=f"{plural_title}Page",
            title=plural_title,
            entity_path=plural,
            api_helper_import=list_helper_import,
        ),
        generated,
        project_dir,
    )
    _write_if_missing(
        detail_page,
        _render_frontend_entity_detail_page(
            component_name=f"{class_name}DetailPage",
            title=class_name,
            entity_path=plural,
            api_helper_import=detail_helper_import,
        ),
        generated,
        project_dir,
    )
    _register_frontend_nav_link(app_root, f"/{plural}", generated, project_dir)
    return generated


def apply_page_scaffold(project_dir: Path, page_path: str) -> list[str]:
    """
    Create a frontend page placeholder from explicit page path (e.g., reports/list).
    Returns generated files only; existing files are preserved.
    """
    app_root = _resolve_frontend_app_root(project_dir)
    if app_root is None:
        return []
    rel = _canonicalize_page_path(page_path)
    if not rel or " " in rel:
        return []
    route_rel = _frontend_route_from_page_rel(rel)
    if not route_rel:
        return []
    target = app_root / route_rel / "page.tsx"
    segments = [seg for seg in rel.split("/") if seg]
    if not segments:
        return []
    title = " ".join(seg.replace("-", " ").replace("_", " ").title() for seg in segments)
    comp_name = _safe_component_name(segments)

    generated: list[str] = []
    _ensure_frontend_api_base_helper(app_root, generated, project_dir)
    _ensure_frontend_navigation_helper(app_root, generated, project_dir)
    _ensure_frontend_navigation_shell_upgrade(app_root, generated, project_dir)
    route_kind = _route_kind_from_segments(segments)
    entity_path = "/".join(segments[:-1]).strip("/") if len(segments) > 1 else (segments[0] if segments else "")
    helper_import = _api_base_helper_import_for_page(app_root, target)
    if entity_path and route_kind == "list":
        _write_if_missing(
            target,
            _render_frontend_entity_list_page(
                component_name=comp_name,
                title=title,
                entity_path=entity_path,
                api_helper_import=helper_import,
            ),
            generated,
            project_dir,
        )
        _register_frontend_nav_link(app_root, f"/{route_rel}", generated, project_dir)
        return generated
    if entity_path and route_kind == "detail":
        _write_if_missing(
            target,
            _render_frontend_entity_detail_page(
                component_name=comp_name,
                title=title,
                entity_path=entity_path,
                api_helper_import=helper_import,
            ),
            generated,
            project_dir,
        )
        return generated
    if entity_path and route_kind == "create":
        singular = _singularize_resource_name(entity_path).replace("-", " ").replace("_", " ").title()
        _write_if_missing(
            target,
            _render_generic_page_scaffold(
                component_name=comp_name,
                title=f"New {singular}" if singular else title,
                rel=route_rel,
                api_helper_import=helper_import,
            ),
            generated,
            project_dir,
        )
        _register_frontend_nav_link(app_root, f"/{route_rel}", generated, project_dir)
        return generated

    _write_if_missing(
        target,
        '"use client";\n\n'
        f'import {{ useApiBaseUrl }} from "{helper_import}";\n\n'
        "export default function "
        + comp_name
        + "() {\n"
        "  const { apiBaseUrl, apiBaseLoading } = useApiBaseUrl();\n"
        "  return (\n"
        '    <section className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4">\n'
        "      <h1>"
        + title
        + "</h1>\n"
        '      <p className="text-xs text-slate-400">API: {apiBaseLoading ? "(resolving...)" : apiBaseUrl}</p>\n'
        "      <p>Page placeholder for "
        + route_rel
        + "</p>\n"
        "    </section>\n"
        "  );\n"
        "}\n",
        generated,
        project_dir,
    )
    _register_frontend_nav_link(app_root, f"/{route_rel}", generated, project_dir)
    return generated


def _page_signal_score(content: str) -> int:
    text = str(content or "").lower()
    score = 0
    for token in (
        "useapibaseurl",
        "fetch(",
        "loading",
        "failed to load",
        "no items found",
        "item not found",
        "missing item id",
        "items.map(",
        "json.stringify(",
        "onsubmit(",
        "method: \"post\"",
        "method: \"put\"",
        "method: \"patch\"",
        "method: \"delete\"",
    ):
        if token in text:
            score += 1
    return score


def _is_placeholder_level_page(content: str) -> bool:
    text = str(content or "").lower()
    if not text.strip():
        return True
    placeholder_markers = (
        "page placeholder for",
        "placeholder page",
        "coming soon",
        "todo",
        "tbd",
    )
    marker_hit = any(token in text for token in placeholder_markers)
    if not marker_hit:
        return False
    return _page_signal_score(text) < 3


def _render_generic_page_scaffold(
    *,
    component_name: str,
    title: str,
    rel: str,
    api_helper_import: str,
) -> str:
    return (
        '"use client";\n\n'
        f'import {{ useApiBaseUrl }} from "{api_helper_import}";\n\n'
        f"export default function {component_name}() {{\n"
        "  const { apiBaseUrl, apiBaseLoading } = useApiBaseUrl();\n"
        "  return (\n"
        '    <section className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4">\n'
        f'      <h1 className="text-lg font-semibold">{title}</h1>\n'
        '      <p className="text-xs text-slate-400">API: {apiBaseLoading ? "(resolving...)" : apiBaseUrl}</p>\n'
        '      <p className="text-sm text-slate-200">This page is implemented and ready for project-specific content.</p>\n'
        '      <div className="rounded-md border border-slate-700 bg-slate-950/60 p-3 text-sm text-slate-300">\n'
        f"        Route: /{rel}\n"
        "      </div>\n"
        "    </section>\n"
        "  );\n"
        "}\n"
    )


def _render_implemented_page_content(app_root: Path, target: Path, rel: str) -> str:
    segments = [seg for seg in rel.split("/") if seg]
    title = " ".join(seg.replace("-", " ").replace("_", " ").title() for seg in segments)
    comp_name = _safe_component_name(segments)
    route_kind = _route_kind_from_segments(segments)
    entity_path = "/".join(segments[:-1]).strip("/") if len(segments) > 1 else (segments[0] if segments else "")
    helper_import = _api_base_helper_import_for_page(app_root, target)
    if entity_path and route_kind == "list":
        return _render_frontend_entity_list_page(
            component_name=comp_name,
            title=title,
            entity_path=entity_path,
            api_helper_import=helper_import,
        )
    if entity_path and route_kind == "detail":
        return _render_frontend_entity_detail_page(
            component_name=comp_name,
            title=title,
            entity_path=entity_path,
            api_helper_import=helper_import,
        )
    return _render_generic_page_scaffold(
        component_name=comp_name,
        title=title,
        rel=_frontend_route_from_page_rel(rel) or rel,
        api_helper_import=helper_import,
    )


def implement_page_scaffold(project_dir: Path, page_path: str) -> dict[str, Any]:
    app_root = _resolve_frontend_app_root(project_dir)
    raw = str(page_path or "").strip()
    rel = _canonicalize_page_path(raw)
    if not rel:
        return {
            "ok": False,
            "status": "invalid",
            "page_path": raw,
            "detail": "Invalid page path",
            "error": "Invalid page path",
            "changed_files": [],
        }
    if app_root is None:
        return {
            "ok": False,
            "status": "no_frontend",
            "page_path": rel,
            "detail": "Frontend structure not found",
            "error": "Frontend structure not found",
            "changed_files": [],
        }

    route_rel = _frontend_route_from_page_rel(rel)
    targets: list[Path] = []
    if route_rel:
        targets.append(app_root / route_rel / "page.tsx")
    targets.append(app_root / rel / "page.tsx")
    target = next((candidate for candidate in targets if candidate.exists()), targets[0] if targets else app_root / rel / "page.tsx")
    if not target.exists():
        return {
            "ok": False,
            "status": "not_found",
            "page_path": rel,
            "detail": f"Page not found: {rel}",
            "error": "Page not found",
            "changed_files": [],
        }

    before = target.read_text(encoding="utf-8")
    if not _is_placeholder_level_page(before):
        return {
            "ok": True,
            "status": "already_implemented",
            "page_path": rel,
            "detail": f"Page already implemented: {rel}",
            "error": "",
            "changed_files": [],
        }

    changed: list[str] = []
    _ensure_frontend_api_base_helper(app_root, changed, project_dir)
    _ensure_frontend_navigation_helper(app_root, changed, project_dir)
    _ensure_frontend_navigation_shell_upgrade(app_root, changed, project_dir)
    content = _render_implemented_page_content(app_root, target, rel)
    _write_if_changed(target, content, changed, project_dir)
    _register_frontend_nav_link(app_root, f"/{route_rel or rel}", changed, project_dir)
    return {
        "ok": True,
        "status": "implemented",
        "page_path": rel,
        "detail": f"Implemented page: {rel}",
        "error": "",
        "changed_files": changed,
    }


def _render_frontend_entity_list_page(
    *,
    component_name: str,
    title: str,
    entity_path: str,
    detail_link_mode: str = "path",
    detail_href_base: str | None = None,
    api_helper_import: str = "../_lib/apiBase",
) -> str:
    api_path = f"/{str(entity_path or '').strip('/')}"
    if _is_note_like_entity_path(entity_path):
        return _render_frontend_note_list_page(component_name=component_name, title=title, api_path=api_path, api_helper_import=api_helper_import)
    detail_base = detail_href_base or api_path
    link_expression = (
        f"`{detail_base}/${{String(item.id)}}`"
        if detail_link_mode != "query"
        else f"`{detail_base}?id=${{String(item.id)}}`"
    )
    return (
        '"use client";\n\n'
        'import Link from "next/link";\n'
        'import { useEffect, useState } from "react";\n'
        f'import {{ useApiBaseUrl }} from "{api_helper_import}";\n\n'
        "type EntityItem = Record<string, unknown> & { id?: number | string };\n\n"
        f"export default function {component_name}() {{\n"
        "  const [items, setItems] = useState<EntityItem[]>([]);\n"
        "  const [loading, setLoading] = useState(true);\n"
        "  const [error, setError] = useState(\"\");\n"
        "  const { apiBaseUrl, apiBaseLoading } = useApiBaseUrl();\n\n"
        "  useEffect(() => {\n"
        "    if (apiBaseLoading || !apiBaseUrl) {\n"
        "      setLoading(true);\n"
        "      return;\n"
        "    }\n"
        "    let mounted = true;\n"
        "    (async () => {\n"
        "      setLoading(true);\n"
        "      setError(\"\");\n"
        "      try {\n"
        f'        const response = await fetch(`${{apiBaseUrl}}{api_path}`, {{ cache: "no-store" }});\n'
        "        if (!response.ok) {\n"
        "          throw new Error(`HTTP ${response.status}`);\n"
        "        }\n"
        "        const payload = (await response.json()) as unknown;\n"
        "        const rows = Array.isArray(payload)\n"
        "          ? payload\n"
        "          : Array.isArray((payload as { items?: unknown[] }).items)\n"
        "            ? (payload as { items: unknown[] }).items\n"
        "            : [];\n"
        "        if (mounted) {\n"
        "          setItems(rows as EntityItem[]);\n"
        "        }\n"
        "      } catch (e) {\n"
        "        const message = e instanceof Error ? e.message : String(e || \"unknown error\");\n"
        "        if (mounted) {\n"
        "          setError(message);\n"
        "        }\n"
        "      } finally {\n"
        "        if (mounted) {\n"
        "          setLoading(false);\n"
        "        }\n"
        "      }\n"
        "    })();\n"
        "    return () => {\n"
        "      mounted = false;\n"
        "    };\n"
        "  }, [apiBaseLoading, apiBaseUrl]);\n\n"
        "  return (\n"
        '    <section className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4">\n'
        f'      <h1 className="text-lg font-semibold">{title}</h1>\n'
        '      <p className="text-xs text-slate-400">API: {apiBaseLoading ? "(resolving...)" : apiBaseUrl}</p>\n'
        "      {loading ? <p className=\"text-sm text-slate-300\">{apiBaseLoading ? \"Resolving API base...\" : \"Loading...\"}</p> : null}\n"
        "      {!loading && error ? <p className=\"text-sm text-rose-300\">Failed to load: {error}</p> : null}\n"
        "      {!loading && !error && items.length === 0 ? <p className=\"text-sm text-slate-300\">No items found.</p> : null}\n"
        "      {!loading && !error && items.length > 0 ? (\n"
        '        <ul className="space-y-2 text-sm">\n'
        "          {items.map((item, index) => (\n"
        '            <li key={String(item.id ?? index)} className="rounded-md border border-slate-700 p-2">\n'
        "              <div className=\"font-medium\">#{String(item.id ?? index)}</div>\n"
        "              <pre className=\"mt-1 overflow-x-auto text-xs text-slate-300\">{JSON.stringify(item, null, 2)}</pre>\n"
        "              {item.id !== undefined ? (\n"
        f"                <Link href={{{link_expression}}} className=\"mt-2 inline-block text-xs text-cyan-300 underline\">\n"
        "                  Open detail\n"
        "                </Link>\n"
        "              ) : null}\n"
        "            </li>\n"
        "          ))}\n"
        "        </ul>\n"
        "      ) : null}\n"
        "    </section>\n"
        "  );\n"
        "}\n"
    )


def _render_frontend_entity_detail_page(
    *,
    component_name: str,
    title: str,
    entity_path: str,
    id_mode: str = "path",
    api_helper_import: str = "../../_lib/apiBase",
) -> str:
    api_path = f"/{str(entity_path or '').strip('/')}"
    if _is_note_like_entity_path(entity_path):
        return _render_frontend_note_detail_page(
            component_name=component_name,
            title=title,
            api_path=api_path,
            id_mode=id_mode,
            api_helper_import=api_helper_import,
        )
    id_source = (
        'const id = String(searchParams.get("id") || "").trim();'
        if id_mode == "query"
        else 'const id = String(params.id || "").trim();'
    )
    imports = (
        'import { useSearchParams } from "next/navigation";\n'
        if id_mode == "query"
        else 'import { useParams } from "next/navigation";\n'
    )
    hook = "const searchParams = useSearchParams();" if id_mode == "query" else "const params = useParams();"
    return (
        '"use client";\n\n'
        "import { useEffect, useState } from \"react\";\n"
        f'import {{ useApiBaseUrl }} from "{api_helper_import}";\n'
        f"{imports}\n"
        "type EntityItem = Record<string, unknown>;\n\n"
        f"export default function {component_name}() {{\n"
        f"  {hook}\n"
        f"  {id_source}\n"
        "  const [item, setItem] = useState<EntityItem | null>(null);\n"
        "  const [loading, setLoading] = useState(true);\n"
        "  const [notFound, setNotFound] = useState(false);\n"
        "  const [error, setError] = useState(\"\");\n"
        "  const { apiBaseUrl, apiBaseLoading } = useApiBaseUrl();\n\n"
        "  useEffect(() => {\n"
        "    if (!id) {\n"
        "      setLoading(false);\n"
        "      setNotFound(true);\n"
        "      return;\n"
        "    }\n"
        "    if (apiBaseLoading || !apiBaseUrl) {\n"
        "      setLoading(true);\n"
        "      return;\n"
        "    }\n"
        "    let mounted = true;\n"
        "    (async () => {\n"
        "      setLoading(true);\n"
        "      setNotFound(false);\n"
        "      setError(\"\");\n"
        "      try {\n"
        f'        const response = await fetch(`${{apiBaseUrl}}{api_path}/${{id}}`, {{ cache: "no-store" }});\n'
        "        if (response.status === 404) {\n"
        "          if (mounted) setNotFound(true);\n"
        "          return;\n"
        "        }\n"
        "        if (!response.ok) {\n"
        "          throw new Error(`HTTP ${response.status}`);\n"
        "        }\n"
        "        const payload = (await response.json()) as EntityItem;\n"
        "        if (mounted) setItem(payload);\n"
        "      } catch (e) {\n"
        "        const message = e instanceof Error ? e.message : String(e || \"unknown error\");\n"
        "        if (mounted) setError(message);\n"
        "      } finally {\n"
        "        if (mounted) setLoading(false);\n"
        "      }\n"
        "    })();\n"
        "    return () => {\n"
        "      mounted = false;\n"
        "    };\n"
        "  }, [apiBaseLoading, apiBaseUrl, id]);\n\n"
        "  return (\n"
        '    <section className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4">\n'
        f'      <h1 className="text-lg font-semibold">{title} Detail</h1>\n'
        "      {!id ? <p className=\"text-sm text-slate-300\">Missing item id.</p> : null}\n"
        "      {loading ? <p className=\"text-sm text-slate-300\">{apiBaseLoading ? \"Resolving API base...\" : \"Loading...\"}</p> : null}\n"
        "      {!loading && notFound ? <p className=\"text-sm text-slate-300\">Item not found.</p> : null}\n"
        "      {!loading && error ? <p className=\"text-sm text-rose-300\">Failed to load: {error}</p> : null}\n"
        "      {!loading && !notFound && !error && item ? (\n"
        "        <pre className=\"overflow-x-auto text-xs text-slate-300\">{JSON.stringify(item, null, 2)}</pre>\n"
        "      ) : null}\n"
        "    </section>\n"
        "  );\n"
        "}\n"
    )


def _is_note_like_entity_path(entity_path: str) -> bool:
    normalized = str(entity_path or "").strip("/").lower()
    if not normalized:
        return False
    leaf = normalized.split("/")[-1]
    return leaf in {"note", "notes", "memo", "memos"}


def _render_frontend_note_list_page(
    *,
    component_name: str,
    title: str,
    api_path: str,
    api_helper_import: str,
) -> str:
    return (
        '"use client";\n\n'
        'import Link from "next/link";\n'
        'import { FormEvent, useEffect, useState } from "react";\n'
        f'import {{ useApiBaseUrl }} from "{api_helper_import}";\n\n'
        "type NoteItem = Record<string, unknown> & { id?: number | string; title?: string; content?: string };\n\n"
        "function extractItems(payload: unknown): NoteItem[] {\n"
        "  if (Array.isArray(payload)) return payload as NoteItem[];\n"
        "  if (payload && typeof payload === \"object\" && Array.isArray((payload as { items?: unknown[] }).items)) {\n"
        "    return ((payload as { items: unknown[] }).items ?? []) as NoteItem[];\n"
        "  }\n"
        "  return [];\n"
        "}\n\n"
        "function errorMessage(error: unknown): string {\n"
        "  if (error instanceof Error) return error.message;\n"
        '  return String(error || "Unknown error");\n'
        "}\n\n"
        "function mergeNoteItem(current: NoteItem[], incoming: NoteItem): NoteItem[] {\n"
        "  const nextId = String(incoming.id ?? \"\").trim();\n"
        "  if (!nextId) {\n"
        "    return [incoming, ...current];\n"
        "  }\n"
        "  const filtered = current.filter((item) => String(item.id ?? \"\").trim() !== nextId);\n"
        "  return [incoming, ...filtered];\n"
        "}\n\n"
        f"export default function {component_name}() {{\n"
        "  const [items, setItems] = useState<NoteItem[]>([]);\n"
        "  const [titleInput, setTitleInput] = useState(\"\");\n"
        "  const [contentInput, setContentInput] = useState(\"\");\n"
        "  const [loading, setLoading] = useState(true);\n"
        "  const [saving, setSaving] = useState(false);\n"
        "  const [error, setError] = useState(\"\");\n"
        "  const [message, setMessage] = useState(\"\");\n"
        "  const { apiBaseUrl, apiBaseLoading } = useApiBaseUrl();\n\n"
        "  async function refreshList() {\n"
        "    if (!apiBaseUrl) return;\n"
        "    setLoading(true);\n"
        "    setError(\"\");\n"
        "    try {\n"
        f'      const response = await fetch(`${{apiBaseUrl}}{api_path}`, {{ cache: "no-store" }});\n'
        "      if (!response.ok) {\n"
        "        throw new Error(`Failed to load notes (HTTP ${response.status})`);\n"
        "      }\n"
        "      setItems(extractItems(await response.json()));\n"
        "    } catch (error) {\n"
        "      setItems([]);\n"
        "      setError(errorMessage(error));\n"
        "    } finally {\n"
        "      setLoading(false);\n"
        "    }\n"
        "  }\n\n"
        "  useEffect(() => {\n"
        "    if (apiBaseLoading || !apiBaseUrl) return;\n"
        "    refreshList().catch(() => {\n"
        "      // handled in refreshList\n"
        "    });\n"
        "  }, [apiBaseLoading, apiBaseUrl]);\n\n"
        "  async function onCreate(event: FormEvent<HTMLFormElement>) {\n"
        "    event.preventDefault();\n"
        "    const title = titleInput.trim();\n"
        "    if (!title) {\n"
        '      setError("Title is required.");\n'
        "      return;\n"
        "    }\n"
        "    if (!apiBaseUrl) {\n"
        '      setError("API base is not ready.");\n'
        "      return;\n"
        "    }\n"
        "    setSaving(true);\n"
        "    setError(\"\");\n"
        "    setMessage(\"\");\n"
        "    try {\n"
        f'      const response = await fetch(`${{apiBaseUrl}}{api_path}`, {{\n'
        '        method: "POST",\n'
        '        headers: {{ "Content-Type": "application/json" }},\n'
        "        body: JSON.stringify({ title, content: contentInput }),\n"
        "      });\n"
        "      if (!response.ok) {\n"
        "        throw new Error(`Failed to create note (HTTP ${response.status})`);\n"
        "      }\n"
        "      const created = (await response.json()) as NoteItem;\n"
        "      setTitleInput(\"\");\n"
        "      setContentInput(\"\");\n"
        '      setMessage("Note created.");\n'
        "      setItems((prev) => mergeNoteItem(prev, created));\n"
        "      refreshList().catch(() => {\n"
        "        // keep optimistic update even if refresh fails\n"
        "      });\n"
        "    } catch (error) {\n"
        "      setError(errorMessage(error));\n"
        "    } finally {\n"
        "      setSaving(false);\n"
        "    }\n"
        "  }\n\n"
        "  return (\n"
        '    <section className="space-y-4 rounded-xl border border-slate-800 bg-slate-900/60 p-4">\n'
        f'      <h1 className="text-lg font-semibold">{title}</h1>\n'
        '      <p className="text-xs text-slate-300">API: {apiBaseLoading ? "(resolving...)" : apiBaseUrl}</p>\n'
        '      <form onSubmit={onCreate} className="space-y-3 rounded-lg border border-slate-800 bg-slate-950/70 p-3">\n'
        '        <h2 className="text-sm font-semibold text-slate-100">Create note</h2>\n'
        '        <input value={titleInput} onChange={(event) => setTitleInput(event.target.value)} placeholder="Title" className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100" />\n'
        '        <textarea value={contentInput} onChange={(event) => setContentInput(event.target.value)} placeholder="Content" className="min-h-24 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100" />\n'
        '        <div className="flex items-center gap-2">\n'
        '          <button type="submit" disabled={saving || apiBaseLoading} className="rounded-md bg-emerald-400 px-3 py-2 text-sm font-semibold text-emerald-950 disabled:opacity-60">\n'
        '            {saving ? "Creating..." : "Create note"}\n'
        "          </button>\n"
        '          <button type="button" onClick={() => { setTitleInput(""); setContentInput(""); setError(""); setMessage(""); }} className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200">\n'
        "            Cancel\n"
        "          </button>\n"
        "        </div>\n"
        '        {message ? <p className="text-xs text-emerald-300">{message}</p> : null}\n'
        "      </form>\n"
        "      {loading ? <p className=\"text-sm text-slate-300\">{apiBaseLoading ? \"Resolving API base...\" : \"Loading notes...\"}</p> : null}\n"
        "      {!loading && error ? <p className=\"text-sm text-rose-300\">Failed to load: {error}</p> : null}\n"
        "      {!loading && !error && items.length === 0 ? <p className=\"text-sm text-slate-300\">No notes yet.</p> : null}\n"
        "      {!loading && !error && items.length > 0 ? (\n"
        '        <ul className="space-y-2 text-sm">\n'
        "          {items.map((item, index) => (\n"
        '            <li key={String(item.id ?? index)} className="rounded-md border border-slate-700 p-3">\n'
        '              <div className="font-medium text-slate-100">{String(item.title || `Untitled #${item.id ?? index}`)}</div>\n'
        '              <p className="mt-1 text-xs text-slate-300">{String(item.content || "(no content)")}</p>\n'
        "              {item.id !== undefined ? (\n"
        '                <Link href={`/notes/${String(item.id)}`} className="mt-2 inline-block text-xs text-cyan-300 underline">\n'
        "                  Open detail\n"
        "                </Link>\n"
        "              ) : null}\n"
        "            </li>\n"
        "          ))}\n"
        "        </ul>\n"
        "      ) : null}\n"
        "    </section>\n"
        "  );\n"
        "}\n"
    )


def _render_frontend_note_detail_page(
    *,
    component_name: str,
    title: str,
    api_path: str,
    id_mode: str,
    api_helper_import: str,
) -> str:
    imports = (
        'import { useSearchParams } from "next/navigation";\n'
        if id_mode == "query"
        else 'import { useParams, useRouter } from "next/navigation";\n'
    )
    hook = "const searchParams = useSearchParams();" if id_mode == "query" else "const params = useParams();\n  const router = useRouter();"
    id_source = (
        'const id = String(searchParams.get("id") || "").trim();'
        if id_mode == "query"
        else 'const id = String(params.id || "").trim();'
    )
    delete_redirect = (
        '      if (typeof router !== "undefined") {\n'
        '        router.push("/notes");\n'
        "        router.refresh();\n"
        "      }\n"
        if id_mode != "query"
        else ""
    )

    return (
        '"use client";\n\n'
        "import { FormEvent, useEffect, useState } from \"react\";\n"
        f'import {{ useApiBaseUrl }} from "{api_helper_import}";\n'
        f"{imports}\n"
        "type NoteItem = Record<string, unknown> & { title?: string; content?: string };\n\n"
        f"export default function {component_name}() {{\n"
        f"  {hook}\n"
        f"  {id_source}\n"
        "  const [item, setItem] = useState<NoteItem | null>(null);\n"
        "  const [titleInput, setTitleInput] = useState(\"\");\n"
        "  const [contentInput, setContentInput] = useState(\"\");\n"
        "  const [loading, setLoading] = useState(true);\n"
        "  const [saving, setSaving] = useState(false);\n"
        "  const [deleting, setDeleting] = useState(false);\n"
        "  const [notFound, setNotFound] = useState(false);\n"
        "  const [error, setError] = useState(\"\");\n"
        "  const [message, setMessage] = useState(\"\");\n"
        "  const { apiBaseUrl, apiBaseLoading } = useApiBaseUrl();\n\n"
        "  async function loadItem() {\n"
        "    if (!apiBaseUrl || !id) return;\n"
        "    setLoading(true);\n"
        "    setError(\"\");\n"
        "    setNotFound(false);\n"
        "    try {\n"
        f'      const response = await fetch(`${{apiBaseUrl}}{api_path}/${{id}}`, {{ cache: "no-store" }});\n'
        "      if (response.status === 404) {\n"
        "        setNotFound(true);\n"
        "        setItem(null);\n"
        "        return;\n"
        "      }\n"
        "      if (!response.ok) {\n"
        "        throw new Error(`Failed to load note (HTTP ${response.status})`);\n"
        "      }\n"
        "      const payload = (await response.json()) as NoteItem;\n"
        "      setItem(payload);\n"
        "      setTitleInput(String(payload.title || \"\"));\n"
        "      setContentInput(String(payload.content || \"\"));\n"
        "    } catch (error) {\n"
        "      const message = error instanceof Error ? error.message : String(error || \"Unknown error\");\n"
        "      setError(message);\n"
        "    } finally {\n"
        "      setLoading(false);\n"
        "    }\n"
        "  }\n\n"
        "  useEffect(() => {\n"
        "    if (!id) {\n"
        "      setNotFound(true);\n"
        "      setLoading(false);\n"
        "      return;\n"
        "    }\n"
        "    if (apiBaseLoading || !apiBaseUrl) return;\n"
        "    loadItem().catch(() => {\n"
        "      // handled in loadItem\n"
        "    });\n"
        "  }, [apiBaseLoading, apiBaseUrl, id]);\n\n"
        "  async function onSubmit(event: FormEvent<HTMLFormElement>) {\n"
        "    event.preventDefault();\n"
        "    const title = titleInput.trim();\n"
        "    if (!title) {\n"
        "      setError(\"Title is required.\");\n"
        "      return;\n"
        "    }\n"
        "    if (!apiBaseUrl || !id) {\n"
        "      setError(\"API base or id is not ready.\");\n"
        "      return;\n"
        "    }\n"
        "    setSaving(true);\n"
        "    setError(\"\");\n"
        "    setMessage(\"\");\n"
        "    try {\n"
        f'      let response = await fetch(`${{apiBaseUrl}}{api_path}/${{id}}`, {{\n'
        '        method: "PUT",\n'
        '        headers: { "Content-Type": "application/json" },\n'
        "        body: JSON.stringify({ title, content: contentInput }),\n"
        "      });\n"
        "      if (response.status === 405) {\n"
        f'        response = await fetch(`${{apiBaseUrl}}{api_path}/${{id}}`, {{\n'
        '          method: "PATCH",\n'
        '          headers: { "Content-Type": "application/json" },\n'
        "          body: JSON.stringify({ title, content: contentInput }),\n"
        "        });\n"
        "      }\n"
        "      if (!response.ok) {\n"
        "        throw new Error(`Failed to update note (HTTP ${response.status})`);\n"
        "      }\n"
        "      const updated = (await response.json()) as NoteItem;\n"
        "      setItem(updated);\n"
        "      setTitleInput(String(updated.title || \"\"));\n"
        "      setContentInput(String(updated.content || \"\"));\n"
        "      setMessage(\"Note updated.\");\n"
        "      loadItem().catch(() => {\n"
        "        // keep optimistic update even if refresh fails\n"
        "      });\n"
        "    } catch (error) {\n"
        "      const message = error instanceof Error ? error.message : String(error || \"Unknown error\");\n"
        "      setError(message);\n"
        "    } finally {\n"
        "      setSaving(false);\n"
        "    }\n"
        "  }\n\n"
        "  async function onDelete() {\n"
        "    if (!apiBaseUrl || !id) {\n"
        "      setError(\"API base or id is not ready.\");\n"
        "      return;\n"
        "    }\n"
        "    if (!confirm(\"Delete this note?\")) return;\n"
        "    setDeleting(true);\n"
        "    setError(\"\");\n"
        "    setMessage(\"\");\n"
        "    try {\n"
        f'      const response = await fetch(`${{apiBaseUrl}}{api_path}/${{id}}`, {{ method: "DELETE" }});\n'
        "      if (!response.ok) {\n"
        "        throw new Error(`Failed to delete note (HTTP ${response.status})`);\n"
        "      }\n"
        f"{delete_redirect}"
        "      setMessage(\"Note deleted.\");\n"
        "      setNotFound(true);\n"
        "      setItem(null);\n"
        "    } catch (error) {\n"
        "      const message = error instanceof Error ? error.message : String(error || \"Unknown error\");\n"
        "      setError(message);\n"
        "    } finally {\n"
        "      setDeleting(false);\n"
        "    }\n"
        "  }\n\n"
        "  return (\n"
        '    <section className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4">\n'
        f'      <h1 className="text-lg font-semibold">{title} Detail</h1>\n'
        "      {!id ? <p className=\"text-sm text-slate-300\">Missing item id.</p> : null}\n"
        "      {loading ? <p className=\"text-sm text-slate-300\">{apiBaseLoading ? \"Resolving API base...\" : \"Loading...\"}</p> : null}\n"
        "      {!loading && notFound ? <p className=\"text-sm text-slate-300\">Item not found.</p> : null}\n"
        "      {!loading && error ? <p className=\"text-sm text-rose-300\">Failed to load: {error}</p> : null}\n"
        "      {!loading && !notFound ? (\n"
        "        <form onSubmit={onSubmit} className=\"space-y-3 rounded-md border border-slate-700 p-3\">\n"
        "          <input value={titleInput} onChange={(event) => setTitleInput(event.target.value)} className=\"w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100\" />\n"
        "          <textarea value={contentInput} onChange={(event) => setContentInput(event.target.value)} className=\"min-h-24 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100\" />\n"
        "          <div className=\"flex items-center gap-2\">\n"
        "            <button type=\"submit\" disabled={saving} className=\"rounded-md bg-emerald-400 px-3 py-2 text-sm font-semibold text-emerald-950 disabled:opacity-60\">\n"
        "              {saving ? \"Saving...\" : \"Save changes\"}\n"
        "            </button>\n"
        "            <button type=\"button\" onClick={onDelete} disabled={deleting} className=\"rounded-md border border-rose-500/50 px-3 py-2 text-sm text-rose-200 disabled:opacity-60\">\n"
        "              {deleting ? \"Deleting...\" : \"Delete note\"}\n"
        "            </button>\n"
        "          </div>\n"
        "          {message ? <p className=\"text-xs text-emerald-300\">{message}</p> : null}\n"
        "        </form>\n"
        "      ) : null}\n"
        "    </section>\n"
        "  );\n"
        "}\n"
    )


def _normalize_field_entries(fields: list[dict[str, Any]]) -> list[tuple[str, str]]:
    normalized: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in fields:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        ftype = str(item.get("type") or "").strip().lower()
        if not name or not ftype:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append((name, ftype))
    return normalized


def _python_type(field_type: str) -> str:
    mapping = {
        "string": "str",
        "int": "int",
        "float": "float",
        "bool": "bool",
        "datetime": "datetime",
    }
    return mapping.get(str(field_type).strip().lower(), "str")


def _write_if_changed(path: Path, content: str, changed: list[str], project_dir: Path) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    if existing == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    rel = str(path.relative_to(project_dir)).replace("\\", "/")
    if rel not in changed:
        changed.append(rel)


def apply_entity_fields_to_scaffold(project_dir: Path, entity_name: str, fields: list[dict[str, Any]]) -> list[str]:
    """
    Update model/schema placeholders with field metadata for an existing entity scaffold.
    Returns files that were changed. Frontend-only projects return [].
    """
    if not _has_backend_structure(project_dir):
        return []
    backend_app_root = _resolve_backend_app_root(project_dir)
    if backend_app_root is None:
        return []
    class_name, slug, _ = _entity_identity(entity_name)
    if not class_name:
        return []

    normalized_fields = _normalize_field_entries(fields)
    need_datetime = any(ftype == "datetime" for _, ftype in normalized_fields)
    field_lines = [f"    {name}: {_python_type(ftype)}" for name, ftype in normalized_fields]
    body = "\n".join(field_lines) if field_lines else "    pass"
    prefix = "from datetime import datetime\n\n" if need_datetime else ""

    model_content = f"{prefix}class {class_name}:\n{body}\n"
    schema_content = (
        f"{prefix}class {class_name}Create:\n"
        f"{body}\n\n"
        f"class {class_name}Read:\n"
        f"{body}\n"
    )

    changed: list[str] = []
    _write_if_changed(backend_app_root / "models" / f"{slug}.py", model_content, changed, project_dir)
    _write_if_changed(backend_app_root / "schemas" / f"{slug}.py", schema_content, changed, project_dir)
    return changed


def validate_generated_project_structure(
    project_dir: Path,
    *,
    app_shape: str = "",
    template_name: str = "",
) -> dict[str, Any]:
    root = project_dir.expanduser().resolve()
    shape = str(app_shape or "").strip().lower()
    template = str(template_name or "").strip().lower()
    is_fullstack = shape == "fullstack" or template == "fullstack-ddd"

    # fullstack-ddd contract is strict and intentionally backend-prefixed.
    if is_fullstack:
        detect = detect_backend_asgi_entry(
            root,
            allowed_layouts=("fullstack",),
            prefer_layout="fullstack",
        )
        backend_main = root / "backend" / "app" / "main.py"
        backend_requirements = root / "backend" / "requirements.txt"
        frontend_dir = root / "frontend"
        backend_ok = bool(detect.get("ok"))
        requirements_ok = backend_requirements.exists()
        frontend_ok = frontend_dir.is_dir()
        root_launcher_ok = not (root / "main.py").exists()

        reasons: list[str] = []
        if not backend_ok:
            reasons.extend(
                [
                    str(item).strip()
                    for item in str(detect.get("failure_reason") or "").split(";")
                    if str(item).strip()
                ]
            )
        if not frontend_ok:
            reasons.append("missing frontend directory: frontend")
        if not root_launcher_ok:
            reasons.append("root main.py is not allowed for fullstack template")

        if reasons:
            return {
                "ok": False,
                "failure_class": "generation-error",
                "reason": "invalid fullstack-ddd structure: " + "; ".join(reasons),
                "entrypoint": "app.main:app",
                "backend": "OK" if backend_ok else "MISSING",
                "frontend": "OK" if frontend_ok else "MISSING",
                "requirements": "OK" if requirements_ok else "MISSING",
            }
        return {
            "ok": True,
            "failure_class": "",
            "reason": "",
            "entrypoint": "app.main:app",
            "backend": "OK",
            "frontend": "OK",
            "requirements": "OK",
        }

    # fastapi / fastapi-ddd: accept either root contract or backend-prefixed contract.
    if template in {"fastapi", "fastapi-ddd"}:
        detect = detect_backend_asgi_entry(
            root,
            allowed_layouts=("flat", "fullstack"),
            prefer_layout="flat",
        )
        if not bool(detect.get("ok")):
            reasons: list[str] = [
                str(item).strip()
                for item in str(detect.get("failure_reason") or "").split(";")
                if str(item).strip()
            ]
            if not reasons:
                reasons = [
                    "missing backend contract: expected (app/main.py + requirements.txt) "
                    "or (backend/app/main.py + backend/requirements.txt)"
                ]
            return {
                "ok": False,
                "failure_class": "generation-error",
                "reason": f"invalid {template} structure: " + "; ".join(reasons),
                "entrypoint": "app.main:app",
                "backend": "MISSING",
                "frontend": "N/A",
                "requirements": "MISSING",
            }
        return {
            "ok": True,
            "failure_class": "",
            "reason": "",
            "entrypoint": "app.main:app",
            "backend": "OK",
            "frontend": "N/A",
            "requirements": "OK",
        }

    # data-tool has its own template contract; do not apply fastapi/root checks.
    if template == "data-tool":
        backend_main = root / "backend" / "app" / "main.py"
        backend_requirements = root / "backend" / "requirements.txt"
        frontend_dir = root / "frontend"
        frontend_package = root / "frontend" / "package.json"
        frontend_page = root / "frontend" / "app" / "page.tsx"
        required: list[tuple[Path, str]] = [
            (backend_main, "missing backend entrypoint: backend/app/main.py"),
            (backend_requirements, "missing requirements: backend/requirements.txt"),
            (frontend_dir, "missing frontend directory: frontend"),
            (frontend_package, "missing frontend package manifest: frontend/package.json"),
            (frontend_page, "missing frontend page: frontend/app/page.tsx"),
        ]
        reasons = [msg for path, msg in required if not path.exists()]
        backend_ok = backend_main.exists()
        requirements_ok = backend_requirements.exists()
        frontend_ok = frontend_dir.exists() and frontend_package.exists() and frontend_page.exists()
        if reasons:
            return {
                "ok": False,
                "failure_class": "generation-error",
                "reason": "invalid data-tool structure: " + "; ".join(reasons),
                "entrypoint": "app.main:app",
                "backend": "OK" if backend_ok else "MISSING",
                "frontend": "OK" if frontend_ok else "MISSING",
                "requirements": "OK" if requirements_ok else "MISSING",
            }
        return {
            "ok": True,
            "failure_class": "",
            "reason": "",
            "entrypoint": "app.main:app",
            "backend": "OK",
            "frontend": "OK",
            "requirements": "OK",
        }

    if template == "internal-tool":
        backend_main = root / "backend" / "app" / "main.py"
        backend_requirements = root / "backend" / "requirements.txt"
        frontend_dir = root / "frontend"
        frontend_package = root / "frontend" / "package.json"
        frontend_page = root / "frontend" / "app" / "page.tsx"
        required: list[tuple[Path, str]] = [
            (backend_main, "missing backend entrypoint: backend/app/main.py"),
            (backend_requirements, "missing requirements: backend/requirements.txt"),
            (frontend_dir, "missing frontend directory: frontend"),
            (frontend_package, "missing frontend package manifest: frontend/package.json"),
            (frontend_page, "missing frontend page: frontend/app/page.tsx"),
        ]
        reasons = [msg for path, msg in required if not path.exists()]
        backend_ok = backend_main.exists()
        requirements_ok = backend_requirements.exists()
        frontend_ok = frontend_dir.exists() and frontend_package.exists() and frontend_page.exists()
        if reasons:
            return {
                "ok": False,
                "failure_class": "generation-error",
                "reason": "invalid internal-tool structure: " + "; ".join(reasons),
                "entrypoint": "app.main:app",
                "backend": "OK" if backend_ok else "MISSING",
                "frontend": "OK" if frontend_ok else "MISSING",
                "requirements": "OK" if requirements_ok else "MISSING",
            }
        return {
            "ok": True,
            "failure_class": "",
            "reason": "",
            "entrypoint": "app.main:app",
            "backend": "OK",
            "frontend": "OK",
            "requirements": "OK",
        }

    requires_backend_contract = shape == "backend" or template in {"worker-api"}
    if not requires_backend_contract:
        return {
            "ok": True,
            "failure_class": "",
            "reason": "",
            "entrypoint": "",
            "backend": "N/A",
            "frontend": "OK" if (root / "frontend").is_dir() or (root / "app").is_dir() else "N/A",
            "requirements": "N/A",
        }

    backend_main = root / "app" / "main.py"
    backend_requirements = root / "requirements.txt"
    backend_ok = backend_main.exists()
    requirements_ok = backend_requirements.exists()
    reasons = []
    if not backend_ok:
        reasons.append("missing backend entrypoint: app/main.py")
    if not requirements_ok:
        reasons.append("missing requirements: requirements.txt")
    if backend_ok and not has_fastapi_app_declaration(backend_main):
        reasons.append("invalid FastAPI app declaration in: app/main.py")
    if reasons:
        return {
            "ok": False,
            "failure_class": "generation-error",
            "reason": "invalid backend structure: " + "; ".join(reasons),
            "entrypoint": "app.main:app",
            "backend": "OK" if backend_ok else "MISSING",
            "frontend": "N/A",
            "requirements": "OK" if requirements_ok else "MISSING",
        }
    return {
        "ok": True,
        "failure_class": "",
        "reason": "",
        "entrypoint": "app.main:app",
        "backend": "OK",
        "frontend": "N/A",
        "requirements": "OK",
    }


def _normalize_spec_seed(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    payload: dict[str, Any] = {}
    for key in ("entities", "api_endpoints", "frontend_pages"):
        value = raw.get(key)
        if isinstance(value, list):
            payload[key] = value
    return payload


def _parse_api_endpoint_hint(raw: str) -> tuple[str, str]:
    text = str(raw or "").strip()
    if not text:
        return "", ""
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        return "", ""
    method = str(parts[0]).strip().upper()
    path = _canonicalize_api_path(parts[1])
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"} or not path:
        return "", ""
    return method, path


def _apply_spec_scaffolds(project_dir: Path, spec: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    entities_raw = spec.get("entities") if isinstance(spec.get("entities"), list) else []
    for item in entities_raw:
        if not isinstance(item, dict):
            continue
        entity_name = str(item.get("name") or "").strip()
        if not entity_name:
            continue
        changed.extend(apply_entity_scaffold(project_dir, entity_name))
        fields = item.get("fields")
        if isinstance(fields, list):
            changed.extend(apply_entity_fields_to_scaffold(project_dir, entity_name, fields))
        changed.extend(apply_frontend_page_scaffold(project_dir, entity_name))

    api_endpoints = spec.get("api_endpoints") if isinstance(spec.get("api_endpoints"), list) else []
    for endpoint in api_endpoints:
        method, path = _parse_api_endpoint_hint(str(endpoint or ""))
        if method and path:
            changed.extend(apply_api_scaffold(project_dir, method, path))

    frontend_pages = spec.get("frontend_pages") if isinstance(spec.get("frontend_pages"), list) else []
    for page in frontend_pages:
        changed.extend(apply_page_scaffold(project_dir, str(page or "")))

    # Preserve ordering while deduplicating.
    unique: list[str] = []
    seen: set[str] = set()
    for path in changed:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


# -----------------------------
# Public entrypoint (CLI calls this)
# -----------------------------
def generate_project(idea: str, opt: GenerateOptions):
    """
    CLI entrypoint.
    - builds prompt
    - generates/repairs spec
    - applies deterministic template if selected
    - writes project to disk
    returns: Path to generated project root
    """
    # Deterministic templates should not require model access.
    if opt.template in {"fastapi-ddd", "fullstack-ddd", "nextjs", "internal-tool", "worker-api", "data-tool"}:
        project_name = (opt.name or "archmind_project").strip() or "archmind_project"
        spec = fallback_spec(project_name=project_name)
    else:
        # prompt text
        prompt_text = ""
        if getattr(opt, "prompt", None):
            try:
                prompt_text = Path(opt.prompt).read_text(encoding="utf-8")
            except FileNotFoundError:
                prompt_text = str(opt.prompt)

        if not prompt_text.strip():
            # minimal prompt: model output can be unreliable; templates may override anyway
            prompt_text = (
                "Return a JSON object with keys: project_name, summary, directories(list), files(object path->content). "
                "files must be string contents. Do not include markdown."
            )

        spec = generate_valid_spec(prompt_text, idea, opt)
    spec_seed = _normalize_spec_seed(getattr(opt, "project_spec", None))
    if spec_seed:
        spec.update(spec_seed)
    spec = apply_template(spec, opt)
    project_dir = write_project(spec, opt)
    _apply_spec_scaffolds(project_dir, spec)
    apply_modules_to_project(project_dir, opt.template, list(getattr(opt, "modules", []) or []))
    structure_check = validate_generated_project_structure(project_dir, template_name=opt.template)
    if not bool(structure_check.get("ok")):
        raise RuntimeError(f"generation-error: {structure_check.get('reason') or 'invalid project structure'}")
    return project_dir
