from __future__ import annotations
from pathlib import Path
import os, json, requests
from typing import Any, Dict, List

OLLAMA_BASE_URL = os.getenv("ARCHMIND_OLLAMA_BASE_URL", "http://localhost:11434")
MODEL = os.getenv("ARCHMIND_MODEL", "llama3:latest")
TIMEOUT = 240

STD_LIB_BLOCKLIST = {
    "sqlite3","json","os","sys","pathlib","datetime","time","re","typing","subprocess","logging","uuid","math","random"
}

def call_ollama_json(prompt: str) -> Dict[str, Any]:
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {
        "model": MODEL,
        "format": "json",
        "messages": [
            {"role": "system", "content": "Return ONLY valid JSON. No markdown. No commentary."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.2},
    }
    r = requests.post(url, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    msg = data.get("message") or {}
    return json.loads((msg.get("content") or "").strip())


def normalize_requirements(content: str) -> str:
    kept = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
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


def inject_required_files(files: Dict[str, str], project_name: str) -> Dict[str, str]:
    req = files.get("requirements.txt", "").strip()
    if not req:
        files["requirements.txt"] = (
            "flask==2.0.1\n"
            "Werkzeug==2.0.3\n"
            "Jinja2==3.0.3\n"
            "itsdangerous==2.0.1\n"
            "click==8.0.4\n"
        )

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


def safe_write(path: Path, content: str, force: bool):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite: {path} (use --force)")
    path.write_text(content, encoding="utf-8")


def generate_project(prompt_text: str, idea: str, out_root: Path, force: bool) -> Path:
    req = f"{prompt_text}\n\nPRODUCT IDEA:\n{idea}\n"
    spec = call_ollama_json(req)

    project_name = (spec.get("project_name") or "").strip() or "archmind_project"
    dirs = spec.get("directories") or []
    files = spec.get("files") or {}

    if "requirements.txt" in files:
        files["requirements.txt"] = normalize_requirements(files["requirements.txt"])

    files = inject_required_files(files, project_name)
    assert isinstance(files, dict)

    project_root = out_root / project_name
    if project_root.exists() and not force:
        raise FileExistsError(f"Project folder exists: {project_root}")

    project_root.mkdir(parents=True, exist_ok=True)

    # dirs
    for d in dirs:
        (project_root / d).mkdir(parents=True, exist_ok=True)

    # files
    for rel, content in files.items():
        safe_write(project_root / rel, content, force=force)

    # spec
    safe_write(project_root / "archmind_spec.json", json.dumps(spec, ensure_ascii=False, indent=2), force=True)

    return project_root