# src/archmind/templates/fastapi.py
from __future__ import annotations

from typing import Dict


RUNTIME_REQUIREMENTS = [
    "fastapi==0.115.0",
    "uvicorn[standard]==0.30.6",
    "pytest==9.0.2",
    "httpx==0.27.0",
]


def _merge_requirements(existing: str) -> str:
    """
    기존 requirements.txt가 있으면 유지하면서,
    fastapi/uvicorn만 '반드시' 포함되도록 합친다.
    """
    existing_lines = [ln.strip() for ln in (existing or "").splitlines() if ln.strip()]
    existing_set = set(existing_lines)

    # 필요한 것만 추가
    for req in RUNTIME_REQUIREMENTS:
        if req not in existing_set:
            existing_lines.append(req)

    return "\n".join(existing_lines) + "\n"


def _normalize_template_path(raw: str) -> str:
    text = str(raw or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    text = text.lstrip("/")
    if not text:
        return ""
    parts: list[str] = []
    for part in text.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _collect_existing_requirements(files: Dict[str, str]) -> str:
    chunks: list[str] = []
    for key in list(files.keys()):
        normalized = _normalize_template_path(key)
        if normalized.casefold() == "requirements.txt":
            value = files.get(key)
            if isinstance(value, str) and value.strip():
                chunks.append(value)
            if key != "requirements.txt":
                files.pop(key, None)
    return "\n".join(chunks)


def enforce_fastapi_runtime(files: Dict[str, str], project_name: str) -> Dict[str, str]:
    # 1) requirements: merge 방식으로 강제
    existing_requirements = _collect_existing_requirements(files)
    files["requirements.txt"] = _merge_requirements(existing_requirements)

    # 2) pytest-ready baseline scaffold
    if "app/__init__.py" not in files:
        files["app/__init__.py"] = ""
    if "app/core/__init__.py" not in files:
        files["app/core/__init__.py"] = ""
    if "app/core/settings.py" not in files or not files["app/core/settings.py"].strip():
        files["app/core/settings.py"] = (
            "from __future__ import annotations\n\n"
            "from pydantic_settings import BaseSettings, SettingsConfigDict\n\n\n"
            "class Settings(BaseSettings):\n"
            "    model_config = SettingsConfigDict(env_file=(\".env\", \"backend/.env\"), extra=\"ignore\")\n\n"
            f"    app_name: str = \"{project_name}\"\n"
            "    app_port: int = 8000\n"
            "    backend_base_url: str = \"http://127.0.0.1:8000\"\n"
            "    cors_allow_origins: str = \"http://localhost:3000,http://127.0.0.1:3000\"\n\n\n"
            "settings = Settings()\n"
        )
    if "app/main.py" not in files or not files["app/main.py"].strip():
        files["app/main.py"] = (
            "from fastapi import FastAPI\n"
            "from fastapi.middleware.cors import CORSMiddleware\n\n"
            "from app.core.settings import settings\n\n"
            "app = FastAPI(title=settings.app_name)\n"
            "app.add_middleware(\n"
            "    CORSMiddleware,\n"
            "    allow_origins=[\"*\"],\n"
            "    allow_credentials=True,\n"
            "    allow_methods=[\"*\"],\n"
            "    allow_headers=[\"*\"],\n"
            ")\n\n"
            "@app.get('/health')\n"
            "def health() -> dict[str, str]:\n"
            "    return {'status': 'ok'}\n\n"
            "@app.get('/')\n"
            "def root() -> dict[str, str]:\n"
            "    return {'status': 'ok'}\n"
        )
    if "tests/test_health.py" not in files or not files["tests/test_health.py"].strip():
        files["tests/test_health.py"] = (
            "from fastapi.testclient import TestClient\n\n"
            "from app.main import app\n\n"
            "client = TestClient(app)\n\n"
            "def test_health() -> None:\n"
            "    res = client.get('/health')\n"
            "    assert res.status_code == 200\n"
            "    assert res.json() == {'status': 'ok'}\n"
        )
    if "pytest.ini" not in files or not files["pytest.ini"].strip():
        files["pytest.ini"] = (
            "[pytest]\n"
            "addopts = -q\n"
            "testpaths = tests\n"
        )

    # 3) entrypoint wrapper: 없으면 생성(있으면 존중)
    if "main.py" not in files or not files["main.py"].strip():
        files["main.py"] = (
            "import os\n\n"
            "from app.main import app\n\n"
            "if __name__ == '__main__':\n"
            "    import uvicorn\n\n"
            "    host = os.getenv('HOST', '0.0.0.0')\n"
            "    port = int(os.getenv('APP_PORT', os.getenv('PORT', '8000')))\n"
            "    uvicorn.run('app.main:app', host=host, port=port, reload=True)\n"
        )

    # 4) README: 비어있으면 생성
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
            "python -m uvicorn app.main:app --reload --host 0.0.0.0 --port ${APP_PORT:-${PORT:-8000}}\n"
            "```\n\n"
            "## Test\n"
            "```bash\n"
            "python -m pytest -q\n"
            "```\n"
        )
    if ".env.example" not in files or not files[".env.example"].strip():
        files[".env.example"] = (
            f"APP_NAME={project_name}\n"
            "APP_PORT=8000\n"
            "BACKEND_BASE_URL=http://127.0.0.1:8000\n"
            "CORS_ALLOW_ORIGINS=http://localhost:3000,http://127.0.0.1:3000\n"
        )

    return files
