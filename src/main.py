from __future__ import annotations

from pathlib import Path
import os
import json
import argparse
import requests
from typing import Any, Dict, List, Tuple

PROMPT_PATH = Path("docs/architecture_prompt.md")
INPUT_PATH = Path("examples/sample_input.txt")

OLLAMA_BASE_URL = os.getenv("ARCHMIND_OLLAMA_BASE_URL", "http://localhost:11434")
MODEL = os.getenv("ARCHMIND_MODEL", "llama3:latest")
TIMEOUT = 240

GENERATED_ROOT = Path("generated")
DEBUG_RAW_OUTPUT = Path("examples/last_raw_output.txt")

# ---- Validation Rules ----
# Common Python stdlib modules that must NOT appear in requirements/dependencies
STD_LIB_BLOCKLIST = {
    "sqlite3", "json", "os", "sys", "pathlib", "datetime", "time", "re",
    "typing", "subprocess", "logging", "uuid", "math", "random", "functools",
    "itertools", "collections", "statistics", "http", "urllib", "csv", "hashlib",
    "base64", "dataclasses", "enum", "threading", "multiprocessing"
}

REQUIRED_FILES = {"README.md", "requirements.txt", "main.py"}  # must exist at project root
MAX_RETRIES = 2

def inject_required_files(files: Dict[str, str], project_name: str) -> Dict[str, str]:
    """
    FastAPI template is enforced.
    Model output is ignored for runtime-critical files.
    """

    # 🔒 FORCE FastAPI requirements
    files["requirements.txt"] = (
        "fastapi==0.115.0\n"
        "uvicorn[standard]==0.30.6\n"
    )

    # 🔒 FORCE main.py (FastAPI)
    files["main.py"] = (
        "import os\n"
        "from fastapi import FastAPI\n\n"
        "app = FastAPI()\n\n"
        "@app.get('/')\n"
        "def health():\n"
        "    return {'status': 'ok'}\n\n"
        "if __name__ == '__main__':\n"
        "    import uvicorn\n"
        "    host = os.getenv('HOST', '0.0.0.0')\n"
        "    port = int(os.getenv('PORT', '8000'))\n"
        "    uvicorn.run('main:app', host=host, port=port, reload=True)\n"
    )

    # README.md
    if not files.get("README.md", "").strip():
        files["README.md"] = (
            f"# {project_name}\n\n"
            "## Setup\n"
            "```bash\n"
            "python3 -m venv .venv\n"
            "source .venv/bin/activate\n"
            "python -m pip install -r requirements.txt\n"
            "```\n\n"
            "## Run\n"
            "```bash\n"
            "PORT=8000 python main.py\n"
            "```\n"
        )

    return files

    # main.py
    if not files.get("main.py", "").strip():
        files["main.py"] = (
            "import os\n"
            "from flask import Flask\n\n"
            "app = Flask(__name__)\n\n"
            "@app.get('/')\n"
            "def health():\n"
            "    return {'status': 'ok'}\n\n"
            "if __name__ == '__main__':\n"
            "    port = int(os.getenv('PORT', '8000'))\n"
            "    app.run(host='0.0.0.0', port=port, debug=True)\n"
        )

    # README.md
    if not files.get("README.md", "").strip():
        files["README.md"] = (
            f"# {project_name}\n\n"
            "## Setup\n"
            "```bash\n"
            "python3 -m venv .venv\n"
            "source .venv/bin/activate\n"
            "python -m pip install -r requirements.txt\n"
            "```\n\n"
            "## Run\n"
            "```bash\n"
            "PORT=8000 python main.py\n"
            "```\n"
        )

    return files

def fallback_spec(project_name: str) -> Dict[str, Any]:
    # 최소 실행 가능한 FastAPI 스켈레톤
    return {
        "project_name": project_name,
        "summary": "Fallback spec because model output was invalid JSON.",
        "stack": {"language": "python", "framework": "fastapi", "server": "uvicorn"},
        "directories": [],
        "files": {},
    }

def call_ollama_chat(text: str) -> str:
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {
        "model": MODEL,
        "format": "json",  # ✅ 강제: JSON만 나오게
        "messages": [
            {"role": "system", "content": "Return ONLY valid JSON. No markdown. No commentary."},
            {"role": "user", "content": text},
        ],
        "stream": False,
        "options": {"temperature": 0.2},
    }
    r = requests.post(url, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return ((data.get("message", {}) or {}).get("content") or "").strip()


def repair_json_with_model(bad_json: str) -> str:
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {
        "model": MODEL,
        "format": "json",
        "messages": [
            {"role": "system", "content": "You fix invalid JSON. Output ONLY valid JSON."},
            {"role": "user", "content": f"Fix this into valid JSON only:\n\n{bad_json}"},
        ],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    r = requests.post(url, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return ((data.get("message", {}) or {}).get("content") or "").strip()


def repair_json_with_model(bad_json: str) -> str:
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {
        "model": MODEL,
        "format": "json",
        "messages": [
            {"role": "system", "content": "You fix invalid JSON. Output ONLY valid JSON."},
            {"role": "user", "content": f"Fix this into valid JSON only:\n\n{bad_json}"},
        ],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    r = requests.post(url, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return ((data.get("message", {}) or {}).get("content") or "").strip()


def parse_json_or_debug(raw: str) -> Dict[str, Any]:
    try:
        return json.loads(raw)

    except json.JSONDecodeError:
        # 1) save raw
        DEBUG_RAW_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        DEBUG_RAW_OUTPUT.write_text(raw + "\n", encoding="utf-8")

        # ===== Track A: simple auto-fix (no model call) =====
        fixed = try_close_braces(raw)
        if fixed != raw:
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass  # fall through to model repair

        # ===== 2) try repair once (model-based) =====
        repaired = repair_json_with_model(raw)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as e2:
            # save repaired too
            Path("examples/last_repaired_output.txt").write_text(repaired + "\n", encoding="utf-8")
            raise RuntimeError(
                "Model did not return valid JSON (even after repair). "
                "Saved raw to examples/last_raw_output.txt and repaired to examples/last_repaired_output.txt.\n"
                f"JSON error: {e2}"
            )


def normalize_requirements(content: str) -> str:
    """
    Remove stdlib modules and normalize lines.
    """
    kept: List[str] = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        # Extract package name for comparisons:
        # supports "pkg==x", "pkg>=x", "pkg<=x", "pkg~=x"
        name = line
        for sep in ("==", ">=", "<=", "~=", ">", "<"):
            if sep in name:
                name = name.split(sep, 1)[0]
                break
        name = name.strip().lower()

        if name in STD_LIB_BLOCKLIST:
            continue

        kept.append(line)

    return ("\n".join(kept).strip() + "\n") if kept else ""


def ensure_required_files(files: Dict[str, str]) -> Tuple[bool, List[str]]:
    present = set(files.keys())
    missing = [f for f in REQUIRED_FILES if f not in present]
    return (len(missing) == 0, missing)


def validate_and_fix_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    - Ensures schema keys exist
    - Sanitizes requirements.txt
    - Ensures required files exist (README.md, main.py, requirements.txt)
    - Adds minimal "Run" instructions to README if missing
    """
    if not isinstance(spec, dict):
        raise RuntimeError("Spec must be a JSON object")

    project_name = (spec.get("project_name") or "").strip()
    if not project_name:
        raise RuntimeError("Spec missing project_name")

    dirs = spec.get("directories") or []
    files = spec.get("files") or {}
    if not isinstance(dirs, list):
        raise RuntimeError("Spec directories must be a list")
    if not isinstance(files, dict):
        raise RuntimeError("Spec files must be an object")

    # requirements.txt sanitize
    if "requirements.txt" in files and isinstance(files["requirements.txt"], str):
        files["requirements.txt"] = normalize_requirements(files["requirements.txt"])

    # If required files are missing, inject safe defaults instead of failing.
    files = inject_required_files(files, project_name)
    spec["files"] = files

    # README run instructions (light-touch)
    readme = files.get("README.md", "")
    if isinstance(readme, str):
        lower = readme.lower()
        if "```" not in lower or ("python" not in lower and "pip" not in lower):
            files["README.md"] = readme.strip() + "\n\n## Run\n```bash\npython3 -m venv .venv\nsource .venv/bin/activate\npip install -r requirements.txt\npython3 main.py\n```\n"

    spec["files"] = files
    spec["directories"] = dirs
    spec["project_name"] = project_name
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
        if not isinstance(rel, str) or not isinstance(content, str):
            raise RuntimeError("Spec files must map strings to strings")
        p = (base / rel).resolve()
        if base_resolved not in p.parents and p != base_resolved:
            raise ValueError(f"Invalid file path escapes base: {rel}")
        safe_write_file(Path(p), content, force=force)


def build_generation_request(prompt: str, idea: str, last_error: str | None = None) -> str:
    """
    If previous attempt failed, add a short corrective instruction to the model.
    """
    correction = ""
    if last_error:
        correction = (
            "\n\nCORRECTION (must comply):\n"
            f"- Fix the following validation error: {last_error}\n"
            "- Output ONLY valid JSON.\n"
            "- Ensure required files exist at project root: README.md, main.py, requirements.txt.\n"
            "- Do NOT include stdlib modules like sqlite3 in requirements.\n"
        )
    return f"{prompt}\n\nPRODUCT IDEA:\n{idea}\n{correction}"

def generate_valid_spec(prompt: str, idea: str, forced_name: str | None = None) -> Dict[str, Any]:
    last_err: str | None = None

    # fallback name 결정 (모델이 망가져도 폴더는 고정)
    fallback_name = (forced_name or "archmind_project").strip() or "archmind_project"

    for attempt in range(1, MAX_RETRIES + 1):
        req = build_generation_request(prompt, idea, last_err)
        raw = call_ollama_chat(req)

        # 1) parse (with Track A inside parse_json_or_debug)
        try:
            spec = parse_json_or_debug(raw)
        except RuntimeError as e:
            print(f"[WARN] Invalid JSON from model. Using fallback spec. Details: {e}")
            spec = fallback_spec(project_name=fallback_name)

        # 2) validate + fix
        try:
            spec = validate_and_fix_spec(spec)
            return spec
        except Exception as e:
            last_err = str(e)
            print(f"[WARN] Spec validation failed (attempt {attempt}/{MAX_RETRIES}): {e}")

    raise RuntimeError(f"Failed to generate valid spec after {MAX_RETRIES} attempts: {last_err}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default=None, help="Override project name (folder name)")
    ap.add_argument("--force", action="store_true", help="Overwrite existing generated files")
    ap.add_argument("--out", default=str(GENERATED_ROOT), help="Output root directory (default: generated/)")
    args = ap.parse_args()

    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    idea = INPUT_PATH.read_text(encoding="utf-8")

    spec = generate_valid_spec(prompt, idea, forced_name=args.name)

    if args.name:
        spec["project_name"] = args.name

    project_name = (args.name.strip() if args.name else spec["project_name"])
    dirs: List[str] = spec.get("directories", [])
    files: Dict[str, str] = spec.get("files", {})

    out_root = Path(args.out)
    project_root = out_root / project_name

    if project_root.exists() and not args.force:
        raise FileExistsError(
            f"Project folder already exists: {project_root}\n"
            f"Use --force to overwrite files, or delete the folder."
        )

    project_root.mkdir(parents=True, exist_ok=True)

    ensure_dirs(project_root, dirs)
    ensure_files(project_root, files, force=args.force)

    # Save spec for reproducibility (always overwrite spec)
    spec_path = project_root / "archmind_spec.json"
    safe_write_file(spec_path, json.dumps(spec, ensure_ascii=False, indent=2), force=True)

    print(f"[OK] Generated project: {project_root}")
    print(f"[OK] Model={MODEL}, files={len(files)}, dirs={len(dirs)}")
    print("\nNext steps:")
    print(f"  cd {project_root}")
    print("  python3 -m venv .venv && source .venv/bin/activate")
    print("  python -m pip install -r requirements.txt")
    print("  PORT=8000 python main.py")


if __name__ == "__main__":
    main()