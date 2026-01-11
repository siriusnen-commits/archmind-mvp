# src/archmind/templates/fastapi.py
from __future__ import annotations

from typing import Dict


RUNTIME_REQUIREMENTS = [
    "fastapi==0.115.0",
    "uvicorn[standard]==0.30.6",
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


def enforce_fastapi_runtime(files: Dict[str, str], project_name: str) -> Dict[str, str]:
    # 1) requirements: merge 방식으로 강제
    files["requirements.txt"] = _merge_requirements(files.get("requirements.txt", ""))

    # 2) main.py: 없으면 생성(있으면 존중)
    if "main.py" not in files or not files["main.py"].strip():
        files["main.py"] = (
            "import os\n"
            "from fastapi import FastAPI\n\n"
            "app = FastAPI()\n\n"
            "@app.get('/health')\n"
            "def health():\n"
            "    return {'status': 'ok'}\n\n"
            "@app.get('/')\n"
            "def root():\n"
            "    return {'status': 'ok'}\n\n"
            "if __name__ == '__main__':\n"
            "    import uvicorn\n"
            "    host = os.getenv('HOST', '0.0.0.0')\n"
            "    port = int(os.getenv('PORT', '8000'))\n"
            "    uvicorn.run('main:app', host=host, port=port, reload=True)\n"
        )

    # 3) README: 비어있으면 생성
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
            "```\n\n"
            "## Test\n"
            "```bash\n"
            "curl -s http://localhost:8000/health\n"
            "```\n"
        )

    return files