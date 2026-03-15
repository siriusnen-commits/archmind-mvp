# src/archmind/generator.py
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional

import requests

from .templates.fastapi import enforce_fastapi_runtime
from .templates.fastapi_ddd import enforce_fastapi_ddd
from .templates.nextjs import enforce_nextjs_runtime
from .templates.internal_tool import enforce_internal_tool
from .templates.worker_api import enforce_worker_api
from .templates.data_tool import enforce_data_tool

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
    """
    Ask the model to repair invalid JSON. Returns a string that should be valid JSON.
    """
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
    backend_root = project_dir / "app"
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

        env_example = project_dir / ".env.example"
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
    spec = apply_template(spec, opt)
    project_dir = write_project(spec, opt)
    apply_modules_to_project(project_dir, opt.template, list(getattr(opt, "modules", []) or []))
    return project_dir
